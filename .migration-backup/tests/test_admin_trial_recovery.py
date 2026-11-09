"""All trial recovery panel operations are mocked; no live account writes."""
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

from cryptography.fernet import Fernet

from streambot.bot import TelegramBot
from streambot.config import load_config
from streambot.service import CheckoutError, CheckoutService
from streambot.store import Store


class AdminTrialRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'test.sqlite3', Fernet.generate_key())
        self.config = load_config(env={'APP_MODE': 'demo', 'SUPPORT_ADMIN_ID': '900'})
        self.config.update(mode='live', panel_writes=True)
        self.panel = Mock()
        self.panel.prepare_generation.return_value = dict(
            generation_mode='panel', before_ids=[], post_attempted=True,
            package_id='275', prepared_at=int(time.time()))
        self.panel.create_account.return_value = dict(username='fake-user', password='fake-password')
        self.service = CheckoutService(self.config, self.store, Mock(), self.panel)
        self.order = self.service.create_trial(42)
        self.store.update(self.order['id'], status='review', credentials=None)
        self.sent = []
        self.bot = TelegramBot(self.service, api=lambda method, payload:
                               self.sent.append((method, payload)) or {'message_id': 1})
        self.recovery = self.bot.trial_recovery

    def preview(self):
        self.recovery.preview(900, self.order['id'])
        return self.store.unseal(self.store.metadata(self.recovery.key(900)))['nonce']

    def test_preview_never_queues_or_creates_and_warns_admin(self):
        self.preview()
        self.assertEqual(self.store.get(self.order['id'])['status'], 'review')
        self.panel.create_account.assert_not_called()
        text = self.sent[-1][1]['text']
        self.assertIn('Missing saved details alone are not proof', text)
        self.assertIn('same trial', text)

    def test_confirm_reuses_order_preserves_entitlement_and_records_audit(self):
        nonce = self.preview()
        self.recovery.confirm(900, nonce)
        self.assertEqual(self.store.get(self.order['id'])['status'], 'paid')
        audit = self.store.unseal(self.store.metadata('trial_admin_recovery:' + nonce))
        self.assertEqual(audit['administrator'], 900)
        self.assertEqual(audit['attestation'], 'creation_never_started')
        self.assertEqual(self.service.create_trial(42)['id'], self.order['id'])
        self.service.provision_pending()
        self.assertEqual(self.store.get(self.order['id'])['status'], 'fulfilled')
        self.panel.create_account.assert_called_once()
        self.assertEqual(self.panel.create_account.call_args.args[1:], ('', '', ''))
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM orders WHERE telegram_id=42').fetchone()[0], 1)

    def test_non_admin_cannot_list_preview_confirm_or_cancel(self):
        nonce = self.preview()
        for uid in (42, 901, True):
            with self.subTest(uid=uid):
                for action in (
                    lambda: self.recovery.message(uid, '/recovertrial', ''),
                    lambda: self.recovery.preview(uid, self.order['id']),
                    lambda: self.recovery.confirm(uid, nonce),
                    lambda: self.recovery.confirm(uid, nonce, cancel=True),
                ):
                    with self.assertRaises(CheckoutError):
                        action()
        self.assertEqual(self.store.get(self.order['id'])['status'], 'review')

    def test_may_have_been_submitted_and_legacy_credentials_are_blocked(self):
        for credentials in (
                {'generation_mode': 'panel', 'post_attempted': True},
                {'generation_mode': 'panel'},
                {'generation_mode': 'panel', 'post_attempted': 0},
                {'username': 'old', 'password': 'old'},
                {'generation_mode': 'panel', 'post_attempted': False, 'username': 'old'},
                {}):
            with self.subTest(credentials=credentials):
                self.store.update(self.order['id'], credentials=credentials)
                with self.assertRaisesRegex(CheckoutError, 'may already have started'):
                    self.preview()
        self.panel.create_account.assert_not_called()

    def test_proven_pre_post_marker_is_eligible(self):
        self.store.update(self.order['id'], credentials={
            'generation_mode': 'panel', 'post_attempted': False})
        self.recovery.confirm(900, self.preview())
        self.assertEqual(self.store.get(self.order['id'])['status'], 'paid')

    def test_cancel_expiry_stale_preview_and_replay_do_not_queue(self):
        nonce = self.preview()
        self.recovery.confirm(900, nonce, cancel=True)
        with self.assertRaises(CheckoutError):
            self.recovery.confirm(900, nonce)
        nonce = self.preview()
        draft = self.store.unseal(self.store.metadata(self.recovery.key(900)))
        draft['expires'] = 0
        self.store.metadata(self.recovery.key(900), self.store.seal(draft))
        with self.assertRaises(CheckoutError):
            self.recovery.confirm(900, nonce)
        nonce = self.preview()
        newer = self.preview()
        with self.assertRaises(CheckoutError):
            self.recovery.confirm(900, nonce)
        self.recovery.confirm(900, newer)
        with self.assertRaises(CheckoutError):
            self.recovery.confirm(900, newer)

    def test_changed_order_and_disabled_writes_are_blocked(self):
        nonce = self.preview()
        self.store.update(self.order['id'], credentials={
            'generation_mode': 'panel', 'post_attempted': True})
        with self.assertRaises(CheckoutError):
            self.recovery.confirm(900, nonce)
        self.store.update(self.order['id'], credentials=None)
        nonce = self.preview()
        self.store.update(self.order['id'], status='fulfilled')
        with self.assertRaises(CheckoutError):
            self.recovery.confirm(900, nonce)
        self.store.update(self.order['id'], status='review')
        nonce = self.preview()
        self.config['panel_writes'] = False
        with self.assertRaisesRegex(CheckoutError, 'disabled'):
            self.recovery.confirm(900, nonce)
        with self.assertRaisesRegex(CheckoutError, 'disabled'):
            self.preview()

    def test_concurrent_confirmation_queues_only_once(self):
        nonce = self.preview()
        def confirm(_):
            try:
                self.recovery.confirm(900, nonce)
                return True
            except CheckoutError:
                return False
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(confirm, range(4))), 1)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM metadata WHERE key LIKE 'trial_admin_recovery:%'").fetchone()[0], 1)

    def test_bot_private_command_listing_and_confirmation(self):
        self.bot.handle({'message': {
            'message_id': 1, 'from': {'id': 900}, 'chat': {'id': 900, 'type': 'private'},
            'text': '/recovertrial'}})
        self.assertIn(self.order['id'], str(self.sent[-1]))
        self.bot.handle({'message': {
            'message_id': 2, 'from': {'id': 900}, 'chat': {'id': 900, 'type': 'private'},
            'text': '/recovertrial ' + self.order['id']}})
        nonce = self.store.unseal(self.store.metadata(self.recovery.key(900)))['nonce']
        callback = {'id': 'test', 'from': {'id': 900}, 'data': 'tr:confirm:' + nonce,
                    'message': {'chat': {'id': -123, 'type': 'group'}}}
        self.bot.handle({'callback_query': callback})
        self.assertEqual(self.store.get(self.order['id'])['status'], 'review')
        callback['message']['chat'] = {'id': 900, 'type': 'private'}
        self.bot.handle({'callback_query': callback})
        self.assertEqual(self.store.get(self.order['id'])['status'], 'paid')

    def test_does_not_depend_on_reseller_or_notification_schema(self):
        with self.store.connection() as db:
            db.execute('DROP TABLE rs_settings')
            db.execute('DROP TABLE nt_contacts')
        restarted = CheckoutService(self.config, self.store, Mock(), self.panel)
        bot = TelegramBot(restarted, api=lambda *args: {'message_id': 1})
        bot.trial_recovery.preview(900, self.order['id'])
        nonce = self.store.unseal(self.store.metadata(self.recovery.key(900)))['nonce']
        bot.trial_recovery.confirm(900, nonce)
        self.assertEqual(self.store.get(self.order['id'])['status'], 'paid')
