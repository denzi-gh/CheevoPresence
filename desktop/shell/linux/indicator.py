"""Native Linux StatusNotifier/AppIndicator shell."""

from __future__ import annotations

import logging
import os
import threading
import webbrowser

from PIL import Image, ImageDraw

from desktop.core.constants import APP_NAME, APP_VERSION, RA_SETTINGS_URL
from desktop.platform.linux import get_runtime_dir
from desktop.runtime.controller import AppController
from desktop.runtime.storage import (
    APP_ICON_PNG_FILE,
    GENERATED_MENU_BAR_TEMPLATE_ICON_FILE,
    MENU_BAR_TEMPLATE_ICON_FILE,
)
from desktop.shell.tk_settings import TkSettingsWindow as SettingsWindow

SHUTDOWN_GRACE_SECONDS = 8
logger = logging.getLogger(__name__)


class LinuxTrayUnavailable(RuntimeError):
    """Raised when the native Linux indicator stack cannot be loaded."""


def _load_indicator_modules():
    """Load Gtk and Ayatana/AppIndicator lazily so headless CI can import this file."""
    try:
        import gi

        try:
            gi.require_version("GLibUnix", "2.0")
            from gi.repository import GLibUnix as _GLibUnix  # noqa: F401
        except (ImportError, ValueError):
            pass

        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk

        try:
            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3 as AppIndicator
        except (ImportError, ValueError):
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3 as AppIndicator
    except Exception as exc:
        raise LinuxTrayUnavailable(str(exc) or "Linux tray backend unavailable.") from exc

    return Gtk, GLib, AppIndicator


def _build_menu_trophy_mask(size):
    """Draw the same monochrome trophy silhouette used for the macOS menu bar."""
    grid_size = 24
    pixel = size // grid_size

    mask = Image.new("L", (grid_size, grid_size), 0)
    draw = ImageDraw.Draw(mask)

    draw.rectangle((7, 3, 16, 4), fill=255)
    draw.rectangle((5, 5, 18, 6), fill=255)
    draw.rectangle((6, 7, 17, 10), fill=255)
    draw.rectangle((7, 11, 16, 11), fill=255)
    draw.rectangle((8, 12, 15, 12), fill=255)

    draw.rectangle((1, 5, 5, 9), fill=255)
    draw.rectangle((2, 6, 4, 8), fill=0)
    draw.rectangle((18, 5, 22, 9), fill=255)
    draw.rectangle((19, 6, 21, 8), fill=0)

    draw.rectangle((10, 13, 13, 16), fill=255)
    draw.rectangle((9, 17, 14, 18), fill=255)
    draw.rectangle((7, 19, 16, 20), fill=255)

    return mask.resize((pixel * grid_size, pixel * grid_size), Image.NEAREST).resize(
        (size, size),
        Image.LANCZOS,
    )


def _generate_linux_template_icon():
    """Generate a Linux copy of the macOS monochrome tray icon when absent."""
    icon_path = os.path.join(get_runtime_dir(), "cheevoRP_menubar_template.png")
    if os.path.exists(icon_path):
        return icon_path
    os.makedirs(os.path.dirname(icon_path), mode=0o700, exist_ok=True)
    alpha = _build_menu_trophy_mask(256).resize((64, 64), Image.LANCZOS)
    template = Image.new("RGBA", alpha.size, (0, 0, 0, 255))
    template.putalpha(alpha)
    template.save(icon_path)
    return icon_path


def get_linux_tray_icon_path():
    """Return the macOS-style monochrome icon to use for the Linux indicator."""
    for candidate in (
        MENU_BAR_TEMPLATE_ICON_FILE,
        GENERATED_MENU_BAR_TEMPLATE_ICON_FILE,
    ):
        if os.path.exists(candidate):
            return candidate
    try:
        return _generate_linux_template_icon()
    except Exception:
        logger.warning("Linux template tray icon generation failed", exc_info=True)
    return APP_ICON_PNG_FILE


class LinuxIndicatorApp:
    """Own the native Linux indicator, settings window, and runtime lifecycle."""

    def __init__(self, controller: AppController, open_settings_on_launch=True):
        self.Gtk, self.GLib, self.AppIndicator = _load_indicator_modules()
        self.controller = controller
        self.worker = controller.worker
        self.controller.set_status_callback(self._on_status)
        self.open_settings_on_launch = open_settings_on_launch
        self.current_status = "disconnected"
        self.status_text = "Not running"
        self.indicator = None
        self.menu = None
        self.version_item = None
        self.status_item = None
        self.connection_item = None
        self._settings_open = False
        self._exit_listener = None
        self._shutdown_lock = threading.Lock()
        self._shutdown_started = False

    def _new_menu_item(self, label, handler=None, sensitive=True):
        """Create a Gtk menu item with optional activation handler."""
        item = self.Gtk.MenuItem.new_with_label(label)
        item.set_sensitive(sensitive)
        if handler is not None:
            item.connect("activate", handler)
        return item

    def _build_menu(self):
        """Create the native GTK indicator menu."""
        self.menu = self.Gtk.Menu()
        self.version_item = self._new_menu_item(
            f"{APP_NAME} v{APP_VERSION}",
            sensitive=False,
        )
        self.status_item = self._new_menu_item(self.status_text, sensitive=False)
        self.connection_item = self._new_menu_item("Connect", self._on_toggle_connection)

        self.menu.append(self.version_item)
        self.menu.append(self.status_item)
        self.menu.append(self.Gtk.SeparatorMenuItem.new())
        self.menu.append(self.connection_item)
        self.menu.append(self._new_menu_item("Settings", self._on_settings))
        self.menu.append(self._new_menu_item("Open RA Settings (Web)", self._on_get_api_key))
        self.menu.append(self.Gtk.SeparatorMenuItem.new())
        self.menu.append(self._new_menu_item("Quit", self._on_quit))
        self.menu.show_all()
        self._update_menu_status()
        return self.menu

    def _create_indicator(self):
        """Create and activate the StatusNotifier/AppIndicator item."""
        icon_path = get_linux_tray_icon_path()
        category = self.AppIndicator.IndicatorCategory.APPLICATION_STATUS
        indicator = self.AppIndicator.Indicator.new(APP_NAME, icon_path, category)
        if hasattr(indicator, "set_icon_full"):
            indicator.set_icon_full(icon_path, APP_NAME)
        else:
            indicator.set_icon(icon_path)
        if hasattr(indicator, "set_title"):
            indicator.set_title(APP_NAME)
        indicator.set_menu(self._build_menu())
        indicator.set_status(self.AppIndicator.IndicatorStatus.ACTIVE)
        return indicator

    def _truncate_status(self, text, limit=72):
        """Trim long worker status text so the menu stays readable."""
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _on_status(self, status, text):
        """Mirror worker status changes into the indicator menu."""
        if self._shutdown_started:
            return
        self.GLib.idle_add(self._apply_status, status, text)

    def _apply_status(self, status, text):
        """Apply a worker status update on the GTK thread."""
        if self._shutdown_started:
            return False
        self.current_status = status
        self.status_text = text
        self._update_menu_status()
        return False

    def _update_menu_status(self):
        """Refresh menu text and indicator title from current runtime state."""
        if self.status_item is not None:
            self.status_item.set_label(self._truncate_status(self.status_text))
        self._update_connection_item()
        if self.indicator is not None and hasattr(self.indicator, "set_title"):
            self.indicator.set_title(f"{APP_NAME} - {self.status_text}")

    def _get_connection_action_title(self):
        """Return the tray action label for the current worker lifecycle."""
        state = self.worker.get_state()
        if state.is_stopping:
            return "Stopping..."
        if state.running:
            return "Disconnect"
        return "Connect"

    def _update_connection_item(self):
        """Refresh the dynamic Connect/Disconnect menu item."""
        if self.connection_item is None:
            return
        state = self.worker.get_state()
        self.connection_item.set_label(self._get_connection_action_title())
        self.connection_item.set_sensitive(not state.is_stopping)

    def _on_toggle_connection(self, *_args):
        """Connect or disconnect directly from the native indicator menu."""
        if self._shutdown_started or self.worker.get_state().is_stopping:
            return
        threading.Thread(target=self._toggle_connection, daemon=True).start()

    def _toggle_connection(self):
        """Run the connect/disconnect action without blocking GTK."""
        if self.worker.get_state().running:
            logger.info("Linux indicator disconnect requested")
            self.controller.disconnect()
            self.GLib.idle_add(self._update_menu_status)
            return

        config = self.controller.load_config()
        if not config["username"] or not config["apikey"]:
            logger.info(
                (
                    "Linux indicator connect blocked missing_credentials "
                    "username_present=%s apikey_present=%s"
                ),
                bool(config["username"]),
                bool(config["apikey"]),
            )
            self.worker.set_ra_status(False)
            self.worker.status_callback("error", "Username or API Key missing")
            self.GLib.idle_add(self.open_settings)
            return

        logger.info("Linux indicator connect requested")
        if not self.controller.start_saved_session():
            logger.warning("Linux indicator connect request did not start worker")
            self.GLib.idle_add(self._update_menu_status)

    def _on_settings(self, *_args):
        """Open the settings window once, even if clicked repeatedly."""
        self.open_settings()

    def open_settings(self):
        """Launch the shared Tk settings window on a dedicated thread."""
        if self._shutdown_started or self._settings_open:
            return False
        self._settings_open = True
        threading.Thread(target=self._show_settings_window, daemon=True).start()
        return False

    def _show_settings_window(self):
        """Run the shared settings UI."""
        try:
            SettingsWindow(
                self.controller,
                on_close=self._on_settings_closed,
                on_quit=self.quit_app,
            )
        except Exception:
            logger.exception("Linux settings window failed")
            self._settings_open = False

    def _on_settings_closed(self):
        """Allow the settings window to be reopened after it closes."""
        self._settings_open = False

    def _on_get_api_key(self, *_args):
        """Open the RetroAchievements web settings page."""
        webbrowser.open(RA_SETTINGS_URL)

    def _on_quit(self, *_args):
        """Handle the native indicator quit command."""
        self.quit_app()

    def quit_app(self):
        """Stop monitoring and exit the native indicator app."""
        with self._shutdown_lock:
            if self._shutdown_started:
                return
            self._shutdown_started = True
        logger.info("Linux indicator shutdown requested")
        self.controller.set_status_callback(None)
        threading.Thread(target=self._shutdown_and_exit, daemon=False).start()

    def _shutdown_and_exit(self):
        """Finish shutdown off the GTK thread before quitting the main loop."""
        try:
            stopped = self.controller.shutdown(timeout=SHUTDOWN_GRACE_SECONDS)
            logger.info("Linux indicator shutdown cleanup completed stopped=%s", stopped)
        finally:
            self.GLib.idle_add(self._finish_quit)

    def _finish_quit(self):
        """Hide the indicator and stop the GTK main loop."""
        if self.indicator is not None:
            self.indicator.set_status(self.AppIndicator.IndicatorStatus.PASSIVE)
        self.Gtk.main_quit()
        return False

    def run(self):
        """Start the native indicator loop and auto-connect if config exists."""
        self.indicator = self._create_indicator()
        self._exit_listener = self.controller.platform.start_exit_listener(self.quit_app)
        logger.info("Linux indicator run started")
        self.controller.start_saved_session()
        if self.open_settings_on_launch:
            self.GLib.idle_add(self.open_settings)
        self.Gtk.main()
        logger.info("Linux indicator run exited")
