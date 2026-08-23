"""Shared settings schema, validation, and migration for the desktop app."""

from dataclasses import asdict, dataclass

SCHEMA_VERSION = 1

_TRUE_STRINGS = frozenset({"1", "true", "yes", "on"})
_FALSE_STRINGS = frozenset({"0", "false", "no", "off"})
_BOOL_FIELDS = (
    "show_profile_button",
    "show_gamepage_button",
    "show_achievement_progress",
    "show_total_playtime",
    "dev_mode",
    "use_retroachievements_developer_titles",
    "show_developer_sets_button",
    "start_on_boot",
)


def _coerce_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_STRINGS:
            return True
        if lowered in _FALSE_STRINGS:
            return False
    return default


def _coerce_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class AppConfig:
    """Typed, validated snapshot of the user configuration."""

    username: str = ""
    apikey: str = ""
    show_profile_button: bool = True
    show_gamepage_button: bool = True
    show_achievement_progress: bool = True
    show_total_playtime: bool = True
    dev_mode: bool = False
    use_retroachievements_developer_titles: bool = True
    show_developer_sets_button: bool = True
    interval: int = 5
    timeout: int = 130
    start_on_boot: bool = False
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_dict(cls, raw, decode_api_key=None):
        if not isinstance(raw, dict):
            return cls()

        defaults = cls()

        username = raw.get("username", "")
        username = username.strip() if isinstance(username, str) else ""

        apikey = raw.get("apikey", "")
        if isinstance(apikey, str) and apikey.strip():
            apikey = apikey.strip()
        else:
            decoder = decode_api_key or (lambda _value: "")
            apikey = decoder(raw.get("apikey_protected", ""))

        bool_values = {
            key: _coerce_bool(raw.get(key, getattr(defaults, key)), getattr(defaults, key))
            for key in _BOOL_FIELDS
        }

        interval = _coerce_int(raw.get("interval", defaults.interval), defaults.interval)
        interval = min(120, max(5, interval))

        timeout = _coerce_int(raw.get("timeout", defaults.timeout), defaults.timeout)
        timeout = max(0, min(3600, timeout))
        if 0 < timeout < 130:
            timeout = 130

        return cls(
            username=username,
            apikey=apikey,
            interval=interval,
            timeout=timeout,
            **bool_values,
        )

    def to_dict(self):
        return asdict(self)


DEFAULT_CONFIG = AppConfig().to_dict()


def normalize_config(raw, decode_api_key=None):
    """Validate a raw config into a plain dict (backwards-compatible surface)."""
    return AppConfig.from_dict(raw, decode_api_key=decode_api_key).to_dict()


def migrate_config(raw):
    """Upgrade a persisted config dict to the current schema version."""
    if not isinstance(raw, dict):
        return {}
    migrated = dict(raw)
    # version = migrated.get("schema_version", 0)
    # if version < 2: migrated["new_field"] = migrated.pop("old_field", ...)
    migrated["schema_version"] = SCHEMA_VERSION
    return migrated


__all__ = [
    "DEFAULT_CONFIG",
    "SCHEMA_VERSION",
    "AppConfig",
    "migrate_config",
    "normalize_config",
]
