import http.client
import os
import tempfile
import threading
import unittest
import logging
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from desktop.runtime.controller import ConnectResult, UpdateStatus
from desktop.runtime.state import MirroredPresence, WorkerState
from desktop.shell.web_settings import (
    WebSettingsAPI,
    WebSettingsWindow,
    open_external_url,
    role_badge_style,
)


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
    def __init__(self, config, update_status=None):
        self.config = dict(config)
        self.worker = FakeWorker()
        self.platform = FakePlatform()
        self.connected_config = None
        self.saved_config = None
        self.disconnected = False
        self.update_status = update_status or UpdateStatus()

    def load_config(self):
        return dict(self.config)

    def get_update_status(self):
        return self.update_status

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
                "show_developer_sets_button": False,
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
        self.assertFalse(controller.connected_config["show_developer_sets_button"])

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
                "show_developer_sets_button": True,
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
                    "show_developer_sets_button": False,
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
        self.assertFalse(controller.saved_config["show_developer_sets_button"])
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

    def test_state_payload_exposes_latest_update_version(self):
        controller = FakeController(
            {},
            update_status=UpdateStatus(
                checked=True,
                available=True,
                current_version="1.2.0",
                latest_version="1.3.1",
                can_self_install=True,
            ),
        )

        state = WebSettingsAPI(controller).get_state()

        self.assertTrue(state["update_status"]["available"])
        self.assertEqual("1.3.1", state["update_status"]["latest_version"])
        self.assertTrue(state["update_status"]["can_self_install"])

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

    def test_connected_dev_mode_role_unlocks_developer_settings(self):
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
            ra_dev_mode=True,
        )

        state = WebSettingsAPI(controller).get_state()

        self.assertTrue(state["developer_settings_unlocked"])

    def test_connected_without_dev_mode_role_ignores_stale_dev_mode_unlock(self):
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
            ra_dev_mode=False,
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
                "show_developer_sets_button": False,
            }
        )
        api = WebSettingsAPI(controller)

        result = api.save_config(
            {
                "use_retroachievements_developer_titles": True,
                "show_developer_sets_button": True,
            }
        )

        self.assertTrue(result["success"])
        self.assertFalse(
            controller.saved_config["use_retroachievements_developer_titles"]
        )
        self.assertFalse(controller.saved_config["show_developer_sets_button"])

    def test_authorized_save_preserves_developer_title_setting_while_running(self):
        controller = FakeController(
            {
                "username": "user",
                "apikey": "key",
                "dev_mode": True,
                "use_retroachievements_developer_titles": True,
                "show_developer_sets_button": True,
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

        result = api.save_config(
            {
                "use_retroachievements_developer_titles": False,
                "show_developer_sets_button": False,
            }
        )

        self.assertTrue(result["success"])
        self.assertTrue(
            controller.saved_config["use_retroachievements_developer_titles"]
        )
        self.assertTrue(controller.saved_config["show_developer_sets_button"])

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

        with patch(
            "desktop.shell.web_settings.open_external_url",
            return_value=True,
        ) as open_url:
            result = api.open_mirror_url("https://retroachievements.org/game/123")

        self.assertTrue(result["success"])
        open_url.assert_called_once_with("https://retroachievements.org/game/123")

    def test_open_mirror_url_blocks_non_retroachievements_links(self):
        controller = FakeController({})
        api = WebSettingsAPI(controller)

        with patch(
            "desktop.shell.web_settings.open_external_url",
            return_value=True,
        ) as open_url:
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
        self.assertEqual("#d98fe6", role_badge_style("event_manager")["accent"])
        self.assertEqual("#f28d4f", role_badge_style("artist")["accent"])
        self.assertEqual("#f2d35c", role_badge_style("play_tester")["accent"])
        self.assertEqual("#7dc5ff", role_badge_style("writer")["accent"])
        self.assertEqual("#b0a0f0", role_badge_style("code_reviewer")["accent"])
        self.assertEqual("#6fcfe2", role_badge_style("moderator")["accent"])
        self.assertEqual("#e86666", role_badge_style("admin")["accent"])
        self.assertEqual("#e0a93c", role_badge_style("unknown")["accent"])

    def test_role_badge_icons_match_expected_tiers(self):
        expected = {
            "junior_developer": "code",
            "developer": "code",
            "code_reviewer": "search",
            "moderator": "shield",
            "event_manager": "star",
            "artist": "palette",
            "play_tester": "controller",
            "writer": "pen",
        }
        for tier, icon in expected.items():
            with self.subTest(tier=tier):
                self.assertEqual(icon, role_badge_style(tier).get("icon"))

        for tier in ("admin", "unknown"):
            with self.subTest(tier=tier):
                self.assertIsNone(role_badge_style(tier).get("icon"))


class SettingsServerTests(unittest.TestCase):
    """The page is served into the user's own browser when no webview backend
    exists, so it shares an origin namespace with every other local page."""

    def setUp(self):
        with patch.object(WebSettingsWindow, "_run", lambda _self: None):
            self.window = WebSettingsWindow(FakeController({}))
        self.url = self.window._start_server()
        self.addCleanup(self.window._stop_server)
        parsed = urlparse(self.url)
        self.port = parsed.port
        self.token = parse_qs(parsed.query)["k"][0]

    def _send(self, method, path, host=None, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", host or f"127.0.0.1:{self.port}")
            for key, value in (headers or {}).items():
                conn.putheader(key, value)
            payload = (body or "").encode("utf-8")
            conn.putheader("Content-Length", str(len(payload)))
            conn.endheaders(payload)
            response = conn.getresponse()
            return response.status, response.read().decode("utf-8")
        finally:
            conn.close()

    def test_page_is_only_served_with_the_session_key(self):
        status, body = self._send("GET", f"/settings?k={self.token}")
        self.assertEqual(200, status)
        self.assertIn(self.token, body)

        for path in ("/settings", "/settings?k=deadbeef"):
            with self.subTest(path=path):
                status, body = self._send("GET", path)
                self.assertEqual(404, status)
                self.assertNotIn(self.token, body)

    def test_foreign_host_or_origin_is_rejected(self):
        status, body = self._send("GET", f"/settings?k={self.token}", host="cheevo.example")
        self.assertEqual(404, status)
        self.assertNotIn(self.token, body)

        status, _body = self._send(
            "POST",
            "/api/get_state",
            headers={"X-Cheevo-Token": self.token, "Origin": "https://cheevo.example"},
            body="{}",
        )
        self.assertEqual(403, status)

    def test_close_session_beacon_needs_the_session_key(self):
        self._send("POST", "/api/close_session?k=deadbeef")
        self.assertFalse(self.window._closed_event.is_set())

        self._send("POST", f"/api/close_session?k={self.token}")
        self.assertTrue(self.window._closed_event.is_set())

    def test_requests_refresh_the_idle_timestamp(self):
        # Keep the active session alive.
        self.window._last_request = 0.0

        status, _body = self._send(
            "POST", "/api/get_state", headers={"X-Cheevo-Token": self.token}, body="{}"
        )

        self.assertEqual(200, status)
        self.assertGreater(self.window._last_request, 0.0)


class BrowserFallbackTests(unittest.TestCase):
    def _window(self):
        with patch.object(WebSettingsWindow, "_run", lambda _self: None):
            return WebSettingsWindow(FakeController({}))

    def test_browser_session_ends_when_the_page_closes(self):
        window = self._window()
        threading.Timer(0.05, window._closed_event.set).start()

        with patch("desktop.shell.web_settings.open_external_url", return_value=True):
            window._run_in_browser("http://127.0.0.1:1/settings?k=x")

        self.assertTrue(window._closed_event.is_set())

    def test_browser_session_ends_when_the_tab_stops_polling(self):
        window = self._window()
        window._last_request = 0.0

        with patch("desktop.shell.web_settings.open_external_url", return_value=True), patch(
            "desktop.shell.web_settings.BROWSER_IDLE_TIMEOUT",
            0.0,
        ):
            window._run_in_browser("http://127.0.0.1:1/settings?k=x")

        self.assertFalse(window._closed_event.is_set())

    def test_native_window_follows_the_platform_unless_overridden(self):
        window = self._window()

        for native, env, expected in (
            (True, "", True),
            (False, "", False),
            (False, "native", True),
            (True, "browser", False),
        ):
            with self.subTest(platform_native=native, env=env):
                platform = type("P", (), {"settings_window_native": native})()
                with patch(
                    "desktop.shell.web_settings.get_platform_services",
                    return_value=platform,
                ), patch.dict(os.environ, {"CHEEVO_SETTINGS_UI": env}):
                    self.assertEqual(expected, window._native_window_allowed())

    def test_present_raises_the_window_without_ever_blocking(self):
        # present() runs from a signal handler on the GUI thread, so it must not
        # wait on pywebview's shown event.
        for shown, expect_restore in ((True, True), (False, False)):
            with self.subTest(shown=shown):
                window = self._window()
                calls = []
                event = threading.Event()
                if shown:
                    event.set()
                window.api.set_window(
                    SimpleNamespace(
                        events=SimpleNamespace(shown=event),
                        restore=lambda: calls.append("restore"),
                    )
                )

                self.assertTrue(window.present())
                self.assertEqual(["restore"] if expect_restore else [], calls)

    def test_focus_native_window_restores_the_window(self):
        window = self._window()
        calls = []
        window.api.set_window(SimpleNamespace(restore=lambda: calls.append("restore")))

        self.assertTrue(window._focus_native_window())
        self.assertEqual(["restore"], calls)

    def test_present_reopens_the_tab_when_there_is_no_native_window(self):
        window = self._window()
        window._url = "http://127.0.0.1:1/settings?k=x"

        with patch(
            "desktop.shell.web_settings.open_external_url", return_value=True
        ) as opened:
            self.assertTrue(window.present())

        opened.assert_called_once_with("http://127.0.0.1:1/settings?k=x")

    def test_missing_webview_backend_falls_back_to_the_browser(self):
        window = self._window()
        opened = []

        with patch.object(
            WebSettingsWindow,
            "_start_server",
            return_value="http://127.0.0.1:1/settings?k=x",
        ), patch.object(
            WebSettingsWindow,
            "_open_native_window",
            side_effect=RuntimeError("no GTK or QT"),
        ), patch.object(
            WebSettingsWindow, "_run_in_browser", opened.append
        ), patch.object(WebSettingsWindow, "_stop_server"):
            window._run()

        self.assertEqual(["http://127.0.0.1:1/settings?k=x"], opened)

    def test_failure_after_the_window_opened_is_not_swallowed(self):
        window = self._window()

        def fail_after_start(_self, _url, started):
            started.set()
            raise RuntimeError("window crashed")

        with patch.object(
            WebSettingsWindow,
            "_start_server",
            return_value="http://127.0.0.1:1/settings?k=x",
        ), patch.object(
            WebSettingsWindow, "_open_native_window", fail_after_start
        ), patch.object(
            WebSettingsWindow, "_run_in_browser"
        ) as run_in_browser, patch.object(WebSettingsWindow, "_stop_server"):
            with self.assertRaises(RuntimeError):
                window._run()

        run_in_browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
