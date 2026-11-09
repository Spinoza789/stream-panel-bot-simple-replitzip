"""Rolling-publish safety: HTTP can start, but only one lease owner works."""
import contextlib
import threading
import time
import unittest
from unittest.mock import Mock, patch

from streambot.__main__ import run_server
from streambot.config import load_config
from streambot.postgres_store import InstanceLockBusy
from streambot.runtime import ExclusiveRuntime
from streambot.web import create_app


def wait_until(predicate, seconds=2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.lock = threading.Lock()
        self.busy = threading.Event()

    @contextlib.contextmanager
    def lease(self):
        if not self.lock.acquire(blocking=False):
            self.busy.set()
            raise InstanceLockBusy('Previous instance is active')
        try:
            yield
        finally:
            self.lock.release()

    def runtime(self, activate=None, healthy=None, lease=None):
        runtime = ExclusiveRuntime(
            lease or self.lease, healthy or (lambda: True),
            activate or Mock(), Mock(), retry_seconds=0.01, check_seconds=0.01)
        self.addCleanup(runtime.close)
        return runtime

    def test_standby_starts_no_workers_then_activates_once_after_release(self):
        self.lock.acquire()
        runtime = self.runtime()
        runtime.start()
        self.assertTrue(self.busy.wait(2))
        runtime.activate.assert_not_called()
        self.assertFalse(runtime.ready.is_set())
        self.lock.release()
        self.assertTrue(runtime.ready.wait(2))
        runtime.activate.assert_called_once()
        runtime.close()
        self.assertFalse(runtime.ready.is_set())
        self.assertFalse(runtime.thread.is_alive())

    def test_two_candidates_never_activate_together_and_handoff_is_possible(self):
        self.lock.acquire()
        first, second = self.runtime(), self.runtime()
        first.start()
        second.start()
        self.assertTrue(self.busy.wait(2))
        self.lock.release()
        self.assertTrue(wait_until(lambda: first.ready.is_set() or second.ready.is_set()))
        self.assertEqual(int(first.ready.is_set()) + int(second.ready.is_set()), 1)
        active, standby = (first, second) if first.ready.is_set() else (second, first)
        standby.activate.assert_not_called()
        active.close()
        self.assertTrue(standby.ready.wait(2))
        active.activate.assert_called_once()
        standby.activate.assert_called_once()

    def test_shutdown_while_waiting_does_not_activate(self):
        self.lock.acquire()
        runtime = self.runtime()
        runtime.start()
        self.assertTrue(self.busy.wait(2))
        runtime.close()
        self.lock.release()
        runtime.activate.assert_not_called()
        runtime.on_failure.assert_not_called()

    def test_lease_loss_fails_closed_without_reacquiring(self):
        acquire = Mock(side_effect=self.lease)
        runtime = self.runtime(healthy=Mock(side_effect=[True, False]), lease=acquire)
        runtime.start()
        self.assertTrue(wait_until(lambda: runtime.on_failure.called))
        self.assertTrue(runtime.stop.is_set())
        self.assertFalse(runtime.ready.is_set())
        runtime.activate.assert_called_once()
        acquire.assert_called_once()

    def test_database_failure_is_not_misreported_as_a_busy_lease(self):
        acquire = Mock(side_effect=RuntimeError('Database is unavailable'))
        runtime = self.runtime(lease=acquire)
        runtime.start()
        self.assertTrue(wait_until(lambda: runtime.on_failure.called))
        runtime.activate.assert_not_called()
        acquire.assert_called_once()

    def test_real_server_wiring_serves_standby_before_any_recovery_or_telegram(self):
        self.lock.acquire()
        config = load_config(env={'APP_MODE': 'demo'})
        config.update(mode='live', database_url='unused-test-connection',
                      telegram_enabled=True, bot_token='fake-test-token')
        service = Mock(config=config)
        service.store.acquire_instance_lock.side_effect = self.lease
        service.store.instance_lock_healthy.return_value = True
        service.panel.inspect_packages.return_value = [
            {'id': str(package)} for package in
            {p['package_id'] for p in config['plans']} | {config['trial_package_id']}]

        def serve(app, **kwargs):
            client = app.test_client()
            self.assertTrue(self.busy.wait(2))
            self.assertEqual(client.get('/').json['status'], 'standby')
            self.assertEqual(client.post('/api/orders', json={}).status_code, 503)
            service.recover_interrupted.assert_not_called()
            service.check_payments.assert_not_called()
            service.provision_pending.assert_not_called()
            telegram.assert_not_called()
            self.lock.release()
            self.assertTrue(wait_until(lambda: client.get('/healthz').json['status'] == 'ok'))
            service.recover_interrupted.assert_called_once()
            self.assertTrue(wait_until(lambda: telegram.return_value.run.called))
            telegram.assert_called_once_with(service)
            self.assertTrue(client.get('/healthz').json['workers_active'])

        with patch('streambot.__main__.serve', side_effect=serve), \
                patch('streambot.__main__.signal.signal'), \
                patch('streambot.__main__.TelegramBot') as telegram, \
                contextlib.ExitStack() as resources:
            run_server(service, config, resources)


class StandbyHttpTests(unittest.TestCase):
    def setUp(self):
        self.ready = threading.Event()
        config = load_config(env={'APP_MODE': 'demo'})
        self.service = Mock(config=config)
        self.service.store.limit.return_value = True
        self.service.create_order.return_value = {'id': 'fake-test-order'}
        self.client = create_app(self.service, ready=self.ready).test_client()

    def test_liveness_succeeds_but_every_business_endpoint_is_blocked(self):
        for path in ('/', '/healthz'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['status'], 'standby')
            self.assertFalse(response.json['workers_active'])
        for method, path in (('GET', '/api/catalog'), ('GET', '/api/order'),
                             ('POST', '/api/orders'), ('POST', '/api/order/verify')):
            self.assertEqual(self.client.open(path, method=method, json={}).status_code, 503)
        self.service.store.limit.assert_not_called()
        self.service.create_order.assert_not_called()

    def test_activation_restores_checkout_and_shutdown_blocks_it_again(self):
        self.ready.set()
        self.assertEqual(self.client.get('/healthz').json['status'], 'ok')
        self.assertIn(b'<!doctype html>', self.client.get('/').data.lower())
        response = self.client.post('/api/orders', json={'plan_id': 'test', 'asset_id': 'test'},
                                    headers={'Origin': self.service.config['public_url']})
        self.assertEqual(response.status_code, 201)
        self.ready.clear()
        self.assertEqual(self.client.post('/api/orders', json={}).status_code, 503)
        self.service.create_order.assert_called_once()
