"""Shared settings validation for the desktop app."""

DEFAULT_CONFIG = {
    "username": "",
    "apikey": "",
    "show_profile_button": True,
    "show_gamepage_button": True,
    "show_achievement_progress": True,
    "use_retroachievements_developer_titles": True,
    "interval": 5,
    "timeout": 130,
    "start_on_boot": False,
}


def normalize_config(raw, decode_api_key=None):
    """Coerce loose JSON config data into the app's validated shape."""
    cfg = dict(DEFAULT_CONFIG)
    if not isinstance(raw, dict):
        return cfg

    username = raw.get("username", "")
    if isinstance(username, str):
        cfg["username"] = username.strip()

    apikey = raw.get("apikey", "")
    if isinstance(apikey, str) and apikey.strip():
        cfg["apikey"] = apikey.strip()
    else:
        decoder = decode_api_key or (lambda _value: "")
        cfg["apikey"] = decoder(raw.get("apikey_protected", ""))

    for key in (
        "show_profile_button",
        "show_gamepage_button",
        "show_achievement_progress",
        "use_retroachievements_developer_titles",
        "start_on_boot",
    ):
        value = raw.get(key, cfg[key])
        if isinstance(value, bool):
            cfg[key] = value
        elif isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                cfg[key] = True
            elif lowered in {"0", "false", "no", "off"}:
                cfg[key] = False

    try:
        interval = int(raw.get("interval", cfg["interval"]))
    except (TypeError, ValueError):
        interval = cfg["interval"]
    cfg["interval"] = min(120, max(5, interval))

    try:
        timeout = int(raw.get("timeout", cfg["timeout"]))
    except (TypeError, ValueError):
        timeout = cfg["timeout"]
    timeout = max(0, min(3600, timeout))
    if 0 < timeout < 130:
        timeout = 130
    cfg["timeout"] = timeout

    return cfg
