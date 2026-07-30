import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from desktop.core.constants import APP_NAME
from desktop.platform import linux
from desktop.platform.base import PlatformServices
from desktop.platform.linux import host_process_env
from desktop.runtime.storage import get_log_dir as get_runtime_log_dir


def _reset_linux_module_state():
    handle = linux._single_instance_handle
    if handle is not None:
        try:
            handle.close()
        except OSError:
            pass
    linux._single_instance_handle = None

    stop_event = linux._exit_listener_stop_event
    if stop_event is not None:
        stop_event.set()
    listener = linux._exit_listener_socket
    if listener is not None:
        try:
            listener.close()
        except OSError:
            pass
    thread = linux._exit_listener_thread
    if thread is not None:
        thread.join(timeout=0.5)
    linux._exit_listener_socket = None
    linux._exit_listener_thread = None
    linux._exit_listener_stop_event = None


class LinuxPlatformTests(unittest.TestCase):
    def tearDown(self):
        _reset_linux_module_state()

    def test_xdg_paths_are_used(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_home = os.path.join(tmpdir, "config")
            state_home = os.path.join(tmpdir, "state")
            runtime_home = os.path.join(tmpdir, "run")
            cache_home = os.path.join(tmpdir, "cache")
            with mock.patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": config_home,
                    "XDG_STATE_HOME": state_home,
                    "XDG_RUNTIME_DIR": runtime_home,
                    "XDG_CACHE_HOME": cache_home,
                },
            ):
                self.assertEqual(
                    os.path.join(config_home, APP_NAME),
                    linux.get_config_dir(),
                )
                self.assertEqual(
                    os.path.join(state_home, APP_NAME, "logs"),
                    linux.get_log_dir(),
                )
                self.assertEqual(
                    os.path.join(runtime_home, APP_NAME),
                    linux.get_runtime_dir(),
                )

    def test_runtime_dir_falls_back_to_cache_home(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_home = os.path.join(tmpdir, "cache")
            with mock.patch.dict(
                os.environ,
                {
                    "XDG_RUNTIME_DIR": "",
                    "XDG_CACHE_HOME": cache_home,
                },
            ):
                self.assertEqual(
                    os.path.join(cache_home, APP_NAME),
                    linux.get_runtime_dir(),
                )

    def test_relative_xdg_values_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_home = os.path.join(tmpdir, "cache")
            with mock.patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": "relative-config",
                    "XDG_STATE_HOME": "relative-state",
                    "XDG_RUNTIME_DIR": "relative-runtime",
                    "XDG_CACHE_HOME": cache_home,
                },
            ):
                self.assertEqual(
                    os.path.join(
                        os.path.abspath(os.path.expanduser("~/.config")),
                        APP_NAME,
                    ),
                    linux.get_config_dir(),
                )
                self.assertEqual(
                    os.path.join(
                        os.path.abspath(os.path.expanduser("~/.local/state")),
                        APP_NAME,
                        "logs",
                    ),
                    linux.get_log_dir(),
                )
                self.assertEqual(
                    os.path.join(cache_home, APP_NAME),
                    linux.get_runtime_dir(),
                )

    def test_runtime_logging_uses_xdg_state_home(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_home = os.path.join(tmpdir, "config")
            state_home = os.path.join(tmpdir, "state")
            platform = linux.LinuxPlatformServices()
            with mock.patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": config_home,
                    "XDG_STATE_HOME": state_home,
                },
            ):
                self.assertEqual(
                    os.path.join(state_home, APP_NAME, "logs"),
                    get_runtime_log_dir(platform),
                )

    def test_autostart_desktop_file_create_status_and_remove(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_home = os.path.join(tmpdir, "config")
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": config_home}):
                self.assertFalse(linux.is_autostart_enabled())

                self.assertIsNone(linux.set_autostart(True))

                autostart_path = linux.get_autostart_path()
                self.assertTrue(os.path.exists(autostart_path))
                self.assertTrue(linux.is_autostart_enabled())
                with open(autostart_path, "r", encoding="utf-8") as handle:
                    payload = handle.read()
                self.assertIn("[Desktop Entry]", payload)
                self.assertIn("Type=Application", payload)
                self.assertIn("Exec=", payload)
                self.assertIn("--tray", payload)
                self.assertIn("X-GNOME-Autostart-enabled=true", payload)

                self.assertIsNone(linux.set_autostart(False))

                self.assertFalse(os.path.exists(autostart_path))
                self.assertFalse(linux.is_autostart_enabled())

    @unittest.skipIf(linux.fcntl is None, "fcntl is not available")
    def test_single_instance_lock_blocks_second_process(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = os.environ.copy()
            env["XDG_RUNTIME_DIR"] = os.path.join(tmpdir, "run")
            script = (
                "import sys, time; "
                "from desktop.platform import linux; "
                "sys.exit(1) if not linux.acquire_single_instance() else time.sleep(5)"
            )
            proc = subprocess.Popen(
                [sys.executable, "-c", script],
                cwd=os.getcwd(),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                lock_path = os.path.join(env["XDG_RUNTIME_DIR"], APP_NAME, "instance.lock")
                for _ in range(30):
                    if os.path.exists(lock_path):
                        break
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)
                self.assertIsNone(proc.poll())
                with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": env["XDG_RUNTIME_DIR"]}):
                    self.assertFalse(linux.acquire_single_instance())
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()

    @unittest.skipIf(os.name != "posix" or not hasattr(socket, "AF_UNIX"), "Unix sockets unavailable")
    def test_exit_socket_request_notifies_listener(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event = threading.Event()
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": os.path.join(tmpdir, "run")}):
                thread = linux.start_exit_listener(event.set)
                self.assertIsNotNone(thread)

                self.assertTrue(linux.request_running_app_exit())

                self.assertTrue(event.wait(timeout=2))
                thread.join(timeout=2)
                self.assertFalse(os.path.exists(linux.get_exit_socket_path()))

    def test_linux_self_update_is_unsupported(self):
        platform = linux.LinuxPlatformServices()

        self.assertFalse(platform.supports_self_update())
        self.assertIsNone(platform.select_update_asset([{"name": "CheevoPresence-linux"}]))
        self.assertIn(
            "not available",
            platform.stage_update_install("download", [], 123),
        )

    def test_native_webview_environment_configures_jsc(self):
        with mock.patch.dict(
            os.environ,
            {
            },
            clear=True,
        ):
            linux.LinuxPlatformServices().prepare_native_webview_environment()

            if linux.JSC_GC_SIGNAL is not None:
                self.assertEqual(str(linux.JSC_GC_SIGNAL), os.environ["JSC_SIGNAL_FOR_GC"])

    def test_native_webview_environment_keeps_a_user_selected_jsc_signal(self):
        with mock.patch.dict(os.environ, {"JSC_SIGNAL_FOR_GC": "31"}, clear=True):
            linux.LinuxPlatformServices().prepare_native_webview_environment()
            self.assertEqual("31", os.environ.get("JSC_SIGNAL_FOR_GC"))

    def test_settings_window_is_native_on_linux(self):
        platform = linux.LinuxPlatformServices()

        self.assertTrue(platform.settings_window_native)


class HostProcessEnvTests(unittest.TestCase):
    """A browser started with the PyInstaller bundle still on its library path
    may load incompatible libraries and fail to start."""

    def test_frozen_runs_restore_the_original_library_path(self):
        env = {"LD_LIBRARY_PATH": "/tmp/_MEI123", "LD_LIBRARY_PATH_ORIG": "/usr/lib"}
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(sys, "frozen", True, create=True):
                result = host_process_env()

        self.assertEqual("/usr/lib", result["LD_LIBRARY_PATH"])
        self.assertNotIn("LD_LIBRARY_PATH_ORIG", result)

    def test_frozen_runs_drop_the_bundle_path_when_there_was_no_original(self):
        with mock.patch.dict(os.environ, {"LD_LIBRARY_PATH": "/tmp/_MEI123"}, clear=False):
            with mock.patch.object(sys, "frozen", True, create=True):
                result = host_process_env()

        self.assertNotIn("LD_LIBRARY_PATH", result)


class OpenExternalUrlTests(unittest.TestCase):
    def test_base_platforms_hand_the_url_straight_to_webbrowser(self):
        services = PlatformServices()
        with mock.patch.object(
            PlatformServices, "open_path", side_effect=AssertionError("must not be used")
        ), mock.patch("webbrowser.open", return_value=True) as browser_open:
            self.assertTrue(services.open_external_url("https://retroachievements.org"))

        browser_open.assert_called_once_with("https://retroachievements.org")

    def test_linux_routes_through_open_path_and_falls_back(self):
        services = linux.LinuxPlatformServices()

        with mock.patch.object(
            services, "open_path", return_value=True
        ) as open_path, mock.patch("webbrowser.open") as browser_open:
            self.assertTrue(services.open_external_url("https://retroachievements.org"))
        open_path.assert_called_once_with("https://retroachievements.org")
        browser_open.assert_not_called()

        with mock.patch.object(services, "open_path", return_value=False), mock.patch(
            "webbrowser.open", return_value=True
        ) as browser_open:
            self.assertTrue(services.open_external_url("https://retroachievements.org"))
        browser_open.assert_called_once_with("https://retroachievements.org")


if __name__ == "__main__":
    unittest.main()
