"""RetroAchievements permission-role helpers."""

import os
from dataclasses import dataclass

DEBUG_FORCE_ROLE_PERMISSION_ENV = "DEBUG_FORCE_ROLE_PERMISSION"


@dataclass(frozen=True)
class RoleInfo:

    permissions: int
    label: str
    tier: str


ROLE_BY_PERMISSION = {
    2: RoleInfo(permissions=2, label="Junior Developer", tier="junior_developer"),
    3: RoleInfo(permissions=3, label="Developer", tier="developer"),
    4: RoleInfo(permissions=4, label="Moderator", tier="moderator"),
    5: RoleInfo(permissions=5, label="Admin", tier="admin"),
    6: RoleInfo(permissions=6, label="Admin", tier="admin"),
}

FORCEABLE_PERMISSIONS = frozenset({1, *ROLE_BY_PERMISSION.keys()})


def debug_forced_role_permission(environ=None):
    environ = os.environ if environ is None else environ
    permissions = coerce_permissions(environ.get(DEBUG_FORCE_ROLE_PERMISSION_ENV))
    if permissions in FORCEABLE_PERMISSIONS:
        return permissions
    return None


def coerce_permissions(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def role_from_permissions(value, forced_permission=None):
    if forced_permission in FORCEABLE_PERMISSIONS:
        return ROLE_BY_PERMISSION.get(forced_permission)
    permissions = coerce_permissions(value)
    if permissions is None:
        return None
    return ROLE_BY_PERMISSION.get(permissions)


def has_special_role(value, forced_permission=None):
    return role_from_permissions(value, forced_permission=forced_permission) is not None


def is_elevated_permission(value, forced_permission=None):
    if forced_permission in FORCEABLE_PERMISSIONS:
        return forced_permission > 1
    permissions = coerce_permissions(value)
    return permissions is not None and permissions > 1
