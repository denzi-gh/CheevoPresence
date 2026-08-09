"""macOS-specific adapters for config, launch agents, keychain, and updates."""

from __future__ import annotations

import logging
import os
import platform
import plistlib
import shlex
import socket
import subprocess
import sys
import tempfile
import shutil
import threading
from pathlib import Path

from desktop.core.constants import APP_NAME
from desktop.platform.generic import GenericPlatformServices
from desktop.platform.macos_keychain import (
    build_keychain_token,
    parse_keychain_token,
    protect_api_key,
    unprotect_api_key,
)
from desktop.runtime.log_events import AREA_AUTOSTART, log_event

try:
    import fcntl
except ImportError:  # pragma: no cover - only relevant on non-POSIX platforms
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

LAUNCH_AGENT_ID = "org.denzi.cheevopresence"
LAUNCH_AGENT_FILE = f"{LAUNCH_AGENT_ID}.plist"
#Release Asset name template for macOS builds (for arm64 and x86_64)
UPDATE_ASSET_NAME_TEMPLATE = "CheevoPresence-macos-{machine}.zip"
_OTHER_ARCH_MARKERS = {
    "arm64": ("x86_64", "amd64", "intel"),
    "x86_64": ("arm64", "aarch64"),
}
EXIT_SOCKET_NAME = "exit.sock"

_single_instance_handle = None
_exit_listener_socket = None
_exit_listener_thread = None
_exit_listener_stop_event = None


def get_exe_path():
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.abspath(sys.argv[0])


def get_app_support_dir(app_name=APP_NAME):
    return os.path.join(os.path.expanduser("~/Library/Application Support"), app_name)


def get_cache_dir(app_name=APP_NAME):
    return os.path.join(os.path.expanduser("~/Library/Caches"), app_name)


def get_launch_agent_path():
    return os.path.join(os.path.expanduser("~/Library/LaunchAgents"), LAUNCH_AGENT_FILE)


def get_exit_socket_path():
    return os.path.join(get_cache_dir(), EXIT_SOCKET_NAME)


def _run_launchctl(args):
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
    )


def _launchctl_job_is_loaded():
    try:
        result = _run_launchctl(["launchctl", "print", f"gui/{os.getuid()}/{LAUNCH_AGENT_ID}"])
    except OSError:
        return False
    return result.returncode == 0


def _launchctl_reload(plist_path):
    user_id = str(os.getuid())
    for args in (
        ["launchctl", "bootout", f"gui/{user_id}", plist_path],
        ["launchctl", "bootstrap", f"gui/{user_id}", plist_path],
    ):
        try:
            result = _run_launchctl(args)
        except OSError:
            return "Could not access launchctl."
        if args[1] == "bootstrap" and result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            return message or "Could not bootstrap the macOS launch agent."
    if not _launchctl_job_is_loaded():
        return "The macOS launch agent did not report as loaded."
    return None


def _find_app_bundle(path):
    if not path:
        return None
    current = Path(path).resolve()
    for parent in (current, *current.parents):
        if parent.suffix == ".app":
            return str(parent)
    return None


def _is_bundle_executable(path):
    bundle_path = _find_app_bundle(path)
    if not bundle_path:
        return False
    expected = Path(bundle_path) / "Contents" / "MacOS"
    return expected in Path(path).resolve().parents


def _has_stable_install_path(bundle_path=None):
    bundle_path = bundle_path or _find_app_bundle(get_exe_path())
    if not bundle_path:
        return False
    resolved_bundle_path = str(Path(bundle_path).resolve())
    if "/AppTranslocation/" in resolved_bundle_path:
        return False
    bundle_parent = Path(bundle_path).parent
    if not bundle_parent.exists():
        return False
    return os.access(bundle_parent, os.W_OK)


def _build_launch_agent_payload(program_arguments):
    return {
        "Label": LAUNCH_AGENT_ID,
        "ProgramArguments": list(program_arguments),
        "RunAtLoad": True,
        "ProcessType": "Interactive",
    }


def _get_launch_command():
    exe_path = get_exe_path()
    bundle_path = _find_app_bundle(exe_path)
    if getattr(sys, "frozen", False) and bundle_path:
        return ["/usr/bin/open", bundle_path, "--args", "--tray"]
    if exe_path.endswith(".py"):
        return [sys.executable, exe_path, "--tray"]
    return [exe_path, "--tray"]


def _write_launch_agent(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="cheevopresence-launchagent-", suffix=".plist")
    try:
        with os.fdopen(fd, "wb") as handle:
            plistlib.dump(payload, handle, sort_keys=False)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _find_staged_app(root_dir, app_name=APP_NAME):
    direct = os.path.join(root_dir, f"{app_name}.app")
    if os.path.isdir(direct):
        return direct
    for current_root, dirnames, _filenames in os.walk(root_dir):
        for dirname in dirnames:
            if dirname == f"{app_name}.app":
                return os.path.join(current_root, dirname)
    return None


def _quote_args(values):
    if not values:
        return ""
    return " ".join(shlex.quote(str(value)) for value in values)


def _build_update_helper_script(target_app, staged_app, relaunch_args, parent_pid, cleanup_dir):
    args_suffix = _quote_args(relaunch_args)
    relaunch_line = f"/usr/bin/open {shlex.quote(target_app)}"
    if args_suffix:
        relaunch_line += f" --args {args_suffix}"
    return f"""#!/bin/bash
set -euo pipefail

TARGET_APP={shlex.quote(target_app)}
STAGED_APP={shlex.quote(staged_app)}
REPLACEMENT_APP="${{TARGET_APP}}.replacement"
BACKUP_APP="${{TARGET_APP}}.previous"
PARENT_PID={int(parent_pid)}
CLEANUP_DIR={shlex.quote(cleanup_dir)}
HELPER_LOG="${{CLEANUP_DIR}}/install_update.log"
completed=0

log() {{
  /bin/mkdir -p "$CLEANUP_DIR"
  /bin/printf '%s\\n' "$1" >> "$HELPER_LOG"
}}

cleanup() {{
  status=$?
  if [ "$completed" -ne 1 ]; then
    log "Update failed with status $status"
    /bin/rm -rf "$REPLACEMENT_APP"
    if [ -d "$BACKUP_APP" ]; then
      /bin/rm -rf "$TARGET_APP"
      /bin/mv "$BACKUP_APP" "$TARGET_APP"
      log "Restored previous app bundle."
    fi
  fi
  if [ "$completed" -eq 1 ]; then
    (
      /bin/sleep 2
      /bin/rm -rf "$CLEANUP_DIR"
    ) >/dev/null 2>&1 &
  fi
  exit "$status"
}}

trap cleanup EXIT

while /bin/kill -0 "$PARENT_PID" >/dev/null 2>&1; do
  /bin/sleep 1
done

if [ ! -d "$STAGED_APP" ]; then
  log "Staged app bundle is missing."
  exit 1
fi

TARGET_PARENT="$(/usr/bin/dirname "$TARGET_APP")"
if [ ! -w "$TARGET_PARENT" ]; then
  log "Target app directory is not writable: $TARGET_PARENT"
  exit 1
fi

/bin/rm -rf "$REPLACEMENT_APP" "$BACKUP_APP"
/usr/bin/ditto "$STAGED_APP" "$REPLACEMENT_APP"

if [ -d "$TARGET_APP" ]; then
  /bin/mv "$TARGET_APP" "$BACKUP_APP"
fi

/bin/mv "$REPLACEMENT_APP" "$TARGET_APP"
/bin/rm -rf "$BACKUP_APP"
log "Updated app bundle successfully."
{relaunch_line}
completed=1
"""


def _unpack_update_archive(archive_path, parent_dir=None):
    staging_dir = tempfile.mkdtemp(prefix="CheevoPresence-macos-update-", dir=parent_dir)
    extracted_dir = os.path.join(staging_dir, "extracted")
    os.makedirs(extracted_dir, exist_ok=True)
    subprocess.run(
        ["ditto", "-x", "-k", archive_path, extracted_dir],
        check=True,
        capture_output=True,
        text=True,
    )
    staged_app = _find_staged_app(extracted_dir)
    if not staged_app:
        raise OSError("The downloaded update did not contain a CheevoPresence.app bundle.")
    return staging_dir, staged_app


def acquire_single_instance():
    global _single_instance_handle

    if sys.platform != "darwin":
        return True

    if fcntl is None:
        return True

    try:
        lock_dir = get_cache_dir()
        os.makedirs(lock_dir, exist_ok=True)
        handle = open(os.path.join(lock_dir, "instance.lock"), "w", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.write(str(os.getpid()))
        handle.flush()
        _single_instance_handle = handle
        return True
    except OSError:
        return False


def notify_already_running():
    message = f"{APP_NAME} is already running in the menu bar."
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display alert "{APP_NAME}" message "{message}" as informational',
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        pass


def request_running_app_exit():
    if sys.platform != "darwin":
        return False

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

    if sys.platform != "darwin" or not callable(callback):
        return None
    if _exit_listener_thread is not None and _exit_listener_thread.is_alive():
        return _exit_listener_thread

    socket_path = get_exit_socket_path()
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


def set_autostart(enable):
    plist_path = get_launch_agent_path()
    try:
        if enable:
            if not _has_stable_install_path(_find_app_bundle(get_exe_path())):
                log_event(
                    logger,
                    AREA_AUTOSTART,
                    "set_failed",
                    level=logging.WARNING,
                    enabled=True,
                    path=plist_path,
                    reason="not_stable_install_path",
                )
                return "Launch at login is only available from a stable writable app install location."
            payload = _build_launch_agent_payload(_get_launch_command())
            _write_launch_agent(plist_path, payload)
            error = _launchctl_reload(plist_path)
            if error:
                try:
                    os.remove(plist_path)
                except OSError:
                    pass
                log_event(
                    logger,
                    AREA_AUTOSTART,
                    "set_failed",
                    level=logging.WARNING,
                    enabled=True,
                    path=plist_path,
                    reason="launchctl_reload_failed",
                )
                return error
        else:
            try:
                _run_launchctl(["launchctl", "bootout", f"gui/{os.getuid()}", plist_path])
            except OSError:
                pass
            if os.path.exists(plist_path):
                os.remove(plist_path)
        log_event(
            logger,
            AREA_AUTOSTART,
            "set",
            enabled=bool(enable),
            success=True,
            path=plist_path,
        )
        return None
    except OSError as exc:
        log_event(
            logger,
            AREA_AUTOSTART,
            "set_failed",
            level=logging.WARNING,
            enabled=bool(enable),
            path=plist_path,
            error_type=exc.__class__.__name__,
        )
        return "Could not update the macOS launch-at-login setting."


def is_autostart_enabled():
    enabled = _launchctl_job_is_loaded()
    # Polled every second by the settings UI, so keep this off the INFO log.
    log_event(logger, AREA_AUTOSTART, "read", level=logging.DEBUG, enabled=enabled)
    return enabled


def supports_self_update():
    exe_path = get_exe_path()
    return (
        sys.platform == "darwin"
        and getattr(sys, "frozen", False)
        and _is_bundle_executable(exe_path)
        and _has_stable_install_path(_find_app_bundle(exe_path))
    )


def select_update_asset(assets, machine=None):
    machine = (machine or platform.machine()).lower()
    exact_name = UPDATE_ASSET_NAME_TEMPLATE.format(machine=machine).lower()
    other_arch_markers = _OTHER_ARCH_MARKERS.get(machine, ())
    preferred = None
    for asset in assets or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").strip()
        if not name:
            continue
        lowered = name.lower()
        if lowered == exact_name:
            return asset
        if (
            preferred is None
            and lowered.endswith(".zip")
            and "mac" in lowered
            and not any(marker in lowered for marker in other_arch_markers)
        ):
            preferred = asset
    return preferred


def stage_update_install(download_path, relaunch_args, source_pid):
    if not supports_self_update():
        return "Automatic updates only work in the packaged macOS .app build installed in a writable location."

    try:
        target_app = _find_app_bundle(get_exe_path())
        if not target_app:
            return "Could not resolve the installed app bundle for update."
        download_dir = os.path.dirname(download_path)
        staging_dir, staged_app = _unpack_update_archive(download_path, parent_dir=download_dir)
        helper_path = os.path.join(staging_dir, "install_update.sh")
        helper_script = _build_update_helper_script(
            target_app=target_app,
            staged_app=staged_app,
            relaunch_args=relaunch_args,
            parent_pid=source_pid,
            cleanup_dir=download_dir,
        )
        with open(helper_path, "w", encoding="utf-8") as handle:
            handle.write(helper_script)
        os.chmod(helper_path, 0o755)
        subprocess.Popen(
            ["/bin/bash", helper_path],
            cwd=staging_dir,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return None
    except subprocess.CalledProcessError:
        return "Could not unpack the downloaded macOS update."
    except OSError as exc:
        return str(exc) or "Could not prepare the macOS update installer."


class MacOSPlatformServices(GenericPlatformServices):

    startup_toggle_label = "Launch on macOS login"
    settings_menu_default = True

    def get_config_dir(self, app_name, runtime_root_dir):
        return get_app_support_dir(app_name)

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
        return select_update_asset(assets)

    def stage_update_install(self, download_path, relaunch_args, source_pid):
        return stage_update_install(download_path, relaunch_args, source_pid)

    def handle_special_args(self, argv):
        return False
