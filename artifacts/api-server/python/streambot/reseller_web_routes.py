"""HTTP routes for the reseller web portal (/reseller/ page and /api/reseller/* JSON).

Every endpoint acts only for the signed-in reseller: the cookie session resolves to
one Telegram ID and every ledger/operations call is scoped by it. POST bodies are
same-origin JSON (enforced globally in web.py); the session cookie is HttpOnly and
scoped to the API path.
"""
import secrets
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory

from .service import CheckoutError
from .trial_message import APP_GUIDE

COOKIE = 'rs_session'
PORTAL = Path(__file__).resolve().parents[3] / 'streamline' / 'reseller'


def register_reseller_web(app, service):
    resellers = service.resellers
    web = resellers.web
    config = service.config
    base = config.get('base_path', '')
    routes = Blueprint('reseller_web', __name__)

    def ip():
        return str(request.remote_addr)

    def current_uid():
        uid = web.session_uid(request.cookies.get(COOKIE))
        if uid is None:
            raise Unauthenticated()
        return uid

    class Unauthenticated(Exception):
        pass

    @routes.errorhandler(Unauthenticated)
    def need_sign_in(_):
        return jsonify(error='Sign in required.', signed_in=False), 401

    def with_cookie(response, token):
        response.set_cookie(COOKIE, token, max_age=web.SESSION_TTL, httponly=True, samesite='Lax',
                            secure=config['public_url'].startswith('https://'), path=base + '/api/reseller')
        return response

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise CheckoutError('Invalid request.')
        return data

    def me(uid):
        member = resellers.member(uid)
        if not member:
            raise CheckoutError('Reseller account not found.')
        counts = resellers.ops.counts(uid)
        return {'brand': config['brand'], 'support': config['support'], 'support_url': config.get('support_url', ''),
                'demo': config['mode'] == 'demo' and config.get('demo_banner', True),
                'telegram_id': uid, 'username': member['username'], 'status': member['status'],
                'credits': {'available': member['available'], 'reserved': member['reserved'], 'balance': member['balance']},
                'counts': counts, 'login': web.login(uid)}

    # ---- page ----------------------------------------------------------------------
    @app.get('/')
    def reseller_page():
        # The home page is the reseller sign-in and nothing else.
        html = (PORTAL / 'index.html').read_text()
        return html.replace('__STREAMBOT_BASE__', base), 200, {'Content-Type': 'text/html; charset=utf-8'}

    @app.get('/reseller/')
    def reseller_page_old():
        return '', 302, {'Location': base + '/'}

    @app.get('/reseller')
    def reseller_page_slash():
        return '', 302, {'Location': base + '/'}

    @app.get('/reseller/static/<path:name>')
    def reseller_static(name):
        if not name.endswith(('.js', '.css')):
            return jsonify(error='Not found.'), 404
        return send_from_directory(str(PORTAL), name, max_age=0)

    # ---- sessions --------------------------------------------------------------------
    @routes.post('/session/code')
    def session_from_code():
        if not service.store.limit('rsweb_code:' + ip(), 10, 60):
            return jsonify(error='Too many sign-in attempts. Please wait a minute.'), 429
        token = web.redeem_code(body().get('code'))
        uid = web.session_uid(token)
        return with_cookie(jsonify(me(uid)), token)

    @routes.post('/session/password')
    def session_from_password():
        data = body()
        email = str(data.get('email', ''))[:254].strip().lower()
        if not service.store.limit('rsweb_pw:' + ip(), 10, 900) or not service.store.limit('rsweb_pw_email:' + email, 5, 900):
            return jsonify(error='Too many sign-in attempts. Please wait 15 minutes.'), 429
        token = web.password_login(email, data.get('password'))
        uid = web.session_uid(token)
        return with_cookie(jsonify(me(uid)), token)

    @routes.post('/signout')
    def signout():
        web.sign_out(request.cookies.get(COOKIE))
        response = jsonify(ok=True)
        response.delete_cookie(COOKIE, path=base + '/api/reseller')
        return response

    # ---- account -----------------------------------------------------------------------
    @routes.get('/me')
    def get_me():
        return jsonify(me(current_uid()))

    @routes.post('/account')
    def account():
        uid = current_uid()
        if not service.store.limit('rsweb_account:' + str(uid), 5, 3600):
            return jsonify(error='Too many changes. Please wait an hour.'), 429
        data = body()
        login = web.set_login(uid, data.get('email'), data.get('password'), data.get('current_password'))
        return jsonify(login=login)

    @routes.post('/signout-everywhere')
    def signout_everywhere():
        uid = current_uid()
        web.sign_out_everywhere(uid)
        response = jsonify(ok=True)
        response.delete_cookie(COOKIE, path=base + '/api/reseller')
        return response

    # ---- records -------------------------------------------------------------------------
    @routes.get('/subscriptions')
    def subscriptions():
        uid = current_uid()
        try:
            page = int(request.args.get('page', '0'))
        except ValueError:
            raise CheckoutError('Invalid page.')
        rows = resellers.ops.records(uid, request.args.get('filter', 'active'), page, request.args.get('search', '')[:100])
        return jsonify(items=rows[:10], more=len(rows) > 10, page=page)

    @routes.get('/subscriptions/<sid>')
    def subscription(sid):
        uid = current_uid()
        record, warning, extensions = resellers.ops.refresh(uid, sid)
        record.pop('reseller_id', None)
        return jsonify(record=record, warning=warning, extensions=extensions)

    @routes.get('/history')
    def history():
        uid = current_uid()
        try:
            page = int(request.args.get('page', '0'))
        except ValueError:
            raise CheckoutError('Invalid page.')
        rows = resellers.finance.history(uid, page)
        return jsonify(items=rows[:10], more=len(rows) > 10, page=page)

    @routes.get('/apps')
    def apps():
        current_uid()
        return jsonify(brand=config['brand'], guide=APP_GUIDE)

    # ---- credits ---------------------------------------------------------------------------
    @routes.get('/packages')
    def packages():
        current_uid()
        return jsonify(packages=[p for p in resellers.finance.packages() if p['active']],
                       assets=[{k: a[k] for k in ('id', 'symbol', 'network')} for a in config['assets'].values() if a.get('enabled', True)],
                       costs=web.costs())

    @routes.post('/purchase')
    def purchase():
        uid = current_uid()
        if not service.store.limit('rsweb_purchase:' + str(uid), 10, 3600):
            return jsonify(error='You have created several quotes. Use an existing one or try again later.'), 429
        data = body()
        quote = resellers.finance.quote_purchase(uid, str(data.get('package_id', '')), str(data.get('asset_id', '')),
                                                 secrets.token_hex(12), with_token=True)
        return jsonify(token=quote['token'], order=quote['order'], checkout=base + '/#order=' + quote['token']), 201

    # ---- operations (create / trial / extend) -------------------------------------------------
    @routes.post('/operations/preview')
    def preview():
        uid = current_uid()
        data = body()
        kind = data.get('kind')
        try:
            months = int(data.get('months') or 0)
            connections = int(data.get('connections') or 1)
        except (TypeError, ValueError):
            raise CheckoutError('Invalid duration or connections.')
        adult = False if kind == 'trial' else data.get('adult')
        if not isinstance(adult, bool):
            raise CheckoutError('Choose adult or no-adult content.')
        customer_ref = str(data.get('customer_ref', ''))[:100].strip()
        target = data.get('target') if kind == 'extend' else None
        result = resellers.ops.preview(uid, kind, months, connections, adult, customer_ref, target)
        return jsonify(nonce=web.stash_preview(uid, result), preview=result)

    @routes.post('/operations/confirm')
    def confirm():
        uid = current_uid()
        saved, request_key = web.take_preview(uid, body().get('nonce'))
        operation = resellers.ops.reserve(uid, request_key, saved)
        return jsonify(operation=operation), 201

    @routes.get('/operations/<oid>')
    def operation(oid):
        uid = current_uid()
        return jsonify(operation=resellers.ops.operation(uid, oid))

    app.register_blueprint(routes, url_prefix='/api/reseller')
