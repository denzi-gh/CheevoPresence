"""Companion settings client for the native host app."""

from __future__ import annotations

import logging
import os
import sys

import tkinter as tk
from tkinter import messagebox

from desktop.runtime.log_events import AREA_SETTINGS, log_event
from desktop.shell.web_settings import WebSettingsWindow

logger = logging.getLogger(__name__)


def _show_startup_error(message):
    """Display a small native error when the settings client cannot boot."""
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("CheevoPresence Settings", message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)


def main(address=None, auth_token=None):
    """Start the shared Tk settings window against the host app bridge."""
    from desktop.platform import get_platform_services
    from desktop.runtime.logging_setup import setup_logging
    from desktop.shell.ipc import (
        SETTINGS_ADDRESS_ENV,
        SETTINGS_AUTH_ENV,
        RemoteAppController,
    )

    # The settings client runs as its own process; route it into the same
    # cheevo.log so [SETTINGS]/[IPC] lines stay in one file.
    setup_logging(get_platform_services())
    log_event(logger, AREA_SETTINGS, "client_started", pid=os.getpid())

    address = address or os.environ.get(SETTINGS_ADDRESS_ENV)
    auth_token = auth_token or os.environ.get(SETTINGS_AUTH_ENV)
    try:
        controller = RemoteAppController(address, auth_token)
        WebSettingsWindow(controller, on_quit=controller.quit_app)
    except Exception as exc:
        log_event(
            logger,
            AREA_SETTINGS,
            "client_error",
            level=logging.ERROR,
            error_type=exc.__class__.__name__,
        )
        _show_startup_error(str(exc) or "The settings client could not connect to the host app.")
