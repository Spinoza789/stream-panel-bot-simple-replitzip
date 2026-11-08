"""Explicit, audited administrator recovery of never-submitted retail trials."""
import json
import re
import secrets
import time

from .service import CheckoutError
from .store import digest


class TrialRecovery:
    def __init__(self, bot):
        self.bot = bot
        self.service = bot.service
        self.store = bot.store

    def admin(self, uid):
        if type(uid) is not int or uid != self.service.config.get('support_admin_id'):
            raise CheckoutError('Only the configured administrator can recover trials.')

    def validate(self, row):
        if not row or row['kind'] != 'trial' or row['status'] != 'review':
            raise CheckoutError('Recovery requires an existing retail trial in review.')
        details = self.store.unseal(row['credentials'])
        if details is not None and not (
                isinstance(details, dict) and details.get('generation_mode') == 'panel'
                and details.get('post_attempted') is False
                and not details.get('username') and not details.get('password')):
            raise CheckoutError('Account creation may already have started. Identify and reconcile the existing panel account; no retry was queued.')
        if self.service.config['mode'] == 'live' and not self.service.config['panel_writes']:
            raise CheckoutError('Panel account creation is disabled. No retry was queued.')
        if type(row['telegram_id']) is not int or row['telegram_id'] <= 0:
            raise CheckoutError('This trial has no valid Telegram owner.')

    @staticmethod
    def fingerprint(row):
        return digest(json.dumps([row[key] for key in (
            'id', 'kind', 'status', 'telegram_id', 'credentials', 'plan_json', 'created_at')]))

    def key(self, uid):
        return 'trial_recovery_draft:' + str(uid)

    def preview(self, uid, order_id):
        self.admin(uid)
        if not re.fullmatch(r'[0-9a-f]{24}', order_id):
            raise CheckoutError('Use /recovertrial ORDER_ID, or /recovertrial to list trials in review.')
        with self.store.connection() as db:
            row = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
            self.validate(row)
            fingerprint = self.fingerprint(row)
        nonce = secrets.token_hex(12)
        draft = dict(order_id=order_id, fingerprint=fingerprint,
                     nonce=nonce, expires=int(time.time()) + 600)
        self.store.metadata(self.key(uid), self.store.seal(draft))
        self.bot.send(uid,
            'ADMINISTRATOR TRIAL RECOVERY — NOT QUEUED\n\nOrder: ' + order_id +
            '\n\nBefore confirming, verify from provisioning logs that account creation '
            'never started. Missing saved details alone are not proof. If a creation '
            'request may have been sent, cancel and reconcile the panel account instead.'
            '\n\nConfirmation requeues this same trial and may create one panel account. '
            'It does not grant another trial or reset lifetime eligibility.',
            {'inline_keyboard': [
                [{'text': 'I verified creation never started', 'callback_data': 'tr:confirm:' + nonce}],
                [{'text': 'Cancel recovery', 'callback_data': 'tr:cancel:' + nonce}],
            ]})

    def confirm(self, uid, nonce, cancel=False):
        self.admin(uid)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            saved = db.execute('SELECT value FROM metadata WHERE key=?', (self.key(uid),)).fetchone()
            draft = self.store.unseal(saved[0]) if saved else None
            if (not draft or draft['nonce'] != nonce or draft['expires'] <= int(time.time())):
                raise CheckoutError('This recovery preview expired, changed, or was already used. Use /recovertrial again.')
            if not cancel:
                row = db.execute('SELECT * FROM orders WHERE id=?', (draft['order_id'],)).fetchone()
                self.validate(row)
                if self.fingerprint(row) != draft['fingerprint']:
                    raise CheckoutError('This trial changed after preview. Nothing was queued; review it again.')
                changed = db.execute(
                    "UPDATE orders SET status='paid',credentials=NULL,"
                    "message='Administrator confirmed no creation was submitted; original trial retry queued.' "
                    "WHERE id=? AND kind='trial' AND status='review'",
                    (draft['order_id'],)).rowcount
                if changed != 1:
                    raise CheckoutError('This trial changed. Nothing was queued.')
                audit = dict(administrator=uid, order_id=draft['order_id'], at=int(time.time()),
                             action='retry_original_trial', attestation='creation_never_started',
                             prior_fingerprint=draft['fingerprint'])
                db.execute('INSERT INTO metadata VALUES(?,?)',
                           ('trial_admin_recovery:' + nonce, self.store.seal(audit)))
                db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',
                           ('trial_recheck_after:' + draft['order_id'], str(int(time.time()) + 300)))
            db.execute('DELETE FROM metadata WHERE key=?', (self.key(uid),))
        return draft['order_id']

    def message(self, uid, command, argument):
        if command != '/recovertrial':
            return False
        self.admin(uid)
        if argument.strip():
            self.preview(uid, argument.strip())
        else:
            with self.store.connection() as db:
                rows = db.execute(
                    "SELECT id FROM orders WHERE kind='trial' AND status='review' "
                    "ORDER BY created_at DESC LIMIT 10").fetchall()
            self.bot.send(uid,
                'Trials in review. Select one to inspect recovery eligibility. '
                'No recovery is automatic.' if rows else 'No retail trials are in review.',
                {'inline_keyboard': [[{'text': row['id'], 'callback_data': 'tr:preview:' + row['id']}]
                                     for row in rows]} if rows else None)
        return True

    def callback(self, uid, action):
        if not action.startswith('tr:'):
            return False
        self.admin(uid)
        parts = action.split(':')
        if len(parts) != 3:
            raise CheckoutError('Invalid trial recovery option.')
        if parts[1] == 'preview':
            self.preview(uid, parts[2])
        elif parts[1] in ('confirm', 'cancel'):
            order_id = self.confirm(uid, parts[2], cancel=parts[1] == 'cancel')
            self.bot.send(uid, 'Recovery cancelled. Nothing was queued.' if parts[1] == 'cancel' else
                          'Original trial ' + order_id + ' queued. The worker will prepare it; '
                          'the customer can use /trial to check. Lifetime eligibility is unchanged.')
        else:
            raise CheckoutError('Invalid trial recovery option.')
        return True
