"""RetroAchievements API client with injectable HTTP transport."""

from datetime import datetime, timezone
from urllib.parse import quote

import requests

from desktop.core.constants import RA_API_BASE, RA_API_V2_BASE


class APIResponseError(Exception):
    pass


class RAClient:

    def __init__(self, session=None, base_url=RA_API_BASE, v2_base_url=RA_API_V2_BASE):
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self.v2_base_url = v2_base_url.rstrip("/")

    def _get_json_dict(self, path, params, timeout=10, headers=None):
        response = self.session.get(
            f"{self.base_url}/{path}",
            params=params,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise APIResponseError
        return data

    def get_user_summary(self, username, apikey, recent_games=0, recent_achievements=0):
        no_cache = datetime.now(tz=timezone.utc).strftime("%d%m%Y%H%M%S")
        return self._get_json_dict(
            "API_GetUserSummary.php",
            {
                "u": username,
                "y": apikey,
                "g": recent_games,
                "a": recent_achievements,
                "noCache": no_cache,
            },
        )

    def get_game(self, username, apikey, game_id):
        return self._get_json_dict(
            "API_GetGame.php",
            {"z": username, "y": apikey, "i": game_id},
        )

    def get_user_progress(self, username, apikey, game_id):
        return self._get_json_dict(
            "API_GetUserProgress.php",
            {"u": username, "y": apikey, "i": game_id},
        )

    def get_user_profile_v2(self, username, apikey):
        safe_username = quote(str(username).strip(), safe="")
        response = self.session.get(
            f"{self.v2_base_url}/users/{safe_username}",
            params={"fields[users]": "visibleRole,displayableRoles"},
            headers={
                "X-API-Key": apikey,
                "Accept": "application/vnd.api+json",
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise APIResponseError
        data = payload.get("data")
        if not isinstance(data, dict):
            raise APIResponseError
        attributes = data.get("attributes")
        if not isinstance(attributes, dict):
            raise APIResponseError
        visible_role = attributes.get("visibleRole")
        if visible_role is not None and not isinstance(visible_role, str):
            raise APIResponseError
        displayable_roles = attributes.get("displayableRoles")
        if displayable_roles is not None and not isinstance(displayable_roles, list):
            raise APIResponseError
        return attributes
