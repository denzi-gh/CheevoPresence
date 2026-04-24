"""Cross-platform entrypoint for the desktop shell."""

import sys

MAC_SETTINGS_CLIENT_FLAG = "--mac-settings-client"


def main():
    """Dispatch to the native desktop shell for the current OS."""
    if MAC_SETTINGS_CLIENT_FLAG in sys.argv:
        flag_index = sys.argv.index(MAC_SETTINGS_CLIENT_FLAG)
        from desktop.shell.macos.settings import main as settings_main

        if len(sys.argv) >= flag_index + 3:
            return settings_main(sys.argv[flag_index + 1], sys.argv[flag_index + 2])
        return settings_main()
    if sys.platform == "darwin":
        from desktop.shell.macos.entrypoint import main as platform_main
    elif sys.platform.startswith("win"):
        from desktop.shell.windows.entrypoint import main as platform_main
    elif sys.platform.startswith("linux"):
        from desktop.shell.linux.entrypoint import main as platform_main
    else:
        raise NotImplementedError("CheevoPresence currently supports Windows, macOS, and Linux only.")
    return platform_main()


__all__ = ["main"]
