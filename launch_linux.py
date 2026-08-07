"""Linux-specific launcher used for packaging the desktop app."""

import sys

LINUX_SETTINGS_CLIENT_FLAG = "--linux-settings-client"


def main():
    if LINUX_SETTINGS_CLIENT_FLAG in sys.argv:
        from desktop.shell.settings_client import main as settings_main

        # Address and auth token are read from the environment
        # (CHEEVO_SETTINGS_SOCKET / CHEEVO_SETTINGS_TOKEN);
        return settings_main()

    from desktop.shell.linux.entrypoint import main as platform_main

    return platform_main()


if __name__ == "__main__":
    main()
