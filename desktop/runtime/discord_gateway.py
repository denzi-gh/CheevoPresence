"""Discord Rich Presence IPC gateway."""

import logging
import threading
import time

from pypresence import Presence
from pypresence import exceptions as pypresence_exceptions

from desktop.core.constants import DISCORD_APP_ID

DISCORD_IPC_PIPES = tuple(range(10))
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
    ):
        self.client_id = client_id
        self.presence_factory = presence_factory
        self.status_callback = status_callback
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

    def connect_pipe(self, pipe):
        """Create and connect a Discord RPC client for one IPC pipe index."""
        logger.info("Discord IPC connect attempt pipe=%s", pipe)
        rpc = self.presence_factory(self.client_id, pipe=pipe)
        try:
            rpc.connect()
        except Exception:
            logger.info("Discord IPC connect failed pipe=%s", pipe)
            close_rpc_client(rpc)
            raise
        return rpc

    def connect(self):
        """Open the Discord IPC connection if it is not already active."""
        with self._lock:
            if self.rpc_connected:
                logger.info("Discord IPC already connected pipe=%s", self.rpc_pipe)
                return True
            close_rpc_client(self.rpc)
            self.rpc = None
            self.rpc_connected = False
            self.start_time = None

            for pipe in self.pipe_order():
                try:
                    self.rpc = self.connect_pipe(pipe)
                    self.rpc_connected = True
                    self.rpc_pipe = pipe
                    self.start_time = int(time.time())
                    logger.info("Discord IPC connected pipe=%s", pipe)
                    self._set_status("connected", "Connected to Discord")
                    return True
                except pypresence_exceptions.InvalidID:
                    self.rpc = None
                    logger.error(
                        "Discord IPC connection failed invalid_client_id=True pipe=%s",
                        pipe,
                    )
                    self._set_status("error", "Discord connection failed")
                    return False
                except Exception as exc:
                    self.rpc = None
                    if is_discord_unavailable_error(exc):
                        logger.info(
                            "Discord IPC pipe unavailable pipe=%s error_type=%s",
                            pipe,
                            safe_exception_name(exc),
                        )
                        continue
                    logger.warning(
                        "Discord IPC connection failed pipe=%s error_type=%s",
                        pipe,
                        safe_exception_name(exc),
                    )
                    self._set_status("error", "Discord connection failed")
                    return False

            self.rpc_pipe = None
            logger.warning("Discord unavailable no_ipc_pipe_connected=True")
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
