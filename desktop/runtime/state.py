"""Runtime state snapshots shared with UI and IPC layers."""

from dataclasses import dataclass


def _coerce_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class MirroredPresence:

    game_id: int
    title: str
    details: str | None
    state: str | None
    console_name: str
    game_icon_url: str | None
    large_text: str | None
    achievement_count: int
    achievement_total: int
    show_achievement_progress: bool
    buttons: list[dict]
    developer_activity: bool

    @classmethod
    def from_dict(cls, payload):
        """Rebuild a snapshot from an IPC payload."""
        if not isinstance(payload, dict):
            return None
        buttons = payload.get("buttons") or []
        if not isinstance(buttons, list):
            buttons = []
        return cls(
            game_id=_coerce_int(payload.get("game_id", 0)),
            title=str(payload.get("title") or ""),
            details=payload.get("details") if payload.get("details") is not None else None,
            state=payload.get("state") if payload.get("state") is not None else None,
            console_name=str(payload.get("console_name") or ""),
            game_icon_url=(
                payload.get("game_icon_url")
                if payload.get("game_icon_url") is not None
                else None
            ),
            large_text=payload.get("large_text") if payload.get("large_text") is not None else None,
            achievement_count=_coerce_int(payload.get("achievement_count", 0)),
            achievement_total=_coerce_int(payload.get("achievement_total", 0)),
            show_achievement_progress=bool(payload.get("show_achievement_progress", False)),
            buttons=[dict(button) for button in buttons if isinstance(button, dict)],
            developer_activity=bool(payload.get("developer_activity", False)),
        )


@dataclass(frozen=True)
class WorkerState:

    running: bool
    is_busy: bool
    is_stopping: bool
    current_status: str
    status_text: str
    ra_connected: bool
    ra_status_text: str
    ra_permissions: int | None = None
    ra_role_label: str = ""
    ra_role_tier: str = ""
    ra_dev_mode: bool = False
    mirrored_presence: MirroredPresence | None = None

    @classmethod
    def from_dict(cls, payload):
        """Rebuild a WorkerState from an IPC payload with defensive coercion."""
        if not isinstance(payload, dict):
            payload = {}
        permissions = payload.get("ra_permissions")
        try:
            ra_permissions = int(permissions) if permissions is not None else None
        except (TypeError, ValueError):
            ra_permissions = None
        return cls(
            running=bool(payload.get("running", False)),
            is_busy=bool(payload.get("is_busy", False)),
            is_stopping=bool(payload.get("is_stopping", False)),
            current_status=str(payload.get("current_status") or "disconnected"),
            status_text=str(payload.get("status_text") or "Not running"),
            ra_connected=bool(payload.get("ra_connected", False)),
            ra_status_text=str(
                payload.get("ra_status_text") or "Not connected to RetroAchievements"
            ),
            ra_permissions=ra_permissions,
            ra_role_label=str(payload.get("ra_role_label") or ""),
            ra_role_tier=str(payload.get("ra_role_tier") or ""),
            ra_dev_mode=bool(payload.get("ra_dev_mode", False)),
            mirrored_presence=MirroredPresence.from_dict(payload.get("mirrored_presence")),
        )
