"""macOS-specific launcher used for packaging the desktop app."""

import sys

from desktop.core.constants import MAC_SETTINGS_CLIENT_FLAG


def main():
    if MAC_SETTINGS_CLIENT_FLAG in sys.argv:
        from desktop.shell.settings_client import main as settings_main

        # Address and auth token are read from the environment
        # (CHEEVO_SETTINGS_SOCKET / CHEEVO_SETTINGS_TOKEN);
        return settings_main()

    from desktop.shell.macos.entrypoint import main as platform_main

    return platform_main()


if __name__ == "__main__":
    main()
