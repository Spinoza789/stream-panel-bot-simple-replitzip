"""The main menu follows the customer: active, expiring, expired; plus How to watch and the owner-written FAQ."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from cryptography.fernet import Fernet
from streambot.bot import TelegramBot
from streambot.config import load_config
from streambot.rates import Rates
from streambot.service import CheckoutError, CheckoutService
from streambot.store import Store

DAY = 86400


class MenuStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'db.sqlite3', Fernet.generate_key())
        self.service = CheckoutService(load_config(env={'APP_MODE': 'demo', 'SUPPORT_ADMIN_ID': '9001'}), self.store, Mock(), Mock(), rates=Rates(demo=True))
        self.calls = []
        self.bot = TelegramBot(self.service, api=lambda m, p: self.calls.append((m, p)) or {'message_id': 1})

    def tap(self, data, uid=42):
        self.bot.handle({'callback_query': {'id': 'c', 'from': {'id': uid}, 'data': data, 'message': {'chat': {'id': uid, 'type': 'private'}, 'message_id': 99}}})
        return [p for m, p in self.calls if m in ('sendMessage', 'editMessageText')][-1]

    def buttons(self, payload): return [b['callback_data'] for row in payload['reply_markup']['inline_keyboard'] for b in row]

    def subscribe(self, expires):
        order = self.service.create_order('month-1', 'usdc-ethereum', owner_telegram_id=42, request_key='k' + str(expires))['order']
        self.store.update(order['id'], status='fulfilled', credentials={'username': 'sub-user', 'password': 'sub-pass', 'panel_id': '900', 'expires_at': expires})
        return order

    def test_subscriber_sees_expiry_and_the_right_call_to_action(self):
        order = self.subscribe(int(time.time()) + 31 * DAY)
        menu = self.tap('menu')
        self.assertIn('🟢 Active until', menu['text']); self.assertIn('1 device', menu['text'])
        self.assertEqual(self.buttons(menu)[:2], ['menu:login', 'pay:renew:' + order['id']])
        self.assertNotIn('menu:trial', self.buttons(menu))
        login = self.tap('menu:login')
        self.assertIn('Username: sub-user', login['text']); self.assertEqual(login['parse_mode'], 'HTML')
        self.store.update(order['id'], credentials={'username': 'sub-user', 'password': 'sub-pass', 'panel_id': '900', 'expires_at': int(time.time()) + 3 * DAY - 60})
        menu = self.tap('menu')
        self.assertIn('🟠 Your subscription ends in 2 days', menu['text']); self.assertEqual(self.buttons(menu)[0], 'pay:renew:' + order['id'])
        self.store.update(order['id'], credentials={'username': 'sub-user', 'password': 'sub-pass', 'panel_id': '900', 'expires_at': int(time.time()) - DAY})
        menu = self.tap('menu')
        self.assertIn('🔴 Your subscription expired on', menu['text']); self.assertEqual(self.buttons(menu)[0], 'pay:renew:' + order['id'])
        account = self.tap('menu:account')
        self.assertIn('🔴 Expired on', account['text']); self.assertIn('nt:settings', self.buttons(account)); self.assertIn('Telegram ID 42', account['text'])

    def test_login_button_without_any_account_explains_what_to_do(self):
        self.assertIn('do not have a login yet', self.tap('menu:login')['text'])

    def test_how_to_watch_lists_devices_and_shows_codes(self):
        picker = self.tap('menu:watch')
        self.assertEqual(self.buttons(picker), ['menu:watch:firestick', 'menu:watch:apple', 'menu:watch:android', 'menu'])
        fire = self.tap('menu:watch:firestick')
        self.assertIn('Downloader', fire['text']); self.assertIn('<code>2976199</code>', fire['text']); self.assertIn('menu:login', self.buttons(fire))
        self.assertIn('BA896705', self.tap('menu:watch:apple')['text'])
        self.assertIn('https://', self.tap('menu:watch:android')['text'])
        self.assertIn('Which device', self.tap('menu:watch:toaster')['text'])  # unknown device falls back to the picker

    def test_faq_is_hidden_until_the_owner_writes_one(self):
        self.assertNotIn('menu:faq', self.buttons(self.tap('menu')))
        self.assertIn('No questions have been added yet', self.tap('menu:faq')['text'])
        with self.assertRaises(CheckoutError): self.service.faq.save(42, [dict(question='q', answer='a')])  # not the owner
        with self.assertRaises(CheckoutError): self.service.faq.save(9001, [dict(question='', answer='a')])
        self.service.faq.save(9001, [dict(question='How long does payment take?', answer='About 3 minutes <on Ethereum>.'), dict(question='Refunds?', answer='Contact support.')])
        menu = self.tap('menu')
        self.assertIn('menu:faq', self.buttons(menu)); self.assertIn('menu:contact', self.buttons(menu))
        listing = self.tap('menu:faq')
        self.assertEqual(self.buttons(listing)[:2], ['menu:faq:0', 'menu:faq:1'])
        answer = self.tap('menu:faq:0')
        self.assertIn('How long does payment take?', answer['text']); self.assertIn('&lt;on Ethereum&gt;', answer['text'])
        self.assertIn('Tap a question', self.tap('menu:faq:7')['text'])  # out of range falls back to the list
        self.service.faq.save(9001, [])
        self.assertNotIn('menu:faq', self.buttons(self.tap('menu')))


if __name__ == '__main__':
    unittest.main()
