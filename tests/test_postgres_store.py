"""PostgreSQL startup checks and opt-in, rollback-only development integration."""
import contextlib
import os
import uuid
import unittest
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet

from streambot.config import load_config
from streambot.postgres_store import PostgresStore, _Connection
from streambot.rates import Rates
from streambot.service import CheckoutService


class PostgresStartupTests(unittest.TestCase):
    def connection(self, db):
        @contextlib.contextmanager
        def connect(_store):
            yield db
        return connect

    def test_constructor_only_checks_schema_without_ddl_or_writes(self):
        db = Mock()
        db.execute.return_value.fetchone.return_value = ('existing_table',)
        with patch.object(PostgresStore, 'connection', self.connection(db)):
            PostgresStore('unused-test-connection', Fernet.generate_key())
        self.assertEqual(db.execute.call_count, 6)
        self.assertTrue(all(call.args[0] == 'SELECT to_regclass(?)'
                            for call in db.execute.call_args_list))

    def test_missing_schema_fails_closed_without_creating_it(self):
        db = Mock()
        db.execute.return_value.fetchone.return_value = (None,)
        with patch.object(PostgresStore, 'connection', self.connection(db)):
            with self.assertRaisesRegex(RuntimeError, 'publish the schema'):
                PostgresStore('unused-test-connection', Fernet.generate_key())
        self.assertEqual(db.execute.call_args.args[0], 'SELECT to_regclass(?)')


@unittest.skipUnless(
    os.environ.get('STREAMBOT_TEST_POSTGRES') == 'true' and not os.environ.get('REPLIT_DEPLOYMENT'),
    'Opt in against the development database with STREAMBOT_TEST_POSTGRES=true.',
)
class PostgresIntegrationTests(unittest.TestCase):
    def setUp(self):
        # Only the runtime-managed development connection is used, never a copied
        # production URL. All test records are rolled back; no real panel/node calls.
        self.store = PostgresStore(os.environ['DATABASE_URL'], Fernet.generate_key())
        self.db = self.store._connect()
        self.db.execute('SELECT 1')  # outer transaction owns all test writes
        self.addCleanup(self.db.close)
        self.addCleanup(self.db.rollback)

        @contextlib.contextmanager
        def transactional_connection():
            with self.db.transaction():
                yield _Connection(self.db, self.store._transaction_lock)
        self.store.connection = transactional_connection
        self.config = load_config(env={'APP_MODE': 'demo'})
        self.config['mode'] = 'live'
        self.verifier, self.panel = Mock(), Mock()
        self.service = CheckoutService(self.config, self.store, self.verifier,
                                       self.panel, rates=Rates(demo=True))
        self.owner = int(uuid.uuid4().hex[:12], 16) + 10**12

    def test_owned_quotes_txid_replay_protection_and_delivery_receipts(self):
        quote = self.service.create_order('adult-month-1', 'usdc-ethereum',
                                         owner_telegram_id=self.owner,
                                         request_key='test:' + uuid.uuid4().hex)
        order = self.store.get(quote['order']['id'])
        repeat = self.service.create_order('adult-month-1', 'usdc-ethereum',
                                          owner_telegram_id=self.owner,
                                          request_key='test:' + uuid.uuid4().hex)
        self.assertEqual(repeat['order']['id'], order['id'])
        self.assertIsNone(self.store.owned_order(self.owner + 1, order['id']))
        self.assertEqual(self.store.telegram_orders(self.owner)[0]['id'], order['id'])

        txid = '0x' + uuid.uuid4().hex * 2
        self.service.submit_telegram_tx(self.owner, order['id'], txid)
        self.verifier.verify.return_value = dict(
            network='ethereum', txid=txid, amount_units=int(order['amount_units']),
            block_time=order['created_at'], confirmations=12,
        )
        self.service.verify_order(order_id=order['id'])
        paid = self.store.get(order['id'])
        self.assertEqual(paid['status'], 'paid')

        # A late TXID submission cannot overwrite a payment already confirmed.
        self.store.submit_tx(order['id'], '0x' + 'b' * 64)
        self.assertEqual(self.store.get(order['id'])['txid'], txid)
        self.assertFalse(self.store.claim_payment('missing-order', self.verifier.verify.return_value))

        receipt = paid['status'] + ':' + paid['message']
        self.store.metadata('tg_notice:' + order['id'], receipt)
        candidates = self.store.telegram_orders(limit=1000)
        self.assertNotIn(order['id'], [candidate['id'] for candidate in candidates])
        self.panel.create_account.assert_not_called()
