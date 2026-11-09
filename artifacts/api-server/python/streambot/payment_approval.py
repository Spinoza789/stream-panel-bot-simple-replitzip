"""Administrator-confirmed, invoice-specific Ethereum USDC overpayment exception."""
import json
import re
import secrets
import time
from html import escape

from .chains import ChainUnavailable, PaymentPending, PaymentRejected
from .config import display_units
from .service import CheckoutError
from .store import digest


class PaymentApproval:
    def __init__(self, bot):
        self.bot = bot
        self.service = bot.service
        self.store = bot.store

    def admin(self, uid):
        if type(uid) is not int or uid != self.service.config.get('support_admin_id'):
            raise CheckoutError('Only the configured administrator can approve an overpayment.')

    def row(self, db, oid):
        row = db.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone()
        if not row or row['kind'] != 'paid' or row['status'] != 'pending':
            raise CheckoutError('Approval requires an existing unpaid membership order.')
        order = self.store.decode(row)
        asset = order['asset']
        if (order['plan'].get('reseller_purchase') or asset.get('id') != 'usdc-ethereum'
                or asset.get('network') != 'ethereum' or asset.get('symbol') != 'USDC'):
            raise CheckoutError('This exception supports Ethereum USDC membership orders only.')
        return row, order

    @staticmethod
    def fingerprint(row):
        # TXID/message may be cleared by normal verification after an amount
        # mismatch. The invoice's identity, ownership and financial terms may not.
        return digest(json.dumps([row[key] for key in
            ('id', 'kind', 'status', 'amount_units', 'created_at', 'expires_at', 'plan_json', 'asset_json')]))

    def key(self, uid):
        return 'payment_approval_draft:' + str(uid)

    def proof(self, order, txid):
        asset = dict(order['asset'])
        asset['rpc_url'] = self.service.config['assets'][asset['id']].get('rpc_url', '')
        asset['require_finalized'] = True
        try:
            proof = self.service.verifier.verify(asset, txid, order['created_at'], order['expires_at'])
        except PaymentPending:
            raise CheckoutError('Payment is not finalized yet. Nothing was approved; try again later.') from None
        except PaymentRejected:
            raise CheckoutError('Blockchain proof failed the token, wallet, transaction or payment-window checks. Nothing was approved.') from None
        except ChainUnavailable:
            raise CheckoutError('The blockchain provider could not verify this payment. Nothing was approved.') from None
        if (proof.get('network') != asset['network'] or proof.get('txid') != txid
                or type(proof.get('amount_units')) is not int
                or proof['amount_units'] <= int(order['amount_units'])
                or type(proof.get('block_time')) is not int
                or not order['created_at'] <= proof['block_time'] <= order['expires_at']
                or type(proof.get('confirmations')) is not int
                or proof['confirmations'] < asset.get('confirmations', 12)):
            raise CheckoutError('This is not a verified, sufficiently confirmed overpayment for this invoice.')
        return proof

    def unused(self, db, oid, txid):
        if db.execute('SELECT order_id FROM payments WHERE (network=? AND lower(txid)=?) OR order_id=?',
                      ('ethereum', txid, oid)).fetchone():
            raise CheckoutError('This payment or order was already claimed. Nothing was approved.')

    def preview(self, uid, oid, txid):
        self.admin(uid)
        if not re.fullmatch(r'[0-9a-f]{24}', oid) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', txid):
            raise CheckoutError('Use /approveoverpayment ORDER_ID ETHEREUM_TXID.')
        txid = txid.lower()
        with self.store.connection() as db:
            row, order = self.row(db, oid)
            self.unused(db, oid, txid)
            fingerprint = self.fingerprint(row)
        proof = self.proof(order, txid)
        draft = dict(order_id=oid, txid=txid, amount_units=proof['amount_units'],
                     fingerprint=fingerprint, nonce=secrets.token_hex(12),
                     expires=int(time.time()) + 600)
        self.store.metadata(self.key(uid), self.store.seal(draft))
        amount = lambda value: display_units(value, order['asset']['decimals'])
        self.bot.send(uid,
            '<b>🛡 ONE-ORDER OVERPAYMENT APPROVAL</b>\n\n'
            '<b>Order:</b> <code>' + escape(oid) + '</code>\n'
            '<b>Quoted:</b> ' + amount(order['amount_units']) + ' USDC\n'
            '<b>Received:</b> ' + amount(proof['amount_units']) + ' USDC\n'
            '<b>Extra received:</b> ' + amount(proof['amount_units'] - int(order['amount_units'])) + ' USDC\n'
            '<b>Wallet:</b> <code>' + escape(order['asset']['wallet']) + '</code>\n'
            '<b>TXID:</b> <code>' + txid + '</code>\n\n'
            '✅ Finalized blockchain proof checked. Nothing approved yet.\n'
            'Confirmation checks the blockchain again, claims this TXID for this order, '
            'and queues the normal membership provisioning. '
            '<b>No refund, wallet transfer or credit balance is created for the extra amount.</b> '
            'The quote stays unchanged and future orders still require exact amounts.',
            {'inline_keyboard': [
                [{'text': '✅ Approve this order only', 'callback_data': 'pa:confirm:' + draft['nonce']}],
                [{'text': 'Cancel approval', 'callback_data': 'pa:cancel:' + draft['nonce']}],
            ]}, parse_mode='HTML')

    def draft(self, db, uid, nonce):
        saved = db.execute('SELECT value FROM metadata WHERE key=?', (self.key(uid),)).fetchone()
        draft = self.store.unseal(saved[0]) if saved else None
        if not draft or draft['nonce'] != nonce or draft['expires'] <= int(time.time()):
            raise CheckoutError('This approval preview expired, changed or was already used. Open a new preview.')
        return draft

    def confirm(self, uid, nonce, cancel=False):
        self.admin(uid)
        with self.store.connection() as db:
            draft = self.draft(db, uid, nonce)
            if not cancel:
                row, order = self.row(db, draft['order_id'])
                if self.fingerprint(row) != draft['fingerprint']:
                    raise CheckoutError('The invoice changed. Nothing was approved.')
        # Network I/O never holds the database transaction lock.
        proof = None if cancel else self.proof(order, draft['txid'])
        if proof and proof['amount_units'] != draft['amount_units']:
            raise CheckoutError('The verified amount changed. Open a new preview.')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self.draft(db, uid, nonce)
            if current != draft:
                raise CheckoutError('The approval preview changed. Nothing was approved.')
            if not cancel:
                row, order = self.row(db, draft['order_id'])
                if self.fingerprint(row) != draft['fingerprint']:
                    raise CheckoutError('The invoice changed. Nothing was approved.')
                self.unused(db, draft['order_id'], draft['txid'])
                audit = dict(administrator=uid, order_id=draft['order_id'],
                             at=int(time.time()), action='one_order_overpayment_approval',
                             quoted_units=order['amount_units'], received_units=proof['amount_units'],
                             txid=draft['txid'], proof=proof)
                db.execute('INSERT INTO payments VALUES(?,?,?,?)',
                           (proof['network'], proof['txid'], draft['order_id'], json.dumps(proof)))
                db.execute("UPDATE orders SET status='paid',txid=?,message="
                           "'Payment approved by administrator after verified overpayment. Preparing your account.' "
                           "WHERE id=? AND status='pending'", (proof['txid'], draft['order_id']))
                db.execute('INSERT INTO metadata VALUES(?,?)',
                           ('payment_admin_approval:' + nonce, self.store.seal(audit)))
            db.execute('DELETE FROM metadata WHERE key=?', (self.key(uid),))
        return draft['order_id']

    def message(self, uid, command, argument):
        if command != '/approveoverpayment':
            return False
        self.admin(uid)
        parts = argument.split()
        if len(parts) != 2:
            raise CheckoutError('Use /approveoverpayment ORDER_ID ETHEREUM_TXID. This opens a preview, not an automatic approval.')
        self.preview(uid, *parts)
        return True

    def callback(self, uid, action):
        if not action.startswith('pa:'):
            return False
        self.admin(uid)
        parts = action.split(':')
        if len(parts) != 3 or parts[1] not in ('confirm', 'cancel'):
            raise CheckoutError('Invalid payment approval option.')
        oid = self.confirm(uid, parts[2], cancel=parts[1] == 'cancel')
        self.bot.send(uid, 'Approval cancelled. Nothing was changed.' if parts[1] == 'cancel' else
                      'Payment approved for order ' + oid + '. Normal membership preparation is queued. '
                      'Do not pay again. No extra credit or automatic refund was created.')
        return True
