"""Private operations use signed gateway identities, never browser-supplied roles."""
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch
from cryptography.fernet import Fernet
from streambot.config import load_config
from streambot.service import CheckoutService, CheckoutError
from streambot.store import Store
from streambot.web import create_app
from streambot.admin_web import WebTrialRecovery


class AdminWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'db.sqlite3', Fernet.generate_key())
        config = load_config(env={'APP_MODE': 'demo'})
        config.update(mode='live', panel_writes=True)
        self.panel = Mock()
        self.service = CheckoutService(config, self.store, Mock(), self.panel)
        self.order = self.service.create_trial(42)
        self.store.update(self.order['id'], status='review', credentials=None)
        self.key = 'a' * 64
        self.env = patch.dict(os.environ, STREAMBOT_ADMIN_BRIDGE_KEY=self.key)
        self.env.start(); self.addCleanup(self.env.stop)
        self.app = create_app(self.service)
        self.client = self.app.test_client()
        self.actor = 'replit:test_owner:' + '1' * 64
        self.recovery = WebTrialRecovery(self.service)

    def headers(self, method, target, raw='', actor=None, timestamp=None, nonce=None):
        actor = actor or self.actor
        timestamp = str(timestamp or int(time.time()))
        nonce = nonce or secrets.token_hex(16)
        parts = [method, target, actor, timestamp, nonce, hashlib.sha256(raw.encode()).hexdigest()]
        signature = hmac.new(self.key.encode(), '\n'.join(parts).encode(), hashlib.sha256).hexdigest()
        return {'Content-Type': 'application/json', 'X-Streamline-Actor': actor,
                'X-Streamline-Time': timestamp, 'X-Streamline-Nonce': nonce,
                'X-Streamline-Signature': signature}

    def call(self, path, data=None, **kwargs):
        method = 'GET' if data is None else 'POST'
        target = '/api/_admin' + path
        raw = '' if data is None else json.dumps(data)
        return self.client.open(target, method=method, data=raw,
                                headers=self.headers(method, target, raw, **kwargs))

    def preview(self):
        result = self.call('/orders/' + self.order['id'] + '/recovery', {})
        self.assertEqual(result.status_code, 200)
        return result.json['nonce']

    def test_owner_manages_resellers_reports_and_rate_card_through_the_bridge(self):
        finance = self.service.resellers.finance
        finance.register(777, 'shop_one'); finance.account_status(self.actor, 777, 'active', 'Approved from the website')
        finance.register(778, 'shop_two')
        page = self.call('/resellers?q=shop').json
        self.assertEqual({r['telegramId'] for r in page['items']}, {777, 778})
        one = [r for r in page['items'] if r['telegramId'] == 777][0]
        self.assertEqual((one['status'], one['available'], one['customers']), ('active', 0, 0))
        credited = self.call('/resellers/777/credits', {'movement': 25, 'reason': 'bank:TEST-REF-1', 'requestKey': 'web-adjust-0001'}).json
        self.assertEqual(credited['reseller']['available'], 25)
        self.assertEqual(credited['history'][0]['movement'], 25)
        # the same request key is idempotent; a bad one is refused
        self.assertEqual(self.call('/resellers/777/credits', {'movement': 25, 'reason': 'bank:TEST-REF-1', 'requestKey': 'web-adjust-0001'}).json['reseller']['available'], 25)
        self.assertEqual(self.call('/resellers/777/credits', {'movement': 5, 'reason': 'x', 'requestKey': 'bad'}).status_code, 400)
        suspended = self.call('/resellers/777/status', {'status': 'suspended', 'reason': 'Chargeback dispute'}).json
        self.assertEqual(suspended['reseller']['status'], 'suspended')
        self.assertEqual(self.call('/resellers/777/status', {'status': 'deleted', 'reason': 'nope'}).status_code, 400)
        self.assertIn(self.call('/resellers/1').status_code, (400, 404))
        with self.store.connection() as db:
            audit = db.execute("SELECT administrator,details FROM rs_audit WHERE action='suspended'").fetchone()
        self.assertEqual(audit['administrator'], 0)
        self.assertIn(self.actor, audit['details'])
        reports = self.call('/reports?months=6').json
        self.assertIn('months', reports)
        self.assertEqual(len(reports['resellers']), 2)
        card = self.call('/ratecard').json
        self.assertEqual(card['packages'][0]['id'], '100')
        updated = self.call('/ratecard', {'category': 'package', 'values': ['100', 12000, 40, True], 'reason': 'Price test'}).json
        self.assertEqual((updated['packages'][0]['pricePence'], updated['packages'][0]['credits']), (12000, 40))
        updated = self.call('/ratecard', {'category': 'cost', 'values': [1, 1, 2], 'reason': 'Cost test'}).json
        self.assertEqual([c for c in updated['costs'] if c['months'] == 1 and c['connections'] == 1][0]['credits'], 2)
        self.assertEqual(self.call('/ratecard', {'category': 'cost', 'values': [2, 1, 2], 'reason': 'bad months'}).status_code, 400)
        overview = self.call('/overview').json
        self.assertEqual(overview['activeResellers'], 0)  # 777 is suspended, 778 pending
        self.assertIn('revenueMonthGbp', overview)
        qr = self.call('/auth/qr', {'uri': 'otpauth://totp/Streamline%20Admin:owner%40example.com?secret=JBSWY3DPEHPK3PXP&issuer=Streamline%20Admin'}).json
        self.assertTrue(qr['qr'].startswith('data:image/png;base64,'))
        self.assertEqual(self.call('/auth/qr', {'uri': 'https://evil.example'}).status_code, 400)

    def test_all_routes_reject_browser_identity_headers(self):
        for method, path in [('GET', '/overview'), ('GET', '/orders'), ('GET', '/status'),
                             ('GET', '/orders/' + self.order['id']),
                             ('POST', '/orders/' + self.order['id'] + '/recovery'),
                             ('POST', '/recovery/confirm')]:
            result = self.client.open('/api/_admin' + path, method=method, json={},
                                      headers={'X-Streamline-Actor': self.actor})
            self.assertEqual(result.status_code, 401)
        self.panel.create_account.assert_not_called()

    def test_signed_read_is_real_and_sanitized(self):
        overview = self.call('/overview').json
        self.assertEqual((overview['total'], overview['review'], overview['trials']), (1, 1, 1))
        page = self.call('/orders?kind=trial&page=1').json
        self.assertEqual(page['total'], 1)
        self.assertEqual(self.call('/orders?q=missing').json['total'], 0)
        detail = self.call('/orders/' + self.order['id']).json
        self.assertTrue(detail['recoveryEligible'])
        serialized = json.dumps(detail)
        self.assertNotIn('token_hash', serialized)
        self.assertNotIn('credentials":', serialized)
        self.assertEqual(self.call('/status').status_code, 200)

    def test_invalid_filters_and_unknown_order(self):
        for query in ['page=0', 'page=bad', 'kind=admin', 'status=hack', 'q=' + 'a' * 81]:
            self.assertEqual(self.call('/orders?' + query).status_code, 400)
        self.assertEqual(self.call('/orders/' + 'a' * 24).status_code, 404)

    def test_signature_binds_method_path_body_actor_and_time(self):
        path = '/api/_admin/recovery/confirm'
        headers = self.headers('POST', path, '{}')
        self.assertEqual(self.client.post(path, data='{"cancel":true}', headers=headers).status_code, 401)
        self.assertEqual(self.call('/overview', timestamp=int(time.time()) - 90).status_code, 401)
        self.assertEqual(self.call('/overview', actor='telegram:900').status_code, 401)

    def test_replayed_bridge_request_denied(self):
        path = '/api/_admin/overview'
        headers = self.headers('GET', path)
        self.assertEqual(self.client.get(path, headers=headers).status_code, 200)
        self.assertEqual(self.client.get(path, headers=headers).status_code, 409)

    def test_preview_then_explicit_confirm_reuses_trial(self):
        nonce = self.preview()
        self.assertEqual(self.store.get(self.order['id'])['status'], 'review')
        self.panel.create_account.assert_not_called()
        bad = self.call('/recovery/confirm', dict(nonce=nonce, attestation=False, cancel=False))
        self.assertEqual(bad.status_code, 400)
        good = self.call('/recovery/confirm', dict(nonce=nonce, attestation=True, cancel=False))
        self.assertTrue(good.json['queued'])
        self.assertEqual(self.store.get(self.order['id'])['status'], 'paid')
        audit = self.store.unseal(self.store.metadata('trial_admin_recovery:' + nonce))
        self.assertEqual(audit['administrator'], self.actor)
        self.assertEqual(self.service.create_trial(42)['id'], self.order['id'])
        self.assertEqual(self.call('/recovery/confirm', dict(nonce=nonce, attestation=True, cancel=False)).status_code, 400)
        self.panel.create_account.assert_not_called()

    def test_session_bound_cancel_and_expiry(self):
        nonce = self.preview()
        self.assertEqual(self.call('/recovery/confirm', dict(nonce=nonce, attestation=True, cancel=False),
                                   actor='replit:test_owner:' + '2' * 64).status_code, 400)
        self.assertFalse(self.call('/recovery/confirm', dict(nonce=nonce, attestation=False, cancel=True)).json['queued'])
        self.assertEqual(self.store.get(self.order['id'])['status'], 'review')
        nonce = self.preview()
        saved = self.store.unseal(self.store.metadata(self.recovery.key(self.actor)))
        saved['expires'] = int(time.time()) - 1
        self.store.metadata(self.recovery.key(self.actor), self.store.seal(saved))
        self.assertEqual(self.call('/recovery/confirm', dict(nonce=nonce, attestation=True, cancel=False)).status_code, 400)

    def test_changed_order_uncertain_generation_and_disabled_writes(self):
        nonce = self.preview()
        self.store.update(self.order['id'], status='fulfilled')
        self.assertEqual(self.call('/recovery/confirm', dict(nonce=nonce, attestation=True, cancel=False)).status_code, 400)
        self.store.update(self.order['id'], status='review', credentials={
            'generation_mode': 'panel', 'post_attempted': True})
        self.assertFalse(self.call('/orders/' + self.order['id']).json['recoveryEligible'])
        self.assertEqual(self.call('/orders/' + self.order['id'] + '/recovery', {}).status_code, 400)
        self.store.update(self.order['id'], credentials=None)
        self.service.config['panel_writes'] = False
        self.assertFalse(self.call('/orders/' + self.order['id']).json['recoveryEligible'])

    def test_concurrent_confirmation_claims_once(self):
        nonce = self.preview()
        def confirm():
            try: self.recovery.confirm(self.actor, nonce); return True
            except CheckoutError: return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sum(executor.map(lambda _: confirm(), range(2))), 1)

    def test_missing_optional_schema_does_not_block_recovery(self):
        with self.store.connection() as db:
            db.execute('DROP TABLE nt_contacts')
        self.assertFalse(self.call('/status').json['notificationSchema'])
        nonce = self.preview()
        self.assertTrue(self.call('/recovery/confirm', dict(nonce=nonce, attestation=True, cancel=False)).json['queued'])

    def test_owner_claim_binds_immutable_subject_once(self):
        self.assertFalse(self.call('/owner/status').json['claimed'])
        self.assertTrue(self.call('/owner/claim', {}).json['matches'])
        self.assertTrue(self.call('/owner/status', actor='replit:test_owner:' + '2' * 64).json['matches'])
        self.assertFalse(self.call('/owner/status', actor='replit:other_user:' + '1' * 64).json['matches'])
        self.assertEqual(self.call('/owner/claim', {}, actor='replit:other_user:' + '1' * 64).status_code, 409)

    def password_profile(self, **changes):
        return dict(id='a' * 32, username='test_owner', email='owner@example.test',
                    passwordHash='scrypt-v1$' + 'a' * 32 + '$' + 'b' * 128,
                    version=1, **changes)

    def test_password_setup_is_atomic_encrypted_and_never_overwrites_an_owner(self):
        profile = self.password_profile()
        actor = 'local:' + profile['id'] + ':' + '1' * 64
        self.assertFalse(self.call('/auth/status').json['configured'])
        self.assertEqual(self.call('/auth/setup', profile).status_code, 403)
        self.store.metadata('web_admin_owner', 'replit:previous_owner')
        result = self.call('/auth/setup', profile, actor=actor)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(self.call('/auth/status').json['configured'])
        self.assertEqual(self.store.metadata('web_admin_owner'), 'local:' + profile['id'])
        self.assertNotIn('test_owner', self.store.metadata('web_local_owner'))
        self.assertNotIn('scrypt', self.store.metadata('web_local_owner'))
        self.assertEqual(self.call('/auth/credentials').json['profile'], profile)
        self.assertEqual(self.call('/auth/setup', profile, actor=actor).status_code, 409)
        self.assertEqual(self.call('/owner/claim', {}).status_code, 409)
        with self.store.connection() as db:
            audits = db.execute("SELECT value FROM metadata WHERE key LIKE 'web_owner_password_setup:%'").fetchall()
        self.assertEqual(len(audits), 1)
        self.assertEqual(self.store.unseal(audits[0][0])['previous_owner'], 'replit:previous_owner')

    def test_password_settings_require_owner_and_exact_credential_version(self):
        profile = self.password_profile()
        actor = 'local:' + profile['id'] + ':' + '1' * 64
        self.call('/auth/setup', profile, actor=actor)
        updated = dict(profile, username='updated_owner', version=2)
        body = dict(profile=updated, expectedVersion=1)
        self.assertEqual(self.call('/auth/update', body).status_code, 403)
        self.assertEqual(self.call('/auth/update', body, actor=actor).status_code, 200)
        self.assertEqual(self.call('/auth/update', body, actor=actor).status_code, 409)
        self.assertEqual(self.call('/auth/credentials').json['profile'], updated)

    def test_local_password_sessions_can_preview_and_cancel_recovery(self):
        actor = 'local:' + 'a' * 32 + ':' + '1' * 64
        result = self.call('/orders/' + self.order['id'] + '/recovery', {}, actor=actor)
        self.assertEqual(result.status_code, 200)
        response = self.call('/recovery/confirm', dict(nonce=result.json['nonce'],
                                                     attestation=False, cancel=True), actor=actor)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.get(self.order['id'])['status'], 'review')

    def test_password_brute_force_limits_are_persistent_and_namespaced(self):
        buckets = ['a' * 64, 'b' * 64]
        for _ in range(5):
            self.assertTrue(self.call('/auth/attempt', dict(kind='setup', buckets=buckets)).json['allowed'])
        self.assertFalse(self.call('/auth/attempt', dict(kind='setup', buckets=buckets)).json['allowed'])
        self.assertTrue(self.call('/auth/attempt', dict(kind='login', buckets=buckets)).json['allowed'])
        self.assertEqual(self.call('/auth/attempt', dict(kind='setup', buckets=['bad'])).status_code, 400)
