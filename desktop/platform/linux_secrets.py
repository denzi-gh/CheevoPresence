"""Linux Secret Service helpers for API-key storage."""

from desktop.platform.generic import GenericPlatformServices

KEYRING_SERVICE = "org.denzi.cheevopresence"
KEYRING_ACCOUNT = "retroachievements-api-key"
KEYRING_TOKEN_PREFIX = f"secretservice://{KEYRING_SERVICE}/"


def build_secret_token(account=KEYRING_ACCOUNT):
    """Build the config token that points at the stored Secret Service item."""
    return f"{KEYRING_TOKEN_PREFIX}{account}"


def parse_secret_token(value):
    """Extract the Secret Service account from a stored config token."""
    if not isinstance(value, str) or not value.startswith(KEYRING_TOKEN_PREFIX):
        return None
    account = value[len(KEYRING_TOKEN_PREFIX) :].strip()
    return account or None


def _load_keyring():
    """Import the optional keyring module lazily."""
    import keyring

    return keyring


def _delete_password(account):
    """Best-effort deletion of the stored API key."""
    try:
        _load_keyring().delete_password(KEYRING_SERVICE, account)
    except Exception:
        pass


def protect_api_key(value):
    """Store the API key in Secret Service, falling back to generic encoding."""
    if not value:
        _delete_password(KEYRING_ACCOUNT)
        return ""

    try:
        _load_keyring().set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, value)
        return build_secret_token()
    except Exception:
        return GenericPlatformServices().protect_api_key(value)


def unprotect_api_key(value):
    """Resolve a stored Secret Service token back into the plaintext API key."""
    account = parse_secret_token(value)
    if account:
        try:
            return _load_keyring().get_password(KEYRING_SERVICE, account) or ""
        except Exception:
            return ""
    return GenericPlatformServices().unprotect_api_key(value)
