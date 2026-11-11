"""Reseller web portal sign-in: Telegram one-time links, optional recovery email + password, cookie sessions.

No Flask here; the HTTP routes live in reseller_web_routes.py. Identity stays the
reseller's Telegram ID; the email/password is an additional way to reach the same account.
"""
import base64
import hashlib
import hmac
import logging
import re
import secrets

from .reseller_ledger import now
from .service import CheckoutError
from .store import digest

log = logging.getLogger(__name__)
EMAIL = re.compile(r'^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$')


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return 'scrypt$16384$8$1$' + base64.b64encode(salt).decode() + '$' + base64.b64encode(derived).decode()


def check_password(password, stored):
    try:
        _, n, r, p, salt, expected = stored.split('$')
        derived = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(base64.b64encode(derived).decode(), expected)
    except (ValueError, TypeError):
        return False


class ResellerWeb:
    CODE_TTL = 600            # one-time sign-in link from the bot
    SESSION_TTL = 30 * 86400  # browser session
    PREVIEW_TTL = 600         # a previewed operation must be confirmed within this window

    def __init__(self, resellers):
        self.r = resellers
        self.service = resellers.service
        self.store = self.service.store
        try:
            with self.store.connection() as db:
                db.execute('SELECT token_hash FROM rs_web_sessions WHERE 1=0')
                db.execute('SELECT reseller_id FROM rs_logins WHERE 1=0')
                db.execute('SELECT code_hash FROM rs_web_codes WHERE 1=0')
                db.execute('SELECT poll_hash FROM rs_login_requests WHERE 1=0')
            self.ready = True
        except Exception as exc:
            self.ready = False
            log.warning('Reseller web tables unavailable (%s); the web dashboard is disabled until the schema is published.', type(exc).__name__)

    def require_ready(self):
        self.r.require_ready()
        if not self.ready:
            raise CheckoutError('The web dashboard is not available until the database schema is published.')

    # ---- Telegram one-time link ------------------------------------------------
    def issue_code(self, uid):
        self.require_ready()
        member = self.r.member(uid)
        if not member:
            raise CheckoutError('Apply as a reseller first.')
        code = secrets.token_urlsafe(24)
        with self.r.finance.transaction() as db:
            db.execute('DELETE FROM rs_web_codes WHERE expires_at<? OR reseller_id=?', (now(), member['id']))
            db.execute('INSERT INTO rs_web_codes VALUES(?,?,?)', (digest(code), member['id'], now() + self.CODE_TTL))
        return code

    # ---- "Log in with Telegram" button: browser starts a request, the bot approves it -----
    LOGIN_TTL = 600

    def bot_username(self):
        name = self.service.config.get('bot_username') or self.store.metadata('bot_username') or ''
        return name if re.fullmatch(r'[A-Za-z0-9_]{3,64}', name) else ''

    def start_login(self):
        """Create a pending login request. The browser keeps `poll` (its secret); the Telegram deep link carries `code`."""
        self.require_ready()
        bot = self.bot_username()
        base = self.service.config.get('telegram_start_url') or ('https://t.me/' + bot + '?start=' if bot else '')
        if not base:
            raise CheckoutError('Telegram login is not set up yet. Open the bot and use Open web dashboard instead.')
        code = secrets.token_urlsafe(16); poll = secrets.token_urlsafe(24)
        with self.r.finance.transaction() as db:
            db.execute('DELETE FROM rs_login_requests WHERE expires_at<?', (now(),))
            db.execute('INSERT INTO rs_login_requests(poll_hash,code_hash,reseller_id,created_at,expires_at) VALUES(?,?,NULL,?,?)',
                       (digest(poll), digest(code), now(), now() + self.LOGIN_TTL))
        return dict(code=code, poll=poll, url=base + 'login_' + code, expires_in=self.LOGIN_TTL)

    @staticmethod
    def valid_login_code(code):
        return isinstance(code, str) and re.fullmatch(r'[A-Za-z0-9_-]{16,40}', code) is not None

    def login_request(self, code):
        """The pending request behind a deep-link code, for the bot's confirmation screen."""
        self.require_ready()
        if not self.valid_login_code(code): raise CheckoutError('This login link is not valid.')
        with self.store.connection() as db:
            row = db.execute('SELECT reseller_id,expires_at FROM rs_login_requests WHERE code_hash=?', (digest(code),)).fetchone()
        if not row or row['expires_at'] < now() or row['reseller_id']:
            raise CheckoutError('This login request has expired or was already used. Tap Log in with Telegram on the website again.')
        return dict(expires_at=row['expires_at'])

    def approve_login(self, code, uid):
        """Bind the browser's request to the Telegram user who confirmed it. Only resellers can use the panel."""
        self.require_ready()
        if not self.valid_login_code(code): raise CheckoutError('This login link is not valid.')
        member = self.r.member(uid)
        if not member: raise CheckoutError('Buy a credit pack in the bot first; that creates your reseller account and the web panel opens up.')
        with self.r.finance.transaction() as db:
            cursor = db.execute('UPDATE rs_login_requests SET reseller_id=? WHERE code_hash=? AND reseller_id IS NULL AND expires_at>=?',
                                (member['id'], digest(code), now()))
            if not cursor.rowcount:
                raise CheckoutError('This login request has expired or was already used. Tap Log in with Telegram on the website again.')
        return member

    def poll_login(self, poll):
        """Session token once the bot approved the request; None while still waiting."""
        self.require_ready()
        if not isinstance(poll, str) or not 20 <= len(poll) <= 100: raise CheckoutError('This login request is not valid.')
        with self.r.finance.transaction() as db:
            row = db.execute('SELECT reseller_id,expires_at FROM rs_login_requests WHERE poll_hash=?', (digest(poll),)).fetchone()
            if not row or row['expires_at'] < now():
                db.execute('DELETE FROM rs_login_requests WHERE poll_hash=?', (digest(poll),))
                raise CheckoutError('This login request has expired. Tap Log in with Telegram again.')
            if not row['reseller_id']: return None
            db.execute('DELETE FROM rs_login_requests WHERE poll_hash=?', (digest(poll),))
            return self._create_session(db, row['reseller_id'])

    def login_url(self, code):
        config = self.service.config
        return config['public_url'] + config.get('base_path', '') + '/#code=' + code

    def redeem_code(self, code):
        self.require_ready()
        if not isinstance(code, str) or not 20 <= len(code) <= 100:
            raise CheckoutError('This sign-in link is not valid.')
        with self.r.finance.transaction() as db:
            row = db.execute('SELECT reseller_id,expires_at FROM rs_web_codes WHERE code_hash=?', (digest(code),)).fetchone()
            db.execute('DELETE FROM rs_web_codes WHERE code_hash=?', (digest(code),))
            if not row or row['expires_at'] < now():
                raise CheckoutError('This sign-in link has expired. Open the bot and request a new one.')
            return self._create_session(db, row['reseller_id'])

    # ---- sessions ----------------------------------------------------------------
    def _create_session(self, db, reseller_id):
        token = secrets.token_urlsafe(32)
        db.execute('DELETE FROM rs_web_sessions WHERE expires_at<?', (now(),))
        db.execute('INSERT INTO rs_web_sessions VALUES(?,?,?,?,?)',
                   (digest(token), reseller_id, now(), now() + self.SESSION_TTL, now()))
        return token

    def session_uid(self, token):
        """Telegram ID for a live session token, or None."""
        if not self.ready or not isinstance(token, str) or not 20 <= len(token) <= 100:
            return None
        with self.store.connection() as db:
            row = db.execute('SELECT s.expires_at,r.telegram_id FROM rs_web_sessions s JOIN rs_resellers r ON r.id=s.reseller_id '
                             'WHERE s.token_hash=?', (digest(token),)).fetchone()
        if not row or row['expires_at'] < now():
            return None
        with self.r.finance.transaction() as db:
            db.execute('UPDATE rs_web_sessions SET last_seen=? WHERE token_hash=?', (now(), digest(token)))
        return row['telegram_id']

    def sign_out(self, token):
        if not self.ready or not isinstance(token, str):
            return
        with self.r.finance.transaction() as db:
            db.execute('DELETE FROM rs_web_sessions WHERE token_hash=?', (digest(token),))

    def sign_out_everywhere(self, uid):
        member = self.r.member(uid)
        if member:
            with self.r.finance.transaction() as db:
                db.execute('DELETE FROM rs_web_sessions WHERE reseller_id=?', (member['id'],))

    # ---- recovery email + password ---------------------------------------------
    def login(self, uid):
        member = self.r.member(uid)
        if not member or not self.ready:
            return {'email': '', 'has_password': False}
        with self.store.connection() as db:
            row = db.execute('SELECT email FROM rs_logins WHERE reseller_id=?', (member['id'],)).fetchone()
        return {'email': row['email'] if row else '', 'has_password': bool(row)}

    def set_login(self, uid, email, password, current_password=None):
        self.require_ready()
        member = self.r.member(uid)
        if not member:
            raise CheckoutError('Reseller account not found.')
        email = (email or '').strip().lower()
        if not isinstance(email, str) or len(email) > 254 or not EMAIL.match(email):
            raise CheckoutError('Enter a valid email address.')
        if not isinstance(password, str) or not 10 <= len(password) <= 200:
            raise CheckoutError('Use a password of at least 10 characters.')
        with self.r.finance.transaction() as db:
            existing = db.execute('SELECT password_hash FROM rs_logins WHERE reseller_id=?', (member['id'],)).fetchone()
            if existing and not check_password(current_password or '', existing['password_hash']):
                raise CheckoutError('Your current password is incorrect.')
            taken = db.execute('SELECT reseller_id FROM rs_logins WHERE email=? AND reseller_id<>?', (email, member['id'])).fetchone()
            if taken:
                raise CheckoutError('That email address is already used by another reseller account.')
            if existing:
                db.execute('UPDATE rs_logins SET email=?,password_hash=?,updated_at=? WHERE reseller_id=?',
                           (email, hash_password(password), now(), member['id']))
            else:
                db.execute('INSERT INTO rs_logins VALUES(?,?,?,?)', (member['id'], email, hash_password(password), now()))
        return self.login(uid)

    def password_login(self, email, password):
        self.require_ready()
        email = (email or '').strip().lower() if isinstance(email, str) else ''
        with self.store.connection() as db:
            row = db.execute('SELECT reseller_id,password_hash FROM rs_logins WHERE email=?', (email,)).fetchone() if email else None
        # Same cost and message whether or not the email exists.
        if not row or not isinstance(password, str) or not check_password(password, row['password_hash']):
            if not row:
                check_password(password if isinstance(password, str) else '', hash_password('timing-equaliser'))
            raise CheckoutError('Email or password is incorrect.')
        with self.r.finance.transaction() as db:
            return self._create_session(db, row['reseller_id'])

    # ---- previewed operations -------------------------------------------------------
    def stash_preview(self, uid, preview):
        nonce = secrets.token_hex(12)
        self.store.metadata('rs_web_preview:' + digest(str(uid) + ':' + nonce),
                            self.store.seal(dict(preview=preview, expires=now() + self.PREVIEW_TTL)))
        return nonce

    def take_preview(self, uid, nonce):
        if not isinstance(nonce, str) or not re.fullmatch(r'[0-9a-f]{24}', nonce):
            raise CheckoutError('Invalid confirmation.')
        key = 'rs_web_preview:' + digest(str(uid) + ':' + nonce)
        saved = self.store.unseal(self.store.metadata(key))
        if not saved or saved['expires'] < now():
            raise CheckoutError('This preview has expired. Preview the request again.')
        return saved['preview'], 'web:' + nonce

    def costs(self):
        with self.store.connection() as db:
            return [dict(r) for r in db.execute('SELECT months,connections,credits FROM rs_costs ORDER BY months,connections').fetchall()]
