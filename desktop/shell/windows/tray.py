"""Tray host and icon helpers for the Windows desktop shell."""

import logging
import os
import subprocess
import sys
import threading
import webbrowser

from PIL import Image, ImageDraw

from desktop.core.constants import (
    APP_NAME,
    APP_VERSION,
    RA_SETTINGS_URL,
    WINDOWS_SETTINGS_CLIENT_FLAG,
)
from desktop.runtime.controller import AppController
from desktop.runtime.storage import (
    APP_ICON_FILE,
    TRAY_ACTIVE_ICON_FILE,
    TRAY_ERROR_ICON_FILE,
    TRAY_INACTIVE_ICON_FILE,
)
from desktop.shell.ipc import SettingsHostService

SHUTDOWN_GRACE_SECONDS = 8
SHUTDOWN_WATCHDOG_SECONDS = 12
logger = logging.getLogger(__name__)


def create_tray_icon(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill=color, outline=(255, 255, 255, 255), width=2)
    return img


def load_icon_image(path):
    if not os.path.exists(path):
        return None
    try:
        with Image.open(path) as img:
            return img.copy()
    except Exception:  # noqa: BLE001 Pillow raises assorted errors for corrupt icons; caller falls back
        return None


class TrayApp:

    def __init__(self, controller: AppController, open_settings_on_launch=False):
        self.controller = controller
        self.icon = None
        self.platform = controller.platform
        self.worker = controller.worker
        self.controller.set_status_callback(self._on_status)
        self.open_settings_on_launch = open_settings_on_launch
        self.current_status = "disconnected"
        self.status_text = "Not running"
        self._settings_open = False
        self._settings_process = None
        self._settings_service = SettingsHostService(controller, on_quit=self.quit_app)
        self._exit_listener = None
        self._shutdown_lock = threading.Lock()
        self._shutdown_started = False
        self._shutdown_done = threading.Event()
        self._shutdown_watchdog = None
        self._fallback_colors = {
            "connected": (0, 200, 0, 255),
            "connecting": (255, 165, 0, 255),
            "disconnected": (150, 150, 150, 255),
            "error": (220, 0, 0, 255),
        }

    def _get_tray_image(self):
        icon_map = {
            "connected": TRAY_ACTIVE_ICON_FILE,
            "connecting": APP_ICON_FILE,
            "disconnected": TRAY_INACTIVE_ICON_FILE,
            "error": TRAY_ERROR_ICON_FILE,
        }
        image = load_icon_image(icon_map.get(self.current_status, APP_ICON_FILE))
        if image is not None:
            return image
        color = self._fallback_colors.get(self.current_status, (150, 150, 150, 255))
        return create_tray_icon(color)

    def _on_status(self, status, text):
        if self._shutdown_started:
            return
        self.current_status = status
        self.status_text = text
        self._update_icon()

    def _update_icon(self):
        if not self.icon or self._shutdown_started:
            return
        self.icon.icon = self._get_tray_image()
        self.icon.title = f"{APP_NAME} - {self.status_text}"
        self._update_menu()

    def _update_menu(self):
        if not self.icon:
            return
        try:
            self.icon.update_menu()
        except Exception:  # pystray teardown race; menu refresh is best-effort
            logger.debug("Tray menu update failed", exc_info=True)

    def _get_connection_action_text(self, _item=None):
        state = self.worker.get_state()
        if state.is_stopping:
            return "Stopping..."
        if state.running:
            return "Disconnect"
        return "Connect"

    def _is_connection_action_enabled(self, _item=None):
        return not self.worker.get_state().is_stopping

    def _on_toggle_connection(self, icon, item):
        if self._shutdown_started or self.worker.get_state().is_stopping:
            return
        threading.Thread(target=self._toggle_connection, daemon=True).start()

    def _toggle_connection(self):
        if self.worker.get_state().running:
            logger.info("Tray disconnect requested")
            self.controller.disconnect()
            return

        config = self.controller.load_config()
        if not config["username"] or not config["apikey"]:
            logger.info(
                (
                    "Tray connect blocked missing_credentials "
                    "username_present=%s apikey_present=%s"
                ),
                bool(config["username"]),
                bool(config["apikey"]),
            )
            self.worker.set_ra_status(False)
            self.worker.status_callback("error", "Username or API Key missing")
            self._on_settings(None, None)
            return

        logger.info("Tray connect requested")
        if not self.controller.start_saved_session():
            logger.warning("Tray connect request did not start worker")
            self._update_menu()

    def _on_settings(self, icon, item):
        if self._shutdown_started:
            return
        self.open_settings()

    def open_settings(self):
        if self._settings_process is not None and self._settings_process.poll() is None:
            return False
        command = self._settings_command()
        env = os.environ.copy()
        env.update(self._settings_service.get_launch_env())
        try:
            self._settings_process = subprocess.Popen(
                command,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            logger.exception("Windows settings client launch failed")
            self._settings_process = None
            self._settings_open = False
            return False
        logger.info("Windows settings client launched pid=%s", self._settings_process.pid)
        self._settings_open = True
        return False

    def _settings_command(self):
        # Address and auth token travel via get_launch_env() only
        if getattr(sys, "frozen", False):
            return [sys.executable, WINDOWS_SETTINGS_CLIENT_FLAG]
        return [sys.executable, os.path.abspath(sys.argv[0]), WINDOWS_SETTINGS_CLIENT_FLAG]

    def _on_settings_closed(self):
        self._settings_open = False

    def _stop_settings_client(self, timeout=2):
        process = self._settings_process
        self._settings_process = None
        self._settings_open = False
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)

    def quit_app(self):
        with self._shutdown_lock:
            if self._shutdown_started:
                return
            self._shutdown_started = True

        logger.info("Windows tray shutdown requested")
        self.controller.set_status_callback(None)
        self._shutdown_watchdog = threading.Timer(
            SHUTDOWN_WATCHDOG_SECONDS,
            self._force_exit,
        )
        self._shutdown_watchdog.daemon = True
        self._shutdown_watchdog.start()

        shutdown_thread = threading.Thread(
            target=self._shutdown_and_exit,
            daemon=False,
        )
        shutdown_thread.start()

    def _shutdown_and_exit(self):
        try:
            if self.icon:
                try:
                    self.icon.stop()
                    logger.info("Windows tray icon stopped")
                except Exception:
                    logger.exception("Windows tray icon stop failed")
            self._stop_settings_client()
            self._settings_service.stop()
            stopped = self.controller.shutdown(timeout=SHUTDOWN_GRACE_SECONDS)
            logger.info("Windows tray shutdown cleanup completed stopped=%s", stopped)
        finally:
            self._shutdown_done.set()
            if self._shutdown_watchdog:
                self._shutdown_watchdog.cancel()

    def _force_exit(self):
        if not self._shutdown_done.is_set():
            logger.critical("Windows tray shutdown watchdog forcing process exit")
            os._exit(0)

    def _on_quit(self, icon, item):
        self.quit_app()

    def _get_status_text(self):
        return self.status_text

    def _on_get_api_key(self, icon, item):
        webbrowser.open(RA_SETTINGS_URL)

    def run(self):
        import pystray

        self._settings_service.start()
        icon_class = self.platform.get_tray_icon_class(pystray)
        menu = pystray.Menu(
            pystray.MenuItem(f"{APP_NAME} v{APP_VERSION}", None, enabled=False),
            pystray.MenuItem(lambda text: self._get_status_text(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                self._get_connection_action_text,
                self._on_toggle_connection,
                enabled=self._is_connection_action_enabled,
            ),
            pystray.MenuItem(
                "Settings",
                self._on_settings,
                default=self.platform.settings_menu_default,
            ),
            pystray.MenuItem("Open RA Settings (Web)", self._on_get_api_key),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._on_quit),
        )

        ico = load_icon_image(APP_ICON_FILE) or create_tray_icon((150, 150, 150, 255))

        self.icon = icon_class(APP_NAME, ico, APP_NAME, menu)
        self._exit_listener = self.platform.start_exit_listener(self.quit_app)
        self._update_icon()

        logger.info("Windows tray run started")
        self.controller.start_saved_session()
        if self.open_settings_on_launch:
            self.open_settings()

        try:
            self.icon.run()
        finally:
            self._settings_service.stop()
            self._stop_settings_client()
            logger.info("Windows tray run exited")
