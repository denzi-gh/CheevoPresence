"""Shared RetroAchievements API compatibility helpers and error formatting."""

import requests

from desktop.core.ra_client import APIResponseError, RAClient


def trimmer(text, max_units=128):
    """Trim text to fit within Discord's UTF-16 unit limit."""
    encoded = text.encode("utf-16-le")
    if len(encoded) <= max_units * 2:
        return text

    result = ""
    size = 0
    for ch in text:
        ch_size = len(ch.encode("utf-16-le"))
        if size + ch_size > (max_units - 3) * 2:
            return result + "..."
        result += ch
        size += ch_size
    return result


_DEFAULT_CLIENT = RAClient()


def ra_get_user_summary(username, apikey):
    """Fetch the current RetroAchievements session summary for a user."""
    return _DEFAULT_CLIENT.get_user_summary(username, apikey)


def ra_get_game(username, apikey, game_id):
    """Fetch static metadata for the currently active RetroAchievements game."""
    return _DEFAULT_CLIENT.get_game(username, apikey, game_id)


def ra_get_user_progress(username, apikey, game_id):
    """Fetch the current user's achievement progress for one game."""
    return _DEFAULT_CLIENT.get_user_progress(username, apikey, game_id)


def format_api_error(exc):
    """Return a user-safe API error message without leaking query params."""
    if isinstance(exc, requests.Timeout):
        return "API error: request timed out"
    if isinstance(exc, requests.ConnectionError):
        return "API error: network unavailable"

    response = getattr(exc, "response", None)
    if response is not None and response.status_code:
        if response.status_code == 401:
            return "Invalid Web API Key"
        return f"API error: HTTP {response.status_code}"

    return "API error: request failed"
