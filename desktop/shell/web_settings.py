"""HTML/pywebview settings window for the desktop shell."""

from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import sys
import threading
import time
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from desktop.core.constants import APP_NAME, APP_VERSION, RA_SETTINGS_URL
from desktop.core.log_events import AREA_SETTINGS, log_event
from desktop.core.settings import normalize_config
from desktop.platform import get_platform_services
from desktop.runtime.logging_setup import get_log_level
from desktop.runtime.logging_setup import set_log_level as apply_log_level
from desktop.runtime.storage import (
    APP_ICON_PNG_FILE,
    get_config_dir,
    get_log_dir,
    get_log_file,
    get_resource_dir,
)
from desktop.shell.settings_presenter import truncate_status_text

if TYPE_CHECKING:
    from desktop.runtime.controller import SettingsController

logger = logging.getLogger(__name__)

WINDOW_WIDTH = 720
WINDOW_HEIGHT = 600
WEB_RA_DISCONNECTED_TEXT = "Not connected"
SETTINGS_UI_ENV = "CHEEVO_SETTINGS_UI"
# The page polls get_state once a second, so a longer gap means the browser tab
# is gone and the settings session can be torn down.
BROWSER_IDLE_TIMEOUT = 15.0

def token_matches(supplied, expected):
    """Constant-time comparison for the settings-server token."""
    if not isinstance(supplied, str) or not expected:
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


ROLE_BADGE_STYLES = {
    "junior_developer": {
        "accent": "#e0a93c",
        "fill": "rgba(217,159,43,.12)",
        "border": "rgba(217,159,43,.4)",
        "icon": "code",
    },
    "developer": {
        "accent": "#5cc081",
        "fill": "rgba(92,192,129,.12)",
        "border": "rgba(92,192,129,.45)",
        "icon": "code",
    },
    "code_reviewer": {
        "accent": "#b0a0f0",
        "fill": "rgba(156,134,234,.13)",
        "border": "rgba(156,134,234,.45)",
        "icon": "search",
    },
    "event_manager": {
        "accent": "#d98fe6",
        "fill": "rgba(217,143,230,.13)",
        "border": "rgba(217,143,230,.45)",
        "icon": "star",
    },
    "artist": {
        "accent": "#f28d4f",
        "fill": "rgba(242,141,79,.13)",
        "border": "rgba(242,141,79,.45)",
        "icon": "palette",
    },
    "play_tester": {
        "accent": "#f2d35c",
        "fill": "rgba(242,211,92,.13)",
        "border": "rgba(242,211,92,.45)",
        "icon": "controller",
    },
    "writer": {
        "accent": "#7dc5ff",
        "fill": "rgba(125,197,255,.13)",
        "border": "rgba(125,197,255,.45)",
        "icon": "pen",
    },
    "moderator": {
        "accent": "#6fcfe2",
        "fill": "rgba(86,184,206,.13)",
        "border": "rgba(86,184,206,.45)",
        "icon": "shield",
    },
    "admin": {
        "accent": "#e86666",
        "fill": "rgba(232,102,102,.13)",
        "border": "rgba(232,102,102,.45)",
    },
}
DEFAULT_ROLE_BADGE_STYLE = {
    key: value for key, value in ROLE_BADGE_STYLES["junior_developer"].items() if key != "icon"
}


def role_badge_style(tier):
    return ROLE_BADGE_STYLES.get(tier, DEFAULT_ROLE_BADGE_STYLE)


def open_external_url(url):
    return bool(get_platform_services().open_external_url(url))


def _asset_path(filename):
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
    with open(_asset_path(filename), "r", encoding="utf-8") as handle:
        return handle.read()


def _data_uri_for_file(path):
    if not os.path.exists(path):
        return ""
    content_type = "image/png" if path.lower().endswith(".png") else "image/x-icon"
    try:
        with open(path, "rb") as handle:
            encoded = base64.b64encode(handle.read()).decode("ascii")
    except OSError:
        return ""
    return f"data:{content_type};base64,{encoded}"


def _about_logo_data_uri():
    return _data_uri_for_file(APP_ICON_PNG_FILE)


def _settings_html():
    html = _asset_text("settings.html")
    html = html.replace(
        '<link rel="stylesheet" href="./settings.css">',
        "<style>\n" + _asset_text("settings.css") + "\n</style>",
    )
    html = html.replace(
        '<script src="./settings.js"></script>',
        "<script>\n" + _asset_text("settings.js") + "\n</script>",
    )
    html = html.replace("__CHEEVO_ABOUT_LOGO__", _about_logo_data_uri())
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


def _developer_settings_unlocked(worker_payload, config):
    if worker_payload.get("ra_connected"):
        return bool(worker_payload.get("ra_dev_mode", False))
    return bool((config or {}).get("dev_mode", False))


class WebSettingsAPI:

    def __init__(self, controller: SettingsController, on_close=None, on_quit=None):
        self.controller = controller
        self.worker = controller.worker
        self.platform = controller.platform
        self.on_close = on_close
        self.on_quit = on_quit
        self.window = None
        self.cfg: dict = {}
        self._closed = False
        self._is_connecting = False
        self._is_installing_update = False
        self._lock = threading.Lock()

    def set_window(self, window):
        self.window = window

    def _poll_controller_state(self):
        poll_state = getattr(self.controller, "poll_runtime_state", None)
        if callable(poll_state):
            poll_state()

    def _worker_state(self):
        return self.worker.get_state()

    def _state_payload(self):
        worker_payload = _dataclass_to_dict(self._worker_state())
        config = getattr(self.controller, "config", self.cfg)
        if not worker_payload.get("ra_connected"):
            worker_payload["ra_status_text"] = WEB_RA_DISCONNECTED_TEXT
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
            "config": _public_config(config),
            "worker": worker_payload,
            "update_status": update_status,
            "role_style": role_badge_style(role_tier),
            "developer_settings_unlocked": _developer_settings_unlocked(
                worker_payload,
                config,
            ),
            "is_connecting": self._is_connecting,
            "is_installing_update": self._is_installing_update,
        }

    def load_config(self):
        with self._lock:
            self.cfg = dict(self.controller.load_config())
            return {
                "config": dict(self.cfg),
                "state": self._state_payload(),
            }

    def get_state(self):
        with self._lock:
            self._poll_controller_state()
            return self._state_payload()

    def _visible_config(self, payload, developer_settings_editable=None):
        base = dict(self.cfg or self.controller.load_config())
        visible = dict(payload or {})
        if developer_settings_editable is None:
            developer_settings_editable = _developer_settings_unlocked(
                _dataclass_to_dict(self._worker_state()),
                base,
            )
        developer_titles = base.get("use_retroachievements_developer_titles", True)
        developer_sets_button = base.get("show_developer_sets_button", True)
        if developer_settings_editable:
            developer_titles = visible.get(
                "use_retroachievements_developer_titles",
                developer_titles,
            )
            developer_sets_button = visible.get(
                "show_developer_sets_button",
                developer_sets_button,
            )
        merged = {
            **base,
            "username": str(visible.get("username", base.get("username", ""))).strip(),
            "apikey": str(visible.get("apikey", base.get("apikey", ""))).strip(),
            "show_profile_button": bool(
                visible.get("show_profile_button", base.get("show_profile_button", False))
            ),
            "show_gamepage_button": bool(
                visible.get("show_gamepage_button", base.get("show_gamepage_button", False))
            ),
            "show_achievement_progress": bool(
                visible.get(
                    "show_achievement_progress",
                    base.get("show_achievement_progress", False),
                )
            ),
            "show_total_playtime": bool(
                visible.get(
                    "show_total_playtime",
                    base.get("show_total_playtime", True),
                )
            ),
            "dev_mode": bool(base.get("dev_mode", False)),
            "use_retroachievements_developer_titles": bool(developer_titles),
            "show_developer_sets_button": bool(developer_sets_button),
            "start_on_boot": bool(
                visible.get("start_on_boot", base.get("start_on_boot", False))
            ),
            "interval": visible.get("interval", base.get("interval", 5)),
            "timeout": visible.get("timeout", base.get("timeout", 130)),
        }
        return normalize_config(merged)

    def save_config(self, payload):
        with self._lock:
            state = self._state_payload()
            worker_payload = state.get("worker") or {}
            developer_settings_editable = (
                state["developer_settings_unlocked"]
                and not worker_payload.get("is_busy")
                and not self._is_connecting
            )
            config = self._visible_config(
                payload,
                developer_settings_editable=developer_settings_editable,
            )
            result = {}
            saver = getattr(self.controller, "save_config", None)
            if callable(saver):
                result = saver(config)
                if isinstance(result, dict) and result.get("config"):
                    config = dict(result["config"])
            self.cfg = dict(config)
            response = {"success": True, "state": self._state_payload()}
            if isinstance(result, dict):
                response.update(
                    {
                        key: value
                        for key, value in result.items()
                        if key not in {"config", "success"}
                    }
                )
                response["success"] = bool(result.get("success", True))
            return response

    def connect(self, payload):
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
        success = self.controller.disconnect()
        with self._lock:
            return {"success": bool(success), "state": self._state_payload()}

    def install_update(self):
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
        urls = {
            "api_key": RA_SETTINGS_URL,
            "retroachievements": "https://retroachievements.org",
            "github": "https://github.com/denzi-gh/CheevoPresence",
            "kofi": "https://ko-fi.com/denzi",
        }
        url = urls.get(target)
        if not url:
            return {"success": False}
        return {"success": open_external_url(url)}

    def open_mirror_url(self, url):
        parsed = urlparse(str(url or ""))
        if parsed.scheme != "https" or parsed.netloc != "retroachievements.org":
            return {"success": False}
        return {"success": open_external_url(parsed.geturl())}

    def open_logs(self):
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

    def tail_logs(self, lines=200):
        platform = get_platform_services()
        path = get_log_file(platform)
        try:
            limit = int(lines or 200)
        except (TypeError, ValueError):
            limit = 200
        limit = max(1, min(limit, 1000))
        out = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                out = handle.read().splitlines()[-limit:]
        except OSError:
            out = []
        level = logging.getLevelName(get_log_level())
        return {"lines": out, "path": get_log_dir(platform), "level": level}

    def set_log_level(self, level):
        name = str(level or "INFO").upper()
        value = getattr(logging, name, logging.INFO)
        apply_log_level(value)
        return {"success": True, "level": logging.getLevelName(value)}

    def copy_diagnostics(self):
        import platform as platform_module

        platform = get_platform_services()
        lines = [
            f"{APP_NAME} {APP_VERSION}",
            f"python={platform_module.python_version()}",
            (
                f"system={platform_module.system()} "
                f"release={platform_module.release()} "
                f"machine={platform_module.machine()}"
            ),
            f"config_dir={get_config_dir(platform)}",
            f"log_dir={get_log_dir(platform)}",
        ]
        return {"text": "\n".join(lines)}

    def dispatch(self, method, params=None):
        params = params or {}
        if method == "load_config":
            return self.load_config()
        if method == "get_state":
            return self.get_state()
        if method == "save_config":
            return self.save_config(params.get("payload") or {})
        if method == "connect":
            return self.connect(params.get("payload") or {})
        if method == "disconnect":
            return self.disconnect()
        if method == "install_update":
            return self.install_update()
        if method == "tail_logs":
            return self.tail_logs(params.get("lines") or 200)
        if method == "set_log_level":
            return self.set_log_level(params.get("level"))
        if method == "copy_diagnostics":
            return self.copy_diagnostics()
        if method == "open_url":
            return self.open_url(params.get("target"))
        if method == "open_mirror_url":
            return self.open_mirror_url(params.get("url"))
        if method == "open_logs":
            return self.open_logs()
        if method == "exit_app":
            return self.exit_app()
        raise ValueError(f"Unknown web settings method: {method}")

    def minimize_window(self):
        if self.window is not None:
            self.window.minimize()
        return {"success": True}

    def close_window(self):
        self._notify_closed()
        if self.window is not None:
            self.window.destroy()
        return {"success": True}

    def exit_app(self):
        self._notify_closed()
        if self.window is not None:
            self.window.destroy()
        if self.on_quit:
            threading.Thread(target=self.on_quit, daemon=True).start()
        return {"success": True}

    def on_window_closed(self, *_args):
        self._notify_closed()

    def _notify_closed(self):
        if self._closed:
            return
        self._closed = True
        if self.on_close:
            self.on_close()


def _macos_call_after(fn):
    from PyObjCTools import AppHelper

    AppHelper.callAfter(fn)


def _invoke_native_window_call(fn):
    if sys.platform == "darwin":
        try:
            _macos_call_after(fn)
        except Exception:
            logger.debug("main-thread dispatch unavailable", exc_info=True)
            return False
        return True
    fn()
    return True


class WebSettingsWindow:

    def __init__(self, controller, on_close=None, on_quit=None, on_ready=None):
        self.api = WebSettingsAPI(controller, on_close=self._handle_closed, on_quit=on_quit)
        self.on_ready = on_ready
        self._on_close = on_close
        self._closed_event = threading.Event()
        self._ready_notified = False
        self._last_request = time.monotonic()
        self._url = None
        self._httpd = None
        self._http_thread = None
        self._run()

    def present(self):
        window = self.api.window
        if window is not None:
            shown = getattr(getattr(window, "events", None), "shown", None)
            if shown is None or shown.is_set():
                window.restore()
            return True
        if self._url:
            return open_external_url(self._url)
        return False

    def _focus_native_window(self, *_args):
        window = self.api.window
        if window is None:
            return False
        return _invoke_native_window_call(window.restore)

    def _notify_ready(self):
        if self._ready_notified or not self.on_ready:
            return
        self._ready_notified = True
        self.on_ready(self)

    def _handle_closed(self):
        self._closed_event.set()
        if self._on_close:
            self._on_close()

    def _touch(self):
        self._last_request = time.monotonic()

    def _start_server(self):
        token = os.urandom(16).hex()
        page = _settings_html().replace(
            "__CHEEVO_API_TOKEN__",
            token,
        )
        api = self.api
        session = self

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

            def _origin(self):
                address, port = self.server.server_address[:2]
                return f"http://{address}:{port}"

            # Validate Host to prevent DNS rebinding to the local server.
            def _is_trusted_request(self):
                address, port = self.server.server_address[:2]
                return (self.headers.get("Host") or "") == f"{address}:{port}"

            def do_GET(self):
                session._touch()
                parsed = urlparse(self.path)
                if not self._is_trusted_request() or parsed.path not in {"/", "/settings"}:
                    self._send(404, {"ok": False, "error": "Not found."})
                    return
                # Without this the settings token could be scraped straight out of
                # the HTML by any other page that guesses the port.
                if not token_matches(parse_qs(parsed.query).get("k", [""])[0], token):
                    self._send(404, {"ok": False, "error": "Not found."})
                    return
                self._send(200, page, "text/html; charset=utf-8")

            def do_POST(self):
                session._touch()
                parsed = urlparse(self.path)
                try:
                    size = int(self.headers.get("Content-Length") or "0")
                except ValueError:
                    size = 0
                raw = self.rfile.read(min(size, 1024 * 1024)) if size > 0 else b""
                if not self._is_trusted_request() or not parsed.path.startswith("/api/"):
                    self._send(404, {"ok": False, "error": "Not found."})
                    return
                origin = self.headers.get("Origin")
                if origin and origin != self._origin():
                    self._send(403, {"ok": False, "error": "Invalid settings origin."})
                    return
                if parsed.path == "/api/close_session":
                    if token_matches(parse_qs(parsed.query).get("k", [""])[0], token):
                        api.on_window_closed()
                    self._send(200, {"ok": True})
                    return
                if not token_matches(self.headers.get("X-Cheevo-Token"), token):
                    self._send(403, {"ok": False, "error": "Invalid settings token."})
                    return
                try:
                    params = json.loads(raw.decode("utf-8") or "{}") if raw else {}
                    method = parsed.path.rsplit("/", 1)[-1]
                    self._send(200, {"ok": True, "result": api.dispatch(method, params)})
                except Exception as exc:  # noqa: BLE001 HTTP boundary; any error becomes a 500 reply
                    self._send(500, {"ok": False, "error": str(exc) or "Request failed."})

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), SettingsHandler)
        self._http_thread = threading.Thread(
            target=self._httpd.serve_forever,
            daemon=True,
        )
        self._http_thread.start()
        host, port = self._httpd.server_address
        return f"http://{host}:{port}/settings?k={token}"

    def _stop_server(self):
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None

    def _native_window_allowed(self):
        mode = os.environ.get(SETTINGS_UI_ENV, "").strip().lower()
        if mode in {"browser", "native"}:
            return mode == "native"
        return bool(get_platform_services().settings_window_native)

    def _open_native_window(self, url, started):
        if not self._native_window_allowed():
            raise RuntimeError(
                f"Native settings window unavailable on this platform "
                f"(override with {SETTINGS_UI_ENV}=native)."
            )

        prepare_environment = getattr(
            get_platform_services(), "prepare_native_webview_environment", None
        )
        if prepare_environment:
            prepare_environment()

        import webview

        window = webview.create_window(
            APP_NAME,
            url=url,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            min_size=(WINDOW_WIDTH, WINDOW_HEIGHT),
            resizable=False,
            frameless=False,
            background_color="#16171b",
        )
        self.api.set_window(window)
        try:
            window.events.closed += self.api.on_window_closed
        except Exception:
            logger.debug("pywebview closed event unavailable", exc_info=True)
        try:
            window.events.shown += self._focus_native_window
        except Exception: 
            logger.debug("pywebview shown event unavailable", exc_info=True)
        self._notify_ready()
        webview.start(started.set, debug=False)

    def _run_in_browser(self, url):
        if not open_external_url(url):
            raise RuntimeError("No web browser is available to show the settings window.")
        log_event(logger, AREA_SETTINGS, "settings_opened_in_browser")
        self._notify_ready()
        while not self._closed_event.wait(1.0):
            if time.monotonic() - self._last_request > BROWSER_IDLE_TIMEOUT:
                log_event(logger, AREA_SETTINGS, "browser_session_idle")
                break

    def _run(self):
        started = threading.Event()
        url = self._url = self._start_server()
        try:
            try:
                self._open_native_window(url, started)
            except Exception as exc:
                if started.is_set():
                    raise
                log_event(
                    logger,
                    AREA_SETTINGS,
                    "native_webview_unavailable",
                    level=logging.WARNING,
                    error_type=exc.__class__.__name__,
                    error=str(exc),
                )
                self._run_in_browser(url)
        finally:
            self._stop_server()


__all__ = [
    "WebSettingsAPI",
    "WebSettingsWindow",
    "role_badge_style",
]
