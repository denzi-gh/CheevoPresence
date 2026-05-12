"""Application entrypoint for the Windows desktop shell."""

import logging
import sys
import threading

from desktop.platform import get_platform_services
from desktop.runtime.controller import AppController
from desktop.runtime.logging_setup import setup_logging
from desktop.shell.windows.tray import TrayApp
from desktop.shell.windows.ui import SettingsWindow

EXIT_APP_FLAG = "--exit"
logger = logging.getLogger(__name__)


def main():
    """Boot the tray app and optionally open the settings window on launch."""
    tray_mode = "--tray" in sys.argv
    platform = get_platform_services()
    setup_logging(platform)
    logger.info(
        "Windows entrypoint started mode=%s frozen=%s",
        "tray" if tray_mode else "settings",
        bool(getattr(sys, "frozen", False)),
    )

    if platform.handle_special_args(sys.argv):
        logger.info("Windows platform helper mode handled")
        return

    if EXIT_APP_FLAG in sys.argv:
        requested = platform.request_running_app_exit()
        logger.info("Windows external exit requested success=%s", requested)
        return

    if not platform.acquire_single_instance():
        logger.info(
            "Windows duplicate instance blocked mode=%s",
            "tray" if tray_mode else "settings",
        )
        if not tray_mode:
            platform.notify_already_running()
        return

    logger.info(
        "Windows single instance acquired mode=%s",
        "tray" if tray_mode else "settings",
    )
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
