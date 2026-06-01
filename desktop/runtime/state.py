"""Runtime state snapshots shared with UI and IPC layers."""

from dataclasses import dataclass


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
