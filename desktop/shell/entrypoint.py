"""Shared startup sequence for the platform desktop shells.

Every platform entrypoint runs the same bootstrap: configure logging, honour
the ``--exit`` and single-instance handling, then hand a ready
``AppController`` to a platform-specific runner. That sequence lives here once
so each shell only supplies its own ``run_app`` hook.
"""

import logging
import sys

from desktop.core.constants import EXIT_APP_FLAG, TRAY_FLAG
from desktop.core.log_events import AREA_STARTUP, log_event
from desktop.platform import get_platform_services
from desktop.runtime.controller import AppController
from desktop.runtime.diagnostics import log_startup_diagnostics
from desktop.runtime.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def run_shell(platform_name, run_app):
    """Run the shared shell startup, then hand off to a platform runner.

    ``run_app(controller, *, tray_mode)`` constructs and runs the
    platform-specific tray/menu-bar app once startup has succeeded.
    """
    tray_mode = TRAY_FLAG in sys.argv
    mode = "tray" if tray_mode else "settings"
    platform = get_platform_services()
    setup_logging(platform)
    log_startup_diagnostics(platform)
    log_event(logger, AREA_STARTUP, "entrypoint_started", platform=platform_name, mode=mode)

    if platform.handle_special_args(sys.argv):
        log_event(logger, AREA_STARTUP, "platform_helper_handled", platform=platform_name)
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
    run_app(controller, tray_mode=tray_mode)


__all__ = ["run_shell"]
