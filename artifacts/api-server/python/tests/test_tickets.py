"""Support tickets: bot flow, owner replies from Telegram and the bridge, reseller panel routes."""
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

from streambot.bot import TelegramBot, TelegramError
from streambot.config import load_config
from streambot.service import CheckoutService, CheckoutError
from streambot.store import Store
from streambot.web import create_app

ORIGIN = 'http://localhost:8090'
ADMIN = 9001


class TicketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'db.sqlite3', Fernet.generate_key())
        self.config = load_config(env={'APP_MODE': 'demo', 'SUPPORT_ADMIN_ID': str(ADMIN)})
        self.service = CheckoutService(self.config, self.store, Mock(), Mock())
        self.calls = []; self.mid = 100; self.blocked = set(); self.n = 0
        def api(method, payload):
            if payload.get('chat_id') in self.blocked: raise TelegramError(403, method)
            self.mid += 1; self.calls.append((method, payload, self.mid)); return {'message_id': self.mid}
        self.bot = TelegramBot(self.service, api=api)
        self.t = self.service.tickets

    def message(self, uid, text, reply_to=None, username='cust', extra=None):
        self.n += 1
        m = {'message_id': self.n, 'from': {'id': uid, 'username': username}, 'chat': {'id': uid, 'type': 'private'}, 'text': text}
        if reply_to: m['reply_to_message'] = {'message_id': reply_to}
        if extra: m.update(extra)
        self.bot.handle({'message': m})

    def click(self, uid, data):
        self.n += 1
        self.bot.handle({'callback_query': {'id': 'c%d' % self.n, 'from': {'id': uid}, 'data': data, 'message': {'chat': {'id': uid, 'type': 'private'}, 'message_id': 1}}})

    def last(self, uid):
        for method, payload, mid in reversed(self.calls):
            if method in ('sendMessage', 'editMessageText') and payload.get('chat_id') == uid: return payload, mid
        return None, None

    def buttons(self, payload):
        return [b['callback_data'] for row in payload['reply_markup']['inline_keyboard'] for b in row]

    def open_from_bot(self, uid=42, text='I paid but nothing arrived'):
        self.click(uid, 'menu:contact'); self.click(uid, 'tk:new'); self.click(uid, 'tk:topic:payment')
        self.message(uid, text)
        return self.last(uid)[0]['text'].split()[2]

    def test_contact_opens_ticket_menu_and_creates_a_ticket(self):
        self.click(42, 'menu:contact')
        menu, _ = self.last(42)
        self.assertIn('SUPPORT', menu['text']); self.assertIn('tk:new', self.buttons(menu))
        self.click(42, 'tk:new'); self.assertIn('tk:topic:payment', self.buttons(self.last(42)[0]))
        self.click(42, 'tk:topic:payment'); self.assertIn('Describe the problem', self.last(42)[0]['text'])
        self.message(42, 'I paid 0.002 BTC but nothing arrived')
        done, _ = self.last(42)
        self.assertRegex(done['text'], r'Ticket T[A-HJ-NP-Z2-9]{6} opened')
        tid = done['text'].split()[2]
        admin, admin_mid = self.last(ADMIN)
        self.assertIn('New ticket ' + tid, admin['text']); self.assertIn('@cust (ID 42)', admin['text']); self.assertIn('I paid 0.002 BTC', admin['text'])
        tickets = self.t.list(42)
        self.assertEqual((tickets[0]['id'], tickets[0]['status'], tickets[0]['topic'], tickets[0]['messages']), (tid, 'open', 'payment', 1))
        # plain text afterwards is not captured
        self.message(42, 'just chatting'); self.assertIn('Free for 24 hours', self.last(42)[0]['text'])
        self.assertEqual(self.t.list(42)[0]['messages'], 1)

    def test_owner_replies_by_telegram_reply_and_customer_is_notified(self):
        tid = self.open_from_bot()
        _, admin_mid = self.last(ADMIN)
        self.message(ADMIN, 'Which wallet did you send from?', reply_to=admin_mid)
        self.assertIn('Reply saved on ' + tid, self.last(ADMIN)[0]['text'])
        customer, _ = self.last(42)
        self.assertIn('Support replied on ticket ' + tid, customer['text']); self.assertIn('Which wallet', customer['text'])
        self.assertIn('tk:reply:' + tid, self.buttons(customer))
        ticket, messages = self.t.get(42, tid)
        self.assertEqual(ticket['status'], 'answered'); self.assertEqual([m['sender'] for m in messages], ['customer', 'support'])
        # redelivered update is not stored twice
        payload = {'message_id': self.n, 'from': {'id': ADMIN}, 'chat': {'id': ADMIN, 'type': 'private'}, 'text': 'Which wallet did you send from?', 'reply_to_message': {'message_id': admin_mid}}
        self.bot.handle({'message': payload})
        self.assertEqual(len(self.t.get(42, tid)[1]), 2)
        # customer replies from the notification button, ticket reopens
        self.click(42, 'tk:reply:' + tid); self.message(42, 'Coinbase')
        self.assertEqual(self.t.get(42, tid)[0]['status'], 'open'); self.assertIn('Reply on ticket ' + tid, self.last(ADMIN)[0]['text'])
        # thread view lists messages in order and offers close
        self.click(42, 'tk:view:' + tid)
        view, _ = self.last(42)
        self.assertLess(view['text'].index('I paid but nothing arrived'), view['text'].index('Which wallet'))
        self.assertIn('tk:close:' + tid, self.buttons(view))
        self.message(ADMIN, '/close ' + tid)
        self.assertEqual(self.t.get(42, tid)[0]['status'], 'closed'); self.assertIn('was closed by support', self.last(42)[0]['text'])
        self.message(ADMIN, 'no reply context'); self.assertIn('Reply to a ticket notification', self.last(ADMIN)[0]['text'])
        self.message(ADMIN, 'stale', reply_to=5); self.assertIn('Reply to a ticket notification', self.last(ADMIN)[0]['text'])

    def test_limits_ownership_and_non_text(self):
        tid = self.open_from_bot()
        with self.assertRaises(CheckoutError): self.t.get(43, tid)
        with self.assertRaises(CheckoutError): self.t.reply(43, tid, 'hi')
        with self.assertRaises(CheckoutError): self.t.open(42, 'nope', 'x')
        with self.assertRaises(CheckoutError): self.t.open(42, 'other', 'x' * 2001)
        with self.assertRaises(CheckoutError): self.t.admin_reply(43, tid, 'not admin')
        for i in range(4): self.t.open(42, 'other', 'issue %d' % i)
        with self.assertRaises(CheckoutError): self.t.open(42, 'other', 'one too many')  # five open already
        self.click(42, 'tk:reply:' + tid); self.message(42, '', extra={'sticker': {'file_id': 'x'}})
        self.assertIn('as text', self.last(42)[0]['text'])
        self.message(42, '/cancel'); self.assertIn('Cancelled', self.last(42)[0]['text'])
        self.assertEqual(len(self.t.get(42, tid)[1]), 1)
        # blocked customer: answer is still stored, owner is told
        self.blocked.add(42)
        self.message(ADMIN, 'answer', reply_to=self.last(ADMIN)[1])
        self.assertIn('could not deliver', self.last(ADMIN)[0]['text'])

    def test_reseller_panel_routes(self):
        finance = self.service.resellers.finance
        finance.register(42, 'shop'); finance.account_status(ADMIN, 42, 'active', 'test')
        app = create_app(self.service); client = app.test_client()
        code = self.service.resellers.web.issue_code(42)
        self.assertEqual(client.post('/api/reseller/session/code', json={'code': code}, headers={'Origin': ORIGIN}).status_code, 200)
        post = lambda path, data: client.post(path, json=data, headers={'Origin': ORIGIN})
        empty = client.get('/api/reseller/tickets').get_json()
        self.assertEqual(empty['items'], []); self.assertIn('payment', empty['topics'])
        self.assertEqual(post('/api/reseller/tickets', {'topic': 'login', 'body': ''}).status_code, 400)
        opened = post('/api/reseller/tickets', {'topic': 'login', 'body': 'Customer demo_1 cannot log in'})
        self.assertEqual(opened.status_code, 200, opened.get_json())
        tid = opened.get_json()['ticket']['id']
        self.assertIn('via web panel', self.last(ADMIN)[0]['text'])
        detail = client.get('/api/reseller/tickets/' + tid).get_json()
        self.assertEqual(detail['messages'][0]['body'], 'Customer demo_1 cannot log in')
        self.assertNotIn('telegram_id', detail['ticket'])
        self.t.admin_reply('replit:owner:' + 'a' * 64, tid, 'Ask them to reinstall')
        replied = post('/api/reseller/tickets/' + tid + '/reply', {'body': 'Done, still failing'}).get_json()
        self.assertEqual([m['sender'] for m in replied['messages']], ['customer', 'support', 'customer']); self.assertEqual(replied['ticket']['status'], 'open')
        closed = post('/api/reseller/tickets/' + tid + '/close', {}).get_json()
        self.assertEqual(closed['ticket']['status'], 'closed')
        listing = client.get('/api/reseller/tickets').get_json()
        self.assertEqual((listing['items'][0]['id'], listing['items'][0]['messages'], listing['items'][0]['last_sender']), (tid, 3, 'customer'))
        other = app.test_client()
        finance.register(43, 'other'); finance.account_status(ADMIN, 43, 'active', 'test')
        other.post('/api/reseller/session/code', json={'code': self.service.resellers.web.issue_code(43)}, headers={'Origin': ORIGIN})
        self.assertIn(other.get('/api/reseller/tickets/' + tid).status_code, (400, 404))

    def test_admin_bridge_routes(self):
        tid = self.open_from_bot()
        key = 'a' * 64; actor = 'replit:test_owner:' + '1' * 64
        with patch.dict(os.environ, STREAMBOT_ADMIN_BRIDGE_KEY=key):
            app = create_app(self.service); client = app.test_client()
            def call(path, data=None):
                method = 'GET' if data is None else 'POST'; target = '/api/_admin' + path; raw = '' if data is None else json.dumps(data)
                ts = str(int(time.time())); nonce = secrets.token_hex(16)
                sig = hmac.new(key.encode(), '\n'.join([method, target, actor, ts, nonce, hashlib.sha256(raw.encode()).hexdigest()]).encode(), hashlib.sha256).hexdigest()
                return client.open(target, method=method, data=raw, headers={'Content-Type': 'application/json', 'X-Streamline-Actor': actor, 'X-Streamline-Time': ts, 'X-Streamline-Nonce': nonce, 'X-Streamline-Signature': sig})
            page = call('/tickets?status=open').json
            self.assertEqual((page['items'][0]['id'], page['items'][0]['telegramId'], page['counts']['open']), (tid, 42, 1))
            self.assertEqual(call('/overview').json['openTickets'], 1)
            detail = call('/tickets/' + tid).json
            self.assertEqual(detail['messages'][0]['body'], 'I paid but nothing arrived')
            replied = call('/tickets/' + tid + '/reply', {'body': 'Checking the chain now'}).json
            self.assertEqual((replied['ticket']['status'], replied['delivered'], replied['messages'][-1]['actor']), ('answered', True, actor))
            self.assertIn('Checking the chain now', self.last(42)[0]['text'])
            closed = call('/tickets/' + tid + '/status', {'status': 'closed'}).json
            self.assertEqual(closed['ticket']['status'], 'closed')
            self.assertEqual(call('/tickets?status=open').json['items'], [])
            self.assertEqual(call('/tickets?q=' + tid[1:4] + '&status=all').json['items'][0]['id'], tid)
            self.assertIn(call('/tickets/TZZZZZZ').status_code, (400, 404))
            self.assertEqual(call('/tickets/' + tid + '/reply', {'body': ''}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
