"""Application entrypoint for the Windows desktop shell."""

import logging
import sys

from desktop.platform import get_platform_services
from desktop.runtime.controller import AppController
from desktop.runtime.diagnostics import log_startup_diagnostics
from desktop.runtime.log_events import AREA_STARTUP, log_event
from desktop.runtime.logging_setup import setup_logging
from desktop.shell.windows.tray import TrayApp

EXIT_APP_FLAG = "--exit"
WINDOWS_SETTINGS_CLIENT_FLAG = "--windows-settings-client"
logger = logging.getLogger(__name__)


def main():
    """Boot the tray app and optionally open the settings window on launch."""
    if WINDOWS_SETTINGS_CLIENT_FLAG in sys.argv:
        flag_index = sys.argv.index(WINDOWS_SETTINGS_CLIENT_FLAG)
        from desktop.shell.settings_client import main as settings_main

        if len(sys.argv) >= flag_index + 3:
            return settings_main(sys.argv[flag_index + 1], sys.argv[flag_index + 2])
        return settings_main()

    tray_mode = "--tray" in sys.argv
    mode = "tray" if tray_mode else "settings"
    platform = get_platform_services()
    setup_logging(platform)
    log_startup_diagnostics(platform)
    log_event(logger, AREA_STARTUP, "entrypoint_started", platform="windows", mode=mode)

    if platform.handle_special_args(sys.argv):
        log_event(logger, AREA_STARTUP, "platform_helper_handled", platform="windows")
        return

    if EXIT_APP_FLAG in sys.argv:
        requested = platform.request_running_app_exit()
        log_event(logger, AREA_STARTUP, "external_exit_requested", success=requested)
        return

    if not platform.acquire_single_instance():
        log_event(logger, AREA_STARTUP, "duplicate_instance_blocked", mode=mode)
        if not tray_mode:
            platform.notify_already_running()
        return

    log_event(logger, AREA_STARTUP, "single_instance_acquired", mode=mode)
    controller = AppController(platform=platform)
    app = TrayApp(controller, open_settings_on_launch=not tray_mode)

    app.run()
