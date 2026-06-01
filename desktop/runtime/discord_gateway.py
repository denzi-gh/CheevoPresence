"""Discord Rich Presence IPC gateway."""

import logging
import threading
import time

from pypresence import Presence
from pypresence import exceptions as pypresence_exceptions

from desktop.core.constants import DISCORD_APP_ID
from desktop.runtime.log_events import AREA_DISCORD, log_event

DISCORD_IPC_PIPES = tuple(range(10))
DISCORD_CONNECT_TIMEOUT_SECONDS = 1.5
DISCORD_RESPONSE_TIMEOUT_SECONDS = 1.5
logger = logging.getLogger(__name__)


def safe_exception_name(exc):
    """Return a diagnostic exception label without payload details."""
    return exc.__class__.__name__


def close_rpc_client(rpc):
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


class DiscordPresenceGateway:
    """Own the Discord IPC client, pipe fallback, and presence updates."""

    def __init__(
        self,
        client_id=DISCORD_APP_ID,
        presence_factory=Presence,
        status_callback=None,
        connect_timeout=DISCORD_CONNECT_TIMEOUT_SECONDS,
        response_timeout=DISCORD_RESPONSE_TIMEOUT_SECONDS,
    ):
        self.client_id = client_id
        self.presence_factory = presence_factory
        self.status_callback = status_callback
        self.connect_timeout = connect_timeout
        self.response_timeout = response_timeout
        self._lock = threading.Lock()
        self.rpc = None
        self.rpc_connected = False
        self.rpc_pipe = None
        self.start_time = None

    def _set_status(self, status, text):
        if self.status_callback:
            self.status_callback(status, text)

    def pipe_order(self):
        """Return the Discord IPC pipe order, preferring the last working pipe."""
        if self.rpc_pipe in DISCORD_IPC_PIPES:
            return (self.rpc_pipe,) + tuple(
                pipe for pipe in DISCORD_IPC_PIPES if pipe != self.rpc_pipe
            )
        return DISCORD_IPC_PIPES

    def _create_presence(self, pipe):
        """Create a pypresence client with short IPC timeouts when supported."""
        try:
            return self.presence_factory(
                self.client_id,
                pipe=pipe,
                connection_timeout=self.connect_timeout,
                response_timeout=self.response_timeout,
            )
        except TypeError:
            return self.presence_factory(self.client_id, pipe=pipe)

    def connect_pipe(self, pipe):
        """Create and connect a Discord RPC client for one IPC pipe index."""
        log_event(
            logger,
            AREA_DISCORD,
            "ipc_connect_attempt",
            pipe=pipe,
            timeout_sec=self.connect_timeout,
        )
        start = time.monotonic()
        rpc = self._create_presence(pipe)
        done = threading.Event()
        errors = []

        def do_connect():
            try:
                rpc.connect()
            except Exception as exc:
                errors.append(exc)
            finally:
                done.set()

        thread = threading.Thread(
            target=do_connect,
            daemon=True,
            name=f"DiscordIPCConnect-{pipe}",
        )
        thread.start()
        try:
            if not done.wait(self.connect_timeout):
                close_rpc_client(rpc)
                raise pypresence_exceptions.ConnectionTimeout
            if errors:
                raise errors[0]
        except Exception as exc:
            log_event(
                logger,
                AREA_DISCORD,
                "ipc_connect_failed",
                pipe=pipe,
                error_type=safe_exception_name(exc),
                elapsed_ms=round((time.monotonic() - start) * 1000),
            )
            close_rpc_client(rpc)
            raise
        return rpc

    def connect(self):
        """Open the Discord IPC connection if it is not already active."""
        with self._lock:
            if self.rpc_connected:
                log_event(logger, AREA_DISCORD, "ipc_already_connected", pipe=self.rpc_pipe)
                return True
            close_rpc_client(self.rpc)
            self.rpc = None
            self.rpc_connected = False
            self.start_time = None
            start = time.monotonic()

            for pipe in self.pipe_order():
                try:
                    self.rpc = self.connect_pipe(pipe)
                    self.rpc_connected = True
                    self.rpc_pipe = pipe
                    self.start_time = int(time.time())
                    log_event(
                        logger,
                        AREA_DISCORD,
                        "ipc_connected",
                        pipe=pipe,
                        elapsed_ms=round((time.monotonic() - start) * 1000),
                    )
                    self._set_status("connected", "Connected to Discord")
                    return True
                except pypresence_exceptions.InvalidID:
                    self.rpc = None
                    log_event(
                        logger,
                        AREA_DISCORD,
                        "ipc_connect_failed",
                        level=logging.ERROR,
                        pipe=pipe,
                        reason="invalid_client_id",
                    )
                    self._set_status("error", "Discord connection failed")
                    return False
                except Exception as exc:
                    self.rpc = None
                    if is_discord_unavailable_error(exc):
                        log_event(
                            logger,
                            AREA_DISCORD,
                            "ipc_pipe_unavailable",
                            pipe=pipe,
                            error_type=safe_exception_name(exc),
                        )
                        continue
                    log_event(
                        logger,
                        AREA_DISCORD,
                        "ipc_connect_failed",
                        level=logging.WARNING,
                        pipe=pipe,
                        error_type=safe_exception_name(exc),
                    )
                    self._set_status("error", "Discord connection failed")
                    return False

            self.rpc_pipe = None
            log_event(
                logger,
                AREA_DISCORD,
                "ipc_unavailable",
                level=logging.WARNING,
                reason="discord_not_open",
            )
            self._set_status("error", "Discord is not open")
            return False

    def update(self, **kwargs):
        """Update the active Discord Rich Presence payload."""
        self.rpc.update(**kwargs)

    def disconnect(self):
        """Clear Discord presence and close the current IPC client safely."""
        with self._lock:
            if self.rpc:
                if self.rpc_connected:
                    try:
                        self.rpc.clear()
                        self.rpc.close()
                        log_event(logger, AREA_DISCORD, "clear_success", pipe=self.rpc_pipe)
                    except Exception:
                        log_event(
                            logger,
                            AREA_DISCORD,
                            "cleanup_failed",
                            level=logging.WARNING,
                            pipe=self.rpc_pipe,
                        )
                        pass
                else:
                    try:
                        self.rpc.close()
                        log_event(logger, AREA_DISCORD, "closed_before_connection")
                    except Exception:
                        log_event(
                            logger,
                            AREA_DISCORD,
                            "close_failed_before_connection",
                            level=logging.WARNING,
                        )
                        pass
            self.rpc = None
            self.rpc_connected = False
            self.start_time = None
