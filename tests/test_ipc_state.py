import unittest
from unittest.mock import patch

from desktop.runtime.state import WorkerState
from desktop.shell.ipc import RemoteAppController, RemoteWorkerProxy, SettingsHostService


class FakeWorker:
    def get_state(self):
        return WorkerState(
            running=True,
            is_busy=True,
            is_stopping=False,
            current_status="connected",
            status_text="Playing",
            ra_connected=True,
            ra_status_text="Connected to RetroAchievements",
            ra_permissions=3,
            ra_role_label="Developer",
            ra_role_tier="developer",
        )


class FakePlatform:
    startup_toggle_label = "Launch on login"

    def is_autostart_enabled(self):
        return True


class FakeController:
    def __init__(self):
        self.worker = FakeWorker()
        self.platform = FakePlatform()
        self.config = {"username": "user", "apikey": "secret"}

    def get_update_status(self):
        from desktop.runtime.controller import UpdateStatus

        return UpdateStatus(checked=True)

    def load_config(self):
        return dict(self.config)


class IpcStateTests(unittest.TestCase):
    def test_service_state_uses_worker_snapshot(self):
        service = object.__new__(SettingsHostService)
        service.controller = FakeController()

        state = service._build_state()

        self.assertEqual("connected", state["worker"]["current_status"])
        self.assertTrue(state["worker"]["is_busy"])
        self.assertEqual("Developer", state["worker"]["ra_role_label"])
        self.assertTrue(state["config"]["apikey_present"])
        self.assertEqual("", state["config"]["apikey"])

    def test_remote_worker_proxy_exposes_snapshot(self):
        proxy = RemoteWorkerProxy()
        proxy.update(
            {
                "running": True,
                "current_status": "error",
                "status_text": "Discord is not open",
                "ra_connected": False,
                "ra_status_text": "Not connected to RetroAchievements",
                "ra_permissions": 4,
                "ra_role_label": "Moderator",
                "ra_role_tier": "moderator",
                "is_busy": True,
                "is_stopping": False,
            }
        )

        state = proxy.get_state()

        self.assertTrue(state.running)
        self.assertEqual("error", state.current_status)
        self.assertTrue(state.is_busy)
        self.assertEqual(4, state.ra_permissions)
        self.assertEqual("Moderator", state.ra_role_label)
        self.assertEqual("moderator", state.ra_role_tier)

    def test_service_supports_tcp_fallback_transport(self):
        service = SettingsHostService(FakeController())
        with patch("desktop.shell.ipc._supports_unix_socket", return_value=False):
            service.start()
            try:
                client = RemoteAppController(service.address, service.auth_token)
                self.assertEqual("user", client.config["username"])
                self.assertTrue(client.config["apikey_present"])
                self.assertEqual("connected", client.worker.current_status)
            finally:
                service.stop()


if __name__ == "__main__":
    unittest.main()
