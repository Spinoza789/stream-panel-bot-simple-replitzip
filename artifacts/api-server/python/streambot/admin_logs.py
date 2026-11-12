"""Owner logs built from our own records: who created or extended which account, and every reseller credit movement.

Nothing here contacts the IPTV panel. Balances before and after are replayed from the
reseller ledger, which records every change to a reseller's credits.
"""
import json
import time

from .service import CheckoutError

PAGE = 25


class AdminLogs:
    def __init__(self, service):
        self.service = service; self.store = service.store; self.accounts = service.accounts

    def _check(self, actor, reseller, search, page):
        self.service.resellers.finance.admin(actor)
        if ((reseller is not None and (type(reseller) is not int or reseller <= 0)) or not isinstance(search, str) or len(search) > 80
                or type(page) is not int or not 1 <= page <= 100000):
            raise CheckoutError('Invalid log filter.')

    def _resellers(self, db):
        if not self.service.resellers.ready: return {}
        return {row['id']: dict(telegramId=int(row['telegram_id']), username=row['username'] or '')
                for row in db.execute('SELECT id,telegram_id,username FROM rs_resellers ORDER BY created_at,id').fetchall()}

    def _ledger(self, db):
        """Every ledger row oldest first, with the reseller's balance after it."""
        if not self.service.resellers.ready: return []
        balance = {}; rows = []
        # Timestamps are whole seconds and ids are random, so two movements in the same second need the
        # table's own insertion order to replay correctly. Ledger rows are never updated or deleted.
        physical = 'ctid' if type(self.store).__name__ == 'PostgresStore' else 'rowid'
        for raw in db.execute('SELECT * FROM rs_ledger ORDER BY created_at,' + physical).fetchall():
            row = dict(raw)
            row['before'] = balance.get(row['reseller_id'], 0)
            balance[row['reseller_id']] = row['after'] = row['before'] + int(row['movement'])
            row['sequence'] = len(rows)
            rows.append(row)
        return rows

    @staticmethod
    def _page(items, page, **extra):
        return dict(items=items[(page - 1) * PAGE:page * PAGE], page=page, pageSize=PAGE, total=len(items), **extra)

    @staticmethod
    def _package(months, connections, adult):
        if not months: return '24-hour trial'
        return '%d month%s · %d device%s%s' % (months, '' if months == 1 else 's', connections, '' if connections == 1 else 's',
                                               ' · with adult' if adult else '')

    # ---- activity: accounts created and extended -----------------------------------------
    def activity(self, actor, *, source='', reseller=None, search='', page=1):
        self._check(actor, reseller, search, page)
        if source not in ('', 'retail', 'reseller'): raise CheckoutError('Invalid log filter.')
        items = []
        with self.store.connection() as db:
            resellers = self._resellers(db)
            if resellers and source != 'retail':
                charged = {row['reference'][len('operation:'):]: row for row in self._ledger(db) if row['reference'].startswith('operation:')}
                logins = {row['id']: row['credentials'] for row in db.execute('SELECT id,credentials FROM rs_subscriptions').fetchall()}
                for op in db.execute('SELECT * FROM rs_operations ORDER BY created_at DESC,id DESC').fetchall():
                    owner = resellers.get(op['reseller_id'])
                    if not owner or (reseller and owner['telegramId'] != reseller): continue
                    credentials = self.store.unseal(logins.get(op['result_id'] or op['target_id'])) or {}
                    entry = charged.get(op['id'])
                    items.append(dict(
                        id=op['id'], date=int(op['created_at']), sequence=entry['sequence'] if entry else 0, source='reseller', resellerTelegramId=owner['telegramId'], resellerUsername=owner['username'],
                        customer=op['customer_ref'] or '', action=op['operation_type'], status=op['status'],
                        package=self._package(int(op['months']), int(op['connections']), bool(op['adult'])),
                        accountUsername=str(credentials.get('username') or ''), accountPassword=str(credentials.get('password') or ''),
                        creditCost=int(op['credit_cost']), creditsBefore=entry['before'] if entry else None, creditsAfter=entry['after'] if entry else None))
            if source != 'reseller' and not reseller:
                owners = self.accounts.owners(db); names = self.accounts.usernames(db)
                for row in db.execute("SELECT * FROM orders WHERE status='fulfilled' AND credentials IS NOT NULL ORDER BY created_at DESC,id DESC").fetchall():
                    plan = json.loads(row['plan_json'])
                    if plan.get('reseller_purchase'): continue
                    credentials = self.store.unseal(row['credentials']) or {}
                    if not credentials.get('username'): continue
                    owner = row['telegram_id'] or owners.get(row['id'])
                    name = names.get(int(owner), '') if owner else ''
                    items.append(dict(
                        id=row['id'], date=int(row['created_at']), sequence=0, source='retail', resellerTelegramId=0, resellerUsername='',
                        customer=('@' + name + ' · ' if name else '') + (str(owner) if owner else 'Website checkout'),
                        action='extend' if plan.get('renew_of') else 'trial' if row['kind'] == 'trial' else 'create', status='succeeded',
                        package=plan.get('name', 'Membership') + (' · ' + plan['detail'] if row['kind'] != 'trial' and plan.get('detail') else '')
                                + (' · added by owner' if plan.get('admin_grant') else ''),
                        accountUsername=str(credentials['username']), accountPassword=str(credentials.get('password') or ''),
                        creditCost=0, creditsBefore=None, creditsAfter=None))
            listing = [dict(telegramId=r['telegramId'], username=r['username']) for r in resellers.values()]
        needle = search.strip().casefold().lstrip('@')
        if needle:
            items = [i for i in items if needle in ' '.join(str(i[k]) for k in (
                'id', 'resellerTelegramId', 'resellerUsername', 'customer', 'action', 'package', 'accountUsername', 'status')).casefold()]
        # Within one second, follow the order the credits were actually charged in.
        items.sort(key=lambda i: (i['date'], i.pop('sequence'), i['id']), reverse=True)
        return self._page(items, page, resellers=listing)

    # ---- credits: every movement on a reseller's balance ---------------------------------
    @staticmethod
    def _kind(reference):
        return 'usage' if reference.startswith('operation:') else 'purchase' if reference.startswith('purchase:') else 'adjustment'

    def credits(self, actor, *, scope='', reseller=None, search='', page=1):
        """scope '' = top-ups and adjustments (what was added or taken by hand); 'usage' = credits spent; 'all' = both."""
        self._check(actor, reseller, search, page)
        if scope not in ('', 'usage', 'all'): raise CheckoutError('Invalid log filter.')
        items = []
        with self.store.connection() as db:
            resellers = self._resellers(db)
            for row in self._ledger(db):
                owner = resellers.get(row['reseller_id']); kind = self._kind(row['reference'])
                if not owner or (reseller and owner['telegramId'] != reseller): continue
                if (scope == '' and kind == 'usage') or (scope == 'usage' and kind != 'usage'): continue
                admin = row['administrator']
                by = ('Payment verified' if kind == 'purchase' else 'Automatic') if admin is None else 'Owner (website)' if int(admin) == 0 else 'Admin ' + str(admin)
                items.append(dict(id=row['id'], date=int(row['created_at']), resellerTelegramId=owner['telegramId'], resellerUsername=owner['username'],
                                  admin=by, kind=kind, movement=int(row['movement']), reason=row['reason'] or '',
                                  balanceBefore=row['before'], balanceAfter=row['after']))
            listing = [dict(telegramId=r['telegramId'], username=r['username']) for r in resellers.values()]
        needle = search.strip().casefold().lstrip('@')
        if needle:
            items = [i for i in items if needle in ' '.join(str(i[k]) for k in ('id', 'resellerTelegramId', 'resellerUsername', 'admin', 'kind', 'reason')).casefold()]
        items.reverse()  # newest first, keeping ledger order within the same second
        return self._page(items, page, resellers=listing, added=sum(i['movement'] for i in items if i['movement'] > 0),
                          removed=-sum(i['movement'] for i in items if i['movement'] < 0))
