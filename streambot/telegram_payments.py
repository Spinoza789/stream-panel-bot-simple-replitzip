"""Custom wallet quotes and owned TXID submission; no Telegram payment provider."""
import logging
import time
from datetime import datetime, timezone

from .service import CheckoutError
from .store import digest

log = logging.getLogger(__name__)
NETWORKS = {'ethereum': 'Ethereum (ERC-20)', 'solana': 'Solana (SPL)', 'bitcoin': 'Bitcoin'}


def network_name(asset):
    if asset['network'] == 'ethereum' and not asset.get('token'):
        return 'Ethereum (native ETH)'
    return NETWORKS[asset['network']]


class TelegramCheckout:
    def __init__(self, bot):
        self.bot = bot
        self.service = bot.service
        self.store = bot.store

    def session_key(self, uid):
        return 'tg_tx_session:' + digest(uid)

    def clear_session(self, uid):
        self.store.metadata(self.session_key(uid), '')

    def crypto_keyboard(self, plan):
        rows = []
        for asset in self.service.config['assets'].values():
            if asset.get('enabled', True):
                label = asset['symbol'] + ' · ' + network_name(asset)
                rows.append([{'text': label, 'callback_data': f"pay:quote:{plan['id']}:{asset['id']}"}])
        rows.append([{'text': '⬅️ Back', 'callback_data':
                     f"plan:connections:{plan['months']}:{int(bool(plan.get('adult_content')))}:{plan['connections']}"}])
        return {'inline_keyboard': rows}

    def order_keyboard(self, order):
        oid = order['id']
        rows = []
        if order['status'] == 'pending':
            rows.append([{'text': "I've paid — enter TXID", 'callback_data': 'pay:tx:' + oid}])
            if self.service.config['mode'] == 'demo':
                rows.append([{'text': 'Simulate payment (demo only)', 'callback_data': 'pay:demo:' + oid}])
        rows.append([{'text': 'Check payment status', 'callback_data': 'pay:status:' + oid}])
        if order['status'] == 'pending':
            rows.append([{'text': '⬅️ Back to crypto choices',
                          'callback_data': 'pay:choose:' + order['plan']['id']}])
        rows.append([{'text': 'My orders', 'callback_data': 'pay:orders'},
                     {'text': 'Main menu', 'callback_data': 'menu'}])
        return {'inline_keyboard': rows}

    def order_text(self, order):
        plan, asset = order['plan'], order['asset']
        demo = self.service.config['mode'] == 'demo'
        lines = ['DEMO — DO NOT SEND FUNDS.\n' if demo else 'CRYPTO PAYMENT\n',
                 'Order: ' + order['id'], plan['name'] + ' · ' + plan.get('detail', ''),
                 'Status: ' + order['status'].upper()]
        if plan.get('usd_price'):
            lines.append(f"Membership value: ${plan['usd_price']} USD (from £{plan['gbp_price']})")
            if demo:
                lines.append('Exchange rates below are simulated, not live prices.')
        if order['status'] == 'pending':
            expiry = datetime.fromtimestamp(order['expires_at'], timezone.utc).strftime('%d %b %Y %H:%M UTC')
            lines.extend(['', 'Send EXACTLY: ' + order['amount'] + ' ' + asset['symbol'],
                          'Network: ' + network_name(asset),
                          'Recipient wallet:\n' + asset['wallet'], 'Quote expires: ' + expiry,
                          'Includes the small order-matching adjustment. Pay network fees separately.',
                          'Confirmations required: ' + str(asset.get('confirmations', 1)),
                          'Never use a different coin or network.'])
            if time.time() > order['expires_at']:
                lines.append('EXPIRED — do not send a new payment. If you already paid within the quote window, submit that TXID.')
            else:
                lines.append('After sending, tap “I’ve paid — enter TXID” and paste the transaction hash.')
            if order.get('txid'):
                lines.append('TXID received. The backend checks the chain automatically; do not pay again.')
        elif order['status'] in ('paid', 'provisioning'):
            lines.append('Payment is confirmed. Preparing your account. Do not pay again.')
        elif order['status'] == 'fulfilled':
            credentials = order.get('credentials') or {}
            lines.extend(['', 'Your account is ready.',
                          'Username: ' + credentials.get('username', ''),
                          'Password: ' + credentials.get('password', '')])
            if credentials.get('server_url'):
                lines.append('Server: ' + credentials['server_url'])
            lines.append('Keep these details private.')
        elif order['status'] == 'review':
            lines.append('Manual review is needed. Do not pay again; contact support with this order ID.')
        if order.get('message'):
            lines.extend(['', order['message']])
        return '\n'.join(lines)

    def show_order(self, uid, order):
        self.bot.send(uid, self.order_text(order), self.order_keyboard(order))
        self.store.metadata('tg_notice:' + order['id'], order['status'] + ':' + order.get('message', ''))

    def show_orders(self, uid):
        orders = self.store.telegram_orders(uid, limit=10)
        rows = [[{'text': order['plan']['name'] + ' · ' + order['status'] + ' · ' + order['id'][:8],
                  'callback_data': 'pay:status:' + order['id']}] for order in orders]
        rows.append([{'text': '⬅️ Back', 'callback_data': 'menu'}])
        self.bot.send(uid, 'MY ORDERS\n\nChoose an order to view it.' if orders else 'No paid orders yet.',
                      {'inline_keyboard': rows})

    def handle_callback(self, uid, action, callback_id):
        if not action.startswith('pay:'):
            return False
        parts = action.split(':')
        try:
            if action == 'pay:orders':
                self.clear_session(uid)
                self.show_orders(uid)
            elif len(parts) == 3 and parts[1] == 'choose':
                self.clear_session(uid)
                plan = next((p for p in self.service.config['plans'] if p['id'] == parts[2]), None)
                if not plan:
                    raise CheckoutError('Membership not found. Please start again.')
                self.bot.send(uid, plan['name'] + ' · ' + plan.get('detail', '') +
                              '\n\nChoose a cryptocurrency AND network. The next step locks a quote and displays its USD equivalent.'
                              '\nExisting invoices remain in My orders. Never pay two invoices for the same purchase.',
                              self.crypto_keyboard(plan))
            elif len(parts) == 4 and parts[1] == 'quote':
                self.clear_session(uid)
                result = self.service.create_order(parts[2], parts[3], owner_telegram_id=uid,
                                                   request_key='tg_quote:' + digest(f'{uid}:{callback_id}'))
                self.show_order(uid, result['order'])
            elif len(parts) == 3 and parts[1] in ('status', 'tx', 'demo'):
                order = self.service.telegram_order(uid, parts[2])
                if parts[1] == 'tx' and order['status'] == 'pending':
                    self.store.metadata(self.bot.support.session_key(uid), '0')
                    prompt = self.bot.send(uid, 'Order: ' + order['id'] +
                                           '\nPaste ONLY the transaction hash/TXID, not a link. '
                                           'A submitted hash is not proof of payment; the backend verifies it. '
                                           'Send /cancel to stop TXID entry.',
                                           {'force_reply': True, 'selective': True,
                                            'input_field_placeholder': 'Paste transaction hash'})
                    self.store.metadata(self.session_key(uid), self.store.seal({
                        'order_id': order['id'], 'prompt_id': prompt.get('message_id'),
                        'expires_at': int(time.time()) + 900}))
                else:
                    if parts[1] == 'demo':
                        self.service.demo_pay_telegram(uid, order['id'])
                        order = self.service.telegram_order(uid, order['id'])
                    self.show_order(uid, order)
            else:
                raise CheckoutError('Payment option unavailable. Open My orders or start again.')
        except CheckoutError as exc:
            self.bot.send(uid, str(exc), {'inline_keyboard': [[
                {'text': 'My orders', 'callback_data': 'pay:orders'},
                {'text': 'Main menu', 'callback_data': 'menu'}]]})
        return True

    def handle_message(self, message, command):
        uid = message['from']['id']
        if command in ('/cancel', '/start', '/help', '/contact', '/support'):
            self.clear_session(uid)
            return False
        if command == '/orders':
            self.show_orders(uid)
            return True
        text = message.get('text', '').strip()
        explicit = command == '/txid'
        value = self.store.metadata(self.session_key(uid))
        session = self.store.unseal(value) if value else None
        if not explicit and (command.startswith('/') or not session):
            return False
        try:
            if explicit:
                parts = text.split()
                if len(parts) != 3:
                    raise CheckoutError('Use /txid ORDER_ID TRANSACTION_HASH, or tap the TXID button on your order.')
                oid, txid = parts[1:]
            else:
                if session['expires_at'] < time.time():
                    self.clear_session(uid)
                    raise CheckoutError('TXID entry timed out. Open My orders and select your order again.')
                reply_id = (message.get('reply_to_message') or {}).get('message_id')
                if reply_id is not None and reply_id != session.get('prompt_id'):
                    raise CheckoutError('Reply to the TXID prompt for this order, or use /txid ORDER_ID HASH.')
                oid, txid = session['order_id'], text
            if not self.store.limit('tg_verify:' + digest(f'{uid}:{oid}'), 12, 60):
                raise CheckoutError('Please wait a minute before submitting another transaction.')
            order = self.service.submit_telegram_tx(uid, oid, txid)
            self.clear_session(uid)
            self.show_order(uid, order)
        except CheckoutError as exc:
            self.bot.send(uid, str(exc))
        return True

    def notify(self):
        for order in self.store.telegram_orders(limit=20):
            retry_key = 'tg_notice_retry:' + order['id']
            if int(self.store.metadata(retry_key) or '0') > time.time():
                continue
            try:
                self.show_order(order['owner_id'], self.service.public(order))
            except Exception as exc:
                # Never log tokens, wallets with credentials, or message contents.
                if getattr(exc, 'code', 0) == 403:
                    self.store.metadata('tg_notice:' + order['id'], order['status'] + ':' + order['message'])
                else:
                    self.store.metadata(retry_key, int(time.time()) + 60)
                    log.warning('Telegram payment notification deferred (%s).', type(exc).__name__)
