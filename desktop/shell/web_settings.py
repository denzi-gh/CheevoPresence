"""HTML/pywebview settings window for the desktop shell."""

from __future__ import annotations

import logging
import os
import json
import threading
import webbrowser
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import urlparse

from desktop.core.constants import APP_NAME, APP_VERSION, RA_SETTINGS_URL
from desktop.core.settings import normalize_config
from desktop.platform import get_platform_services
from desktop.runtime.log_events import AREA_SETTINGS, log_event
from desktop.runtime.storage import get_log_dir, get_resource_dir
from desktop.shell.settings_presenter import truncate_status_text

logger = logging.getLogger(__name__)

WINDOW_WIDTH = 640
WINDOW_HEIGHT = 530

ROLE_BADGE_STYLES = {
    "junior_developer": {
        "accent": "#f0b450",
        "fill": "rgba(231,163,58,.13)",
        "border": "rgba(231,163,58,.4)",
        "icon": "code",
    },
    "developer": {
        "accent": "#5fd07f",
        "fill": "rgba(63,191,99,.12)",
        "border": "rgba(63,191,99,.45)",
        "icon": "code",
    },
    "code_reviewer": {
        "accent": "#b0a0f0",
        "fill": "rgba(156,134,234,.13)",
        "border": "rgba(156,134,234,.45)",
        "icon": "search",
    },
    "moderator": {
        "accent": "#6fcfe2",
        "fill": "rgba(86,184,206,.13)",
        "border": "rgba(86,184,206,.45)",
        "icon": "shield",
    },
}
DEFAULT_ROLE_BADGE_STYLE = ROLE_BADGE_STYLES["junior_developer"]


def role_badge_style(tier):
    """Return web badge colors and icon metadata for a role tier."""
    return ROLE_BADGE_STYLES.get(tier, DEFAULT_ROLE_BADGE_STYLE)


def _asset_path(filename):
    """Resolve a web settings asset in source and frozen builds."""
    bundled = os.path.join(
        get_resource_dir(),
        "desktop",
        "shell",
        "web_assets",
        filename,
    )
    if os.path.exists(bundled):
        return bundled
    return os.path.join(os.path.dirname(__file__), "web_assets", filename)


def _asset_text(filename):
    """Read a packaged web settings asset as UTF-8 text."""
    with open(_asset_path(filename), "r", encoding="utf-8") as handle:
        return handle.read()


def _settings_html():
    """Return the settings page with CSS and JS inlined for webview engines."""
    html = _asset_text("settings.html")
    html = html.replace(
        '<link rel="stylesheet" href="./settings.css">',
        "<style>\n" + _asset_text("settings.css") + "\n</style>",
    )
    html = html.replace(
        '<script src="./settings.js"></script>',
        "<script>\n" + _asset_text("settings.js") + "\n</script>",
    )
    return html


def _dataclass_to_dict(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    return {}


def _public_config(config):
    payload = dict(config or {})
    apikey = payload.pop("apikey", "")
    payload["apikey_present"] = bool(apikey or payload.get("apikey_present"))
    return payload


class WebSettingsAPI:
    """Bridge used by the HTML settings window to call Python app services."""

    def __init__(self, controller, on_close=None, on_quit=None):
        self.controller = controller
        self.worker = controller.worker
        self.platform = controller.platform
        self.on_close = on_close
        self.on_quit = on_quit
        self.window = None
        self.cfg = {}
        self._closed = False
        self._is_connecting = False
        self._is_installing_update = False
        self._lock = threading.Lock()

    def set_window(self, window):
        """Attach the pywebview window after it has been created."""
        self.window = window

    def _poll_controller_state(self):
        poll_state = getattr(self.controller, "poll_runtime_state", None)
        if callable(poll_state):
            poll_state()

    def _worker_state(self):
        get_state = getattr(self.worker, "get_state", None)
        if callable(get_state):
            return get_state()
        return SimpleNamespace(
            running=self.worker.running,
            is_busy=self.worker.is_busy(),
            is_stopping=self.worker.is_stopping(),
            current_status=self.worker.current_status,
            status_text=self.worker.status_text,
            ra_connected=self.worker.ra_connected,
            ra_status_text=self.worker.ra_status_text,
            ra_permissions=getattr(self.worker, "ra_permissions", None),
            ra_role_label=getattr(self.worker, "ra_role_label", ""),
            ra_role_tier=getattr(self.worker, "ra_role_tier", ""),
        )

    def _state_payload(self):
        worker_state = self._worker_state()
        worker_payload = _dataclass_to_dict(worker_state)
        if not worker_payload.get("ra_connected"):
            ra_status_text = str(worker_payload.get("ra_status_text") or "")
            if ra_status_text.startswith("Connected "):
                worker_payload["ra_status_text"] = "Not connected to RetroAchievements"
        worker_payload["status_text"] = truncate_status_text(
            worker_payload.get("status_text", "")
        )
        worker_payload["ra_status_text"] = truncate_status_text(
            worker_payload.get("ra_status_text", "")
        )
        update_status = _dataclass_to_dict(self.controller.get_update_status())
        role_tier = worker_payload.get("ra_role_tier", "")
        return {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "config": _public_config(getattr(self.controller, "config", self.cfg)),
            "worker": worker_payload,
            "update_status": update_status,
            "role_style": role_badge_style(role_tier),
            "is_connecting": self._is_connecting,
            "is_installing_update": self._is_installing_update,
        }

    def load_config(self):
        """Load the editable form config, including the API key field."""
        with self._lock:
            self.cfg = dict(self.controller.load_config())
            return {
                "config": dict(self.cfg),
                "state": self._state_payload(),
            }

    def get_state(self):
        """Return a sanitized runtime snapshot for polling."""
        with self._lock:
            self._poll_controller_state()
            return self._state_payload()

    def _visible_config(self, payload):
        base = dict(self.cfg or self.controller.load_config())
        visible = dict(payload or {})
        merged = {
            **base,
            "username": str(visible.get("username", "")).strip(),
            "apikey": str(visible.get("apikey", "")).strip(),
            "show_profile_button": bool(visible.get("show_profile_button", False)),
            "show_gamepage_button": bool(visible.get("show_gamepage_button", False)),
            "show_achievement_progress": bool(
                visible.get("show_achievement_progress", False)
            ),
            "dev_mode": bool(visible.get("dev_mode", False)),
            "interval": visible.get("interval", base.get("interval", 5)),
            "timeout": visible.get("timeout", base.get("timeout", 130)),
        }
        return normalize_config(merged)

    def connect(self, payload):
        """Persist visible settings and start monitoring."""
        with self._lock:
            config = self._visible_config(payload)
            if not config["username"] or not config["apikey"]:
                return {
                    "success": False,
                    "error_title": "Missing Info",
                    "error_message": "Please enter your RA Username and Web API Key.",
                    "state": self._state_payload(),
                }
            self._is_connecting = True
        try:
            result = self.controller.connect(config)
        finally:
            with self._lock:
                self._is_connecting = False

        with self._lock:
            if result.config is not None:
                self.cfg = dict(result.config)
            payload = _dataclass_to_dict(result)
            payload["state"] = self._state_payload()
            return payload

    def disconnect(self):
        """Stop active monitoring."""
        success = self.controller.disconnect()
        with self._lock:
            return {"success": bool(success), "state": self._state_payload()}

    def install_update(self):
        """Install a staged update, then request app shutdown on success."""
        with self._lock:
            self._is_installing_update = True
        try:
            result = self.controller.install_update()
        finally:
            with self._lock:
                self._is_installing_update = False

        payload = _dataclass_to_dict(result)
        if payload.get("success"):
            self.exit_app()
        else:
            payload["state"] = self.get_state()
        return payload

    def open_url(self, target):
        """Open one of the footer links in the system browser."""
        urls = {
            "api_key": RA_SETTINGS_URL,
            "retroachievements": "https://retroachievements.org",
            "github": "https://github.com/denzi-gh/CheevoPresence",
            "kofi": "https://ko-fi.com/denzi",
        }
        url = urls.get(target)
        if not url:
            return {"success": False}
        webbrowser.open(url)
        return {"success": True}

    def open_logs(self):
        """Open the runtime log folder in the OS file manager."""
        platform = get_platform_services()
        log_dir = get_log_dir(platform)
        os.makedirs(log_dir, exist_ok=True)
        success = platform.open_path(log_dir)
        log_event(
            logger,
            AREA_SETTINGS,
            "open_log_folder",
            success=success,
            path=log_dir,
        )
        return {"success": bool(success), "path": log_dir}

    def dispatch(self, method, params=None):
        """Dispatch an HTTP API method from the web settings page."""
        params = params or {}
        if method == "load_config":
            return self.load_config()
        if method == "get_state":
            return self.get_state()
        if method == "connect":
            return self.connect(params.get("payload") or {})
        if method == "disconnect":
            return self.disconnect()
        if method == "install_update":
            return self.install_update()
        if method == "open_url":
            return self.open_url(params.get("target"))
        if method == "open_logs":
            return self.open_logs()
        if method == "exit_app":
            return self.exit_app()
        raise ValueError(f"Unknown web settings method: {method}")

    def minimize_window(self):
        """Minimize the webview window."""
        if self.window is not None:
            self.window.minimize()
        return {"success": True}

    def close_window(self):
        """Close only the settings window."""
        self._notify_closed()
        if self.window is not None:
            self.window.destroy()
        return {"success": True}

    def exit_app(self):
        """Close settings and delegate full app shutdown to the host."""
        self._notify_closed()
        if self.window is not None:
            self.window.destroy()
        if self.on_quit:
            threading.Thread(target=self.on_quit, daemon=True).start()
        return {"success": True}

    def on_window_closed(self, *_args):
        """Handle native window close events."""
        self._notify_closed()

    def _notify_closed(self):
        if self._closed:
            return
        self._closed = True
        if self.on_close:
            self.on_close()


class WebSettingsWindow:
    """Render the HTML settings window and block until it closes."""

    def __init__(self, controller, on_close=None, on_quit=None, on_ready=None):
        self.api = WebSettingsAPI(controller, on_close=on_close, on_quit=on_quit)
        self.on_ready = on_ready
        self._httpd = None
        self._http_thread = None
        self._run()

    def _start_server(self):
        token = os.urandom(16).hex()
        page = _settings_html().replace(
            "__CHEEVO_API_TOKEN__",
            token,
        )
        api = self.api

        class SettingsHandler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def _send(self, status, body, content_type="application/json"):
                if isinstance(body, str):
                    payload = body.encode("utf-8")
                else:
                    payload = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path not in {"/", "/settings"}:
                    self._send(404, {"ok": False, "error": "Not found."})
                    return
                self._send(200, page, "text/html; charset=utf-8")

            def do_POST(self):
                parsed = urlparse(self.path)
                if not parsed.path.startswith("/api/"):
                    self._send(404, {"ok": False, "error": "Not found."})
                    return
                if self.headers.get("X-Cheevo-Token") != token:
                    self._send(403, {"ok": False, "error": "Invalid settings token."})
                    return
                try:
                    size = int(self.headers.get("Content-Length") or "0")
                    raw = self.rfile.read(min(size, 1024 * 1024))
                    params = json.loads(raw.decode("utf-8") or "{}") if raw else {}
                    method = parsed.path.rsplit("/", 1)[-1]
                    self._send(200, {"ok": True, "result": api.dispatch(method, params)})
                except Exception as exc:
                    self._send(500, {"ok": False, "error": str(exc) or "Request failed."})

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), SettingsHandler)
        self._http_thread = threading.Thread(
            target=self._httpd.serve_forever,
            daemon=True,
        )
        self._http_thread.start()
        host, port = self._httpd.server_address
        return f"http://{host}:{port}/settings"

    def _stop_server(self):
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None

    def _run(self):
        try:
            import webview
        except ImportError as exc:
            raise RuntimeError(
                "pywebview is not installed. Install the platform requirements and try again."
            ) from exc

        url = self._start_server()
        window = webview.create_window(
            APP_NAME,
            url=url,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            min_size=(WINDOW_WIDTH, WINDOW_HEIGHT),
            resizable=False,
            frameless=False,
            background_color="#15191f",
        )
        self.api.set_window(window)
        try:
            window.events.closed += self.api.on_window_closed
        except Exception:
            pass
        if self.on_ready:
            self.on_ready(self)
        try:
            webview.start(debug=False)
        finally:
            self._stop_server()


__all__ = [
    "WebSettingsAPI",
    "WebSettingsWindow",
    "role_badge_style",
]
