import tempfile
import unittest
from unittest.mock import patch

from desktop.runtime.controller import ConnectResult, UpdateStatus
from desktop.runtime.state import WorkerState
from desktop.shell.web_settings import WebSettingsAPI, role_badge_style


class FakePlatform:
    startup_toggle_label = "Launch on startup"

    def __init__(self):
        self.opened_path = None

    def is_autostart_enabled(self):
        return True

    def open_path(self, path):
        self.opened_path = path
        return True


class FakeWorker:
    def __init__(self):
        self.state = WorkerState(
            running=False,
            is_busy=False,
            is_stopping=False,
            current_status="disconnected",
            status_text="Not running",
            ra_connected=False,
            ra_status_text="Not connected to RetroAchievements",
        )

    def get_state(self):
        return self.state


class FakeController:
    def __init__(self, config):
        self.config = dict(config)
        self.worker = FakeWorker()
        self.platform = FakePlatform()
        self.connected_config = None
        self.disconnected = False

    def load_config(self):
        return dict(self.config)

    def get_update_status(self):
        return UpdateStatus()

    def connect(self, config):
        self.connected_config = dict(config)
        self.config = dict(config)
        return ConnectResult(success=True, config=dict(config))

    def disconnect(self):
        self.disconnected = True
        return True


class WebSettingsTests(unittest.TestCase):
    def test_connect_preserves_omitted_config_values(self):
        controller = FakeController(
            {
                "username": "old",
                "apikey": "old-key",
                "show_profile_button": False,
                "show_gamepage_button": True,
                "show_achievement_progress": True,
                "dev_mode": True,
                "use_retroachievements_developer_titles": False,
                "interval": 5,
                "timeout": 130,
                "start_on_boot": True,
            }
        )
        api = WebSettingsAPI(controller)
        api.load_config()

        result = api.connect(
            {
                "username": "new-user",
                "apikey": "new-key",
                "show_profile_button": True,
                "show_gamepage_button": False,
                "show_achievement_progress": False,
                "dev_mode": False,
                "interval": 10,
                "timeout": 260,
            }
        )

        self.assertTrue(result["success"])
        self.assertEqual("new-user", controller.connected_config["username"])
        self.assertTrue(controller.connected_config["start_on_boot"])
        self.assertFalse(
            controller.connected_config["use_retroachievements_developer_titles"]
        )

    def test_polling_state_does_not_expose_api_key(self):
        controller = FakeController(
            {
                "username": "user",
                "apikey": "secret",
                "interval": 5,
                "timeout": 130,
            }
        )
        state = WebSettingsAPI(controller).get_state()

        self.assertNotIn("apikey", state["config"])
        self.assertTrue(state["config"]["apikey_present"])

    def test_disconnect_delegates_to_controller(self):
        controller = FakeController({})

        result = WebSettingsAPI(controller).disconnect()

        self.assertTrue(result["success"])
        self.assertTrue(controller.disconnected)

    def test_disconnected_state_does_not_render_stale_connected_ra_text(self):
        controller = FakeController({})
        controller.worker.state = WorkerState(
            running=False,
            is_busy=False,
            is_stopping=False,
            current_status="disconnected",
            status_text="Stopped",
            ra_connected=False,
            ra_status_text="Connected as SomeUser",
        )

        state = WebSettingsAPI(controller).get_state()

        self.assertEqual(
            "Not connected to RetroAchievements",
            state["worker"]["ra_status_text"],
        )

    def test_open_logs_uses_platform_file_manager(self):
        controller = FakeController({})
        api = WebSettingsAPI(controller)

        with tempfile.TemporaryDirectory() as tmpdir:
            platform = FakePlatform()
            with patch(
                "desktop.shell.web_settings.get_platform_services",
                return_value=platform,
            ), patch("desktop.shell.web_settings.get_log_dir", return_value=tmpdir):
                result = api.open_logs()

            self.assertTrue(result["success"])
            self.assertEqual(tmpdir, platform.opened_path)

    def test_role_badge_style_supports_reference_tiers(self):
        self.assertEqual("#f0b450", role_badge_style("junior_developer")["accent"])
        self.assertEqual("#5fd07f", role_badge_style("developer")["accent"])
        self.assertEqual("#b0a0f0", role_badge_style("code_reviewer")["accent"])
        self.assertEqual("#6fcfe2", role_badge_style("moderator")["accent"])
        self.assertEqual("#f0b450", role_badge_style("unknown")["accent"])


if __name__ == "__main__":
    unittest.main()
