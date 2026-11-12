"""Owner dashboard: account details, Telegram usernames, add/delete subscriptions and reseller trial limits."""
import contextlib
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet

from streambot.bot import TelegramBot
from streambot.config import load_config
from streambot.postgres_store import PostgresStore, _Connection
from streambot.rates import Rates
from streambot.service import CheckoutError, CheckoutService
from streambot.store import Store
from streambot.web import create_app
from tests.test_resellers import Provider

ADMIN = 9001


class Scenarios:
    def setup_service(self):
        config = load_config(env={'APP_MODE': 'demo', 'SUPPORT_ADMIN_ID': str(ADMIN)})
        config.update(mode='live', panel_writes=True)
        self.panel = Mock()
        self.panel.prepare_generation.side_effect = lambda package: dict(generation_mode='panel', package_id=package)
        self.created = 0
        def create_account(package, *_args, **_kwargs):
            self.created += 1
            return dict(username='line%d' % self.created, password='pass%d' % self.created, panel_id=str(500 + self.created),
                        package_id=package, expires_at=str(int(time.time()) + 30 * 86400))
        self.panel.create_account.side_effect = create_account
        self.service = CheckoutService(config, self.store, Mock(), self.panel, Rates(demo=True))
        self.accounts = self.service.accounts
        self.finance = self.service.resellers.finance; self.ops = self.service.resellers.ops
        self.provider = Provider(); self.ops.provider = self.provider
        self.finance.register(42, 'reseller_one'); self.finance.account_status(ADMIN, 42, 'active', 'Test approval')
        self.finance.register(43, 'reseller_two'); self.finance.account_status(ADMIN, 43, 'active', 'Test approval')
        self.key = 'a' * 64
        env = patch.dict(os.environ, STREAMBOT_ADMIN_BRIDGE_KEY=self.key); env.start(); self.addCleanup(env.stop)
        self.client = create_app(self.service).test_client()
        self.actor = 'local:owner:' + '1' * 64
        self.sent = []
        self.bot = TelegramBot(self.service, api=lambda method, payload: self.sent.append((method, payload)) or {'message_id': 1})

    # ---- helpers ----
    def call(self, path, data=None):
        method = 'GET' if data is None else 'POST'
        target = '/api/_admin' + path
        raw = '' if data is None else json.dumps(data)
        timestamp = str(int(time.time())); nonce = secrets.token_hex(16)
        parts = [method, target, self.actor, timestamp, nonce, hashlib.sha256(raw.encode()).hexdigest()]
        signature = hmac.new(self.key.encode(), '\n'.join(parts).encode(), hashlib.sha256).hexdigest()
        return self.client.open(target, method=method, data=raw, headers={
            'Content-Type': 'application/json', 'X-Streamline-Actor': self.actor, 'X-Streamline-Time': timestamp,
            'X-Streamline-Nonce': nonce, 'X-Streamline-Signature': signature})

    def trial(self, uid=700):
        order = self.service.create_trial(uid)
        self.service.provision_pending()
        return self.store.get(order['id'])

    def reseller_trial(self, uid=42, key=None):
        preview = self.ops.preview(uid, 'trial', 0, 1, False, 'Customer ' + (key or 'a'))
        op = self.ops.reserve(uid, 'request-' + (key or secrets.token_hex(4)), preview)
        self.ops.process()
        return self.ops.operation(uid, op['id'])

    def message(self, uid, username, text='/start'):
        self.bot.handle({'update_id': secrets.randbelow(10 ** 9), 'message': {
            'message_id': secrets.randbelow(10 ** 9), 'text': text, 'chat': {'id': uid, 'type': 'private'},
            'from': {'id': uid, 'username': username}}})

    # ---- account details and usernames ----
    def test_order_detail_shows_the_login_and_the_telegram_username(self):
        order = self.trial(700)
        self.assertEqual(order['status'], 'fulfilled')
        detail = self.call('/orders/' + order['id']).json
        self.assertEqual(detail['account']['username'], 'line1')
        self.assertEqual(detail['account']['password'], 'pass1')
        self.assertGreater(detail['account']['expiresAt'], time.time())
        self.assertTrue(detail['canDelete'])
        self.assertEqual(detail['order']['username'], '')
        self.message(700, 'alice_tv')
        self.assertEqual(self.call('/orders/' + order['id']).json['order']['username'], 'alice_tv')
        # A renamed account replaces the stored handle; malformed handles are ignored.
        self.message(700, 'alice_new'); self.message(700, 'bad name!')
        self.assertEqual(self.call('/orders/' + order['id']).json['order']['username'], 'alice_new')
        # Searching orders by @username or Telegram ID finds the trial.
        self.assertEqual(self.call('/orders?q=%40ALICE_new').json['total'], 1)
        self.assertEqual(self.call('/orders?q=700').json['total'], 1)
        self.assertEqual(self.call('/orders?q=nobody_here').json['total'], 0)

    def test_bot_looks_up_usernames_for_customers_it_has_not_heard_from(self):
        from streambot.bot import TelegramError
        trial = self.trial(700)
        paid = self.call('/subscriptions', {'telegramId': 800, 'planId': 'month-1', 'reason': 'Existing customer'}).json['orderId']
        self.service.create_trial(701); self.service.create_trial(702)
        asked = []
        def api(method, payload):
            if method != 'getChat': return {'message_id': 1}
            asked.append(payload['chat_id'])
            if payload['chat_id'] == 701: raise TelegramError(400, 'getChat')        # never started the bot
            return {'id': payload['chat_id'], 'username': {700: 'alice_tv', 800: 'bob_h'}.get(payload['chat_id'])}
        self.bot.api = api
        self.assertEqual(self.bot.backfill_usernames(), 2)
        self.assertEqual(sorted(asked), [700, 701, 702, 800])
        self.assertEqual(self.call('/orders/' + trial['id']).json['order']['username'], 'alice_tv')
        self.assertEqual(self.call('/orders/' + paid).json['order']['username'], 'bob_h')
        # Nothing is asked twice: found names are kept, and misses wait a week before the next try.
        self.bot._username_backfill_at = 0
        self.assertEqual(self.bot.backfill_usernames(), 0)
        self.assertEqual(len(asked), 4)
        with self.store.connection() as db:
            db.execute("UPDATE metadata SET value='0' WHERE key='tg_username_checked:702'")
        self.bot._username_backfill_at = 0; self.bot.backfill_usernames()
        self.assertEqual(asked[4:], [702])
        # A broken API never stops the bot's loop.
        def broken(method, payload): raise RuntimeError('network down')
        self.bot.api = broken
        with self.store.connection() as db:
            db.execute("UPDATE metadata SET value='0' WHERE key='tg_username_checked:702'")
        self.bot._username_backfill_at = 0
        self.assertEqual(self.bot.backfill_usernames(), 0)

    def test_order_without_an_account_has_no_login_and_cannot_be_deleted(self):
        order = self.service.create_trial(701)
        detail = self.call('/orders/' + order['id']).json
        self.assertIsNone(detail['account'])
        self.assertFalse(detail['canDelete'])
        self.assertEqual(self.call('/subscriptions/retail/' + order['id'] + '/delete', {'confirm': True, 'reason': 'No account yet'}).status_code, 404)

    # ---- one list for retail and reseller accounts ----
    def test_list_combines_retail_and_reseller_accounts_with_filters(self):
        self.trial(700); self.message(700, 'alice_tv')
        self.reseller_trial(42, 'first')
        page = self.call('/subscriptions').json
        self.assertEqual((page['total'], page['trials'], page['active']), (2, 2, 2))
        retail = next(i for i in page['items'] if i['source'] == 'retail')
        resold = next(i for i in page['items'] if i['source'] == 'reseller')
        self.assertEqual((retail['telegramId'], retail['telegramUsername'], retail['accountUsername'], retail['accountPassword']),
                         (700, 'alice_tv', 'line1', 'pass1'))
        self.assertEqual((resold['resellerTelegramId'], resold['resellerUsername'], resold['accountUsername']),
                         (42, 'reseller_one', 'test-user-1'))
        self.assertEqual(self.call('/subscriptions?source=retail').json['total'], 1)
        self.assertEqual(self.call('/subscriptions?source=reseller').json['total'], 1)
        self.assertEqual(self.call('/subscriptions?reseller=42').json['total'], 1)
        self.assertEqual(self.call('/subscriptions?reseller=43').json['total'], 0)
        self.assertEqual(self.call('/subscriptions?kind=paid').json['total'], 0)
        self.assertEqual(self.call('/subscriptions?q=alice_tv').json['total'], 1)
        self.assertEqual(self.call('/subscriptions?q=test-user-1').json['total'], 1)
        self.assertEqual(self.call('/subscriptions?source=nonsense').status_code, 400)

    # ---- add ----
    def test_owner_adds_a_membership_without_payment_and_the_bot_delivers_it(self):
        result = self.call('/subscriptions', {'telegramId': 800, 'planId': 'month-3', 'reason': 'Goodwill for outage'})
        self.assertEqual(result.status_code, 200)
        order_id = result.json['orderId']
        queued = self.store.get(order_id)
        self.assertEqual((queued['status'], queued['kind'], queued['amount_units']), ('paid', 'paid', '0'))
        # While it is being prepared the bot explains it without inventing a payment.
        text = self.bot.checkout.order_text(self.service.public(queued))
        self.assertIn('MEMBERSHIP ADDED BY SUPPORT', text); self.assertNotIn('PAYMENT RECEIVED', text)
        self.assertIn('no payment', self.bot.checkout.details_text(self.service.public(queued)))
        # A second request while one is in flight is refused rather than creating two accounts.
        again = self.call('/subscriptions', {'telegramId': 800, 'planId': 'month-3', 'reason': 'Clicked twice'})
        self.assertEqual(again.status_code, 400)
        self.service.provision_pending()
        delivered = self.store.get(order_id)
        self.assertEqual(delivered['status'], 'fulfilled')
        self.assertEqual(self.panel.create_account.call_count, 1)
        package = next(p['package_id'] for p in self.service.config['plans'] if p['id'] == 'month-3')
        self.assertEqual(self.panel.create_account.call_args.args[0], str(package))  # the chosen plan's panel package
        self.bot.checkout.notify()
        self.assertTrue(any(payload.get('chat_id') == 800 and 'line1' in payload.get('text', '') for _, payload in self.sent))
        item = self.call('/subscriptions?source=retail').json['items'][0]
        self.assertEqual((item['kind'], item['telegramId'], item['accountUsername']), ('paid', 800, 'line1'))
        # No payment exists, so revenue is untouched.
        self.assertEqual(self.call('/overview').json['revenueMonthGbp'], 0)
        # The customer's own bot menu treats it as their membership.
        self.assertEqual(self.bot.menus.state(800)['kind'], 'active')

    def test_add_validates_customer_plan_reason_and_panel_switch(self):
        for body in ({'telegramId': 0, 'planId': 'month-1', 'reason': 'Bad ID'}, {'telegramId': '800', 'planId': 'month-1', 'reason': 'Text ID'},
                     {'telegramId': 800, 'planId': 'nope', 'reason': 'Bad plan'}, {'telegramId': 800, 'planId': 'month-1', 'reason': ''}):
            self.assertEqual(self.call('/subscriptions', body).status_code, 400)
        self.service.config['panel_writes'] = False
        self.assertEqual(self.call('/subscriptions', {'telegramId': 800, 'planId': 'month-1', 'reason': 'Writes off'}).status_code, 400)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM orders WHERE kind='paid'").fetchone()[0], 0)
        with self.assertRaises(CheckoutError): self.accounts.add(123, 800, 'month-1', 'Not the administrator')

    # ---- delete ----
    def test_deleting_a_membership_needs_confirmation_and_unlinks_the_customer(self):
        order_id = self.call('/subscriptions', {'telegramId': 800, 'planId': 'month-1', 'reason': 'Set up for a friend'}).json['orderId']
        self.service.provision_pending()
        path = '/subscriptions/retail/' + order_id + '/delete'
        self.assertEqual(self.call(path, {'reason': 'Forgot to confirm'}).status_code, 400)
        self.assertEqual(self.call(path, {'confirm': True, 'reason': ''}).status_code, 400)
        self.assertEqual(self.call('/subscriptions').json['total'], 1)
        self.assertEqual(self.call(path, {'confirm': True, 'reason': 'Customer left'}).json, {'deleted': True})
        self.assertEqual(self.call('/subscriptions').json['total'], 0)
        self.assertEqual(self.bot.menus.state(800)['kind'], 'new')          # gone from the customer's bot
        self.assertIsNotNone(self.store.get(order_id))                       # the order itself is kept
        detail = self.call('/orders/' + order_id).json
        self.assertGreater(detail['removedAt'], 0); self.assertFalse(detail['canDelete'])
        self.assertEqual(detail['order']['customer'], '800')                 # the record remembers whose it was
        self.assertEqual(self.call(path, {'confirm': True, 'reason': 'Twice'}).status_code, 404)
        self.panel.delete_account.assert_not_called()                        # never touches the panel line

    def test_deleting_a_trial_keeps_the_one_trial_rule(self):
        order = self.trial(700)
        self.assertTrue(self.call('/subscriptions/retail/' + order['id'] + '/delete', {'confirm': True, 'reason': 'Tidy up'}).json['deleted'])
        self.assertEqual(self.call('/subscriptions').json['total'], 0)
        again = self.service.create_trial(700)
        self.assertEqual(again['id'], order['id'])
        self.assertEqual(self.panel.create_account.call_count, 1)

    def test_deleting_a_reseller_subscription_hides_it_from_the_reseller_too(self):
        result = self.reseller_trial(42, 'first')
        sid = result['result_id']
        self.assertEqual(len(self.ops.records(42, 'trials')), 1)
        self.assertTrue(self.call('/subscriptions/reseller/' + sid + '/delete', {'confirm': True, 'reason': 'Abuse report'}).json['deleted'])
        self.assertEqual(self.ops.records(42, 'trials'), [])
        self.assertEqual(self.call('/subscriptions?reseller=42').json['total'], 0)
        self.assertEqual(self.call('/subscriptions/reseller/' + sid + '/delete', {'confirm': True, 'reason': 'Twice'}).status_code, 404)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM rs_audit WHERE action='subscription_delete'").fetchone()[0], 1)

    # ---- reseller trial limits ----
    def expire_trials(self):
        for account in self.provider.accounts.values(): account['expires_at'] = int(time.time()) - 10
        with self.store.connection() as db:
            db.execute("UPDATE rs_subscriptions SET expires_at=? WHERE kind='trial'", (int(time.time()) - 10,))

    def age_trials(self, seconds):
        with self.store.connection() as db:
            db.execute("UPDATE rs_operations SET created_at=created_at-? WHERE operation_type='trial'", (seconds,))

    def test_default_limits_apply_to_every_reseller_and_can_be_unlimited(self):
        card = self.call('/ratecard').json
        self.assertEqual(card['trialLimits'], {'daily': 1, 'weekly': -1, 'monthly': -1, 'active': 1})
        self.reseller_trial(42, 'one'); self.expire_trials()
        with self.assertRaises(CheckoutError): self.reseller_trial(42, 'two')            # daily cap of 1
        saved = self.call('/ratecard', {'category': 'trials', 'values': [-1, 3, -1, -1], 'reason': 'Unlimited per day, three a week'})
        self.assertEqual(saved.json['trialLimits'], {'daily': -1, 'weekly': 3, 'monthly': -1, 'active': -1})
        self.reseller_trial(42, 'two'); self.reseller_trial(42, 'three')
        with self.assertRaisesRegex(CheckoutError, 'weekly'): self.reseller_trial(42, 'four')
        self.reseller_trial(43, 'other')                                                # counted per reseller, not across them
        self.age_trials(8 * 86400)                                                      # a week later the allowance is back
        self.reseller_trial(42, 'four')
        self.assertEqual(self.call('/ratecard', {'category': 'trials', 'values': [1, 1, 1, -2], 'reason': 'Out of range'}).status_code, 400)

    def test_monthly_limit_uses_a_rolling_thirty_days(self):
        self.finance.configure(ADMIN, 'trials', (-1, -1, 2, -1), 'Two a month')
        self.reseller_trial(42, 'one'); self.reseller_trial(42, 'two')
        with self.assertRaisesRegex(CheckoutError, 'monthly'): self.reseller_trial(42, 'three')
        self.age_trials(29 * 86400)
        with self.assertRaises(CheckoutError): self.reseller_trial(42, 'three')
        self.age_trials(2 * 86400)
        self.reseller_trial(42, 'three')

    def test_one_reseller_can_have_its_own_limits(self):
        path = '/resellers/42/trial-limits'
        detail = self.call('/resellers/42').json['trials']
        self.assertEqual(detail['limits'], {'daily': None, 'weekly': None, 'monthly': None, 'active': None})
        self.assertEqual(detail['effective'], {'daily': 1, 'weekly': -1, 'monthly': -1, 'active': 1})
        saved = self.call(path, {'daily': -1, 'weekly': None, 'monthly': 5, 'active': -1, 'reason': 'Trusted partner'}).json['trials']
        self.assertEqual(saved['limits'], {'daily': -1, 'weekly': None, 'monthly': 5, 'active': -1})
        self.assertEqual(saved['effective'], {'daily': -1, 'weekly': -1, 'monthly': 5, 'active': -1})
        for key in 'abc': self.reseller_trial(42, key)
        self.assertEqual(self.call('/resellers/42').json['trials']['usage'], {'daily': 3, 'weekly': 3, 'monthly': 3, 'active': 3})
        self.reseller_trial(43, 'one')
        with self.assertRaises(CheckoutError): self.reseller_trial(43, 'two')            # everyone else still on the default
        # Zero switches trials off for this reseller only.
        self.call(path, {'daily': 0, 'weekly': None, 'monthly': None, 'active': None, 'reason': 'Paused'})
        with self.assertRaises(CheckoutError): self.reseller_trial(42, 'd')
        # Clearing every field returns the reseller to the default.
        cleared = self.call(path, {'daily': None, 'weekly': None, 'monthly': None, 'active': None, 'reason': 'Back to default'}).json['trials']
        self.assertEqual(cleared['effective'], {'daily': 1, 'weekly': -1, 'monthly': -1, 'active': 1})
        self.assertEqual(self.call(path, {'daily': 'many', 'weekly': None, 'monthly': None, 'active': None, 'reason': 'Bad value'}).status_code, 400)
        self.assertEqual(self.call(path, {'daily': 1, 'weekly': None, 'monthly': None, 'active': None, 'reason': ''}).status_code, 400)
        # The Telegram administrator's settings view still shows plain numbers, not per-reseller JSON.
        self.assertEqual(set(self.finance.configuration(ADMIN)['settings']), {'trial_daily', 'trial_weekly', 'trial_monthly', 'trial_active'})

    def test_telegram_command_form_still_sets_daily_and_active(self):
        self.finance.configure(ADMIN, 'trials', (2, 2), 'From /rstrials')
        with self.store.connection() as db:
            self.assertEqual(self.finance.trial_limits(db)[0], {'daily': 2, 'weekly': -1, 'monthly': -1, 'active': 2})

    # ---- owner creates resellers, trials and tickets ----
    def test_owner_creates_an_active_reseller_with_starting_credits(self):
        body = {'telegramId': 900, 'username': '@new_partner', 'credits': 25, 'reason': 'Agreed by phone', 'requestKey': 'create-900-a'}
        made = self.call('/resellers', body).json
        self.assertEqual((made['reseller']['status'], made['reseller']['username'], made['reseller']['available']), ('active', 'new_partner', 25))
        self.assertEqual(self.call('/resellers', body).status_code, 400)                        # already active; no second grant
        self.assertEqual(self.finance.member(900)['balance'], 25)
        self.reseller_trial(900, 'first')                                                       # can use the account straight away
        log = self.call('/logs/credits?reseller=900').json
        self.assertEqual((log['total'], log['items'][0]['movement'], log['items'][0]['reason']), (1, 25, 'Agreed by phone'))
        zero = self.call('/resellers', {'telegramId': 901, 'credits': 0, 'reason': 'No credits yet', 'requestKey': 'create-901-a'}).json
        self.assertEqual((zero['reseller']['status'], zero['reseller']['available']), ('active', 0))
        for bad in ({'telegramId': 0, 'credits': 0, 'reason': 'Bad ID', 'requestKey': 'create-bad-1'},
                    {'telegramId': 902, 'credits': -1, 'reason': 'Negative', 'requestKey': 'create-bad-2'},
                    {'telegramId': 902, 'credits': 1, 'reason': '', 'requestKey': 'create-bad-3'},
                    {'telegramId': 902, 'username': 'bad name', 'credits': 1, 'reason': 'Bad name', 'requestKey': 'create-bad-4'}):
            self.assertEqual(self.call('/resellers', bad).status_code, 400)
        self.assertIsNone(self.finance.member(902))
        self.finance.account_status(ADMIN, 900, 'suspended', 'Test suspension')
        self.assertEqual(self.call('/resellers', dict(body, requestKey='create-900-b')).status_code, 400)

    def test_owner_starts_a_customers_trial_once(self):
        result = self.call('/subscriptions', {'telegramId': 810, 'planId': 'trial', 'reason': 'Asked on the phone'})
        self.assertEqual(result.status_code, 200); self.assertIn('Trial queued', result.json['message'])
        self.service.provision_pending()
        order = self.store.get(result.json['orderId'])
        self.assertEqual((order['kind'], order['status'], order['telegram_id']), ('trial', 'fulfilled', 810))
        self.bot.notify_trials()
        self.assertTrue(any(payload.get('chat_id') == 810 and 'line1' in payload.get('text', '') for _, payload in self.sent))
        again = self.call('/subscriptions', {'telegramId': 810, 'planId': 'trial', 'reason': 'Second go'})
        self.assertEqual(again.status_code, 400); self.assertIn('already had', again.json['error'])
        self.assertEqual(self.panel.create_account.call_count, 1)
        self.assertEqual(self.call('/subscriptions?kind=trial').json['total'], 1)

    def test_owner_opens_a_ticket_to_a_customer_and_a_reseller(self):
        self.message(700, 'alice_tv')
        made = self.call('/tickets', {'telegramId': 700, 'topic': 'payment', 'body': 'Your payment arrived, thank you.'}).json
        ticket = made['ticket']
        self.assertEqual((ticket['telegramId'], ticket['username'], ticket['status'], ticket['reseller'], made['delivered']), (700, 'alice_tv', 'answered', False, True))
        self.assertEqual([(m['sender'], m['body']) for m in made['messages']], [('support', 'Your payment arrived, thank you.')])
        sent = [payload for _, payload in self.sent if payload.get('chat_id') == 700 and 'Message from support' in payload.get('text', '')]
        self.assertEqual(len(sent), 1); self.assertIn('Your payment arrived', sent[0]['text'])
        # The customer can answer it like any ticket, which puts it back in the owner's queue.
        self.service.tickets.reply(700, ticket['id'], 'Thanks!')
        self.assertEqual(self.call('/tickets/' + ticket['id']).json['ticket']['status'], 'open')
        reseller = self.call('/tickets', {'telegramId': 42, 'topic': 'reseller', 'body': 'New credit packs are available.'}).json['ticket']
        self.assertEqual((reseller['reseller'], reseller['username']), (True, 'reseller_one'))
        for bad in ({'telegramId': 0, 'topic': 'other', 'body': 'x'}, {'telegramId': 700, 'topic': 'nope', 'body': 'x'}, {'telegramId': 700, 'topic': 'other', 'body': '  '}):
            self.assertEqual(self.call('/tickets', bad).status_code, 400)

    # ---- activity and credit logs ----
    def test_activity_log_shows_who_created_what_with_credits_before_and_after(self):
        self.finance.adjust(ADMIN, 42, 20, 'Bank transfer REF1', 'fund-42-a')
        self.reseller_trial(42, 'first')
        op = self.ops.reserve(42, 'request-paid', self.ops.preview(42, 'create', 3, 2, False, 'Bar on King St')); self.ops.process()
        self.trial(700); self.message(700, 'alice_tv')
        log = self.call('/logs/activity').json
        self.assertEqual(log['total'], 3)
        self.assertEqual({r['telegramId'] for r in log['resellers']}, {42, 43})
        paid = next(i for i in log['items'] if i['id'] == op['id'])
        cost = paid['creditCost']
        self.assertGreater(cost, 0)
        self.assertEqual((paid['action'], paid['status'], paid['resellerUsername'], paid['customer'], paid['package']),
                         ('create', 'succeeded', 'reseller_one', 'Bar on King St', '3 months · 2 devices'))
        self.assertEqual((paid['creditsBefore'], paid['creditsAfter']), (20, 20 - cost))
        self.assertTrue(paid['accountUsername'].startswith('test-user-')); self.assertTrue(paid['accountPassword'])
        trial = next(i for i in log['items'] if i['action'] == 'trial' and i['source'] == 'reseller')
        self.assertEqual((trial['package'], trial['creditCost'], trial['creditsBefore'], trial['creditsAfter']), ('24-hour trial', 0, 20, 20))
        direct = next(i for i in log['items'] if i['source'] == 'retail')
        self.assertEqual((direct['customer'], direct['accountUsername'], direct['creditsBefore']), ('@alice_tv · 700', 'line1', None))
        # by reseller, by source, by search
        self.assertEqual(self.call('/logs/activity?reseller=42').json['total'], 2)
        self.assertEqual(self.call('/logs/activity?reseller=43').json['total'], 0)
        self.assertEqual(self.call('/logs/activity?source=retail').json['total'], 1)
        self.assertEqual(self.call('/logs/activity?q=king').json['total'], 1)
        self.assertEqual(self.call('/logs/activity?source=panel').status_code, 400)

    def test_credit_log_lists_top_ups_and_adjustments_per_reseller(self):
        self.finance.adjust(ADMIN, 42, 20, 'Bank transfer REF1', 'fund-42-a')
        self.call('/resellers/42/credits', {'movement': -5, 'reason': 'Correction', 'requestKey': 'correct-42-a'})
        self.finance.adjust(ADMIN, 43, 7, 'Goodwill', 'fund-43-a')
        self.ops.reserve(42, 'request-paid', self.ops.preview(42, 'create', 1, 1, False, 'Sam')); self.ops.process()
        log = self.call('/logs/credits').json
        self.assertEqual((log['total'], log['added'], log['removed']), (3, 27, 5))   # usage is not a top-up
        newest = log['items'][0]
        self.assertEqual((newest['resellerTelegramId'], newest['movement'], newest['reason'], newest['kind']), (43, 7, 'Goodwill', 'adjustment'))
        mine = self.call('/logs/credits?reseller=42').json
        self.assertEqual([(i['movement'], i['balanceBefore'], i['balanceAfter'], i['admin']) for i in mine['items']],
                         [(-5, 20, 15, 'Owner (website)'), (20, 0, 20, 'Admin 9001')])
        usage = self.call('/logs/credits?reseller=42&scope=usage').json
        self.assertEqual((usage['total'], usage['items'][0]['kind'], usage['items'][0]['balanceBefore']), (1, 'usage', 15))
        self.assertEqual(self.call('/logs/credits?scope=all').json['total'], 4)
        self.assertEqual(self.call('/logs/credits?q=goodwill').json['total'], 1)
        self.assertEqual(self.call('/logs/credits?reseller=abc').status_code, 400)


class AdminSubscriptionTests(Scenarios, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'db.sqlite3', Fernet.generate_key())
        self.setup_service()


@unittest.skipUnless(os.getenv('STREAMBOT_TEST_POSTGRES') == 'true' and not os.getenv('REPLIT_DEPLOYMENT'), 'Development PostgreSQL opt-in only')
class PostgresAdminSubscriptionTests(Scenarios, unittest.TestCase):
    def setUp(self):
        # Every write happens inside one outer transaction that is rolled back; no panel or network calls.
        self.store = PostgresStore(os.environ['DATABASE_URL'], Fernet.generate_key())
        db = self.store._connect(); db.execute('SELECT 1')
        self.addCleanup(db.close); self.addCleanup(db.rollback)

        @contextlib.contextmanager
        def connection():
            with db.transaction(): yield _Connection(db, self.store._transaction_lock)
        self.store.connection = connection
        self.setup_service()


if __name__ == '__main__':
    unittest.main()
