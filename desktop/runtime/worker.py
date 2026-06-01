"""Desktop runtime worker that mirrors RetroAchievements into Discord RPC."""

import logging
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from pypresence import ActivityType, Presence
from pypresence import exceptions as pypresence_exceptions

from desktop.core.api import (
    APIResponseError,
    format_api_error,
    ra_get_game,
    ra_get_user_progress,
    ra_get_user_summary,
    trimmer,
)
from desktop.core.constants import DISCORD_APP_ID
from desktop.core.settings import normalize_config
from desktop.runtime.backoff import BackoffPolicy
from desktop.runtime.storage import load_config, load_console_icons

DEVELOPER_ACTIVITY_MESSAGES = {
    "inspecting memory",
    "developing achievements",
}
DISCORD_IPC_PIPES = tuple(range(10))
logger = logging.getLogger(__name__)


def _safe_exception_name(exc):
    """Return a diagnostic exception label without payload details."""
    return exc.__class__.__name__


def _close_rpc_client(rpc):
    """Best-effort cleanup for a Discord RPC client."""
    if not rpc:
        return
    try:
        rpc.close()
    except Exception:
        pass


def is_discord_unavailable_error(exc):
    """Recognize Discord IPC errors that usually mean Discord is not running."""
    return isinstance(
        exc,
        (
            pypresence_exceptions.DiscordNotFound,
            pypresence_exceptions.InvalidPipe,
            pypresence_exceptions.PipeClosed,
            pypresence_exceptions.ConnectionTimeout,
            pypresence_exceptions.ResponseTimeout,
            BrokenPipeError,
            ConnectionRefusedError,
            ConnectionResetError,
            FileNotFoundError,
            TimeoutError,
        ),
    )


class RPCWorker:
    """Poll RetroAchievements and mirror the active session to Discord RPC."""

    def __init__(
        self,
        status_callback=None,
        initial_config=None,
        console_icons=None,
        presence_factory=Presence,
    ):
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._external_callback = status_callback
        self._presence_factory = presence_factory
        self.config = normalize_config(
            initial_config if initial_config is not None else load_config()
        )
        self.console_icons = console_icons if console_icons is not None else load_console_icons()
        self.running = False
        self.thread = None
        self.rpc = None
        self.rpc_connected = False
        self.rpc_pipe = None
        self.start_time = None
        self._current_game_id = None
        self.current_status = "disconnected"
        self.status_text = "Not running"
        self.ra_connected = False
        self.ra_status_text = "Not connected to RetroAchievements"

    def set_status_callback(self, callback):
        """Register the UI-facing status callback used by the runtime shell."""
        self._external_callback = callback

    def status_callback(self, status, text):
        """Store the latest worker status and forward it to the UI if present."""
        self.current_status = status
        self.status_text = text
        if self._external_callback:
            self._external_callback(status, text)

    def set_ra_status(self, connected):
        """Track whether the RetroAchievements API is currently reachable."""
        self.ra_connected = connected
        self.ra_status_text = (
            "Connected to RetroAchievements"
            if connected
            else "Not connected to RetroAchievements"
        )

    def is_busy(self):
        """Return whether the worker is active or still shutting down."""
        with self._state_lock:
            return self.running or (self.thread is not None and self.thread.is_alive())

    def is_stopping(self):
        """Return whether the worker is in its shutdown grace period."""
        with self._state_lock:
            return not self.running and self.thread is not None and self.thread.is_alive()

    def start(self, config=None):
        """Start the polling thread if credentials are available."""
        with self._state_lock:
            if self.running or (self.thread is not None and self.thread.is_alive()):
                logger.info("Worker start skipped already_running=True")
                return False

            cfg = normalize_config(config if config is not None else load_config())
            if not cfg["username"] or not cfg["apikey"]:
                logger.info(
                    (
                        "Worker start skipped missing_credentials "
                        "username_present=%s apikey_present=%s"
                    ),
                    bool(cfg["username"]),
                    bool(cfg["apikey"]),
                )
                self.set_ra_status(False)
                self.status_callback("error", "Username or API Key missing")
                return False

            self.config = cfg
            self._stop_event.clear()
            self.running = True
            logger.info(
                "Worker starting interval=%s timeout=%s achievement_progress=%s",
                cfg["interval"],
                cfg["timeout"],
                bool(cfg.get("show_achievement_progress", True)),
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
                logger.info("Worker stop requested already_stopped=True")
                self._disconnect_rpc()
                self._current_game_id = None
                self.set_ra_status(False)
                self.status_callback("disconnected", "Stopped")
                return True
            self.running = False
            self._stop_event.set()
            logger.info(
                "Worker stop requested timeout=%s thread_alive=%s",
                timeout,
                bool(thread and thread.is_alive()),
            )

        if thread and thread is not threading.current_thread():
            thread.join(timeout=timeout)

        stopped = not thread or not thread.is_alive()
        if stopped:
            logger.info("Worker stopped cleanly")
            self.status_callback("disconnected", "Stopped")
        else:
            logger.warning("Worker did not stop within timeout=%s", timeout)
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

    def _coerce_progress_int(self, value):
        """Coerce loose API progress values into non-negative integers."""
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    def _build_achievement_state(self, total, achieved, achieved_hc):
        """Translate raw progress counts into the Discord state label."""
        if total <= 0:
            return "No achievements available", 0
        if achieved <= 0:
            return "No achievements yet", 0
        if achieved_hc < achieved:
            return "\U0001F3C6 Softcore", achieved
        return "\U0001F3C6 Hardcore", achieved_hc

    def _is_developer_activity(self, rich_presence_message):
        """Return whether the RA rich presence text means achievement dev work."""
        if not isinstance(rich_presence_message, str):
            return False
        return rich_presence_message.strip().casefold() in DEVELOPER_ACTIVITY_MESSAGES

    def _build_display_game_title(self, game_title, is_developer_activity):
        """Decorate the Discord game title when the user is developing achievements."""
        if is_developer_activity:
            return f"\U0001F6E0\ufe0f {game_title} \U0001F6E0\ufe0f"
        return game_title

    def _unexpected_api_response(self):
        """Surface a standard unexpected-API-response error to the UI."""
        logger.warning("RetroAchievements returned unexpected payload")
        self._disconnect_rpc()
        self.set_ra_status(False)
        self.status_callback("error", "API error: unexpected response")

    def _discord_pipe_order(self):
        """Return the Discord IPC pipe order, preferring the last working pipe."""
        if self.rpc_pipe in DISCORD_IPC_PIPES:
            return (self.rpc_pipe,) + tuple(
                pipe for pipe in DISCORD_IPC_PIPES if pipe != self.rpc_pipe
            )
        return DISCORD_IPC_PIPES

    def _connect_rpc_pipe(self, pipe):
        """Create and connect a Discord RPC client for one IPC pipe index."""
        logger.info("Discord IPC connect attempt pipe=%s", pipe)
        rpc = self._presence_factory(DISCORD_APP_ID, pipe=pipe)
        try:
            rpc.connect()
        except Exception:
            logger.info("Discord IPC connect failed pipe=%s", pipe)
            _close_rpc_client(rpc)
            raise
        return rpc

    def _connect_rpc(self):
        """Open the Discord IPC connection if it is not already active."""
        with self._lock:
            if self.rpc_connected:
                logger.info("Discord IPC already connected pipe=%s", self.rpc_pipe)
                return True
            _close_rpc_client(self.rpc)
            self.rpc = None
            self.rpc_connected = False
            self.start_time = None

            for pipe in self._discord_pipe_order():
                try:
                    self.rpc = self._connect_rpc_pipe(pipe)
                    self.rpc_connected = True
                    self.rpc_pipe = pipe
                    self.start_time = int(time.time())
                    logger.info("Discord IPC connected pipe=%s", pipe)
                    self.status_callback("connected", "Connected to Discord")
                    return True
                except pypresence_exceptions.InvalidID:
                    self.rpc = None
                    logger.error(
                        "Discord IPC connection failed invalid_client_id=True pipe=%s",
                        pipe,
                    )
                    self.status_callback("error", "Discord connection failed")
                    return False
                except Exception as exc:
                    self.rpc = None
                    if is_discord_unavailable_error(exc):
                        logger.info(
                            "Discord IPC pipe unavailable pipe=%s error_type=%s",
                            pipe,
                            _safe_exception_name(exc),
                        )
                        continue
                    logger.warning(
                        "Discord IPC connection failed pipe=%s error_type=%s",
                        pipe,
                        _safe_exception_name(exc),
                    )
                    self.status_callback("error", "Discord connection failed")
                    return False

            self.rpc_pipe = None
            logger.warning("Discord unavailable no_ipc_pipe_connected=True")
            self.status_callback("error", "Discord is not open")
            return False

    def _disconnect_rpc(self):
        """Clear Discord presence and close the current IPC client safely."""
        with self._lock:
            if self.rpc:
                if self.rpc_connected:
                    try:
                        self.rpc.clear()
                        self.rpc.close()
                        logger.info("Discord IPC cleared and closed pipe=%s", self.rpc_pipe)
                    except Exception:
                        logger.warning("Discord IPC cleanup failed pipe=%s", self.rpc_pipe)
                        pass
                else:
                    try:
                        self.rpc.close()
                        logger.info("Discord IPC closed before connection")
                    except Exception:
                        logger.warning("Discord IPC close failed before connection")
                        pass
            self.rpc = None
            self.rpc_connected = False
            self.start_time = None

    def _loop(self):
        """Continuously poll RA, build presence data, and update Discord."""
        try:
            logger.info("Worker loop started")
            self.set_ra_status(False)
            self.status_callback("connecting", "Starting...")
            self.config = normalize_config(self.config)
            username = self.config["username"]
            apikey = self.config["apikey"]
            interval = self.config["interval"]
            timeout_sec = self.config["timeout"]
            backoff = BackoffPolicy(interval)
            consecutive_errors = 0

            while not self._should_stop():
                try:
                    user_data = ra_get_user_summary(username, apikey)
                    if self._should_stop():
                        break

                    was_ra_connected = self.ra_connected
                    self.set_ra_status(True)
                    if not was_ra_connected:
                        logger.info("RetroAchievements connection succeeded")
                    last_game_id = self._coerce_progress_int(user_data.get("LastGameID", 0))


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
                            logger.info("User marked not playing reason=no_last_game_id")
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
                            logger.info(
                                "User marked not actively playing reason=rich_presence_stale timeout=%s",
                                timeout_sec,
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

                    game_title = game_data.get("GameTitle", "Unknown")
                    if not isinstance(game_title, str):
                        raise APIResponseError
                    is_developer_activity = self._is_developer_activity(rp_msg)
                    display_game_title = self._build_display_game_title(
                        game_title,
                        is_developer_activity,
                    )

                    console_name = game_data.get("ConsoleName", "Unknown")
                    if not isinstance(console_name, str):
                        raise APIResponseError

                    console_id = str(game_data.get("ConsoleID", "0"))
                    image_icon = game_data.get("ImageIcon", "")
                    if image_icon is None:
                        image_icon = ""
                    if not isinstance(image_icon, str):
                        raise APIResponseError

                    if last_game_id != self._current_game_id:
                        self._current_game_id = last_game_id
                        if self.rpc_connected:
                            self.start_time = int(time.time())

                    gid_str = str(last_game_id)
                    prog = progress_data.get(gid_str, {})
                    if prog is None:
                        prog = {}
                    if not isinstance(prog, dict):
                        raise APIResponseError

                    total = self._coerce_progress_int(prog.get("NumPossibleAchievements", 0))
                    achieved = self._coerce_progress_int(prog.get("NumAchieved", 0))
                    achieved_hc = self._coerce_progress_int(prog.get("NumAchievedHardcore", 0))
                    state_str, achi_count = self._build_achievement_state(
                        total,
                        achieved,
                        achieved_hc,
                    )

                    show_achievement_progress = self.config.get("show_achievement_progress", True)
                    party = [achi_count, total] if show_achievement_progress and total > 0 else None
                    if show_achievement_progress and total > 0:
                        large_tooltip = f"{achi_count}/{total} achievements"
                    else:
                        large_tooltip = game_title

                    game_url = f"https://retroachievements.org/game/{last_game_id}"
                    profile_url = f"https://retroachievements.org/user/{quote(username)}"

                    buttons = []
                    if self.config.get("show_gamepage_button", True):
                        buttons.append({"label": "View on RetroAchievements", "url": game_url})
                    if self.config.get("show_profile_button", True):
                        buttons.append({"label": f"{username}'s RA Page", "url": profile_url})
                    if not buttons:
                        buttons = None

                    large_img = (
                        f"https://media.retroachievements.org{image_icon}"
                        if image_icon
                        else None
                    )
                    small_img = self.console_icons.get(console_id)

                    if not self._connect_rpc():
                        self._sleep(interval)
                        continue
                    if self._should_stop():
                        break

                    update_kwargs = dict(
                        activity_type=ActivityType.PLAYING,
                        name=trimmer(display_game_title),
                        details=trimmer(rp_msg) if rp_msg else None,
                        state=state_str,
                        start=self.start_time,
                        large_image=large_img,
                        large_text=large_tooltip,
                        small_image=small_img,
                        small_text=console_name,
                        buttons=buttons,
                    )
                    if party:
                        update_kwargs["party_id"] = f"ra_{last_game_id}"
                        update_kwargs["party_size"] = party

                    button_count = len(buttons or [])
                    logger.info(
                        (
                            "Discord rich presence update attempt game_id=%s "
                            "console_id=%s console_name=%s pipe=%s "
                            "achievements=%s/%s buttons=%s developer_activity=%s"
                        ),
                        last_game_id,
                        console_id,
                        console_name,
                        self.rpc_pipe,
                        achi_count,
                        total,
                        button_count,
                        is_developer_activity,
                    )
                    try:
                        self.rpc.update(**update_kwargs)
                    except Exception as exc:
                        logger.warning(
                            "Discord rich presence update failed game_id=%s pipe=%s error_type=%s",
                            last_game_id,
                            self.rpc_pipe,
                            _safe_exception_name(exc),
                        )
                        raise
                    logger.info(
                        (
                            "Discord rich presence update succeeded game_id=%s "
                            "pipe=%s achievements=%s/%s buttons=%s"
                        ),
                        last_game_id,
                        self.rpc_pipe,
                        achi_count,
                        total,
                        button_count,
                    )
                    activity_label = "Developing" if is_developer_activity else "Playing"
                    self.status_callback(
                        "connected",
                        f"{activity_label}: {game_title} ({console_name})",
                    )
                    consecutive_errors = 0

                except requests.RequestException as exc:
                    consecutive_errors += 1
                    self._disconnect_rpc()
                    self.set_ra_status(False)
                    logger.warning(
                        "RetroAchievements request failed error=%s consecutive_errors=%s",
                        format_api_error(exc),
                        consecutive_errors,
                    )
                    self.status_callback("error", format_api_error(exc))
                except APIResponseError:
                    consecutive_errors += 1
                    self._unexpected_api_response()
                except Exception as exc:
                    consecutive_errors += 1
                    self._disconnect_rpc()
                    if is_discord_unavailable_error(exc):
                        logger.warning(
                            (
                                "Discord unavailable during worker loop "
                                "error_type=%s consecutive_errors=%s"
                            ),
                            _safe_exception_name(exc),
                            consecutive_errors,
                        )
                        self.status_callback("error", "Discord is not open")
                    else:
                        self.set_ra_status(False)
                        logger.exception(
                            "Unexpected worker failure consecutive_errors=%s",
                            consecutive_errors,
                        )
                        self.status_callback("error", "Error: unexpected failure")

                wait = backoff.delay_for(consecutive_errors)
                if consecutive_errors > 0:
                    logger.info("Worker backing off wait_seconds=%s", wait)
                self._sleep(wait)
        finally:
            self._disconnect_rpc()
            self._current_game_id = None
            self.set_ra_status(False)
            self._current_thread_done()
            if self._stop_event.is_set():
                self.status_callback("disconnected", "Stopped")
            logger.info(
                "Worker loop finished stop_requested=%s",
                self._stop_event.is_set(),
            )

    def _sleep(self, seconds):
        """Sleep in one-second slices so shutdown stays responsive."""
        for _ in range(int(seconds)):
            if self._should_stop():
                return
            time.sleep(1)
