"""Cross-platform entrypoint for the desktop shell."""

import sys

from desktop.core.constants import MAC_SETTINGS_CLIENT_FLAG


def main():
    if MAC_SETTINGS_CLIENT_FLAG in sys.argv:
        from desktop.shell.settings_client import main as settings_main

        # Address and auth token are read from the environment
        # (CHEEVO_SETTINGS_SOCKET / CHEEVO_SETTINGS_TOKEN);
        return settings_main()
    if sys.platform == "darwin":
        from desktop.shell.macos.entrypoint import main as platform_main
    elif sys.platform.startswith("win"):
        from desktop.shell.windows.entrypoint import main as platform_main
    elif sys.platform.startswith("linux"):
        from desktop.shell.linux.entrypoint import main as platform_main
    else:
        raise NotImplementedError(
            "CheevoPresence currently supports Windows, macOS, and Linux only."
        )
    return platform_main()


__all__ = ["main"]
