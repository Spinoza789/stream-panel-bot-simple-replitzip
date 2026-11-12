import io
import logging
from pathlib import Path
from flask import Flask, jsonify, request, send_file
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.exceptions import NotFound
import qrcode
from .service import CheckoutError

log = logging.getLogger(__name__)


def create_app(service,ready=None):
    # Keep the original checkout in its own web artifact; Flask still renders
    # the base-path placeholder and applies the original security protections.
    checkout = Path(__file__).resolve().parents[3] / 'streamline' / 'checkout'
    app = Flask(__name__,static_folder=str(checkout),static_url_path='/static')
    app.config['MAX_CONTENT_LENGTH']=4096
    if service.config.get('trust_proxy'):
        app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1)

    @app.before_request
    def protect():
        if ready is not None and not ready.is_set():
            # Liveness must succeed during a rolling publish so the platform
            # can retire the old version and release its worker lease.
            # No checkout/state access is allowed before leadership is held.
            if request.method in ('GET','HEAD') and request.path in ('/','/healthz'):
                return jsonify(status='standby',workers_active=False,mode=service.config['mode'],
                               message='The service is starting. Please retry shortly.'),200,{'Retry-After':'3'}
            return jsonify(error='The service is starting. Please retry shortly.'),503,{'Retry-After':'3'}
        # The private admin bridge is authenticated by a per-process HMAC key before it touches any
        # state, and sign-in attempts have their own persistent limits, so it skips this shared bucket.
        if request.path.startswith('/api/') and not request.path.startswith('/api/_admin/'):
            bucket='web:'+str(request.remote_addr)
            if not service.store.limit(bucket,180,60): return jsonify(error='Too many requests. Please wait a minute.'),429
        if request.method=='POST' and not request.path.startswith('/api/_admin/'):
            if not request.is_json: return jsonify(error='JSON requests only.'),415
            if request.headers.get('Origin')!=service.config['public_url']:
                return jsonify(error='This request must come from the checkout website.'),403
            if request.content_length is None: return jsonify(error='A request body is required.'),400

    @app.after_request
    def headers(response):
        response.headers.update({
            'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff',
            'X-Frame-Options':'DENY','Permissions-Policy':'camera=(), microphone=(), geolocation=()',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        if service.config['mode']=='live': response.headers['Strict-Transport-Security']='max-age=31536000'
        return response

    @app.errorhandler(CheckoutError)
    def invalid_order(exc): return jsonify(error=str(exc)),404 if 'not found' in str(exc).lower() else 400

    @app.errorhandler(413)
    def oversized(_): return jsonify(error='Request is too large.'),413

    @app.get('/order/')
    def legacy_order_page():
        # Past web customers keep their private recovery links; new orders are not taken here.
        html=(Path(app.static_folder)/'index.html').read_text()
        return html.replace('__STREAMBOT_BASE__',service.config.get('base_path','')),200,{'Content-Type':'text/html; charset=utf-8'}

    @app.get('/order')
    def legacy_order_redirect(): return '',302,{'Location':service.config.get('base_path','')+'/order/'}

    @app.get('/healthz')
    def health(): return jsonify(status='ok',mode=service.config['mode'],workers_active=True)

    @app.get('/api/catalog')
    def catalog():
        return jsonify(brand=service.config['brand'],support=service.config['support'],support_url=service.config['support_url'],
                       demo=service.config['mode']=='demo',
                       plans=[{k:v for k,v in plan.items() if k not in ('prices','package_id')} for plan in service.config['plans'] if plan.get('active',True)],
                       assets=[{k:asset[k] for k in ('id','symbol','network','decimals')} for asset in service.config['assets'].values() if asset.get('enabled',True)])

    def token():
        value=request.headers.get('X-Order-Token','')
        if not 40<=len(value)<=100: raise CheckoutError('Order not found.')
        return value

    @app.post('/api/orders')
    def create_order():
        # The website no longer sells memberships; customers order through the Telegram bot.
        request.get_json(silent=True)  # still enforce the body-size limit before answering
        return jsonify(error='Orders are placed through our Telegram bot, not on this website.',support_url=service.config.get('support_url','')),410

    @app.get('/api/order')
    def get_order(): return jsonify(service.get_order(token()))

    @app.post('/api/order/verify')
    def verify():
        value=token()
        if not service.store.limit('verify:'+value,12,60): return jsonify(error='Please wait before checking again.'),429
        data=request.get_json()
        if not isinstance(data,dict): return jsonify(error='Invalid request.'),400
        return jsonify(service.submit_tx(value,data.get('txid','')))

    @app.post('/api/order/demo-pay')
    def demo_pay():
        if service.config['mode']!='demo': return jsonify(error='Not found.'),404
        value=token();service.demo_pay(value)
        return jsonify(service.get_order(value))

    @app.post('/api/order/link')
    def link_code():
        value=token()
        if not service.store.limit('link:'+value,5,60): return jsonify(error='Please wait before generating another code.'),429
        return jsonify(code=service.create_link_code(value),expires_in=600)

    @app.get('/api/order/qr')
    def qr():
        order=service.get_order(token())
        image=qrcode.make(order['asset']['wallet'])
        output=io.BytesIO();image.save(output,format='PNG');output.seek(0)
        return send_file(output,mimetype='image/png')

    from .admin_web import register_admin
    register_admin(app, service)
    from .reseller_web_routes import register_reseller_web
    register_reseller_web(app, service)

    if service.config.get('base_path'):
        app.wsgi_app=DispatcherMiddleware(NotFound(),{service.config['base_path']:app.wsgi_app})
    return app
