"""Companion settings client for the native host app."""

from __future__ import annotations

import logging
import os
import signal
import sys
import tkinter as tk
from tkinter import messagebox

from desktop.core.log_events import AREA_SETTINGS, log_event, register_log_secret
from desktop.shell.web_settings import WebSettingsWindow

logger = logging.getLogger(__name__)

PRESENT_SIGNAL = getattr(signal, "SIGUSR1", None)


def _install_present_handler(window):
    """Let the host raise this window instead of launching a second client."""
    if PRESENT_SIGNAL is None:
        return

    def handle(_signum, _frame):
        try:
            window.present()
        except Exception:  # noqa: BLE001 signal-handler boundary; warning logged below
            log_event(
                logger,
                AREA_SETTINGS,
                "client_present_failed",
                level=logging.WARNING,
                exc_info=True,
            )

    try:
        signal.signal(PRESENT_SIGNAL, handle)
    except (ValueError, OSError):
        
        pass


def _show_startup_error(message):
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("CheevoPresence Settings", message)
        root.destroy()
    except Exception:  # noqa: BLE001 error dialog is best-effort; stderr is the fallback
        print(message, file=sys.stderr)


def main():
    from desktop.platform import get_platform_services
    from desktop.runtime.crash_reporting import install_crash_reporting
    from desktop.runtime.logging_setup import setup_child_logging
    from desktop.shell.ipc import (
        SETTINGS_ADDRESS_ENV,
        SETTINGS_AUTH_ENV,
        RemoteAppController,
    )

    # The host is the sole cheevo.log writer. It captures and forwards this
    # structured stream, including stderr output from early/native failures.
    setup_child_logging()

    address = os.environ.get(SETTINGS_ADDRESS_ENV)
    auth_token = os.environ.get(SETTINGS_AUTH_ENV)
    register_log_secret(auth_token)
    crash_reporter = install_crash_reporting(
        get_platform_services(),
        process_role="settings",
    )
    log_event(logger, AREA_SETTINGS, "client_started", pid=os.getpid())
    try:
        controller = RemoteAppController(address, auth_token)
        WebSettingsWindow(
            controller,
            on_quit=controller.quit_app,
            on_ready=_install_present_handler,
        )
    except Exception as exc:  # noqa: BLE001 process entry boundary; logged and shown to the user
        crash_reporter.capture_exception(
            type(exc),
            exc,
            exc.__traceback__,
            origin="settings_client_main",
        )
        _show_startup_error(str(exc) or "The settings client could not connect to the host app.")
