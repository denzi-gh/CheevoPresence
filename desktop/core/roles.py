"""RetroAchievements permission-role helpers."""

import os
from dataclasses import dataclass

DEBUG_FORCE_ROLE_PERMISSION_ENV = "DEBUG_FORCE_ROLE_PERMISSION"


@dataclass(frozen=True)
class RoleInfo:

    permissions: int | None
    label: str
    tier: str


ROLE_BY_PERMISSION = {
    2: RoleInfo(permissions=2, label="Junior Developer", tier="junior_developer"),
    3: RoleInfo(permissions=3, label="Developer", tier="developer"),
    4: RoleInfo(permissions=4, label="Moderator", tier="moderator"),
    5: RoleInfo(permissions=5, label="Admin", tier="admin"),
    6: RoleInfo(permissions=6, label="Admin", tier="admin"),
}

ROLE_BY_VISIBLE_ROLE = {
    "developer": RoleInfo(permissions=None, label="Developer", tier="developer"),
    "developer-junior": RoleInfo(
        permissions=None,
        label="Junior Developer",
        tier="junior_developer",
    ),
    "event-manager": RoleInfo(
        permissions=None,
        label="Event Manager",
        tier="event_manager",
    ),
    "artist": RoleInfo(permissions=None, label="Artist", tier="artist"),
    "play-tester": RoleInfo(permissions=None, label="Play Tester", tier="play_tester"),
    "writer": RoleInfo(permissions=None, label="Writer", tier="writer"),
    "moderator": RoleInfo(permissions=None, label="Moderator", tier="moderator"),
    "code-reviewer": RoleInfo(
        permissions=None,
        label="Code Reviewer",
        tier="code_reviewer",
    ),
}

ROLE_BY_TIER = {role.tier: role for role in ROLE_BY_VISIBLE_ROLE.values()}

FORCEABLE_PERMISSIONS = frozenset({1, *ROLE_BY_PERMISSION.keys()})

DEV_MODE_TIERS = frozenset(
    {
        "junior_developer",
        "developer",
        "code_reviewer",
        "moderator",
    }
)


def debug_forced_role_permission(environ=None):
    environ = os.environ if environ is None else environ
    value = environ.get(DEBUG_FORCE_ROLE_PERMISSION_ENV)
    permissions = coerce_permissions(value)
    if permissions in FORCEABLE_PERMISSIONS:
        return permissions
    role = role_from_visible_role(value)
    if role is not None:
        return role
    return None


def coerce_permissions(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def role_from_permissions(value, forced_permission=None):
    if forced_permission in FORCEABLE_PERMISSIONS:
        return ROLE_BY_PERMISSION.get(forced_permission)
    if isinstance(forced_permission, RoleInfo):
        return forced_permission
    permissions = coerce_permissions(value)
    if permissions is None:
        return None
    return ROLE_BY_PERMISSION.get(permissions)


def role_from_visible_role(value):
    if not isinstance(value, str):
        return None
    role_key = value.strip().lower().replace(" ", "-")
    if not role_key:
        return None
    tier = role_key.replace("-", "_")
    slug = role_key.replace("_", "-")
    return ROLE_BY_TIER.get(tier) or ROLE_BY_VISIBLE_ROLE.get(slug)


def role_from_api(permissions, visible_role=None, forced_permission=None):
    if forced_permission in FORCEABLE_PERMISSIONS:
        return role_from_permissions(permissions, forced_permission=forced_permission)
    if isinstance(forced_permission, RoleInfo):
        return forced_permission
    return role_from_visible_role(visible_role) or role_from_permissions(permissions)


def has_special_role(value, forced_permission=None):
    return role_from_permissions(value, forced_permission=forced_permission) is not None


def is_elevated_permission(value, forced_permission=None):
    if forced_permission in FORCEABLE_PERMISSIONS:
        return forced_permission > 1
    if isinstance(forced_permission, RoleInfo) and forced_permission.permissions is not None:
        return forced_permission.permissions > 1
    permissions = coerce_permissions(value)
    return permissions is not None and permissions > 1


def roles_grant_dev_mode(displayable_roles):
    for slug in displayable_roles or ():
        role = role_from_visible_role(slug)
        if role is not None and role.tier in DEV_MODE_TIERS:
            return True
    return False


def resolve_dev_mode(permissions, displayable_roles, forced_permission=None):
    if forced_permission in FORCEABLE_PERMISSIONS:
        role = ROLE_BY_PERMISSION.get(forced_permission)
        return role is not None and role.tier in DEV_MODE_TIERS
    if isinstance(forced_permission, RoleInfo):
        return forced_permission.tier in DEV_MODE_TIERS
    if displayable_roles is not None:
        return roles_grant_dev_mode(displayable_roles)
    return is_elevated_permission(permissions)
