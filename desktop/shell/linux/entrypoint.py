"""Application entrypoint for the Linux native tray shell."""

import logging
import sys

from desktop.core.constants import APP_NAME
from desktop.platform import get_platform_services
from desktop.runtime.controller import AppController
from desktop.runtime.logging_setup import setup_logging
from desktop.shell.linux.indicator import LinuxIndicatorApp, LinuxTrayUnavailable
from desktop.shell.tk_settings import TkSettingsWindow as SettingsWindow

EXIT_APP_FLAG = "--exit"
logger = logging.getLogger(__name__)


def _show_tray_unavailable_warning(reason):
    """Show a best-effort warning before falling back to the settings window."""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(
            APP_NAME,
            (
                "The native Linux tray backend is not available. "
                "CheevoPresence will open the settings window instead.\n\n"
                f"{reason}"
            ),
        )
        root.destroy()
    except Exception:
        logger.warning("Linux tray fallback warning could not be shown", exc_info=True)


def _run_settings_fallback(controller, reason):
    """Run a visible settings window when no indicator backend is available."""
    logger.warning("Linux indicator unavailable; using settings fallback: %s", reason)
    controller.start_saved_session()
    _show_tray_unavailable_warning(reason)
    try:
        SettingsWindow(controller)
    finally:
        controller.shutdown()


def main():
    """Boot the Linux native tray app and optionally open Settings on launch."""
    tray_mode = "--tray" in sys.argv
    platform = get_platform_services()
    setup_logging(platform)
    logger.info(
        "Linux entrypoint started mode=%s frozen=%s",
        "tray" if tray_mode else "settings",
        bool(getattr(sys, "frozen", False)),
    )

    if platform.handle_special_args(sys.argv):
        logger.info("Linux platform helper mode handled")
        return

    if EXIT_APP_FLAG in sys.argv:
        requested = platform.request_running_app_exit()
        logger.info("Linux external exit requested success=%s", requested)
        return

    if not platform.acquire_single_instance():
        logger.info(
            "Linux duplicate instance blocked mode=%s",
            "tray" if tray_mode else "settings",
        )
        if not tray_mode:
            platform.notify_already_running()
        return

    logger.info(
        "Linux single instance acquired mode=%s",
        "tray" if tray_mode else "settings",
    )
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
