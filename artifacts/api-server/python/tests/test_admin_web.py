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
