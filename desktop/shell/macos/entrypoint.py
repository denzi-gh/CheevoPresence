"""Application entrypoint for the macOS menu-bar shell."""

from desktop.shell.entrypoint import run_shell
from desktop.shell.macos.menu_bar import MacOSMenuBarApp


def _run_app(controller, *, tray_mode):
    MacOSMenuBarApp(controller, open_settings_on_launch=not tray_mode).run()


def main():
    return run_shell("macos", _run_app)
