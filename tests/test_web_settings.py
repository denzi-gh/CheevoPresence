import tempfile
import unittest
import logging
from unittest.mock import patch

from desktop.runtime.controller import ConnectResult, UpdateStatus
from desktop.runtime.state import MirroredPresence, WorkerState
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
        self.saved_config = None
        self.disconnected = False

    def load_config(self):
        return dict(self.config)

    def get_update_status(self):
        return UpdateStatus()

    def connect(self, config):
        self.connected_config = dict(config)
        self.config = dict(config)
        return ConnectResult(success=True, config=dict(config))

    def save_config(self, config):
        self.saved_config = dict(config)
        self.config = dict(config)
        return {"success": True, "config": dict(config)}

    def disconnect(self):
        self.disconnected = True
        return True


def _presence_snapshot():
    return MirroredPresence(
        game_id=123,
        title="Mega Game",
        details="Playing Level 1",
        state="\U0001F3C6 Softcore",
        console_name="NES",
        game_icon_url="https://media.retroachievements.org/Images/000123.png",
        large_text="4/10 achievements",
        achievement_count=4,
        achievement_total=10,
        show_achievement_progress=True,
        buttons=[
            {
                "label": "View on RetroAchievements",
                "url": "https://retroachievements.org/game/123",
            }
        ],
        developer_activity=False,
    )


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

    def test_save_config_dispatch_persists_without_connecting(self):
        controller = FakeController(
            {
                "username": "old",
                "apikey": "old-key",
                "show_profile_button": True,
                "show_gamepage_button": True,
                "show_achievement_progress": True,
                "dev_mode": True,
                "use_retroachievements_developer_titles": True,
                "interval": 5,
                "timeout": 130,
                "start_on_boot": False,
            }
        )
        api = WebSettingsAPI(controller)
        api.load_config()

        result = api.dispatch(
            "save_config",
            {
                "payload": {
                    "username": "new-user",
                    "apikey": "new-key",
                    "show_profile_button": False,
                    "show_gamepage_button": True,
                    "show_achievement_progress": False,
                    "use_retroachievements_developer_titles": False,
                    "interval": 15,
                    "timeout": 260,
                    "start_on_boot": True,
                    "dev_mode": False,
                }
            },
        )

        self.assertTrue(result["success"])
        self.assertIsNone(controller.connected_config)
        self.assertEqual("new-user", controller.saved_config["username"])
        self.assertTrue(controller.saved_config["start_on_boot"])
        self.assertFalse(
            controller.saved_config["use_retroachievements_developer_titles"]
        )
        self.assertTrue(controller.saved_config["dev_mode"])

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
            "Not connected",
            state["worker"]["ra_status_text"],
        )

    def test_disconnected_dev_mode_unlocks_developer_settings(self):
        controller = FakeController({"dev_mode": True})

        state = WebSettingsAPI(controller).get_state()

        self.assertTrue(state["developer_settings_unlocked"])

    def test_connected_elevated_permissions_unlock_developer_settings(self):
        controller = FakeController({"dev_mode": False})
        controller.worker.state = WorkerState(
            running=True,
            is_busy=True,
            is_stopping=False,
            current_status="connected",
            status_text="Playing",
            ra_connected=True,
            ra_status_text="Connected to RetroAchievements",
            ra_permissions=2,
            ra_role_label="Junior Developer",
            ra_role_tier="junior_developer",
        )

        state = WebSettingsAPI(controller).get_state()

        self.assertTrue(state["developer_settings_unlocked"])

    def test_connected_normal_permissions_ignore_stale_dev_mode_unlock(self):
        controller = FakeController({"dev_mode": True})
        controller.worker.state = WorkerState(
            running=True,
            is_busy=True,
            is_stopping=False,
            current_status="connected",
            status_text="Playing",
            ra_connected=True,
            ra_status_text="Connected to RetroAchievements",
            ra_permissions=1,
        )

        state = WebSettingsAPI(controller).get_state()

        self.assertFalse(state["developer_settings_unlocked"])

    def test_unauthorized_save_preserves_developer_title_setting(self):
        controller = FakeController(
            {
                "username": "user",
                "apikey": "key",
                "dev_mode": False,
                "use_retroachievements_developer_titles": False,
            }
        )
        api = WebSettingsAPI(controller)

        result = api.save_config({"use_retroachievements_developer_titles": True})

        self.assertTrue(result["success"])
        self.assertFalse(
            controller.saved_config["use_retroachievements_developer_titles"]
        )

    def test_authorized_save_preserves_developer_title_setting_while_running(self):
        controller = FakeController(
            {
                "username": "user",
                "apikey": "key",
                "dev_mode": True,
                "use_retroachievements_developer_titles": True,
            }
        )
        controller.worker.state = WorkerState(
            running=True,
            is_busy=True,
            is_stopping=False,
            current_status="connected",
            status_text="Developing",
            ra_connected=True,
            ra_status_text="Connected to RetroAchievements",
            ra_permissions=2,
            ra_role_label="Junior Developer",
            ra_role_tier="junior_developer",
        )
        api = WebSettingsAPI(controller)

        result = api.save_config({"use_retroachievements_developer_titles": False})

        self.assertTrue(result["success"])
        self.assertTrue(
            controller.saved_config["use_retroachievements_developer_titles"]
        )

    def test_state_payload_serializes_mirrored_presence(self):
        controller = FakeController({})
        controller.worker.state = WorkerState(
            running=True,
            is_busy=True,
            is_stopping=False,
            current_status="connected",
            status_text="Playing: Mega Game (NES)",
            ra_connected=True,
            ra_status_text="Connected to RetroAchievements",
            mirrored_presence=_presence_snapshot(),
        )

        state = WebSettingsAPI(controller).get_state()

        presence = state["worker"]["mirrored_presence"]
        self.assertEqual("Mega Game", presence["title"])
        self.assertEqual("NES", presence["console_name"])
        self.assertEqual(
            "https://retroachievements.org/game/123",
            presence["buttons"][0]["url"],
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

    def test_tail_logs_returns_recent_lines_path_and_level(self):
        controller = FakeController({})
        api = WebSettingsAPI(controller)

        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = f"{tmpdir}/cheevo.log"
            with open(log_file, "w", encoding="utf-8") as handle:
                handle.write("one\ntwo\nthree\n")

            with patch(
                "desktop.shell.web_settings.get_platform_services",
                return_value=FakePlatform(),
            ), patch("desktop.shell.web_settings.get_log_dir", return_value=tmpdir), patch(
                "desktop.shell.web_settings.get_log_file",
                return_value=log_file,
            ):
                result = api.tail_logs(lines=2)

        self.assertEqual(["two", "three"], result["lines"])
        self.assertEqual(tmpdir, result["path"])
        self.assertIn(result["level"], {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

    def test_set_log_level_updates_root_logger(self):
        controller = FakeController({})
        api = WebSettingsAPI(controller)
        root = logging.getLogger()
        original = root.level
        try:
            result = api.set_log_level("DEBUG")

            self.assertTrue(result["success"])
            self.assertEqual("DEBUG", result["level"])
            self.assertEqual(logging.DEBUG, root.level)
        finally:
            root.setLevel(original)

    def test_open_mirror_url_allows_retroachievements_https_links(self):
        controller = FakeController({})
        api = WebSettingsAPI(controller)

        with patch("desktop.shell.web_settings.webbrowser.open") as open_url:
            result = api.open_mirror_url("https://retroachievements.org/game/123")

        self.assertTrue(result["success"])
        open_url.assert_called_once_with("https://retroachievements.org/game/123")

    def test_open_mirror_url_blocks_non_retroachievements_links(self):
        controller = FakeController({})
        api = WebSettingsAPI(controller)

        with patch("desktop.shell.web_settings.webbrowser.open") as open_url:
            result = api.open_mirror_url("https://example.com/game/123")

        self.assertFalse(result["success"])
        open_url.assert_not_called()

    def test_copy_diagnostics_returns_secret_free_support_text(self):
        controller = FakeController({})
        api = WebSettingsAPI(controller)

        with patch(
            "desktop.shell.web_settings.get_platform_services",
            return_value=FakePlatform(),
        ), patch(
            "desktop.shell.web_settings.get_config_dir",
            return_value="CONFIG_DIR",
        ), patch("desktop.shell.web_settings.get_log_dir", return_value="LOG_DIR"):
            result = api.copy_diagnostics()

        self.assertIn("CheevoPresence", result["text"])
        self.assertIn("config_dir=CONFIG_DIR", result["text"])
        self.assertIn("log_dir=LOG_DIR", result["text"])
        self.assertNotIn("apikey", result["text"].lower())

    def test_role_badge_style_supports_reference_tiers(self):
        self.assertEqual("#e0a93c", role_badge_style("junior_developer")["accent"])
        self.assertEqual("#5cc081", role_badge_style("developer")["accent"])
        self.assertEqual("#b0a0f0", role_badge_style("code_reviewer")["accent"])
        self.assertEqual("#6fcfe2", role_badge_style("moderator")["accent"])
        self.assertEqual("#e86666", role_badge_style("admin")["accent"])
        self.assertEqual("#e0a93c", role_badge_style("unknown")["accent"])


if __name__ == "__main__":
    unittest.main()
