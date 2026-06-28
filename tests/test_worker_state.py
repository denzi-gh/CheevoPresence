import threading
import unittest

from desktop.runtime.state import WorkerState
from desktop.runtime.worker import RPCWorker


class WorkerStateTests(unittest.TestCase):
    def test_get_state_returns_status_snapshot(self):
        worker = RPCWorker(initial_config={}, console_icons={})

        worker.status_callback("connected", "Playing")
        worker.set_ra_status(True)
        worker.set_ra_role(2)
        state = worker.get_state()

        self.assertIsInstance(state, WorkerState)
        self.assertFalse(state.running)
        self.assertFalse(state.is_busy)
        self.assertFalse(state.is_stopping)
        self.assertEqual("connected", state.current_status)
        self.assertEqual("Playing", state.status_text)
        self.assertTrue(state.ra_connected)
        self.assertEqual("Connected to RetroAchievements", state.ra_status_text)
        self.assertEqual(2, state.ra_permissions)
        self.assertEqual("Junior Developer", state.ra_role_label)
        self.assertEqual("junior_developer", state.ra_role_tier)

    def test_ra_status_clear_removes_role_snapshot(self):
        worker = RPCWorker(initial_config={}, console_icons={})
        worker.set_ra_status(True)
        worker.set_ra_role(3)

        worker.set_ra_status(False)
        state = worker.get_state()

        self.assertFalse(state.ra_connected)
        self.assertIsNone(state.ra_permissions)
        self.assertEqual("", state.ra_role_label)
        self.assertEqual("", state.ra_role_tier)

    def test_busy_and_stopping_are_derived_from_thread_lifecycle(self):
        worker = RPCWorker(initial_config={}, console_icons={})
        stop_event = threading.Event()
        thread = threading.Thread(target=stop_event.wait)
        thread.start()
        try:
            worker.thread = thread
            worker.running = False

            state = worker.get_state()

            self.assertTrue(state.is_busy)
            self.assertTrue(state.is_stopping)
            self.assertTrue(worker.is_busy())
            self.assertTrue(worker.is_stopping())
        finally:
            stop_event.set()
            thread.join(timeout=1)

    def test_status_callback_invokes_external_callback_outside_state_update(self):
        seen = []
        worker = RPCWorker(
            status_callback=lambda status, text: seen.append((status, text)),
            initial_config={},
            console_icons={},
        )

        worker.status_callback("error", "Discord is not open")

        self.assertEqual([("error", "Discord is not open")], seen)
        self.assertEqual("error", worker.get_state().current_status)


if __name__ == "__main__":
    unittest.main()
