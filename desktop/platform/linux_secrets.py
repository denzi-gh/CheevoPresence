"""Linux API-key storage helpers."""

from desktop.platform.generic import GenericPlatformServices


def protect_api_key(value):
    return GenericPlatformServices().protect_api_key(value)


def unprotect_api_key(value):
    return GenericPlatformServices().unprotect_api_key(value)
