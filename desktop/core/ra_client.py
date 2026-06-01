"""RetroAchievements API client with injectable HTTP transport."""

from datetime import datetime

import requests

from desktop.core.constants import RA_API_BASE


class APIResponseError(Exception):
    """Raised when RetroAchievements returns an unexpected payload shape."""


class RAClient:
    """Small RetroAchievements API client backed by a requests-like session."""

    def __init__(self, session=None, base_url=RA_API_BASE):
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")

    def _get_json_dict(self, path, params, timeout=10):
        """Fetch one endpoint and require a dictionary JSON payload."""
        response = self.session.get(
            f"{self.base_url}/{path}",
            params=params,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise APIResponseError
        return data

    def get_user_summary(self, username, apikey):
        """Fetch the current RetroAchievements session summary for a user."""
        no_cache = datetime.now().strftime("%d%m%Y%H%M%S")
        return self._get_json_dict(
            "API_GetUserSummary.php",
            {"u": username, "y": apikey, "g": 0, "a": 0, "noCache": no_cache},
        )

    def get_game(self, username, apikey, game_id):
        """Fetch static metadata for the currently active RetroAchievements game."""
        return self._get_json_dict(
            "API_GetGame.php",
            {"z": username, "y": apikey, "i": game_id},
        )

    def get_user_progress(self, username, apikey, game_id):
        """Fetch the current user's achievement progress for one game."""
        return self._get_json_dict(
            "API_GetUserProgress.php",
            {"u": username, "y": apikey, "i": game_id},
        )
