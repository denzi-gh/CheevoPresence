"""Regression test: disconnect must not hold the action lock over the join.

A hung worker (worker.stop blocking up to `timeout`) used to freeze every
other controller action because disconnect held _action_lock across the join.
"""

import threading
import unittest

from desktop.runtime.controller import AppController


class _BlockingWorker:
    def __init__(self, entered, release):
        self._entered = entered
        self._release = release

    def stop(self, timeout=35):
        self._entered.set()
        # Simulate a slow/hung join.
        self._release.wait(timeout=5)
        return True


class DisconnectLockScopeTests(unittest.TestCase):
    def _controller(self, worker):
        controller = object.__new__(AppController)
        controller._action_lock = threading.Lock()
        controller.worker = worker
        controller.config = {}
        return controller

    def test_action_lock_is_free_while_disconnect_joins(self):
        entered = threading.Event()
        release = threading.Event()
        controller = self._controller(_BlockingWorker(entered, release))

        thread = threading.Thread(target=controller.disconnect)
        thread.start()
        try:
            self.assertTrue(entered.wait(timeout=2), "disconnect never called worker.stop")

            # While disconnect is blocked inside worker.stop(), another action
            # must still be able to take the controller lock.
            acquired = controller._action_lock.acquire(timeout=1)
            self.assertTrue(acquired, "disconnect held _action_lock across the join")
            controller._action_lock.release()
        finally:
            release.set()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
