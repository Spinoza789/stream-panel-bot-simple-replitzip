"""Private gateway-authenticated operations, using the bot's authoritative store."""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from types import SimpleNamespace

from flask import Blueprint, jsonify, request
from .config import display_units
from .service import CheckoutError
from .trial_recovery import TrialRecovery
from .store import digest


WARNING = ('Verify from provisioning logs that account creation never started. '
           'Missing saved credentials alone are not proof. If a request may have '
           'been submitted, cancel and reconcile the existing panel account. '
           'Confirmation queues this original trial only; it may create one account.')
ACTOR_PATTERN = r'(?:replit|local):[A-Za-z0-9_-]{1,128}:[a-f0-9]{64}'
NONCE_PRUNE_SQL = 'DELETE FROM metadata WHERE key LIKE ? AND value<?'


class WebTrialRecovery(TrialRecovery):
    """Reuse the Telegram recovery transaction without impersonating a Telegram ID."""
    def __init__(self, service):
        super().__init__(SimpleNamespace(service=service, store=service.store))

    def admin(self, actor):
        if not isinstance(actor, str) or not re.fullmatch(ACTOR_PATTERN, actor):
            raise CheckoutError('Verified website owner session required.')

    def key(self, actor):
        return 'web_trial_recovery:' + digest(actor)

    def preview(self, actor, order_id):
        self.admin(actor)
        if not re.fullmatch(r'[a-f0-9]{24}', order_id):
            raise CheckoutError('Invalid order ID.')
        with self.store.connection() as db:
            row = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
            self.validate(row)
            fingerprint = self.fingerprint(row)
        draft = dict(order_id=order_id, fingerprint=fingerprint,
                     nonce=secrets.token_hex(12), expires=int(time.time()) + 600)
        self.store.metadata(self.key(actor), self.store.seal(draft))
        return dict(nonce=draft['nonce'], orderId=order_id,
                    expiresAt=draft['expires'], warning=WARNING)


def register_admin(app, service):
    routes = Blueprint('admin_internal', __name__)
    recovery = WebTrialRecovery(service)
    store = service.store
    from .web_password_auth import register_password_routes
    register_password_routes(routes, store)

    @routes.before_request
    def authenticate():
        # A fresh process-only key is supplied by the supervising API gateway.
        # No browser-provided user/role header is trusted.
        key = os.environ.get('STREAMBOT_ADMIN_BRIDGE_KEY', '')
        actor = request.headers.get('X-Streamline-Actor', '')
        timestamp = request.headers.get('X-Streamline-Time', '')
        nonce = request.headers.get('X-Streamline-Nonce', '')
        signature = request.headers.get('X-Streamline-Signature', '')
        if (len(key) < 64 or not re.fullmatch(r'\d{10}', timestamp)
                or abs(time.time() - int(timestamp)) > 30
                or not re.fullmatch(r'[a-f0-9]{32}', nonce)
                or not re.fullmatch(ACTOR_PATTERN, actor)):
            return jsonify(error='Unauthorized.'), 401
        raw = request.get_data()
        parts = [request.method, request.full_path.rstrip('?'), actor, timestamp, nonce,
                 hashlib.sha256(raw).hexdigest()]
        expected = hmac.new(key.encode(), '\n'.join(parts).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return jsonify(error='Unauthorized.'), 401
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            replay_key = 'admin_bridge_nonce:' + nonce
            if db.execute('SELECT value FROM metadata WHERE key=?', (replay_key,)).fetchone():
                return jsonify(error='Request already used.'), 409
            # Only gateway-generated integer timestamps live under this namespace.
            # The LIKE percent must be a bound value: psycopg interprets a raw
            # percent in SQL with parameters as its own placeholder syntax.
            db.execute(NONCE_PRUNE_SQL, ('admin_bridge_nonce:%', str(int(time.time()) - 60)))
            db.execute('INSERT INTO metadata VALUES(?,?)', (replay_key, timestamp))
        request.admin_actor = actor

    @routes.get('/owner/status')
    def owner_status():
        owner = store.metadata('web_admin_owner')
        return jsonify(claimed=bool(owner),
                       matches=owner == request.admin_actor.rsplit(':', 1)[0])

    @routes.post('/owner/claim')
    def claim_owner():
        # The gateway requires OIDC login, allowlisted email AND workspace secret.
        # This immutable subject binding cannot be replaced by another sign-up.
        subject = request.admin_actor.rsplit(':', 1)[0]
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute("SELECT value FROM metadata WHERE key='web_admin_owner'").fetchone()
            if existing and existing[0] != subject:
                return jsonify(error='An owner is already configured. Nothing was changed.'), 409
            if not existing:
                db.execute('INSERT INTO metadata VALUES(?,?)', ('web_admin_owner', subject))
                db.execute('INSERT INTO metadata VALUES(?,?)', (
                    'web_admin_owner_claim:' + digest(subject),
                    store.seal(dict(actor=subject, at=int(time.time()), proof='workspace_secret'))))
        return jsonify(claimed=True, matches=True)

    accounts = service.accounts

    def safe(row, owners, names):
        plan = json.loads(row['plan_json'])
        asset = json.loads(row['asset_json'])
        # Trials carry their Telegram ID on the order; paid bot orders are linked through account_links.
        owner = row['telegram_id'] or owners.get(row['id'])
        return dict(id=row['id'], kind=row['kind'], status=row['status'],
                    plan=plan.get('name', plan.get('id', 'Membership')),
                    createdAt=row['created_at'],
                    amount=display_units(row['amount_units'], asset.get('decimals', 0)),
                    symbol=asset.get('symbol', ''), network=asset.get('network', ''),
                    customer=str(owner) if owner else 'Website checkout',
                    username=names.get(int(owner), '') if owner else '')

    def safe_rows(rows):
        with store.connection() as db:
            owners = accounts.owners(db, [row['id'] for row in rows if not row['telegram_id']])
            names = accounts.usernames(db, [row['telegram_id'] or owners.get(row['id']) for row in rows if row['telegram_id'] or owners.get(row['id'])])
        return [safe(row, owners, names) for row in rows]

    @routes.get('/overview')
    def overview():
        with store.connection() as db:
            counts = db.execute('SELECT status,COUNT(*) AS n FROM orders GROUP BY status').fetchall()
            trials = db.execute("SELECT COUNT(*) FROM orders WHERE kind='trial'").fetchone()[0]
            recent = db.execute('SELECT * FROM orders ORDER BY created_at DESC,id DESC LIMIT 8').fetchall()
        totals = {row['status']: row['n'] for row in counts}
        extra = dict(creditsSoldMonth=0, activeResellers=0, testsConverted=0, revenueMonthGbp=0.0, openTickets=service.tickets.admin_counts()['open'])
        if service.resellers.ready:
            month = service.resellers.finance.month_start()
            with store.connection() as db:
                extra['creditsSoldMonth'] = int(db.execute("SELECT COALESCE(SUM(credits),0) FROM rs_purchases WHERE status='granted' AND created_at>=?", (month,)).fetchone()[0])
                extra['activeResellers'] = int(db.execute("SELECT COUNT(*) FROM rs_resellers WHERE status='active'").fetchone()[0])
                extra['testsConverted'] = int(db.execute("SELECT COUNT(*) FROM rs_subscriptions WHERE converted_at IS NOT NULL").fetchone()[0])
                packs = db.execute("SELECT COALESCE(SUM(amount_pence),0) FROM rs_purchases WHERE status='granted' AND created_at>=?", (month,)).fetchone()[0]
                retail = db.execute("SELECT o.plan_json FROM orders o JOIN payments p ON p.order_id=o.id WHERE o.kind='paid' AND o.created_at>=?", (month,)).fetchall()
            revenue = float(packs or 0) / 100  # PostgreSQL sums arrive as Decimal; keep the maths in float
            for row in retail:
                plan = json.loads(row['plan_json'])
                if not plan.get('reseller_purchase'): revenue += float(plan.get('gbp_price') or 0)
            extra['revenueMonthGbp'] = round(revenue, 2)
        return jsonify(mode=service.config['mode'], total=sum(totals.values()), trials=trials,
                       fulfilled=totals.get('fulfilled', 0), review=totals.get('review', 0),
                       queued=totals.get('paid', 0) + totals.get('provisioning', 0),
                       pending=totals.get('pending', 0), recent=safe_rows(recent), **extra)

    @routes.get('/orders')
    def orders():
        try: page = int(request.args.get('page', '1'))
        except ValueError: raise CheckoutError('Invalid page.') from None
        if not 1 <= page <= 100000: raise CheckoutError('Invalid page.')
        q = request.args.get('q', '')
        status = request.args.get('status', '')
        kind = request.args.get('kind', '')
        if len(q) > 80 or (status and status not in (
                'pending', 'paid', 'provisioning', 'fulfilled', 'review', 'expired', 'queued')):
            raise CheckoutError('Invalid order filter.')
        if kind and kind not in ('trial', 'paid'): raise CheckoutError('Invalid order type.')
        clauses, params = [], []
        if q:
            # Order ID fragment, exact Telegram ID, or exact Telegram @username (trials carry the ID
            # on the order; paid bot orders are linked through account_links).
            with store.connection() as db:
                ids = accounts.username_ids(db, q)[:20]
            if q.isdigit() and len(q) <= 19: ids.append(int(q))
            match = ['id LIKE ?']; params.append('%' + q.replace('%', '').replace('_', '') + '%')
            if ids:
                marks = ','.join('?' * len(ids))
                match.append('telegram_id IN (' + marks + ')')
                match.append('id IN (SELECT order_id FROM account_links WHERE telegram_id IN (' + marks + '))')
                params.extend(ids + ids)
            clauses.append('(' + ' OR '.join(match) + ')')
        if status == 'queued': clauses.append("status IN ('paid','provisioning')")
        elif status: clauses.append('status=?'); params.append(status)
        if kind: clauses.append('kind=?'); params.append(kind)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with store.connection() as db:
            total = db.execute('SELECT COUNT(*) FROM orders' + where, tuple(params)).fetchone()[0]
            rows = db.execute('SELECT * FROM orders' + where +
                              ' ORDER BY created_at DESC,id DESC LIMIT 25 OFFSET ?',
                              tuple(params + [(page - 1) * 25])).fetchall()
        return jsonify(items=safe_rows(rows), page=page, pageSize=25, total=total)

    @routes.get('/orders/<order_id>')
    def detail(order_id):
        if not re.fullmatch(r'[a-f0-9]{24}', order_id): raise CheckoutError('Order not found.')
        with store.connection() as db:
            row = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
        if not row: raise CheckoutError('Order not found.')
        try:
            recovery.validate(row)
            eligible, reason = True, WARNING
        except CheckoutError as exc:
            eligible, reason = False, str(exc)
        # Raw provider/credential data and tokens never leave this boundary.
        messages = {
            'review': 'Account provisioning needs manual review. Do not create a duplicate account.',
            'fulfilled': 'Account delivery has been confirmed.',
            'pending': 'Awaiting a verified payment.',
            'paid': 'Payment or trial entitlement accepted; account preparation is queued.',
            'provisioning': 'Account preparation is in progress.',
            'expired': 'The payment quote has expired.',
        }
        # The owner asked to see the delivered login here. Checkout tokens, payment proofs and raw
        # provider errors still never leave this boundary.
        plan = json.loads(row['plan_json'])
        months = None if row['kind'] == 'trial' else int(plan.get('months') or 1)
        account = accounts.account(row['created_at'], store.unseal(row['credentials']), months) if row['status'] == 'fulfilled' else None
        with store.connection() as db:
            removed = accounts.removed(db, order_id)
        order = safe_rows([row])[0]
        if removed and removed.get('telegram_id') and order['customer'] == 'Website checkout':
            order['customer'] = str(removed['telegram_id'])  # the link was dropped on delete; the record remembers who it was
        message = messages.get(row['status'], 'Check order status.')
        if removed: message = 'This subscription was deleted from the dashboard. The order is kept for your records.'
        return jsonify(order=order, message=message, recoveryEligible=eligible, recoveryReason=reason,
                       account=account, removedAt=int(removed['at']) if removed else 0,
                       canDelete=bool(account) and not removed and not plan.get('reseller_purchase'))

    # ---- resellers, reports, rate card (website owner acts through the bridge actor) ----
    def finance():
        if not service.resellers.ready: raise CheckoutError('Reseller tables are not present in this database.')
        return service.resellers.finance

    def reseller_public(row):
        return dict(telegramId=row['telegram_id'], username=row['username'], status=row['status'], createdAt=row['created_at'],
                    balance=row['balance'], reserved=row['reserved'], available=row['available'], customers=row['customers'],
                    activeCustomers=row['active_customers'], creditsBought=row['credits_bought'], lastActivity=row['last_activity'])

    def reseller_detail(telegram_id):
        f = finance()
        rows = [r for r in f.summary(request.admin_actor, str(telegram_id)) if r['telegram_id'] == telegram_id]
        if not rows: raise CheckoutError('Reseller not found.')
        history = f.history(telegram_id, 0)[:10]
        return dict(reseller=reseller_public(rows[0]), stats=f.stats(telegram_id), trials=f.trial_summary(telegram_id),
                    history=[dict(createdAt=h['created_at'], movement=h['movement'], reason=h['reason'], reference=h['reference']) for h in history])

    def reseller_id(value):
        if not re.fullmatch(r'[1-9][0-9]{0,18}', value): raise CheckoutError('Invalid reseller.')
        return int(value)

    @routes.get('/resellers')
    def resellers():
        try: page = int(request.args.get('page', '1'))
        except ValueError: raise CheckoutError('Invalid page.') from None
        if not 1 <= page <= 100000: raise CheckoutError('Invalid page.')
        q = request.args.get('q', '')[:80]
        rows = finance().summary(request.admin_actor, q, page - 1)
        return jsonify(items=[reseller_public(r) for r in rows[:25]], page=page, pageSize=25, more=len(rows) > 25)

    @routes.get('/resellers/<telegram_id>')
    def reseller(telegram_id):
        return jsonify(reseller_detail(reseller_id(telegram_id)))

    @routes.post('/resellers/<telegram_id>/status')
    def reseller_status(telegram_id):
        uid = reseller_id(telegram_id)
        data = request.get_json(silent=True) or {}
        finance().account_status(request.admin_actor, uid, str(data.get('status', '')), str(data.get('reason', '')))
        return jsonify(reseller_detail(uid))

    @routes.post('/resellers/<telegram_id>/credits')
    def reseller_credits(telegram_id):
        uid = reseller_id(telegram_id)
        data = request.get_json(silent=True) or {}
        movement = data.get('movement')
        if type(movement) is not int: raise CheckoutError('Credits must be a whole number.')
        key = str(data.get('requestKey', ''))
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', key): raise CheckoutError('A request key is required.')
        finance().adjust(request.admin_actor, uid, movement, str(data.get('reason', '')), key)
        return jsonify(reseller_detail(uid))

    @routes.post('/resellers/<telegram_id>/trial-limits')
    def reseller_trial_limits(telegram_id):
        uid = reseller_id(telegram_id)
        data = request.get_json(silent=True) or {}
        limits = {name: data.get(name) for name in ('daily', 'weekly', 'monthly', 'active')}
        if any(value is not None and type(value) is not int for value in limits.values()):
            raise CheckoutError('Trial limits must be whole numbers.')
        finance().set_trial_limits(request.admin_actor, uid, limits, str(data.get('reason', '')))
        return jsonify(reseller_detail(uid))

    # ---- subscriptions and trials: retail and reseller accounts in one list ----
    @routes.get('/subscriptions')
    def subscriptions():
        try:
            page = int(request.args.get('page', '1'))
            reseller = int(request.args['reseller']) if request.args.get('reseller') else None
        except ValueError: raise CheckoutError('Invalid subscription filter.') from None
        return jsonify(accounts.list(request.admin_actor, source=request.args.get('source', ''), kind=request.args.get('kind', ''),
                                     status=request.args.get('status', ''), reseller=reseller, search=request.args.get('q', ''), page=page))

    @routes.post('/subscriptions')
    def add_subscription():
        data = request.get_json(silent=True) or {}
        order_id = accounts.add(request.admin_actor, data.get('telegramId'), data.get('planId'), str(data.get('reason', '')))
        return jsonify(orderId=order_id, message='Membership queued. The account is created in the background and the login is sent to the customer in Telegram.')

    @routes.post('/subscriptions/<source>/<sid>/delete')
    def delete_subscription(source, sid):
        data = request.get_json(silent=True) or {}
        if data.get('confirm') is not True: raise CheckoutError('Confirm the deletion first.')
        accounts.delete(request.admin_actor, source, sid, str(data.get('reason', '')))
        return jsonify(deleted=True)

    @routes.get('/reports')
    def reports():
        try: months = int(request.args.get('months', '12'))
        except ValueError: raise CheckoutError('Invalid range.') from None
        report = finance().report(request.admin_actor, months)
        return jsonify(months=[dict(month=m['month'], retailOrders=m['retail_orders'], retailGbp=m['retail_gbp'], creditPacks=m['credit_packs'],
                                    creditGbp=m['credit_gbp'], totalGbp=m['total_gbp'], creditsSold=m['credits_sold'], creditsUsed=m['credits_used'],
                                    tests=m['tests'], testsConverted=m['tests_converted']) for m in report['months']],
                       resellers=[reseller_public(r) for r in report['resellers']])

    def rate_card():
        f = finance(); f.seed()
        with store.connection() as db:
            costs = [dict(months=r['months'], connections=r['connections'], credits=r['credits']) for r in
                     db.execute('SELECT months,connections,credits FROM rs_costs ORDER BY months,connections').fetchall()]
            limits = f.trial_limits(db)[0]
        return dict(packages=[dict(id=p['id'], pricePence=p['price_pence'], credits=p['credits'], active=bool(p['active'])) for p in f.packages()],
                    plans=service.pricing.public(),
                    costs=costs, trialDaily=limits['daily'], trialActive=limits['active'], trialLimits=limits)

    @routes.get('/faq')
    def get_faq():
        finance().admin(request.admin_actor)
        return jsonify(items=service.faq.items())

    @routes.post('/faq')
    def update_faq():
        data = request.get_json(silent=True) or {}
        return jsonify(items=service.faq.save(request.admin_actor, data.get('items')))

    @routes.get('/ratecard')
    def get_rate_card():
        finance().admin(request.admin_actor)
        return jsonify(rate_card())

    @routes.post('/ratecard')
    def update_rate_card():
        data = request.get_json(silent=True) or {}
        category, values, reason = data.get('category'), data.get('values'), str(data.get('reason', ''))
        if not isinstance(values, list): raise CheckoutError('Invalid values.')
        if category == 'package':
            pid, price, credits, active = (str(values[0]), int(values[1]), int(values[2]), int(bool(values[3]))) if len(values) == 4 else (None,) * 4
            finance().configure(request.admin_actor, 'package', (pid, price, credits, active), reason)
        elif category == 'plan':
            if len(values) != 3: raise CheckoutError('Invalid values.')
            service.pricing.set_plan(request.admin_actor, str(values[0]), str(values[1]), bool(values[2]), reason)
        elif category == 'package_add':
            if len(values) != 2: raise CheckoutError('Invalid values.')
            finance().configure(request.admin_actor, 'package_add', (int(values[0]), int(values[1])), reason)
        elif category == 'package_delete':
            if len(values) != 1: raise CheckoutError('Invalid values.')
            finance().configure(request.admin_actor, 'package_delete', (str(values[0]),), reason)
        elif category == 'cost':
            if len(values) != 3: raise CheckoutError('Invalid values.')
            finance().configure(request.admin_actor, 'cost', (int(values[0]), int(values[1]), int(values[2])), reason)
        elif category == 'trials':
            # (daily, active) or (daily, weekly, monthly, active); -1 means unlimited.
            if len(values) not in (2, 4) or any(type(v) is not int for v in values): raise CheckoutError('Invalid values.')
            finance().configure(request.admin_actor, 'trials', tuple(values), reason)
        else: raise CheckoutError('Unknown configuration option.')
        return jsonify(rate_card())

    def ticket_public(t):
        return dict(id=t['id'], telegramId=int(t['telegram_id']), username=t['username'], topic=t['topic'], topicLabel=t['topic_label'],
                    status=t['status'], channel=t['channel'], reseller=bool(t['reseller']), createdAt=int(t['created_at']), updatedAt=int(t['updated_at']),
                    messages=int(t.get('messages', 0)), lastSender=t.get('last_sender', ''), preview=t.get('preview', ''))

    def ticket_detail(tid):
        t, messages = service.tickets.admin_get(request.admin_actor, tid)
        return dict(ticket=ticket_public(dict(t, messages=len(messages), last_sender=messages[-1]['sender'] if messages else '', preview=messages[-1]['body'][:120] if messages else '')),
                    messages=[dict(id=m['id'], sender=m['sender'], body=m['body'], actor=m['actor'], createdAt=int(m['created_at'])) for m in messages])

    @routes.get('/tickets')
    def tickets():
        try: page = int(request.args.get('page', '1'))
        except ValueError: raise CheckoutError('Invalid page.') from None
        if not 1 <= page <= 10000: raise CheckoutError('Invalid page.')
        rows = service.tickets.admin_list(request.admin_actor, request.args.get('status', 'open'), request.args.get('q', '')[:80], page - 1)
        return jsonify(items=[ticket_public(t) for t in rows[:25]], page=page, pageSize=25, more=len(rows) > 25, counts=service.tickets.admin_counts())

    @routes.get('/tickets/<tid>')
    def ticket(tid):
        return jsonify(ticket_detail(tid))

    @routes.post('/tickets/<tid>/reply')
    def ticket_reply(tid):
        data = request.get_json(silent=True) or {}
        _, delivered = service.tickets.admin_reply(request.admin_actor, tid, str(data.get('body', '')))
        return jsonify(delivered=delivered, **ticket_detail(tid))

    @routes.post('/tickets/<tid>/status')
    def ticket_status(tid):
        data = request.get_json(silent=True) or {}
        service.tickets.admin_status(request.admin_actor, tid, str(data.get('status', '')))
        return jsonify(delivered=True, **ticket_detail(tid))

    @routes.post('/auth/qr')
    def auth_qr():
        # Bridge-only helper: renders the owner's authenticator enrolment URI as a PNG data URL.
        import base64, io, qrcode
        uri = str((request.get_json(silent=True) or {}).get('uri', ''))
        if not uri.startswith('otpauth://totp/') or len(uri) > 400: raise CheckoutError('Invalid enrolment URI.')
        buffer = io.BytesIO(); qrcode.make(uri).save(buffer, format='PNG')
        return jsonify(qr='data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode())

    @routes.get('/status')
    def status():
        try:
            with store.connection() as db: db.execute('SELECT telegram_id FROM nt_contacts WHERE 1=0')
            notification_ready = True
        except Exception: notification_ready = False
        return jsonify(mode=service.config['mode'], workersActive=True,
                       panelWrites=bool(service.config.get('panel_writes')),
                       telegramEnabled=bool(service.config.get('telegram_enabled')),
                       panelConfigured=bool(service.config.get('panel_username') and service.config.get('panel_password')),
                       resellerSchema=bool(getattr(service.resellers, 'ready', False)),
                       notificationSchema=notification_ready,
                       database='PostgreSQL' if service.config.get('database_url') else 'SQLite demo')

    @routes.post('/orders/<order_id>/recovery')
    def preview(order_id):
        if request.get_json() != {}: raise CheckoutError('Invalid recovery preview.')
        return jsonify(recovery.preview(request.admin_actor, order_id))

    @routes.post('/recovery/confirm')
    def confirm():
        data = request.get_json()
        if (not isinstance(data, dict) or set(data) != {'nonce', 'attestation', 'cancel'}
                or type(data['cancel']) is not bool or type(data['attestation']) is not bool
                or not isinstance(data['nonce'], str) or not re.fullmatch(r'[a-f0-9]{24}', data['nonce'])
                or (not data['cancel'] and data['attestation'] is not True)):
            raise CheckoutError('Explicit no-submission attestation is required.')
        order_id = recovery.confirm(request.admin_actor, data['nonce'], cancel=data['cancel'])
        return jsonify(orderId=order_id, queued=not data['cancel'],
                       message='Recovery cancelled. Nothing was queued.' if data['cancel'] else
                       'Original trial queued. The worker will prepare it; this is not delivery confirmation.')

    app.register_blueprint(routes, url_prefix='/api/_admin')
