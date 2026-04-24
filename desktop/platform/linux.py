"""Linux-specific adapters for config, secrets, autostart, tray, and updates."""

from __future__ import annotations

import base64
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from tkinter import messagebox

from desktop.core.constants import APP_NAME
from desktop.platform.generic import GenericPlatformServices

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import keyring
    _KEYRING_AVAILABLE = True
except ImportError:
    keyring = None
    _KEYRING_AVAILABLE = False

LAUNCH_DESKTOP_FILE = f"{APP_NAME}.desktop"
EXIT_SOCKET_NAME = "exit.sock"
INSTANCE_LOCK_NAME = "instance.lock"
KEYRING_SERVICE = "org.denzi.cheevopresence"
KEYRING_USERNAME = "retroachievements-api-key"
KEYRING_TOKEN_PREFIX = f"keyring://{KEYRING_SERVICE}/"
UPDATE_HELPER_SCRIPT_NAME = "apply_update.sh"

_single_instance_handle = None
_exit_listener_socket = None
_exit_listener_thread = None
_exit_listener_stop_event = None


def _get_xdg_config_dir():
    """Return the XDG config directory for the current user."""
    return os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))


def _get_xdg_cache_dir():
    """Return the XDG cache directory for the current user."""
    return os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))


def _get_app_config_dir(app_name=APP_NAME):
    """Return the app's config directory under XDG_CONFIG_HOME."""
    return os.path.join(_get_xdg_config_dir(), app_name)


def _get_app_cache_dir(app_name=APP_NAME):
    """Return the app's cache directory under XDG_CACHE_HOME."""
    return os.path.join(_get_xdg_cache_dir(), app_name)


def _get_autostart_dir():
    """Return the per-user autostart directory."""
    return os.path.join(_get_xdg_config_dir(), "autostart")


def _get_autostart_file_path():
    """Return the full path to the autostart .desktop file."""
    return os.path.join(_get_autostart_dir(), LAUNCH_DESKTOP_FILE)


def _get_exit_socket_path():
    """Return the local socket path used for external shutdown requests."""
    return os.path.join(_get_app_cache_dir(), EXIT_SOCKET_NAME)


def _get_instance_lock_path():
    """Return the file path used for the single-instance advisory lock."""
    return os.path.join(_get_app_cache_dir(), INSTANCE_LOCK_NAME)


def get_exe_path():
    """Return the active executable path for the packaged app or source run."""
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.abspath(sys.argv[0])


def _build_keyring_token():
    """Build the config token that points at the stored keyring item."""
    return f"{KEYRING_TOKEN_PREFIX}{KEYRING_USERNAME}"


def _parse_keyring_token(value):
    """Extract the keyring account from a stored config token."""
    if not isinstance(value, str) or not value.startswith(KEYRING_TOKEN_PREFIX):
        return None
    return value[len(KEYRING_TOKEN_PREFIX):].strip() or None


def _is_packaged_app():
    """Return whether the app is running as a packaged executable."""
    return getattr(sys, "frozen", False)


def protect_api_key(value):
    """Store the API key in the system keyring and return a reference token."""
    if not value:
        if _KEYRING_AVAILABLE:
            try:
                keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
            except Exception:
                pass
        return ""
    if _KEYRING_AVAILABLE:
        try:
            keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, value)
            return _build_keyring_token()
        except Exception:
            pass
    return GenericPlatformServices().protect_api_key(value)


def unprotect_api_key(value):
    """Resolve a stored keyring token back into the plaintext secret."""
    account = _parse_keyring_token(value)
    if account and _KEYRING_AVAILABLE:
        try:
            password = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
            if password is not None:
                return password
        except Exception:
            pass
    return GenericPlatformServices().unprotect_api_key(value)


def acquire_single_instance():
    """Acquire a non-blocking advisory file lock for the running app."""
    global _single_instance_handle

    if sys.platform != "linux":
        return True
    if fcntl is None:
        return True

    try:
        lock_dir = _get_app_cache_dir()
        os.makedirs(lock_dir, exist_ok=True)
        handle = open(_get_instance_lock_path(), "w", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.write(str(os.getpid()))
        handle.flush()
        _single_instance_handle = handle
        return True
    except OSError:
        return False


def notify_already_running():
    """Show a small info dialog when another instance is launched."""
    message = f"{APP_NAME} is already running in the system tray."
    try:
        messagebox.showinfo(APP_NAME, message)
    except Exception:
        pass


def request_running_app_exit():
    """Ask the running tray instance to shut itself down."""
    if sys.platform != "linux":
        return False

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(2)
            conn.connect(_get_exit_socket_path())
            conn.sendall(b"exit\n")
        return True
    except OSError:
        return False


def start_exit_listener(callback):
    """Listen on a local socket for --exit shutdown requests."""
    global _exit_listener_socket, _exit_listener_thread, _exit_listener_stop_event

    if sys.platform != "linux" or not callable(callback):
        return None
    if _exit_listener_thread is not None and _exit_listener_thread.is_alive():
        return _exit_listener_thread

    socket_path = _get_exit_socket_path()
    listener = None
    try:
        os.makedirs(os.path.dirname(socket_path), mode=0o700, exist_ok=True)
        try:
            os.chmod(os.path.dirname(socket_path), 0o700)
        except OSError:
            pass
        if os.path.exists(socket_path):
            os.remove(socket_path)

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(socket_path)
        os.chmod(socket_path, 0o600)
        listener.listen()
        listener.settimeout(0.5)
    except OSError:
        try:
            listener.close()
        except Exception:
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


def _build_autostart_desktop_content(exec_cmd):
    """Render the .desktop file content for autostart."""
    return f"""[Desktop Entry]
Name={APP_NAME}
Comment=Mirror your RetroAchievements activity to Discord
Exec={exec_cmd}
Icon={APP_NAME.lower()}
Type=Application
Terminal=false
Categories=Game;Network;
X-GNOME-Autostart-enabled=true
"""


def _get_launch_command():
    """Return the best launch command for autostart."""
    exe_path = get_exe_path()
    if exe_path.endswith(".py"):
        return f'"{sys.executable}" "{exe_path}" --tray'
    return f'"{exe_path}" --tray'


def set_autostart(enable):
    """Enable or disable autostart by writing/removing the .desktop file."""
    autostart_dir = _get_autostart_dir()
    desktop_file = _get_autostart_file_path()
    try:
        if enable:
            os.makedirs(autostart_dir, exist_ok=True)
            content = _build_autostart_desktop_content(_get_launch_command())
            fd, tmp_path = tempfile.mkstemp(dir=autostart_dir, suffix=".desktop.tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(content)
                os.replace(tmp_path, desktop_file)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        else:
            if os.path.exists(desktop_file):
                os.remove(desktop_file)
        return None
    except OSError:
        return "Could not update the autostart setting."


def is_autostart_enabled():
    """Return whether the autostart .desktop file exists."""
    return os.path.exists(_get_autostart_file_path())


def supports_self_update():
    """Return whether the current Linux runtime can replace itself automatically."""
    exe_path = get_exe_path()
    if sys.platform != "linux" or not _is_packaged_app():
        return False
    parent_dir = os.path.dirname(exe_path)
    return os.access(parent_dir, os.W_OK)


def select_update_asset(assets):
    """Pick the preferred Linux release asset from the GitHub asset list."""
    preferred = None
    for asset in assets or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").strip()
        if not name:
            continue
        lowered = name.lower()
        if "appimage" in lowered and lowered.endswith(".appimage"):
            return asset
        if lowered.endswith(".tar.gz") and ("linux" in lowered or "cheevopresence" in lowered):
            if preferred is None:
                preferred = asset
        elif lowered.endswith(".appimage") and preferred is None:
            preferred = asset
    return preferred


def _build_update_helper_script(target_path, download_path, relaunch_args, parent_pid, cleanup_dir):
    """Render the detached shell helper that replaces the current app."""
    args_str = " ".join(f'"{arg}"' for arg in (relaunch_args or []))
    relaunch_line = f'"{target_path}"'
    if args_str:
        relaunch_line += f" {args_str}"
    return f"""#!/bin/bash
set -euo pipefail

TARGET_PATH={shlex.quote(target_path)}
DOWNLOAD_PATH={shlex.quote(download_path)}
CLEANUP_DIR={shlex.quote(cleanup_dir)}
PARENT_PID={int(parent_pid)}
HELPER_LOG="$CLEANUP_DIR/install_update.log"
completed=0

log() {{
  mkdir -p "$CLEANUP_DIR"
  printf '%s %s\\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$HELPER_LOG"
}}

cleanup() {{
  status=$?
  if [ "$completed" -ne 1 ]; then
    log "Update failed with status $status"
  fi
  if [ "$completed" -eq 1 ]; then
    (
      sleep 2
      rm -rf "$CLEANUP_DIR"
    ) >/dev/null 2>&1 &
  fi
  exit "$status"
}}

trap cleanup EXIT

while kill -0 "$PARENT_PID" >/dev/null 2>&1; do
  sleep 1
done

log "Parent process exited."

if [ ! -e "$DOWNLOAD_PATH" ]; then
  log "Downloaded update is missing."
  exit 1
fi

TARGET_PARENT="$(dirname "$TARGET_PATH")"
if [ ! -w "$TARGET_PARENT" ]; then
  log "Target directory is not writable: $TARGET_PARENT"
  exit 1
fi

if [ -d "$DOWNLOAD_PATH" ]; then
  rm -rf "$TARGET_PATH"
  mv "$DOWNLOAD_PATH" "$TARGET_PATH"
else
  rm -f "$TARGET_PATH"
  mv "$DOWNLOAD_PATH" "$TARGET_PATH"
  if [ -x "$TARGET_PATH" ] || [ ! -x "$TARGET_PATH" ]; then
    chmod +x "$TARGET_PATH" 2>/dev/null || true
  fi
fi

log "Updated successfully."
{relaunch_line}
completed=1
"""


def stage_update_install(download_path, relaunch_args, source_pid):
    """Stage a detached helper to replace the current app after exit."""
    if not supports_self_update():
        return "Automatic updates only work in packaged Linux builds installed in a writable location."

    try:
        target_path = get_exe_path()
        download_dir = os.path.dirname(download_path)
        helper_path = os.path.join(download_dir, UPDATE_HELPER_SCRIPT_NAME)
        helper_script = _build_update_helper_script(
            target_path=target_path,
            download_path=download_path,
            relaunch_args=relaunch_args,
            parent_pid=source_pid,
            cleanup_dir=download_dir,
        )
        with open(helper_path, "w", encoding="utf-8") as handle:
            handle.write(helper_script)
        os.chmod(helper_path, 0o755)
        subprocess.Popen(
            ["/bin/bash", helper_path],
            cwd=download_dir,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return None
    except OSError as exc:
        return str(exc) or "Could not prepare the Linux update installer."


class LinuxPlatformServices(GenericPlatformServices):
    """Bundle the Linux-specific hooks needed by the desktop runtime."""

    startup_toggle_label = "Launch on system startup"
    settings_menu_default = True

    def get_config_dir(self, app_name, runtime_root_dir):
        """Store config under ~/.config following the XDG Base Directory spec."""
        return _get_app_config_dir(app_name)

    def protect_api_key(self, value):
        """Store the API key in the system keyring and return its config token."""
        return protect_api_key(value)

    def unprotect_api_key(self, value):
        """Resolve a stored keyring token back into the plaintext API key."""
        return unprotect_api_key(value)

    def acquire_single_instance(self):
        """Acquire the shared Linux single-instance file lock."""
        return acquire_single_instance()

    def notify_already_running(self):
        """Show the duplicate-launch notice."""
        return notify_already_running()

    def request_running_app_exit(self):
        """Ask the running tray instance to exit."""
        return request_running_app_exit()

    def start_exit_listener(self, callback):
        """Start listening for external shutdown requests."""
        return start_exit_listener(callback)

    def set_autostart(self, enable):
        """Write or remove the autostart .desktop file."""
        return set_autostart(enable)

    def is_autostart_enabled(self):
        """Return whether autostart is currently configured."""
        return is_autostart_enabled()

    def supports_self_update(self):
        """Report whether the current packaged app can self-update."""
        return supports_self_update()

    def select_update_asset(self, assets):
        """Pick the preferred .tar.gz or .AppImage release asset for Linux."""
        return select_update_asset(assets)

    def stage_update_install(self, download_path, relaunch_args, source_pid):
        """Stage a detached helper to replace the current executable."""
        return stage_update_install(download_path, relaunch_args, source_pid)

    def handle_special_args(self, argv):
        """Linux uses an external shell helper for updates, so there are no special args."""
        return False
