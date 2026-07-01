"""Structured logging helpers for a single tagged ``cheevo.log``.

Every diagnostic line is rendered as ``[AREA] event key=value`` so support cases
can be triaged from one log file. Sensitive fields are always redacted and URLs
never carry their query string (which may hold the RA API key).
"""

import logging
from urllib.parse import urlsplit, urlunsplit

# Area tags used across the runtime so support can grep one log file.
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

REDACTED = "<redacted>"


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


def sanitize_log_value(value):
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return str(value)

    text = _strip_url_query(str(value))
    if text == "":
        return '""'
    if any(char.isspace() for char in text) or "=" in text or '"' in text:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def sanitize_log_fields(fields):
    safe = {}
    for key, value in fields.items():
        if key.lower() in SENSITIVE_KEYS:
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
