"""No live provider writes: financial invariants and Telegram ownership regression checks."""
import contextlib
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

from cryptography.fernet import Fernet

from streambot.bot import TelegramBot
from streambot.config import load_config
from streambot.panel import PanelError,ProvisioningUncertain
from streambot.postgres_store import PostgresStore,_Connection
from streambot.rates import Rates
from streambot.reseller_ledger import now
from streambot.reseller_provider import provider_time
from streambot.service import CheckoutError,CheckoutService
from streambot.store import Store


class Provider:
    """Deliberate test double injected into the live service; no network methods."""
    def __init__(self):
        self.accounts={};self.calls=[];self.by_operation={}
        self.prepare_error=False;self.definite_error=False;self.timeout=False;self.offline=False
    def package(self,months,connections,adult):return f'{months}-{connections}-{int(adult)}'
    def read(self,pid):
        if self.offline:raise PanelError('Test provider offline')
        result=dict(self.accounts[pid])
        result['status']='active' if result['expires_at']>now() else 'expired'
        return result
    def preview_extension(self,record,months):
        current=self.read(record['provider_id'])
        return dict(previous_expiry=current['expires_at'],expected_expiry=max(now(),current['expires_at'])+months*30*86400)
    def prepare(self,op,record=None):
        if self.prepare_error:raise PanelError('Rejected before POST')
        return dict(oid=op['id'],record=record,expected_expiry=max(now(),record['expires_at'] if record else 0)+(86400 if op['months']==0 else op['months']*30*86400))
    def execute(self,op,context):
        if self.definite_error:raise PanelError('Definite pre-submit rejection')
        self.calls.append(op['id'])
        record=context['record'];pid=record['provider_id'] if record else str(len(self.accounts)+1)
        credentials=self.accounts[pid]['credentials'] if record else dict(username='test-user-'+pid,password='test-password-'+pid)
        account=dict(provider_id=pid,credentials=credentials,expires_at=context['expected_expiry'],status='active',
                     connections=op['connections'],adult=op['adult'])
        self.accounts[pid]=account;self.by_operation[op['id']]=pid
        if self.timeout:raise ProvisioningUncertain('Submission timed out')
        return account
    def reconcile(self,op,context,provider_id=None):
        pid=self.by_operation[op['id']]
        if provider_id and provider_id!=pid:raise PanelError('Wrong provider account')
        return self.read(pid)


class Scenarios:
    def setup_service(self):
        self.config=load_config(env={'APP_MODE':'demo','SUPPORT_ADMIN_ID':'9001'})
        self.config.update(mode='live',panel_writes=True)
        self.service=CheckoutService(self.config,self.store,Mock(),Mock(),Rates(demo=True))
        self.r=self.service.resellers;self.f=self.r.finance;self.o=self.r.ops
        self.provider=Provider();self.o.provider=self.provider
        for uid in (42,43):
            self.f.register(uid,'test_username')
            self.f.account_status(9001,uid,'active','Test approval')
        self.calls=[]
        self.bot=TelegramBot(self.service,api=lambda method,payload:self.calls.append((method,payload)) or {'message_id':1})
        self.message_id=0

    def fund(self,amount=100,uid=42):
        return self.f.adjust(9001,uid,amount,'Test funding','fund-'+str(uid)+'-'+str(amount))
    def preview(self,kind='create',months=1,connections=1,adult=False,uid=42,target=None,ref='Test customer'):
        return self.o.preview(uid,kind,months,connections,adult,ref,target)
    def reserve(self,nonce='request-0001',**kwargs):
        uid=kwargs.get('uid',42)
        return self.o.reserve(uid,nonce,self.preview(**kwargs))
    def create(self,nonce='request-0001',**kwargs):
        op=self.reserve(nonce,**kwargs);self.o.process()
        return self.o.operation(kwargs.get('uid',42),op['id'])
    def message(self,uid,text):
        self.message_id+=1
        self.bot.handle({'message':{'message_id':self.message_id,'from':{'id':uid,'username':'mutable_name'},
                                   'chat':{'id':uid,'type':'private'},'text':text}})
    def click(self,uid,action):
        self.message_id+=1
        self.bot.handle({'callback_query':{'id':'click-'+str(self.message_id),'from':{'id':uid},
                        'data':action,'message':{'chat':{'id':uid,'type':'private'}}}})

    def sent_to(self,uid):
        return [p for m,p in self.calls if m=='sendMessage' and p.get('chat_id')==uid]

    def test_anyone_becomes_a_reseller_by_buying_credits(self):
        self.click(77,'rs:home')
        screen=self.sent_to(77)[-1]
        self.assertIn('BECOME A RESELLER',screen['text'])
        self.assertIn('WHAT CREDITS BUY',screen['text'])
        self.assertIn('12 months: 12 cr (1 device) · 15 cr (2 devices) · 20 cr (3 devices)',screen['text'])
        self.assertIn('£100 → 34 credits',screen['text'])
        self.assertEqual(screen['reply_markup']['inline_keyboard'][0][0]['callback_data'],'rs:packages')
        self.assertIsNone(self.f.member(77))  # looking never creates an account
        self.click(77,'rs:packages')
        self.assertEqual(self.f.member(77)['status'],'pending')
        packs=self.sent_to(77)[-1]
        self.assertIn('goes live',packs['text'])
        self.assertEqual(packs['reply_markup']['inline_keyboard'][0][0]['callback_data'],'rs:package:100')
        self.assertEqual(len(self.sent_to(9001)),0)  # nobody has to approve anything
        # an unpaid "reseller" is still an ordinary customer: retail trial and plans stay open
        self.assertEqual(self.service.create_trial(77)['status'],'paid')
        order=self.f.quote_purchase(77,'100','usdc-ethereum','join-77')
        self.store.claim_payment(order['id'],dict(network='ethereum',txid='join-tx',amount_units=int(order['amount_units']),block_time=now(),confirmations=12))
        self.f.grant(order['id'])
        member=self.f.member(77)
        self.assertEqual((member['status'],member['balance']),('active',34))
        self.click(77,'rs:home')
        dashboard=self.sent_to(77)[-1]
        self.assertIn('RESELLER DASHBOARD',dashboard['text'])
        self.assertIn('Credits: 34 available',dashboard['text'])
        buttons={b['callback_data'] for row in dashboard['reply_markup']['inline_keyboard'] for b in row}
        self.assertTrue({'rs:create','rs:trial','rs:packages','rs:balance','rs:list:active:0','rs:history:0','rs:web','rs:guide'}<=buttons)
        self.message(9001,'/rssuspend 77 test suspension')
        self.assertIn('suspended',self.sent_to(77)[-1]['text'])
        with self.assertRaises(CheckoutError):self.f.quote_purchase(77,'100','usdc-ethereum','join-77-again')
        self.message(9001,'/rsapprove 77 reinstated')
        self.assertIn('approved',self.sent_to(77)[-1]['text'])

    def test_credit_guide_is_available_from_the_dashboard(self):
        self.click(42,'rs:guide')
        text=self.sent_to(42)[-1]['text']
        self.assertIn('1 credit = 1 month of TV on 1 device',text)
        self.assertIn('Example: £100 = 34 credits = 2 full-year subscriptions + 10 months to spare.',text)

    def test_dashboard_counts_follow_subscriptions(self):
        self.fund(50)
        self.create('op-dash-1',months=1)
        self.create('op-dash-2',kind='trial')
        counts=self.o.counts(42)
        self.assertEqual((counts['active'],counts['trials'],counts['total']),(1,1,2))
        self.click(42,'rs:home')
        self.assertIn('1 active',self.sent_to(42)[-1]['text'])
        self.assertIn('1 trial running',self.sent_to(42)[-1]['text'])

    def test_initial_packages_and_complete_cost_matrix(self):
        self.assertEqual([(p['price_pence'],p['credits']) for p in self.f.packages()],[(10000,34),(20000,75),(30000,129),(40000,192)])
        for months,costs in ((1,(1,2,3)),(3,(3,4,5)),(6,(6,7,8)),(9,(9,10,11)),(12,(12,15,20))):
            for n,cost in enumerate(costs,1):
                for adult in (False,True):self.assertEqual(self.preview(months=months,connections=n,adult=adult)['cost'],cost)

    def test_verified_packages_add_once_and_accumulate_with_immutable_snapshots(self):
        balance=0
        for pid,credits in (('100',34),('200',75),('300',129),('400',192)):
            order=self.f.quote_purchase(42,pid,'usdc-ethereum','buy-'+pid)
            with self.assertRaises(CheckoutError):self.f.grant(order['id'])
            self.assertEqual(self.f.member(42)['balance'],balance)
            self.store.claim_payment(order['id'],dict(network='ethereum',txid='test-'+pid,amount_units=int(order['amount_units']),block_time=now(),confirmations=12))
            self.f.grant(order['id']);self.f.grant(order['id'])
            balance+=credits
            self.assertEqual(self.f.member(42)['balance'],balance)
        self.f.configure(9001,'package',('100',15000,999,1),'Updated future pricing')
        with self.store.connection() as db:
            original=db.execute('SELECT amount_pence,credits FROM rs_purchases WHERE credits=?',(34,)).fetchone()
        self.assertEqual((original[0],original[1]),(10000,34))

    def test_manual_payment_requires_admin_reason_and_unique_reference(self):
        first=self.f.quote_purchase(42,'100','usdc-ethereum','first-purchase')
        second=self.f.quote_purchase(43,'100','usdc-ethereum','second-purchase')
        with self.assertRaises(CheckoutError):self.f.grant(first['id'],actor=42,reference='bank:one',reason='Cannot approve self')
        with self.assertRaises(CheckoutError):self.f.grant(first['id'],actor=9001,reference='bank:one',reason='')
        self.f.grant(first['id'],actor=9001,reference='bank:one',reason='Bank payment checked')
        self.f.grant(first['id'],actor=9001,reference='bank:one',reason='Duplicate notification')
        with self.assertRaises(CheckoutError):self.f.grant(second['id'],actor=9001,reference='BANK:ONE',reason='Duplicate receipt')
        self.assertEqual(self.f.member(42)['balance'],34)
        self.assertEqual(self.f.member(43)['balance'],0)

    def test_ive_paid_button_and_txid_never_grant_credits(self):
        order=self.f.quote_purchase(42,'100','usdc-ethereum','not-verified')
        self.click(42,'pay:tx:'+order['id'])
        self.message(42,'0x'+'a'*64)
        self.assertEqual(self.f.member(42)['balance'],0)
        self.assertEqual(self.store.get(order['id'])['status'],'pending')

    def test_account_worker_grants_verified_credits_without_creating_a_subscription(self):
        order=self.f.quote_purchase(42,'100','usdc-ethereum','worker-credit-purchase')
        self.store.claim_payment(order['id'],dict(network='ethereum',txid='worker-credit-proof',
                                amount_units=int(order['amount_units']),block_time=now(),confirmations=12))
        self.service.provision_pending();self.service.provision_pending()
        self.assertEqual(self.f.member(42)['balance'],34)
        self.assertEqual(self.store.get(order['id'])['status'],'fulfilled')
        self.assertEqual(self.provider.calls,[])
        self.assertIn('34 credits added',self.bot.checkout.order_text(self.service.public(self.store.get(order['id']))))

    def test_success_reserves_then_deducts_once_and_encrypts_credentials(self):
        self.fund(34)
        preview=self.preview(months=12,connections=3,adult=True)
        op=self.o.reserve(42,'stable-request',preview)
        self.assertEqual((self.f.member(42)['balance'],self.f.member(42)['reserved'],self.f.member(42)['available']),(34,20,14))
        self.assertEqual(self.o.reserve(42,'stable-request',preview)['id'],op['id'])
        self.o.process();self.o.process()
        self.assertEqual((self.f.member(42)['balance'],self.f.member(42)['reserved']),(14,0))
        done=self.o.operation(42,op['id'])
        record=self.o.owned(42,done['result_id'])
        self.assertNotIn('test-password',record['credentials'])
        self.assertEqual(self.store.unseal(record['credentials'])['password'],'test-password-1')
        self.o.complete(op['id'],self.provider.accounts['1'])
        self.assertEqual(self.f.member(42)['balance'],14)
        self.assertEqual(len(self.provider.calls),1)

    def test_insufficient_credits_and_reserved_credit_removal_are_blocked(self):
        self.fund(3)
        op=self.reserve(months=1,connections=3)
        with self.assertRaises(CheckoutError):self.reserve('another-request')
        with self.assertRaises(CheckoutError):self.f.adjust(9001,42,-1,'Cannot spend held credits','withdraw')
        self.assertEqual(self.o.operation(42,op['id'])['status'],'queued')
        self.assertEqual(self.f.member(42)['reserved'],3)

    def test_definite_preparation_and_submission_failures_release_not_charge(self):
        self.fund(3)
        self.provider.prepare_error=True
        first=self.create('prepare-failure')
        self.assertEqual((first['status'],self.f.member(42)['balance'],self.f.member(42)['reserved']),('failed',3,0))
        self.provider.prepare_error=False;self.provider.definite_error=True
        second=self.create('definite-failure')
        self.assertEqual((second['status'],self.f.member(42)['balance'],self.f.member(42)['reserved']),('failed',3,0))

    def test_uncertain_success_holds_until_read_only_reconciliation(self):
        self.fund(3);self.provider.timeout=True
        op=self.create('uncertain-request')
        self.assertEqual(op['status'],'uncertain')
        self.assertEqual((self.f.member(42)['balance'],self.f.member(42)['reserved']),(3,1))
        self.o.process();self.assertEqual(len(self.provider.calls),1)
        with self.assertRaises(CheckoutError):self.o.reconcile(43,op['id'])
        self.o.reconcile(9001,op['id'])
        self.assertEqual(self.o.operation(42,op['id'])['status'],'succeeded')
        self.assertEqual((self.f.member(42)['balance'],self.f.member(42)['reserved']),(2,0))
        self.assertEqual(len(self.provider.calls),1)

    def test_new_confirmation_cannot_replace_an_uncertain_customer_request(self):
        self.fund(3);self.provider.timeout=True
        op=self.create('uncertain-customer')
        with self.assertRaises(CheckoutError):self.reserve('replacement-request')
        another=self.reserve('another-customer',ref='Different customer')
        self.assertNotEqual(op['id'],another['id'])
        self.assertEqual(self.f.member(42)['reserved'],2)

    def test_database_constraints_and_actual_cost_snapshot_protect_balances(self):
        self.fund(10);op=self.reserve(months=6)
        self.f.configure(9001,'cost',(6,1,20),'Future pricing change')
        member=self.f.member(42)
        with self.assertRaises(Exception):
            with self.store.connection() as db:
                db.execute('UPDATE rs_accounts SET balance=-1 WHERE reseller_id=?',(member['id'],))
        with self.assertRaises(Exception):
            with self.store.connection() as db:
                db.execute('UPDATE rs_accounts SET reserved=balance+1 WHERE reseller_id=?',(member['id'],))
        self.o.process()
        self.assertEqual(self.f.member(42)['balance'],4)
        self.assertEqual(self.o.operation(42,op['id'])['credit_cost'],6)

    def test_restart_never_requeues_a_submitted_uncertain_post(self):
        self.fund(3);op=self.reserve()
        with self.store.connection() as db:
            db.execute("UPDATE rs_operations SET status='processing',provider_context=? WHERE id=?",
                       (self.store.seal({'test':'submission-intent'}),op['id']))
        self.o.recover();self.o.process()
        self.assertEqual(self.o.operation(42,op['id'])['status'],'uncertain')
        self.assertEqual(self.f.member(42)['reserved'],1)
        self.assertEqual(self.provider.calls,[])

    def test_suspended_accounts_cannot_buy_create_trial_extend_or_use_stale_buttons(self):
        self.fund()
        record=self.create()['result_id']
        self.f.account_status(9001,42,'suspended','Test suspension')
        with self.assertRaises(CheckoutError):self.f.quote_purchase(42,'100','usdc-ethereum','blocked-buy')
        for kind in ('create','trial','extend'):
            with self.assertRaises(CheckoutError):self.preview(kind=kind,target=record)
        self.click(42,'rs:create');self.click(42,'plan:duration:1')
        self.assertIn('suspended',self.calls[-1][1]['text'])
        self.assertEqual(len(self.provider.calls),1)

    def test_suspension_pauses_queued_work_without_losing_reservations(self):
        self.fund();op=self.reserve()
        self.f.account_status(9001,42,'suspended','Pending work paused')
        self.o.process();self.assertEqual(self.provider.calls,[])
        self.assertEqual(self.f.member(42)['reserved'],1)
        self.f.account_status(9001,42,'active','Resume approved work');self.o.process()
        self.assertEqual(self.o.operation(42,op['id'])['status'],'succeeded')

    def test_ownership_is_enforced_for_details_operations_extensions_search_and_callbacks(self):
        self.fund();op=self.create()
        for call in (lambda:self.o.owned(43,op['result_id']),lambda:self.o.operation(43,op['id']),
                     lambda:self.o.refresh(43,op['result_id']),lambda:self.preview(kind='extend',uid=43,target=op['result_id'])):
            with self.assertRaises(CheckoutError):call()
        self.assertEqual(self.o.records(43),[])
        self.click(43,'rs:detail:'+op['result_id'])
        self.assertNotIn('test-password',self.calls[-1][1]['text'])
        self.click(43,'rs:adminlist:accounts:0')
        self.assertIn('Administrator access required',self.calls[-1][1]['text'])

    def test_trial_limits_count_pending_and_active_then_preserve_expired_history(self):
        first=self.reserve(kind='trial',adult=True)
        with self.assertRaises(CheckoutError):self.reserve('second-trial',kind='trial')
        self.o.process()
        self.assertEqual(self.f.member(42)['balance'],0)
        result=self.o.operation(42,first['id'])
        self.provider.accounts['1']['expires_at']=now()-10
        self.o.refresh(42,result['result_id'])
        with self.assertRaises(CheckoutError):self.reserve('daily-blocked',kind='trial')
        self.f.configure(9001,'trials',(2,1),'Allow two rolling-day trials')
        second=self.create('allowed-second-trial',kind='trial',adult=False)
        self.assertEqual(second['status'],'succeeded')
        self.assertEqual(len(self.o.records(42,'trials')),2)
        self.assertEqual(self.f.member(42)['balance'],0)
        with self.assertRaises(CheckoutError):self.reserve('third-trial',kind='trial')

    def test_extension_preserves_profile_records_cost_and_converts_trial(self):
        self.fund(100)
        trial=self.create(kind='trial',adult=True)
        record=self.o.owned(42,trial['result_id'])
        old=record['expires_at']
        extension=self.create('extend-request',kind='extend',months=12,target=record['id'])
        updated=self.o.owned(42,record['id'])
        self.assertEqual((updated['connections'],updated['adult'],updated['kind']),(1,1,'paid'))
        self.assertGreater(updated['expires_at'],old)
        self.assertEqual(self.f.member(42)['balance'],88)
        _,_,history=self.o.refresh(42,record['id'])
        self.assertEqual((history[0]['months'],history[0]['credits'],history[0]['previous_expiry']),(12,12,old))
        self.assertEqual(extension['status'],'succeeded')

    def test_expired_extension_starts_from_provider_current_time(self):
        self.fund();op=self.create()
        self.provider.accounts['1']['expires_at']=now()-86400*30
        record,_,_=self.o.refresh(42,op['result_id'])
        before=now();extension=self.create('expired-extension',kind='extend',months=1,target=record['id'])
        self.assertGreaterEqual(self.o.owned(42,record['id'])['expires_at'],before+30*86400)
        self.assertEqual(extension['status'],'succeeded')

    def test_pending_extension_and_changed_prices_do_not_double_reserve(self):
        self.fund();op=self.create()
        preview=self.preview(kind='extend',months=3,target=op['result_id'])
        self.o.reserve(42,'one-extension',preview)
        with self.assertRaises(CheckoutError):self.o.reserve(42,'another-extension',preview)
        pending=self.preview(months=6)
        self.f.configure(9001,'cost',(6,1,20),'New future cost')
        with self.assertRaises(CheckoutError):self.o.reserve(42,'old-price-request',pending)

    def test_refresh_after_provider_success_before_commit_does_not_lose_extension_charge(self):
        self.fund(10)
        created=self.create()
        record=self.o.owned(42,created['result_id'])
        op=self.reserve('refresh-race-extension',kind='extend',months=1,target=record['id'])
        context=self.provider.prepare(op,record)
        with self.store.connection() as db:
            db.execute("UPDATE rs_operations SET status='processing',provider_context=? WHERE id=?",(self.store.seal(context),op['id']))
        confirmed=self.provider.execute(op,context)
        self.o.refresh(42,record['id'])
        self.o.complete(op['id'],confirmed)
        self.assertEqual(self.o.operation(42,op['id'])['status'],'succeeded')
        self.assertEqual(self.f.member(42)['balance'],8)
        _,_,history=self.o.refresh(42,record['id'])
        self.assertEqual(history[0]['previous_expiry'],record['expires_at'])

    def test_provider_down_shows_last_confirmed_and_never_reserves_extension(self):
        self.fund();op=self.create()
        self.provider.offline=True
        record,warning,_=self.o.refresh(42,op['result_id'])
        self.assertIn('last-confirmed',warning)
        self.assertEqual(record['credentials']['username'],'test-user-1')
        with self.assertRaises(CheckoutError):self.preview(kind='extend',target=op['result_id'])
        self.assertEqual(self.f.member(42)['reserved'],0)

    def test_reseller_flow_uses_persistent_confirmation_and_sends_download_details(self):
        self.fund(3)
        for action in ('rs:create','rs:duration:1','rs:connections:2','rs:adult:0','rs:skip'):
            self.click(42,action)
        confirmation=self.calls[-1][1]
        self.assertIn('Remaining after purchase: 1',confirmation['text'])
        action=confirmation['reply_markup']['inline_keyboard'][0][0]['callback_data']
        self.click(42,action)
        self.bot=TelegramBot(self.service,api=lambda method,payload:self.calls.append((method,payload)) or {'message_id':1})
        self.click(42,action)
        self.o.process();self.bot.reseller.notify()
        delivered=[p for method,p in self.calls if method=='sendMessage' and 'test-password' in p['text']]
        self.assertEqual(len(delivered),1)
        self.assertIn('APP DOWNLOAD CODES',delivered[0]['text'])
        self.assertIn('Provider-confirmed expiry',delivered[0]['text'])
        self.assertEqual(self.f.member(42)['balance'],1)
        sent=len(self.calls);self.bot.reseller.notify();self.assertEqual(len(self.calls),sent)

    def test_admin_history_is_shown_to_admin_not_sent_to_customer(self):
        self.fund()
        self.message(9001,'/rshistory 42')
        sends=[payload for method,payload in self.calls if method=='sendMessage']
        self.assertTrue(sends)
        self.assertTrue(all(payload['chat_id']==9001 for payload in sends))


class SQLiteTests(Scenarios,unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.key=Fernet.generate_key()
        self.store=Store(Path(temp.name)/'resellers.db',self.key)
        self.setup_service()

    def test_simultaneous_requests_cannot_overspend(self):
        self.fund(1);preview=self.preview()
        def reserve(index):
            try:return self.o.reserve(42,'concurrent-'+str(index),dict(preview,customer_ref='Customer '+str(index)))['id']
            except CheckoutError:return None
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(reserve,range(8)))
        self.assertEqual(len([r for r in results if r]),1)
        self.assertEqual((self.f.member(42)['available'],self.f.member(42)['reserved']),(0,1))

    def test_financial_rows_and_encrypted_access_survive_reopening(self):
        self.fund();op=self.create()
        reopened=Store(self.store.path,self.key)
        service=CheckoutService(self.config,reopened,Mock(),Mock(),Rates(demo=True))
        self.assertEqual(service.resellers.finance.member(42)['balance'],99)
        self.assertEqual(service.resellers.ops.owned(42,op['result_id'])['provider_id'],'1')

    def test_search_pagination_and_filters_stay_owner_scoped(self):
        self.fund()
        for index in range(12):self.reserve('pagination-'+str(index),ref='Customer '+str(index))
        for _ in range(6):self.o.process()
        self.assertEqual(len(self.o.records(42,'all',0)),11)
        self.assertEqual(len(self.o.records(42,'all',1)),2)
        self.assertEqual(len(self.o.records(42,search='test-user-12')),1)
        self.assertEqual(self.o.records(43,search='Customer'),[])
        self.assertEqual(self.o.records(42,'trials'),[])

    def test_active_expiring_expired_and_trial_filters_use_confirmed_expiry(self):
        self.fund()
        for index,days in enumerate((5,10,-1)):
            op=self.create('filter-'+str(index),ref='Filter customer '+str(index))
            record=self.o.owned(42,op['result_id'])
            self.provider.accounts[record['provider_id']]['expires_at']=now()+days*86400
            self.o.refresh(42,record['id'])
        self.create('filter-trial',kind='trial')
        self.assertEqual(len(self.o.records(42,'active')),2)
        self.assertEqual(len(self.o.records(42,'expiring')),1)
        self.assertEqual(len(self.o.records(42,'expired')),1)
        self.assertEqual(len(self.o.records(42,'trials')),1)
        self.assertEqual(len(self.o.records(42,'all')),4)


@unittest.skipUnless(os.getenv('STREAMBOT_TEST_POSTGRES')=='true' and not os.getenv('REPLIT_DEPLOYMENT'),'Development PostgreSQL opt-in only')
class PostgreSQLTests(Scenarios,unittest.TestCase):
    def setUp(self):
        self.store=PostgresStore(os.environ['DATABASE_URL'],Fernet.generate_key())
        db=self.store._connect();db.execute('SELECT 1')
        self.addCleanup(db.close);self.addCleanup(db.rollback)
        @contextlib.contextmanager
        def connection():
            with db.transaction():yield _Connection(db,self.store._transaction_lock)
        self.store.connection=connection
        self.setup_service()


class DateTests(unittest.TestCase):
    def test_london_winter_summer_and_provider_formats(self):
        self.assertEqual(provider_time('2026-11-08 20:00'),provider_time('08-11-2026 20:00'))
        self.assertEqual(provider_time('<span>08-11-2026 20:00</span>'),provider_time('2026-11-08 20:00'))
        self.assertEqual(provider_time('2026-07-08 20:00')-provider_time('2026-07-08 20:00','UTC'),-3600)
