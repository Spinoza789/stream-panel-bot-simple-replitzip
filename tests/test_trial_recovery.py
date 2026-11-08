"""Trial recovery uses the same order and credentials; all panel calls are fake."""
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

from cryptography.fernet import Fernet

from streambot.bot import TelegramBot
from streambot.config import load_config
from streambot.panel import PanelError, ProvisioningUncertain
from streambot.service import CheckoutError, CheckoutService
from streambot.store import Store


class TrialRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name) / 'test.sqlite3', Fernet.generate_key())
        self.config = load_config(env={'APP_MODE': 'demo'})
        self.config.update(mode='live', panel_writes=True)
        self.panel = Mock()
        self.panel.find_account.return_value = None
        self.panel.create_account.side_effect = lambda package, user, password, description: {
            'username': user, 'password': password, 'package_id': package, 'server_url': 'test server'}
        self.service = CheckoutService(self.config, self.store, Mock(), self.panel)
        self.order = self.service.create_trial(42)
        self.credentials = dict(username='test-user', password='test-secret',
                                package_id=str(self.config['trial_package_id']))
        self.store.update(self.order['id'], status='review', credentials=self.credentials)
        self.store.metadata('trial_recheck_after:' + self.order['id'], 0)
        self.calls = []
        self.bot = TelegramBot(self.service, api=lambda method, payload: self.calls.append((method, payload)) or {'message_id': 1})

    def test_absent_account_requeues_original_once_and_reuses_credentials(self):
        first = self.service.retry_trial(42)
        again = self.service.retry_trial(42)
        self.assertEqual((first['id'], again['id']), (self.order['id'], self.order['id']))
        self.assertEqual(first['status'], 'paid')
        self.panel.find_account.assert_called_once_with(self.credentials['username'])
        self.service.provision_pending()
        fulfilled = self.store.trial(42)
        self.assertEqual(fulfilled['status'], 'fulfilled')
        self.assertEqual(fulfilled['credentials']['password'], self.credentials['password'])
        self.panel.create_account.assert_called_once()
        self.assertEqual(self.service.create_trial(42)['id'], self.order['id'])

    def test_existing_matching_account_is_delivered_without_creation(self):
        self.panel.find_account.return_value = self.credentials
        result = self.service.retry_trial(42)
        self.assertEqual(result['status'], 'fulfilled')
        self.assertEqual(result['credentials'], self.credentials)
        self.panel.create_account.assert_not_called()

    def test_different_owner_and_mismatched_credentials_never_retry(self):
        with self.assertRaises(CheckoutError):
            self.service.retry_trial(43)
        self.panel.find_account.assert_not_called()
        self.panel.find_account.return_value = dict(self.credentials, password='different-secret')
        with self.assertRaisesRegex(CheckoutError, 'No retry was queued'):
            self.service.retry_trial(42)
        self.assertEqual(self.store.trial(42)['status'], 'review')
        self.panel.create_account.assert_not_called()

    def test_lookup_failure_and_cooldown_do_not_requeue(self):
        self.panel.find_account.side_effect = PanelError('Cannot read listing')
        with self.assertRaisesRegex(CheckoutError, 'No retry was queued'):
            self.service.retry_trial(42)
        self.store.metadata('trial_recheck_after:' + self.order['id'], int(time.time()) + 300)
        with self.assertRaisesRegex(CheckoutError, 'Please wait'):
            self.service.retry_trial(42)
        self.assertEqual(self.store.trial(42)['status'], 'review')
        self.panel.find_account.assert_called_once()

    def test_concurrent_checks_cannot_queue_two_creations(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.service.retry_trial, [42, 42]))
        self.assertTrue(all(result['id'] == self.order['id'] for result in results))
        self.service.provision_pending()
        self.panel.create_account.assert_called_once()

    def test_uncertain_retry_stops_in_review_and_enforces_cooldown(self):
        self.service.retry_trial(42)
        self.panel.create_account.side_effect = ProvisioningUncertain('Unverified creation')
        self.service.provision_pending()
        self.assertEqual(self.store.trial(42)['status'], 'review')
        with self.assertRaisesRegex(CheckoutError, 'Please wait'):
            self.service.retry_trial(42)
        self.panel.create_account.assert_called_once()

    def test_bot_review_button_and_retry_command_are_functional(self):
        message = {'message_id': 1, 'from': {'id': 42}, 'chat': {'id': 42, 'type': 'private'}, 'text': '/trial'}
        self.bot.handle({'message': message})
        sent = [payload for method, payload in self.calls if method == 'sendMessage'][-1]
        self.assertEqual(sent['reply_markup']['inline_keyboard'][0][0]['callback_data'], 'menu:retrytrial')
        self.bot.handle({'message': dict(message, message_id=2, text='/retrytrial')})
        self.assertEqual(self.store.trial(42)['status'], 'paid')
        self.assertIn('being prepared', [p['text'] for m, p in self.calls if m == 'sendMessage'][-1])

    def test_callback_recovery_and_disabled_writes(self):
        self.config['panel_writes'] = False
        with self.assertRaisesRegex(CheckoutError, 'disabled'):
            self.service.retry_trial(42)
        self.assertEqual(self.store.trial(42)['status'], 'review')
        self.config['panel_writes'] = True
        self.bot.handle({'callback_query': {
            'id': 'retry-click', 'from': {'id': 42}, 'data': 'menu:retrytrial',
            'message': {'chat': {'id': 42, 'type': 'private'}}}})
        self.assertEqual(self.store.trial(42)['status'], 'paid')
