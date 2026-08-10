"""Shared application constants used by the desktop core and runtime."""

DISCORD_APP_ID = "1485964205713788958"
RA_API_BASE = "https://retroachievements.org/API"
RA_API_V2_BASE = "https://api.retroachievements.org/v2"
APP_NAME = "CheevoPresence"
APP_VERSION = "1.3.2"
RA_SETTINGS_URL = "https://retroachievements.org/settings"
RELEASES_PAGE_URL = "https://github.com/denzi-gh/CheevoPresence/releases"
RELEASES_LATEST_API_URL = "https://api.github.com/repos/denzi-gh/CheevoPresence/releases/latest"
UPDATE_TEST_FILE_NAME = "update-test.json"

# CLI flags shared across the launchers, platform entrypoints, and adapters.
# Centralised here so a flag string is defined once and platform shells can
# reference it without importing each other (which would be circular).
TRAY_FLAG = "--tray"
EXIT_APP_FLAG = "--exit"
MAC_SETTINGS_CLIENT_FLAG = "--mac-settings-client"
WINDOWS_SETTINGS_CLIENT_FLAG = "--windows-settings-client"
LINUX_SETTINGS_CLIENT_FLAG = "--linux-settings-client"
