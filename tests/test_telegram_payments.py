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

    def create_account(self, package_id, username, password, description):
        self.calls.append(package_id)
        return dict(username=username, password=password, server_url='test server')


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
        self.assertIn('EXACTLY: ' + self.service.public(order)['amount'], invoice['text'])
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
        self.assertIn('Your account is ready', self.calls[-1][1]['text'])
        self.assertIn('Username:', self.calls[-1][1]['text'])
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
