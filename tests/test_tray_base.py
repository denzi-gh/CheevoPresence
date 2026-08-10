"""Tests for the shared tray connection state machine."""

import unittest
from unittest import mock

from desktop.shell.tray_base import (
    TrayControllerBase,
    tray_connection_title,
    truncate_tray_status,
)


class FakeState:
    def __init__(self, running=False, is_stopping=False):
        self.running = running
        self.is_stopping = is_stopping


class FakeWorker:
    def __init__(self, state):
        self._state = state
        self.ra_status = None
        self.status_calls = []

    def get_state(self):
        return self._state

    def set_ra_status(self, connected):
        self.ra_status = connected

    def status_callback(self, status, text):
        self.status_calls.append((status, text))


class FakeController:
    def __init__(self, config, start_result=True):
        self._config = config
        self._start_result = start_result
        self.disconnected = False
        self.started = False

    def load_config(self):
        return self._config

    def disconnect(self):
        self.disconnected = True

    def start_saved_session(self):
        self.started = True
        return self._start_result


class FakeTray(TrayControllerBase):
    def __init__(self, controller, worker):
        self.controller = controller
        self.worker = worker
        self._shutdown_started = False
        self.menu_refreshed = 0
        self.settings_opened = 0

    def _marshal(self, fn):
        # The real shells hop to their UI thread here; run synchronously.
        fn()

    def _refresh_menu(self):
        self.menu_refreshed += 1

    def open_settings(self):
        self.settings_opened += 1


_CREDS = {"username": "u", "apikey": "k"}


def _tray(state, config=None, start_result=True):
    worker = FakeWorker(state)
    controller = FakeController(config or dict(_CREDS), start_result=start_result)
    return FakeTray(controller, worker), controller, worker


class ConnectionTitleTests(unittest.TestCase):
    def test_stopping_takes_priority(self):
        self.assertEqual("Stopping...", tray_connection_title(FakeWorker(FakeState(running=True, is_stopping=True))))

    def test_running_is_disconnect(self):
        self.assertEqual("Disconnect", tray_connection_title(FakeWorker(FakeState(running=True))))

    def test_idle_is_connect(self):
        self.assertEqual("Connect", tray_connection_title(FakeWorker(FakeState())))


class TruncateTests(unittest.TestCase):
    def test_short_text_unchanged(self):
        self.assertEqual("hello", truncate_tray_status("hello"))

    def test_long_text_clipped_with_ellipsis(self):
        out = truncate_tray_status("x" * 100, limit=10)
        self.assertEqual(10, len(out))
        self.assertTrue(out.endswith("..."))


class ToggleConnectionTests(unittest.TestCase):
    def test_running_disconnects_and_refreshes(self):
        tray, controller, _ = _tray(FakeState(running=True))

        tray._toggle_connection()

        self.assertTrue(controller.disconnected)
        self.assertFalse(controller.started)
        self.assertEqual(1, tray.menu_refreshed)

    def test_missing_credentials_opens_settings_without_starting(self):
        tray, controller, worker = _tray(FakeState(), config={"username": "", "apikey": ""})

        tray._toggle_connection()

        self.assertFalse(controller.started)
        self.assertEqual(False, worker.ra_status)
        self.assertEqual([("error", "Username or API Key missing")], worker.status_calls)
        self.assertEqual(1, tray.settings_opened)
        self.assertEqual(0, tray.menu_refreshed)

    def test_successful_start_does_not_refresh_menu(self):
        tray, controller, _ = _tray(FakeState(), start_result=True)

        tray._toggle_connection()

        self.assertTrue(controller.started)
        self.assertEqual(0, tray.menu_refreshed)
        self.assertEqual(0, tray.settings_opened)

    def test_failed_start_refreshes_menu(self):
        tray, controller, _ = _tray(FakeState(), start_result=False)

        tray._toggle_connection()

        self.assertTrue(controller.started)
        self.assertEqual(1, tray.menu_refreshed)


class RequestToggleGuardTests(unittest.TestCase):
    def _spawned(self, tray):
        with mock.patch("desktop.shell.tray_base.threading.Thread") as thread:
            tray._request_toggle_connection()
        return thread.called

    def test_spawns_worker_thread_when_idle(self):
        tray, _, _ = _tray(FakeState())
        self.assertTrue(self._spawned(tray))

    def test_stopping_does_not_spawn(self):
        tray, _, _ = _tray(FakeState(is_stopping=True))
        self.assertFalse(self._spawned(tray))

    def test_shutdown_does_not_spawn(self):
        tray, _, _ = _tray(FakeState())
        tray._shutdown_started = True
        self.assertFalse(self._spawned(tray))


if __name__ == "__main__":
    unittest.main()
