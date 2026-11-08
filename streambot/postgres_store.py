"""Durable Store using a private PostgreSQL schema.

The small connection adapter supports the SQL used by Store, CheckoutService,
and TelegramBot; it is deliberately not a general SQLite compatibility layer.
"""
import contextlib
import hashlib
import json
import re
import threading

import psycopg
from cryptography.fernet import Fernet

from .store import Store


class InstanceLockBusy(RuntimeError):
    """A healthy older instance still owns the worker lease."""


def _state_error(error, stage):
    """Expose useful failure categories, never the driver's secret-bearing text."""
    state = getattr(error, 'sqlstate', None)
    if not isinstance(state, str) or not re.fullmatch(r'[A-Z0-9]{5}', state):
        state = 'unavailable'
    result = RuntimeError(
        'PostgreSQL ' + stage + ' failed (' + type(error).__name__ +
        ', SQLSTATE ' + state + '). Check production database setup and permissions.'
    )
    result.db_stage = stage if stage in ('connect','query','commit') else 'unknown'
    result.sqlstate = state
    return result


class _Row(dict):
    """Keep SQLite's named and positional row access for existing callers."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def _row_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: _Row(zip(names, values))


def _placeholders(statement):
    """Translate parameters without altering question marks in quoted SQL."""
    result = []
    quote = None
    index = 0
    while index < len(statement):
        char = statement[index]
        if quote:
            result.append(char)
            if char == quote:
                if index + 1 < len(statement) and statement[index + 1] == quote:
                    result.append(quote)
                    index += 1
                else:
                    quote = None
        elif char in ("'", '"'):
            quote = char
            result.append(char)
        else:
            result.append('%s' if char == '?' else char)
        index += 1
    return ''.join(result)


class _Connection:
    def __init__(self, connection, transaction_lock):
        self._connection = connection
        self._transaction_lock = transaction_lock

    def execute(self, statement, parameters=None):
        if isinstance(statement, str):
            if statement.strip().rstrip(';').upper() == 'BEGIN IMMEDIATE':
                # READ COMMITTED takes a fresh snapshot after this lock is held,
                # matching SQLite's serialized read/check/write transactions.
                return self._connection.execute('SELECT pg_advisory_xact_lock(%s)', (self._transaction_lock,))
            statement = statement.replace("json_extract(asset_json,'$.id')", "(asset_json::jsonb ->> 'id')")
            # Metadata also contains encrypted state and text settings. PostgreSQL
            # may evaluate the cast before a sibling key predicate; CASE must
            # guard the cast itself, including against bigint overflow.
            statement = statement.replace(
                'CAST(value AS INTEGER)',
                "CASE WHEN value ~ '^-?[0-9]{1,18}$' THEN CAST(value AS BIGINT) ELSE NULL END")
            if re.match(r'^\s*INSERT OR REPLACE INTO metadata\b', statement, re.I):
                statement = re.sub(r'INSERT OR REPLACE INTO', 'INSERT INTO', statement, count=1, flags=re.I)
                statement = statement.rstrip().rstrip(';') + ' ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value'
            elif re.match(r'^\s*INSERT OR IGNORE INTO account_links\b', statement, re.I):
                statement = re.sub(r'INSERT OR IGNORE INTO', 'INSERT INTO', statement, count=1, flags=re.I)
                statement = statement.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'
            statement = _placeholders(statement)
        return self._connection.execute(statement, parameters)


class PostgresStore(Store):
    """Store contract with committed transactions and encrypted credentials.

    No DDL or data writes target public or another application's schema. Use a
    direct PostgreSQL endpoint for acquire_instance_lock(): that lock needs a
    dedicated session for the entire application lifetime.
    """

    def __init__(self, url, key, schema='stream_panel_bot_live'):
        if not isinstance(schema, str) or not re.fullmatch(r'stream_panel_bot_(?:demo|live|test_[0-9a-f]{1,40})', schema):
            raise ValueError('Use a dedicated stream_panel_bot_demo, stream_panel_bot_live, or stream_panel_bot_test_<hex> schema.')
        self.schema = schema
        self._url = url
        self.cipher = Fernet(key.encode() if isinstance(key, str) else key)
        self._slots = threading.BoundedSemaphore(8)
        self._transaction_lock = self._lock_id('transaction')
        self._instance_lock = self._lock_id('instance')
        self._instance_lock_lost = threading.Event()
        # Schema changes belong to development + Publish, never runtime startup.
        # Keep this validation read-only, including when a table is missing.
        with self.connection() as db:
            for table in ('orders','payments','links','account_links','metadata','limits'):
                if db.execute('SELECT to_regclass(?)',(self.schema+'.'+table,)).fetchone()[0] is None:
                    raise RuntimeError('PostgreSQL application schema is missing. Prepare sql/schema.sql in development and publish the schema before starting.')

    def _lock_id(self, purpose):
        value = ('stream-panel-bot:' + purpose + ':' + self.schema).encode()
        return int.from_bytes(hashlib.sha256(value).digest()[:8], 'big', signed=True)

    def _connect(self, *, autocommit=False):
        # Explicit options override connection-string options: public is never
        # searched and stalled queries/transactions have bounded lifetimes.
        options = (f'-c search_path={self.schema},pg_catalog '
                   '-c lock_timeout=5000 -c statement_timeout=15000 '
                   '-c idle_in_transaction_session_timeout=20000 '
                   r'-c default_transaction_isolation=read\ committed')
        return psycopg.connect(self._url, connect_timeout=10, options=options,
                               row_factory=_row_factory, autocommit=autocommit,
                               keepalives=1, keepalives_idle=2, keepalives_interval=1,
                               keepalives_count=3, tcp_user_timeout=5000)

    def instance_lock_healthy(self):
        """False permanently after this Store loses its instance lease.

        A process watchdog must stop all workers when this becomes false. Before
        acquiring a lease (including schema setup), this returns true.
        """
        return not self._instance_lock_lost.is_set()

    def _check_instance_lock(self):
        if not self.instance_lock_healthy():
            raise RuntimeError('PostgreSQL instance lock was lost. Restart the application.')

    @contextlib.contextmanager
    def connection(self):
        self._check_instance_lock()
        if not self._slots.acquire(timeout=20):
            raise RuntimeError('PostgreSQL state connection capacity reached. Please retry.')
        try:
            stage = 'connect'
            try:
                self._check_instance_lock()
                with self._connect() as connection:
                    stage = 'query'
                    self._check_instance_lock()
                    yield _Connection(connection, self._transaction_lock)
                    stage = 'commit'
                    self._check_instance_lock()
            except psycopg.Error as exc:
                # Connection errors can contain addresses or connection details.
                raise _state_error(exc, stage) from None
        finally:
            self._slots.release()

    def claim_payment(self, order_id, proof):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            order = db.execute('SELECT status FROM orders WHERE id=? FOR UPDATE', (order_id,)).fetchone()
            if not order or order['status'] != 'pending':
                return False
            claimed = db.execute(
                'INSERT INTO payments(network,txid,order_id,proof) VALUES(?,?,?,?) '
                'ON CONFLICT DO NOTHING RETURNING order_id',
                (proof['network'], proof['txid'], order_id, json.dumps(proof)),
            ).fetchone()
            if not claimed:
                db.execute("UPDATE orders SET message='This transaction has already been used.',txid=NULL WHERE id=?", (order_id,))
                return False
            db.execute("UPDATE orders SET status='paid',txid=?,message='Payment confirmed. Preparing your account.' WHERE id=?", (proof['txid'], order_id))
            return True

    @contextlib.contextmanager
    def acquire_instance_lock(self):
        """Hold a monitored session lease, failing closed if it is ever lost."""
        self._check_instance_lock()
        try:
            # This connection is deliberately outside the bounded request slots
            # and never carries an open transaction while the server runs.
            connection = self._connect(autocommit=True)
        except psycopg.Error:
            raise RuntimeError('PostgreSQL instance lock failed. Check database availability.') from None
        stop = threading.Event()
        heartbeat = None
        acquired = False
        try:
            try:
                connection.execute("SET statement_timeout = '5s'")
                acquired = connection.execute('SELECT pg_try_advisory_lock(%s)', (self._instance_lock,)).fetchone()[0]
                if not acquired:
                    raise InstanceLockBusy('Another application instance is already running for this database schema.')
            except psycopg.Error:
                raise RuntimeError('PostgreSQL instance lock failed. Check database availability.') from None
            heartbeat = threading.Thread(target=self._monitor_instance_lock, args=(connection, stop),
                                         name='postgres-instance-lease', daemon=True)
            heartbeat.start()
            yield
        finally:
            stop.set()
            if acquired:
                self._instance_lock_lost.set()
            if heartbeat is not None:
                heartbeat.join(timeout=6)
            # Closing the dedicated session releases its advisory lock. Avoid a
            # final query on a lost connection that could mask the body error.
            with contextlib.suppress(Exception):
                connection.close()

    def _monitor_instance_lock(self, connection, stop):
        lock_id = self._instance_lock & ((1 << 64) - 1)
        try:
            while not stop.wait(1):
                held = connection.execute(
                    "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' "
                    'AND pid=pg_backend_pid() AND classid::bigint=%s AND objid::bigint=%s '
                    'AND objsubid=1 AND granted)',
                    (lock_id >> 32, lock_id & ((1 << 32) - 1)),
                ).fetchone()[0]
                if not held:
                    self._instance_lock_lost.set()
                    return
        except Exception:
            # Never reconnect or reacquire here: another instance may now own
            # the lease. The main watchdog handles process-wide shutdown.
            if not stop.is_set():
                self._instance_lock_lost.set()
