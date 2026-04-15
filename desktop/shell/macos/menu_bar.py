"""Native macOS menu-bar shell built on AppKit."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import webbrowser

import objc
from AppKit import (
    NSAlert,
    NSApplication,
    NSApplicationActivateIgnoringOtherApps,
    NSApplicationActivationPolicyAccessory,
    NSColor,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSRunningApplication,
    NSStatusBar,
    NSSquareStatusItemLength,
)
from Foundation import NSObject, NSMakeSize
from PyObjCTools.AppHelper import callAfter, runEventLoop
from Quartz import CALayer

from desktop.core.constants import APP_NAME, APP_VERSION, RA_SETTINGS_URL
from desktop.platform.macos import get_exe_path
from desktop.runtime.controller import AppController
from desktop.runtime.storage import (
    APP_ICON_PNG_FILE,
    GENERATED_MENU_BAR_TEMPLATE_ICON_FILE,
    MENU_BAR_TEMPLATE_ICON_FILE,
)
from desktop.shell.entrypoint import MAC_SETTINGS_CLIENT_FLAG


def _load_template_status_image():
    """Load the preferred menu-bar template icon, with SF Symbol fallback."""
    image = None
    for candidate in (
        MENU_BAR_TEMPLATE_ICON_FILE,
        GENERATED_MENU_BAR_TEMPLATE_ICON_FILE,
        APP_ICON_PNG_FILE,
    ):
        if os.path.exists(candidate):
            image = NSImage.alloc().initWithContentsOfFile_(candidate)
            if image is not None:
                break
    if image is None and hasattr(NSImage, "imageWithSystemSymbolName_accessibilityDescription_"):
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "gamecontroller.fill",
            APP_NAME,
        )
    if image is not None:
        image.setTemplate_(True)
        image.setSize_(NSMakeSize(20, 20))
    return image


class _MenuBarDelegate(NSObject):
    """Bridge AppKit callbacks back into the Python menu-bar host."""

    def initWithOwner_(self, owner):
        self = objc.super(_MenuBarDelegate, self).init()
        if self is None:
            return None
        self.owner = owner
        return self

    def applicationDidFinishLaunching_(self, _notification):
        self.owner._application_did_finish_launching()

    def applicationShouldHandleReopen_hasVisibleWindows_(self, _app, _visible):
        self.owner.open_settings()
        return True

    def openSettings_(self, _sender):
        self.owner.open_settings()

    def openRASettings_(self, _sender):
        self.owner.open_ra_settings()

    def toggleConnection_(self, _sender):
        self.owner.toggle_connection()

    def openHelp_(self, _sender):
        self.owner.open_help()

    def quitApp_(self, _sender):
        self.owner.quit_app()


class MacOSMenuBarApp:
    """Own the menu-bar status item, settings window, and runtime lifecycle."""

    def __init__(self, controller: AppController, open_settings_on_launch=True):
        self.controller = controller
        self.worker = controller.worker
        self.controller.set_status_callback(self._on_status)
        self.open_settings_on_launch = open_settings_on_launch
        self.current_status = "disconnected"
        self.status_text = "Not running"
        self.app = None
        self.status_item = None
        self.status_menu = None
        self.status_text_item = None
        self.version_item = None
        self.connection_item = None
        self._status_badge_layer = None
        from .ipc import MacOSAppService

        self.settings_service = MacOSAppService(controller, on_quit=self.quit_app)
        self._settings_process = None
        self._delegate = None
        self._exit_listener = None
        self._shutdown_started = False
        self._shutdown_lock = threading.Lock()

    def _application_did_finish_launching(self):
        """Build the status item and start the shared runtime controller."""
        self.settings_service.start()
        self._build_status_item()
        self._exit_listener = self.controller.platform.start_exit_listener(self.quit_app)
        self._update_menu_status()
        self.controller.start_saved_session()
        if self.open_settings_on_launch:
            self.open_settings()

    def _build_status_item(self):
        """Create the menu-bar status item, icon, and menu entries."""
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSSquareStatusItemLength)
        button = self.status_item.button()
        image = _load_template_status_image()
        if image is not None:
            button.setImage_(image)
        else:
            button.setTitle_("CP")
        button.setToolTip_(APP_NAME)
        button.setWantsLayer_(True)

        self.status_menu = NSMenu.alloc().initWithTitle_(APP_NAME)
        self.version_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"{APP_NAME} v{APP_VERSION}",
            None,
            "",
        )
        self.version_item.setEnabled_(False)
        self.status_text_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            self.status_text,
            None,
            "",
        )
        self.status_text_item.setEnabled_(False)

        self.status_menu.addItem_(self.version_item)
        self.status_menu.addItem_(self.status_text_item)
        self.status_menu.addItem_(NSMenuItem.separatorItem())

        self.connection_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Connect",
            "toggleConnection:",
            "",
        )
        self.connection_item.setTarget_(self._delegate)
        self.status_menu.addItem_(self.connection_item)

        settings_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Settings",
            "openSettings:",
            "",
        )
        settings_item.setTarget_(self._delegate)
        self.status_menu.addItem_(settings_item)

        ra_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open RA Settings (Web)",
            "openRASettings:",
            "",
        )
        ra_item.setTarget_(self._delegate)
        self.status_menu.addItem_(ra_item)

        self.status_menu.addItem_(NSMenuItem.separatorItem())

        help_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Help",
            "openHelp:",
            "",
        )
        help_item.setTarget_(self._delegate)
        self.status_menu.addItem_(help_item)

        self.status_menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit",
            "quitApp:",
            "q",
        )
        quit_item.setTarget_(self._delegate)
        self.status_menu.addItem_(quit_item)
        self.status_item.setMenu_(self.status_menu)

    def _truncate_status(self, text, limit=72):
        """Trim long worker status text so the menu stays readable."""
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _on_status(self, status, text):
        """Mirror worker status changes into the menu-bar presentation."""
        self.current_status = status
        self.status_text = text
        callAfter(self._update_menu_status)

    def _update_menu_status(self):
        """Refresh the menu text and tooltip for the current runtime state."""
        if not self.status_item:
            return
        title = self._truncate_status(self.status_text)
        if self.status_text_item is not None:
            self.status_text_item.setTitle_(title)
        self._update_connection_item()
        button = self.status_item.button()
        if button is not None:
            button.setToolTip_(f"{APP_NAME} - {self.status_text}")
            self._update_status_badge(button)

    def _get_connection_action_title(self):
        """Return the menu action label for the current worker lifecycle."""
        if self.worker.is_stopping():
            return "Stopping..."
        if self.worker.running:
            return "Disconnect"
        return "Connect"

    def _update_connection_item(self):
        """Refresh the dynamic Connect/Disconnect menu item."""
        if self.connection_item is None:
            return
        self.connection_item.setTitle_(self._get_connection_action_title())
        self.connection_item.setEnabled_(not self.worker.is_stopping())

    def toggle_connection(self):
        """Connect or disconnect directly from the menu-bar context menu."""
        if self.worker.is_stopping():
            return
        threading.Thread(target=self._toggle_connection, daemon=True).start()

    def _toggle_connection(self):
        """Run the connect/disconnect action without blocking AppKit."""
        if self.worker.running:
            self.controller.disconnect()
            return

        config = self.controller.load_config()
        if not config["username"] or not config["apikey"]:
            self.worker.set_ra_status(False)
            self.worker.status_callback("error", "Username or API Key missing")
            callAfter(self.open_settings)
            return

        if not self.controller.start_saved_session():
            callAfter(self._update_menu_status)

    def _badge_color_for_status(self):
        """Return the badge color for the current runtime state, if any."""
        if self.current_status == "connected":
            return NSColor.systemGreenColor()
        if self.current_status == "error":
            return NSColor.systemRedColor()
        return None

    def _get_status_badge_layer(self, button):
        """Create the status badge layer on demand and attach it to the button."""
        button.setWantsLayer_(True)
        root_layer = button.layer()
        if root_layer is None:
            root_layer = CALayer.layer()
            button.setLayer_(root_layer)
        if root_layer is None:
            return None
        if (
            self._status_badge_layer is not None
            and self._status_badge_layer.superlayer() is root_layer
        ):
            return self._status_badge_layer
        self._status_badge_layer = None
        badge = CALayer.layer()
        badge.setHidden_(True)
        badge.setCornerRadius_(3.5)
        badge.setBorderWidth_(1.0)
        badge.setBorderColor_(NSColor.blackColor().colorWithAlphaComponent_(0.35).CGColor())
        badge.setZPosition_(10.0)
        root_layer.addSublayer_(badge)
        self._status_badge_layer = badge
        return badge

    def _update_status_badge(self, button):
        """Show a bottom-right status badge for connected or error states."""
        badge = self._get_status_badge_layer(button)
        if badge is None:
            return
        color = self._badge_color_for_status()
        if color is None:
            badge.setHidden_(True)
            return
        bounds = button.bounds()
        diameter = 7.0
        inset_x = 4.5
        inset_y = 2.5
        is_flipped = False
        try:
            is_flipped = bool(button.isFlipped())
        except Exception:
            pass
        badge_y = bounds.size.height - diameter - inset_y if is_flipped else inset_y
        badge.setFrame_(
            (
                (
                    bounds.size.width - diameter - inset_x,
                    badge_y,
                ),
                (
                    diameter,
                    diameter,
                ),
            )
        )
        badge.setBackgroundColor_(color.CGColor())
        badge.setHidden_(False)

    def open_settings(self):
        """Launch the shared Tk settings client when it is not already open."""
        if self._is_settings_process_running():
            self._focus_settings_process()
            return
        command, env = self._build_settings_command()
        self._settings_process = subprocess.Popen(
            command,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        self._focus_settings_process()

    def _build_settings_command(self):
        """Return the command used to launch the companion settings process."""
        launch_env = os.environ.copy()
        launch_env.update(self.settings_service.get_launch_env())
        exe_path = get_exe_path()
        if getattr(sys, "frozen", False):
            return [sys.executable, MAC_SETTINGS_CLIENT_FLAG], launch_env
        return [sys.executable, exe_path, MAC_SETTINGS_CLIENT_FLAG], launch_env

    def _is_settings_process_running(self):
        """Return whether the companion settings client is still active."""
        return bool(self._settings_process and self._settings_process.poll() is None)

    def _focus_settings_process(self):
        """Bring the companion settings window to the front when possible."""
        if not self._is_settings_process_running():
            return False
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(
            self._settings_process.pid
        )
        if app is None:
            return False
        app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        return True

    def _stop_settings_process(self):
        """Terminate the companion settings client if it is still running."""
        if not self._is_settings_process_running():
            self._settings_process = None
            return
        self._settings_process.terminate()
        try:
            self._settings_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._settings_process.kill()
        self._settings_process = None

    def open_ra_settings(self):
        """Open the RetroAchievements settings page in the browser."""
        webbrowser.open(RA_SETTINGS_URL)

    def open_help(self):
        """Show the hidden achievement popup from the native macOS menu."""
        alert = NSAlert.alloc().init()
        alert.setMessageText_(
            "Achievement Unlocked: neending help lmao (6942067 RA points)"
        )
        alert.runModal()

    def quit_app(self):
        """Stop the worker and exit the menu-bar app."""
        with self._shutdown_lock:
            if self._shutdown_started:
                return
            self._shutdown_started = True
        threading.Thread(target=self._shutdown_and_terminate, daemon=True).start()

    def _shutdown_and_terminate(self):
        """Finish shutdown off the AppKit thread before terminating NSApp."""
        try:
            self._stop_settings_process()
            self.settings_service.stop()
            self.controller.shutdown()
        finally:
            callAfter(NSApplication.sharedApplication().terminate_, None)

    def run(self):
        """Start the AppKit event loop for the menu-bar accessory app."""
        self.app = NSApplication.sharedApplication()
        self.app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        self._delegate = _MenuBarDelegate.alloc().initWithOwner_(self)
        self.app.setDelegate_(self._delegate)
        runEventLoop()
