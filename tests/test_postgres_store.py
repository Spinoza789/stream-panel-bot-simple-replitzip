"""PostgreSQL startup checks and opt-in, rollback-only development integration."""
import contextlib
import os
import uuid
import unittest
from unittest.mock import Mock, patch

import psycopg
from cryptography.fernet import Fernet

from streambot.config import load_config
from streambot.bot import TelegramBot
from streambot.postgres_store import PostgresStore, InstanceLockBusy, _Connection, _state_error
from streambot.rates import Rates
from streambot.service import CheckoutService


class PostgresStartupTests(unittest.TestCase):
    def test_connection_failure_reports_stage_without_secret_driver_message(self):
        private_text = 'postgresql://fake-user:fake-password@private-host/database'
        with patch.object(PostgresStore, '_connect', side_effect=psycopg.OperationalError(private_text)):
            with self.assertRaisesRegex(RuntimeError, r'connect failed \(OperationalError, SQLSTATE unavailable\)') as caught:
                PostgresStore('unused-test-connection', Fernet.generate_key())
        self.assertNotIn(private_text, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)

    def test_sqlstate_is_reported_without_provider_error_text(self):
        class Denied(psycopg.Error):
            sqlstate = '42501'
        error = _state_error(Denied('private-provider-message'), 'query')
        self.assertIn('query failed (Denied, SQLSTATE 42501)', str(error))
        self.assertNotIn('private-provider-message', str(error))
        self.assertEqual(error.db_stage,'query')
        self.assertEqual(error.sqlstate,'42501')

    def test_malformed_sqlstate_cannot_leak_error_content(self):
        class InvalidState(psycopg.Error):
            sqlstate = 'private-provider-message'
        error = _state_error(InvalidState('another-private-message'), 'connect')
        self.assertIn('SQLSTATE unavailable', str(error))
        self.assertNotIn('private-provider-message', str(error))

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

    def test_trial_review_recovery_is_owner_scoped_and_atomic(self):
        self.config['panel_writes'] = True
        trial = self.service.create_trial(self.owner)
        credentials = dict(username='test-user', password='test-secret',
                           package_id=str(self.config['trial_package_id']))
        self.store.update(trial['id'], status='review', credentials=credentials)
        self.store.metadata('trial_recheck_after:' + trial['id'], 0)
        self.store.resolve_trial_review(trial['id'], self.owner + 1)
        self.assertEqual(self.store.trial(self.owner)['status'], 'review')
        self.panel.find_account.return_value = None
        self.assertEqual(self.service.retry_trial(self.owner)['status'], 'paid')
        self.store.resolve_trial_review(trial['id'], self.owner, credentials)
        self.assertEqual(self.store.trial(self.owner)['status'], 'paid')
        self.store.update(trial['id'], status='review')
        self.store.metadata('trial_recheck_after:' + trial['id'], 0)
        self.panel.find_account.return_value = credentials
        self.assertEqual(self.service.retry_trial(self.owner)['status'], 'fulfilled')
        self.panel.create_account.assert_not_called()
        self.store.update(trial['id'],status='review')
        self.store.resolve_trial_review(trial['id'],self.owner,clear_credentials=True)
        self.assertEqual(self.store.trial(self.owner)['status'],'paid')
        self.assertIsNone(self.store.trial(self.owner)['credentials'])

    def test_real_session_lease_handoff_and_old_owner_fencing(self):
        first = PostgresStore(os.environ['DATABASE_URL'], Fernet.generate_key())
        second = PostgresStore(os.environ['DATABASE_URL'], Fernet.generate_key())
        # Use an isolated advisory-lock ID, never the live application lease.
        lock_id = int(uuid.uuid4().hex[:15],16)
        first._instance_lock = second._instance_lock = lock_id
        with first.acquire_instance_lock():
            with self.assertRaises(InstanceLockBusy):
                with second.acquire_instance_lock():
                    self.fail('Two instances acquired the same lease')
            self.assertTrue(second.instance_lock_healthy())
            self.assertTrue(first.instance_lock_healthy())
        self.assertFalse(first.instance_lock_healthy())
        with self.assertRaisesRegex(RuntimeError,'lock was lost'):
            with first.connection():
                self.fail('A retired owner accessed application state')
        with second.acquire_instance_lock():
            self.assertTrue(second.instance_lock_healthy())
        self.assertFalse(second.instance_lock_healthy())

    def test_generated_trial_notification_with_mixed_metadata(self):
        self.config['panel_writes']=True
        self.panel.prepare_generation.return_value=dict(
            generation_mode='panel',package_id=str(self.config['trial_package_id']),
            before_ids=[],prepared_at=0,post_attempted=True)
        self.panel.create_account.return_value=dict(username='generated-test-user',password='generated-test-secret')
        trial=self.service.create_trial(self.owner)
        self.service.provision_pending()
        self.assertEqual(self.store.get(trial['id'])['status'],'fulfilled')
        self.store.metadata('test:noninteger','not-an-integer')
        messages=[]
        bot=TelegramBot(self.service,api=lambda method,payload:messages.append((method,payload)) or {'message_id':1})
        bot.notify_trials()
        self.assertTrue(any(method=='sendMessage' and payload['chat_id']==self.owner for method,payload in messages))

    def test_retry_timestamp_cast_ignores_text_and_overflow_metadata(self):
        keys=['test:timestamp:'+uuid.uuid4().hex for _ in range(4)]
        for key,value in zip(keys,['not-an-integer','9'*50,'1794170000','-1']):
            self.store.metadata(key,value)
        with self.store.connection() as db:
            rows=db.execute('SELECT key,CAST(value AS INTEGER) AS retry_at FROM metadata '
                            'WHERE key IN (?,?,?,?)',tuple(keys)).fetchall()
        actual={row['key']:row['retry_at'] for row in rows}
        self.assertIsNone(actual[keys[0]])
        self.assertIsNone(actual[keys[1]])
        self.assertEqual(actual[keys[2]],1794170000)
        self.assertEqual(actual[keys[3]],-1)
