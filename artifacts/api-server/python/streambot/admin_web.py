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

    def safe(row):
        plan = json.loads(row['plan_json'])
        asset = json.loads(row['asset_json'])
        return dict(id=row['id'], kind=row['kind'], status=row['status'],
                    plan=plan.get('name', plan.get('id', 'Membership')),
                    createdAt=row['created_at'],
                    amount=display_units(row['amount_units'], asset.get('decimals', 0)),
                    symbol=asset.get('symbol', ''), network=asset.get('network', ''),
                    customer=str(row['telegram_id']) if row['telegram_id'] else 'Website checkout')

    @routes.get('/overview')
    def overview():
        with store.connection() as db:
            counts = db.execute('SELECT status,COUNT(*) AS n FROM orders GROUP BY status').fetchall()
            trials = db.execute("SELECT COUNT(*) FROM orders WHERE kind='trial'").fetchone()[0]
            recent = db.execute('SELECT * FROM orders ORDER BY created_at DESC,id DESC LIMIT 8').fetchall()
        totals = {row['status']: row['n'] for row in counts}
        return jsonify(mode=service.config['mode'], total=sum(totals.values()), trials=trials,
                       fulfilled=totals.get('fulfilled', 0), review=totals.get('review', 0),
                       queued=totals.get('paid', 0) + totals.get('provisioning', 0),
                       pending=totals.get('pending', 0), recent=[safe(row) for row in recent])

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
            # Identifier search, not pattern injection or decryption of private data.
            clauses.append("(id LIKE ? OR CAST(telegram_id AS TEXT)=?)")
            params.extend(['%' + q.replace('%', '').replace('_', '') + '%', q])
        if status == 'queued': clauses.append("status IN ('paid','provisioning')")
        elif status: clauses.append('status=?'); params.append(status)
        if kind: clauses.append('kind=?'); params.append(kind)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with store.connection() as db:
            total = db.execute('SELECT COUNT(*) FROM orders' + where, tuple(params)).fetchone()[0]
            rows = db.execute('SELECT * FROM orders' + where +
                              ' ORDER BY created_at DESC,id DESC LIMIT 25 OFFSET ?',
                              tuple(params + [(page - 1) * 25])).fetchall()
        return jsonify(items=[safe(row) for row in rows], page=page, pageSize=25, total=total)

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
        return jsonify(order=safe(row), message=messages.get(row['status'], 'Check order status.'),
                       recoveryEligible=eligible, recoveryReason=reason)

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
