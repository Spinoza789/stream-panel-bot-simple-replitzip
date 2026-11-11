"""Safe diagnostic stages and durable Telegram update acknowledgements."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet

from streambot.bot import TelegramBot, TelegramError
from streambot.config import load_config
from streambot.postgres_store import _state_error
from streambot.service import CheckoutService
from streambot.store import Store


class StopOnBackoff(threading.Event):
    def wait(self, timeout=None):
        self.set()
        return True


class PollingTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store=Store(Path(temp.name)/'polling.sqlite3',Fernet.generate_key())
        config=load_config(env={'APP_MODE':'demo'})
        self.service=CheckoutService(config,self.store,Mock(),Mock())
        self.updates=[]
        self.api=Mock(side_effect=lambda method,payload:self.updates if method=='getUpdates' else True)
        self.bot=TelegramBot(self.service,api=self.api)
        self.bot.notify_trials=Mock()
        self.bot.checkout.notify=Mock()

    def run_failure(self,stage):
        stop=StopOnBackoff()
        with self.assertLogs('streambot.bot',level='WARNING') as captured:
            self.bot.run(stop)
        text='\n'.join(captured.output)
        self.assertIn('stage='+stage,text)
        self.assertNotIn('private-provider-message',text)
        return text

    def test_notification_failures_report_safe_database_category(self):
        class InvalidCast(Exception):
            sqlstate='22P02'
        failure=_state_error(InvalidCast('private-provider-message'),'query')
        for stage in ('trial_notifications','payment_notifications'):
            with self.subTest(stage=stage):
                self.bot.notify_trials.side_effect=failure if stage=='trial_notifications' else None
                self.bot.checkout.notify.side_effect=failure if stage=='payment_notifications' else None
                text=self.run_failure(stage)
                self.assertIn('db_stage=query',text)
                self.assertIn('SQLSTATE=22P02',text)

    def test_poll_and_handler_errors_never_log_raw_messages(self):
        self.api.side_effect=lambda method,payload:(_ for _ in ()).throw(
            RuntimeError('private-provider-message')) if method=='getUpdates' else True
        self.run_failure('poll')
        # A failing handler is logged safely and the update is acknowledged, so one bad tap can
        # never hold up the chat or make the loop replay it every few seconds.
        stop=threading.Event()
        polls=[]
        def api(method,payload):
            if method=='getUpdates':
                polls.append(payload['offset'])
                if len(polls)>1:stop.set();return []
                return [{'update_id':41,'message':{'text':'private-provider-message'}}]
            return True
        self.bot.api=api
        self.bot.handle=Mock(side_effect=RuntimeError('private-provider-message'))
        with self.assertLogs('streambot.bot',level='WARNING') as captured:
            self.bot.run(stop)
        text='\n'.join(captured.output)
        self.assertIn('stage=handle_update',text)
        self.assertNotIn('private-provider-message',text)
        self.assertEqual(polls,[0,42])
        self.assertEqual(self.store.metadata('telegram_offset'),'42')
        self.bot.handle.assert_called_once()

    def test_initial_offset_failure_is_retried_instead_of_killing_thread(self):
        with patch.object(self.store,'metadata',side_effect=RuntimeError('private-provider-message')):
            self.run_failure('offset_load')
        self.api.assert_not_called()

    def test_cursor_is_not_advanced_until_persistence_succeeds(self):
        self.updates=[{'update_id':41}]
        self.bot.handle=Mock()
        stop=threading.Event()
        polls=[]
        attempts=0
        original=self.store.metadata

        def metadata(key,value=None):
            nonlocal attempts
            if key=='telegram_offset' and value is not None:
                attempts+=1
                if attempts==1:raise RuntimeError('private-provider-message')
                stop.set()
            return original(key,value)

        def api(method,payload):
            if method=='getUpdates':
                polls.append(payload['offset'])
                return self.updates
            return True
        self.bot.api=api
        with patch.object(self.store,'metadata',side_effect=metadata),patch.object(stop,'wait',return_value=False):
            with self.assertLogs('streambot.bot',level='WARNING') as captured:
                self.bot.run(stop)
        self.assertIn('stage=save_offset','\n'.join(captured.output))
        self.assertEqual(polls,[0,0])
        self.assertEqual(original('telegram_offset'),'42')

    def test_telegram_api_errors_keep_only_method_and_code(self):
        self.api.side_effect=TelegramError(401,'getMe')
        with self.assertLogs('streambot.bot',level='WARNING') as captured:
            self.bot.run(StopOnBackoff())
        self.assertIn('getMe, Telegram API code 401','\n'.join(captured.output))
