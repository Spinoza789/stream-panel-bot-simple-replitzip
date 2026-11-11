"""Main menu after the free trial: no second trial for customers; resellers are sent to their own trial tool."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from cryptography.fernet import Fernet
from streambot.bot import TelegramBot
from streambot.config import load_config
from streambot.service import CheckoutService
from streambot.store import Store


class TrialMenuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'db.sqlite3', Fernet.generate_key())
        self.service = CheckoutService(load_config(env={'APP_MODE': 'demo', 'SUPPORT_ADMIN_ID': '9001'}), self.store, Mock(), Mock())
        self.calls = []
        self.bot = TelegramBot(self.service, api=lambda m, p: self.calls.append((m, p)) or {'message_id': 1})

    def menu(self, uid):
        self.bot.handle({'message': {'message_id': len(self.calls) + 1, 'from': {'id': uid}, 'chat': {'id': uid, 'type': 'private'}, 'text': '/start'}})
        return self.calls[-1][1]

    def buttons(self, payload):
        return [b['callback_data'] for row in payload['reply_markup']['inline_keyboard'] for b in row]

    def test_menu_changes_once_the_trial_is_delivered(self):
        self.assertEqual(self.buttons(self.menu(42))[0], 'menu:trial')
        order = self.service.create_trial(42)
        self.assertEqual(self.buttons(self.menu(42))[0], 'menu:trial')  # still queued: the button shows its status
        self.store.update(order['id'], status='fulfilled', credentials={'username': 'u', 'password': 'p'})
        shown = self.menu(42)
        self.assertEqual(self.buttons(shown)[0], 'menu:plans'); self.assertIn('Trial used', str(shown['reply_markup'])); self.assertIn('has been used', shown['text'])
        # the account screen no longer offers to start a trial, and My orders lists the trial
        self.bot.handle({'callback_query': {'id': 'c1', 'from': {'id': 42}, 'data': 'menu:account', 'message': {'chat': {'id': 42, 'type': 'private'}, 'message_id': 1}}})
        self.assertNotIn('Start free trial', str(self.calls[-1][1]['reply_markup']))
        self.bot.handle({'callback_query': {'id': 'c2', 'from': {'id': 42}, 'data': 'pay:orders', 'message': {'chat': {'id': 42, 'type': 'private'}, 'message_id': 1}}})
        self.assertIn('24-hour trial · fulfilled', str(self.calls[-1][1]['reply_markup']))
        # an active reseller is pointed at the reseller trial tool instead
        finance = self.service.resellers.finance
        finance.register(42, 'shop'); finance.account_status(9001, 42, 'active', 'test')
        self.assertEqual(self.buttons(self.menu(42))[0], 'rs:trial')
        # a customer who never had a trial still sees the offer
        self.assertEqual(self.buttons(self.menu(43))[0], 'menu:trial')


if __name__ == '__main__':
    unittest.main()
