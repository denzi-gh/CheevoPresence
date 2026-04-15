"""Base contracts for desktop platform adapters."""


class PlatformServices:
    """Describe the OS-specific hooks the desktop runtime depends on."""

    startup_toggle_label = "Launch on system startup"
    settings_menu_default = False

    def protect_api_key(self, value):
        """Protect an API key before it is written to disk."""
        raise NotImplementedError

    def unprotect_api_key(self, value):
        """Restore a previously protected API key back to plain text."""
        raise NotImplementedError

    def get_config_dir(self, app_name, runtime_root_dir):
        """Return the preferred config directory for this platform."""
        return None

    def acquire_single_instance(self):
        """Claim the single-instance lock for the running app."""
        return True

    def notify_already_running(self):
        """Tell the user that another instance is already running."""
        return None

    def request_running_app_exit(self):
        """Ask an already-running app instance to shut down."""
        return False

    def start_exit_listener(self, callback):
        """Start listening for external shutdown requests."""
        return None

    def set_autostart(self, enable):
        """Enable or disable launch at login for the current platform."""
        return None

    def is_autostart_enabled(self):
        """Return whether launch at login is currently enabled."""
        return False

    def get_tray_icon_class(self, pystray):
        """Return the tray icon class that best matches platform behavior."""
        return pystray.Icon

    def supports_self_update(self):
        """Return whether the current runtime can replace itself automatically."""
        return False

    def select_update_asset(self, assets):
        """Pick the preferred release asset for this platform from a GitHub release."""
        return None

    def stage_update_install(self, download_path, relaunch_args, source_pid):
        """Prepare a downloaded update to replace the current app after exit."""
        return "Automatic updates are not available on this platform yet."

    def handle_special_args(self, argv):
        """Handle any platform-specific helper mode before normal app startup."""
        return False
