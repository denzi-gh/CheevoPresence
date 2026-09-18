"""Structured logging helpers for a single tagged ``cheevo.log``.

Every diagnostic line is rendered as ``[AREA] event key=value`` so support cases
can be triaged from one log file. Sensitive fields are always redacted and URLs
never carry their query string (which may hold the RA API key).
"""

import json
import logging
import re
import threading
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit

# Area tags used across the app so support can grep one log file.
AREA_STARTUP = "STARTUP"
AREA_PLATFORM = "PLATFORM"
AREA_PATHS = "PATHS"
AREA_CONFIG = "CONFIG"
AREA_TRAY = "TRAY"
AREA_SETTINGS = "SETTINGS"
AREA_IPC = "IPC"
AREA_DISCORD = "DISCORD"
AREA_RA = "RA"
AREA_WORKER = "WORKER"
AREA_UPDATE = "UPDATE"
AREA_AUTOSTART = "AUTOSTART"
AREA_SHUTDOWN = "SHUTDOWN"
AREA_ERROR = "ERROR"

# Field names whose values must never reach the log file.
SENSITIVE_KEYS = frozenset(
    {
        "apikey",
        "api_key",
        "apikey_protected",
        "token",
        "auth_token",
        "authorization",
        "password",
        "secret",
    }
)
_NORMALIZED_SENSITIVE_KEYS = frozenset(
    re.sub(r"[^a-z0-9]", "", item) for item in SENSITIVE_KEYS
)

REDACTED = "<redacted>"
MAX_LOG_VALUE_CHARS = 4096
_REGISTERED_SECRETS: set[str] = set()
_REGISTERED_SECRETS_LOCK = threading.Lock()
_URL_RE = re.compile(r"\bhttps?://[^\s<>\"']+", re.IGNORECASE)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)(?P<key>['\"]?(?:api[_-]?key|apikey_protected|x[_-]?api[_-]?key|"
    r"access[_-]?token|auth[_-]?token|token|authorization|password|secret)['\"]?"
    r"\s*[:=]\s*)"
    r"(?P<value>Bearer\s+[^\s,}\]]+|'[^']*'|\"[^\"]*\"|[^\s,}\]]+)"
)


def _strip_url_query(value):
    if "://" not in value:
        return value
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not parts.scheme or not parts.netloc:
        return value
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _is_sensitive_key(key):
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    if normalized.endswith("present"):
        return False
    return (
        normalized in _NORMALIZED_SENSITIVE_KEYS
        or "apikey" in normalized
        or normalized.endswith(("password", "secret", "token"))
    )


def register_log_secret(value):
    """Register a runtime credential for final-output redaction."""
    if not isinstance(value, str):
        return
    secret = value.strip()
    # Very short values create destructive false positives in ordinary words.
    if len(secret) < 4:
        return
    with _REGISTERED_SECRETS_LOCK:
        _REGISTERED_SECRETS.add(secret)


def _registered_secrets():
    with _REGISTERED_SECRETS_LOCK:
        return sorted(_REGISTERED_SECRETS, key=len, reverse=True)


def _escape_control_characters(text):
    out = []
    for char in text:
        codepoint = ord(char)
        if char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif char == "\t":
            out.append("\\t")
        elif codepoint < 32 or codepoint == 127:
            out.append(f"\\x{codepoint:02x}")
        else:
            out.append(char)
    return "".join(out)


def _stringify_log_value(value):
    try:
        return str(value)
    except Exception:  # noqa: BLE001 logging must not break the caller
        return f"<unprintable {value.__class__.__name__}>"


def redact_log_text(value, *, escape_controls=False):
    """Redact credentials and URL queries anywhere in rendered log text."""
    text = _stringify_log_value(value)
    text = text.encode("utf-8", errors="backslashreplace").decode("utf-8")
    text = _URL_RE.sub(lambda match: _strip_url_query(match.group(0)), text)
    text = _SENSITIVE_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group('key')}{REDACTED}",
        text,
    )
    for secret in _registered_secrets():
        text = text.replace(secret, REDACTED)
    if escape_controls:
        text = _escape_control_characters(text)
    return text


def _sanitize_nested_value(value, seen=None):
    seen = seen if seen is not None else set()
    if isinstance(value, Mapping):
        if id(value) in seen:
            return "<cycle>"
        seen.add(id(value))
        try:
            return {
                _stringify_log_value(key): (
                    REDACTED
                    if _is_sensitive_key(key)
                    else _sanitize_nested_value(item, seen)
                )
                for key, item in value.items()
            }
        finally:
            seen.remove(id(value))
    if isinstance(value, (list, tuple, set, frozenset)):
        if id(value) in seen:
            return "<cycle>"
        seen.add(id(value))
        try:
            return [_sanitize_nested_value(item, seen) for item in value]
        finally:
            seen.remove(id(value))
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_log_text(value, escape_controls=True)


def sanitize_log_value(value):
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, (Mapping, list, tuple, set, frozenset)):
        value = json.dumps(
            _sanitize_nested_value(value),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=isinstance(value, Mapping),
        )

    text = redact_log_text(value, escape_controls=True)
    if len(text) > MAX_LOG_VALUE_CHARS:
        text = f"{text[:MAX_LOG_VALUE_CHARS]}...<truncated>"
    if text == "":
        return '""'
    if any(char.isspace() for char in text) or "=" in text or '"' in text:
        return json.dumps(text, ensure_ascii=True)
    return text


def sanitize_log_fields(fields):
    safe = {}
    for key, value in fields.items():
        if _is_sensitive_key(key):
            safe[key] = REDACTED
        else:
            safe[key] = sanitize_log_value(value)
    return safe


def format_event(area, event, **fields):
    safe_fields = sanitize_log_fields(fields)
    parts = [f"[{area}]", event]
    parts.extend(f"{key}={value}" for key, value in safe_fields.items())
    return " ".join(parts)


def log_event(logger, area, event, level=logging.INFO, exc_info=False, **fields):
    logger.log(level, format_event(area, event, **fields), exc_info=exc_info)
