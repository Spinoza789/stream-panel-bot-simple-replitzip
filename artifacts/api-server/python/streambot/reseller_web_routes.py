"""HTTP routes for the reseller web portal (/reseller/ page and /api/reseller/* JSON).

Every endpoint acts only for the signed-in reseller: the cookie session resolves to
one Telegram ID and every ledger/operations call is scoped by it. POST bodies are
same-origin JSON (enforced globally in web.py); the session cookie is HttpOnly and
scoped to the API path.
"""
import csv
import io
import secrets
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, send_from_directory

from .service import CheckoutError
from .tickets import TOPICS
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

    @app.get('/install')
    def install_page():
        # Public, read-only setup guide: no login, no account data. Shares APP_GUIDE with the bot and the panel.
        return install_html(config['brand'], base), 200, {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'public, max-age=300'}

    @app.get('/reseller/static/<path:name>')
    def reseller_static(name):
        if not name.endswith(('.js', '.css', '.png', '.jpg')):
            return jsonify(error='Not found.'), 404
        return send_from_directory(str(PORTAL), name, max_age=0 if name.endswith(('.js', '.css')) else 86400)

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

    @routes.get('/stats')
    def stats():
        return jsonify(resellers.finance.stats(current_uid()))

    @routes.post('/subscriptions/<sid>/notes')
    def notes(sid):
        uid = current_uid()
        data = body()
        record = resellers.ops.update_notes(uid, sid, str(data.get('customer_ref', '')), str(data.get('contact', '')))
        record.pop('credentials', None); record.pop('reseller_id', None)
        return jsonify(record=record)

    @routes.post('/subscriptions/<sid>/delete')
    def delete_subscription(sid):
        record = resellers.ops.delete(current_uid(), sid)
        return jsonify(deleted=record['id'])

    @routes.post('/subscriptions/delete-expired')
    def delete_expired():
        return jsonify(deleted=resellers.ops.delete_expired(current_uid()))

    def ticket_public(t):
        return {k: t[k] for k in ('id', 'topic', 'topic_label', 'status', 'status_label', 'channel', 'created_at', 'updated_at', 'closed_at') if k in t} | \
               {k: t[k] for k in ('messages', 'last_sender', 'preview') if k in t}

    def message_public(m):
        return dict(id=m['id'], sender=m['sender'], body=m['body'], created_at=m['created_at'])

    @routes.get('/tickets')
    def tickets():
        uid = current_uid()
        try: page = int(request.args.get('page', '0'))
        except ValueError: raise CheckoutError('Invalid page.') from None
        rows = service.tickets.list(uid, page)
        return jsonify(items=[ticket_public(t) for t in rows[:10]], more=len(rows) > 10, page=page, topics=TOPICS,
                       counts=service.tickets.counts(uid))

    @routes.post('/tickets')
    def open_ticket():
        uid = current_uid(); data = body()
        login = web.login(uid) or {}
        ticket = service.tickets.open(uid, str(data.get('topic', '')), str(data.get('body', '')), 'web', str(login.get('username') or ''))
        return jsonify(ticket=ticket_public(ticket))

    @routes.get('/tickets/<tid>')
    def ticket(tid):
        t, messages = service.tickets.get(current_uid(), tid)
        return jsonify(ticket=ticket_public(t), messages=[message_public(m) for m in messages])

    @routes.post('/tickets/<tid>/reply')
    def reply_ticket(tid):
        uid = current_uid(); data = body()
        t = service.tickets.reply(uid, tid, str(data.get('body', '')), 'web')
        t, messages = service.tickets.get(uid, tid)
        return jsonify(ticket=ticket_public(t), messages=[message_public(m) for m in messages])

    @routes.post('/tickets/<tid>/close')
    def close_ticket(tid):
        uid = current_uid()
        service.tickets.close(uid, tid)
        t, messages = service.tickets.get(uid, tid)
        return jsonify(ticket=ticket_public(t), messages=[message_public(m) for m in messages])

    def csv_response(name, header, rows):
        out = io.StringIO(); writer = csv.writer(out); writer.writerow(header); writer.writerows(rows)
        return Response(out.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': 'attachment; filename="' + name + '"', 'Cache-Control': 'no-store'})

    def stamp(ts):
        return datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d %H:%M') if ts else ''

    @routes.get('/history.csv')
    def history_csv():
        uid = current_uid()
        rows, page = [], 0
        while page < 400:
            chunk = resellers.finance.history(uid, page)
            rows.extend(chunk[:10])
            if len(chunk) <= 10: break
            page += 1
        return csv_response('credit-history.csv', ['date', 'credits', 'reason', 'reference'],
                            [[stamp(r['created_at']), r['movement'], r['reason'], r['reference']] for r in rows])

    @routes.get('/subscriptions.csv')
    def subscriptions_csv():
        uid = current_uid()
        rows, page = [], 0
        while page < 400:
            chunk = resellers.ops.records(uid, 'all', page, '')
            rows.extend(chunk[:10])
            if len(chunk) <= 10: break
            page += 1
        return csv_response('customers.csv', ['customer', 'contact', 'type', 'devices', 'username', 'status', 'started', 'expires', 'subscription_id'],
                            [[r['customer_ref'], r.get('contact') or '', 'test' if r['kind'] == 'trial' else 'subscription', r['connections'],
                              r['username'], r['status'], stamp(r['starts_at']), stamp(r['expires_at']), r['provider_id']] for r in rows])

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


def install_html(brand, base):
    """Server-rendered install guide. Only static text from APP_GUIDE is interpolated, all HTML-escaped."""
    from html import escape as e
    g = APP_GUIDE
    def steps(section):
        items = []
        for i, step in enumerate(section['steps']):
            picture = ('<img src="' + e(base + '/reseller/static/' + step['picture']) + '" alt="" loading="lazy">') if step.get('picture') else ''
            items.append('<li>' + picture + '<div><span class="n">' + str(i + 1) + '</span>' + e(step['text']) + '</div></li>')
        return '<ol class="steps">' + ''.join(items) + '</ol>'
    fire = g['firestick']; apple = g['apple']; android = g['android']
    codes = ''.join('<tr><th>' + e(a['name']) + '</th><td>' + ' · '.join('<code>' + e(c) + '</code>' for c in a['codes']) + '</td></tr>' for a in fire['apps'])
    links = ''.join('<tr><th>' + e(a['name']) + '</th><td><a href="' + e(a['url']) + '" rel="noopener">' + e(a['url']) + '</a></td></tr>' for a in android['apps'])
    css = ('body{margin:0;background:#f1f1f1;color:#303030;font:14px/1.55 Inter,-apple-system,Segoe UI,Roboto,sans-serif}'
           'main{max-width:960px;margin:0 auto;padding:24px 16px 48px}h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:0 0 12px}'
           '.lead{color:#616161;margin:0 0 20px}section{background:#fff;border-radius:12px;box-shadow:0 1px 0 rgba(26,26,26,.07),0 0 0 1px rgba(0,0,0,.04);padding:16px;margin-bottom:16px}'
           '.steps{list-style:none;margin:0 0 14px;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;align-items:start}'
           '.steps li{background:#f7f7f7;border:1px solid #e3e3e3;border-radius:12px;overflow:hidden}.steps img{display:block;width:100%;height:180px;object-fit:contain;background:#111}'
           '.steps li div{display:flex;gap:10px;padding:10px 12px}.n{flex:none;width:22px;height:22px;border-radius:50%;background:#303030;color:#fff;font-size:12px;font-weight:650;display:grid;place-items:center}'
           'table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:8px 10px;border-top:1px solid #e3e3e3;vertical-align:top}th{width:160px;font-weight:550}'
           'code{font:13px ui-monospace,Menlo,Consolas,monospace;background:#f1f1f1;border:1px solid #e3e3e3;border-radius:6px;padding:2px 6px}a{color:#005bd3}'
           '.note{color:#616161;font-size:12px;margin:10px 0 0}footer{color:#616161;font-size:12px;text-align:center;margin-top:12px}')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>' + e(brand) + ' · How to install</title><style>' + css + '</style></head><body><main>'
            '<h1>How to install ' + e(brand) + '</h1><p class="lead">Pick your device. You will need the username and password you were sent.</p>'
            '<section><h2>' + e(fire['title']) + '</h2>' + steps(fire) + '<table>' + codes + '</table><p class="note">' + e(fire.get('note', '')) + '</p></section>'
            '<section><h2>' + e(apple['title']) + '</h2>' + steps(apple) + '<table><tr><th>Download</th><td><a href="https://' + e(apple['site']) + '" rel="noopener">' + e(apple['site']) + '</a></td></tr>'
            '<tr><th>URL code</th><td><code>' + e(apple['url_code']) + '</code></td></tr></table></section>'
            '<section><h2>' + e(android['title']) + '</h2>' + steps(android) + '<table>' + links + '</table></section>'
            '<footer>' + e(g.get('credits', '')) + '</footer></main></body></html>')
