"""Companion settings client for the native host app."""

from __future__ import annotations

import os
import sys

import tkinter as tk
from tkinter import messagebox

from desktop.shell.tk_settings import TkSettingsWindow


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
    from desktop.shell.ipc import (
        SETTINGS_ADDRESS_ENV,
        SETTINGS_AUTH_ENV,
        RemoteAppController,
    )

    address = address or os.environ.get(SETTINGS_ADDRESS_ENV)
    auth_token = auth_token or os.environ.get(SETTINGS_AUTH_ENV)
    try:
        controller = RemoteAppController(address, auth_token)
        TkSettingsWindow(controller, on_quit=controller.quit_app)
    except Exception as exc:
        _show_startup_error(str(exc) or "The settings client could not connect to the host app.")
