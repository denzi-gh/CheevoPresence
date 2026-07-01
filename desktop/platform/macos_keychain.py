"""macOS Keychain helpers for API-key storage."""

import subprocess

from desktop.platform.generic import GenericPlatformServices

KEYCHAIN_SERVICE = "org.denzi.cheevopresence"
KEYCHAIN_ACCOUNT = "retroachievements-api-key"
KEYCHAIN_TOKEN_PREFIX = f"keychain://{KEYCHAIN_SERVICE}/"


def build_keychain_token(account=KEYCHAIN_ACCOUNT):
    return f"{KEYCHAIN_TOKEN_PREFIX}{account}"


def parse_keychain_token(value):
    if not isinstance(value, str) or not value.startswith(KEYCHAIN_TOKEN_PREFIX):
        return None
    account = value[len(KEYCHAIN_TOKEN_PREFIX) :].strip()
    return account or None


def _run_command(args, input_text=None, check=True):
    return subprocess.run(
        args,
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
    )


def _read_keychain_password(account):
    try:
        result = _run_command(
            [
                "security",
                "find-generic-password",
                "-a",
                account,
                "-s",
                KEYCHAIN_SERVICE,
                "-w",
            ]
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def _write_keychain_password(account, value):
    try:
        _run_command(
            [
                "security",
                "add-generic-password",
                "-U",
                "-a",
                account,
                "-s",
                KEYCHAIN_SERVICE,
                "-w",
                value,
            ]
        )
    except OSError as exc:
        raise OSError("Could not access the macOS Keychain.") from exc
    except subprocess.CalledProcessError as exc:
        raise OSError("Could not save the API key to the macOS Keychain.") from exc


def _delete_keychain_password(account):
    try:
        subprocess.run(
            [
                "security",
                "delete-generic-password",
                "-a",
                account,
                "-s",
                KEYCHAIN_SERVICE,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        pass


def protect_api_key(value):
    if not value:
        _delete_keychain_password(KEYCHAIN_ACCOUNT)
        return ""
    _write_keychain_password(KEYCHAIN_ACCOUNT, value)
    return build_keychain_token()


def unprotect_api_key(value):
    account = parse_keychain_token(value)
    if account:
        return _read_keychain_password(account)
    return GenericPlatformServices().unprotect_api_key(value)
