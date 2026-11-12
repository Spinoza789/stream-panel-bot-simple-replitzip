"""Owner view of every delivered account: retail trials and memberships plus reseller subscriptions and trials.

The owner sees the login details here, can add a complimentary membership for a Telegram
user, and can remove a subscription from the books. Nothing in this module talks to the
IPTV panel: removing a subscription never cancels the line there.
"""
import json
import re
import secrets
import time

from .reseller_provider import provider_time
from .service import CheckoutError
from .store import digest

PAGE = 25
USERNAME = r'[A-Za-z0-9_]{1,64}'
USERNAME_KEY = 'tg_username:'
REMOVED_KEY = 'admin_removed:'
DAY = 86400


def remember_username(store, cache, sender):
    """Keep the customer's current Telegram @username beside their numeric ID. Called by the bot on every update."""
    uid, name = sender.get('id'), sender.get('username')
    if type(uid) is not int or uid <= 0 or not isinstance(name, str) or not re.fullmatch(USERNAME, name): return
    if cache.get(uid) == name: return
    try:
        if store.metadata(USERNAME_KEY + str(uid)) != name: store.metadata(USERNAME_KEY + str(uid), name)
    except Exception: return  # never let bookkeeping break a customer's message
    if len(cache) > 5000: cache.clear()
    cache[uid] = name


class AdminSubscriptions:
    def __init__(self, service):
        self.service = service; self.store = service.store; self.config = service.config

    # ---- shared helpers ------------------------------------------------------------------
    def admin(self, actor):
        self.service.resellers.finance.admin(actor)

    def audit(self, db, actor, action, subject, reason, details=None):
        if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 500:
            raise CheckoutError('A reason of 3–500 characters is required.')
        if self.service.resellers.ready:
            self.service.resellers.finance.audit(db, actor, action, subject, reason, details)
        else:  # no reseller tables in this database: keep the audit entry sealed in metadata instead
            entry = dict(actor=str(actor), action=action, subject=str(subject), reason=reason.strip(), details=details or {}, at=int(time.time()))
            db.execute('INSERT INTO metadata VALUES(?,?)', ('admin_audit:' + secrets.token_hex(12), self.store.seal(entry)))

    def usernames(self, db, ids=None):
        """Telegram ID -> @username from the bot's own sightings, then reseller and ticket records.

        Pass `ids` to look up just those customers (one page of orders) instead of everyone.
        """
        names = {}
        if ids is not None:
            ids = sorted({int(i) for i in ids})
            if not ids: return names
        marks = ','.join('?' * len(ids)) if ids else ''
        try:
            for row in db.execute("SELECT telegram_id,username FROM tk_tickets WHERE username!=''" +
                                  (' AND telegram_id IN (' + marks + ')' if ids else '') + ' ORDER BY updated_at', tuple(ids or ())).fetchall():
                names[int(row['telegram_id'])] = row['username']
        except Exception: pass
        if self.service.resellers.ready:
            for row in db.execute("SELECT telegram_id,username FROM rs_resellers WHERE username!=''" +
                                  (' AND telegram_id IN (' + marks + ')' if ids else ''), tuple(ids or ())).fetchall():
                names[int(row['telegram_id'])] = row['username']
        if ids: rows = db.execute('SELECT key,value FROM metadata WHERE key IN (' + marks + ')', tuple(USERNAME_KEY + str(i) for i in ids)).fetchall()
        else: rows = db.execute('SELECT key,value FROM metadata WHERE key LIKE ?', (USERNAME_KEY + '%',)).fetchall()
        for row in rows:
            uid = row['key'][len(USERNAME_KEY):]
            if uid.isdigit() and re.fullmatch(USERNAME, row['value'] or ''): names[int(uid)] = row['value']
        return names

    def username_ids(self, db, text):
        """Telegram IDs whose known @username matches the search text exactly (case-insensitive)."""
        needle = text.strip().lstrip('@').casefold()
        if not re.fullmatch(USERNAME, needle): return []
        return [uid for uid, name in self.usernames(db).items() if name.casefold() == needle]

    def owners(self, db, order_ids=None):
        """Order ID -> Telegram ID of the customer the order is linked to."""
        if order_ids is None:
            return {row['order_id']: int(row['telegram_id']) for row in db.execute('SELECT order_id,telegram_id FROM account_links').fetchall()}
        result = {}
        for oid in order_ids:
            row = db.execute('SELECT telegram_id FROM account_links WHERE order_id=?', (oid,)).fetchone()
            if row: result[oid] = int(row['telegram_id'])
        return result

    def removed(self, db, order_id=None):
        if order_id is not None:
            row = db.execute('SELECT value FROM metadata WHERE key=?', (REMOVED_KEY + order_id,)).fetchone()
            return self.store.unseal(row['value']) if row else None
        return {row['key'][len(REMOVED_KEY):] for row in db.execute('SELECT key FROM metadata WHERE key LIKE ?', (REMOVED_KEY + '%',)).fetchall()}

    def expiry(self, created_at, credentials, months=None):
        value = (credentials or {}).get('expires_at')
        if value:
            try: return provider_time(value, self.config.get('provider_timezone') or 'Europe/London')
            except Exception: pass
        return created_at + (DAY if months is None else max(1, months) * 30 * DAY)

    def account(self, created_at, credentials, months=None):
        """Login details of a delivered account, or None while there is no confirmed login."""
        credentials = credentials or {}
        if not isinstance(credentials.get('username'), str) or not credentials['username']: return None
        return dict(username=credentials['username'], password=str(credentials.get('password') or ''),
                    serverUrl=str(credentials.get('server_url') or ''), panelId=str(credentials.get('panel_id') or ''),
                    expiresAt=self.expiry(created_at, credentials, months))

    # ---- listing -------------------------------------------------------------------------
    def _retail_groups(self, db):
        """Delivered retail orders grouped by panel login: a renewal or trial upgrade extends the same account."""
        gone = self.removed(db); owners = self.owners(db); groups = {}
        rows = db.execute("SELECT * FROM orders WHERE status='fulfilled' AND credentials IS NOT NULL ORDER BY created_at,id").fetchall()
        for row in rows:
            if row['id'] in gone: continue
            plan = json.loads(row['plan_json'])
            if plan.get('reseller_purchase'): continue
            credentials = self.store.unseal(row['credentials']) or {}
            months = None if row['kind'] == 'trial' else int(plan.get('months') or 1)
            account = self.account(row['created_at'], credentials, months)
            if not account: continue
            owner = row['telegram_id'] or owners.get(row['id'])
            groups.setdefault(account['panelId'] or row['id'], []).append(dict(
                id=row['id'], kind=row['kind'], created_at=row['created_at'], plan=plan, account=account,
                telegram_id=int(owner) if owner else None))
        return groups

    def _retail_items(self, db, names):
        now = int(time.time()); items = []
        for members in self._retail_groups(db).values():
            root, latest = members[0], max(members, key=lambda m: m['account']['expiresAt'])
            paid = [m for m in members if m['kind'] == 'paid']
            owner = next((m['telegram_id'] for m in members if m['telegram_id']), None)
            plan = (paid[-1] if paid else root)['plan']
            items.append(dict(
                id=root['id'], source='retail', kind='paid' if paid else 'trial',
                status='active' if latest['account']['expiresAt'] > now else 'expired',
                customer=str(owner) if owner else 'Website checkout', telegramId=owner or 0,
                telegramUsername=names.get(owner, '') if owner else '',
                resellerTelegramId=0, resellerUsername='', customerRef='',
                accountUsername=latest['account']['username'], accountPassword=latest['account']['password'],
                serverUrl=latest['account']['serverUrl'],
                plan=plan.get('name', plan.get('id', 'Membership')) + ((' · ' + plan['detail']) if paid and plan.get('detail') else ''),
                connections=int(plan.get('connections') or 1), createdAt=root['created_at'],
                expiresAt=latest['account']['expiresAt'], orderIds=[m['id'] for m in members]))
        return items

    def _reseller_items(self, db, names):
        if not self.service.resellers.ready: return []
        now = int(time.time()); items = []
        try:
            rows = db.execute('SELECT s.*,r.telegram_id AS reseller_telegram_id,r.username AS reseller_username FROM rs_subscriptions s '
                              'JOIN rs_resellers r ON r.id=s.reseller_id WHERE s.deleted_at IS NULL ORDER BY s.created_at DESC,s.id DESC').fetchall()
        except Exception:
            raise CheckoutError('Reseller subscriptions cannot be listed until the latest database schema is published.') from None
        for row in rows:
            credentials = self.store.unseal(row['credentials']) or {}
            status = 'expired' if int(row['expires_at']) <= now and row['status'] == 'active' else row['status']
            items.append(dict(
                id=row['id'], source='reseller', kind=row['kind'], status=status,
                customer=row['customer_ref'] or (row['contact'] or ''), telegramId=0, telegramUsername='',
                resellerTelegramId=int(row['reseller_telegram_id']),
                resellerUsername=row['reseller_username'] or names.get(int(row['reseller_telegram_id']), ''),
                customerRef=' · '.join(v for v in (row['customer_ref'], row['contact']) if v),
                accountUsername=str(credentials.get('username') or ''), accountPassword=str(credentials.get('password') or ''),
                serverUrl=str(credentials.get('server_url') or ''),
                plan='24-hour trial' if row['kind'] == 'trial' else 'Reseller subscription',
                connections=int(row['connections']), createdAt=int(row['created_at']), expiresAt=int(row['expires_at']), orderIds=[]))
        return items

    def list(self, actor, *, source='', kind='', status='', reseller=None, search='', page=1):
        self.admin(actor)
        if (source not in ('', 'retail', 'reseller') or kind not in ('', 'trial', 'paid') or status not in ('', 'active', 'expired')
                or not isinstance(search, str) or len(search) > 80 or type(page) is not int or not 1 <= page <= 100000):
            raise CheckoutError('Invalid subscription filter.')
        with self.store.connection() as db:
            names = self.usernames(db)
            items = [] if source == 'reseller' or reseller else self._retail_items(db, names)
            if source != 'retail': items += self._reseller_items(db, names)
        needle = search.strip().casefold().lstrip('@')
        def keep(item):
            if kind and item['kind'] != kind: return False
            if status and (item['status'] == 'active') != (status == 'active'): return False
            if reseller and item['resellerTelegramId'] != reseller: return False
            if not needle: return True
            text = ' '.join(str(item[k]) for k in ('id', 'customer', 'telegramUsername', 'resellerTelegramId', 'resellerUsername',
                                                   'customerRef', 'accountUsername', 'plan')) + ' ' + ' '.join(item['orderIds'])
            return needle in text.casefold()
        items = sorted((item for item in items if keep(item)), key=lambda item: (item['createdAt'], item['id']), reverse=True)
        counts = dict(total=len(items), active=sum(1 for i in items if i['status'] == 'active'), trials=sum(1 for i in items if i['kind'] == 'trial'))
        chosen = items[(page - 1) * PAGE:page * PAGE]
        for item in chosen: item.pop('orderIds')
        return dict(items=chosen, page=page, pageSize=PAGE, **counts)

    def groups(self, actor, *, kind='', reseller=None, search=''):
        """Accounts still running, grouped by who sold them (direct first, then each reseller), with everything
        that has expired or been disabled gathered separately for the bottom of the page."""
        self.admin(actor)
        if kind not in ('', 'trial', 'paid') or not isinstance(search, str) or len(search) > 80 or (reseller is not None and (type(reseller) is not int or reseller <= 0)):
            raise CheckoutError('Invalid subscription filter.')
        with self.store.connection() as db:
            names = self.usernames(db)
            items = [] if reseller else self._retail_items(db, names)
            items += self._reseller_items(db, names)
        needle = search.strip().casefold().lstrip('@')
        def keep(item):
            if kind and item['kind'] != kind: return False
            if reseller and item['resellerTelegramId'] != reseller: return False
            if not needle: return True
            text = ' '.join(str(item[k]) for k in ('id', 'customer', 'telegramUsername', 'resellerTelegramId', 'resellerUsername',
                                                   'customerRef', 'accountUsername', 'plan')) + ' ' + ' '.join(item['orderIds'])
            return needle in text.casefold()
        items = sorted((item for item in items if keep(item)), key=lambda item: (item['createdAt'], item['id']), reverse=True)
        groups = {}; expired = []
        for item in items:
            item.pop('orderIds')
            if item['status'] != 'active': expired.append(item); continue
            key = 'direct' if item['source'] == 'retail' else 'reseller:%d' % item['resellerTelegramId']
            groups.setdefault(key, dict(key=key, source=item['source'], resellerTelegramId=item['resellerTelegramId'],
                                        resellerUsername=item['resellerUsername'], items=[]))['items'].append(item)
        ordered = sorted(groups.values(), key=lambda g: (g['source'] != 'retail', (g['resellerUsername'] or '~').casefold(), g['resellerTelegramId']))
        return dict(groups=ordered, expired=expired, total=len(items), active=len(items) - len(expired))

    # ---- add: a complimentary membership for a Telegram user ---------------------------------
    def add(self, actor, telegram_id, plan_id, reason):
        """Queue a membership without payment. The provisioning worker creates the account and the bot delivers the login."""
        self.admin(actor)
        if type(telegram_id) is not int or not 0 < telegram_id < 2 ** 63:
            raise CheckoutError('Enter the customer’s numeric Telegram ID.')
        if self.config['mode'] == 'live' and not self.config.get('panel_writes'):
            raise CheckoutError('Panel account creation is switched off, so no account can be created. Nothing was added.')
        if plan_id == 'trial': return self._add_trial(actor, telegram_id, reason)
        plan = next((p for p in self.config.get('plans', []) if p['id'] == plan_id and p.get('package_id')), None) if isinstance(plan_id, str) else None
        if not plan: raise CheckoutError('Choose a plan.')
        now = int(time.time()); order_id = secrets.token_hex(12)
        granted = dict(plan, admin_grant=dict(at=now))
        granted.pop('reseller_purchase', None)
        asset = dict(id='admin', symbol='', network='none', decimals=0)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            busy = db.execute("SELECT o.id FROM orders o JOIN account_links a ON a.order_id=o.id "
                              "WHERE a.telegram_id=? AND o.kind='paid' AND o.status IN ('paid','provisioning')", (telegram_id,)).fetchone()
            if busy: raise CheckoutError('This customer already has an account being prepared (order ' + busy[0] + '). Wait for it to finish.')
            self.audit(db, actor, 'subscription_add', telegram_id, reason, dict(order_id=order_id, plan=plan['id']))
            db.execute('INSERT INTO orders(id,token_hash,kind,telegram_id,plan_json,asset_json,amount_units,created_at,expires_at,status,message) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (order_id, digest(secrets.token_urlsafe(32)), 'paid', None, json.dumps(granted), json.dumps(asset), '0', now, now + 3600,
                        'paid', 'Membership added by support. Preparing your account.'))
            db.execute('INSERT INTO account_links VALUES(?,?)', (telegram_id, order_id))
            db.execute('INSERT INTO metadata VALUES(?,?)', ('tg_order:' + order_id, '1'))
        return order_id

    def _add_trial(self, actor, telegram_id, reason):
        """The customer's one 24-hour trial, started by the owner. The bot delivers the login like any other trial."""
        with self.store.connection() as db:
            existing = db.execute('SELECT id FROM orders WHERE telegram_id=?', (telegram_id,)).fetchone()
            if existing: raise CheckoutError('This customer has already had their free trial (order ' + existing[0] + '). Add a subscription instead.')
            db.execute('BEGIN IMMEDIATE')
            self.audit(db, actor, 'trial_add', telegram_id, reason, {})
        plan = dict(id='trial', name='24-hour trial', package_id=str(self.config['trial_package_id']), admin_grant=dict(at=int(time.time())))
        try:  # the owner is not held to the public daily trial allowance
            _, order = self.store.create(plan, dict(id='trial', network='none', decimals=0), 0, telegram_id=telegram_id, daily_limit=10 ** 9)
        except ValueError as exc: raise CheckoutError(str(exc)) from None
        return order['id']

    # ---- delete ----------------------------------------------------------------------------
    def delete(self, actor, source, sid, reason):
        """Take a subscription off the books. Records stay for reports and trial eligibility; the panel line is not touched."""
        self.admin(actor)
        if not isinstance(sid, str) or not re.fullmatch(r'[a-f0-9]{24}', sid): raise CheckoutError('Subscription not found.')
        now = int(time.time())
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if source == 'reseller':
                if not self.service.resellers.ready: raise CheckoutError('Subscription not found.')
                row = db.execute('SELECT id,reseller_id,provider_id FROM rs_subscriptions WHERE id=? AND deleted_at IS NULL', (sid,)).fetchone()
                if not row: raise CheckoutError('Subscription not found. It may already have been deleted.')
                self.audit(db, actor, 'subscription_delete', sid, reason, dict(source='reseller', provider_id=row['provider_id']))
                db.execute('UPDATE rs_subscriptions SET deleted_at=? WHERE id=? AND deleted_at IS NULL', (now, sid))
                return 1
            if source != 'retail': raise CheckoutError('Subscription not found.')
            members = next((g for g in self._retail_groups(db).values() if any(m['id'] == sid for m in g)), None)
            if not members: raise CheckoutError('Subscription not found. It may already have been deleted.')
            self.audit(db, actor, 'subscription_delete', sid, reason, dict(source='retail', orders=[m['id'] for m in members]))
            for member in members:
                marker = dict(at=now, reason=reason.strip(), telegram_id=member['telegram_id'], kind=member['kind'])
                db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', (REMOVED_KEY + member['id'], self.store.seal(marker)))
                if member['kind'] == 'paid':
                    # The customer no longer sees this membership in the bot. A trial stays tied to its
                    # Telegram ID so the one-trial-per-user rule still holds.
                    db.execute('DELETE FROM account_links WHERE order_id=?', (member['id'],))
                    db.execute('DELETE FROM metadata WHERE key=?', ('tg_order:' + member['id'],))
            return len(members)
