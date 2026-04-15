"""Tray host and icon helpers for the Windows desktop shell."""

import os
import threading
import webbrowser

from PIL import Image, ImageDraw

from desktop.core.constants import APP_NAME, APP_VERSION, RA_SETTINGS_URL
from desktop.runtime.controller import AppController
from desktop.runtime.storage import (
    APP_ICON_FILE,
    TRAY_ACTIVE_ICON_FILE,
    TRAY_ERROR_ICON_FILE,
    TRAY_INACTIVE_ICON_FILE,
)
from desktop.shell.windows.ui import SettingsWindow


def create_tray_icon(color):
    """Create a simple fallback tray icon as a colored circle."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill=color, outline=(255, 255, 255, 255), width=2)
    return img


def load_icon_image(path):
    """Load a tray icon from disk without keeping the file open."""
    if not os.path.exists(path):
        return None
    try:
        with Image.open(path) as img:
            return img.copy()
    except Exception:
        return None


class TrayApp:
    """Own the tray icon, worker lifetime, and settings window entrypoints."""

    def __init__(self, controller: AppController):
        self.controller = controller
        self.icon = None
        self.platform = controller.platform
        self.worker = controller.worker
        self.controller.set_status_callback(self._on_status)
        self.current_status = "disconnected"
        self.status_text = "Not running"
        self._settings_open = False
        self._exit_listener = None
        self._fallback_colors = {
            "connected": (0, 200, 0, 255),
            "connecting": (255, 165, 0, 255),
            "disconnected": (150, 150, 150, 255),
            "error": (220, 0, 0, 255),
        }

    def _get_tray_image(self):
        """Pick the best tray image for the current connection state."""
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
        """Mirror worker status changes into the tray presentation."""
        self.current_status = status
        self.status_text = text
        self._update_icon()

    def _update_icon(self):
        """Refresh the live tray icon and title if the tray is running."""
        if not self.icon:
            return
        self.icon.icon = self._get_tray_image()
        self.icon.title = f"{APP_NAME} - {self.status_text}"
        self._update_menu()

    def _update_menu(self):
        """Refresh dynamic tray menu labels such as Connect/Disconnect."""
        if not self.icon:
            return
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def _get_connection_action_text(self, _item=None):
        """Return the tray action label for the current worker lifecycle."""
        if self.worker.is_stopping():
            return "Stopping..." 
        if self.worker.running:
            return "Disconnect"
        return "Connect"

    def _is_connection_action_enabled(self, _item=None):
        """Disable the tray connect action while the worker is shutting down."""
        return not self.worker.is_stopping()

    def _on_toggle_connection(self, icon, item):
        """Connect or disconnect directly from the tray context menu."""
        if self.worker.is_stopping():
            return
        threading.Thread(target=self._toggle_connection, daemon=True).start()

    def _toggle_connection(self):
        """Run the connect/disconnect action without blocking the tray menu."""
        if self.worker.running:
            self.controller.disconnect()
            return

        config = self.controller.load_config()
        if not config["username"] or not config["apikey"]:
            self.worker.set_ra_status(False)
            self.worker.status_callback("error", "Username or API Key missing")
            self._on_settings(None, None)
            return

        if not self.controller.start_saved_session():
            self._update_menu()

    def _on_settings(self, icon, item):
        """Open the settings window once, even if the menu is clicked repeatedly."""
        if self._settings_open:
            return
        self._settings_open = True
        threading.Thread(target=self._show_settings_window, daemon=True).start()

    def _show_settings_window(self):
        """Launch the settings window on a dedicated thread."""
        try:
            SettingsWindow(
                self.controller,
                on_close=self._on_settings_closed,
                on_quit=self.quit_app,
            )
        except Exception:
            self._settings_open = False

    def _on_settings_closed(self):
        """Allow the settings window to be reopened after it closes."""
        self._settings_open = False

    def quit_app(self):
        """Stop monitoring and exit the tray host."""
        self.controller.shutdown()
        if self.icon:
            self.icon.stop()

    def _on_quit(self, icon, item):
        """Handle the tray quit command."""
        self.quit_app()

    def _get_status_text(self):
        """Expose the current status string to the tray menu."""
        return self.status_text

    def _on_get_api_key(self, icon, item):
        """Open the RetroAchievements web settings page."""
        webbrowser.open(RA_SETTINGS_URL)

    def run(self):
        """Start the tray loop and auto-connect if a valid config exists."""
        import pystray

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

        self.controller.start_saved_session()

        self.icon.run()
