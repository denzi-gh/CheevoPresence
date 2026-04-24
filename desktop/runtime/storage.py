"""Runtime storage and asset helpers for the desktop app."""

import configparser
import json
import os
import sys
import tempfile

from desktop.core.constants import APP_NAME, UPDATE_TEST_FILE_NAME
from desktop.core.settings import DEFAULT_CONFIG, normalize_config
from desktop.platform import get_platform_services


def get_resource_dir():
    """Return the directory that contains bundled runtime assets."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_runtime_root_dir():
    """Return the directory next to the running EXE or top-level script tree."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_config_dir(platform=None):
    """Return the per-user directory where the runtime config should live."""
    platform = platform or get_platform_services()
    runtime_root_dir = get_runtime_root_dir()
    preferred_dir = platform.get_config_dir(APP_NAME, runtime_root_dir)
    if preferred_dir:
        return preferred_dir
    if getattr(sys, "frozen", False):
        return os.path.join(runtime_root_dir, APP_NAME)
    return runtime_root_dir


def get_config_file(platform=None):
    """Return the config file path for the selected platform adapter."""
    return os.path.join(get_config_dir(platform), "config.json")


RESOURCE_DIR = get_resource_dir()
RUNTIME_ROOT_DIR = get_runtime_root_dir()
LEGACY_CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config.json")
CONSOLE_ICONS_FILE = os.path.join(RESOURCE_DIR, "console_icons.ini")
APP_ICON_FILE = os.path.join(RESOURCE_DIR, "cheevoRP_icon.ico")
APP_ICON_PNG_FILE = os.path.join(RESOURCE_DIR, "cheevoRP_icon.png")
MENU_BAR_TEMPLATE_ICON_FILE = os.path.join(RESOURCE_DIR, "cheevoRP_menubar_template.png")
GENERATED_MENU_BAR_TEMPLATE_ICON_FILE = os.path.join(
    RUNTIME_ROOT_DIR,
    "build",
    "macos",
    "generated",
    "cheevoRP_menubar_template.png",
)
TRAY_INACTIVE_ICON_FILE = os.path.join(RESOURCE_DIR, "cheevoRP_inactive.ico")
TRAY_ACTIVE_ICON_FILE = os.path.join(RESOURCE_DIR, "cheevoRP_active.ico")
TRAY_ERROR_ICON_FILE = os.path.join(RESOURCE_DIR, "cheevoRP_error.ico")
TRAY_INACTIVE_PNG_FILE = os.path.join(RESOURCE_DIR, "cheevoRP_inactive.png")
TRAY_ACTIVE_PNG_FILE = os.path.join(RESOURCE_DIR, "cheevoRP_active.png")
TRAY_ERROR_PNG_FILE = os.path.join(RESOURCE_DIR, "cheevoRP_error.png")
UPDATE_OVERRIDE_FILE = os.path.join(RUNTIME_ROOT_DIR, UPDATE_TEST_FILE_NAME)


def load_config(platform=None):
    """Load config from disk and migrate the legacy in-repo file if needed."""
    platform = platform or get_platform_services()
    config_file = get_config_file(platform)
    source = config_file
    if not os.path.exists(source) and LEGACY_CONFIG_FILE != config_file and os.path.exists(LEGACY_CONFIG_FILE):
        source = LEGACY_CONFIG_FILE

    if os.path.exists(source):
        try:
            with open(source, "r", encoding="utf-8") as handle:
                saved = json.load(handle)
            cfg = normalize_config(saved, decode_api_key=platform.unprotect_api_key)
            if source != config_file:
                save_config(cfg, platform)
                try:
                    os.remove(source)
                except OSError:
                    pass
            return cfg
        except (json.JSONDecodeError, OSError):
            return dict(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_config(cfg, platform=None):
    """Persist the normalized config to disk with a protected API key."""
    platform = platform or get_platform_services()
    config_dir = get_config_dir(platform)
    config_file = get_config_file(platform)
    cfg = normalize_config(cfg, decode_api_key=platform.unprotect_api_key)
    stored_cfg = {key: value for key, value in cfg.items() if key != "apikey"}
    protected_apikey = platform.protect_api_key(cfg["apikey"])
    if protected_apikey:
        stored_cfg["apikey_protected"] = protected_apikey

    os.makedirs(config_dir, exist_ok=True)
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(stored_cfg, handle, indent=2)
        os.replace(tmp_path, config_file)
    except OSError:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        with open(config_file, "w", encoding="utf-8") as handle:
            json.dump(stored_cfg, handle, indent=2)


def load_console_icons():
    """Load RetroAchievements console image mappings from the INI file."""
    cp = configparser.ConfigParser()
    cp.read(CONSOLE_ICONS_FILE)
    mapping = {}
    if cp.has_section("CI"):
        for key, value in cp.items("CI"):
            mapping[key.strip()] = value.strip()
    return mapping
