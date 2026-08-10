"""Shared, toolkit-independent tray/menu-bar behavior."""

import logging
import threading

from desktop.core.log_events import AREA_TRAY, log_event

logger = logging.getLogger(__name__)

STATUS_TEXT_LIMIT = 72


def tray_connection_title(worker):
    """Label for the connect/disconnect menu item given the worker state."""
    state = worker.get_state()
    if state.is_stopping:
        return "Stopping..."
    if state.running:
        return "Disconnect"
    return "Connect"


def truncate_tray_status(text, limit=STATUS_TEXT_LIMIT):
    """Clip a status line to fit a tray menu/tooltip."""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


class TrayControllerBase:
    """Connection state machine shared by the platform tray shells."""

    def _marshal(self, fn):
        raise NotImplementedError

    def _refresh_menu(self):
        raise NotImplementedError

    def open_settings(self):
        raise NotImplementedError

    def connection_action_title(self):
        return tray_connection_title(self.worker)

    def _truncate_status(self, text, limit=STATUS_TEXT_LIMIT):
        return truncate_tray_status(text, limit)

    def _request_toggle_connection(self):
        """UI callback: run the toggle off the UI thread so it never blocks."""
        if getattr(self, "_shutdown_started", False):
            return
        if self.worker.get_state().is_stopping:
            return
        threading.Thread(target=self._toggle_connection, daemon=True).start()

    def _toggle_connection(self):
        if self.worker.get_state().running:
            log_event(logger, AREA_TRAY, "disconnect_requested")
            self.controller.disconnect()
            self._marshal(self._refresh_menu)
            return

        config = self.controller.load_config()
        if not config["username"] or not config["apikey"]:
            log_event(
                logger,
                AREA_TRAY,
                "connect_blocked",
                reason="missing_credentials",
                username_present=bool(config["username"]),
                apikey_present=bool(config["apikey"]),
            )
            self.worker.set_ra_status(False)
            self.worker.status_callback("error", "Username or API Key missing")
            self._marshal(self.open_settings)
            return

        log_event(logger, AREA_TRAY, "connect_requested")
        if not self.controller.start_saved_session():
            log_event(logger, AREA_TRAY, "connect_no_worker", level=logging.WARNING)
            self._marshal(self._refresh_menu)
