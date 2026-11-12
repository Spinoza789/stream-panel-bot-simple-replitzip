"""Telegram side of support tickets: the Contact support screen, opening and replying, and the owner's reply-to-answer flow."""
import re
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from .service import CheckoutError
from .store import digest
from .tickets import TOPICS, ICONS, STATUS_LABEL, ID_PATTERN


def when(value):
    return datetime.fromtimestamp(int(value), ZoneInfo('Europe/London')).strftime('%d %b %H:%M')


def button(text, action): return {'text': text, 'callback_data': 'tk:' + action}


class TicketBot:
    def __init__(self, bot):
        self.bot = bot; self.store = bot.store; self.service = bot.service
        self.tickets = getattr(bot.service, 'tickets', None)
        if self.tickets is None:  # lightweight test doubles build the service piecemeal
            from .tickets import Tickets
            self.tickets = Tickets(bot.service); bot.service.tickets = self.tickets
        self.tickets.telegram = self

    @property
    def admin(self): return self.service.config.get('support_admin_id')

    def state_key(self, uid): return 'tk_state:' + digest(uid)
    def state(self, uid, value=None, clear=False):
        if clear: self.store.metadata(self.state_key(uid), ''); return None
        if value is not None: self.store.metadata(self.state_key(uid), self.store.seal(value)); return value
        raw = self.store.metadata(self.state_key(uid))
        return self.store.unseal(raw) if raw else None

    def send(self, uid, text, rows, keep=False):
        self.bot.send(uid, text, {'inline_keyboard': rows}, parse_mode='HTML', keep=keep)

    def direct(self):
        return 'Direct contact: @' + self.service.config['support_username']

    # ---------- screens ----------
    def menu(self, uid):
        if uid == self.admin:
            counts = self.tickets.admin_counts()
            self.bot.send(uid, 'You are the support administrator. Open tickets: %d · answered: %d.\nReply to a ticket notification to answer it, or use Tickets in the admin dashboard.' % (counts['open'], counts['answered']),
                          {'inline_keyboard': [[{'text': '⬅️ Main menu', 'callback_data': 'menu'}]]}); return
        if not self.tickets.ready:
            self.bot.send(uid, 'Support tickets are not available right now. ' + self.direct(), {'inline_keyboard': [[{'text': '⬅️ Main menu', 'callback_data': 'menu'}]]}); return
        items = self.tickets.list(uid)
        text = ('<b>💬 SUPPORT</b>\n\nOpen a ticket and we will answer you here in Telegram. '
                'Resellers can also see and answer their tickets in the web panel.')
        rows = [[button('🆕 Open a new ticket', 'new')]]
        if items:
            text += '\n\n<b>Your tickets</b>'
            for t in items[:5]:
                icon = {'open': '🟡', 'answered': '🟢', 'closed': '⚪️'}[t['status']]
                text += '\n' + icon + ' ' + t['id'] + ' · ' + escape(t['topic_label']) + ' · ' + t['status_label']
                rows.append([button(icon + ' ' + t['id'] + ' · ' + ICONS.get(t['topic'], '') + ' ' + t['topic_label'], 'view:' + t['id'])])
        text += '\n\n' + escape(self.direct())
        rows.append([{'text': '⬅️ Main menu', 'callback_data': 'menu'}])
        self.send(uid, text, rows)

    def topics(self, uid):
        rows = [[button(ICONS[key] + ' ' + label, 'topic:' + key)] for key, label in TOPICS.items()] + [[button('⬅️ Back', 'menu')]]
        self.send(uid, '<b>🆕 NEW TICKET</b>\n\nWhat is it about?', rows)

    def view(self, uid, tid):
        ticket, messages = self.tickets.get(uid, tid)
        icon = {'open': '🟡', 'answered': '🟢', 'closed': '⚪️'}[ticket['status']]
        text = '<b>🎫 Ticket ' + ticket['id'] + '</b>\n' + ICONS.get(ticket['topic'], '') + ' ' + escape(ticket['topic_label']) + ' · ' + icon + ' ' + ticket['status_label'] + '\nOpened ' + when(ticket['created_at'])
        shown = messages[-6:]
        if len(messages) > len(shown): text += '\n\n… %d earlier message%s' % (len(messages) - len(shown), '' if len(messages) - len(shown) == 1 else 's')
        for m in shown:
            who = '👤 You' if m['sender'] == 'customer' else '🛟 Support'
            body = m['body'] if len(m['body']) <= 700 else m['body'][:700] + '…'
            text += '\n\n<b>' + who + '</b> · ' + when(m['created_at']) + '\n' + escape(body)
        rows = []
        if ticket['status'] == 'closed': rows.append([button('🔄 Reopen with a reply', 'reply:' + tid)])
        else: rows.append([button('✍️ Reply', 'reply:' + tid), button('✅ Close ticket', 'close:' + tid)])
        rows.append([button('⬅️ Support', 'menu')])
        self.send(uid, text, rows)

    def prompt(self, uid, state):
        self.bot.checkout.clear_session(uid); self.bot.reseller.state(uid, clear=True)  # free text now belongs to the ticket
        self.state(uid, state)
        if state.get('ticket') == 'new':
            text = ('<b>' + ICONS[state['topic']] + ' ' + escape(TOPICS[state['topic']]) + '</b>\n\nDescribe the problem in one message. Include the account username and what you see on screen if you can.'
                    '\n\nSend it as text. Up to 2000 characters.')
        else:
            text = '<b>Reply on ticket ' + state['ticket'] + '</b>\n\nType your reply as one message.'
        self.send(uid, text, [[button('Cancel', 'cancel')]], keep=True)

    # ---------- callbacks and messages ----------
    def callback(self, uid, action):
        if not action.startswith('tk:'): return False
        parts = action.split(':'); name = parts[1]
        try:
            if name == 'menu': self.state(uid, clear=True); self.menu(uid)
            elif name == 'new': self.tickets.require_ready(); self.topics(uid)
            elif name == 'topic': self.prompt(uid, {'ticket': 'new', 'topic': self.tickets.topic(parts[2])})
            elif name == 'cancel': self.state(uid, clear=True); self.bot.send(uid, 'Cancelled. Nothing was sent.', {'inline_keyboard': [[button('⬅️ Support', 'menu')], [{'text': '⬅️ Main menu', 'callback_data': 'menu'}]]})
            elif name == 'view': self.view(uid, self.tickets.ticket_id(parts[2]))
            elif name == 'reply':
                self.tickets.get(uid, self.tickets.ticket_id(parts[2]))  # ownership check before prompting
                self.prompt(uid, {'ticket': parts[2]})
            elif name == 'close':
                self.tickets.close(uid, self.tickets.ticket_id(parts[2])); self.view(uid, parts[2])
            else: raise CheckoutError('This option is unavailable.')
        except CheckoutError as exc:
            self.bot.send(uid, str(exc), {'inline_keyboard': [[button('⬅️ Support', 'menu')]]})
        return True

    def message(self, message, command, argument=''):
        """Returns True when the message belonged to the ticket flow."""
        uid = message['from']['id']
        if command in ('/contact', '/support', '/paysupport', '/ticket', '/tickets'):
            self.state(uid, clear=True); self.menu(uid); return True
        if uid == self.admin:
            if command == '/close' and argument: return self.admin_close(argument.strip())
            if message.get('reply_to_message'): return self.admin_reply(message)
            if not command.startswith('/'):
                self.bot.send(uid, 'Reply to a ticket notification to answer it, or use Tickets in the admin dashboard. /close TICKET closes one.'); return True
            return False
        state = self.state(uid)
        if command == '/cancel':
            if state: self.state(uid, clear=True); self.bot.send(uid, 'Cancelled. Nothing was sent.', self.bot.menu_keyboard(uid)); return True
            return False
        if not state or command.startswith('/'): return False
        text = message.get('text')
        if not isinstance(text, str) or not text.strip():
            self.bot.send(uid, 'Please send your message as text. To share a screenshot, send it to @' + self.service.config['support_username'] + ' and mention your ticket number.',
                          {'inline_keyboard': [[button('Cancel', 'cancel')]]}, keep=True); return True
        try:
            if state.get('ticket') == 'new':
                ticket = self.tickets.open(uid, state['topic'], text, 'bot', message['from'].get('username', ''))
                self.state(uid, clear=True)
                extra = '\nYou can also follow it under Support in your reseller web panel.' if ticket['reseller'] else ''
                self.bot.send(uid, '🎫 Ticket ' + ticket['id'] + ' opened. We will reply here in Telegram.' + extra,
                              {'inline_keyboard': [[button('📄 View ticket', 'view:' + ticket['id'])], [{'text': '⬅️ Main menu', 'callback_data': 'menu'}]]}, keep=True)
            else:
                ticket = self.tickets.reply(uid, state['ticket'], text, 'bot')
                self.state(uid, clear=True)
                self.bot.send(uid, '✅ Added to ticket ' + ticket['id'] + '. Support will reply here.',
                              {'inline_keyboard': [[button('📄 View ticket', 'view:' + ticket['id'])], [{'text': '⬅️ Main menu', 'callback_data': 'menu'}]]}, keep=True)
        except CheckoutError as exc:
            self.bot.send(uid, str(exc), {'inline_keyboard': [[button('Try again', 'menu')]]}, keep=True)
        return True

    # ---------- owner side in Telegram ----------
    def route_key(self, message_id): return 'tk_route:%s:%s' % (self.admin, message_id)

    def ticket_to_admin(self, ticket, body, first):
        who = ('@' + ticket['username']) if ticket['username'] else 'Customer'
        head = ('🎫 New ticket ' if first else '💬 Reply on ticket ') + ticket['id'] + ' · ' + ICONS.get(ticket['topic'], '') + ' ' + ticket['topic_label']
        text = (head + '\nFrom: ' + who + ' (ID ' + str(ticket['telegram_id']) + ')' + (' · reseller' if ticket['reseller'] else '') + ' · via ' + ('web panel' if ticket['channel'] == 'web' else 'bot') +
                '\n\n' + body + '\n\n↩️ Reply to this message to answer. /close ' + ticket['id'] + ' closes it.')
        result = self.bot.send(self.admin, text, keep=True)
        mid = result.get('message_id') if isinstance(result, dict) else None
        if type(mid) is int and mid > 0: self.store.metadata(self.route_key(mid), ticket['id'])

    def ticket_to_customer(self, ticket, body, first=False):
        from .bot import TelegramError
        if body is None:
            text = '⚪️ Ticket ' + ticket['id'] + ' was closed by support. Reply on it any time to reopen it.'
            rows = [[button('📄 View ticket', 'view:' + ticket['id'])]]
        else:
            text = ('🛟 <b>Message from support · ticket ' + ticket['id'] + '</b>\n\n' if first else '🛟 <b>Support replied on ticket ' + ticket['id'] + '</b>\n\n') + escape(body)
            rows = [[button('✍️ Reply', 'reply:' + ticket['id']), button('✅ Close ticket', 'close:' + ticket['id'])], [button('📄 View ticket', 'view:' + ticket['id'])]]
        try:
            self.bot.send(ticket['telegram_id'], text, {'inline_keyboard': rows}, parse_mode='HTML', keep=True); return True
        except TelegramError as exc:
            if exc.code in (400, 403): return False
            raise

    def admin_reply(self, message):
        reply = (message.get('reply_to_message') or {}).get('message_id')
        tid = self.store.metadata(self.route_key(reply)) if type(reply) is int else None
        if not tid:
            self.bot.send(self.admin, 'Reply to a ticket notification from this bot to answer its customer, or use the admin dashboard.'); return True
        text = message.get('text')
        if not isinstance(text, str) or not text.strip():
            self.bot.send(self.admin, 'Ticket answers must be text. Send a text reply to this notification.'); return True
        mid = message.get('message_id')
        once = 'tk_sent:' + digest('%s:%s' % (self.admin, mid)) if type(mid) is int else None
        if once and self.store.metadata(once): return True
        try:
            ticket, delivered = self.tickets.admin_reply(self.admin, tid, text)
            if once: self.store.metadata(once, '1')
            self.bot.send(self.admin, ('✅ Reply saved on ' + tid + ' and sent to the customer.') if delivered else ('⚠️ Reply saved on ' + tid + ' but Telegram could not deliver it (the customer may have blocked the bot). They can still read it in the web panel.'))
        except CheckoutError as exc: self.bot.send(self.admin, str(exc))
        return True

    def admin_close(self, tid):
        tid = tid.upper()
        if not re.fullmatch(ID_PATTERN, tid): self.bot.send(self.admin, 'Use /close TICKET, for example /close TABC234.'); return True
        try: self.tickets.admin_status(self.admin, tid, 'closed'); self.bot.send(self.admin, '⚪️ Ticket ' + tid + ' closed.')
        except CheckoutError as exc: self.bot.send(self.admin, str(exc))
        return True
