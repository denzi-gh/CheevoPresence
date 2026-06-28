"""Desktop runtime worker that mirrors RetroAchievements into Discord RPC."""

import logging
import threading
import time
from datetime import datetime, timezone

import requests
from pypresence import Presence

from desktop.core.api import (
    APIResponseError,
    format_api_error,
    ra_get_game,
    ra_get_user_progress,
    ra_get_user_summary,
)
from desktop.core.roles import role_from_permissions
from desktop.core.settings import normalize_config
from desktop.runtime.backoff import BackoffPolicy
from desktop.runtime.discord_gateway import (
    DiscordPresenceGateway,
    is_discord_unavailable_error,
    safe_exception_name,
)
from desktop.runtime.log_events import (
    AREA_DISCORD,
    AREA_RA,
    AREA_WORKER,
    log_event,
)
from desktop.runtime.presence_builder import PresenceBuilder, coerce_progress_int
from desktop.runtime.state import WorkerState
from desktop.runtime.storage import load_config, load_console_icons

logger = logging.getLogger(__name__)


class RPCWorker:
    """Poll RetroAchievements and mirror the active session to Discord RPC."""

    def __init__(
        self,
        status_callback=None,
        initial_config=None,
        console_icons=None,
        presence_factory=Presence,
        discord_gateway=None,
    ):
        self._state_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._external_callback = status_callback
        self._presence_factory = presence_factory
        self.config = normalize_config(
            initial_config if initial_config is not None else load_config()
        )
        self.console_icons = console_icons if console_icons is not None else load_console_icons()
        self.running = False
        self.thread = None
        self.discord_gateway = discord_gateway or DiscordPresenceGateway(
            presence_factory=presence_factory,
            status_callback=self.status_callback,
        )
        self.rpc = None
        self.rpc_connected = False
        self.rpc_pipe = None
        self.start_time = None
        self._current_game_id = None
        self.current_status = "disconnected"
        self.status_text = "Not running"
        self.ra_connected = False
        self.ra_status_text = "Not connected to RetroAchievements"
        self.ra_permissions = None
        self.ra_role_label = ""
        self.ra_role_tier = ""

    def set_status_callback(self, callback):
        """Register the UI-facing status callback used by the runtime shell."""
        self._external_callback = callback

    def status_callback(self, status, text):
        """Store the latest worker status and forward it to the UI if present."""
        with self._state_lock:
            self.current_status = status
            self.status_text = text
            callback = self._external_callback
        if callback:
            callback(status, text)

    def set_ra_status(self, connected):
        """Track whether the RetroAchievements API is currently reachable."""
        with self._state_lock:
            self.ra_connected = connected
            username = str(self.config.get("username") or "").strip()
            self.ra_status_text = (
                f"Connected as {username}" if username else "Connected to RetroAchievements"
                if connected
                else "Not connected to RetroAchievements"
            )
            if not connected:
                self.ra_permissions = None
                self.ra_role_label = ""
                self.ra_role_tier = ""

    def set_ra_role(self, permissions):
        """Track display metadata for the connected user's RA role."""
        role = role_from_permissions(permissions)
        with self._state_lock:
            self.ra_permissions = role.permissions if role else None
            self.ra_role_label = role.label if role else ""
            self.ra_role_tier = role.tier if role else ""

    def get_state(self):
        """Return an immutable snapshot of UI-facing worker state."""
        with self._state_lock:
            thread_alive = self.thread is not None and self.thread.is_alive()
            return WorkerState(
                running=self.running,
                is_busy=self.running or thread_alive,
                is_stopping=not self.running and thread_alive,
                current_status=self.current_status,
                status_text=self.status_text,
                ra_connected=self.ra_connected,
                ra_status_text=self.ra_status_text,
                ra_permissions=self.ra_permissions,
                ra_role_label=self.ra_role_label,
                ra_role_tier=self.ra_role_tier,
            )

    def is_busy(self):
        """Return whether the worker is active or still shutting down."""
        return self.get_state().is_busy

    def is_stopping(self):
        """Return whether the worker is in its shutdown grace period."""
        return self.get_state().is_stopping

    def start(self, config=None):
        """Start the polling thread if credentials are available."""
        with self._state_lock:
            if self.running or (self.thread is not None and self.thread.is_alive()):
                log_event(logger, AREA_WORKER, "start_skipped", reason="already_running")
                return False

            cfg = normalize_config(config if config is not None else load_config())
            if not cfg["username"] or not cfg["apikey"]:
                log_event(
                    logger,
                    AREA_WORKER,
                    "start_skipped",
                    reason="missing_credentials",
                    username_present=bool(cfg["username"]),
                    apikey_present=bool(cfg["apikey"]),
                )
                self.set_ra_status(False)
                self.status_callback("error", "Username or API Key missing")
                return False

            self.config = cfg
            self._stop_event.clear()
            self.running = True
            log_event(
                logger,
                AREA_WORKER,
                "started",
                interval_sec=cfg["interval"],
                timeout_sec=cfg["timeout"],
                achievement_progress=bool(cfg.get("show_achievement_progress", True)),
            )
            self.thread = threading.Thread(
                target=self._loop,
                daemon=True,
                name="RPCWorker",
            )
            self.thread.start()
            return True

    def stop(self, timeout=35):
        """Request a clean worker shutdown and wait briefly for it to finish."""
        with self._state_lock:
            thread = self.thread
            if not self.running and not (thread and thread.is_alive()):
                log_event(logger, AREA_WORKER, "stop_skipped", reason="already_stopped")
                self._disconnect_rpc()
                self._current_game_id = None
                self.set_ra_status(False)
                self.status_callback("disconnected", "Stopped")
                return True
            self.running = False
            self._stop_event.set()
            log_event(
                logger,
                AREA_WORKER,
                "stop_requested",
                timeout_sec=timeout,
                thread_alive=bool(thread and thread.is_alive()),
            )

        if thread and thread is not threading.current_thread():
            thread.join(timeout=timeout)

        stopped = not thread or not thread.is_alive()
        if stopped:
            log_event(logger, AREA_WORKER, "stopped")
            self.status_callback("disconnected", "Stopped")
        else:
            log_event(
                logger,
                AREA_WORKER,
                "stop_timeout",
                level=logging.WARNING,
                timeout_sec=timeout,
            )
            self.status_callback("connecting", "Stopping...")
        return stopped

    def _should_stop(self):
        """Return whether the polling loop should exit on the next check."""
        return self._stop_event.is_set() or not self.running

    def _current_thread_done(self):
        """Mark the current worker thread as finished in shared state."""
        with self._state_lock:
            self.running = False
            if threading.current_thread() is self.thread:
                self.thread = None

    def _unexpected_api_response(self):
        """Surface a standard unexpected-API-response error to the UI."""
        log_event(
            logger,
            AREA_RA,
            "invalid_response",
            level=logging.WARNING,
            reason="unexpected_payload",
        )
        self._disconnect_rpc()
        self.set_ra_status(False)
        self.status_callback("error", "API error: unexpected response")

    def _sync_gateway_from_worker(self):
        """Keep compatibility fields in sync before delegating to the gateway."""
        self.discord_gateway.presence_factory = self._presence_factory
        self.discord_gateway.status_callback = self.status_callback
        self.discord_gateway.rpc = self.rpc
        self.discord_gateway.rpc_connected = self.rpc_connected
        self.discord_gateway.rpc_pipe = self.rpc_pipe
        self.discord_gateway.start_time = self.start_time

    def _sync_worker_from_gateway(self):
        """Mirror gateway-owned Discord state onto legacy worker attributes."""
        self.rpc = self.discord_gateway.rpc
        self.rpc_connected = self.discord_gateway.rpc_connected
        self.rpc_pipe = self.discord_gateway.rpc_pipe
        self.start_time = self.discord_gateway.start_time

    def _connect_rpc(self):
        """Open the Discord IPC connection if it is not already active."""
        self._sync_gateway_from_worker()
        connected = self.discord_gateway.connect()
        self._sync_worker_from_gateway()
        return connected

    def _disconnect_rpc(self):
        """Clear Discord presence and close the current IPC client safely."""
        self._sync_gateway_from_worker()
        self.discord_gateway.disconnect()
        self._sync_worker_from_gateway()

    def _loop(self):
        """Continuously poll RA, build presence data, and update Discord."""
        try:
            log_event(logger, AREA_WORKER, "loop_started")
            self.set_ra_status(False)
            self.status_callback("connecting", "Starting...")
            self.config = normalize_config(self.config)
            username = self.config["username"]
            apikey = self.config["apikey"]
            interval = self.config["interval"]
            timeout_sec = self.config["timeout"]
            backoff = BackoffPolicy(interval)
            presence_builder = PresenceBuilder(self.config, self.console_icons)
            consecutive_errors = 0

            while not self._should_stop():
                try:
                    user_data = ra_get_user_summary(username, apikey)
                    if self._should_stop():
                        break

                    was_ra_connected = self.ra_connected
                    self.set_ra_status(True)
                    self.set_ra_role(user_data.get("Permissions"))
                    if not was_ra_connected:
                        log_event(logger, AREA_RA, "connection_succeeded")
                    last_game_id = coerce_progress_int(user_data.get("LastGameID", 0))


                    # Test Dev Mode by forcing "Developing Achievements" activity
                    # rp_msg = user_data.get("RichPresenceMsg", "")
                    rp_msg = user_data.get("RichPresenceMsg", "")
                    if not isinstance(rp_msg, str):
                        raise APIResponseError

                    rp_date_str = user_data.get("RichPresenceMsgDate", "")
                    if rp_date_str is None:
                        rp_date_str = ""
                    if not isinstance(rp_date_str, str):
                        raise APIResponseError

                    if not last_game_id:
                        if self.status_text != "Not playing":
                            log_event(logger, AREA_RA, "no_game_detected")
                        self._disconnect_rpc()
                        self._current_game_id = None
                        self.status_callback("disconnected", "Not playing")
                        consecutive_errors = 0
                        self._sleep(interval)
                        continue

                    is_active = True
                    if timeout_sec > 0 and rp_date_str:
                        try:
                            rp_date = datetime.strptime(
                                rp_date_str,
                                "%Y-%m-%d %H:%M:%S",
                            ).replace(tzinfo=timezone.utc)
                            time_diff = (datetime.now(timezone.utc) - rp_date).total_seconds()
                            if time_diff > timeout_sec:
                                is_active = False
                        except ValueError:
                            pass
                    elif not rp_date_str:
                        is_active = False

                    if not is_active:
                        if self.status_text != "Not actively playing":
                            log_event(
                                logger,
                                AREA_RA,
                                "session_inactive",
                                reason="rich_presence_stale",
                                timeout_sec=timeout_sec,
                            )
                        self._disconnect_rpc()
                        self._current_game_id = None
                        self.status_callback("disconnected", "Not actively playing")
                        consecutive_errors = 0
                        self._sleep(interval)
                        continue

                    game_data = ra_get_game(username, apikey, last_game_id)
                    if self._should_stop():
                        break

                    progress_data = ra_get_user_progress(username, apikey, last_game_id)
                    if self._should_stop():
                        break

                    game_changed = last_game_id != self._current_game_id
                    if game_changed:
                        self._current_game_id = last_game_id
                        if self.rpc_connected:
                            self.start_time = int(time.time())

                    presence = presence_builder.build(
                        username=username,
                        last_game_id=last_game_id,
                        rich_presence_message=rp_msg,
                        game_data=game_data,
                        progress_data=progress_data,
                        start_time=self.start_time,
                    )

                    if not self._connect_rpc():
                        self._sleep(interval)
                        continue
                    if self._should_stop():
                        break

                    # Status changes (new game) are logged at INFO; steady-state
                    # refreshes every few seconds stay at DEBUG to keep the log small.
                    presence_level = logging.INFO if game_changed else logging.DEBUG
                    if game_changed:
                        log_event(
                            logger,
                            AREA_RA,
                            "session_active",
                            game_id=last_game_id,
                            console=presence.console_name,
                            rich_presence_present=bool(rp_msg),
                        )
                    log_event(
                        logger,
                        AREA_DISCORD,
                        "presence_update_attempt",
                        level=presence_level,
                        game_id=last_game_id,
                        console_id=presence.console_id,
                        console_name=presence.console_name,
                        pipe=self.rpc_pipe,
                        achievements=f"{presence.achievement_count}/{presence.achievement_total}",
                        buttons=presence.button_count,
                        developer_activity=presence.developer_activity,
                    )
                    try:
                        self.discord_gateway.update(**presence.update_kwargs)
                    except Exception as exc:
                        log_event(
                            logger,
                            AREA_DISCORD,
                            "presence_update_failed",
                            level=logging.WARNING,
                            game_id=last_game_id,
                            pipe=self.rpc_pipe,
                            error_type=safe_exception_name(exc),
                        )
                        raise
                    log_event(
                        logger,
                        AREA_DISCORD,
                        "presence_update_succeeded",
                        level=presence_level,
                        game_id=last_game_id,
                        pipe=self.rpc_pipe,
                        achievements=f"{presence.achievement_count}/{presence.achievement_total}",
                        buttons=presence.button_count,
                    )
                    activity_label = "Developing" if presence.developer_activity else "Playing"
                    self.status_callback(
                        "connected",
                        f"{activity_label}: {presence.game_title} ({presence.console_name})",
                    )
                    consecutive_errors = 0

                except requests.RequestException as exc:
                    consecutive_errors += 1
                    self._disconnect_rpc()
                    self.set_ra_status(False)
                    log_event(
                        logger,
                        AREA_RA,
                        "request_failed",
                        level=logging.WARNING,
                        error_type=exc.__class__.__name__,
                        detail=format_api_error(exc),
                        consecutive_errors=consecutive_errors,
                    )
                    self.status_callback("error", format_api_error(exc))
                except APIResponseError:
                    consecutive_errors += 1
                    self._unexpected_api_response()
                except Exception as exc:
                    consecutive_errors += 1
                    self._disconnect_rpc()
                    if is_discord_unavailable_error(exc):
                        log_event(
                            logger,
                            AREA_DISCORD,
                            "unavailable_during_loop",
                            level=logging.WARNING,
                            error_type=safe_exception_name(exc),
                            consecutive_errors=consecutive_errors,
                        )
                        self.status_callback("error", "Discord is not open")
                    else:
                        self.set_ra_status(False)
                        log_event(
                            logger,
                            AREA_WORKER,
                            "unexpected_failure",
                            level=logging.ERROR,
                            exc_info=True,
                            consecutive_errors=consecutive_errors,
                        )
                        self.status_callback("error", "Error: unexpected failure")

                wait = backoff.delay_for(consecutive_errors)
                if consecutive_errors > 0:
                    log_event(logger, AREA_WORKER, "backing_off", wait_sec=wait)
                self._sleep(wait)
        finally:
            self._disconnect_rpc()
            self._current_game_id = None
            self.set_ra_status(False)
            self._current_thread_done()
            if self._stop_event.is_set():
                self.status_callback("disconnected", "Stopped")
            log_event(
                logger,
                AREA_WORKER,
                "loop_finished",
                stop_requested=self._stop_event.is_set(),
            )

    def _sleep(self, seconds):
        """Sleep in one-second slices so shutdown stays responsive."""
        for _ in range(int(seconds)):
            if self._should_stop():
                return
            time.sleep(1)
