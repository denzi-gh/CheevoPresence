"""Native Linux StatusNotifier/AppIndicator shell."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import webbrowser

from PIL import Image, ImageDraw

from desktop.core.constants import APP_NAME, APP_VERSION, RA_SETTINGS_URL
from desktop.platform.linux import get_runtime_dir
from desktop.runtime.controller import AppController
from desktop.runtime.log_events import AREA_SHUTDOWN, AREA_TRAY, log_event
from desktop.runtime.storage import (
    APP_ICON_PNG_FILE,
    TRAY_ACTIVE_ICON_FILE,
    TRAY_ERROR_ICON_FILE,
    TRAY_INACTIVE_ICON_FILE,
    GENERATED_MENU_BAR_TEMPLATE_ICON_FILE,
    MENU_BAR_TEMPLATE_ICON_FILE,
)
from desktop.shell.ipc import SettingsHostService

SHUTDOWN_GRACE_SECONDS = 8
logger = logging.getLogger(__name__)


class LinuxTrayUnavailable(RuntimeError):
    """Raised when the native Linux indicator stack cannot be loaded."""


def _load_indicator_modules():
    """Load Gtk and Ayatana/AppIndicator lazily so headless CI can import this file."""
    try:
        import gi

        try:
            import gi.overrides

            original_deprecated_attr = gi.overrides.deprecated_attr

            def safe_deprecated_attr(namespace, attr, replacement):
                if namespace == "GLib" and attr == "unix_signal_add_full":
                    return
                original_deprecated_attr(namespace, attr, replacement)

            gi.overrides.deprecated_attr = safe_deprecated_attr
        except Exception:
            original_deprecated_attr = None

        try:
            gi.require_version("Gtk", "3.0")
            from gi.repository import GLib, Gtk
        finally:
            if original_deprecated_attr is not None:
                gi.overrides.deprecated_attr = original_deprecated_attr

        app_indicator = None
        ayatana_loaded = False
        appindicator_loaded = False
        try:
            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3 as app_indicator

            ayatana_loaded = True
        except (ImportError, ValueError):
            pass

        if app_indicator is None:
            try:
                gi.require_version("AppIndicator3", "0.1")
                from gi.repository import AppIndicator3 as app_indicator

                appindicator_loaded = True
            except (ImportError, ValueError):
                pass
    except Exception as exc:
        raise LinuxTrayUnavailable(str(exc) or "Linux tray backend unavailable.") from exc

    log_event(
        logger,
        AREA_TRAY,
        "modules_loaded",
        gtk=True,
        ayatana=ayatana_loaded,
        appindicator=appindicator_loaded,
        statusicon=hasattr(Gtk, "StatusIcon"),
    )
    return Gtk, GLib, app_indicator


def _select_linux_tray_backend(Gtk, AppIndicator, session_type=None):
    """Choose the native Linux tray backend for this desktop session."""
    has_status_icon = hasattr(Gtk, "StatusIcon")
    has_indicator = AppIndicator is not None

    if has_indicator:
        return "appindicator"
    if has_status_icon:
        return "statusicon"
    raise LinuxTrayUnavailable("No AppIndicator or GTK StatusIcon tray backend is available.")


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
        log_event(
            logger,
            AREA_TRAY,
            "template_icon_generation_failed",
            level=logging.WARNING,
            exc_info=True,
        )
    return APP_ICON_PNG_FILE


def _icon_cache_matches_source(output_path, source_path, source_marker_path):
    if not (
        os.path.exists(output_path)
        and os.path.exists(source_marker_path)
        and os.path.getmtime(output_path) >= os.path.getmtime(source_path)
    ):
        return False
    try:
        with open(source_marker_path, "r", encoding="utf-8") as handle:
            return handle.read() == os.path.abspath(source_path)
    except OSError:
        return False


def _png_copy_for_icon(source_path, name):
    """Return a PNG copy of an icon file for Linux tray APIs."""
    output_path = os.path.join(get_runtime_dir(), f"{name}.png")
    source_marker_path = f"{output_path}.source"
    expected_source = os.path.abspath(source_path)
    if _icon_cache_matches_source(output_path, source_path, source_marker_path):
        return output_path
    os.makedirs(os.path.dirname(output_path), mode=0o700, exist_ok=True)
    tmp_path = f"{output_path}.tmp"
    tmp_marker_path = f"{source_marker_path}.tmp"
    with Image.open(source_path) as image:
        image.convert("RGBA").resize((64, 64), Image.LANCZOS).save(tmp_path, format="PNG")
    os.replace(tmp_path, output_path)
    with open(tmp_marker_path, "w", encoding="utf-8") as handle:
        handle.write(expected_source)
    os.replace(tmp_marker_path, source_marker_path)
    return output_path


def _indicator_icon_from_path(path):
    """Return the icon theme directory and name for AppIndicator APIs."""
    icon_dir = os.path.dirname(path)
    icon_name = os.path.splitext(os.path.basename(path))[0]
    return icon_dir, icon_name, path


def get_linux_status_icon_path(status):
    """Return a Windows-like colored tray icon path for GTK StatusIcon."""
    icon_map = {
        "connected": TRAY_ACTIVE_ICON_FILE,
        "connecting": APP_ICON_PNG_FILE,
        "disconnected": TRAY_INACTIVE_ICON_FILE,
        "error": TRAY_ERROR_ICON_FILE,
    }
    source_path = icon_map.get(status, APP_ICON_PNG_FILE)
    if os.path.exists(source_path):
        try:
            return _png_copy_for_icon(source_path, f"linux-tray-{status}")
        except Exception:
            log_event(
                logger,
                AREA_TRAY,
                "colored_icon_conversion_failed",
                level=logging.WARNING,
                exc_info=True,
            )
    return get_linux_tray_icon_path()


def get_linux_indicator_icon(status):
    """Return a named PNG icon suitable for StatusNotifier/AppIndicator."""
    return _indicator_icon_from_path(get_linux_status_icon_path(status))


class LinuxIndicatorApp:
    """Own the native Linux indicator, settings window, and runtime lifecycle."""

    def __init__(self, controller: AppController, open_settings_on_launch=True):
        self.Gtk, self.GLib, self.AppIndicator = _load_indicator_modules()
        self.backend = _select_linux_tray_backend(self.Gtk, self.AppIndicator)
        self.controller = controller
        self.worker = controller.worker
        self.controller.set_status_callback(self._on_status)
        self.open_settings_on_launch = open_settings_on_launch
        self.current_status = "disconnected"
        self.status_text = "Not running"
        self.indicator = None
        self.status_icon = None
        self.menu = None
        self.version_item = None
        self.status_item = None
        self.connection_item = None
        self._settings_open = False
        self._settings_process = None
        self._settings_service = SettingsHostService(controller, on_quit=self.quit_app)
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
        icon_dir, icon_name, _icon_path = get_linux_indicator_icon(self.current_status)
        category = self.AppIndicator.IndicatorCategory.APPLICATION_STATUS
        if hasattr(self.AppIndicator.Indicator, "new_with_path"):
            indicator = self.AppIndicator.Indicator.new_with_path(
                APP_NAME,
                icon_name,
                category,
                icon_dir,
            )
        else:
            indicator = self.AppIndicator.Indicator.new(APP_NAME, icon_name, category)
            if hasattr(indicator, "set_icon_theme_path"):
                indicator.set_icon_theme_path(icon_dir)
        self._set_indicator_icon(indicator, self.current_status)
        if hasattr(indicator, "set_title"):
            indicator.set_title(APP_NAME)
        indicator.set_menu(self._build_menu())
        indicator.set_status(self.AppIndicator.IndicatorStatus.ACTIVE)
        return indicator

    def _set_indicator_icon(self, indicator, status):
        """Refresh the AppIndicator icon using a theme path plus icon name."""
        icon_dir, icon_name, _icon_path = get_linux_indicator_icon(status)
        if hasattr(indicator, "set_icon_theme_path"):
            indicator.set_icon_theme_path(icon_dir)
        if hasattr(indicator, "set_icon_full"):
            indicator.set_icon_full(icon_name, APP_NAME)
        else:
            indicator.set_icon(icon_name)

    def _log_icon_resolved(self, icon_path):
        """Log which tray icon file was resolved for the current status."""
        log_event(
            logger,
            AREA_TRAY,
            "icon_resolved",
            status=self.current_status,
            icon_path=icon_path,
            exists=os.path.exists(icon_path),
        )

    def _create_status_icon(self):
        """Create a GTK StatusIcon tray item for classic Linux panels."""
        icon_path = get_linux_status_icon_path(self.current_status)
        self._log_icon_resolved(icon_path)
        status_icon = self.Gtk.StatusIcon.new_from_file(icon_path)
        status_icon.set_title(APP_NAME)
        status_icon.set_tooltip_text(f"{APP_NAME} - {self.status_text}")
        status_icon.set_visible(True)
        status_icon.connect("popup-menu", self._on_status_icon_popup)
        status_icon.connect("activate", lambda *_args: self.open_settings())
        self._build_menu()
        self.GLib.timeout_add(1500, self._check_status_icon_embedded, status_icon)
        return status_icon

    def _check_status_icon_embedded(self, status_icon):
        """Warn when the desktop never embedded the GTK StatusIcon tray item."""
        try:
            embedded = bool(status_icon.is_embedded())
        except Exception:
            return False
        if embedded:
            log_event(logger, AREA_TRAY, "statusicon_embedded", embedded=True)
        else:
            log_event(
                logger,
                AREA_TRAY,
                "statusicon_not_embedded",
                level=logging.WARNING,
                reason="desktop_did_not_show_icon",
            )
        return False

    def _create_tray(self):
        """Create the selected native Linux tray backend."""
        if self.backend == "appindicator":
            try:
                log_event(logger, AREA_TRAY, "backend_selected", backend="appindicator")
                icon_dir, _icon_name, icon_path = get_linux_indicator_icon(self.current_status)
                self._log_icon_resolved(icon_path)
                self.indicator = self._create_indicator()
                return
            except Exception as exc:
                if not hasattr(self.Gtk, "StatusIcon"):
                    raise LinuxTrayUnavailable(
                        str(exc) or "AppIndicator tray backend failed."
                    ) from exc
                log_event(
                    logger,
                    AREA_TRAY,
                    "fallback",
                    level=logging.WARNING,
                    exc_info=True,
                    to="statusicon",
                    error_type=exc.__class__.__name__,
                    **{"from": "appindicator"},
                )

        if hasattr(self.Gtk, "StatusIcon"):
            log_event(logger, AREA_TRAY, "backend_selected", backend="statusicon")
            self.status_icon = self._create_status_icon()
            return
        raise LinuxTrayUnavailable("No AppIndicator or GTK StatusIcon tray backend is available.")

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
        if self.indicator is not None:
            self._set_indicator_icon(self.indicator, self.current_status)
        if self.status_icon is not None:
            self.status_icon.set_from_file(get_linux_status_icon_path(self.current_status))
            self.status_icon.set_tooltip_text(f"{APP_NAME} - {self.status_text}")

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
            log_event(logger, AREA_TRAY, "disconnect_requested")
            self.controller.disconnect()
            self.GLib.idle_add(self._update_menu_status)
            return

        config = self.controller.load_config()
        if not config["username"] or not config["apikey"]:
            log_event(
                logger,
                AREA_TRAY,
                "connect_blocked",
                reason="missing_credentials",
                username_present=bool(config["username"]),
                apikey_present=bool(config["apikey"]),
            )
            self.worker.set_ra_status(False)
            self.worker.status_callback("error", "Username or API Key missing")
            self.GLib.idle_add(self.open_settings)
            return

        log_event(logger, AREA_TRAY, "connect_requested")
        if not self.controller.start_saved_session():
            log_event(
                logger,
                AREA_TRAY,
                "connect_no_worker",
                level=logging.WARNING,
            )
            self.GLib.idle_add(self._update_menu_status)

    def _on_settings(self, *_args):
        """Open the settings window once, even if clicked repeatedly."""
        self.open_settings()

    def open_settings(self):
        """Launch the shared Tk settings window as a companion process."""
        if self._shutdown_started:
            return False
        if self._settings_process is not None and self._settings_process.poll() is None:
            return False
        command = self._settings_command()
        env = os.environ.copy()
        env.update(self._settings_service.get_launch_env())
        try:
            self._settings_process = subprocess.Popen(command, env=env)
        except Exception:
            logger.exception("Linux settings client launch failed")
            self._settings_process = None
            return False
        self._settings_open = True
        return False

    def _settings_command(self):
        """Return the command for the companion settings client."""
        args = [
            "--linux-settings-client",
            self._settings_service.address,
            self._settings_service.auth_token,
        ]
        if getattr(sys, "frozen", False):
            return [sys.executable, *args]
        return [sys.executable, os.path.abspath(sys.argv[0]), *args]

    def _on_settings_closed(self):
        """Allow the settings window to be reopened after it closes."""
        self._settings_open = False

    def _stop_settings_client(self, timeout=2):
        """Stop the companion settings process if it is still open."""
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

    def _on_get_api_key(self, *_args):
        """Open the RetroAchievements web settings page."""
        webbrowser.open(RA_SETTINGS_URL)

    def _on_quit(self, *_args):
        """Handle the native indicator quit command."""
        self.quit_app()

    def _on_status_icon_popup(self, status_icon, button, activate_time):
        """Open the classic GTK tray context menu."""
        self._update_menu_status()
        self.menu.popup(
            None,
            None,
            self.Gtk.StatusIcon.position_menu,
            status_icon,
            button,
            activate_time,
        )

    def quit_app(self):
        """Stop monitoring and exit the native indicator app."""
        with self._shutdown_lock:
            if self._shutdown_started:
                return
            self._shutdown_started = True
        log_event(logger, AREA_SHUTDOWN, "indicator_shutdown_requested")
        self.controller.set_status_callback(None)
        threading.Thread(target=self._shutdown_and_exit, daemon=False).start()

    def _shutdown_and_exit(self):
        """Finish shutdown off the GTK thread before quitting the main loop."""
        try:
            self._stop_settings_client()
            stopped = self.controller.shutdown(timeout=SHUTDOWN_GRACE_SECONDS)
            log_event(logger, AREA_SHUTDOWN, "indicator_cleanup_completed", stopped=stopped)
        finally:
            self.GLib.idle_add(self._finish_quit)

    def _finish_quit(self):
        """Hide the indicator and stop the GTK main loop."""
        if self.indicator is not None:
            self.indicator.set_status(self.AppIndicator.IndicatorStatus.PASSIVE)
        if self.status_icon is not None:
            self.status_icon.set_visible(False)
        self.Gtk.main_quit()
        return False

    def run(self):
        """Start the native indicator loop and auto-connect if config exists."""
        self._settings_service.start()
        self._create_tray()
        self._exit_listener = self.controller.platform.start_exit_listener(self.quit_app)
        log_event(logger, AREA_TRAY, "run_started", backend=self.backend)
        self.controller.start_saved_session()
        if self.open_settings_on_launch:
            self.GLib.idle_add(self.open_settings)
        self.Gtk.main()
        self._settings_service.stop()
        self._stop_settings_client()
        log_event(logger, AREA_TRAY, "run_exited")
