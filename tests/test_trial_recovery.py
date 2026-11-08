"""Trial recovery uses the same order and credentials; all panel calls are fake."""
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

from cryptography.fernet import Fernet

from streambot.bot import TelegramBot
from streambot.config import load_config
from streambot.panel import PanelError, ProvisioningUncertain
from streambot.service import CheckoutError, CheckoutService
from streambot.store import Store
from streambot.trial_message import trial_ready_text


class TrialRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.key=Fernet.generate_key()
        self.store = Store(Path(temp.name) / 'test.sqlite3', self.key)
        self.config = load_config(env={'APP_MODE': 'demo'})
        self.config.update(mode='live', panel_writes=True)
        self.panel = Mock()
        self.panel.find_account.return_value = None
        self.panel.prepare_generation.side_effect = lambda package:dict(
            generation_mode='panel',package_id=package,before_ids=[],prepared_at=int(time.time()),post_attempted=True)
        self.panel.create_account.side_effect = lambda package, user, password, description, **kwargs: {
            'username': 'generated-user', 'password': 'generated-secret', 'package_id': package, 'server_url': 'test server'}
        self.service = CheckoutService(self.config, self.store, Mock(), self.panel)
        self.order = self.service.create_trial(42)
        self.credentials = dict(username='test-user', password='test-secret',
                                package_id=str(self.config['trial_package_id']))
        self.store.update(self.order['id'], status='review', credentials=self.credentials)
        self.store.metadata('trial_recheck_after:' + self.order['id'], 0)
        self.calls = []
        self.bot = TelegramBot(self.service, api=lambda method, payload: self.calls.append((method, payload)) or {'message_id': 1})

    def test_absent_account_requeues_original_once_using_panel_generation(self):
        first = self.service.retry_trial(42)
        again = self.service.retry_trial(42)
        self.assertEqual((first['id'], again['id']), (self.order['id'], self.order['id']))
        self.assertEqual(first['status'], 'paid')
        self.panel.find_account.assert_called_once_with(self.credentials['username'])
        self.service.provision_pending()
        fulfilled = self.store.trial(42)
        self.assertEqual(fulfilled['status'], 'fulfilled')
        self.assertEqual(fulfilled['credentials']['password'], 'generated-secret')
        self.panel.create_account.assert_called_once()
        self.assertEqual(self.panel.create_account.call_args.args[1:],('','',''))
        self.assertEqual(self.service.create_trial(42)['id'], self.order['id'])

    def test_lifetime_limit_survives_every_status_expiry_and_store_restart(self):
        for status in ('paid','provisioning','fulfilled','review','expired','cancelled'):
            self.store.update(self.order['id'],status=status,credentials=self.credentials)
            with self.store.connection() as db:
                db.execute('UPDATE orders SET expires_at=0,created_at=0 WHERE id=?',(self.order['id'],))
            restarted=CheckoutService(self.config,Store(self.store.path,self.key),Mock(),self.panel)
            self.assertEqual(restarted.create_trial(42)['id'],self.order['id'])
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM orders WHERE telegram_id=?',(42,)).fetchone()[0],1)
        self.panel.create_account.assert_not_called()

    def test_simultaneous_requests_create_and_provision_only_one_trial(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            orders=list(pool.map(self.service.create_trial,[98]*16))
        self.assertEqual(len({order['id'] for order in orders}),1)
        self.service.provision_pending()
        self.service.provision_pending()
        self.assertEqual(self.service.create_trial(98)['id'],orders[0]['id'])
        self.panel.create_account.assert_called_once()

    def test_username_changes_commands_and_buttons_do_not_reset_eligibility(self):
        for index,username in enumerate(('first_name','changed_name')):
            sender={'id':42,'username':username}
            self.bot.handle({'message':{'message_id':index+1,'from':sender,
                                       'chat':{'id':42,'type':'private'},'text':'/trial'}})
            self.bot.handle({'callback_query':{'id':'trial-'+str(index),'from':sender,'data':'menu:trial',
                                              'message':{'chat':{'id':42,'type':'private'}}}})
        self.assertEqual(self.store.trial(42)['id'],self.order['id'])
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM orders WHERE telegram_id=?',(42,)).fetchone()[0],1)
        self.panel.prepare_generation.assert_not_called()

    def test_different_telegram_ids_have_independent_one_trial_allowances(self):
        first=self.service.create_trial(98)
        second=self.service.create_trial(99)
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(self.service.create_trial(98)['id'],first['id'])
        self.assertEqual(self.service.create_trial(99)['id'],second['id'])

    def test_invalid_telegram_id_types_are_rejected_at_both_layers(self):
        for uid in (True,False,'42',42.0,0,-1):
            with self.subTest(uid_type=type(uid).__name__):
                with self.assertRaises(CheckoutError):
                    self.service.create_trial(uid)
                with self.assertRaises(ValueError):
                    self.store.create({'id':'trial'},dict(id='trial'),0,telegram_id=uid)

    def test_existing_matching_account_is_delivered_without_creation(self):
        self.panel.find_account.return_value = self.credentials
        result = self.service.retry_trial(42)
        self.assertEqual(result['status'], 'fulfilled')
        self.assertEqual(result['credentials'], self.credentials)
        self.panel.create_account.assert_not_called()

    def test_trial_commands_callbacks_and_background_delivery_share_format(self):
        self.store.update(self.order['id'],status='fulfilled',credentials=self.credentials)
        expected=trial_ready_text(self.credentials)
        message={'message_id':1,'from':{'id':42},'chat':{'id':42,'type':'private'},'text':'/trial'}
        self.bot.handle({'message':message})
        self.bot.handle({'message':dict(message,message_id=2,text='/retrytrial')})
        self.bot.handle({'callback_query':{'id':'fulfilled-trial','from':{'id':42},'data':'menu:trial',
                                          'message':{'chat':{'id':42,'type':'private'}}}})
        self.store.metadata('trial_sent:'+self.order['id'],'')
        with self.store.connection() as db:
            db.execute('DELETE FROM metadata WHERE key=?',('trial_sent:'+self.order['id'],))
        self.bot.notify_trials()
        delivered=[p for method,p in self.calls if method=='sendMessage']
        self.assertEqual(len(delivered),4)
        self.assertTrue(all(p['text']==expected and p['chat_id']==42 for p in delivered))

    def test_different_owner_and_mismatched_credentials_never_retry(self):
        with self.assertRaises(CheckoutError):
            self.service.retry_trial(43)
        self.panel.find_account.assert_not_called()
        self.panel.find_account.return_value = dict(self.credentials, password='different-secret')
        with self.assertRaisesRegex(CheckoutError, 'No retry was queued'):
            self.service.retry_trial(42)
        self.assertEqual(self.store.trial(42)['status'], 'review')
        self.panel.create_account.assert_not_called()

    def test_lookup_failure_and_cooldown_do_not_requeue(self):
        self.panel.find_account.side_effect = PanelError('Cannot read listing')
        with self.assertRaisesRegex(CheckoutError, 'No retry was queued'):
            self.service.retry_trial(42)
        self.store.metadata('trial_recheck_after:' + self.order['id'], int(time.time()) + 300)
        with self.assertRaisesRegex(CheckoutError, 'Please wait'):
            self.service.retry_trial(42)
        self.assertEqual(self.store.trial(42)['status'], 'review')
        self.panel.find_account.assert_called_once()

    def test_concurrent_checks_cannot_queue_two_creations(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.service.retry_trial, [42, 42]))
        self.assertTrue(all(result['id'] == self.order['id'] for result in results))
        self.service.provision_pending()
        self.panel.create_account.assert_called_once()

    def test_uncertain_retry_stops_in_review_and_enforces_cooldown(self):
        self.service.retry_trial(42)
        self.panel.create_account.side_effect = ProvisioningUncertain('Unverified creation')
        self.service.provision_pending()
        self.assertEqual(self.store.trial(42)['status'], 'review')
        with self.assertRaisesRegex(CheckoutError, 'No second account'):
            self.service.retry_trial(42)
        self.panel.create_account.assert_called_once()
        public=self.service.trial_status(42)
        self.assertTrue(public['account_identity_unknown'])
        self.assertEqual(self.bot.trial_keyboard(public)['inline_keyboard'][0][0]['callback_data'],'menu:contact')

    def test_generation_snapshot_is_durable_before_post(self):
        self.service.retry_trial(42)
        def generate(package,user,password,description,**kwargs):
            saved=self.store.get(self.order['id'])['credentials']
            self.assertEqual(saved['generation_mode'],'panel')
            self.assertTrue(saved['post_attempted'])
            self.assertNotIn('username',saved)
            self.assertEqual((user,password,description),('','',''))
            return {'username':'generated-user','password':'generated-secret'}
        self.panel.create_account.side_effect=generate
        self.service.provision_pending()
        self.assertEqual(self.store.trial(42)['status'],'fulfilled')

    def test_pre_submit_failure_can_be_explicitly_requeued_without_old_identity(self):
        self.service.retry_trial(42)
        self.panel.create_account.side_effect=PanelError('Package not available')
        self.service.provision_pending()
        self.assertFalse(self.store.trial(42)['credentials']['post_attempted'])
        self.store.metadata('trial_recheck_after:'+self.order['id'],0)
        self.assertEqual(self.service.retry_trial(42)['status'],'paid')
        self.assertIsNone(self.store.trial(42)['credentials'])

    def test_snapshot_failure_saves_pre_post_proof_and_retries_same_trial(self):
        self.store.update(self.order['id'],status='paid',credentials=None)
        self.panel.prepare_generation.side_effect=PanelError('Panel listing changed during lookup')
        self.service.provision_pending()
        saved=self.store.trial(42)
        self.assertEqual(saved['status'],'review')
        self.assertFalse(saved['credentials']['post_attempted'])
        self.assertEqual(saved['credentials']['failure_stage'],'generation_preflight')
        self.panel.create_account.assert_not_called()
        with self.assertRaisesRegex(CheckoutError,'Please wait'):
            self.service.retry_trial(42)
        self.store.metadata('trial_recheck_after:'+self.order['id'],0)
        self.assertEqual(self.service.retry_trial(42)['id'],self.order['id'])
        self.panel.prepare_generation.side_effect=lambda package:dict(
            generation_mode='panel',package_id=package,before_ids=[],
            prepared_at=int(time.time()),post_attempted=True)
        self.service.provision_pending()
        self.assertEqual(self.store.trial(42)['status'],'fulfilled')
        self.panel.create_account.assert_called_once()
        self.assertEqual(self.service.create_trial(42)['id'],self.order['id'])

    def test_old_missing_details_remain_blocked_without_durable_pre_post_proof(self):
        self.store.update(self.order['id'],status='review',credentials=None)
        with self.assertRaisesRegex(CheckoutError,'stored account details'):
            self.service.retry_trial(42)
        self.panel.create_account.assert_not_called()

    def test_failed_legacy_lookup_keeps_existing_credentials(self):
        self.store.update(self.order['id'],status='paid')
        self.panel.find_account.side_effect=PanelError('Panel temporarily unavailable')
        self.service.provision_pending()
        self.assertEqual(self.store.trial(42)['credentials'],self.credentials)
        self.panel.create_account.assert_not_called()

    def test_all_paid_plans_and_new_trials_submit_only_blank_fields(self):
        asset=self.config['assets']['usdc-ethereum']
        for plan in self.config['plans']:
            _,order=self.store.create(plan,asset,10000)
            self.store.update(order['id'],status='paid')
            self.service.provision_pending()
            self.assertEqual(self.store.get(order['id'])['status'],'fulfilled')
        self.service.create_trial(43)
        self.service.provision_pending()
        calls=self.panel.create_account.call_args_list
        self.assertEqual(len(calls),len(self.config['plans'])+1)
        self.assertTrue(all(call.args[1:]==('','','') for call in calls))
        self.assertEqual([call.args[0] for call in calls[:-1]],[str(p['package_id']) for p in self.config['plans']])

    def test_bot_review_button_and_retry_command_are_functional(self):
        message = {'message_id': 1, 'from': {'id': 42}, 'chat': {'id': 42, 'type': 'private'}, 'text': '/trial'}
        self.bot.handle({'message': message})
        sent = [payload for method, payload in self.calls if method == 'sendMessage'][-1]
        self.assertEqual(sent['reply_markup']['inline_keyboard'][0][0]['callback_data'], 'menu:retrytrial')
        self.bot.handle({'message': dict(message, message_id=2, text='/retrytrial')})
        self.assertEqual(self.store.trial(42)['status'], 'paid')
        self.assertIn('being prepared', [p['text'] for m, p in self.calls if m == 'sendMessage'][-1])

    def test_callback_recovery_and_disabled_writes(self):
        self.config['panel_writes'] = False
        with self.assertRaisesRegex(CheckoutError, 'disabled'):
            self.service.retry_trial(42)
        self.assertEqual(self.store.trial(42)['status'], 'review')
        self.config['panel_writes'] = True
        self.bot.handle({'callback_query': {
            'id': 'retry-click', 'from': {'id': 42}, 'data': 'menu:retrytrial',
            'message': {'chat': {'id': 42, 'type': 'private'}}}})
        self.assertEqual(self.store.trial(42)['status'], 'paid')
