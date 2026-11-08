import contextlib
import hashlib
import json
import os
import secrets
import sqlite3
import time
from cryptography.fernet import Fernet


def digest(value): return hashlib.sha256(value if isinstance(value,bytes) else str(value).encode()).hexdigest()


class Store:
    def __init__(self, path, key):
        self.path = str(path)
        self.cipher = Fernet(key.encode() if isinstance(key, str) else key)
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), mode=0o700, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY, token_hash TEXT UNIQUE, kind TEXT NOT NULL,
                    telegram_id INTEGER UNIQUE, plan_json TEXT NOT NULL, asset_json TEXT NOT NULL,
                    amount_units TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', txid TEXT, message TEXT NOT NULL DEFAULT '',
                    credentials TEXT, attempts INTEGER NOT NULL DEFAULT 0, last_check INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS payments (
                    network TEXT NOT NULL, txid TEXT NOT NULL, order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
                    proof TEXT NOT NULL, PRIMARY KEY(network,txid)
                );
                CREATE TABLE IF NOT EXISTS links (
                    code_hash TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id), expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS account_links (
                    telegram_id INTEGER NOT NULL, order_id TEXT NOT NULL REFERENCES orders(id),
                    PRIMARY KEY(telegram_id,order_id), UNIQUE(order_id)
                );
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS limits (bucket TEXT NOT NULL, at INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS limits_bucket ON limits(bucket,at);
                CREATE INDEX IF NOT EXISTS orders_state ON orders(status,last_check);
            ''')
            from .reseller_schema import SCHEMA
            db.executescript(SCHEMA)
            from .notification_schema import SCHEMA as NOTIFICATION_SCHEMA
            db.executescript(NOTIFICATION_SCHEMA)
        os.chmod(self.path, 0o600)

    @contextlib.contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db: yield db
        finally: db.close()

    def seal(self, value): return self.cipher.encrypt(json.dumps(value).encode()).decode()
    def unseal(self, value): return json.loads(self.cipher.decrypt(value.encode())) if value else None

    def decode(self, row):
        if row is None: return None
        item = dict(row)
        item['plan'] = json.loads(item.pop('plan_json'))
        item['asset'] = json.loads(item.pop('asset_json'))
        item['credentials'] = self.unseal(item['credentials'])
        return item

    def get(self, order_id):
        with self.connection() as db: return self.decode(db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone())

    def by_token(self, token):
        with self.connection() as db: return self.decode(db.execute('SELECT * FROM orders WHERE token_hash=?', (digest(token),)).fetchone())

    def owned_order(self,telegram_id,order_id):
        with self.connection() as db:
            return self.decode(db.execute('SELECT o.* FROM orders o JOIN account_links a ON a.order_id=o.id '
                                          'WHERE o.id=? AND a.telegram_id=?',(order_id,telegram_id)).fetchone())

    def telegram_orders(self,telegram_id=None,limit=50):
        statement=("SELECT o.*,a.telegram_id AS owner_id FROM orders o "
                   "JOIN account_links a ON a.order_id=o.id JOIN metadata m ON m.key='tg_order:'||o.id "
                   "WHERE o.kind='paid'")
        parameters=[]
        if telegram_id is not None:
            statement+=' AND a.telegram_id=?';parameters.append(telegram_id)
        else:
            statement+=" AND (o.status!='pending' OR o.last_check>0)"
            statement+=(" AND NOT EXISTS (SELECT 1 FROM metadata n WHERE n.key='tg_notice:'||o.id "
                        "AND n.value=o.status||':'||o.message)")
        statement+=' ORDER BY o.created_at '+('DESC' if telegram_id is not None else 'ASC')+' LIMIT ?'
        parameters.append(limit)
        with self.connection() as db:
            return [self.decode(row) for row in db.execute(statement,tuple(parameters)).fetchall()]

    def trial(self, tg_id):
        with self.connection() as db: return self.decode(db.execute('SELECT * FROM orders WHERE telegram_id=?', (tg_id,)).fetchone())

    def create(self, plan, asset, base_units, quantum=1, *, telegram_id=None, daily_limit=20,
               lifetime=3600, max_nonce=999, owner_telegram_id=None, request_key=None):
        if telegram_id is not None and (type(telegram_id) is not int or telegram_id<=0):
            raise ValueError('Invalid Telegram user.')
        now = int(time.time()); token = secrets.token_urlsafe(32); order_id = secrets.token_hex(12)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            purchase=plan.get('reseller_purchase')
            if purchase:
                reseller=db.execute("SELECT id FROM rs_resellers WHERE id=? AND telegram_id=? AND status='active'",
                                    (purchase['reseller_id'],owner_telegram_id)).fetchone()
                if not reseller:raise ValueError('An approved active reseller account is required.')
            if owner_telegram_id is not None:
                if type(owner_telegram_id) is not int or owner_telegram_id<=0 or telegram_id is not None:
                    raise ValueError('Invalid payment owner.')
                if request_key:
                    previous=db.execute('SELECT value FROM metadata WHERE key=?',(request_key,)).fetchone()
                    if previous:
                        existing=db.execute('SELECT o.* FROM orders o JOIN account_links a ON a.order_id=o.id '
                                            'WHERE o.id=? AND a.telegram_id=?',(previous[0],owner_telegram_id)).fetchone()
                        if existing: return None,self.decode(existing)
                pending=db.execute("SELECT o.* FROM orders o JOIN account_links a ON a.order_id=o.id "
                                   "WHERE a.telegram_id=? AND o.kind='paid' AND o.status='pending' AND o.expires_at>=?",
                                   (owner_telegram_id,now)).fetchall()
                for row in pending:
                    existing=self.decode(row)
                    if existing['plan']['id']==plan['id'] and existing['asset']['id']==asset['id']:
                        if request_key:
                            db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',(request_key,existing['id']))
                        return None,existing
                count=db.execute("SELECT count(*) FROM orders o JOIN account_links a ON a.order_id=o.id "
                                 "WHERE a.telegram_id=? AND o.kind='paid' AND o.created_at>=?",
                                 (owner_telegram_id,now-3600)).fetchone()[0]
                if count>=10: raise ValueError('Too many quotes. Use My orders to return to an existing quote.')
            if telegram_id is not None:
                # Lifetime eligibility: an expired, failed or fulfilled trial
                # still belongs to this Telegram ID. Never reset it here.
                existing = db.execute('SELECT * FROM orders WHERE telegram_id=?', (telegram_id,)).fetchone()
                if existing: return None, self.decode(existing)
                count = db.execute("SELECT count(*) FROM orders WHERE kind='trial' AND created_at>=?", (now-86400,)).fetchone()[0]
                if count >= daily_limit: raise ValueError('The daily trial allowance has been reached. Please contact support.')
                amount = 0
            else:
                reserved = {row[0] for row in db.execute("SELECT amount_units FROM orders WHERE json_extract(asset_json,'$.id')=? AND expires_at>=?", (asset['id'], now))}
                candidates = [base_units + n * quantum for n in range(1, max_nonce+1) if str(base_units + n * quantum) not in reserved]
                if not candidates: raise ValueError('All payment quotes are reserved. Please try later.')
                amount = secrets.choice(candidates)
            db.execute('INSERT INTO orders(id,token_hash,kind,telegram_id,plan_json,asset_json,amount_units,created_at,expires_at,status) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (order_id, digest(token), 'trial' if telegram_id is not None else 'paid', telegram_id,
                        json.dumps(plan), json.dumps(asset), str(amount), now, now+lifetime, 'paid' if telegram_id is not None else 'pending'))
            if owner_telegram_id is not None:
                db.execute('INSERT INTO account_links VALUES(?,?)',(owner_telegram_id,order_id))
                db.execute('INSERT INTO metadata VALUES(?,?)',('tg_order:'+order_id,'1'))
                if request_key:
                    db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',(request_key,order_id))
            if purchase:
                package=purchase['package']
                db.execute('INSERT INTO rs_purchases VALUES(?,?,?,?,?,?,?,?,?)',
                           (order_id,purchase['reseller_id'],json.dumps(package),package['price_pence'],
                            package['credits'],None,'pending',now,now))
        return token, self.get(order_id)

    def update(self, order_id, **values):
        allowed = {'status','txid','message','credentials','last_check','attempts'}
        if not values or not set(values) <= allowed: raise ValueError('Invalid update fields.')
        if 'credentials' in values: values['credentials'] = self.seal(values['credentials'])
        with self.connection() as db:
            db.execute('UPDATE orders SET ' + ','.join(k+'=?' for k in values) + ' WHERE id=?', (*values.values(), order_id))

    def submit_tx(self,order_id,txid):
        with self.connection() as db:
            db.execute("UPDATE orders SET txid=?,message='Checking the blockchain. Confirmation can take several minutes.',"
                       "last_check=0 WHERE id=? AND status='pending'",(txid,order_id))

    def claim_payment(self, order_id, proof):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            order = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
            if order['status'] != 'pending': return False
            try:
                db.execute('INSERT INTO payments VALUES(?,?,?,?)', (proof['network'], proof['txid'], order_id, json.dumps(proof)))
            except sqlite3.IntegrityError:
                db.execute("UPDATE orders SET message='This transaction has already been used.',txid=NULL WHERE id=?", (order_id,))
                return False
            db.execute("UPDATE orders SET status='paid',txid=?,message='Payment confirmed. Preparing your account.' WHERE id=?", (proof['txid'],order_id))
            return True

    def claim_provision(self, order_id):
        with self.connection() as db:
            return db.execute("UPDATE orders SET status='provisioning' WHERE id=? AND status='paid'", (order_id,)).rowcount == 1

    def resolve_trial_review(self, order_id, telegram_id, account=None, *, clear_credentials=False):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if account is not None:
                db.execute("UPDATE orders SET status='fulfilled',credentials=?,message='Your account is ready.' "
                           "WHERE id=? AND telegram_id=? AND kind='trial' AND status='review'",
                           (self.seal(account),order_id,telegram_id))
            else:
                reset = "credentials=NULL," if clear_credentials else ""
                changed = db.execute("UPDATE orders SET "+reset+"status='paid',message='Existing trial retry queued after a panel account check.' "
                                     "WHERE id=? AND telegram_id=? AND kind='trial' AND status='review'",
                                     (order_id,telegram_id)).rowcount
                if changed:
                    db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',
                               ('trial_recheck_after:'+order_id,str(int(time.time())+300)))

    def select(self, status, limit=50):
        with self.connection() as db:
            extra = ' AND txid IS NOT NULL' if status == 'pending' else ''
            return [self.decode(row) for row in db.execute('SELECT * FROM orders WHERE status=?' + extra + ' ORDER BY last_check,created_at LIMIT ?', (status,limit))]

    def limit(self, bucket, count, window):
        now = int(time.time())
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM limits WHERE at<?', (now-86400,))
            recent = db.execute('SELECT count(*) FROM limits WHERE bucket=? AND at>?', (digest(bucket), now-window)).fetchone()[0]
            if recent >= count: return False
            db.execute('INSERT INTO limits VALUES(?,?)', (digest(bucket),now))
            return True

    def metadata(self, key, value=None):
        with self.connection() as db:
            if value is not None: db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', (key,str(value)))
            row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            return row[0] if row else None
