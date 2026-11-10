"""Reseller web portal: Telegram one-time link sign-in, recovery email + password, and per-reseller scoping."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from cryptography.fernet import Fernet

from streambot.config import load_config
from streambot.service import CheckoutService, CheckoutError
from streambot.store import Store
from streambot.web import create_app
from streambot.reseller_web import hash_password, check_password

ORIGIN = 'http://localhost:8090'


class ResellerWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'db.sqlite3', Fernet.generate_key())
        self.config = load_config(env={'APP_MODE': 'demo', 'SUPPORT_ADMIN_ID': '9001'})
        self.service = CheckoutService(self.config, self.store, Mock(), Mock())
        self.r = self.service.resellers
        self.web = self.r.web
        for uid in (42, 43):
            self.r.finance.register(uid, 'reseller_' + str(uid))
            self.r.finance.account_status(9001, uid, 'active', 'test')
        self.r.finance.register(77, 'pending_person')
        self.app = create_app(self.service)
        self.client = self.app.test_client()

    def post(self, path, data, **kwargs):
        return self.client.post(path, json=data, headers={'Origin': ORIGIN}, **kwargs)

    def sign_in(self, uid=42):
        code = self.web.issue_code(uid)
        response = self.post('/api/reseller/session/code', {'code': code})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    # ---- links and sessions ---------------------------------------------------------
    def test_link_points_at_the_portal_and_signs_in_once(self):
        code = self.web.issue_code(42)
        self.assertTrue(self.web.login_url(code).startswith(ORIGIN + '/reseller/#code='))
        self.assertEqual(self.client.get('/api/reseller/me').status_code, 401)
        me = self.sign_in()
        self.assertEqual((me['telegram_id'], me['status'], me['username']), (42, 'active', 'reseller_42'))
        self.assertEqual(me['credits'], {'available': 0, 'reserved': 0, 'balance': 0})
        # the cookie carries the session; the code is spent
        self.assertEqual(self.client.get('/api/reseller/me').get_json()['telegram_id'], 42)
        self.assertEqual(self.post('/api/reseller/session/code', {'code': code}).status_code, 400)
        self.assertEqual(self.post('/api/reseller/signout', {}).status_code, 200)
        self.assertEqual(self.client.get('/api/reseller/me').status_code, 401)

    def test_expired_or_unknown_codes_are_refused(self):
        code = self.web.issue_code(42)
        with self.store.connection() as db:
            db.execute('UPDATE rs_web_codes SET expires_at=?', (int(time.time()) - 1,))
        self.assertEqual(self.post('/api/reseller/session/code', {'code': code}).status_code, 400)
        self.assertEqual(self.post('/api/reseller/session/code', {'code': 'x' * 40}).status_code, 400)
        self.assertEqual(self.post('/api/reseller/session/code', {'code': 'short'}).status_code, 400)
        with self.assertRaises(CheckoutError):
            self.web.issue_code(555)  # not a reseller

    def test_unpaid_resellers_can_sign_in_and_buy_but_not_create_yet(self):
        me = self.sign_in(77)
        self.assertEqual(me['status'], 'pending')
        self.assertEqual(self.post('/api/reseller/purchase', {'package_id': '100', 'asset_id': 'usdc-ethereum'}).status_code, 201)
        self.assertEqual(self.post('/api/reseller/operations/preview',
                                   {'kind': 'trial', 'months': 0, 'connections': 1, 'adult': False}).status_code, 400)

    def test_cookie_is_http_only_and_posts_must_be_same_origin(self):
        code = self.web.issue_code(42)
        response = self.post('/api/reseller/session/code', {'code': code})
        cookie = response.headers.get('Set-Cookie', '')
        self.assertIn('rs_session=', cookie)
        self.assertIn('HttpOnly', cookie)
        self.assertIn('Path=/api/reseller', cookie)
        self.assertEqual(self.client.post('/api/reseller/signout', json={}, headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/reseller/me').status_code, 200)

    # ---- recovery email + password ---------------------------------------------------
    def test_recovery_email_and_password_sign_in(self):
        self.sign_in()
        self.assertEqual(self.post('/api/reseller/account', {'email': 'nope', 'password': 'long enough password'}).status_code, 400)
        self.assertEqual(self.post('/api/reseller/account', {'email': 'a@b.co', 'password': 'short'}).status_code, 400)
        saved = self.post('/api/reseller/account', {'email': ' Reseller@Example.com ', 'password': 'correct horse battery'})
        self.assertEqual(saved.get_json()['login'], {'email': 'reseller@example.com', 'has_password': True})
        # changing it needs the current password
        self.assertEqual(self.post('/api/reseller/account', {'email': 'new@example.com', 'password': 'another long one'}).status_code, 400)
        self.assertEqual(self.post('/api/reseller/account', {'email': 'new@example.com', 'password': 'another long one',
                                                              'current_password': 'correct horse battery'}).status_code, 200)
        self.post('/api/reseller/signout', {})
        fresh = self.app.test_client()
        bad = fresh.post('/api/reseller/session/password', json={'email': 'new@example.com', 'password': 'wrong wrong wrong'}, headers={'Origin': ORIGIN})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.get_json()['error'], 'Email or password is incorrect.')
        unknown = fresh.post('/api/reseller/session/password', json={'email': 'ghost@example.com', 'password': 'wrong wrong wrong'}, headers={'Origin': ORIGIN})
        self.assertEqual(unknown.get_json()['error'], 'Email or password is incorrect.')
        good = fresh.post('/api/reseller/session/password', json={'email': 'New@Example.com', 'password': 'another long one'}, headers={'Origin': ORIGIN})
        self.assertEqual(good.status_code, 200)
        self.assertEqual(good.get_json()['telegram_id'], 42)

    def test_email_is_unique_across_resellers(self):
        self.web.set_login(42, 'shared@example.com', 'password number one')
        with self.assertRaises(CheckoutError):
            self.web.set_login(43, 'shared@example.com', 'password number two')

    def test_password_hashes_are_salted_scrypt(self):
        one, two = hash_password('same password'), hash_password('same password')
        self.assertNotEqual(one, two)
        self.assertTrue(one.startswith('scrypt$16384$8$1$'))
        self.assertTrue(check_password('same password', one))
        self.assertFalse(check_password('other password', one))
        self.assertFalse(check_password('same password', 'garbage'))

    # ---- scoped data and actions ---------------------------------------------------------
    def test_records_actions_and_purchases_are_scoped_to_the_signed_in_reseller(self):
        self.r.finance.adjust(9001, 42, 10, 'test funding', 'fund-42')
        self.sign_in()
        me = self.client.get('/api/reseller/me').get_json()
        self.assertEqual(me['credits']['available'], 10)
        preview = self.post('/api/reseller/operations/preview',
                            {'kind': 'create', 'months': 1, 'connections': 2, 'adult': False, 'customer_ref': 'Web customer'})
        self.assertEqual(preview.status_code, 200, preview.get_json())
        body = preview.get_json()
        self.assertEqual((body['preview']['cost'], body['preview']['remaining']), (2, 8))
        self.assertEqual(self.post('/api/reseller/operations/confirm', {'nonce': 'not-a-nonce'}).status_code, 400)
        confirmed = self.post('/api/reseller/operations/confirm', {'nonce': body['nonce']})
        self.assertEqual(confirmed.status_code, 201)
        oid = confirmed.get_json()['operation']['id']
        again = self.post('/api/reseller/operations/confirm', {'nonce': body['nonce']})  # a retried confirm is idempotent
        self.assertEqual(again.get_json()['operation']['id'], oid)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM rs_operations').fetchone()[0], 1)
        self.r.process()
        op = self.client.get('/api/reseller/operations/' + oid).get_json()['operation']
        self.assertEqual(op['status'], 'succeeded')
        self.assertNotIn('provider_context', op)
        listing = self.client.get('/api/reseller/subscriptions?filter=active').get_json()
        self.assertEqual(len(listing['items']), 1)
        self.assertEqual(listing['items'][0]['customer_ref'], 'Web customer')
        self.assertNotIn('credentials', listing['items'][0])
        detail = self.client.get('/api/reseller/subscriptions/' + listing['items'][0]['id']).get_json()
        self.assertTrue(detail['record']['credentials']['username'])
        self.assertNotIn('reseller_id', detail['record'])
        self.assertEqual(self.client.get('/api/reseller/me').get_json()['credits']['available'], 8)
        history = self.client.get('/api/reseller/history').get_json()
        self.assertTrue(any(r['movement'] == -2 for r in history['items']))
        quote = self.post('/api/reseller/purchase', {'package_id': '100', 'asset_id': 'usdc-ethereum'})
        self.assertEqual(quote.status_code, 201, quote.get_json())
        self.assertTrue(quote.get_json()['checkout'].startswith('/#order='))
        self.assertEqual(quote.get_json()['order']['status'], 'pending')
        # another reseller sees none of it
        other = self.app.test_client()
        other.post('/api/reseller/session/code', json={'code': self.web.issue_code(43)}, headers={'Origin': ORIGIN})
        self.assertEqual(other.get('/api/reseller/subscriptions?filter=all').get_json()['items'], [])
        self.assertEqual(other.get('/api/reseller/subscriptions/' + listing['items'][0]['id']).status_code, 404)
        self.assertEqual(other.get('/api/reseller/operations/' + oid).status_code, 404)

    def test_portal_page_and_assets_are_served(self):
        page = self.client.get('/reseller/')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Sign in with Telegram', page.data)
        for name in ('reseller.js', 'reseller.css'):
            response = self.client.get('/reseller/static/' + name)
            self.assertEqual(response.status_code, 200)
            response.close()
        self.assertEqual(self.client.get('/reseller/static/index.html').status_code, 404)
        self.assertEqual(self.client.get('/reseller').status_code, 302)

    def test_sign_out_everywhere_drops_every_session(self):
        self.sign_in()
        second = self.app.test_client()
        second.post('/api/reseller/session/code', json={'code': self.web.issue_code(42)}, headers={'Origin': ORIGIN})
        self.assertEqual(second.get('/api/reseller/me').status_code, 200)
        self.assertEqual(self.post('/api/reseller/signout-everywhere', {}).status_code, 200)
        self.assertEqual(second.get('/api/reseller/me').status_code, 401)
        self.assertEqual(self.client.get('/api/reseller/me').status_code, 401)


if __name__ == '__main__':
    unittest.main()
