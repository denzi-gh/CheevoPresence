"""Platform-specific desktop adapters."""

import os
import sys

from desktop.platform.base import PlatformServices
from desktop.platform.generic import GenericPlatformServices

_platform_services = None


def get_platform_services() -> PlatformServices:
    """Return the singleton platform adapter for the current runtime."""
    global _platform_services
    if _platform_services is None:
        if os.name == "nt":
            from desktop.platform.windows import WindowsPlatformServices

            _platform_services = WindowsPlatformServices()
        elif sys.platform == "darwin":
            from desktop.platform.macos import MacOSPlatformServices

            _platform_services = MacOSPlatformServices()
        elif sys.platform.startswith("linux"):
            from desktop.platform.linux import LinuxPlatformServices

            _platform_services = LinuxPlatformServices()
        else:
            _platform_services = GenericPlatformServices()
    return _platform_services
