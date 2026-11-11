"""Run Telegram update handlers off the polling thread.

One slow handler (a panel read, a chain lookup, a rate quote, a sluggish Telegram API call)
used to hold up every other chat's taps until it finished, and the taps then arrived in a
burst. The dispatcher keeps one handler at a time per chat so a user's taps still apply in
order, but lets different chats proceed at once, and never lets one failing update stop
the loop from moving on.
"""
import collections
import threading
from concurrent.futures import ThreadPoolExecutor


class ChatDispatcher:
    def __init__(self, handle, workers=6, on_error=None):
        self.handle = handle
        self.on_error = on_error
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='telegram-chat')
        self.lock = threading.Lock()
        self.queues = {}
        self.closed = False

    def submit(self, chat_id, update):
        """Queue an update for its chat. Returns False once the dispatcher is shut down."""
        with self.lock:
            if self.closed:
                return False
            queue = self.queues.get(chat_id)
            if queue is not None:
                queue.append(update)
                return True
            self.queues[chat_id] = collections.deque([update])
        self.pool.submit(self._drain, chat_id)
        return True

    def _drain(self, chat_id):
        while True:
            with self.lock:
                queue = self.queues[chat_id]
                if not queue:
                    del self.queues[chat_id]
                    return
                update = queue.popleft()
            try:
                self.handle(update)
            except BaseException as exc:  # a failing handler must never take the worker down
                if self.on_error:
                    try: self.on_error(exc)
                    except Exception: pass

    def pending(self):
        with self.lock:
            return sum(len(queue) for queue in self.queues.values()) + len(self.queues)

    def shutdown(self, wait=True):
        with self.lock:
            self.closed = True
        self.pool.shutdown(wait=wait)
