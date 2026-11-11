"""Support tickets.

Customers and resellers open tickets from the Telegram bot or the reseller web panel.
The owner answers by replying to the Telegram notification or from the admin
dashboard; every answer is stored on the ticket and pushed to the customer in Telegram.
Message bodies are sealed at rest because people paste logins into them.
"""
import logging
import re
import secrets
import time

from .reseller_ledger import WEB_ACTOR
from .service import CheckoutError

TOPICS = {'payment': 'Payment', 'login': 'Login or app', 'playback': 'Playback',
          'reseller': 'Reseller account', 'other': 'Something else'}
ICONS = {'payment': '💳', 'login': '🔑', 'playback': '📺', 'reseller': '🏪', 'other': '❓'}
STATUS_LABEL = {'open': 'Open', 'answered': 'Answered', 'closed': 'Closed'}
ID_PATTERN = r'T[A-HJ-NP-Z2-9]{6}'
ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
MAX_BODY = 2000
MAX_OPEN = 5
log = logging.getLogger(__name__)


def now(): return int(time.time())


class Tickets:
    def __init__(self, service):
        self.service = service; self.store = service.store; self.config = service.config
        self.telegram = None  # set by TelegramBot so answers reach the customer in chat
        try:
            with self.store.connection() as db: db.execute('SELECT id FROM tk_tickets WHERE 1=0')
            self.ready = True
        except Exception as exc:
            self.ready = False
            log.warning('Ticket tables unavailable (%s); support tickets are disabled until the schema is published.', type(exc).__name__)

    # ---------- validation ----------
    def require_ready(self):
        if not self.ready: raise CheckoutError('Support tickets are not set up yet. Contact us directly: ' + self.config['support_url'])

    @staticmethod
    def clean(body):
        if not isinstance(body, str): raise CheckoutError('Write a message first.')
        body = body.strip()
        if not body: raise CheckoutError('Write a message first.')
        if len(body) > MAX_BODY: raise CheckoutError('Keep each message under %d characters.' % MAX_BODY)
        return body

    @staticmethod
    def topic(value):
        if value not in TOPICS: raise CheckoutError('Choose a topic.')
        return value

    @staticmethod
    def ticket_id(value):
        if not isinstance(value, str) or not re.fullmatch(ID_PATTERN, value): raise CheckoutError('Ticket not found.')
        return value

    def admin(self, actor):
        if isinstance(actor, str) and re.fullmatch(WEB_ACTOR, actor): return
        expected = self.config.get('support_admin_id')
        if type(actor) is not int or not expected or actor != expected: raise CheckoutError('Administrator access required.')

    # ---------- shaping ----------
    def _ticket(self, row):
        t = dict(row); t['topic_label'] = TOPICS.get(t['topic'], t['topic']); t['status_label'] = STATUS_LABEL[t['status']]
        return t

    def _message(self, row):
        m = dict(row)
        try: m['body'] = self.store.unseal(m['body'])
        except Exception: m['body'] = '[unreadable]'
        return m

    def _messages(self, db, tid):
        return [self._message(r) for r in db.execute('SELECT id,sender,body,actor,created_at FROM tk_messages WHERE ticket_id=? ORDER BY created_at,id', (tid,)).fetchall()]

    def _with_preview(self, db, rows):
        items = []
        for row in rows:
            t = self._ticket(row)
            last = db.execute('SELECT sender,body,created_at FROM tk_messages WHERE ticket_id=? ORDER BY created_at DESC,id DESC LIMIT 1', (t['id'],)).fetchone()
            count = db.execute('SELECT COUNT(*) FROM tk_messages WHERE ticket_id=?', (t['id'],)).fetchone()[0]
            if last:
                m = self._message(last); t['last_sender'] = m['sender']; t['preview'] = m['body'][:120]
            else: t['last_sender'] = ''; t['preview'] = ''
            t['messages'] = int(count); items.append(t)
        return items

    def _new_id(self, db):
        for _ in range(20):
            tid = 'T' + ''.join(secrets.choice(ALPHABET) for _ in range(6))
            if not db.execute('SELECT 1 FROM tk_tickets WHERE id=?', (tid,)).fetchone(): return tid
        raise CheckoutError('Could not allocate a ticket number. Try again.')

    def _add(self, db, tid, sender, body, actor=''):
        db.execute('INSERT INTO tk_messages(id,ticket_id,sender,body,actor,created_at) VALUES(?,?,?,?,?,?)',
                   ('%020d%s' % (time.time_ns(), secrets.token_hex(4)), tid, sender, self.store.seal(body), str(actor or ''), now()))  # id sorts in creation order

    def owned(self, uid, tid, db):
        row = db.execute('SELECT * FROM tk_tickets WHERE id=? AND telegram_id=?', (self.ticket_id(tid), uid)).fetchone()
        if not row: raise CheckoutError('Ticket not found.')
        return self._ticket(row)

    # ---------- customer side ----------
    def open(self, uid, topic, body, channel='bot', username=''):
        self.require_ready(); topic = self.topic(topic); body = self.clean(body)
        if type(uid) is not int or uid <= 0: raise CheckoutError('Sign in first.')
        if not self.store.limit('ticket_open:' + str(uid), 5, 3600): raise CheckoutError('You have opened several tickets recently. Please wait a while, or reply on an existing ticket.')
        username = username if isinstance(username, str) and re.fullmatch(r'[A-Za-z0-9_]{1,64}', username) else ''
        member = self.service.resellers.member(uid)
        with self.store.connection() as db:
            open_count = db.execute("SELECT COUNT(*) FROM tk_tickets WHERE telegram_id=? AND status!='closed'", (uid,)).fetchone()[0]
            if open_count >= MAX_OPEN: raise CheckoutError('You already have %d open tickets. Reply on one of them instead.' % open_count)
            tid = self._new_id(db)
            db.execute('INSERT INTO tk_tickets(id,telegram_id,username,topic,status,channel,reseller,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                       (tid, uid, username, topic, 'open', channel if channel in ('bot', 'web') else 'bot', 1 if member else 0, now(), now()))
            self._add(db, tid, 'customer', body)
            ticket = self.owned(uid, tid, db)
        self._notify_admin(ticket, body, first=True)
        return ticket

    def reply(self, uid, tid, body, channel='bot'):
        self.require_ready(); body = self.clean(body)
        if not self.store.limit('ticket_reply:' + str(uid), 30, 3600): raise CheckoutError('Too many messages in a short time. Please wait a few minutes.')
        with self.store.connection() as db:
            ticket = self.owned(uid, tid, db)
            self._add(db, tid, 'customer', body)
            db.execute("UPDATE tk_tickets SET status='open',updated_at=?,closed_at=NULL WHERE id=?", (now(), tid))
            ticket = self.owned(uid, tid, db)
        self._notify_admin(ticket, body, first=False)
        return ticket

    def close(self, uid, tid):
        self.require_ready()
        with self.store.connection() as db:
            self.owned(uid, tid, db)
            db.execute("UPDATE tk_tickets SET status='closed',closed_at=?,updated_at=? WHERE id=?", (now(), now(), tid))
            return self.owned(uid, tid, db)

    def list(self, uid, page=0):
        self.require_ready()
        if type(page) is not int or not 0 <= page <= 10000: raise CheckoutError('Invalid page.')
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM tk_tickets WHERE telegram_id=? ORDER BY CASE status WHEN 'closed' THEN 1 ELSE 0 END,updated_at DESC,id DESC LIMIT 11 OFFSET ?", (uid, page * 10)).fetchall()
            return self._with_preview(db, rows)

    def get(self, uid, tid):
        self.require_ready()
        with self.store.connection() as db:
            ticket = self.owned(uid, tid, db)
            return ticket, self._messages(db, tid)

    def counts(self, uid):
        if not self.ready: return {'open': 0, 'answered': 0}
        with self.store.connection() as db:
            row = db.execute("SELECT SUM(CASE WHEN status='open' THEN 1 ELSE 0 END),SUM(CASE WHEN status='answered' THEN 1 ELSE 0 END) FROM tk_tickets WHERE telegram_id=?", (uid,)).fetchone()
        return {'open': int(row[0] or 0), 'answered': int(row[1] or 0)}

    # ---------- support side ----------
    def admin_list(self, actor, status='open', q='', page=0):
        self.admin(actor); self.require_ready()
        if status not in ('open', 'answered', 'closed', 'all'): raise CheckoutError('Invalid status filter.')
        if type(page) is not int or not 0 <= page <= 10000: raise CheckoutError('Invalid page.')
        q = (q or '')[:80].strip()
        clauses, params = [], []
        if status != 'all': clauses.append('status=?'); params.append(status)
        if q:
            clauses.append('(id LIKE ? OR username LIKE ? OR CAST(telegram_id AS TEXT) LIKE ?)')
            like = '%' + q.upper() + '%' if re.fullmatch(r'[A-Za-z0-9]+', q) and q.upper().startswith('T') else '%' + q + '%'
            params.extend([like, '%' + q + '%', '%' + q + '%'])
        where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
        with self.store.connection() as db:
            rows = db.execute('SELECT * FROM tk_tickets' + where + ' ORDER BY updated_at DESC,id DESC LIMIT 26 OFFSET ?', (*params, page * 25)).fetchall()
            return self._with_preview(db, rows)

    def admin_get(self, actor, tid):
        self.admin(actor); self.require_ready()
        with self.store.connection() as db:
            row = db.execute('SELECT * FROM tk_tickets WHERE id=?', (self.ticket_id(tid),)).fetchone()
            if not row: raise CheckoutError('Ticket not found.')
            return self._ticket(row), self._messages(db, tid)

    def admin_reply(self, actor, tid, body):
        self.admin(actor); self.require_ready(); body = self.clean(body)
        with self.store.connection() as db:
            row = db.execute('SELECT * FROM tk_tickets WHERE id=?', (self.ticket_id(tid),)).fetchone()
            if not row: raise CheckoutError('Ticket not found.')
            self._add(db, tid, 'support', body, actor)
            db.execute("UPDATE tk_tickets SET status='answered',updated_at=?,closed_at=NULL WHERE id=?", (now(), tid))
            ticket = self._ticket(db.execute('SELECT * FROM tk_tickets WHERE id=?', (tid,)).fetchone())
        delivered = self._notify_customer(ticket, body)
        return ticket, delivered

    def admin_status(self, actor, tid, status):
        self.admin(actor); self.require_ready()
        if status not in ('open', 'closed'): raise CheckoutError('Status must be open or closed.')
        with self.store.connection() as db:
            if not db.execute('SELECT 1 FROM tk_tickets WHERE id=?', (self.ticket_id(tid),)).fetchone(): raise CheckoutError('Ticket not found.')
            db.execute('UPDATE tk_tickets SET status=?,closed_at=?,updated_at=? WHERE id=?', (status, now() if status == 'closed' else None, now(), tid))
            ticket = self._ticket(db.execute('SELECT * FROM tk_tickets WHERE id=?', (tid,)).fetchone())
        if status == 'closed': self._notify_customer(ticket, None)
        return ticket

    def admin_counts(self):
        if not self.ready: return {'open': 0, 'answered': 0, 'closed': 0}
        with self.store.connection() as db:
            rows = db.execute('SELECT status,COUNT(*) FROM tk_tickets GROUP BY status').fetchall()
        counts = {'open': 0, 'answered': 0, 'closed': 0}
        for row in rows: counts[row[0]] = int(row[1])  # positional: PostgreSQL rows are dicts, not tuples
        return counts

    # ---------- Telegram delivery (best effort; the ticket is the record) ----------
    def _notify_admin(self, ticket, body, first):
        bot = self.telegram; admin = self.config.get('support_admin_id')
        if not bot or not admin: return
        try: bot.ticket_to_admin(ticket, body, first)
        except Exception as exc: log.warning('Ticket %s: admin notification failed (%s)', ticket['id'], type(exc).__name__)

    def _notify_customer(self, ticket, body):
        bot = self.telegram
        if not bot: return False
        try: return bool(bot.ticket_to_customer(ticket, body))
        except Exception as exc:
            log.warning('Ticket %s: customer notification failed (%s)', ticket['id'], type(exc).__name__); return False
