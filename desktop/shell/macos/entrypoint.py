"""Application entrypoint for the macOS menu-bar shell."""

import sys

from desktop.platform import get_platform_services
from desktop.runtime.controller import AppController
from desktop.shell.macos.menu_bar import MacOSMenuBarApp

EXIT_APP_FLAG = "--exit"


def main():
    """Boot the macOS menu-bar app and optionally open Settings on launch."""
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
    app = MacOSMenuBarApp(
        controller,
        open_settings_on_launch=not tray_mode,
    )
    app.run()
