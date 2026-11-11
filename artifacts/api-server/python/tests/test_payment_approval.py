"""Invoice-specific overpayment approval; fake chain and panel only."""
import copy
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

from cryptography.fernet import Fernet

from streambot.bot import TelegramBot
from streambot.chains import ChainUnavailable, PaymentPending, PaymentRejected
from streambot.config import load_config
from streambot.rates import Rates
from streambot.service import CheckoutError, CheckoutService
from streambot.store import Store

TXID = '0x' + 'a' * 64


class PaymentApprovalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name) / 'test.sqlite3', Fernet.generate_key())
        self.config = load_config(env={'APP_MODE': 'demo', 'SUPPORT_ADMIN_ID': '900'})
        self.config.update(mode='live', panel_writes=True)
        self.verifier, self.panel = Mock(), Mock()
        self.service = CheckoutService(self.config, self.store, self.verifier, self.panel, Rates(demo=True))
        self.order = self.service.create_order('month-1', 'usdc-ethereum',
                                               owner_telegram_id=42)['order']
        self.proof = dict(network='ethereum', txid=TXID,
                          amount_units=int(self.order['amount_units']) + 5_000_000 + 3484,  # beyond the automatic $5 tolerance
                          block_time=self.order['created_at'], confirmations=62)
        self.verifier.verify.side_effect = lambda *args: copy.deepcopy(self.proof)
        self.sent = []
        self.bot = TelegramBot(self.service, api=lambda method, payload:
                               self.sent.append((method, payload)) or {'message_id': 1})
        self.approval = self.bot.payment_approval

    def preview(self):
        self.approval.preview(900, self.order['id'], TXID)
        return self.store.unseal(self.store.metadata(self.approval.key(900)))['nonce']

    def test_preview_is_not_approval_and_confirmation_rechecks_finalized_proof(self):
        nonce = self.preview()
        self.assertEqual(self.store.get(self.order['id'])['status'], 'pending')
        self.panel.create_account.assert_not_called()
        self.assertEqual(self.sent[-1][1]['parse_mode'], 'HTML')
        self.assertIn('Extra received:', self.sent[-1][1]['text'])
        self.assertIn('No refund', self.sent[-1][1]['text'])
        self.approval.confirm(900, nonce)
        self.assertEqual(self.verifier.verify.call_count, 2)
        for call in self.verifier.verify.call_args_list:
            self.assertIs(call.args[0]['require_finalized'], True)  # manual approval always insists on finality, whatever the asset's everyday policy
            self.assertEqual(call.args[0]['wallet'], self.order['asset']['wallet'])
            self.assertEqual(call.args[2:], (self.order['created_at'], self.order['expires_at']))
        saved = self.store.get(self.order['id'])
        self.assertEqual((saved['status'], saved['txid']), ('paid', TXID))
        self.assertEqual(saved['amount_units'], self.order['amount_units'])
        with self.store.connection() as db:
            payment = db.execute('SELECT * FROM payments WHERE order_id=?', (saved['id'],)).fetchone()
        import json
        self.assertEqual(json.loads(payment['proof'])['amount_units'], self.proof['amount_units'])
        audit = self.store.unseal(self.store.metadata('payment_admin_approval:' + nonce))
        self.assertEqual(audit['administrator'], 900)
        self.assertEqual(audit['quoted_units'], self.order['amount_units'])

    def test_non_admin_never_gets_preview_confirm_or_cancel(self):
        nonce = self.preview()
        for uid in (42, 901, True):
            for action in (
                lambda: self.approval.preview(uid, self.order['id'], TXID),
                lambda: self.approval.confirm(uid, nonce),
                lambda: self.approval.confirm(uid, nonce, cancel=True),
            ):
                with self.assertRaises(CheckoutError):
                    action()

    def test_pending_unavailable_and_rejected_proofs_never_approve(self):
        for error in (PaymentPending(), ChainUnavailable(), PaymentRejected('wrong wallet')):
            self.verifier.verify.side_effect = error
            with self.assertRaises(CheckoutError):
                self.preview()
            self.assertEqual(self.store.get(self.order['id'])['status'], 'pending')
        self.panel.create_account.assert_not_called()

    def test_confirm_rejects_nonfinal_proof_or_changed_amount(self):
        nonce = self.preview()
        self.verifier.verify.side_effect = PaymentPending()
        with self.assertRaises(CheckoutError):
            self.approval.confirm(900, nonce)
        self.verifier.verify.side_effect = lambda *args: dict(self.proof, amount_units=self.proof['amount_units'] + 1)
        with self.assertRaisesRegex(CheckoutError, 'amount changed'):
            self.approval.confirm(900, nonce)
        self.assertEqual(self.store.get(self.order['id'])['status'], 'pending')

    def test_wrong_network_txid_time_confirmations_and_non_overpayments_fail(self):
        valid = copy.deepcopy(self.proof)
        for overrides in (
                dict(network='solana'), dict(txid='0x' + 'b' * 64),
                dict(block_time=self.order['created_at'] - 1), dict(confirmations=11),
                dict(amount_units=int(self.order['amount_units'])),
                dict(amount_units=int(self.order['amount_units']) - 1)):
            self.proof = dict(valid, **overrides)
            with self.assertRaises(CheckoutError):
                self.preview()

    def test_already_claimed_transaction_cannot_pay_another_order(self):
        nonce = self.preview()
        other = self.service.create_order('month-1', 'usdc-ethereum',
                                           owner_telegram_id=43)['order']
        self.store.claim_payment(other['id'], self.proof)
        with self.assertRaisesRegex(CheckoutError, 'already claimed'):
            self.approval.confirm(900, nonce)
        self.assertEqual(self.store.get(self.order['id'])['status'], 'pending')

    def test_cancel_expiry_changed_draft_and_replay_are_safe(self):
        nonce = self.preview()
        self.approval.confirm(900, nonce, cancel=True)
        with self.assertRaises(CheckoutError):
            self.approval.confirm(900, nonce)
        nonce = self.preview()
        newer = self.preview()
        with self.assertRaises(CheckoutError):
            self.approval.confirm(900, nonce)
        draft = self.store.unseal(self.store.metadata(self.approval.key(900)))
        draft['expires'] = 0
        self.store.metadata(self.approval.key(900), self.store.seal(draft))
        with self.assertRaises(CheckoutError):
            self.approval.confirm(900, newer)
        self.approval.confirm(900, self.preview())
        with self.assertRaises(CheckoutError):
            self.approval.confirm(900, newer)

    def test_changed_invoice_does_not_approve(self):
        nonce = self.preview()
        with self.store.connection() as db:
            db.execute('UPDATE orders SET amount_units=? WHERE id=?', ('1', self.order['id']))
        with self.assertRaisesRegex(CheckoutError, 'invoice changed'):
            self.approval.confirm(900, nonce)

    def test_normal_exact_matching_does_not_change_and_cleared_hash_can_be_reviewed(self):
        nonce = self.preview()
        self.service.submit_telegram_tx(42, self.order['id'], TXID)
        self.service.verify_order(order_id=self.order['id'])
        saved = self.store.get(self.order['id'])
        self.assertEqual(saved['status'], 'pending')
        self.assertIsNone(saved['txid'])
        self.assertIn('Do not pay again', saved['message'])
        self.approval.confirm(900, nonce)
        self.assertEqual(self.store.get(self.order['id'])['status'], 'paid')

    def test_old_background_result_cannot_clear_approved_or_replaced_hash(self):
        self.service.submit_telegram_tx(42, self.order['id'], TXID)
        def background(*args):
            self.approval.confirm(900, nonce)
            return copy.deepcopy(self.proof)
        nonce = self.preview()
        self.verifier.verify.side_effect = background
        # The administrator's nested verification must be a separate response.
        def results(*args):
            self.verifier.verify.side_effect = lambda *a: copy.deepcopy(self.proof)
            return background(*args)
        self.verifier.verify.side_effect = results
        self.service.verify_order(order_id=self.order['id'])
        saved = self.store.get(self.order['id'])
        self.assertEqual((saved['status'], saved['txid']), ('paid', TXID))
        self.assertIn('approved by administrator', saved['message'])
        other = self.service.create_order('month-1', 'usdc-ethereum',
                                           owner_telegram_id=44)['order']
        replacement = '0x' + 'c' * 64
        self.store.submit_tx(other['id'], replacement)
        self.store.update_pending_verification(other['id'], TXID, txid=None, message='stale')
        self.assertEqual(self.store.get(other['id'])['txid'], replacement)

    def test_concurrent_confirmations_claim_once(self):
        nonce = self.preview()
        def confirm(_):
            try:
                self.approval.confirm(900, nonce)
                return True
            except CheckoutError:
                return False
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(confirm, range(4))), 1)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM payments').fetchone()[0], 1)

    def test_private_command_and_callback_route_without_optional_tables(self):
        with self.store.connection() as db:
            db.execute('DROP TABLE rs_settings')
            db.execute('DROP TABLE nt_contacts')
        self.service = CheckoutService(self.config, self.store, self.verifier, self.panel, Rates(demo=True))
        self.bot = TelegramBot(self.service, api=lambda *args: {'message_id': 1})
        self.approval = self.bot.payment_approval
        self.bot.handle({'message': {'message_id': 1, 'from': {'id': 900},
                        'chat': {'id': 900, 'type': 'private'},
                        'text': '/approveoverpayment ' + self.order['id'] + ' ' + TXID}})
        nonce = self.store.unseal(self.store.metadata(self.approval.key(900)))['nonce']
        callback = dict(id='test', data='pa:confirm:' + nonce, **{'from': {'id': 900}},
                        message={'chat': {'id': -1, 'type': 'group'}})
        self.bot.handle({'callback_query': callback})
        self.assertEqual(self.store.get(self.order['id'])['status'], 'pending')
        callback['message']['chat'] = {'id': 900, 'type': 'private'}
        self.bot.handle({'callback_query': callback})
        self.assertEqual(self.store.get(self.order['id'])['status'], 'paid')
