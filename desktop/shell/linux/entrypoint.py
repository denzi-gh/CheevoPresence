"""Application entrypoint for the Linux native tray shell."""

import logging
import sys

from desktop.platform import get_platform_services
from desktop.runtime.controller import AppController
from desktop.runtime.diagnostics import log_startup_diagnostics
from desktop.runtime.log_events import AREA_STARTUP, log_event
from desktop.runtime.logging_setup import setup_logging
from desktop.shell.linux.indicator import LinuxIndicatorApp, LinuxTrayUnavailable
from desktop.shell.web_settings import WebSettingsWindow as SettingsWindow

EXIT_APP_FLAG = "--exit"
logger = logging.getLogger(__name__)


def _run_settings_fallback(controller, reason):
    log_event(
        logger,
        AREA_STARTUP,
        "indicator_unavailable_fallback",
        level=logging.WARNING,
        reason=reason,
    )
    controller.start_saved_session()
    try:
        SettingsWindow(controller)
    finally:
        controller.shutdown()


def main():
    tray_mode = "--tray" in sys.argv
    mode = "tray" if tray_mode else "settings"
    platform = get_platform_services()
    setup_logging(platform)
    log_startup_diagnostics(platform)
    log_event(logger, AREA_STARTUP, "entrypoint_started", platform="linux", mode=mode)

    if platform.handle_special_args(sys.argv):
        log_event(logger, AREA_STARTUP, "platform_helper_handled", platform="linux")
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
    try:
        app = LinuxIndicatorApp(
            controller,
            open_settings_on_launch=not tray_mode,
        )
    except LinuxTrayUnavailable as exc:
        _run_settings_fallback(controller, str(exc))
        return

    app.run()
