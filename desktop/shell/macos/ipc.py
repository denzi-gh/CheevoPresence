"""Local IPC bridge between the native macOS host and the shared settings UI."""

from __future__ import annotations

import json
import os
import socket
import threading
import uuid
from dataclasses import asdict

from desktop.runtime.controller import ConnectResult, UpdateInstallResult, UpdateStatus
from desktop.runtime.state import WorkerState

MACOS_SETTINGS_ADDRESS_ENV = "CHEEVO_MACOS_SETTINGS_SOCKET"
MACOS_SETTINGS_AUTH_ENV = "CHEEVO_MACOS_SETTINGS_TOKEN"
_MAX_MESSAGE_BYTES = 1024 * 1024


def _socket_dir():
    """Return the per-user directory used to host the settings socket."""
    path = os.path.join("/tmp", f"CheevoPresence-{os.getuid()}")
    os.makedirs(path, mode=0o700, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _make_socket_path():
    """Return a short AF_UNIX socket path that fits macOS length limits."""
    return os.path.join(_socket_dir(), f"settings-{uuid.uuid4().hex[:8]}.sock")


def _serialize_dataclass(value):
    """Convert runtime dataclasses into plain dictionaries for IPC."""
    return asdict(value)


def _public_config(config):
    """Return the config fields safe to include in background state polling."""
    payload = dict(config or {})
    payload["apikey"] = ""
    payload["apikey_present"] = bool((config or {}).get("apikey"))
    return payload


def _read_message(conn):
    """Read a single newline-delimited JSON message from a socket."""
    chunks = []
    total = 0
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > _MAX_MESSAGE_BYTES:
            raise RuntimeError("IPC message too large.")
        if b"\n" in chunk:
            break
    line = b"".join(chunks)
    if not line:
        raise RuntimeError("Empty IPC message.")
    line = line.split(b"\n", 1)[0]
    return json.loads(line.decode("utf-8"))


def _write_message(conn, payload):
    """Write one newline-delimited JSON response to a socket."""
    conn.sendall(json.dumps(payload).encode("utf-8") + b"\n")


def _format_ipc_error(exc):
    """Return a client-safe IPC error string."""
    if isinstance(exc, PermissionError):
        return "Invalid IPC token."
    if isinstance(exc, ValueError):
        return str(exc) or "Invalid IPC request."
    return "IPC request failed."


class MacOSAppService:
    """Expose the main-app controller to the companion settings process."""

    def __init__(self, controller, on_quit=None):
        self.controller = controller
        self.on_quit = on_quit
        self.address = _make_socket_path()
        self.auth_token = uuid.uuid4().hex
        self.listener = None
        self.thread = None
        self._stop_event = threading.Event()

    def start(self):
        """Start the background request loop."""
        self._stop_event.clear()
        if os.path.exists(self.address):
            os.remove(self.address)
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(self.address)
        os.chmod(self.address, 0o600)
        self.listener.listen()
        self.listener.settimeout(0.5)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop serving requests and remove the socket path."""
        self._stop_event.set()
        if self.listener is not None:
            try:
                self.listener.close()
            except OSError:
                pass
            self.listener = None
        if (
            self.thread is not None
            and self.thread.is_alive()
            and threading.current_thread() is not self.thread
        ):
            self.thread.join(timeout=1)
        if os.path.exists(self.address):
            try:
                os.remove(self.address)
            except OSError:
                pass

    def get_launch_env(self):
        """Return the environment variables required by the settings client."""
        return {
            MACOS_SETTINGS_ADDRESS_ENV: self.address,
            MACOS_SETTINGS_AUTH_ENV: self.auth_token,
        }

    def _build_state(self):
        """Capture the current controller/worker/platform snapshot."""
        worker = self.controller.worker
        worker_state = worker.get_state()
        return {
            "config": _public_config(self.controller.config),
            "worker": asdict(worker_state),
            "platform": {
                "startup_toggle_label": self.controller.platform.startup_toggle_label,
                "autostart_enabled": self.controller.platform.is_autostart_enabled(),
            },
            "update_status": _serialize_dataclass(self.controller.get_update_status()),
        }

    def _dispatch(self, request):
        """Handle a single IPC request and return a serializable response."""
        if request.get("token") != self.auth_token:
            raise PermissionError("Invalid IPC token.")

        method = request.get("method")
        params = request.get("params") or {}

        if method == "get_state":
            return self._build_state()
        if method == "load_config":
            return self.controller.load_config()
        if method == "connect":
            return _serialize_dataclass(self.controller.connect(params.get("config") or {}))
        if method == "disconnect":
            return {"success": self.controller.disconnect()}
        if method == "install_update":
            return _serialize_dataclass(self.controller.install_update())
        if method == "quit_app":
            if self.on_quit:
                threading.Thread(target=self.on_quit, daemon=True).start()
            return {"success": True}
        raise ValueError(f"Unknown IPC method: {method}")

    def _serve(self):
        """Serve one-request connections until the host shuts down."""
        while not self._stop_event.is_set():
            try:
                conn, _addr = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.settimeout(5)
                request = _read_message(conn)
                response = {"ok": True, "result": self._dispatch(request)}
            except Exception as exc:
                response = {"ok": False, "error": _format_ipc_error(exc)}
            try:
                _write_message(conn, response)
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass


class RemoteWorkerProxy:
    """Mirror the main worker state inside the companion settings process."""

    def __init__(self):
        self.running = False
        self.current_status = "disconnected"
        self.status_text = "Not running"
        self.ra_connected = False
        self.ra_status_text = "Not connected to RetroAchievements"
        self._is_busy = False
        self._is_stopping = False

    def update(self, payload):
        """Replace the cached worker snapshot."""
        self.running = bool(payload.get("running", False))
        self.current_status = str(payload.get("current_status") or "disconnected")
        self.status_text = str(payload.get("status_text") or "Not running")
        self.ra_connected = bool(payload.get("ra_connected", False))
        self.ra_status_text = str(payload.get("ra_status_text") or "Not connected to RetroAchievements")
        self._is_busy = bool(payload.get("is_busy", False))
        self._is_stopping = bool(payload.get("is_stopping", False))

    def is_busy(self):
        """Return whether the host worker is running or shutting down."""
        return self._is_busy

    def is_stopping(self):
        """Return whether the host worker is in its shutdown grace period."""
        return self._is_stopping

    def get_state(self):
        """Return the cached host worker snapshot."""
        return WorkerState(
            running=self.running,
            is_busy=self._is_busy,
            is_stopping=self._is_stopping,
            current_status=self.current_status,
            status_text=self.status_text,
            ra_connected=self.ra_connected,
            ra_status_text=self.ra_status_text,
        )


class RemotePlatformProxy:
    """Expose the platform fields the Tk settings UI reads."""

    def __init__(self):
        self.startup_toggle_label = "Launch on system startup"
        self._autostart_enabled = False

    def update(self, payload):
        """Replace the cached platform snapshot."""
        self.startup_toggle_label = str(payload.get("startup_toggle_label") or self.startup_toggle_label)
        self._autostart_enabled = bool(payload.get("autostart_enabled", False))

    def is_autostart_enabled(self):
        """Return the cached launch-at-login state."""
        return self._autostart_enabled


class MacOSRemoteController:
    """Controller adapter used by the shared Tk UI in the settings client."""

    def __init__(self, address=None, auth_token=None):
        self.address = address or os.environ.get(MACOS_SETTINGS_ADDRESS_ENV, "").strip()
        self.auth_token = auth_token or os.environ.get(MACOS_SETTINGS_AUTH_ENV, "").strip()
        if not self.address or not self.auth_token:
            raise RuntimeError("Missing macOS settings bootstrap environment.")
        self.worker = RemoteWorkerProxy()
        self.platform = RemotePlatformProxy()
        self.config = {}
        self._update_status = UpdateStatus()
        self.poll_runtime_state()

    def _request(self, method, **params):
        """Send one request to the host service and return the decoded result."""
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(5)
            conn.connect(self.address)
            _write_message(
                conn,
                {
                    "token": self.auth_token,
                    "method": method,
                    "params": params,
                },
            )
            response = _read_message(conn)
        if not response.get("ok"):
            raise RuntimeError(response.get("error") or "IPC request failed")
        return response.get("result")

    def _apply_state(self, state):
        """Update cached worker/platform/update state from an IPC snapshot."""
        self.config = dict(state.get("config") or {})
        self.worker.update(state.get("worker") or {})
        self.platform.update(state.get("platform") or {})
        self._update_status = UpdateStatus(**(state.get("update_status") or {}))

    def poll_runtime_state(self):
        """Refresh the cached state from the host app."""
        self._apply_state(self._request("get_state"))

    def load_config(self):
        """Load the persisted config from the host controller."""
        self.config = dict(self._request("load_config") or {})
        return dict(self.config)

    def get_update_status(self):
        """Return the most recently cached update status."""
        return self._update_status

    def connect(self, config):
        """Request a connect action from the host app."""
        result = ConnectResult(**(self._request("connect", config=config) or {}))
        self.poll_runtime_state()
        return result

    def disconnect(self):
        """Request a disconnect action from the host app."""
        result = self._request("disconnect")
        self.poll_runtime_state()
        return bool((result or {}).get("success"))

    def install_update(self):
        """Request update staging from the host app."""
        result = UpdateInstallResult(**(self._request("install_update") or {}))
        self.poll_runtime_state()
        return result

    def quit_app(self):
        """Request full app shutdown from the host app."""
        self._request("quit_app")
