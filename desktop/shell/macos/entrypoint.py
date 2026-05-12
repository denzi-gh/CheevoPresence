"""Application entrypoint for the macOS menu-bar shell."""

import logging
import sys

from desktop.platform import get_platform_services
from desktop.runtime.controller import AppController
from desktop.runtime.logging_setup import setup_logging
from desktop.shell.macos.menu_bar import MacOSMenuBarApp

EXIT_APP_FLAG = "--exit"
logger = logging.getLogger(__name__)


def main():
    """Boot the macOS menu-bar app and optionally open Settings on launch."""
    tray_mode = "--tray" in sys.argv
    platform = get_platform_services()
    setup_logging(platform)
    logger.info(
        "macOS entrypoint started mode=%s frozen=%s",
        "tray" if tray_mode else "settings",
        bool(getattr(sys, "frozen", False)),
    )

    if platform.handle_special_args(sys.argv):
        logger.info("macOS platform helper mode handled")
        return

    if EXIT_APP_FLAG in sys.argv:
        requested = platform.request_running_app_exit()
        logger.info("macOS external exit requested success=%s", requested)
        return

    if not platform.acquire_single_instance():
        logger.info(
            "macOS duplicate instance blocked mode=%s",
            "tray" if tray_mode else "settings",
        )
        if not tray_mode:
            platform.notify_already_running()
        return

    logger.info(
        "macOS single instance acquired mode=%s",
        "tray" if tray_mode else "settings",
    )
    controller = AppController(platform=platform)
    app = MacOSMenuBarApp(
        controller,
        open_settings_on_launch=not tray_mode,
    )
    app.run()
