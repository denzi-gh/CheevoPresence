"""Windows-specific adapters for startup, secrets, and tray behavior."""

import base64
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from tkinter import messagebox

from desktop.core.constants import APP_NAME
from desktop.platform.base import PlatformServices

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


class DataBlob(ctypes.Structure):
    """Mirror the Win32 DATA_BLOB struct used by DPAPI."""

    _fields_ = [
        ("cbData", ctypes.c_uint),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _blob_from_bytes(data):
    """Wrap Python bytes in a DATA_BLOB plus a keepalive buffer."""
    if not data:
        return DataBlob(), None
    buffer = ctypes.create_string_buffer(data)
    return DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def protect_api_key(value):
    """Encrypt the API key for storage, using DPAPI on Windows."""
    if not value:
        return ""

    raw = value.encode("utf-8")
    if os.name != "nt":
        return base64.b64encode(raw).decode("ascii")

    input_blob, _keepalive = _blob_from_bytes(raw)
    output_blob = DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(ctypes.byref(input_blob), APP_NAME, None, None, None, 0, ctypes.byref(output_blob)):
        raise OSError("Could not protect the API key.")

    try:
        protected = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return base64.b64encode(protected).decode("ascii")
    finally:
        if output_blob.pbData:
            kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))


def unprotect_api_key(value):
    """Decrypt a previously stored API key back into plain text."""
    if not isinstance(value, str) or not value:
        return ""

    try:
        raw = base64.b64decode(value)
    except (ValueError, TypeError):
        return ""

    if os.name != "nt":
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return ""

    input_blob, _keepalive = _blob_from_bytes(raw)
    output_blob = DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)):
        return ""

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData).decode("utf-8")
    except UnicodeDecodeError:
        return ""
    finally:
        if output_blob.pbData:
            kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))


def acquire_single_instance():
    """Create a Windows mutex so only one tray instance can run at a time."""
    global _single_instance_mutex

    if os.name != "nt":
        return True

    try:
        kernel32 = ctypes.windll.kernel32
        mutex = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX_NAME)
        if not mutex:
            return True

        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(mutex)
            return False

        _single_instance_mutex = mutex
        return True
    except Exception:
        return True


def notify_already_running():
    """Show a small info dialog when a second instance is launched."""
    message = f"{APP_NAME} is already running in the system tray."

    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x40)
            return
        except Exception:
            pass

    try:
        messagebox.showinfo(APP_NAME, message)
    except Exception:
        pass


def request_running_app_exit():
    """Signal the running tray instance to shut itself down."""
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
    except Exception:
        return False


def start_exit_listener(callback):
    """Listen for a named Win32 event triggered by `--exit`."""
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
            return None
    except Exception:
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
            pass

    _exit_listener_thread = threading.Thread(target=listen_for_exit, daemon=True)
    _exit_listener_thread.start()
    return _exit_listener_thread


def get_exe_path():
    """Return the path to the running executable or script."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(sys.argv[0])


def _encode_relaunch_args(values):
    """Serialize relaunch arguments into a compact command-line token."""
    raw = json.dumps(list(values or []), separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_relaunch_args(value):
    """Restore relaunch arguments previously encoded for the update helper."""
    if not value:
        return []
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
        decoded = json.loads(raw.decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    return [str(item) for item in decoded if item is not None]


def _append_update_log(log_path, message):
    """Append a timestamped line to the helper log when troubleshooting updates."""
    try:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def _wait_for_process_exit(pid, timeout_seconds=120):
    """Wait for a Windows process id to exit, falling back to polling if needed."""
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
        except Exception:
            probe = None
        if not probe:
            return
        kernel32.CloseHandle(probe)
        time.sleep(1)


def _replace_file_with_retries(source_path, target_path, log_path, attempts=60):
    """Retry replacing the old EXE until Windows releases the target file."""
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
    """Remove temporary update directories after the helper exits."""
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
    """Parse the embedded update-helper command line into a small options dict."""
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
    """Run the embedded updater helper when the app is launched in helper mode."""
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
    except Exception as exc:
        _append_update_log(log_path, f"Launch failed: {exc}")

    _spawn_cleanup(cleanup_paths)
    _append_update_log(log_path, "Helper finished.")
    return True


def supports_self_update():
    """Return whether the packaged Windows executable can replace itself."""
    exe_path = get_exe_path()
    return os.name == "nt" and getattr(sys, "frozen", False) and exe_path.lower().endswith(".exe")


def select_update_asset(assets):
    """Choose the preferred Windows release asset from the GitHub asset list."""
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
    """Copy the running EXE to temp and launch it in embedded update-helper mode."""
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
    """Enable or disable Windows startup by writing the Run registry value."""
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
        return None
    except Exception:
        return "Could not update the Windows startup setting."


def is_autostart_enabled():
    """Return whether the Windows startup registry entry already exists."""
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, STARTUP_REG_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def get_tray_icon_class(pystray):
    """Return the tray icon class that matches the current OS behavior."""
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
                    lpszClassName="%s%dSystemTrayIcon" % (self.name, id(self)),
                    hIconSm=None,
                )
            )

    return WindowsDoubleClickIcon


class WindowsPlatformServices(PlatformServices):
    """Bundle the Windows-specific hooks needed by the desktop runtime."""

    startup_toggle_label = "Launch on Windows startup"
    settings_menu_default = True

    def get_config_dir(self, app_name, runtime_root_dir):
        """Store config under %APPDATA% when it is available on Windows."""
        appdata = os.getenv("APPDATA")
        if appdata:
            return os.path.join(appdata, app_name)
        return None

    def protect_api_key(self, value):
        """Protect the API key using Windows DPAPI."""
        return protect_api_key(value)

    def unprotect_api_key(self, value):
        """Restore a DPAPI-protected API key."""
        return unprotect_api_key(value)

    def acquire_single_instance(self):
        """Claim the Windows single-instance mutex."""
        return acquire_single_instance()

    def notify_already_running(self):
        """Show the standard duplicate-instance notice."""
        return notify_already_running()

    def request_running_app_exit(self):
        """Signal the running tray instance to exit."""
        return request_running_app_exit()

    def start_exit_listener(self, callback):
        """Start listening for external shutdown requests."""
        return start_exit_listener(callback)

    def set_autostart(self, enable):
        """Update the Windows Run registry entry."""
        return set_autostart(enable)

    def is_autostart_enabled(self):
        """Read the Windows Run registry state."""
        return is_autostart_enabled()

    def get_tray_icon_class(self, pystray):
        """Return the Windows tray class with double-click support."""
        return get_tray_icon_class(pystray)

    def supports_self_update(self):
        """Report whether the running Windows app can replace its own EXE."""
        return supports_self_update()

    def select_update_asset(self, assets):
        """Pick the preferred EXE asset for the latest Windows release."""
        return select_update_asset(assets)

    def stage_update_install(self, download_path, relaunch_args, source_pid):
        """Start the detached Windows helper that installs the downloaded EXE."""
        return stage_update_install(download_path, relaunch_args, source_pid)

    def handle_special_args(self, argv):
        """Run the embedded Windows update helper before normal app startup."""
        return handle_special_args(argv)
