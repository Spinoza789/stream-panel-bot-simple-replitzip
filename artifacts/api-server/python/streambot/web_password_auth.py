"""Encrypted local-owner credentials behind the process-authenticated bridge only."""
import re
import secrets
import time

from flask import jsonify, request

LOCAL_OWNER_KEY = 'web_local_owner'


def register_password_routes(routes, store):
    def profile():
        return store.unseal(store.metadata(LOCAL_OWNER_KEY))

    def valid(value):
        return (isinstance(value, dict)
                and re.fullmatch(r'[a-f0-9]{32}', str(value.get('id', '')))
                and isinstance(value.get('username'), str)
                and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{2,31}', value['username'])
                and isinstance(value.get('email'), str) and len(value['email']) <= 254
                and re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', value['email'])
                and re.fullmatch(r'scrypt-v1\$[a-f0-9]{32}\$[a-f0-9]{128}',
                                 str(value.get('passwordHash', '')))
                and type(value.get('version')) is int and value['version'] > 0)

    @routes.get('/auth/status')
    def auth_status():
        return jsonify(configured=bool(store.metadata(LOCAL_OWNER_KEY)))

    @routes.get('/auth/credentials')
    def auth_credentials():
        # Never mounted publicly. Only the gateway verifies hashes; browsers see
        # safe account fields from separate Node endpoints.
        return jsonify(profile=profile())

    @routes.post('/auth/attempt')
    def auth_attempt():
        data = request.get_json(silent=True) or {}
        kind = data.get('kind')
        buckets = data.get('buckets')
        if (kind not in ('login', 'setup', 'update') or not isinstance(buckets, list)
                or len(buckets) != 2 or any(not isinstance(b, str)
                    or not re.fullmatch(r'[a-f0-9]{64}', b) for b in buckets)):
            return jsonify(error='Invalid rate limit.'), 400
        count = 10 if kind == 'login' else 5
        allowed = [store.limit('web-password:' + kind + ':' + bucket, count, 900)
                   for bucket in buckets]
        return jsonify(allowed=all(allowed))

    @routes.post('/auth/setup')
    def setup_password():
        data = request.get_json(silent=True)
        if not valid(data):
            return jsonify(error='Invalid local account.'), 400
        subject = 'local:' + data['id']
        if not request.admin_actor.startswith(subject + ':'):
            return jsonify(error='Invalid setup identity.'), 403
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT value FROM metadata WHERE key=?', (LOCAL_OWNER_KEY,)).fetchone():
                return jsonify(error='Administrator login is already configured.'), 409
            old = db.execute("SELECT value FROM metadata WHERE key='web_admin_owner'").fetchone()
            if old and not old[0].startswith('replit:'):
                return jsonify(error='Existing owner requires support.'), 409
            db.execute('INSERT INTO metadata VALUES(?,?)', (LOCAL_OWNER_KEY, store.seal(data)))
            db.execute("INSERT OR REPLACE INTO metadata VALUES('web_admin_owner',?)", (subject,))
            db.execute('INSERT INTO metadata VALUES(?,?)', (
                'web_owner_password_setup:' + secrets.token_hex(12),
                store.seal(dict(actor=subject, previous_owner=old[0] if old else None,
                                at=int(time.time()), proof='workspace_secret'))))
        return jsonify(saved=True)

    @routes.post('/auth/update')
    def update_password():
        data = request.get_json(silent=True) or {}
        updated = data.get('profile')
        expected = data.get('expectedVersion')
        if not valid(updated) or type(expected) is not int or updated['version'] != expected + 1:
            return jsonify(error='Invalid account update.'), 400
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT value FROM metadata WHERE key=?', (LOCAL_OWNER_KEY,)).fetchone()
            owner = db.execute("SELECT value FROM metadata WHERE key='web_admin_owner'").fetchone()
            if not row or not owner or owner[0] != request.admin_actor.rsplit(':', 1)[0]:
                return jsonify(error='Owner session required.'), 403
            current = store.unseal(row[0])
            if current['id'] != updated['id'] or current['version'] != expected:
                return jsonify(error='Account changed. Sign in again.'), 409
            db.execute('UPDATE metadata SET value=? WHERE key=?', (store.seal(updated), LOCAL_OWNER_KEY))
            db.execute('INSERT INTO metadata VALUES(?,?)', (
                'web_owner_password_update:' + secrets.token_hex(12),
                store.seal(dict(actor=request.admin_actor, at=int(time.time()),
                                version=updated['version']))))
        return jsonify(saved=True)
