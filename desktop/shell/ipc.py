"""Local IPC bridge between the native host app and the shared settings UI."""

from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import socket
import tempfile
import threading
import time
import uuid
from dataclasses import asdict

from desktop.core.log_events import AREA_IPC, log_event
from desktop.runtime.controller import ConnectResult
from desktop.runtime.state import WorkerState
from desktop.runtime.update_service import UpdateInstallResult, UpdateStatus

logger = logging.getLogger(__name__)

SETTINGS_ADDRESS_ENV = "CHEEVO_SETTINGS_SOCKET"
SETTINGS_AUTH_ENV = "CHEEVO_SETTINGS_TOKEN"
_MAX_MESSAGE_BYTES = 1024 * 1024
_TCP_ADDRESS_PREFIX = "tcp://"
# The settings UI polls these methods ~once per second; log them at most this
# often so cheevo.log stays readable. Failures and other methods always log.
IPC_THROTTLED_METHODS = frozenset({"get_state"})
IPC_LOG_THROTTLE_SECONDS = 60


def _socket_dir():
    user_token = str(os.getuid()) if hasattr(os, "getuid") else os.environ.get("USERNAME", "user")
    path = os.path.join(tempfile.gettempdir(), f"CheevoPresence-{user_token}")
    os.makedirs(path, mode=0o700, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _make_socket_path():
    return os.path.join(_socket_dir(), f"settings-{uuid.uuid4().hex[:8]}.sock")


def _supports_unix_socket():
    return hasattr(socket, "AF_UNIX")


def _format_tcp_address(host, port):
    return f"{_TCP_ADDRESS_PREFIX}{host}:{port}"


def _parse_tcp_address(address):
    if not str(address).startswith(_TCP_ADDRESS_PREFIX):
        raise ValueError("Invalid TCP IPC address.")
    endpoint = str(address)[len(_TCP_ADDRESS_PREFIX) :]
    host, separator, port_text = endpoint.rpartition(":")
    if not host or not separator:
        raise ValueError("Invalid TCP IPC address.")
    return host, int(port_text)


def _is_tcp_address(address):
    return str(address or "").startswith(_TCP_ADDRESS_PREFIX)


def _serialize_dataclass(value):
    return asdict(value)


def _public_config(config):
    payload = dict(config or {})
    payload["apikey"] = ""
    payload["apikey_present"] = bool((config or {}).get("apikey"))
    return payload


def _read_message(conn):
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
    conn.sendall(json.dumps(payload).encode("utf-8") + b"\n")


def _format_ipc_error(exc):
    if isinstance(exc, PermissionError):
        return "Invalid IPC token."
    if isinstance(exc, ValueError):
        return str(exc) or "Invalid IPC request."
    return "IPC request failed."


class SettingsHostService:

    def __init__(self, controller, on_quit=None, on_request=None):
        self.controller = controller
        self.on_quit = on_quit
        self.on_request = on_request
        self.address = ""
        self.auth_token = secrets.token_hex(32)
        self.listener = None
        self.thread = None
        self._uses_unix_socket = False
        self._stop_event = threading.Event()
        self._last_request_log = {}

    def start(self):
        self._stop_event.clear()
        self._uses_unix_socket = _supports_unix_socket()
        if self._uses_unix_socket:
            self.address = _make_socket_path()
            if os.path.exists(self.address):
                os.remove(self.address)
            self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.listener.bind(self.address)
            os.chmod(self.address, 0o600)
        else:
            self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.listener.bind(("127.0.0.1", 0))
            host, port = self.listener.getsockname()
            self.address = _format_tcp_address(host, port)
        self.listener.listen()
        self.listener.settimeout(0.5)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        log_event(logger, AREA_IPC, "host_service_start", socket=self.address)

    def stop(self):
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
        if self._uses_unix_socket and os.path.exists(self.address):
            try:
                os.remove(self.address)
            except OSError:
                pass
        log_event(logger, AREA_IPC, "host_service_stop")

    def get_launch_env(self):
        return {
            SETTINGS_ADDRESS_ENV: self.address,
            SETTINGS_AUTH_ENV: self.auth_token,
        }

    def _build_state(self):
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
        supplied_token = request.get("token")
        if not isinstance(supplied_token, str) or not hmac.compare_digest(
            supplied_token.encode("utf-8"),
            self.auth_token.encode("utf-8"),
        ):
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

    def _should_log_request(self, method, now):
        if method not in IPC_THROTTLED_METHODS:
            return True
        last = self._last_request_log.get(method, 0)
        if now - last >= IPC_LOG_THROTTLE_SECONDS:
            self._last_request_log[method] = now
            return True
        return False

    def _serve(self):
        while not self._stop_event.is_set():
            try:
                conn, _addr = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            start = time.monotonic()
            method = None
            try:
                conn.settimeout(5)
                request = _read_message(conn)
                method = request.get("method")
                response = {"ok": True, "result": self._dispatch(request)}
                if self.on_request:
                    self.on_request(method)
                if self._should_log_request(method, start):
                    log_event(
                        logger,
                        AREA_IPC,
                        "request",
                        method=method,
                        success=True,
                        elapsed_ms=round((time.monotonic() - start) * 1000),
                    )
            except Exception as exc:  # noqa: BLE001 dispatch boundary; error is formatted generically for the client
                response = {"ok": False, "error": _format_ipc_error(exc)}
                log_event(
                    logger,
                    AREA_IPC,
                    "request",
                    level=logging.WARNING,
                    method=method,
                    success=False,
                    error_type=exc.__class__.__name__,
                    elapsed_ms=round((time.monotonic() - start) * 1000),
                )
            try:
                _write_message(conn, response)
            except OSError as exc:
                log_event(
                    logger,
                    AREA_IPC,
                    "response_write_failed",
                    level=logging.WARNING,
                    method=method,
                    error_type=exc.__class__.__name__,
                )
            except (TypeError, ValueError) as exc:
                log_event(
                    logger,
                    AREA_IPC,
                    "response_serialize_failed",
                    level=logging.ERROR,
                    exc_info=True,
                    method=method,
                    error_type=exc.__class__.__name__,
                )
            finally:
                try:
                    conn.close()
                except OSError:
                    pass


class RemoteWorkerProxy:
    """A read-only view of the host worker's state, fed by IPC payloads."""

    def __init__(self):
        self._state = WorkerState.from_dict({})

    def update(self, payload):
        self._state = WorkerState.from_dict(payload)

    def get_state(self):
        return self._state

    def __getattr__(self, name):
        state = self.__dict__.get("_state")
        if state is not None and hasattr(state, name):
            return getattr(state, name)
        raise AttributeError(name)


class RemotePlatformProxy:

    def __init__(self):
        self.startup_toggle_label = "Launch on system startup"
        self._autostart_enabled = False

    def update(self, payload):
        self.startup_toggle_label = str(payload.get("startup_toggle_label") or self.startup_toggle_label)
        self._autostart_enabled = bool(payload.get("autostart_enabled", False))

    def is_autostart_enabled(self):
        return self._autostart_enabled


class RemoteAppController:

    def __init__(self, address=None, auth_token=None):
        self.address = address or os.environ.get(SETTINGS_ADDRESS_ENV, "").strip()
        self.auth_token = auth_token or os.environ.get(SETTINGS_AUTH_ENV, "").strip()
        if not self.address or not self.auth_token:
            raise RuntimeError("Missing settings bootstrap environment.")
        self.worker = RemoteWorkerProxy()
        self.platform = RemotePlatformProxy()
        self.config = {}
        self._update_status = UpdateStatus()
        self.poll_runtime_state()

    def _request(self, method, **params):
        if _is_tcp_address(self.address):
            family = socket.AF_INET
            endpoint = _parse_tcp_address(self.address)
        else:
            if not _supports_unix_socket():
                raise RuntimeError("This platform does not support Unix IPC sockets.")
            family = socket.AF_UNIX
            endpoint = self.address
        with socket.socket(family, socket.SOCK_STREAM) as conn:
            conn.settimeout(5)
            conn.connect(endpoint)
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
        self.config = dict(state.get("config") or {})
        self.worker.update(state.get("worker") or {})
        self.platform.update(state.get("platform") or {})
        self._update_status = UpdateStatus(**(state.get("update_status") or {}))

    def poll_runtime_state(self):
        self._apply_state(self._request("get_state"))

    def load_config(self):
        self.config = dict(self._request("load_config") or {})
        return dict(self.config)

    def get_update_status(self):
        return self._update_status

    def connect(self, config):
        result = ConnectResult(**(self._request("connect", config=config) or {}))
        self.poll_runtime_state()
        return result

    def disconnect(self):
        result = self._request("disconnect")
        self.poll_runtime_state()
        return bool((result or {}).get("success"))

    def install_update(self):
        result = UpdateInstallResult(**(self._request("install_update") or {}))
        self.poll_runtime_state()
        return result

    def quit_app(self):
        self._request("quit_app")
