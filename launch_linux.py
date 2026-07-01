"""Linux-specific launcher used for packaging the desktop app."""

import sys

LINUX_SETTINGS_CLIENT_FLAG = "--linux-settings-client"


def main():
    if LINUX_SETTINGS_CLIENT_FLAG in sys.argv:
        flag_index = sys.argv.index(LINUX_SETTINGS_CLIENT_FLAG)
        from desktop.shell.settings_client import main as settings_main

        if len(sys.argv) >= flag_index + 3:
            return settings_main(sys.argv[flag_index + 1], sys.argv[flag_index + 2])
        return settings_main()

    from desktop.shell.linux.entrypoint import main as platform_main

    return platform_main()


if __name__ == "__main__":
    main()
