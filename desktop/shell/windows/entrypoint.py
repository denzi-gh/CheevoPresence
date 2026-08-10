"""Application entrypoint for the Windows desktop shell."""

import sys

from desktop.core.constants import WINDOWS_SETTINGS_CLIENT_FLAG
from desktop.shell.entrypoint import run_shell
from desktop.shell.windows.tray import TrayApp


def _run_app(controller, *, tray_mode):
    TrayApp(controller, open_settings_on_launch=not tray_mode).run()


def main():
    if WINDOWS_SETTINGS_CLIENT_FLAG in sys.argv:
        # Address and auth token are read from the environment
        # (CHEEVO_SETTINGS_SOCKET / CHEEVO_SETTINGS_TOKEN).
        from desktop.shell.settings_client import main as settings_main

        return settings_main()

    return run_shell("windows", _run_app)
