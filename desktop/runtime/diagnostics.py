"""Startup diagnostics emitted into the single tagged ``cheevo.log``.

These ``[STARTUP]``/``[PLATFORM]``/``[PATHS]`` lines let a support case be
triaged from the log alone: app version, Python/runtime, distro/desktop on
Linux, and every important on-disk path. No secrets are collected.
"""

import logging
import os
import platform as platform_module
import sys

from desktop.core.constants import APP_VERSION
from desktop.runtime.log_events import (
    AREA_PATHS,
    AREA_PLATFORM,
    AREA_STARTUP,
    log_event,
)
from desktop.runtime.storage import (
    get_config_dir,
    get_config_file,
    get_log_dir,
    get_log_file,
    get_runtime_root_dir,
)

logger = logging.getLogger(__name__)


def parse_os_release(path="/etc/os-release"):
    data = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                value = value.strip().strip('"').strip("'")
                data[key.strip()] = value
    except OSError:
        return {}
    return data


def collect_linux_diagnostics():
    os_release = parse_os_release()
    return {
        "distro_id": os_release.get("ID", "unknown"),
        "distro_version": os_release.get("VERSION_ID", "unknown"),
        "pretty_name": os_release.get("PRETTY_NAME", "unknown"),
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", "unknown"),
        "session_type": os.environ.get("XDG_SESSION_TYPE", "unknown"),
        "display_set": bool(os.environ.get("DISPLAY")),
        "wayland_display_set": bool(os.environ.get("WAYLAND_DISPLAY")),
    }


def collect_windows_diagnostics():
    return {
        "release": platform_module.release(),
        "version": platform_module.version(),
    }


def collect_macos_diagnostics():
    return {"mac_version": platform_module.mac_ver()[0] or "unknown"}


def collect_platform_diagnostics(platform=None):
    system = platform_module.system()
    if system == "Linux":
        return collect_linux_diagnostics()
    if system == "Windows":
        return collect_windows_diagnostics()
    if system == "Darwin":
        return collect_macos_diagnostics()
    return {}


def log_startup_diagnostics(platform=None):
    log_event(
        logger,
        AREA_STARTUP,
        "app_started",
        version=APP_VERSION,
        python=platform_module.python_version(),
        frozen=bool(getattr(sys, "frozen", False)),
        executable=sys.executable,
    )
    log_event(
        logger,
        AREA_PLATFORM,
        "system_info",
        system=platform_module.system(),
        release=platform_module.release(),
        machine=platform_module.machine(),
    )

    extra = collect_platform_diagnostics(platform)
    if extra:
        log_event(logger, AREA_PLATFORM, "environment", **extra)

    log_event(
        logger,
        AREA_PATHS,
        "resolved",
        config_dir=get_config_dir(platform),
        config_file=get_config_file(platform),
        log_dir=get_log_dir(platform),
        log_file=get_log_file(platform),
        runtime_dir=get_runtime_root_dir(),
    )
