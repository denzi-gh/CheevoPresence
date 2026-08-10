"""Application entrypoint for the Linux native tray shell."""

import logging

from desktop.core.log_events import AREA_STARTUP, log_event
from desktop.shell.entrypoint import run_shell
from desktop.shell.linux.indicator import LinuxIndicatorApp, LinuxTrayUnavailable
from desktop.shell.web_settings import WebSettingsWindow as SettingsWindow

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


def _run_app(controller, *, tray_mode):
    try:
        app = LinuxIndicatorApp(controller, open_settings_on_launch=not tray_mode)
    except LinuxTrayUnavailable as exc:
        _run_settings_fallback(controller, str(exc))
        return
    app.run()


def main():
    return run_shell("linux", _run_app)
