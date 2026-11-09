"""Serve HTTP during a rolling publish without running two worker instances."""
import logging
import threading

from .postgres_store import InstanceLockBusy

log = logging.getLogger(__name__)


class ExclusiveRuntime:
    def __init__(self, acquire_lease, healthy, activate, on_failure, *,
                 stop=None, retry_seconds=2, check_seconds=1):
        self.acquire_lease = acquire_lease
        self.healthy = healthy
        self.activate = activate
        self.on_failure = on_failure
        self.stop = stop if stop is not None else threading.Event()
        self.ready = threading.Event()
        self.retry_seconds = retry_seconds
        self.check_seconds = check_seconds
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True, name='worker-leadership')
        self.thread.start()

    def close(self):
        self.ready.clear()
        self.stop.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=8)

    def run(self):
        waiting_logged = False
        try:
            while not self.stop.is_set():
                try:
                    with self.acquire_lease():
                        if self.stop.is_set():
                            return
                        if not self.healthy():
                            raise RuntimeError('Worker lease is not healthy.')
                        self.activate()
                        if self.stop.is_set():
                            return
                        self.ready.set()
                        log.info('Worker leadership acquired; order processing is active.')
                        try:
                            while not self.stop.wait(self.check_seconds):
                                if not self.healthy():
                                    raise RuntimeError('Worker lease was lost.')
                        finally:
                            self.ready.clear()
                    return
                except InstanceLockBusy:
                    if not waiting_logged:
                        log.info('Waiting for the previous instance to release worker leadership. HTTP is in standby.')
                        waiting_logged = True
                    self.stop.wait(self.retry_seconds)
        except Exception as exc:
            self.ready.clear()
            self.stop.set()
            log.critical('Worker leadership failed (%s). Stopping to protect order processing.', type(exc).__name__)
            self.on_failure()
