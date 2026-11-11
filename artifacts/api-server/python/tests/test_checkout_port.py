"""Checkout parity checks: isolated SQLite, simulated payments, no live calls."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from streambot.__main__ import DemoPanel, DemoVerifier
from streambot.config import load_config
from streambot.service import CheckoutService
from streambot.store import Store
from streambot.web import create_app


class CheckoutPortTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        # Any accidental provider call must fail this suite, not contact a service.
        network = patch('requests.sessions.Session.request',
                        side_effect=AssertionError('No live HTTP during checkout tests'))
        network.start()
        self.addCleanup(network.stop)
        self.config = load_config(env={'APP_MODE': 'demo',
                                      'PUBLIC_URL': 'https://checkout.example.test'})
        self.service = CheckoutService(
            self.config, Store(Path(temp.name) / 'checkout.sqlite3', Fernet.generate_key()),
            DemoVerifier(), DemoPanel())
        self.client = create_app(self.service).test_client()
        self.origin = {'Origin': self.config['public_url']}
        self.selection = {'plan_id': self.config['plans'][0]['id'],
                          'asset_id': next(k for k, v in self.config['assets'].items()
                                           if v.get('enabled', True))}

    def quote(self):
        # The website no longer takes orders; existing orders (made via the bot or before) are still readable by token.
        self.assertEqual(self.client.post('/api/orders', json=self.selection, headers=self.origin).status_code, 410)
        return self.service.create_order(self.selection['plan_id'], self.selection['asset_id'])

    def test_original_frontend_and_security_headers(self):
        home = self.client.get('/')
        self.assertEqual(home.status_code, 200)
        self.assertIn(b'Log in with Telegram', home.data)  # the home page is the reseller sign-in only
        self.assertNotIn(b'Membership plans', home.data)
        response = self.client.get('/order/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'UKCTV', response.data)
        self.assertNotIn(b'__STREAMBOT_BASE__', response.data)
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        for asset in ('app.js', 'style.css'):
            response = self.client.get('/static/' + asset)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data,
                             (Path(__file__).resolve().parents[3] /
                              'streamline' / 'checkout' / asset).read_bytes())
            response.close()

    def test_demo_quote_qr_simulation_fulfillment_reload_and_link(self):
        catalog = self.client.get('/api/catalog').get_json()
        self.assertTrue(catalog['demo'])
        self.assertNotIn('package_id', catalog['plans'][0])
        quote = self.quote()
        headers = {**self.origin, 'X-Order-Token': quote['token']}
        order = quote['order']
        self.assertTrue(order['asset']['wallet'].startswith('DEMO-'))
        qr = self.client.get('/api/order/qr', headers=headers)
        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr.mimetype, 'image/png')
        self.assertTrue(qr.data.startswith(b'\x89PNG'))
        qr.close()
        paid = self.client.post('/api/order/demo-pay', json={}, headers=headers)
        self.assertEqual(paid.status_code, 200)
        self.assertEqual(paid.get_json()['status'], 'paid')
        # Uses the original DemoPanel, which rejects nonblank creation fields.
        self.service.provision_pending()
        restored = self.client.get('/api/order', headers=headers)
        self.assertEqual(restored.get_json()['status'], 'fulfilled')
        self.assertIn('credentials', restored.get_json())
        link = self.client.post('/api/order/link', json={}, headers=headers)
        self.assertEqual(link.status_code, 200)
        self.assertEqual(link.get_json()['expires_in'], 600)
        self.assertTrue(link.get_json()['code'])

    def test_origin_tokens_body_limits_and_invalid_inputs(self):
        for origin in ({}, {'Origin': 'https://wrong.example.test'}):
            self.assertEqual(self.client.post('/api/orders', json=self.selection,
                                              headers=origin).status_code, 403)
        self.assertEqual(self.client.post('/api/orders', data='x',
                                         headers=self.origin).status_code, 415)
        self.assertEqual(self.client.post('/api/orders', json={'large': 'x' * 5000},
                                         headers=self.origin).status_code, 413)
        self.assertEqual(self.client.post('/api/orders', json=[],
                                         headers=self.origin).status_code, 410)
        self.assertEqual(self.client.get('/api/order').status_code, 404)
        quote = self.quote()
        self.assertEqual(self.client.get('/api/order', headers={
            'X-Order-Token': 'x' * len(quote['token'])}).status_code, 404)
        self.assertEqual(self.client.get('/static/../config.json').status_code, 404)

    def test_existing_base_path_behavior(self):
        self.config['base_path'] = '/stream'
        client = create_app(self.service).test_client()
        self.assertEqual(client.get('/').status_code, 404)
        html = client.get('/stream/').data
        self.assertIn(b'content="/stream"', html)
        self.assertIn(b'href="/stream/reseller/static/reseller.css"', html)
        self.assertIn(b'src="/stream/reseller/static/reseller.js"', html)
        legacy = client.get('/stream/order/').data
        self.assertIn(b'src="/stream/static/app.js"', legacy)
        self.assertEqual(client.get('/stream/api/catalog').status_code, 200)
        for path in ('/stream/static/app.js', '/stream/reseller/static/reseller.js'):
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            response.close()
        self.assertEqual(client.post('/stream/api/orders', json=self.selection,
                                     headers=self.origin).status_code, 410)

    def test_live_mode_cannot_use_demo_payment_endpoint(self):
        self.config['mode'] = 'live'
        response = self.client.post('/api/order/demo-pay', json={}, headers=self.origin)
        self.assertEqual(response.status_code, 404)
