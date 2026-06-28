"""Runtime state snapshots shared with UI and IPC layers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MirroredPresence:
    """Discord presence snapshot mirrored into the settings UI."""

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


@dataclass(frozen=True)
class WorkerState:
    """Immutable snapshot of the worker lifecycle and display status."""

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
    mirrored_presence: MirroredPresence | None = None
