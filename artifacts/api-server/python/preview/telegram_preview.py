"""Local Telegram look-alike for trying the Streamline bot by hand.

Runs the real bot code (menus, checkout, support relay, reseller area, trial
provisioning) in demo mode against a throwaway SQLite database, with a fake
Telegram transport that keeps every message in memory. Nothing talks to
Telegram, the panel or any blockchain.

    python3 preview/telegram_preview.py            # http://127.0.0.1:8099
    PREVIEW_PORT=8123 python3 preview/telegram_preview.py

Environment: PREVIEW_USER_ID (default 8072956432), PREVIEW_ADMIN_ID (default
999000001), PREVIEW_RATE_LIMITS=1 to keep the bot's per-user rate limits on.
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from cryptography.fernet import Fernet  # noqa: E402

from streambot.__main__ import build  # noqa: E402
from streambot.bot import TelegramBot, TelegramError  # noqa: E402
from streambot.config import load_config  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'preview'
PORT = int(os.environ.get('PREVIEW_PORT', '8099'))
YOU = int(os.environ.get('PREVIEW_USER_ID', '8072956432'))
ADMIN = int(os.environ.get('PREVIEW_ADMIN_ID', '999000001'))
RESELLER = ADMIN + 1
RATE_LIMITS = os.environ.get('PREVIEW_RATE_LIMITS') == '1'
BOT = {'id': 1, 'is_bot': True, 'first_name': 'Streamline', 'username': 'FlixFlexBot'}
USERS = [
    {'id': YOU, 'label': 'You', 'first_name': 'You', 'username': 'you'},
    {'id': ADMIN, 'label': 'Support admin', 'first_name': 'Admin', 'username': 'InterRamit'},
    {'id': RESELLER, 'label': 'Reseller applicant', 'first_name': 'Reseller', 'username': 'reseller_demo'},
]


class FakeTelegram:
    """In-memory stand-in for the Telegram Bot API, driven by the browser."""

    def __init__(self):
        self.lock = threading.Condition()
        self.chats = {}          # chat_id -> [message dict]
        self.counters = {}       # chat_id -> last message_id
        self.toasts = []         # callback answers with text
        self.updates = []        # pending updates for getUpdates
        self.callback_chats = {}  # callback_query_id -> chat_id
        self.commands = []
        self.seq = 0
        self.update_id = 0

    # ---- helpers -------------------------------------------------------
    def bump(self):
        self.seq += 1
        self.lock.notify_all()
        return self.seq

    def new_message(self, chat_id, sender, **fields):
        self.counters[chat_id] = self.counters.get(chat_id, 0) + 1
        message = {'message_id': self.counters[chat_id], 'chat_id': chat_id, 'from': sender,
                   'date': time.time(), 'edited': False}
        message.update(fields)
        message['seq'] = self.bump()
        self.chats.setdefault(chat_id, []).append(message)
        return message

    def find(self, chat_id, message_id):
        for message in self.chats.get(chat_id, []):
            if message['message_id'] == message_id:
                return message
        return None

    # ---- Bot API -------------------------------------------------------
    def __call__(self, method, payload):
        with self.lock:
            if method == 'getUpdates':
                if not self.updates:
                    self.lock.wait(1.0)
                batch, self.updates = self.updates[:100], self.updates[100:]
                return batch
            if method == 'getMe':
                return dict(BOT)
            if method == 'setMyCommands':
                self.commands = payload.get('commands', [])
                self.bump()
                return True
            if method == 'sendMessage':
                message = self.new_message(payload['chat_id'], 'bot', text=payload.get('text', ''),
                                           parse_mode=payload.get('parse_mode'),
                                           reply_markup=payload.get('reply_markup'),
                                           reply_to_message_id=payload.get('reply_to_message_id'))
                return {'message_id': message['message_id'], 'chat': {'id': payload['chat_id']},
                        'text': message['text']}
            if method == 'editMessageText':
                message = self.find(payload['chat_id'], payload['message_id'])
                if message is None:
                    raise TelegramError(400, method, description='Bad Request: message to edit not found')
                if message['from'] != 'bot':
                    raise TelegramError(400, method, description="Bad Request: message can't be edited")
                same = (message['text'] == payload.get('text', '')
                        and (message.get('reply_markup') or None) == (payload.get('reply_markup') or None))
                if same:
                    raise TelegramError(400, method, description='Bad Request: message is not modified')
                message.update(text=payload.get('text', ''), parse_mode=payload.get('parse_mode'),
                               reply_markup=payload.get('reply_markup'), edited=True, seq=self.bump())
                return {'message_id': message['message_id'], 'chat': {'id': payload['chat_id']}}
            if method == 'copyMessage':
                source = self.find(payload['from_chat_id'], payload['message_id'])
                if source is None:
                    raise TelegramError(400, method, description='Bad Request: message to copy not found')
                copy = self.new_message(payload['chat_id'], 'bot', text=source.get('text', ''),
                                        parse_mode=source.get('parse_mode'), reply_markup=None, copied=True)
                return {'message_id': copy['message_id']}
            if method == 'answerCallbackQuery':
                if payload.get('text'):
                    chat_id = self.callback_chats.get(payload.get('callback_query_id'))
                    self.toasts.append({'chat_id': chat_id, 'text': payload['text'],
                                        'alert': bool(payload.get('show_alert')), 'seq': self.bump()})
                return True
            return True

    # ---- browser-driven events ---------------------------------------
    def user(self, uid):
        for user in USERS:
            if user['id'] == uid:
                return {'id': uid, 'first_name': user['first_name'], 'username': user['username']}
        return {'id': uid, 'first_name': 'User ' + str(uid)}

    def queue(self, update):
        self.update_id += 1
        update['update_id'] = self.update_id
        self.updates.append(update)
        self.lock.notify_all()

    def send_text(self, uid, text, reply_to=None):
        with self.lock:
            fields = {'text': text}
            if reply_to:
                fields['reply_to_message_id'] = reply_to
            message = self.new_message(uid, 'user', **fields)
            update = {'message_id': message['message_id'], 'from': self.user(uid),
                      'chat': {'id': uid, 'type': 'private'}, 'date': int(time.time()), 'text': text}
            if reply_to:
                update['reply_to_message'] = {'message_id': reply_to}
            self.queue({'message': update})
            return message

    def tap(self, uid, message_id, data):
        with self.lock:
            callback_id = 'cb-%d-%d' % (uid, time.time_ns())
            self.callback_chats[callback_id] = uid
            self.queue({'callback_query': {
                'id': callback_id, 'from': self.user(uid), 'data': data,
                'message': {'message_id': message_id, 'chat': {'id': uid, 'type': 'private'}}}})

    def state(self, uid, since, timeout=20.0):
        deadline = time.monotonic() + timeout
        with self.lock:
            while self.seq <= since and time.monotonic() < deadline:
                self.lock.wait(deadline - time.monotonic())
            messages = [dict(m) for m in self.chats.get(uid, [])]
            toasts = [t for t in self.toasts if t['chat_id'] == uid and t['seq'] > since]
            return {'seq': self.seq, 'bot': BOT, 'commands': self.commands, 'users': USERS,
                    'rate_limits': RATE_LIMITS, 'messages': messages, 'toasts': toasts}


def start_bot():
    DATA.mkdir(parents=True, exist_ok=True)
    key_path = DATA / 'key'
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
    env = {'APP_MODE': 'demo', 'TELEGRAM_BOT_TOKEN': 'preview', 'TELEGRAM_ENABLED': 'true',
           'SUPPORT_ADMIN_ID': str(ADMIN), 'DATABASE_PATH': str(DATA / 'preview.sqlite3'),
           'CREDENTIAL_KEY': key_path.read_text().strip(), 'PUBLIC_URL': 'http://127.0.0.1:%d' % PORT}
    config = load_config(ROOT / 'config.json', env=env)
    service = build(config)
    service.recover_interrupted()
    api = FakeTelegram()
    api.update_id = int(service.store.metadata('telegram_offset') or '0')
    bot = TelegramBot(service, api=api)
    stop = threading.Event()

    def worker():
        while not stop.is_set():
            try:
                service.provision_pending()
            except Exception as exc:  # mirrors the production worker: log and keep going
                print('worker paused:', type(exc).__name__, flush=True)
            stop.wait(1)

    threading.Thread(target=bot.run, args=(stop,), daemon=True, name='telegram-preview').start()
    threading.Thread(target=worker, daemon=True, name='account-worker').start()
    return service, api, stop


def unthrottle(service):
    if RATE_LIMITS:
        return
    with service.store.connection() as db:
        db.execute('DELETE FROM limits')


def reset_and_restart():
    time.sleep(0.3)
    for name in ('preview.sqlite3', 'preview.sqlite3-journal', 'preview.sqlite3-wal',
                 'preview.sqlite3-shm', 'key'):
        try:
            (DATA / name).unlink()
        except FileNotFoundError:
            pass
    os.execv(sys.executable, [sys.executable] + sys.argv)


def main():
    service, api, _stop = start_bot()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal quiet
            pass

        def reply(self, status, body, content_type='application/json; charset=utf-8'):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == '/':
                return self.reply(200, (HERE / 'telegram.html').read_bytes(), 'text/html; charset=utf-8')
            if url.path == '/api/state':
                query = parse_qs(url.query)
                uid = int(query.get('uid', [YOU])[0])
                since = int(query.get('since', ['0'])[0])
                return self.reply(200, api.state(uid, since))
            self.reply(404, {'error': 'not found'})

        def do_POST(self):
            length = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(length) or b'{}')
            uid = int(body.get('uid', YOU))
            if self.path == '/api/send':
                unthrottle(service)
                api.send_text(uid, str(body.get('text', '')).strip(), body.get('reply_to'))
                return self.reply(200, {'ok': True})
            if self.path == '/api/tap':
                unthrottle(service)
                api.tap(uid, int(body['message_id']), str(body['data']))
                return self.reply(200, {'ok': True})
            if self.path == '/api/reset':
                threading.Thread(target=reset_and_restart, daemon=True).start()
                return self.reply(200, {'ok': True})
            self.reply(404, {'error': 'not found'})

    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    server.daemon_threads = True
    print('Telegram preview (demo mode, no network): http://127.0.0.1:%d' % PORT, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
