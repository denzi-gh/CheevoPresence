"""Desktop runtime worker that mirrors RetroAchievements into Discord RPC."""

import logging
import threading
import time
from datetime import datetime, timezone

import requests
from pypresence import Presence

from desktop.core.api import (
    format_api_error,
    ra_get_game,
    ra_get_game_info_and_user_progress,
    ra_get_user_profile_v2,
    ra_get_user_progress,
    ra_get_user_summary,
)
from desktop.core.log_events import (
    AREA_DISCORD,
    AREA_RA,
    AREA_WORKER,
    log_event,
)
from desktop.core.ra_client import APIResponseError
from desktop.core.roles import (
    coerce_permissions,
    debug_forced_role_permission,
    resolve_dev_mode,
    role_from_api,
)
from desktop.core.settings import normalize_config
from desktop.runtime.backoff import BackoffPolicy
from desktop.runtime.discord_gateway import (
    DiscordPresenceGateway,
    is_discord_unavailable_error,
    safe_exception_name,
)
from desktop.runtime.presence_builder import (
    PLAY_MODE_HARDCORE,
    PLAY_MODE_SOFTCORE,
    PresenceBuilder,
    coerce_progress_int,
)
from desktop.runtime.state import MirroredPresence, WorkerState
from desktop.runtime.storage import load_config, load_console_icons

logger = logging.getLogger(__name__)
ROLE_REFRESH_INTERVAL_SECONDS = 15 * 60

# GetUserSummary only surfaces achievements from the recently played games
SUMMARY_RECENT_GAMES = 10


def mode_from_summary(user_data):
    games = user_data.get("RecentAchievements") if isinstance(user_data, dict) else None
    if not isinstance(games, dict):
        return None
    latest = None
    for achievements in games.values():
        if not isinstance(achievements, dict):
            continue
        for entry in achievements.values():
            if not isinstance(entry, dict):
                continue
            try:
                date = datetime.strptime(
                    str(entry.get("DateAwarded", "")),
                    "%Y-%m-%d %H:%M:%S",
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            hardcore = coerce_progress_int(entry.get("HardcoreAchieved", 0))
            # Tuple order lets the hardcore flag win a samesecond tie
            candidate = (date, hardcore)
            if latest is None or candidate > latest:
                latest = candidate
    if latest is None:
        return None
    return PLAY_MODE_HARDCORE if latest[1] else PLAY_MODE_SOFTCORE


class RPCWorker:

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
        self._current_game_id = None
        self._game_data = None
        self._play_mode = None
        self._playtime_start = None
        self.current_status = "disconnected"
        self.status_text = "Not running"
        self.ra_connected = False
        self.ra_status_text = "Not connected to RetroAchievements"
        self.ra_permissions = None
        self.ra_role_label = ""
        self.ra_role_tier = ""
        self.ra_dev_mode = False
        self._ra_role_cache_username = None
        self._ra_role_cache_visible_role = None
        self._ra_role_cache_displayable_roles = None
        self._ra_role_cache_at = 0.0
        self.mirrored_presence = None

    # Delegating views onto the gateway-owned connection state. Keeping them as
    # properties preserves the worker's public surface (and its tests) without
    # duplicating the fields.
    @property
    def rpc(self):
        return self.discord_gateway.rpc

    @property
    def rpc_connected(self):
        return self.discord_gateway.rpc_connected

    @property
    def rpc_pipe(self):
        return self.discord_gateway.rpc_pipe

    @rpc_pipe.setter
    def rpc_pipe(self, value):
        self.discord_gateway.rpc_pipe = value

    @property
    def start_time(self):
        return self.discord_gateway.start_time

    @start_time.setter
    def start_time(self, value):
        self.discord_gateway.start_time = value

    def replace_config(self, config):
        """Thread-safe config swap used by the controller from the UI thread."""
        with self._state_lock:
            self.config = normalize_config(config)

    def _config_snapshot(self):
        with self._state_lock:
            return dict(self.config)

    def set_status_callback(self, callback):
        self._external_callback = callback

    def status_callback(self, status, text):
        with self._state_lock:
            self.current_status = status
            self.status_text = text
            callback = self._external_callback
        if callback:
            callback(status, text)

    def set_ra_status(self, connected):
        with self._state_lock:
            self.ra_connected = connected
            username = str(self.config.get("username") or "").strip()
            if connected:
                self.ra_status_text = (
                    f"Connected as {username}"
                    if username
                    else "Connected to RetroAchievements"
                )
            else:
                self.ra_status_text = "Not connected to RetroAchievements"
            if not connected:
                self.ra_permissions = None
                self.ra_role_label = ""
                self.ra_role_tier = ""
                self.ra_dev_mode = False
                self._ra_role_cache_username = None
                self._ra_role_cache_visible_role = None
                self._ra_role_cache_displayable_roles = None
                self._ra_role_cache_at = 0.0
                self.mirrored_presence = None

    def set_ra_role(self, permissions, visible_role=None, displayable_roles=None):
        forced_permission = debug_forced_role_permission()
        role = role_from_api(
            permissions,
            visible_role=visible_role,
            forced_permission=forced_permission,
        )
        dev_mode = resolve_dev_mode(
            permissions,
            displayable_roles,
            forced_permission=forced_permission,
        )
        with self._state_lock:
            self.ra_permissions = (
                role.permissions
                if role and role.permissions is not None
                else coerce_permissions(permissions)
                if role
                else None
            )
            self.ra_role_label = role.label if role else ""
            self.ra_role_tier = role.tier if role else ""
            self.ra_dev_mode = dev_mode
            self.config["dev_mode"] = dev_mode

    def get_state(self):
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
                ra_dev_mode=self.ra_dev_mode,
                mirrored_presence=self.mirrored_presence,
            )

    def is_busy(self):
        return self.get_state().is_busy

    def is_stopping(self):
        return self.get_state().is_stopping

    def start(self, config=None):
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
        with self._state_lock:
            thread = self.thread
            if not self.running and not (thread and thread.is_alive()):
                log_event(logger, AREA_WORKER, "stop_skipped", reason="already_stopped")
                self._disconnect_rpc()
                self._clear_game_state()
                self.set_ra_status(False)
                self.status_callback("disconnected", "Stopped")
                return True
            self.running = False
            self._stop_event.set()
            self.set_ra_status(False)
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
            self.set_ra_status(False)
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
        return self._stop_event.is_set() or not self.running

    def _current_thread_done(self):
        with self._state_lock:
            self.running = False
            if threading.current_thread() is self.thread:
                self.thread = None

    def _unexpected_api_response(self):
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

    def _clear_game_state(self):
        self._current_game_id = None
        self._game_data = None
        self._playtime_start = None

    def _update_play_mode(self, user_data):
        mode = mode_from_summary(user_data)
        if mode != self._play_mode:
            self._play_mode = mode
            log_event(logger, AREA_RA, "play_mode_changed", mode=mode)

    def _seed_playtime_start(self, username, apikey, game_id):
        # Backdates Discord's elapsed timer to the user's total playtime for the game
        self._playtime_start = None
        if not self._config_snapshot().get("show_total_playtime", True):
            return
        try:
            payload = ra_get_game_info_and_user_progress(username, apikey, game_id)
        except (requests.RequestException, APIResponseError) as exc:
            log_event(
                logger,
                AREA_RA,
                "playtime_seed_failed",
                level=logging.WARNING,
                error_type=exc.__class__.__name__,
            )
            return
        playtime = coerce_progress_int(payload.get("UserTotalPlaytime", 0))
        if playtime > 0:
            self._playtime_start = int(time.time()) - playtime
            log_event(logger, AREA_RA, "playtime_seeded", playtime_sec=playtime)

    def _clear_mirrored_presence(self):
        with self._state_lock:
            self.mirrored_presence = None

    def _set_mirrored_presence(self, last_game_id, presence):
        update_kwargs = presence.update_kwargs
        buttons = update_kwargs.get("buttons") or []
        with self._state_lock:
            self.mirrored_presence = MirroredPresence(
                game_id=int(last_game_id),
                title=update_kwargs.get("name") or presence.game_title,
                details=update_kwargs.get("details"),
                state=update_kwargs.get("state"),
                console_name=presence.console_name,
                game_icon_url=update_kwargs.get("large_image"),
                large_text=update_kwargs.get("large_text"),
                achievement_count=presence.achievement_count,
                achievement_total=presence.achievement_total,
                show_achievement_progress=bool(
                    self.config.get("show_achievement_progress", True)
                ),
                buttons=[dict(button) for button in buttons],
                developer_activity=presence.developer_activity,
            )

    def _configure_gateway(self):
        # The presence factory (and status callback) can be swapped after
        # construction, so push the current ones before connecting.
        self.discord_gateway.presence_factory = self._presence_factory
        self.discord_gateway.status_callback = self.status_callback

    def _connect_rpc(self):
        self._configure_gateway()
        return self.discord_gateway.connect()

    def _disconnect_rpc(self):
        self.discord_gateway.disconnect()
        self._clear_mirrored_presence()

    def _presence_builder(self):
        return PresenceBuilder(self._config_snapshot(), self.console_icons)

    def _roles_for_user(self, username, apikey):
        now = time.monotonic()
        if (
            self._ra_role_cache_username == username
            and now - self._ra_role_cache_at < ROLE_REFRESH_INTERVAL_SECONDS
        ):
            return (
                self._ra_role_cache_visible_role,
                self._ra_role_cache_displayable_roles,
            )

        try:
            profile = ra_get_user_profile_v2(username, apikey)
            visible_role = profile.get("visibleRole")
            displayable_roles = profile.get("displayableRoles")
        except requests.RequestException as exc:
            visible_role = None
            displayable_roles = None
            log_event(
                logger,
                AREA_RA,
                "v2_role_lookup_failed",
                level=logging.WARNING,
                error_type=exc.__class__.__name__,
                detail=format_api_error(exc),
            )
        except APIResponseError:
            visible_role = None
            displayable_roles = None
            log_event(
                logger,
                AREA_RA,
                "v2_role_lookup_failed",
                level=logging.WARNING,
                error_type="APIResponseError",
                reason="unexpected_payload",
            )

        self._ra_role_cache_username = username
        self._ra_role_cache_visible_role = visible_role
        self._ra_role_cache_displayable_roles = displayable_roles
        self._ra_role_cache_at = now
        return visible_role, displayable_roles

    def _loop(self):
        try:
            log_event(logger, AREA_WORKER, "loop_started")
            self.set_ra_status(False)
            self.status_callback("connecting", "Starting...")
            # Snapshot the session identity once under the state lock; the
            # controller may swap self.config from the UI thread at any time.
            with self._state_lock:
                self.config = normalize_config(self.config)
                session = dict(self.config)
            username = session["username"]
            apikey = session["apikey"]
            interval = session["interval"]
            timeout_sec = session["timeout"]
            backoff = BackoffPolicy(interval)
            consecutive_errors = 0

            while not self._should_stop():
                try:
                    user_data = ra_get_user_summary(
                        username,
                        apikey,
                        recent_games=SUMMARY_RECENT_GAMES,
                        recent_achievements=1,
                    )
                    if self._should_stop():
                        break
                    self._update_play_mode(user_data)

                    was_ra_connected = self.ra_connected
                    self.set_ra_status(True)
                    visible_role, displayable_roles = self._roles_for_user(username, apikey)
                    self.set_ra_role(
                        user_data.get("Permissions"),
                        visible_role=visible_role,
                        displayable_roles=displayable_roles,
                    )
                    if not was_ra_connected:
                        log_event(logger, AREA_RA, "connection_succeeded")
                    last_game_id = coerce_progress_int(user_data.get("LastGameID", 0))

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
                        self._clear_game_state()
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
                        self._clear_game_state()
                        self.status_callback("disconnected", "Not actively playing")
                        consecutive_errors = 0
                        self._sleep(interval)
                        continue

                    progress_data = user_data.get("Awarded")
                    if not isinstance(progress_data, dict):
                        raise APIResponseError
                    if str(last_game_id) not in progress_data:
                        progress_data = ra_get_user_progress(username, apikey, last_game_id)

                    game_changed = last_game_id != self._current_game_id
                    if game_changed:
                        self._game_data = ra_get_game(username, apikey, last_game_id)
                        self._current_game_id = last_game_id
                        if self.rpc_connected:
                            self.start_time = int(time.time())
                        self._seed_playtime_start(username, apikey, last_game_id)
                    game_data = self._game_data
                    if self._should_stop():
                        break


                    playtime_enabled = self._config_snapshot().get("show_total_playtime", True)
                    start_time = (
                        self._playtime_start if playtime_enabled else None
                    ) or self.start_time

                    presence_builder = self._presence_builder()
                    presence = presence_builder.build(
                        username=username,
                        last_game_id=last_game_id,
                        rich_presence_message=rp_msg,
                        game_data=game_data,
                        progress_data=progress_data,
                        start_time=start_time,
                        play_mode=self._play_mode,
                    )

                    if not self._connect_rpc():
                        self._clear_mirrored_presence()
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
                        mode=self._play_mode,
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
                    self._set_mirrored_presence(last_game_id, presence)
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
                except Exception as exc:  # noqa: BLE001 the worker loop must survive any iteration failure; classified below
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
            self._clear_game_state()
            self._play_mode = None
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
        for _ in range(int(seconds)):
            if self._should_stop():
                return
            time.sleep(1)
