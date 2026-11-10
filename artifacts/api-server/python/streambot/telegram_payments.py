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

    def crypto_keyboard(self, plan):
        rows = []
        for asset in self.service.config['assets'].values():
            if asset.get('enabled', True):
                label = asset['symbol'] + ' · ' + network_name(asset)
                rows.append([{'text': label, 'callback_data': f"pay:quote:{plan['id']}:{asset['id']}"}])
        rows.append([{'text': '⬅️ Back', 'callback_data': f"plan:duration:{plan['months']}"}])
        return {'inline_keyboard': rows}

    def choose(self, uid, plan):
        """Coin/network picker for a chosen plan; no order exists until a coin is tapped."""
        self.clear_session(uid)
        self.bot.send(uid, '<b>🪙 CHOOSE COIN &amp; NETWORK</b>\n\n' +
                      escape(plan['name'] + ' · ' + plan.get('detail', '')) +
                      '\n\nThe next screen shows the <b>exact crypto amount to send</b> and a copyable wallet.'
                      '\n⚠️ The rounded USD price is a reference only. Do not use it as the transfer amount.'
                      '\n\nExisting invoices stay in <b>My orders</b>. Never pay two invoices for the same purchase.',
                      self.crypto_keyboard(plan), parse_mode='HTML')

    def order_keyboard(self, order):
        oid = order['id']
        rows = []
        if order['status'] == 'pending':
            if not order.get('txid') and time.time() <= order['expires_at']:
                rows.append([
                    {'text': '📋 Copy exact amount', 'copy_text': {'text': order['amount']}},
                    {'text': '📋 Copy wallet', 'copy_text': {'text': order['asset']['wallet']}},
                ])
            if not order.get('txid'):
                rows.append([{'text': "✅ I've paid — enter TXID", 'callback_data': 'pay:tx:' + oid}])
            if self.service.config['mode'] == 'demo':
                rows.append([{'text': 'Simulate payment (demo only)', 'callback_data': 'pay:demo:' + oid}])
        rows.append([{'text': '🔄 Check payment status', 'callback_data': 'pay:status:' + oid}])
        if order['status'] == 'pending' and not order.get('txid'):
            rows.append([{'text': '⬅️ Back to crypto choices',
                          'callback_data': 'rs:packages' if order['plan'].get('reseller_purchase') else 'pay:choose:' + order['plan']['id']}])
        rows.append([{'text': 'My orders', 'callback_data': 'pay:orders'},
                     {'text': 'Main menu', 'callback_data': 'menu'}])
        rows.append([{'text': '🛟 Payment help', 'callback_data': 'menu:contact'}])
        return {'inline_keyboard': rows}

    def order_text(self, order):
        plan, asset = order['plan'], order['asset']
        demo = self.service.config['mode'] == 'demo'
        if order['status']=='fulfilled' and plan.get('reseller_purchase'):
            purchase=plan['reseller_purchase']['package']
            return ('DEMO — simulated payment.\n\n' if demo else '')+str(purchase['credits'])+' credits added to your reseller account.\nPurchase: '+order['id']+'\nUse My Balance to see available and reserved credits.'
        if order['status']=='fulfilled':
            text=membership_ready_text(plan,order['credentials'])
            return ('DEMO — DO NOT SEND FUNDS.\n\n' if demo else '')+text
        e = lambda value: escape(str(value))
        expired = time.time() > order['expires_at']
        checking = order['status'] == 'pending' and bool(order.get('txid'))
        heading = '🔎 PAYMENT VERIFICATION' if checking else '💳 CRYPTO PAYMENT'
        lines = [('<b>🧪 DEMO — DO NOT SEND FUNDS</b>\n' if demo else '') + '<b>' + heading + '</b>',
                 e(plan['name'] + ' · ' + plan.get('detail', ''))]
        if order['status'] == 'pending':
            expiry = datetime.fromtimestamp(order['expires_at'], timezone.utc).strftime('%d %b %Y %H:%M UTC')
            if checking:
                lines.extend(['', '<b>✅ TXID received — do not send another payment.</b>',
                              '<code>' + e(order['txid']) + '</code>',
                              'We are checking the blockchain. A submitted TXID is not payment confirmation.'])
            else:
                lines.extend(['', '<b>⌛ QUOTE EXPIRED — DO NOT PAY</b>' if expired else '<b>💰 SEND EXACTLY</b>',
                              '<code>' + e(order['amount']) + '</code> <b>' + e(asset['symbol']) + '</b>',
                              '', '<b>🌐 Network:</b> ' + e(network_name(asset)),
                              '<b>📋 Receiving wallet:</b>\n<code>' + e(asset['wallet']) + '</code>'])
                if expired:
                    lines.append('\nIf you already paid within the quote window, submit that TXID. Do not pay this expired quote.')
                else:
                    lines.extend(['', '<b>⚠️ Copy the exact amount above. Do not round it.</b>',
                                  'The receiving wallet must get that exact amount. Pay network fees separately.',
                                  'Use only <b>' + e(asset['symbol']) + '</b> on <b>' + e(network_name(asset)) + '</b>.',
                                  '', '<b>1️⃣ Copy amount and wallet</b>\nUse the buttons below.',
                                  '<b>2️⃣ Send once</b>\nCheck the coin, network and full amount before sending.',
                                  '<b>3️⃣ Submit the TXID</b>\nTap “I\'ve paid — enter TXID” after sending.'])
            lines.extend(['', '<b>⏰ Quote expires:</b> ' + e(expiry),
                          '<b>🔗 Confirmations required:</b> ' + e(asset.get('confirmations', 1))])
        elif order['status'] in ('paid', 'provisioning'):
            lines.append('\n<b>✅ Payment confirmed.</b>\nPreparing your account. Do not pay again.')
        elif order['status'] == 'review':
            lines.append('\n<b>🛟 Manual review needed.</b>\nDo not pay again. Contact support with the order ID below.')
        if plan.get('usd_price') and not checking and order['status']=='pending':
            lines.extend(['', '<b>ℹ️ Price reference only — NOT the amount to send</b>',
                          '$' + e(plan['usd_price']) + ' USD (from £' + e(plan['gbp_price']) + ').',
                          'Use the full crypto amount shown above, not this rounded USD value.'])
            if demo:
                lines.append('Exchange rates are simulated, not live prices.')
        if order.get('message'):
            lines.extend(['', '<b>📍 Update:</b> ' + e(order['message'])])
        lines.extend(['', '<b>🧾 Order ID:</b> <code>' + e(order['id']) + '</code>',
                      '<b>Status:</b> ' + e(order['status'].upper())])
        if order['status']=='pending' and not checking:
            lines.append('\nAlready sent a different amount? <b>Do not send more.</b> Contact support with your order ID and TXID.')
        return '\n'.join(lines)

    def show_order(self, uid, order):
        # Invoices and logins are kept as their own messages, never edited away by later navigation.
        self.bot.send(uid, self.order_text(order), self.order_keyboard(order),
                      parse_mode='HTML' if order['status'] != 'fulfilled' else None, keep=True)
        self.store.metadata('tg_notice:' + order['id'], order['status'] + ':' + order.get('message', ''))

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
            elif len(parts) == 4 and parts[1] == 'quote':
                self.clear_session(uid)
                result = self.service.create_order(parts[2], parts[3], owner_telegram_id=uid,
                                                   request_key='tg_quote:' + digest(f'{uid}:{callback_id}'))
                self.show_order(uid, result['order'])
            elif len(parts) == 3 and parts[1] in ('status', 'tx', 'demo'):
                order = self.service.telegram_order(uid, parts[2])
                if parts[1] == 'tx' and order['status'] == 'pending':
                    self.store.metadata(self.bot.support.session_key(uid), '0')
                    prompt = self.bot.send(uid, '<b>🔗 ENTER TRANSACTION ID</b>\n\nOrder: <code>' + escape(order['id']) +
                                           '</code>\n\nPaste <b>only the transaction hash / TXID</b>, not a link.'
                                           '\nWe verify the payment on the blockchain. <b>Do not send another payment.</b>'
                                           '\n\nSend /cancel to stop TXID entry.',
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
