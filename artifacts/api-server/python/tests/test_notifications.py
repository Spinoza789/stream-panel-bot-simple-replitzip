"""No Telegram sends, provider writes or production database access."""
import contextlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from cryptography.fernet import Fernet
from streambot.bot import TelegramBot,TelegramError
from streambot.config import load_config
from streambot.rates import Rates
from streambot.service import CheckoutService
from streambot.store import Store
from streambot.postgres_store import PostgresStore,_Connection


class NotificationScenarios:
    def setup_notifications(self):
        self.clock=1800000000;self.actual={};self.sent=[];self.error=None
        self.config=load_config(env={'APP_MODE':'demo','SUPPORT_ADMIN_ID':'9001'})
        self.config['mode']='live'
        self.service=CheckoutService(self.config,self.store,Mock(),Mock(),Rates(demo=True))
        self.service.resellers.ops.provider=Mock()
        self.service.resellers.ops.provider.summary.side_effect=lambda:self.actual
        self.bot=TelegramBot(self.service,api=self.api);self.n=self.bot.notifications
        for name in ('streambot.notifications.now','streambot.notification_bot.now'):
            p=patch(name,side_effect=lambda:self.clock);p.start();self.addCleanup(p.stop)

    def api(self,method,payload):
        if method=='sendMessage':
            if self.error:raise self.error
            self.sent.append(payload)
        return {}

    def subscription(self,uid=42,kind='paid',days=6,pid='101'):
        f=self.service.resellers.finance
        f.account_status(9001,uid,'active','Notification test fixture')
        member=f.member(uid);expiry=self.clock+int(days*86400)
        with self.store.connection() as db:
            db.execute('INSERT INTO rs_subscriptions(id,reseller_id,provider_id,customer_ref,kind,connections,adult,starts_at,expires_at,status,credentials,confirmed_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       ('sub-'+pid,member['id'],pid,'Test reference',kind,1,0,self.clock-86400,expiry,
                        'active',self.store.seal({'username':'test','password':'not-real'}),self.clock,self.clock))
        self.actual[pid]={'expires_at':expiry,'status':'active' if days>0 else 'expired'}
        return expiry

    def deliveries(self):
        with self.store.connection() as db:return [dict(r) for r in db.execute('SELECT * FROM nt_deliveries ORDER BY created_at,id').fetchall()]

    def campaign(self,uid=42,cid='campaign-one'):
        self.n.preference(uid,'deals',1)
        return self.n.queue_campaign(9001,dict(id=cid,body='Test offer',audience='all',recipients=[uid],expires=self.clock+900))

    def test_expiry_windows_and_durable_deduplication(self):
        expiry=self.subscription()
        for clock in (self.clock,expiry-2*86400,expiry-12*3600,expiry+1):
            self.clock=clock;self.n.next_scan=0;self.n.tick();self.n.next_scan=0;self.n.tick()
        self.assertEqual(len(self.sent),4)
        self.assertTrue(all('not-real' not in m['text'] for m in self.sent))
        self.assertIn('has expired',self.sent[-1]['text'])
        self.n.recover();self.n.next_scan=0;self.n.tick()
        self.assertEqual(len(self.sent),4)

    def test_expired_trials_not_old_trials_or_long_subscriptions(self):
        self.subscription(kind='trial',days=-0.1)
        self.subscription(uid=43,kind='trial',days=-2,pid='102')
        self.subscription(uid=44,days=15,pid='103')
        self.n.tick()
        self.assertEqual([m['chat_id'] for m in self.sent],[42])
        self.assertIn('trial has expired',self.sent[0]['text'])

    def test_renewal_and_removed_ownership_cancel_stale_reminders(self):
        self.subscription()
        records=self.n.sources();self.n.enqueue_expiries(records,self.actual)
        self.actual['101']['expires_at']+=30*86400
        self.n.tick();self.assertEqual(self.sent,[])
        self.actual['101']['expires_at']=self.clock+86400
        self.n.enqueue_expiries(self.n.sources(),self.actual)
        with self.store.connection() as db:db.execute("DELETE FROM rs_subscriptions WHERE provider_id='101'")
        self.n.tick();self.assertEqual(self.sent,[])

    def test_unreachable_provider_never_sends_cached_expiry(self):
        self.subscription();self.n.enqueue_expiries(self.n.sources(),self.actual)
        self.service.resellers.ops.provider.summary.side_effect=RuntimeError('Test outage')
        self.n.tick()
        self.assertEqual(self.sent,[])
        self.assertEqual(self.deliveries()[0]['status'],'pending')

    def test_expiry_opt_out_and_disabled_accounts(self):
        self.subscription()
        self.n.preference(42,'alerts',0);self.n.tick()
        self.assertEqual(self.sent,[])
        self.n.preference(42,'alerts',1);self.actual['101']['status']='disabled'
        self.n.next_scan=0;self.n.tick();self.assertEqual(self.sent,[])

    def test_retail_trial_and_linked_membership_sources(self):
        for uid,kind,pid in ((71,'trial','201'),(72,'paid','202')):
            with self.store.connection() as db:
                db.execute("INSERT INTO orders(id,token_hash,kind,telegram_id,plan_json,asset_json,amount_units,created_at,expires_at,status,credentials) "
                           "VALUES(?,?,?,?,?,?,'1',?,?,'fulfilled',?)",
                           ('order-'+pid,'token-'+pid,kind,uid if kind=='trial' else None,'{}','{}',self.clock-1,self.clock+1,
                            self.store.seal({'panel_id':pid,'username':'test','password':'not-real'})))
                if kind=='paid':db.execute('INSERT INTO account_links(telegram_id,order_id) VALUES(?,?)',(uid,'order-'+pid))
            self.actual[pid]={'expires_at':self.clock+(-1 if kind=='trial' else 86400),'status':'active'}
        self.n.tick()
        self.assertEqual({m['chat_id'] for m in self.sent},{71,72})

    def test_reminders_carry_extend_and_renew_buttons(self):
        self.subscription()
        with self.store.connection() as db:
            db.execute("INSERT INTO orders(id,token_hash,kind,telegram_id,plan_json,asset_json,amount_units,created_at,expires_at,status,credentials) "
                       "VALUES(?,?,?,?,?,?,'1',?,?,'fulfilled',?)",
                       ('order-202','token-202','paid',None,'{}','{}',self.clock-1,self.clock+1,self.store.seal({'panel_id':'202','username':'test','password':'not-real'})))
            db.execute('INSERT INTO account_links(telegram_id,order_id) VALUES(?,?)',(72,'order-202'))
        self.actual['202']={'expires_at':self.clock+86400,'status':'active'}
        self.n.tick()
        by_chat={m['chat_id']:m for m in self.sent}
        reseller=[b['callback_data'] for row in by_chat[42]['reply_markup']['inline_keyboard'] for b in row]
        self.assertIn('rs:extendnow:sub-101:1',reseller)
        self.assertIn('rs:detail:sub-101',reseller)
        retail=[b['callback_data'] for row in by_chat[72]['reply_markup']['inline_keyboard'] for b in row]
        self.assertIn('pay:renew:order-202',retail)
        self.assertIn('Nothing has been renewed or charged yet.',by_chat[72]['text'])

    def test_marketing_requires_opt_in_and_administrator(self):
        self.n.contact(42)
        self.assertEqual(self.n.eligible('all'),[])
        with self.assertRaises(Exception):
            self.n.queue_campaign(42,dict(id='bad',body='x',audience='all',recipients=[42],expires=self.clock+900))
        self.n.message(42,'/announce','Unauthorised offer')
        self.assertIsNone(self.n.draft(42))
        self.assertEqual(self.deliveries(),[])

    def test_preview_confirm_snapshot_and_repeated_confirm(self):
        self.n.preference(42,'deals',1)
        self.n.message(9001,'/announce','A test deal')
        draft=self.n.draft(9001);cid=draft['id']
        self.n.callback(9001,'nt:audience:'+cid+':all')
        preview=self.n.draft(9001)['preview_id']
        self.n.preference(43,'deals',1)
        self.assertEqual(self.deliveries(),[])
        self.n.callback(9001,'nt:send:'+cid+':'+preview)
        self.n.callback(9001,'nt:send:'+cid+':'+preview)
        self.sent.clear();self.n.tick();self.n.tick()
        self.assertEqual([m['chat_id'] for m in self.sent],[42])
        self.assertEqual(self.n.campaigns(9001)[0]['counts'],{'sent':1})

    def test_opt_out_after_confirmation_and_campaign_cancellation(self):
        cid=self.campaign();self.n.preference(42,'deals',0);self.n.tick()
        self.assertEqual(self.sent,[])
        cid=self.campaign(cid='second');self.n.cancel(9001,cid);self.n.tick()
        self.assertEqual(self.sent,[])

    def test_old_audience_confirmation_cannot_send_to_a_new_audience(self):
        self.n.preference(42,'deals',1)
        self.n.message(9001,'/announce','Audience safety test')
        cid=self.n.draft(9001)['id']
        self.n.callback(9001,'nt:audience:'+cid+':retail')
        old=self.n.draft(9001)['preview_id']
        self.n.callback(9001,'nt:audience:'+cid+':all')
        self.n.callback(9001,'nt:send:'+cid+':'+old)
        self.assertEqual(self.deliveries(),[])

    def test_batch_limit_and_same_chat_delivery_spacing(self):
        for uid in range(42,48):self.n.preference(uid,'deals',1)
        self.n.queue_campaign(9001,dict(id='bulk',body='Bulk test',audience='all',recipients=list(range(42,48)),expires=self.clock+900))
        self.n.tick();self.assertEqual(len(self.sent),5);self.assertTrue(self.n.backlog)
        self.n.tick();self.assertEqual(len(self.sent),6)
        self.campaign(cid='second');self.n.tick()
        self.assertEqual(len(self.sent),6)
        self.clock+=2;self.n.tick();self.assertEqual(len(self.sent),7)
    def test_blocked_chats_stop_future_attempts_until_private_contact(self):
        self.campaign();self.error=TelegramError(403);self.n.tick()
        self.assertEqual(self.n.preferences(42)['blocked'],1)
        self.error=None;self.campaign(cid='second');self.n.tick()
        self.assertEqual(self.sent,[])
        self.n.contact(42,incoming=True);self.campaign(cid='third');self.n.tick()
        self.assertEqual(len(self.sent),1)

    def test_telegram_rate_limit_is_persisted_and_retried(self):
        self.campaign();self.error=TelegramError(429,retry_after=31);self.n.tick()
        self.assertEqual(self.deliveries()[0]['status'],'retry')
        self.error=None;self.n.tick();self.assertEqual(self.sent,[])
        self.clock+=32;self.n.tick();self.assertEqual(len(self.sent),1)

    def test_network_uncertainty_and_crash_are_not_blindly_replayed(self):
        self.campaign();self.error=TelegramError();self.n.tick()
        self.assertEqual(self.deliveries()[0]['status'],'uncertain')
        self.error=None;self.n.tick();self.assertEqual(self.sent,[])
        self.campaign(cid='second')
        with self.store.connection() as db:db.execute("UPDATE nt_deliveries SET status='sending' WHERE status='pending'")
        self.n.recover();self.n.tick();self.assertEqual(self.sent,[])

    def test_stop_persists_and_group_callbacks_cannot_change_preferences(self):
        self.n.preference(42,'deals',1);self.n.message(42,'/stop','')
        self.n.contact(42,incoming=True)
        self.assertEqual((self.n.preferences(42)['alerts'],self.n.preferences(42)['deals']),(0,0))
        self.bot.handle({'callback_query':{'id':'group','from':{'id':42},'data':'nt:deals:1',
                                         'message':{'chat':{'type':'group','id':-100}}}})
        self.assertEqual(self.n.preferences(42)['deals'],0)

    def test_recipient_filters_exclude_suspended_resellers(self):
        self.subscription();self.n.preference(42,'deals',1);self.n.preference(43,'deals',1)
        self.assertEqual(self.n.eligible('retail'),[43])
        self.assertEqual(self.n.eligible('resellers'),[42])
        self.service.resellers.finance.account_status(9001,42,'suspended','Test suspension')
        self.assertEqual(self.n.eligible('all'),[43])


class SQLiteNotificationTests(NotificationScenarios,unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=Store(Path(temp.name)/'notifications.db',Fernet.generate_key())
        self.setup_notifications()


@unittest.skipUnless(os.getenv('STREAMBOT_TEST_POSTGRES')=='true' and not os.getenv('REPLIT_DEPLOYMENT'),'Development PostgreSQL opt-in only')
class PostgreSQLNotificationTests(NotificationScenarios,unittest.TestCase):
    def setUp(self):
        self.store=PostgresStore(os.environ['DATABASE_URL'],Fernet.generate_key())
        db=self.store._connect();db.execute('SELECT 1')
        self.addCleanup(db.close);self.addCleanup(db.rollback)
        @contextlib.contextmanager
        def connection():
            with db.transaction():yield _Connection(db,self.store._transaction_lock)
        self.store.connection=connection
        self.setup_notifications()
