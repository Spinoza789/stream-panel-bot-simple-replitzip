"""Custom wallet quotes and owned TXID submission; no Telegram payment provider."""
import logging
import time
from datetime import datetime, timezone
from html import escape

from .service import CheckoutError
from .store import digest
from .trial_message import membership_ready_text

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

    def crypto_keyboard(self, plan, renew_of=None):
        rows = []
        for asset in self.service.config['assets'].values():
            if asset.get('enabled', True):
                label = asset['symbol'] + ' · ' + network_name(asset)
                data = f"pay:rquote:{renew_of}:{asset['id']}" if renew_of else f"pay:quote:{plan['id']}:{asset['id']}"
                rows.append([{'text': label, 'callback_data': data}])
        rows.append([{'text': '⬅️ Back', 'callback_data': 'pay:orders' if renew_of else f"plan:duration:{plan['months']}"}])
        return {'inline_keyboard': rows}

    def renew(self, uid, order_id):
        """Coin picker for renewing a delivered membership. The order is quoted only when a coin is tapped."""
        order = self.service.telegram_order(uid, order_id)
        if order['kind'] != 'paid' or order['status'] != 'fulfilled' or order['plan'].get('reseller_purchase'):
            raise CheckoutError('Only a delivered membership can be renewed.')
        plan = order['plan']
        self.clear_session(uid)
        self.bot.send(uid, '<b>🔁 RENEW YOUR MEMBERSHIP</b>\n\n' + escape(plan['name'] + ' · ' + plan.get('detail', '')) +
                      '\n\nSame login, extended by ' + escape(str(plan['months'])) + (' month' if plan['months'] == 1 else ' months') +
                      ' from its current expiry. Pick how you want to pay.',
                      self.crypto_keyboard(plan, renew_of=order['id']), parse_mode='HTML')

    def choose(self, uid, plan):
        """Coin/network picker for a chosen plan; no order exists until a coin is tapped."""
        self.clear_session(uid)
        self.bot.send(uid, '<b>🪙 CHOOSE COIN &amp; NETWORK</b>\n\n' +
                      escape(plan['name'] + ' · ' + plan.get('detail', '')) +
                      '\n\nPick how you want to pay. The next screen shows the exact amount and the wallet to send it to.',
                      self.crypto_keyboard(plan), parse_mode='HTML')

    def order_keyboard(self, order):
        oid = order['id']
        rows = []
        pending = order['status'] == 'pending'
        checking = pending and bool(order.get('txid'))
        if pending and not checking:
            rows.append([{'text': "✅ I've paid — enter TXID", 'callback_data': 'pay:tx:' + oid}])
            if self.service.config['mode'] == 'demo':
                rows.append([{'text': 'Simulate payment (demo only)', 'callback_data': 'pay:demo:' + oid}])
        else:
            rows.append([{'text': '🔄 Check payment status', 'callback_data': 'pay:status:' + oid}])
        rows.append([{'text': 'ℹ️ Details & help', 'callback_data': 'pay:details:' + oid}])
        if pending and not checking:
            rows.append([{'text': '⬅️ Back', 'callback_data': 'rs:packages' if order['plan'].get('reseller_purchase') else 'pay:choose:' + order['plan']['id']},
                         {'text': 'Main menu', 'callback_data': 'menu'}])
        else:
            rows.append([{'text': 'My orders', 'callback_data': 'pay:orders'},
                         {'text': 'Main menu', 'callback_data': 'menu'}])
        return {'inline_keyboard': rows}

    def tolerance_note(self, order):
        tolerance = self.service.config.get('payment_tolerance_usd', {})
        under, over = tolerance.get('under', '0'), tolerance.get('over', '0')
        if order['plan'].get('tolerance_under_units') and (under != '0' or over != '0'):
            return 'Up to $' + escape(under) + ' short or $' + escape(over) + ' over is still accepted.'
        return 'Exact amount only. Do not round it.'

    def expiry(self, order):
        return datetime.fromtimestamp(order['expires_at'], timezone.utc).strftime('%H:%M UTC, %d %b')

    def order_text(self, order):
        """The payment message: only what is needed to pay. Everything else lives behind Details & help."""
        plan, asset = order['plan'], order['asset']
        demo = self.service.config['mode'] == 'demo'
        if order['status']=='fulfilled' and plan.get('reseller_purchase'):
            purchase=plan['reseller_purchase']['package']
            return ('DEMO — simulated payment.\n\n' if demo else '')+'<b>'+escape(str(purchase['credits']))+' credits added to your reseller account.</b>\nYour reseller account is active: open the Reseller dashboard or /reseller to create trials and subscriptions.\nPurchase: '+escape(order['id'])
        if order['status']=='fulfilled' and plan.get('renew_of'):
            creds=order['credentials'] or {}
            until=creds.get('expires_at')
            when=datetime.fromtimestamp(int(until),timezone.utc).strftime('%d %b %Y') if isinstance(until,int) or (isinstance(until,str) and until.isdigit()) else None
            return ('DEMO — simulated payment.\n\n' if demo else '')+'<b>✅ Membership extended.</b>\nYour existing login keeps working'+(' until <b>'+escape(when)+'</b>' if when else '')+'.\nOrder: '+escape(order['id'])
        if order['status']=='fulfilled':
            text=membership_ready_text(plan,order['credentials'])
            return ('DEMO — DO NOT SEND FUNDS.\n\n' if demo else '')+text
        e = lambda value: escape(str(value))
        expired = time.time() > order['expires_at']
        checking = order['status'] == 'pending' and bool(order.get('txid'))
        banner = '<b>🧪 DEMO — DO NOT SEND FUNDS</b>\n' if demo else ''
        item = e(plan['name'] + ' · ' + plan.get('detail', ''))
        order_line = '🧾 Order <code>' + e(order['id']) + '</code>'
        if order['status'] == 'pending' and checking:
            lines = [banner + '<b>🔎 PAYMENT VERIFICATION</b>', item, '',
                     '<b>✅ TXID received — do not send another payment.</b>', '<code>' + e(order['txid']) + '</code>', '',
                     'We are checking the blockchain. Tap <b>Check payment status</b> for updates.']
        elif order['status'] == 'pending' and expired:
            lines = [banner + '<b>⌛ QUOTE EXPIRED — DO NOT PAY</b>', item, '',
                     'This quote expired at ' + e(self.expiry(order)) + '.',
                     'Already sent it in time? Tap <b>I\'ve paid</b> and enter the TXID. Otherwise go back and start a new order.']
        elif order['status'] == 'pending':
            lines = [banner + '<b>💳 PAY WITH ' + e(asset['symbol']) + '</b>', item, '',
                     '<b>💰 AMOUNT TO SEND</b>', '<code>' + e(order['amount']) + '</code> ' + e(asset['symbol']),
                     '<b>on ' + e(network_name(asset)) + ' to</b>', '<code>' + e(asset['wallet']) + '</code>', '',
                     '👆 Tap the amount or the wallet to copy it.',
                     '⚠️ ' + self.tolerance_note(order) + ' Network fees are extra.',
                     '', 'Sent it? Tap <b>I\'ve paid</b> and paste your TXID.', '',
                     '⏰ Expires ' + e(self.expiry(order))]
        elif order['status'] in ('paid', 'provisioning'):
            lines = [banner + '<b>✅ PAYMENT CONFIRMED</b>', item, '', 'Preparing your account. Do not pay again.']
        else:
            lines = [banner + '<b>🛟 MANUAL REVIEW NEEDED</b>', item, '',
                     'Do not pay again. Contact support with your order ID.']
        if order.get('message'):
            lines.extend(['', '<b>📍 Update:</b> ' + e(order['message'])])
        lines.extend(['', order_line])
        return '\n'.join(lines)

    def details_text(self, order):
        """Everything we used to cram into the invoice: reference price, confirmations, what to do if something went wrong."""
        plan, asset = order['plan'], order['asset']
        e = lambda value: escape(str(value))
        demo = self.service.config['mode'] == 'demo'
        lines = [('<b>🧪 DEMO — DO NOT SEND FUNDS</b>\n' if demo else '') + '<b>ℹ️ PAYMENT DETAILS</b>',
                 e(plan['name'] + ' · ' + plan.get('detail', '')), '',
                 '<b>Amount:</b> <code>' + e(order['amount']) + '</code> ' + e(asset['symbol']),
                 '<b>Network:</b> ' + e(network_name(asset)) + ' — use only ' + e(asset['symbol']) + ' on this network.',
                 '<b>Wallet:</b> <code>' + e(asset['wallet']) + '</code>',
                 '<b>Quote expires:</b> ' + e(self.expiry(order)),
                 '<b>Confirmations required:</b> ' + e(asset.get('confirmations', 1)),
                 '<b>Order ID:</b> <code>' + e(order['id']) + '</code>',
                 '<b>Status:</b> ' + e(order['status'].upper())]
        if plan.get('usd_price'):
            lines.extend(['', '<b>Price reference — NOT the amount to send</b>',
                          '$' + e(plan['usd_price']) + ' USD (from £' + e(plan['gbp_price']) + '). Send the crypto amount above. '
                          + self.tolerance_note(order) + ' Anything further off needs support.'])
            if demo:
                lines.append('Exchange rates are simulated, not live prices.')
        if order.get('txid'):
            lines.extend(['', '<b>TXID:</b> <code>' + e(order['txid']) + '</code>'])
        if order.get('message'):
            lines.extend(['', '<b>Update:</b> ' + e(order['message'])])
        lines.extend(['', '<b>Something went wrong?</b>',
                      '• Sent an amount outside that range, or the wrong coin or network? <b>Do not send more.</b> Contact support with your order ID and TXID.',
                      '• Paid after the quote expired? Submit the TXID anyway and contact support.',
                      '• A submitted TXID is not confirmation. Credits or logins arrive once the payment is verified on-chain.'])
        return '\n'.join(lines)

    def show_details(self, uid, order):
        rows = [[{'text': '🛟 Payment help', 'callback_data': 'menu:contact'}],
                [{'text': 'My orders', 'callback_data': 'pay:orders'}, {'text': 'Main menu', 'callback_data': 'menu'}]]
        self.bot.send(uid, self.details_text(order), {'inline_keyboard': rows}, parse_mode='HTML')

    def show_order(self, uid, order):
        # Invoices and logins are kept as their own messages, never edited away by later navigation.
        self.bot.send(uid, self.order_text(order), self.order_keyboard(order), parse_mode='HTML', keep=True)
        self.store.metadata('tg_notice:' + order['id'], order['status'] + ':' + order.get('message', ''))
        if order['status'] == 'fulfilled' and order['plan'].get('reseller_purchase'):
            try: self.bot.reseller.onboard_if_due(uid)
            except Exception as exc:
                if getattr(exc, 'code', None) != 403: log.warning('Reseller onboarding deferred (%s).', type(exc).__name__)

    def show_orders(self, uid):
        orders = self.store.telegram_orders(uid, limit=10)
        rows = [[{'text': order['plan']['name'] + ' · ' + order['status'] + ' · ' + order['id'][:8],
                  'callback_data': 'pay:status:' + order['id']}] for order in orders]
        rows.append([{'text': '⬅️ Back', 'callback_data': 'menu'}])
        self.bot.send(uid, '<b>🧾 MY ORDERS</b>\n\nChoose an order to view it.' if orders else '<b>🧾 MY ORDERS</b>\n\nNo paid orders yet.',
                      {'inline_keyboard': rows}, parse_mode='HTML')

    def handle_callback(self, uid, action, callback_id):
        if not action.startswith('pay:'):
            return False
        parts = action.split(':')
        try:
            if action == 'pay:orders':
                self.clear_session(uid)
                self.show_orders(uid)
            elif len(parts) == 3 and parts[1] == 'choose':
                plan = next((p for p in self.service.config['plans'] if p['id'] == parts[2]), None)
                if not plan:
                    raise CheckoutError('Membership not found. Please start again.')
                self.choose(uid, plan)
            elif len(parts) == 3 and parts[1] == 'renew':
                self.renew(uid, parts[2])
            elif len(parts) == 4 and parts[1] == 'rquote':
                self.clear_session(uid)
                result = self.service.renew_order(uid, parts[2], parts[3], request_key='tg_quote:' + digest(f'{uid}:{callback_id}'))
                self.show_order(uid, result['order'])
            elif len(parts) == 4 and parts[1] == 'quote':
                self.clear_session(uid)
                result = self.service.create_order(parts[2], parts[3], owner_telegram_id=uid,
                                                   request_key='tg_quote:' + digest(f'{uid}:{callback_id}'))
                self.show_order(uid, result['order'])
            elif len(parts) == 3 and parts[1] in ('status', 'tx', 'demo', 'details'):
                order = self.service.telegram_order(uid, parts[2])
                if parts[1] == 'details':
                    self.show_details(uid, order)
                elif parts[1] == 'tx' and order['status'] == 'pending':
                    self.bot.tickets.state(uid, clear=True)  # the next text is a TXID, not a ticket message
                    prompt = self.bot.send(uid, '<b>🔗 ENTER TRANSACTION ID</b>\n\nPaste the transaction hash (TXID) of your payment, not a link.'
                                           '\n<b>Do not send another payment.</b>\n\nSend /cancel to stop.',
                                           {'force_reply': True, 'selective': True,
                                            'input_field_placeholder': 'Paste transaction hash'}, parse_mode='HTML', keep=True)
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
