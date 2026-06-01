"""Linux API-key storage helpers."""

from desktop.platform.generic import GenericPlatformServices


def protect_api_key(value):
    """Protect the API key using the non-blocking local config encoding."""
    return GenericPlatformServices().protect_api_key(value)


def unprotect_api_key(value):
    """Restore an API key stored with the local config encoding."""
    return GenericPlatformServices().unprotect_api_key(value)
