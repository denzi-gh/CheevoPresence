"""Validated RetroAchievements activity snapshots."""

from dataclasses import dataclass
from datetime import datetime, timezone


class APIResponseError(Exception):
    """Invalid or incomplete API response."""


def _object(value: object) -> dict:
    if not isinstance(value, dict):
        raise APIResponseError("Expected a JSON object")
    return value


def _required(mapping, key):
    if key not in mapping:
        raise APIResponseError("Missing requested API field")
    return mapping[key]


def _document(payload: object) -> dict:
    document = _object(payload)
    if "errors" in document:
        raise APIResponseError("Unexpected JSON:API error document")
    return document


def _resource(value, resource_type):
    value = _object(value)
    resource_id = value.get("id")
    if value.get("type") != resource_type or not isinstance(resource_id, str) or not resource_id:
        raise APIResponseError("Invalid JSON:API resource identity")
    return value


def _game_id(value: object) -> int:
    resource_id = _resource(value, "games")["id"]
    if not resource_id.isascii() or not resource_id.isdigit():
        raise APIResponseError("Invalid game ID")
    try:
        game_id = int(resource_id)
    except ValueError:
        raise APIResponseError("Invalid game ID") from None
    if game_id <= 0:
        raise APIResponseError("Invalid game ID")
    return game_id


def _optional_text(value: object) -> str | None:
    if value is not None and not isinstance(value, str):
        raise APIResponseError("Expected text or null")
    return value


def _timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise APIResponseError("Invalid activity timestamp")
    try:
        # Python 3.10 does not accept the Z suffix in fromisoformat.
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise APIResponseError("Invalid activity timestamp") from None


def _last_game(payload: dict, user: dict) -> tuple[int | None, str | None]:
    included = payload.get("included", [])
    if not isinstance(included, list):
        raise APIResponseError("Invalid included resources")
    games = {}
    for item in included:
        item = _object(item)
        if item.get("type") == "games":
            game_id = _game_id(item)
            if game_id in games:
                raise APIResponseError("Duplicate included game")
            games[game_id] = item

    relationships = _object(user.get("relationships", {}))
    if "lastGame" in relationships:
        reference = _required(_object(relationships["lastGame"]), "data")
        if reference is None:
            if games:
                raise APIResponseError("Conflicting last game data")
            return None, None
        game_id = _game_id(reference)
        if game_id not in games:
            raise APIResponseError("Missing included last game")
    else:
        if "included" not in payload or len(games) > 1:
            raise APIResponseError("Missing or ambiguous last game data")
        if not games:
            if included:
                raise APIResponseError("Missing included last game")
            return None, None
        game_id = next(iter(games))

    title = _required(_object(games[game_id].get("attributes")), "title")
    if not isinstance(title, str):
        raise APIResponseError("Invalid game title")
    return game_id, title


@dataclass(frozen=True)
class UserActivity:
    """Activity snapshot; the timestamp may advance without a text change."""

    game_id: int | None
    game_title: str | None
    rich_presence: str
    rich_presence_updated_at: datetime | None
    visible_role: str | None
    displayable_roles: tuple[str, ...] | None

    @classmethod
    def from_json_api(cls, payload: object) -> "UserActivity":
        document = _document(payload)
        user = _resource(document.get("data"), "users")
        attributes = _object(user.get("attributes"))
        rich_presence = _optional_text(_required(attributes, "richPresence"))
        updated_at = _timestamp(_required(attributes, "richPresenceUpdatedAt"))
        visible_role = _optional_text(attributes.get("visibleRole"))
        roles = attributes.get("displayableRoles")
        if roles is not None and (
            not isinstance(roles, list) or any(not isinstance(role, str) for role in roles)
        ):
            raise APIResponseError("Invalid displayable roles")
        game_id, game_title = _last_game(document, user)
        return cls(
            game_id=game_id,
            game_title=game_title,
            rich_presence=rich_presence or "",
            rich_presence_updated_at=updated_at,
            visible_role=visible_role,
            displayable_roles=tuple(roles) if roles is not None else None,
        )


@dataclass(frozen=True)
class PlayerGameActivity:
    """Unlock history for hardcore/softcore inference"""

    game_id: int
    last_unlock_at: datetime | None
    last_unlock_hardcore_at: datetime | None

    @classmethod
    def collection_from_json_api(cls, payload: object) -> tuple["PlayerGameActivity", ...]:
        document = _document(payload)
        data = document.get("data")
        if not isinstance(data, list):
            raise APIResponseError("Expected a player-games collection")
        activities = []
        for item in data:
            item = _resource(item, "player-games")
            attributes = _object(item.get("attributes"))
            relationships = _object(item.get("relationships"))
            game = _object(relationships.get("game"))
            activities.append(cls(
                game_id=_game_id(game.get("data")),
                last_unlock_at=_timestamp(_required(attributes, "lastUnlockAt")),
                last_unlock_hardcore_at=_timestamp(_required(attributes, "lastUnlockHardcoreAt")),
            ))
        return tuple(activities)
