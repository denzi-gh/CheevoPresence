"""Application entrypoint for the Windows desktop shell."""

import sys
import threading

from desktop.platform import get_platform_services
from desktop.runtime.controller import AppController
from desktop.shell.windows.tray import TrayApp
from desktop.shell.windows.ui import SettingsWindow

EXIT_APP_FLAG = "--exit"


def main():
    """Boot the tray app and optionally open the settings window on launch."""
    tray_mode = "--tray" in sys.argv
    platform = get_platform_services()

    if platform.handle_special_args(sys.argv):
        return

    if EXIT_APP_FLAG in sys.argv:
        platform.request_running_app_exit()
        return

    if not platform.acquire_single_instance():
        if not tray_mode:
            platform.notify_already_running()
        return

    controller = AppController(platform=platform)
    app = TrayApp(controller)

    if tray_mode:
        app.run()
    else:
        def open_initial_settings():
            app._settings_open = True
            SettingsWindow(
                controller,
                on_close=app._on_settings_closed,
                on_quit=app.quit_app,
            )

        threading.Thread(target=open_initial_settings, daemon=True).start()
        app.run()
