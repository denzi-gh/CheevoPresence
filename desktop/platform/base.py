"""Base contracts for desktop platform adapters."""

import os
import subprocess
import sys
import webbrowser


class PlatformServices:

    startup_toggle_label = "Launch on system startup"
    settings_menu_default = False
   
    settings_window_native = True

    def protect_api_key(self, value):
        raise NotImplementedError

    def unprotect_api_key(self, value):
        raise NotImplementedError

    def get_config_dir(self, app_name, runtime_root_dir):
        return None

    def get_log_dir(self, app_name, runtime_root_dir, config_dir):
        return os.path.join(config_dir, "logs")

    def acquire_single_instance(self):
        return True

    def notify_already_running(self):
        return None

    def request_running_app_exit(self):
        return False

    def start_exit_listener(self, callback):
        return None

    def set_autostart(self, enable):
        return None

    def is_autostart_enabled(self):
        return False

    def get_tray_icon_class(self, pystray):
        return pystray.Icon

    def supports_self_update(self):
        return False

    def select_update_asset(self, assets):
        return None

    def stage_update_install(self, download_path, relaunch_args, source_pid):
        return "Automatic updates are not available on this platform yet."

    def handle_special_args(self, argv):
        return False

    def open_path(self, path):
        if not path:
            return False
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa: S606 - documented Windows file-manager open
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path], env=self.child_process_env())
            else:
                subprocess.Popen(["xdg-open", path], env=self.child_process_env())
            return True
        except Exception:
            return False

    def child_process_env(self):
        """Environment for programs we hand off to, such as a browser."""
        return os.environ.copy()

    def prepare_native_webview_environment(self):
        return None

    def open_external_url(self, url):
        """Show a URL in the user's browser."""
        return bool(webbrowser.open(url))
