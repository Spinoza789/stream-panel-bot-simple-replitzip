"""Taps from one chat stay in order; different chats never wait for each other; failures are skipped."""
import threading
import time
import unittest

from streambot.dispatch import ChatDispatcher


class DispatchTests(unittest.TestCase):
    def test_chats_run_side_by_side_but_each_chat_in_order(self):
        release=threading.Event(); seen=[]; lock=threading.Lock()
        def handle(update):
            if update=='A1':release.wait(5)
            with lock:seen.append(update)
        d=ChatDispatcher(handle,workers=4)
        d.submit('A','A1'); d.submit('A','A2'); d.submit('B','B1')
        deadline=time.time()+5
        while 'B1' not in seen and time.time()<deadline:time.sleep(0.01)
        self.assertEqual(seen,['B1'])  # chat B was not held up by chat A's slow tap
        release.set(); d.shutdown()
        self.assertEqual(seen,['B1','A1','A2'])  # and chat A's taps applied in the order they were sent

    def test_failures_are_reported_and_the_chat_keeps_going(self):
        errors=[]; seen=[]
        def handle(update):
            if update=='boom':raise RuntimeError('private text')
            seen.append(update)
        d=ChatDispatcher(handle,workers=2,on_error=lambda exc:errors.append(type(exc).__name__))
        d.submit(1,'boom'); d.submit(1,'next'); d.shutdown()
        self.assertEqual((errors,seen),(['RuntimeError'],['next']))
        self.assertFalse(d.submit(1,'late'))  # nothing is accepted after shutdown


if __name__ == '__main__':
    unittest.main()
