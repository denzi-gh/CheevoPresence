"""RetroAchievements API client with injectable HTTP transport."""

from urllib.parse import quote

import requests

from desktop.core.constants import RA_API_BASE, RA_API_V2_BASE
from desktop.core.ra_models import APIResponseError, PlayerGameActivity, UserActivity


class RAClient:

    def __init__(self, session=None, base_url=RA_API_BASE, v2_base_url=RA_API_V2_BASE):
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self.v2_base_url = v2_base_url.rstrip("/")

    def _get_json_dict(self, path, params, timeout=10, headers=None, *, base_url=None):
        response = self.session.get(
            f"{base_url or self.base_url}/{path}",
            params=params,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError:
            raise APIResponseError("Invalid JSON response") from None
        if not isinstance(data, dict):
            raise APIResponseError
        return data

    def _get_v2_json_dict(self, path, apikey, params):
        return self._get_json_dict(
            path,
            params,
            base_url=self.v2_base_url,
            headers={"X-API-Key": apikey, "Accept": "application/vnd.api+json"},
        )

    def get_user_activity(self, username: str, apikey: str) -> UserActivity:
        safe_username = quote(str(username).strip(), safe="")
        payload = self._get_v2_json_dict(
            f"users/{safe_username}",
            apikey,
            {
                # Sparse fieldsets must retain the included relationship.
                "fields[users]": "richPresence,richPresenceUpdatedAt,visibleRole,displayableRoles,lastGame",
                "include": "lastGame",
                "fields[games]": "title",
            },
        )
        return UserActivity.from_json_api(payload)

    def get_player_games_v2(
        self, username: str, apikey: str, *, game_id: int | None = None, limit: int = 10,
    ) -> tuple[PlayerGameActivity, ...]:
        safe_username = quote(str(username).strip(), safe="")
        params = {
            "fields[player-games]": "lastUnlockAt,lastUnlockHardcoreAt,game",
            # The serializer needs include=game to emit relationship linkage
            "include": "game",
            "fields[games]": "",
            "sort": "-lastPlayedAt",
            "page[number]": 1,
            "page[size]": limit,
        }
        if game_id is not None:
            params["filter[gameId]"] = game_id
        payload = self._get_v2_json_dict(f"users/{safe_username}/player-games", apikey, params)
        return PlayerGameActivity.collection_from_json_api(payload)

    def get_user_profile(self, username: str, apikey: str) -> dict:
        return self._get_json_dict("API_GetUserProfile.php", {"u": username, "y": apikey})

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

    def get_game_info_and_user_progress(self, username, apikey, game_id):
        return self._get_json_dict(
            "API_GetGameInfoAndUserProgress.php",
            {"u": username, "y": apikey, "g": game_id},
        )
