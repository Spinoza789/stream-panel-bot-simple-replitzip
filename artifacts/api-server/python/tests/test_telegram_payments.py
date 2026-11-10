"""Isolated wallet/TXID tests: temporary SQLite, fake rates, nodes, panel and Telegram."""
import copy
import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import requests
from cryptography.fernet import Fernet

from streambot.bot import TelegramBot
from streambot.chains import (BITCOIN_GENESIS, BlockchainVerifier, ChainUnavailable,
                              PaymentPending, PaymentRejected)
from streambot.config import load_config
from streambot.rates import Rates, RateUnavailable
from streambot.service import CheckoutError, CheckoutService
from streambot.store import Store

CONFIG = Path(__file__).resolve().parents[1] / 'config.json'
TXID = '0x' + 'a' * 64


class Panel:
    def __init__(self):
        self.calls = []

    def prepare_generation(self, package_id):
        return dict(generation_mode='panel',package_id=package_id,before_ids=[],prepared_at=0,post_attempted=True)

    def create_account(self, package_id, username='', password='', description='', *, generation=None):
        if username or password or description: raise AssertionError('Generation fields must be blank')
        self.calls.append(package_id)
        return dict(username='generated-user-'+str(len(self.calls)),password='generated-secret-'+str(len(self.calls)), server_url='test server')


class Verifier:
    def __init__(self):
        self.proof = None
        self.error = None

    def verify(self, *args):
        if self.error:
            raise self.error
        return copy.deepcopy(self.proof)


class TelegramPaymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = load_config(CONFIG, env={'APP_MODE': 'demo'})
        # Live state-machine behavior is tested exclusively against fakes.
        self.config['mode'] = 'live'
        self.store = Store(Path(self.temp.name) / 'test.sqlite3', Fernet.generate_key())
        self.verifier, self.panel = Verifier(), Panel()
        self.service = CheckoutService(self.config, self.store, self.verifier, self.panel, rates=Rates(demo=True))
        self.calls = []
        def api(method, payload):
            self.calls.append((method, copy.deepcopy(payload)))
            return {'message_id': len(self.calls)}
        self.api = api
        self.bot = TelegramBot(self.service, api=api)

    def click(self, action, uid=42, callback_id='callback'):
        self.calls.clear()
        self.bot.handle({'callback_query': {'id': callback_id, 'from': {'id': uid},
                         'message': {'chat': {'type': 'private', 'id': uid}}, 'data': action}})
        sent = [p for m, p in self.calls if m == 'sendMessage']
        return sent[-1] if sent else None

    def create(self, uid=42, plan='adult-month-1', asset='usdc-ethereum', request='request'):
        return self.service.create_order(plan, asset, owner_telegram_id=uid,
                                         request_key=f'test:{uid}:{request}')['order']

    def proof(self, order, **overrides):
        proof = dict(network=order['asset']['network'], txid=TXID,
                     amount_units=int(order['amount_units']), block_time=order['created_at'], confirmations=12)
        proof.update(overrides)
        self.verifier.proof = proof
        self.verifier.error = None

    def test_entire_quote_txid_confirmation_and_credential_delivery(self):
        crypto = self.click('pay:choose:adult-month-1')
        callbacks = [b['callback_data'] for row in crypto['reply_markup']['inline_keyboard'] for b in row]
        self.assertIn('pay:quote:adult-month-1:usdc-ethereum', callbacks)
        invoice = self.click('pay:quote:adult-month-1:usdc-ethereum')
        order = self.store.telegram_orders(42)[0]
        self.assertIn('$12.50 USD', invoice['text'])
        self.assertIn('<b>💰 SEND EXACTLY</b>\n<code>' + self.service.public(order)['amount'], invoice['text'])
        self.assertEqual(invoice['parse_mode'], 'HTML')
        self.assertEqual(order['plan']['package_id'], '140')
        self.assertNotIn('Simulate payment', str(invoice))
        prompt = self.click('pay:tx:' + order['id'])
        self.assertTrue(prompt['reply_markup']['force_reply'])
        self.bot.handle({'update_id': 1, 'message': {'message_id': 1, 'from': {'id': 42},
                         'chat': {'id': 42, 'type': 'private'}, 'text': TXID}})
        self.assertEqual(self.store.get(order['id'])['status'], 'pending')
        self.assertEqual(len(self.panel.calls), 0)
        self.verifier.error = PaymentPending()
        self.service.verify_order(order_id=order['id'])
        self.assertEqual(self.store.get(order['id'])['status'], 'pending')
        self.bot.checkout.notify()
        self.assertIn('Waiting for blockchain confirmation', self.calls[-1][1]['text'])
        self.proof(order)
        self.service.verify_order(order_id=order['id'])
        self.assertEqual(self.store.get(order['id'])['status'], 'paid')
        self.service.provision_pending()
        self.bot.checkout.notify()
        self.assertEqual(self.panel.calls, ['140'])
        self.assertIn('Membership — ', self.calls[-1][1]['text'])
        self.assertIn('Username:', self.calls[-1][1]['text'])
        self.assertIn('APP DOWNLOAD CODES',self.calls[-1][1]['text'])
        sent = len(self.calls)
        self.bot.checkout.notify()
        self.assertEqual(len(self.calls), sent)
        result = self.click('pay:orders')
        self.assertIn(order['id'], str(result['reply_markup']))

    def test_ownership_cannot_be_changed_using_an_order_id(self):
        order = self.create()
        result = self.click('pay:status:' + order['id'], uid=99)
        self.assertIn('Order not found', result['text'])
        self.assertNotIn(order['asset']['wallet'], result['text'])

    def test_invoice_copy_buttons_use_full_amount_not_rounded_usd_price(self):
        order = self.create()
        # Reproduce the customer's confusing USD-reference/USDC-amount example.
        order['plan'].update(usd_price='13.36', gbp_price='10.00')
        order['amount'] = '13.356516'
        self.bot.checkout.show_order(42, order)
        payload = self.calls[-1][1]
        self.assertEqual(payload['parse_mode'], 'HTML')
        self.assertLess(payload['text'].index('13.356516'), payload['text'].index('$13.36'))
        self.assertIn('NOT the amount to send', payload['text'])
        self.assertIn('Do not round it', payload['text'])
        self.assertIn('<code>' + order['asset']['wallet'] + '</code>', payload['text'])
        copies = [button['copy_text']['text'] for row in payload['reply_markup']['inline_keyboard']
                  for button in row if 'copy_text' in button]
        self.assertEqual(copies, ['13.356516', order['asset']['wallet']])
        self.assertNotIn('13.36', copies)

    def test_checking_payment_does_not_repeat_send_or_copy_instructions(self):
        order = self.create()
        self.service.submit_telegram_tx(42, order['id'], TXID)
        order = self.service.telegram_order(42, order['id'])
        self.bot.checkout.show_order(42, order)
        payload = self.calls[-1][1]
        self.assertIn('PAYMENT VERIFICATION', payload['text'])
        self.assertIn('do not send another payment', payload['text'])
        self.assertNotIn('SEND EXACTLY', payload['text'])
        self.assertNotIn('copy_text', str(payload['reply_markup']))
        self.assertNotIn('pay:quote:', str(payload['reply_markup']))
        self.assertNotIn('pay:tx:', str(payload['reply_markup']))

    def test_expired_invoice_has_no_copy_buttons_and_does_not_request_payment(self):
        order = dict(self.create(), expires_at=0)
        text = self.bot.checkout.order_text(order)
        self.assertIn('QUOTE EXPIRED — DO NOT PAY', text)
        self.assertNotIn('SEND EXACTLY', text)
        self.assertNotIn('copy_text', str(self.bot.checkout.order_keyboard(order)))
        self.assertIn('pay:tx:', str(self.bot.checkout.order_keyboard(order)))

    def test_invoice_escapes_dynamic_html_and_preserves_exact_copy_values(self):
        order = self.create()
        order['plan']['name'] = '<b>Fake</b> & other'
        order['message'] = '<a href="https://wrong.example">Click</a>'
        order['asset']['wallet'] = 'wallet<&>'
        text = self.bot.checkout.order_text(order)
        self.assertIn('&lt;b&gt;Fake&lt;/b&gt; &amp; other', text)
        self.assertNotIn('<a href=', text)
        self.assertIn('<code>wallet&lt;&amp;&gt;</code>', text)
        self.assertEqual(self.bot.checkout.order_keyboard(order)['inline_keyboard'][0][1]['copy_text']['text'], 'wallet<&>')

    def test_every_completed_membership_has_guide_but_unfinished_orders_do_not(self):
        from streambot.trial_message import APP_DOWNLOAD_GUIDE
        order=self.create()
        for index,plan in enumerate(self.service.config['plans']):
            credentials={'username':'test-member-'+str(index),'password':'test-password-'+str(index)}
            text=self.bot.checkout.order_text(dict(order,status='fulfilled',plan=plan,credentials=credentials))
            self.assertTrue(text.startswith('<blockquote><u>Membership — '+plan['name']+'</u>'))
            self.assertIn(plan['detail'],text)
            self.assertIn('Username: '+credentials['username'],text)
            self.assertTrue(text.endswith(APP_DOWNLOAD_GUIDE))
            self.assertLess(len(text),4096)
        for status in ('pending','paid','provisioning','review'):
            text=self.bot.checkout.order_text(dict(order,status=status,credentials={'username':'private-test-name','password':'private-test-secret'}))
            self.assertNotIn('private-test-secret',text)
            self.assertNotIn('APP DOWNLOAD CODES',text)

    def test_membership_notification_and_status_button_share_the_format(self):
        from streambot.trial_message import membership_ready_text
        order=self.create()
        credentials={'username':'test-member','password':'test-member-password'}
        self.store.update(order['id'],status='fulfilled',credentials=credentials)
        expected=membership_ready_text(order['plan'],credentials)
        self.bot.checkout.notify()
        self.assertEqual(self.calls[-1][1]['text'],expected)
        result=self.click('pay:status:'+order['id'])
        self.assertEqual(result['text'],expected)
        with self.assertRaises(CheckoutError):
            self.service.submit_telegram_tx(99, order['id'], TXID)
        self.assertIsNone(self.store.get(order['id'])['txid'])

    def test_repeated_clicks_and_concurrent_quotes_do_not_duplicate_invoices(self):
        first = self.create()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda n: self.create(request=str(n)), range(4)))
        self.assertTrue(all(o['id'] == first['id'] for o in results))
        self.assertEqual(len(self.store.telegram_orders(42)), 1)
        self.store.update(first['id'], status='paid')
        self.assertEqual(self.create()['id'], first['id'])

    def test_wrong_amount_network_or_time_never_confirms_payment(self):
        order = self.create()
        bad = [{'amount_units': int(order['amount_units']) - 1},
               {'network': 'bitcoin'}, {'block_time': order['created_at'] - 1},
               {'block_time': order['expires_at'] + 1}]
        for overrides in bad:
            self.service.submit_telegram_tx(42, order['id'], TXID)
            self.proof(order, **overrides)
            self.service.verify_order(order_id=order['id'])
            checked = self.store.get(order['id'])
            self.assertEqual(checked['status'], 'pending')
            self.assertIsNone(checked['txid'])
            self.service.provision_pending()
        self.assertEqual(self.panel.calls, [])

    def test_provider_outage_and_recipient_rejection_fail_closed(self):
        order = self.create()
        self.service.submit_telegram_tx(42, order['id'], TXID)
        self.verifier.error = ChainUnavailable()
        self.service.verify_order(order_id=order['id'])
        self.assertEqual(self.store.get(order['id'])['txid'], TXID)
        self.assertIn('retry automatically', self.store.get(order['id'])['message'])
        self.verifier.error = PaymentRejected('Wrong recipient')
        self.service.verify_order(order_id=order['id'])
        self.assertEqual(self.store.get(order['id'])['status'], 'pending')
        self.assertIsNone(self.store.get(order['id'])['txid'])

    def test_transaction_can_only_pay_one_order(self):
        first = self.create()
        self.service.submit_telegram_tx(42, first['id'], TXID)
        self.proof(first)
        self.service.verify_order(order_id=first['id'])
        second = self.create(uid=43)
        self.service.submit_telegram_tx(43, second['id'], TXID)
        self.proof(second)
        self.service.verify_order(order_id=second['id'])
        self.assertEqual(self.store.get(first['id'])['status'], 'paid')
        self.assertEqual(self.store.get(second['id'])['status'], 'pending')
        self.assertIn('already been used', self.store.get(second['id'])['message'])

    def test_txid_entry_survives_restart_and_does_not_leak_into_support(self):
        order = self.create()
        self.click('pay:tx:' + order['id'])
        self.bot = TelegramBot(self.service, api=self.api)
        self.bot.handle({'message': {'message_id': 5, 'from': {'id': 42},
                                    'chat': {'id': 42, 'type': 'private'}, 'text': TXID}})
        self.assertEqual(self.store.get(order['id'])['txid'], TXID)
        self.assertEqual(self.store.metadata(self.bot.checkout.session_key(42)), '')

    def test_bad_txid_is_not_accepted_and_live_demo_action_is_blocked(self):
        order = self.create()
        for text in ('bad', 'https://explorer.example/tx/' + TXID, 'a' * 32 + ' ' + 'b' * 32):
            with self.assertRaises(CheckoutError):
                self.service.submit_telegram_tx(42, order['id'], text)
        self.click('pay:demo:' + order['id'])
        self.assertEqual(self.store.get(order['id'])['status'], 'pending')

    def test_expired_quote_warns_but_accepts_txid_for_a_payment_made_on_time(self):
        order = self.create()
        now = int(time.time())
        with self.store.connection() as db:
            db.execute('UPDATE orders SET created_at=?,expires_at=? WHERE id=?',
                       (now - 200, now - 100, order['id']))
        response = self.click('pay:status:' + order['id'])
        self.assertIn('EXPIRED', response['text'])
        self.service.submit_telegram_tx(42, order['id'], TXID)
        self.proof(order, block_time=now - 150)
        self.service.verify_order(order_id=order['id'])
        self.assertEqual(self.store.get(order['id'])['status'], 'paid')

    def test_demo_simulation_is_explicit_and_uses_nonpayable_wallets(self):
        self.config['mode'] = 'demo'
        response = self.click('pay:quote:month-1:btc')
        self.assertIn('DO NOT SEND FUNDS', response['text'])
        self.assertIn('simulated, not live prices', response['text'])
        order = self.store.telegram_orders(42)[0]
        self.assertTrue(order['asset']['wallet'].startswith('DEMO-'))
        self.click('pay:demo:' + order['id'])
        self.assertEqual(self.store.get(order['id'])['status'], 'paid')


class RateTests(unittest.TestCase):
    def test_usd_and_coin_conversion_share_one_snapshot(self):
        response = Mock()
        response.json.return_value = {'data': {'currency': 'GBP', 'rates':
                                    {'USD': '1.3', 'USDC': '1.299', 'USDT': '1.301',
                                     'ETH': '0.0004', 'BTC': '0.000015'}}}
        http = Mock()
        http.get.return_value = response
        rates = Rates(http=http)
        quote = rates.snapshot('USDC')
        self.assertEqual(quote['usd_per_gbp'], Decimal('1.3'))
        self.assertEqual(quote['crypto_per_gbp'], Decimal('1.299'))
        self.assertEqual(quote['crypto_per_usd'] * quote['usd_per_gbp'], Decimal('1.299'))
        rates.snapshot('BTC')
        self.assertEqual(http.get.call_count, 1)
        rates.fetched_at = 0
        http.get.side_effect = requests.ConnectionError()
        with self.assertRaises(RateUnavailable):
            rates.snapshot('BTC')

    def test_invalid_or_missing_usd_rate_fails_closed(self):
        for usd in (None, 'NaN', '-1', '0'):
            data = {'USDC': '1', 'USDT': '1', 'ETH': '0.1', 'BTC': '0.01'}
            if usd is not None:
                data['USD'] = usd
            response = Mock()
            response.json.return_value = {'data': {'currency': 'GBP', 'rates': data}}
            http = Mock()
            http.get.return_value = response
            with self.assertRaises(RateUnavailable):
                Rates(http=http).snapshot('USDC')


class BitcoinVerificationTests(unittest.TestCase):
    def setUp(self):
        config = json.loads(CONFIG.read_text())
        self.asset = dict(config['assets']['btc'], rpc_url='https://node.example/api')
        self.txid = 'a' * 64
        self.block = 'b' * 64
        self.now = int(time.time())
        self.tx = {'txid': self.txid, 'status': {'confirmed': True, 'block_height': 100,
                   'block_hash': self.block, 'block_time': self.now},
                   'vout': [{'value': 15000, 'scriptpubkey_address': self.asset['wallet']}]}
        self.tip = '102'
        def get(url, **kwargs):
            response = Mock(status_code=200)
            if url.endswith('/block-height/0'):
                response.text = BITCOIN_GENESIS
            elif url.endswith('/block-height/100'):
                response.text = self.block
            elif url.endswith('/blocks/tip/height'):
                response.text = self.tip
            elif url.endswith('/tx/' + self.txid):
                response.json.return_value = self.tx
            else:
                raise AssertionError('Unexpected node call')
            return response
        http = Mock()
        http.get.side_effect = get
        self.verifier = BlockchainVerifier(http=http)

    def verify(self):
        return self.verifier.verify(self.asset, self.txid, self.now - 10, self.now + 100)

    def test_confirmed_payment_proves_actual_recipient_outputs(self):
        proof = self.verify()
        self.assertEqual(proof['amount_units'], 15000)
        self.assertEqual(proof['confirmations'], 3)
        self.tx['vout'][0]['scriptpubkey_address'] = 'different-address'
        with self.assertRaises(PaymentRejected):
            self.verify()

    def test_unconfirmed_or_insufficient_confirmations_cannot_pass(self):
        self.tip = '101'
        with self.assertRaises(PaymentPending):
            self.verify()
        self.tx['status']['confirmed'] = False
        with self.assertRaises(PaymentPending):
            self.verify()

    def test_wrong_token_contract_cannot_pay_an_erc20_invoice(self):
        config = json.loads(CONFIG.read_text())
        asset = dict(config['assets']['usdt-ethereum'], token='0x' + 'f' * 40,
                     rpc_url='https://node.example/rpc')
        with self.assertRaises(PaymentRejected):
            BlockchainVerifier._validate_config(asset)


if __name__ == '__main__':
    unittest.main()
