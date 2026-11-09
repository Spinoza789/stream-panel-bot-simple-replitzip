"""Telegram membership navigation tests; no network or live database access."""
import copy
import unittest
from pathlib import Path
from types import SimpleNamespace

from streambot.bot import TelegramBot, TelegramError
from streambot.config import load_config


class MemoryStore:
    def __init__(self):
        self.values = {}

    def limit(self, *args):
        return True

    def metadata(self, key, value=None):
        if value is not None:
            self.values[key] = value
        return self.values.get(key)


class TelegramAPI:
    def __init__(self):
        self.calls = []
        self.ack_error = None

    def __call__(self, method, payload):
        self.calls.append((method, copy.deepcopy(payload)))
        if method == 'answerCallbackQuery' and self.ack_error:
            raise TelegramError(self.ack_error, method)
        return {'message_id': 1}


class MembershipMenuTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'config.json'
        self.config = load_config(path, env={'APP_MODE': 'demo'})
        self.api = TelegramAPI()
        self.store = MemoryStore()
        service=SimpleNamespace(config=self.config,store=self.store,
                                resellers=SimpleNamespace(member=lambda uid:None))
        self.bot = TelegramBot(service, api=self.api)

    def click(self, action, private=True):
        self.api.calls.clear()
        self.bot.handle({'callback_query': {
            'id': 'test-callback',
            'from': {'id': 42},
            'message': {'chat': {'id': 42 if private else -100, 'type': 'private' if private else 'group'}},
            'data': action,
        }})
        sent = [payload for method, payload in self.api.calls if method == 'sendMessage']
        return sent[-1] if sent else None

    @staticmethod
    def callbacks(message):
        return [button['callback_data'] for row in message['reply_markup']['inline_keyboard'] for button in row]

    def test_exact_package_mappings_and_matching_prices(self):
        adult = {1: ['140', '141', '142'], 3: ['134', '135', '136'],
                 6: ['128', '129', '130'], 12: ['116', '117', '118']}
        original = {1: ['137', '138', '139'], 3: ['131', '132', '133'],
                    6: ['125', '126', '127'], 12: ['113', '114', '115']}
        self.assertEqual(len(self.config['plans']), 24)
        self.assertEqual(len({p['id'] for p in self.config['plans']}), 24)
        for months in adult:
            for connections in (1, 2, 3):
                with_adult = self.bot.find_plan(months, True, connections)
                no_adult = self.bot.find_plan(months, False, connections)
                self.assertEqual(with_adult['package_id'], adult[months][connections - 1])
                self.assertEqual(no_adult['package_id'], original[months][connections - 1])
                self.assertEqual(with_adult['gbp_price'], no_adult['gbp_price'])

    def test_duration_buttons_and_back_to_main_menu(self):
        message = self.click('menu:plans')
        self.assertEqual(self.callbacks(message), [
            'plan:duration:1', 'plan:duration:3', 'plan:duration:6', 'plan:duration:12', 'menu',
        ])
        self.assertIn('Choose a subscription length', message['text'])
        home = self.click('menu')
        self.assertIn('menu:plans', self.callbacks(home))

    def test_all_combinations_and_back_paths_through_real_callback_handler(self):
        for months in (1, 3, 6, 12):
            content = self.click(f'plan:duration:{months}')
            self.assertEqual(self.callbacks(content), [
                f'plan:content:{months}:0', f'plan:content:{months}:1', 'plan:back:duration',
            ])
            for adult in (0, 1):
                connections = self.click(f'plan:content:{months}:{adult}')
                expected = [f'plan:connections:{months}:{adult}:{count}' for count in (1, 2, 3)]
                self.assertEqual(self.callbacks(connections), expected + [f'plan:back:content:{months}:{adult}'])
                for count in (1, 2, 3):
                    summary = self.click(f'plan:connections:{months}:{adult}:{count}')
                    plan = self.bot.find_plan(months, bool(adult), count)
                    self.assertIn('MEMBERSHIP SELECTED', summary['text'])
                    self.assertIn('With adult content' if adult else 'No adult content', summary['text'])
                    self.assertIn(f'{count} connection', summary['text'])
                    price = format(float(plan['gbp_price']), '.2f').rstrip('0').rstrip('.')
                    self.assertIn('£' + price, summary['text'])
                    self.assertIn('no order or payment has been created', summary['text'])
                    self.assertEqual(self.callbacks(summary)[0], 'pay:choose:' + plan['id'])
                    back = self.callbacks(summary)[1]
                    self.assertEqual(self.callbacks(self.click(back)), self.callbacks(connections))
                back_to_content = self.callbacks(connections)[-1]
                self.assertEqual(self.callbacks(self.click(back_to_content)), self.callbacks(content))
            self.assertEqual(self.callbacks(self.click('plan:back:duration')), self.callbacks(self.click('menu:plans')))

    def test_expired_acknowledgement_does_not_block_menu(self):
        self.api.ack_error = 400
        message = self.click('menu:plans')
        self.assertIn('plan:duration:1', self.callbacks(message))

    def test_transient_telegram_errors_are_not_silently_ignored(self):
        self.api.ack_error = 429
        with self.assertRaises(TelegramError):
            self.click('menu:plans')

    def test_invalid_callbacks_do_not_crash_or_select_a_plan(self):
        for action in ('plan:duration:bad', 'plan:duration:99', 'plan:duration:1:extra',
                       'plan:content:1:2', 'plan:connections:1:1:99', 'plan:back:connections:1:bad'):
            with self.subTest(action=action):
                result = self.click(action)
                self.assertIsNotNone(result)
                self.assertNotIn('MEMBERSHIP SELECTED', result['text'])
                self.assertIn('menu:plans', self.callbacks(result))

    def test_no_membership_actions_in_group_chats(self):
        self.assertIsNone(self.click('plan:connections:1:1:1', private=False))
        self.assertEqual(self.store.values, {})


if __name__ == '__main__':
    unittest.main()
