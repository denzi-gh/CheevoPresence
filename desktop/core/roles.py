"""RetroAchievements permission-role helpers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleInfo:

    permissions: int
    label: str
    tier: str


ROLE_BY_PERMISSION = {
    2: RoleInfo(permissions=2, label="Junior Developer", tier="junior_developer"),
    3: RoleInfo(permissions=3, label="Developer", tier="developer"),
    4: RoleInfo(permissions=4, label="Moderator", tier="moderator"),
    5: RoleInfo(permissions=5, label="Moderator", tier="moderator"),
    6: RoleInfo(permissions=6, label="Moderator", tier="moderator"),
}


def coerce_permissions(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def role_from_permissions(value):
    permissions = coerce_permissions(value)
    if permissions is None:
        return None
    return ROLE_BY_PERMISSION.get(permissions)


def has_special_role(value):
    return role_from_permissions(value) is not None


def is_elevated_permission(value):
    permissions = coerce_permissions(value)
    return permissions is not None and permissions > 1
