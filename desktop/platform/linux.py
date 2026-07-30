"""Linux-specific adapters for XDG paths, startup, local config, and IPC."""

from __future__ import annotations

import logging
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import webbrowser

from desktop.core.constants import APP_NAME
from desktop.platform.generic import GenericPlatformServices
from desktop.platform.linux_secrets import protect_api_key, unprotect_api_key
from desktop.runtime.log_events import AREA_AUTOSTART, log_event

try:
    import fcntl
except ImportError:  # pragma: no cover - only relevant on non-POSIX platforms
    fcntl = None

AUTOSTART_FILE_NAME = "CheevoPresence.desktop"
EXIT_SOCKET_NAME = "exit.sock"
_EXEC_SAFE_RE = re.compile(r"^[A-Za-z0-9_/:=@%+.,-]+$")
JSC_GC_SIGNAL = getattr(signal, "SIGPWR", None)

_single_instance_handle = None
_exit_listener_socket = None
_exit_listener_thread = None
_exit_listener_stop_event = None
logger = logging.getLogger(__name__)


def _absolute_xdg_home(env_name, fallback):
    value = os.getenv(env_name)
    if value:
        expanded = os.path.expanduser(value)
        if os.path.isabs(expanded):
            return os.path.abspath(expanded)
    return os.path.abspath(os.path.expanduser(fallback))


def get_config_home():
    return _absolute_xdg_home("XDG_CONFIG_HOME", "~/.config")


def get_state_home():
    return _absolute_xdg_home("XDG_STATE_HOME", "~/.local/state")


def get_cache_home():
    return _absolute_xdg_home("XDG_CACHE_HOME", "~/.cache")


def get_config_dir(app_name=APP_NAME):
    return os.path.join(get_config_home(), app_name)


def get_log_dir(app_name=APP_NAME):
    return os.path.join(get_state_home(), app_name, "logs")


def get_runtime_dir(app_name=APP_NAME):
    runtime_home = os.getenv("XDG_RUNTIME_DIR")
    if runtime_home:
        runtime_home = os.path.expanduser(runtime_home)
        if os.path.isabs(runtime_home):
            return os.path.join(os.path.abspath(runtime_home), app_name)
    return os.path.join(get_cache_home(), app_name)


def _ensure_private_dir(path):
    os.makedirs(path, mode=0o700, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def get_exit_socket_path():
    return os.path.join(get_runtime_dir(), EXIT_SOCKET_NAME)


def get_lock_path():
    return os.path.join(get_runtime_dir(), "instance.lock")


def get_autostart_path():
    return os.path.join(get_config_home(), "autostart", AUTOSTART_FILE_NAME)


def host_process_env():
    env = os.environ.copy()
    if not getattr(sys, "frozen", False):
        return env
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD"):
        original = env.pop(f"{key}_ORIG", None)
        if original:
            env[key] = original
        else:
            env.pop(key, None)
    return env


def get_exe_path():
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.abspath(sys.argv[0])


def _get_launch_command():
    exe_path = get_exe_path()
    if getattr(sys, "frozen", False):
        return [exe_path, "--tray"]
    if exe_path.endswith(".py"):
        return [sys.executable, exe_path, "--tray"]
    return [exe_path, "--tray"]


def _quote_desktop_exec_arg(value):
    text = str(value).replace("%", "%%")
    if text and _EXEC_SAFE_RE.fullmatch(text):
        return text
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    return f'"{escaped}"'


def _format_exec_line(args):
    return " ".join(_quote_desktop_exec_arg(arg) for arg in args)


def _build_autostart_entry(command):
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Version=1.0",
            f"Name={APP_NAME}",
            "Comment=Mirror RetroAchievements activity to Discord Rich Presence",
            f"Exec={_format_exec_line(command)}",
            f"Icon={APP_NAME}",
            "Terminal=false",
            "Categories=Utility;",
            "X-GNOME-Autostart-enabled=true",
            "",
        ]
    )


def acquire_single_instance():
    global _single_instance_handle

    if fcntl is None:
        return True
    if _single_instance_handle is not None:
        return True

    try:
        lock_path = get_lock_path()
        _ensure_private_dir(os.path.dirname(lock_path))
        handle = open(lock_path, "w", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.write(str(os.getpid()))
        handle.flush()
        _single_instance_handle = handle
        return True
    except OSError:
        try:
            handle.close()
        except Exception:
            pass
        return False


def notify_already_running():
    message = f"{APP_NAME} is already running in the system tray."
    try:
        subprocess.run(
            ["notify-send", APP_NAME, message],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        pass


def request_running_app_exit():
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(2)
            conn.connect(get_exit_socket_path())
            conn.sendall(b"exit\n")
        return True
    except OSError:
        return False


def start_exit_listener(callback):
    global _exit_listener_socket, _exit_listener_thread, _exit_listener_stop_event

    if not callable(callback):
        return None
    if _exit_listener_thread is not None and _exit_listener_thread.is_alive():
        return _exit_listener_thread

    socket_path = get_exit_socket_path()
    listener = None
    try:
        _ensure_private_dir(os.path.dirname(socket_path))
        if os.path.exists(socket_path):
            os.remove(socket_path)

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(socket_path)
        os.chmod(socket_path, 0o600)
        listener.listen()
        listener.settimeout(0.5)
    except OSError:
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        return None

    stop_event = threading.Event()
    _exit_listener_socket = listener
    _exit_listener_stop_event = stop_event

    def listen_for_exit():
        try:
            while not stop_event.is_set():
                try:
                    conn, _addr = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    conn.recv(64)
                except OSError:
                    pass
                finally:
                    try:
                        conn.close()
                    except OSError:
                        pass
                callback()
                break
        finally:
            try:
                listener.close()
            except OSError:
                pass
            try:
                if os.path.exists(socket_path):
                    os.remove(socket_path)
            except OSError:
                pass

    _exit_listener_thread = threading.Thread(target=listen_for_exit, daemon=True)
    _exit_listener_thread.start()
    return _exit_listener_thread


def set_autostart(enable):
    autostart_path = get_autostart_path()
    try:
        if enable:
            os.makedirs(os.path.dirname(autostart_path), exist_ok=True)
            payload = _build_autostart_entry(_get_launch_command())
            fd, tmp_path = tempfile.mkstemp(
                prefix=".CheevoPresence-",
                suffix=".desktop.tmp",
                dir=os.path.dirname(autostart_path),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                os.replace(tmp_path, autostart_path)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        else:
            try:
                os.remove(autostart_path)
            except FileNotFoundError:
                pass
        log_event(
            logger,
            AREA_AUTOSTART,
            "set",
            enabled=bool(enable),
            success=True,
            path=autostart_path,
        )
        return None
    except OSError as exc:
        log_event(
            logger,
            AREA_AUTOSTART,
            "set_failed",
            level=logging.WARNING,
            enabled=bool(enable),
            path=autostart_path,
            error_type=exc.__class__.__name__,
        )
        return "Could not update the Linux startup setting."


def is_autostart_enabled():
    autostart_path = get_autostart_path()
    enabled = os.path.exists(autostart_path)
    # Polled every second by the settings UI, so keep this off the INFO log.
    log_event(
        logger,
        AREA_AUTOSTART,
        "read",
        level=logging.DEBUG,
        enabled=enabled,
        path=autostart_path,
    )
    return enabled


def supports_self_update():
    return False


class LinuxPlatformServices(GenericPlatformServices):

    startup_toggle_label = "Launch on Linux login"
    settings_menu_default = True

    def get_config_dir(self, app_name, runtime_root_dir):
        return get_config_dir(app_name)

    def get_log_dir(self, app_name, runtime_root_dir, config_dir):
        return get_log_dir(app_name)

    def protect_api_key(self, value):
        return protect_api_key(value)

    def unprotect_api_key(self, value):
        return unprotect_api_key(value)

    def acquire_single_instance(self):
        return acquire_single_instance()

    def notify_already_running(self):
        return notify_already_running()

    def request_running_app_exit(self):
        return request_running_app_exit()

    def start_exit_listener(self, callback):
        return start_exit_listener(callback)

    def set_autostart(self, enable):
        return set_autostart(enable)

    def is_autostart_enabled(self):
        return is_autostart_enabled()

    def supports_self_update(self):
        return supports_self_update()

    def select_update_asset(self, assets):
        return None

    def stage_update_install(self, download_path, relaunch_args, source_pid):
        return "Automatic updates are not available for Linux builds yet."

    def child_process_env(self):
        return host_process_env()

    def prepare_native_webview_environment(self):
        if JSC_GC_SIGNAL is not None:
            # The settings-window presenter uses SIGUSR1. JavaScriptCore also
            # defaults to that signal, so assign its GC thread control a
            # different Linux signal before WebKit initializes.
            os.environ.setdefault("JSC_SIGNAL_FOR_GC", str(JSC_GC_SIGNAL))

    def open_external_url(self, url):
        return self.open_path(url) or super().open_external_url(url)
