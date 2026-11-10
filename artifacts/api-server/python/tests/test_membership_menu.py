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
            self.values[key] = str(value)
        return self.values.get(key)


class TelegramAPI:
    def __init__(self):
        self.calls = []
        self.ack_error = None
        self.edit_error = None
        self.next_id = 10

    def __call__(self, method, payload):
        self.calls.append((method, copy.deepcopy(payload)))
        if method == 'answerCallbackQuery' and self.ack_error:
            raise TelegramError(self.ack_error, method)
        if method == 'editMessageText':
            if self.edit_error:
                code, description = self.edit_error
                raise TelegramError(code, method, description=description)
            return {'message_id': payload['message_id']}
        if method != 'sendMessage':
            return True
        self.next_id += 1
        return {'message_id': self.next_id}


class MembershipMenuTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'config.json'
        self.config = load_config(path, env={'APP_MODE': 'demo'})
        self.api = TelegramAPI()
        self.store = MemoryStore()
        service = SimpleNamespace(config=self.config, store=self.store,
                                  resellers=SimpleNamespace(member=lambda uid: None),
                                  create_order=self.fail_create_order)
        self.bot = TelegramBot(service, api=self.api)

    @staticmethod
    def fail_create_order(*args, **kwargs):
        raise AssertionError('Navigation must never create an order.')

    def click(self, action, private=True, message_id=None):
        self.api.calls.clear()
        message = {'chat': {'id': 42 if private else -100, 'type': 'private' if private else 'group'}}
        if message_id is not None:
            message['message_id'] = message_id
        self.bot.handle({'callback_query': {'id': 'test-callback', 'from': {'id': 42}, 'message': message, 'data': action}})
        shown = [payload for method, payload in self.api.calls if method in ('sendMessage', 'editMessageText')]
        return shown[-1] if shown else None

    def methods(self):
        return [method for method, _ in self.api.calls]

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

    def test_main_menu_is_trial_plans_reseller_notifications_and_account_row(self):
        home = self.click('menu')
        rows = [[b['callback_data'] for b in row] for row in home['reply_markup']['inline_keyboard']]
        self.assertEqual(rows, [['menu:trial'], ['menu:plans'], ['rs:home'], ['nt:settings'],
                                ['menu:account', 'menu:contact']])
        self.assertIn('MEMBER ACCESS', home['text'])
        self.assertIn('Choose an option below', home['text'])

    def test_legacy_more_button_returns_to_the_main_menu(self):
        more = self.click('menu:more')
        self.assertEqual(self.callbacks(more), self.callbacks(self.click('menu')))

    def test_duration_buttons_and_back_to_main_menu(self):
        message = self.click('menu:plans')
        self.assertEqual(self.callbacks(message), [
            'plan:duration:1', 'plan:duration:3', 'plan:duration:6', 'plan:duration:12', 'menu',
        ])
        self.assertIn('Choose a subscription length', message['text'])
        home = self.click('menu')
        self.assertIn('menu:plans', self.callbacks(home))

    def test_three_taps_from_plans_to_coin_choice(self):
        for months in (1, 3, 6, 12):
            pick = self.click(f'plan:duration:{months}')
            rows = pick['reply_markup']['inline_keyboard']
            self.assertEqual(len(rows), 3)  # no-adult row, adult row, back
            for adult, row in ((0, rows[0]), (1, rows[1])):
                self.assertEqual([b['callback_data'] for b in row],
                                 [f'plan:pick:{months}:{adult}:{count}' for count in (1, 2, 3)])
                for button, count in zip(row, (1, 2, 3)):
                    plan = self.bot.find_plan(months, bool(adult), count)
                    price = format(float(plan['gbp_price']), '.2f').rstrip('0').rstrip('.')
                    self.assertEqual(button['text'], ('🔞' if adult else '🚫') + f' {count} · £' + price)
                    coins = self.click(button['callback_data'])
                    callbacks = self.callbacks(coins)
                    self.assertIn('CHOOSE COIN', coins['text'])
                    self.assertIn(plan['detail'], coins['text'])
                    self.assertTrue(all(c.startswith('pay:quote:' + plan['id'] + ':') for c in callbacks[:-1]))
                    self.assertEqual(callbacks[-1], f'plan:duration:{months}')
            self.assertEqual(self.callbacks(pick)[-1], 'menu:plans')
            self.assertIn('Nothing is ordered until you choose a coin', pick['text'])

    def test_buttons_from_the_previous_layout_still_navigate(self):
        self.assertIn('plan:duration:1', self.callbacks(self.click('plan:back:duration')))
        self.assertIn('plan:pick:3:0:1', self.callbacks(self.click('plan:content:3:0')))
        self.assertIn('plan:pick:6:1:1', self.callbacks(self.click('plan:back:content:6:1')))
        self.assertIn('plan:pick:12:0:1', self.callbacks(self.click('plan:back:connections:12:0')))
        self.assertIn('CHOOSE COIN', self.click('plan:connections:1:1:2')['text'])

    def test_navigation_edits_the_latest_menu_in_place(self):
        home = self.click('menu')
        self.assertEqual(self.methods(), ['answerCallbackQuery', 'sendMessage'])
        self.assertEqual(self.store.values['tg_nav:' + self.bot.nav_key(42)[7:]], '11')
        plans = self.click('menu:plans', message_id=11)
        self.assertEqual(self.methods(), ['answerCallbackQuery', 'editMessageText'])
        self.assertEqual(self.api.calls[-1][1]['message_id'], 11)
        self.assertIn('plan:duration:1', self.callbacks(plans))
        # An older menu further up the chat gets a fresh message instead.
        self.click('menu:plans', message_id=3)
        self.assertEqual(self.methods(), ['answerCallbackQuery', 'sendMessage'])
        # Taps without a message id (or on a kept message) also send fresh messages.
        self.click('menu')
        self.assertEqual(self.methods(), ['answerCallbackQuery', 'sendMessage'])

    def test_edit_refusals_fall_back_safely(self):
        self.click('menu')
        self.api.edit_error = (400, "Bad Request: message is not modified")
        self.click('menu', message_id=11)
        self.assertEqual(self.methods(), ['answerCallbackQuery', 'editMessageText'])  # no duplicate menu
        self.api.edit_error = (400, "Bad Request: message can't be edited")
        self.click('menu:plans', message_id=11)
        self.assertEqual(self.methods(), ['answerCallbackQuery', 'editMessageText', 'sendMessage'])
        self.api.edit_error = (429, 'Too Many Requests')
        with self.assertRaises(TelegramError):
            self.click('menu:plans', message_id=12)

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
                       'plan:pick:1:2:1', 'plan:pick:1:1:99', 'plan:pick:1:1', 'plan:back:connections:1:bad', 'plan:nope'):
            with self.subTest(action=action):
                result = self.click(action)
                self.assertIsNotNone(result)
                self.assertNotIn('CHOOSE COIN', result['text'])
                self.assertIn('menu:plans', self.callbacks(result))

    def test_no_membership_actions_in_group_chats(self):
        self.assertIsNone(self.click('plan:pick:1:1:1', private=False))
        self.assertEqual(self.store.values, {})


if __name__ == '__main__':
    unittest.main()
