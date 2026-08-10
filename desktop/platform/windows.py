"""Windows-specific adapters for startup, secrets, and tray behavior."""

import base64
import ctypes
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from tkinter import messagebox

from desktop.core.constants import APP_NAME
from desktop.core.log_events import AREA_AUTOSTART, log_event
from desktop.platform.base import PlatformServices
from desktop.platform.windows_secrets import protect_api_key, unprotect_api_key

SINGLE_INSTANCE_MUTEX_NAME = f"Local\\{APP_NAME}Singleton"
EXIT_EVENT_NAME = f"Local\\{APP_NAME}Exit"
ERROR_ALREADY_EXISTS = 183
STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REG_NAME = "CheevoPresence"
UPDATE_HELPER_FLAG = "--apply-update"
UPDATE_TARGET_FLAG = "--update-target"
UPDATE_SOURCE_FLAG = "--update-source"
UPDATE_PARENT_PID_FLAG = "--update-parent-pid"
UPDATE_RELAUNCH_ARGS_FLAG = "--update-relaunch-args"

_single_instance_mutex = None
_exit_event_handle = None
_exit_listener_thread = None
logger = logging.getLogger(__name__)


def acquire_single_instance():
    global _single_instance_mutex

    if os.name != "nt":
        return True

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_wchar_p,
        ]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool
        mutex = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX_NAME)
        if not mutex:
            logger.warning("Windows single-instance mutex creation failed")
            return False

        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(mutex)
            logger.info("Windows single-instance mutex already exists")
            return False

        _single_instance_mutex = mutex
        logger.info("Windows single-instance mutex acquired")
        return True
    except Exception:
        logger.exception("Windows single-instance mutex acquisition failed")
        return False


def notify_already_running():
    message = f"{APP_NAME} is already running in the system tray."

    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x40)
            return
        except Exception:  # any native failure falls back to the tk box
            logger.debug("Native message box unavailable", exc_info=True)

    try:
        messagebox.showinfo(APP_NAME, message)
    except Exception:  # notification is best-effort (e.g. headless tk)
        logger.debug("tk message box unavailable", exc_info=True)


def request_running_app_exit():
    if os.name != "nt":
        return False

    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenEventW.restype = ctypes.c_void_p
        kernel32.SetEvent.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        event_modify_state = 0x0002
        event = kernel32.OpenEventW(event_modify_state, False, EXIT_EVENT_NAME)
        if not event:
            return False
        try:
            return bool(kernel32.SetEvent(event))
        finally:
            kernel32.CloseHandle(event)
    except (OSError, AttributeError):
        return False


def start_exit_listener(callback):
    global _exit_event_handle, _exit_listener_thread

    if os.name != "nt" or not callable(callback):
        return None
    if _exit_listener_thread is not None and _exit_listener_thread.is_alive():
        return _exit_listener_thread

    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateEventW.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        manual_reset = False
        initial_state = False
        event = kernel32.CreateEventW(None, manual_reset, initial_state, EXIT_EVENT_NAME)
        if not event:
            logger.warning("Windows exit listener event could not be created")
            return None
    except (OSError, AttributeError):
        logger.warning("Windows exit listener could not start", exc_info=True)
        return None

    _exit_event_handle = event

    def listen_for_exit():
        wait_object_0 = 0x00000000
        infinite = 0xFFFFFFFF
        try:
            result = kernel32.WaitForSingleObject(event, infinite)
            if result == wait_object_0:
                callback()
        except Exception:
            logger.exception("Windows exit listener failed")

    _exit_listener_thread = threading.Thread(target=listen_for_exit, daemon=True)
    _exit_listener_thread.start()
    return _exit_listener_thread


def get_exe_path():
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(sys.argv[0])


def _encode_relaunch_args(values):
    raw = json.dumps(list(values or []), separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_relaunch_args(value):
    if not value:
        return []
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
        decoded = json.loads(raw.decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    return [str(item) for item in decoded if item is not None]


def _append_update_log(log_path, message):
    try:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def _wait_for_process_exit(pid, timeout_seconds=120):
    if not pid or os.name != "nt":
        return
    kernel32 = ctypes.windll.kernel32
    synchronize = 0x00100000
    wait_object_0 = 0x00000000
    wait_timeout = 0x00000102
    handle = kernel32.OpenProcess(synchronize, False, int(pid))
    if handle:
        try:
            result = kernel32.WaitForSingleObject(handle, int(timeout_seconds * 1000))
            if result in (wait_object_0, wait_timeout):
                return
        finally:
            kernel32.CloseHandle(handle)
    for _ in range(int(timeout_seconds)):
        try:
            probe = kernel32.OpenProcess(synchronize, False, int(pid))
        except OSError:
            probe = None
        if not probe:
            return
        kernel32.CloseHandle(probe)
        time.sleep(1)


def _replace_file_with_retries(source_path, target_path, log_path, attempts=60):
    for attempt in range(1, attempts + 1):
        try:
            os.replace(source_path, target_path)
            _append_update_log(log_path, f"Replaced target on attempt {attempt}.")
            return True
        except OSError as exc:
            _append_update_log(log_path, f"Attempt {attempt} failed: {exc}")
            time.sleep(1)
    return False


def _spawn_cleanup(cleanup_paths):
    paths = [path for path in cleanup_paths if path and os.path.isdir(path)]
    if not paths:
        return
    quoted = " & ".join(f'rmdir /s /q "{path}"' for path in paths)
    subprocess.Popen(
        [
            "cmd.exe",
            "/c",
            f'ping 127.0.0.1 -n 4 >NUL & {quoted}',
        ],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _parse_update_helper_args(argv):
    options = {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == UPDATE_TARGET_FLAG and index + 1 < len(argv):
            options["target"] = argv[index + 1]
            index += 2
        elif token == UPDATE_SOURCE_FLAG and index + 1 < len(argv):
            options["source"] = argv[index + 1]
            index += 2
        elif token == UPDATE_PARENT_PID_FLAG and index + 1 < len(argv):
            options["parent_pid"] = argv[index + 1]
            index += 2
        elif token == UPDATE_RELAUNCH_ARGS_FLAG and index + 1 < len(argv):
            options["relaunch_args"] = argv[index + 1]
            index += 2
        else:
            index += 1
    return options


def handle_special_args(argv):
    if UPDATE_HELPER_FLAG not in argv:
        return False

    options = _parse_update_helper_args(argv)
    helper_dir = os.path.dirname(get_exe_path())
    log_path = os.path.join(helper_dir, "apply_update.log")
    target_path = options.get("target")
    source_path = options.get("source")
    relaunch_args = _decode_relaunch_args(options.get("relaunch_args"))
    cleanup_paths = [helper_dir]
    parent_pid = 0
    try:
        parent_pid = int(options.get("parent_pid") or 0)
    except (TypeError, ValueError):
        parent_pid = 0

    _append_update_log(log_path, "Helper started.")
    if not target_path or not source_path:
        _append_update_log(log_path, "Missing target or source path.")
        return True

    _wait_for_process_exit(parent_pid)
    _append_update_log(log_path, "Parent process exited.")

    replaced = _replace_file_with_retries(source_path, target_path, log_path)
    launch_path = target_path if replaced else source_path
    if replaced:
        cleanup_paths.append(os.path.dirname(source_path))

    try:
        _append_update_log(log_path, f"Launching {launch_path}")
        subprocess.Popen(
            [launch_path, *relaunch_args],
            cwd=os.path.dirname(target_path) or None,
        )
    except Exception as exc:  # noqa: BLE001 helper must finish the swap; failure is in the update log
        _append_update_log(log_path, f"Launch failed: {exc}")

    _spawn_cleanup(cleanup_paths)
    _append_update_log(log_path, "Helper finished.")
    return True


def supports_self_update():
    exe_path = get_exe_path()
    return os.name == "nt" and getattr(sys, "frozen", False) and exe_path.lower().endswith(".exe")


def select_update_asset(assets):
    preferred = None
    for asset in assets or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").strip()
        if not name:
            continue
        lowered = name.lower()
        if lowered == "cheevopresence.exe":
            return asset
        if lowered.endswith(".exe") and preferred is None:
            preferred = asset
    return preferred


def stage_update_install(download_path, relaunch_args, source_pid):
    if not supports_self_update():
        return "Automatic updates only work in the packaged Windows .exe build."

    target_path = get_exe_path()
    update_dir = tempfile.mkdtemp(prefix="CheevoPresence-update-")
    helper_path = os.path.join(update_dir, os.path.basename(target_path))
    shutil.copy2(target_path, helper_path)
    subprocess.Popen(
        [
            helper_path,
            UPDATE_HELPER_FLAG,
            UPDATE_TARGET_FLAG,
            target_path,
            UPDATE_SOURCE_FLAG,
            download_path,
            UPDATE_PARENT_PID_FLAG,
            str(source_pid),
            UPDATE_RELAUNCH_ARGS_FLAG,
            _encode_relaunch_args(relaunch_args),
        ],
        cwd=os.path.dirname(target_path) or None,
    )
    return None


def set_autostart(enable):
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE)
        try:
            if enable:
                exe = get_exe_path()
                if exe.endswith(".py"):
                    value = f'"{sys.executable}" "{exe}" --tray'
                else:
                    value = f'"{exe}" --tray'
                winreg.SetValueEx(key, STARTUP_REG_NAME, 0, winreg.REG_SZ, value)
            else:
                try:
                    winreg.DeleteValue(key, STARTUP_REG_NAME)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        log_event(
            logger,
            AREA_AUTOSTART,
            "set",
            enabled=bool(enable),
            success=True,
            path=f"HKCU\\{STARTUP_REG_KEY}\\{STARTUP_REG_NAME}",
        )
        return None
    except OSError as exc:
        log_event(
            logger,
            AREA_AUTOSTART,
            "set_failed",
            level=logging.WARNING,
            enabled=bool(enable),
            error_type=exc.__class__.__name__,
        )
        return "Could not update the Windows startup setting."


def is_autostart_enabled():
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, STARTUP_REG_NAME)
            enabled = True
        except FileNotFoundError:
            enabled = False
        finally:
            winreg.CloseKey(key)
    except OSError:
        enabled = False
    # Polled every second by the settings UI, so keep this off the INFO log.
    log_event(logger, AREA_AUTOSTART, "read", level=logging.DEBUG, enabled=enabled)
    return enabled


def get_tray_icon_class(pystray):
    if os.name != "nt":
        return pystray.Icon

    import pystray._win32 as pystray_win32

    class WindowsDoubleClickIcon(pystray_win32.Icon):
        WM_LBUTTONDBLCLK = 0x0203
        CS_DBLCLKS = 0x0008

        def _on_notify(self, wparam, lparam):
            if lparam == self.WM_LBUTTONDBLCLK:
                self()
            elif self._menu_handle and lparam == pystray_win32.win32.WM_RBUTTONUP:
                pystray_win32.win32.SetForegroundWindow(self._hwnd)

                point = pystray_win32.wintypes.POINT()
                pystray_win32.win32.GetCursorPos(ctypes.byref(point))

                hmenu, descriptors = self._menu_handle
                index = pystray_win32.win32.TrackPopupMenuEx(
                    hmenu,
                    pystray_win32.win32.TPM_RIGHTALIGN
                    | pystray_win32.win32.TPM_BOTTOMALIGN
                    | pystray_win32.win32.TPM_RETURNCMD,
                    point.x,
                    point.y,
                    self._menu_hwnd,
                    None,
                )
                if index > 0:
                    descriptors[index - 1](self)

        def _register_class(self):
            return pystray_win32.win32.RegisterClassEx(
                pystray_win32.win32.WNDCLASSEX(
                    cbSize=ctypes.sizeof(pystray_win32.win32.WNDCLASSEX),
                    style=self.CS_DBLCLKS,
                    lpfnWndProc=pystray_win32._dispatcher,
                    cbClsExtra=0,
                    cbWndExtra=0,
                    hInstance=pystray_win32.win32.GetModuleHandle(None),
                    hIcon=None,
                    hCursor=None,
                    hbrBackground=pystray_win32.win32.COLOR_WINDOW + 1,
                    lpszMenuName=None,
                    lpszClassName=f"{self.name}{id(self)}SystemTrayIcon",
                    hIconSm=None,
                )
            )

    return WindowsDoubleClickIcon


class WindowsPlatformServices(PlatformServices):

    startup_toggle_label = "Launch on Windows startup"
    settings_menu_default = True

    def get_config_dir(self, app_name, runtime_root_dir):
        appdata = os.getenv("APPDATA")
        if appdata:
            return os.path.join(appdata, app_name)
        return None

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

    def get_tray_icon_class(self, pystray):
        return get_tray_icon_class(pystray)

    def supports_self_update(self):
        return supports_self_update()

    def select_update_asset(self, assets):
        return select_update_asset(assets)

    def stage_update_install(self, download_path, relaunch_args, source_pid):
        return stage_update_install(download_path, relaunch_args, source_pid)

    def handle_special_args(self, argv):
        return handle_special_args(argv)
