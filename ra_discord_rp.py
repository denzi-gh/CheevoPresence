"""
RetroAchievements Discord Rich Presence - GUI Application
Mirrors your RetroAchievements activity to Discord Rich Presence.
"""

import configparser
from contextlib import contextmanager
import ctypes
import base64
import json
import os
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timezone
from urllib.parse import quote

import webbrowser

import requests
from pypresence import Presence, ActivityType
from pypresence import exceptions as pypresence_exceptions
from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DISCORD_APP_ID = "1485964205713788958"
RA_API_BASE = "https://retroachievements.org/API"
APP_NAME = "CheevoPresence"
APP_VERSION = "1.0.0"
RA_SETTINGS_URL = "https://retroachievements.org/settings"
SINGLE_INSTANCE_MUTEX_NAME = f"Local\\{APP_NAME}Singleton"
ERROR_ALREADY_EXISTS = 183

_single_instance_mutex = None


def get_resource_dir():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_config_dir():
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP_NAME)
    appdata = os.getenv("APPDATA")
    if appdata:
        return os.path.join(appdata, APP_NAME)
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), APP_NAME)
    return os.path.dirname(os.path.abspath(__file__))


RESOURCE_DIR = get_resource_dir()
CONFIG_DIR = get_config_dir()
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
LEGACY_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
CONSOLE_ICONS_FILE = os.path.join(RESOURCE_DIR, "console_icons.ini")
APP_ICON_FILE = os.path.join(RESOURCE_DIR, "cheevoRP_icon.ico")
TRAY_INACTIVE_ICON_FILE = os.path.join(RESOURCE_DIR, "cheevoRP_inactive.ico")
TRAY_ACTIVE_ICON_FILE = os.path.join(RESOURCE_DIR, "cheevoRP_active.ico")
TRAY_ERROR_ICON_FILE = os.path.join(RESOURCE_DIR, "cheevoRP_error.ico")

STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REG_NAME = "CheevoPresence"


def acquire_single_instance():
    global _single_instance_mutex

    if os.name == "nt":
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

    # Unix: use a file lock
    lock_file = None
    try:
        import fcntl
        os.makedirs(CONFIG_DIR, exist_ok=True)
        lock_path = os.path.join(CONFIG_DIR, f".{APP_NAME}.lock")
        lock_file = open(lock_path, "w")
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Keep the file object alive to hold the lock
        _single_instance_mutex = lock_file
        return True
    except (OSError, IOError):
        if lock_file is not None:
            lock_file.close()
        return False
    except Exception:
        return True


def notify_already_running():
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


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "username": "",
    "apikey": "",
    "show_profile_button": True,
    "show_gamepage_button": True,
    "interval": 5,
    "timeout": 130,
    "start_on_boot": False,
}


class DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _blob_from_bytes(data):
    if not data:
        return DataBlob(), None
    buffer = ctypes.create_string_buffer(data)
    return DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def protect_api_key(value):
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


def normalize_config(raw):
    cfg = dict(DEFAULT_CONFIG)
    if not isinstance(raw, dict):
        return cfg

    username = raw.get("username", "")
    if isinstance(username, str):
        cfg["username"] = username.strip()

    apikey = raw.get("apikey", "")
    if isinstance(apikey, str) and apikey.strip():
        cfg["apikey"] = apikey.strip()
    else:
        cfg["apikey"] = unprotect_api_key(raw.get("apikey_protected", ""))

    for key in ("show_profile_button", "show_gamepage_button", "start_on_boot"):
        value = raw.get(key, cfg[key])
        if isinstance(value, bool):
            cfg[key] = value
        elif isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                cfg[key] = True
            elif lowered in {"0", "false", "no", "off"}:
                cfg[key] = False

    try:
        interval = int(raw.get("interval", cfg["interval"]))
    except (TypeError, ValueError):
        interval = cfg["interval"]
    cfg["interval"] = min(120, max(5, interval))

    try:
        timeout = int(raw.get("timeout", cfg["timeout"]))
    except (TypeError, ValueError):
        timeout = cfg["timeout"]
    timeout = max(0, min(3600, timeout))
    if 0 < timeout < 130:
        timeout = 130
    cfg["timeout"] = timeout

    return cfg


def load_config():
    source = CONFIG_FILE
    if not os.path.exists(source) and LEGACY_CONFIG_FILE != CONFIG_FILE and os.path.exists(LEGACY_CONFIG_FILE):
        source = LEGACY_CONFIG_FILE
    if os.path.exists(source):
        try:
            with open(source, "r", encoding="utf-8") as f:
                saved = json.load(f)
            cfg = normalize_config(saved)
            if source != CONFIG_FILE:
                save_config(cfg)
                try:
                    os.remove(source)
                except OSError:
                    pass
            return cfg
        except (json.JSONDecodeError, OSError):
            return dict(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    cfg = normalize_config(cfg)
    stored_cfg = {key: value for key, value in cfg.items() if key != "apikey"}
    protected_apikey = protect_api_key(cfg["apikey"])
    if protected_apikey:
        stored_cfg["apikey_protected"] = protected_apikey
    dir_path = os.path.dirname(CONFIG_FILE)
    os.makedirs(dir_path, exist_ok=True)
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(stored_cfg, f, indent=2)
        os.replace(tmp_path, CONFIG_FILE)
    except OSError:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(stored_cfg, f, indent=2)


# ---------------------------------------------------------------------------
# Console icon mapping
# ---------------------------------------------------------------------------
def load_console_icons():
    cp = configparser.ConfigParser()
    cp.read(CONSOLE_ICONS_FILE)
    mapping = {}
    if cp.has_section("CI"):
        for key, val in cp.items("CI"):
            mapping[key.strip()] = val.strip()
    return mapping


# ---------------------------------------------------------------------------
# Autostart helpers
# ---------------------------------------------------------------------------
def get_exe_path():
    """Return the path to the running executable or script."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(sys.argv[0])


_LAUNCHAGENT_LABEL = "com.cheevopresence.app"


def _get_launchagent_path():
    return os.path.join(
        os.path.expanduser("~"), "Library", "LaunchAgents", f"{_LAUNCHAGENT_LABEL}.plist"
    )


def _get_launch_args():
    exe = get_exe_path()
    if exe.endswith(".py"):
        return [sys.executable, exe, "--tray"]
    return [exe, "--tray"]


def set_autostart(enable):
    if sys.platform == "darwin":
        return _set_autostart_macos(enable)
    return _set_autostart_windows(enable)


def _set_autostart_windows(enable):
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE)
        try:
            if enable:
                val = " ".join(f'"{a}"' for a in _get_launch_args())
                winreg.SetValueEx(key, STARTUP_REG_NAME, 0, winreg.REG_SZ, val)
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


def _set_autostart_macos(enable):
    import plistlib
    plist_path = _get_launchagent_path()
    try:
        if enable:
            plist = {
                "Label": _LAUNCHAGENT_LABEL,
                "ProgramArguments": _get_launch_args(),
                "RunAtLoad": True,
            }
            os.makedirs(os.path.dirname(plist_path), exist_ok=True)
            with open(plist_path, "wb") as f:
                plistlib.dump(plist, f)
        else:
            try:
                os.remove(plist_path)
            except FileNotFoundError:
                pass
        return None
    except Exception:
        return "Could not update the login item setting."


def is_autostart_enabled():
    if sys.platform == "darwin":
        return os.path.exists(_get_launchagent_path())
    return _is_autostart_enabled_windows()


def _is_autostart_enabled_windows():
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


# ---------------------------------------------------------------------------
# Tray icon image generation
# ---------------------------------------------------------------------------
def create_tray_icon(color):
    """Create a simple circle icon in the given color."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill=color, outline=(255, 255, 255, 255), width=2)
    return img


def load_icon_image(path):
    """Load an icon image from disk and detach it from the file handle."""
    if not os.path.exists(path):
        return None
    try:
        with Image.open(path) as img:
            return img.copy()
    except Exception:
        return None


if sys.platform == "darwin":
    SYSTEM_FONT = "Helvetica Neue"
elif os.name == "nt":
    SYSTEM_FONT = "Segoe UI"
else:
    SYSTEM_FONT = "sans-serif"


class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)
        widget.bind("<ButtonPress>", self.hide)

    def show(self, _event=None):
        if self.tip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() + 10
        y = self.widget.winfo_rooty() - 2
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw, text=self.text, justify="left",
            bg="#1a1e26", fg="#e0e4ec", relief="solid", borderwidth=1,
            padx=8, pady=6, font=(SYSTEM_FONT, 9), wraplength=280,
        ).pack()

    def hide(self, _event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None




# ---------------------------------------------------------------------------
# RetroAchievements API
# ---------------------------------------------------------------------------
def trimmer(text, max_units=128):
    """Trim text to fit within max_units UTF-16 code units."""
    encoded = text.encode("utf-16-le")
    if len(encoded) <= max_units * 2:
        return text
    # Trim character by character to avoid splitting surrogate pairs
    result = ""
    size = 0
    for ch in text:
        ch_size = len(ch.encode("utf-16-le"))
        if size + ch_size > (max_units - 3) * 2:
            return result + "..."
        result += ch
        size += ch_size
    return result


def ra_get_user_summary(username, apikey):
    now = datetime.now()
    no_cache = now.strftime("%d%m%Y%H%M%S")
    url = f"{RA_API_BASE}/API_GetUserSummary.php"
    params = {"u": username, "y": apikey, "g": 0, "a": 0, "noCache": no_cache}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise APIResponseError
    return data


def ra_get_game(username, apikey, game_id):
    url = f"{RA_API_BASE}/API_GetGame.php"
    params = {"z": username, "y": apikey, "i": game_id}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise APIResponseError
    return data


def ra_get_user_progress(username, apikey, game_id):
    url = f"{RA_API_BASE}/API_GetUserProgress.php"
    params = {"u": username, "y": apikey, "i": game_id}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise APIResponseError
    return data


def format_api_error(exc):
    """Return a user-safe API error message without leaking query params."""
    if isinstance(exc, requests.Timeout):
        return "API error: request timed out"
    if isinstance(exc, requests.ConnectionError):
        return "API error: network unavailable"

    response = getattr(exc, "response", None)
    if response is not None and response.status_code:
        if response.status_code == 401:
            return "Invalid Web API Key"
        return f"API error: HTTP {response.status_code}"

    return "API error: request failed"


class APIResponseError(Exception):
    pass


def is_discord_unavailable_error(exc):
    return isinstance(
        exc,
        (
            pypresence_exceptions.DiscordNotFound,
            pypresence_exceptions.InvalidPipe,
            pypresence_exceptions.PipeClosed,
            BrokenPipeError,
            ConnectionResetError,
        ),
    )


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
                    None)
                if index > 0:
                    descriptors[index - 1](self)

        def _register_class(self):
            return pystray_win32.win32.RegisterClassEx(pystray_win32.win32.WNDCLASSEX(
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
                lpszClassName='%s%dSystemTrayIcon' % (self.name, id(self)),
                hIconSm=None))

    return WindowsDoubleClickIcon


# ---------------------------------------------------------------------------
# RPC Worker Thread
# ---------------------------------------------------------------------------
class RPCWorker:
    def __init__(self, status_callback=None):
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._external_callback = status_callback
        self.config = load_config()
        self.console_icons = load_console_icons()
        self.running = False
        self.thread = None
        self.rpc = None
        self.rpc_connected = False
        self.start_time = None
        self._current_game_id = None
        self.current_status = "disconnected"
        self.status_text = "Not running"
        self.ra_connected = False
        self.ra_status_text = "Not connected to RetroAchievements"

    def status_callback(self, status, text):
        self.current_status = status
        self.status_text = text
        if self._external_callback:
            self._external_callback(status, text)

    def set_ra_status(self, connected):
        self.ra_connected = connected
        self.ra_status_text = "Connected to RetroAchievements" if connected else "Not connected to RetroAchievements"

    def is_busy(self):
        with self._state_lock:
            return self.running or (self.thread is not None and self.thread.is_alive())

    def is_stopping(self):
        with self._state_lock:
            return not self.running and self.thread is not None and self.thread.is_alive()

    def start(self, config=None):
        with self._state_lock:
            if self.running or (self.thread is not None and self.thread.is_alive()):
                return False

            cfg = normalize_config(config if config is not None else load_config())
            if not cfg["username"] or not cfg["apikey"]:
                self.set_ra_status(False)
                self.status_callback("error", "Username or API Key missing")
                return False

            self.config = cfg
            self._stop_event.clear()
            self.running = True
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()
            return True

    def stop(self):
        with self._state_lock:
            thread = self.thread
            if not self.running and not (thread and thread.is_alive()):
                self._disconnect_rpc()
                self._current_game_id = None
                self.set_ra_status(False)
                self.status_callback("disconnected", "Stopped")
                return True
            self.running = False
            self._stop_event.set()

        if thread and thread is not threading.current_thread():
            thread.join(timeout=35)

        stopped = not thread or not thread.is_alive()
        if stopped:
            self.status_callback("disconnected", "Stopped")
        else:
            self.status_callback("connecting", "Stopping...")
        return stopped

    def _should_stop(self):
        return self._stop_event.is_set() or not self.running

    def _current_thread_done(self):
        with self._state_lock:
            self.running = False
            if threading.current_thread() is self.thread:
                self.thread = None

    def _coerce_progress_int(self, value):
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    def _build_achievement_state(self, total, achieved, achieved_hc):
        if total <= 0:
            return "No achievements available", 0
        if achieved <= 0:
            return "No achievements yet", 0
        if achieved_hc < achieved:
            return "\U0001F3C6 Softcore", achieved
        return "\U0001F3C6 Hardcore", achieved_hc

    def _unexpected_api_response(self):
        self._disconnect_rpc()
        self.set_ra_status(False)
        self.status_callback("error", "API error: unexpected response")

    def _connect_rpc(self):
        with self._lock:
            if self.rpc_connected:
                return True
            try:
                # Close any stale Presence object before creating a new one
                if self.rpc:
                    try:
                        self.rpc.close()
                    except Exception:
                        pass
                    self.rpc = None
                self.rpc = Presence(DISCORD_APP_ID)
                self.rpc.connect()
                self.rpc_connected = True
                self.start_time = int(time.time())
                self.status_callback("connected", "Connected to Discord")
                return True
            except Exception as e:
                self.rpc = None
                self.rpc_connected = False
                if is_discord_unavailable_error(e):
                    self.status_callback("error", "Discord is not open")
                else:
                    self.status_callback("error", "Discord connection failed")
                return False

    def _disconnect_rpc(self):
        with self._lock:
            if self.rpc:
                if self.rpc_connected:
                    try:
                        self.rpc.clear()
                        self.rpc.close()
                    except Exception:
                        pass
                else:
                    try:
                        self.rpc.close()
                    except Exception:
                        pass
            self.rpc = None
            self.rpc_connected = False
            self.start_time = None

    def _loop(self):
        try:
            self.set_ra_status(False)
            self.status_callback("connecting", "Starting...")
            self.config = normalize_config(self.config)
            username = self.config["username"]
            apikey = self.config["apikey"]
            interval = self.config["interval"]
            timeout_sec = self.config["timeout"]
            consecutive_errors = 0

            while not self._should_stop():
                try:
                    user_data = ra_get_user_summary(username, apikey)
                    if self._should_stop():
                        break

                    self.set_ra_status(True)
                    last_game_id = self._coerce_progress_int(user_data.get("LastGameID", 0))

                    rp_msg = user_data.get("RichPresenceMsg", "")
                    if not isinstance(rp_msg, str):
                        raise APIResponseError

                    rp_date_str = user_data.get("RichPresenceMsgDate", "")
                    if rp_date_str is None:
                        rp_date_str = ""
                    if not isinstance(rp_date_str, str):
                        raise APIResponseError

                    if not last_game_id:
                        self._disconnect_rpc()
                        self._current_game_id = None
                        self.status_callback("disconnected", "Not playing")
                        consecutive_errors = 0
                        self._sleep(interval)
                        continue

                    is_active = True
                    if timeout_sec > 0 and rp_date_str:
                        try:
                            rp_date = datetime.strptime(rp_date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                            time_diff = (datetime.now(timezone.utc) - rp_date).total_seconds()
                            if time_diff > timeout_sec:
                                is_active = False
                        except ValueError:
                            pass
                    elif not rp_date_str:
                        is_active = False

                    if not is_active:
                        self._disconnect_rpc()
                        self._current_game_id = None
                        self.status_callback("disconnected", "Not actively playing")
                        consecutive_errors = 0
                        self._sleep(interval)
                        continue

                    game_data = ra_get_game(username, apikey, last_game_id)
                    if self._should_stop():
                        break

                    progress_data = ra_get_user_progress(username, apikey, last_game_id)
                    if self._should_stop():
                        break

                    game_title = game_data.get("GameTitle", "Unknown")
                    if not isinstance(game_title, str):
                        raise APIResponseError

                    console_name = game_data.get("ConsoleName", "Unknown")
                    if not isinstance(console_name, str):
                        raise APIResponseError

                    console_id = str(game_data.get("ConsoleID", "0"))
                    image_icon = game_data.get("ImageIcon", "")
                    if image_icon is None:
                        image_icon = ""
                    if not isinstance(image_icon, str):
                        raise APIResponseError

                    if last_game_id != self._current_game_id:
                        self._current_game_id = last_game_id
                        if self.rpc_connected:
                            self.start_time = int(time.time())

                    gid_str = str(last_game_id)
                    prog = progress_data.get(gid_str, {})
                    if prog is None:
                        prog = {}
                    if not isinstance(prog, dict):
                        raise APIResponseError

                    total = self._coerce_progress_int(prog.get("NumPossibleAchievements", 0))
                    achieved = self._coerce_progress_int(prog.get("NumAchieved", 0))
                    achieved_hc = self._coerce_progress_int(prog.get("NumAchievedHardcore", 0))
                    state_str, achi_count = self._build_achievement_state(total, achieved, achieved_hc)

                    party = [achi_count, total] if total > 0 else None
                    large_tooltip = f"{achi_count}/{total} achievements" if total > 0 else state_str

                    game_url = f"https://retroachievements.org/game/{last_game_id}"
                    profile_url = f"https://retroachievements.org/user/{quote(username)}"

                    buttons = []
                    if self.config.get("show_gamepage_button", True):
                        buttons.append({
                            "label": "View on RetroAchievements",
                            "url": game_url,
                        })
                    if self.config.get("show_profile_button", True):
                        buttons.append({
                            "label": f"{username}'s RA Page",
                            "url": profile_url,
                        })
                    if not buttons:
                        buttons = None

                    large_img = f"https://media.retroachievements.org{image_icon}" if image_icon else None
                    small_img = self.console_icons.get(console_id)

                    if not self._connect_rpc():
                        self._sleep(interval)
                        continue
                    if self._should_stop():
                        break

                    update_kwargs = dict(
                        activity_type=ActivityType.PLAYING,
                        name=game_title,
                        details=trimmer(rp_msg) if rp_msg else None,
                        state=state_str,
                        start=self.start_time,
                        large_image=large_img,
                        large_text=large_tooltip,
                        small_image=small_img,
                        small_text=console_name,
                        buttons=buttons,
                    )
                    if party:
                        update_kwargs["party_id"] = f"ra_{last_game_id}"
                        update_kwargs["party_size"] = party

                    self.rpc.update(**update_kwargs)
                    self.status_callback("connected", f"Playing: {game_title} ({console_name})")
                    consecutive_errors = 0

                except requests.RequestException as e:
                    consecutive_errors += 1
                    self._disconnect_rpc()
                    self.set_ra_status(False)
                    self.status_callback("error", format_api_error(e))
                except APIResponseError:
                    consecutive_errors += 1
                    self._unexpected_api_response()
                except Exception as e:
                    consecutive_errors += 1
                    self._disconnect_rpc()
                    if is_discord_unavailable_error(e):
                        self.status_callback("error", "Discord is not open")
                    else:
                        self.set_ra_status(False)
                        self.status_callback("error", "Error: unexpected failure")

                wait = min(interval * (2 ** min(consecutive_errors, 4)), 60) if consecutive_errors > 0 else interval
                self._sleep(wait)
        finally:
            self._disconnect_rpc()
            self._current_game_id = None
            self.set_ra_status(False)
            self._current_thread_done()
            if self._stop_event.is_set():
                self.status_callback("disconnected", "Stopped")

    def _sleep(self, seconds):
        for _ in range(int(seconds)):
            if self._should_stop():
                return
            time.sleep(1)


# ---------------------------------------------------------------------------
# macOS: work around Tk/AppKit menu assertion crash
# ---------------------------------------------------------------------------
# TkAqua's TKMenu subclass asserts that only TKMenuItemProxy items are inserted.
# On recent macOS, AppKit's _addDebugMenuIfNeeded inserts a regular NSMenuItem
# during Tk_CreateConsoleWindow, hitting a fatal NSAssert.  Installing a silent
# NSAssertionHandler around tk.Tk() lets the assertion pass without throwing,
# so the debug item is inserted normally and Tk initialisation completes.

@contextmanager
def _suppress_tk_menu_assertion():
    """Temporarily install a no-op NSAssertionHandler for the current thread."""
    try:
        import objc
        NSAssertionHandler = objc.lookUpClass("NSAssertionHandler")
        NSThread = objc.lookUpClass("NSThread")

        # Define the subclass only once; ObjC class registration is permanent.
        if not hasattr(_suppress_tk_menu_assertion, "_handler_cls"):

            class _SilentAssertionHandler(NSAssertionHandler):
                def handleFailureInMethod_object_file_lineNumber_description_(
                    self, sel, obj, fname, line, desc
                ):
                    pass

                def handleFailureInFunction_file_lineNumber_description_(
                    self, func, fname, line, desc
                ):
                    pass

            _suppress_tk_menu_assertion._handler_cls = _SilentAssertionHandler

        td = NSThread.currentThread().threadDictionary()
        td["NSAssertionHandler"] = _suppress_tk_menu_assertion._handler_cls.alloc().init()
        try:
            yield
        finally:
            td.removeObjectForKey_("NSAssertionHandler")
    except Exception:
        yield


# ---------------------------------------------------------------------------
# System Tray (pystray)
# ---------------------------------------------------------------------------
class TrayApp:
    def __init__(self):
        self.icon = None
        self._tk_root = None
        self.worker = RPCWorker(self._on_status)
        self.current_status = "disconnected"
        self.status_text = "Not running"
        self._settings_open = False
        self._fallback_colors = {
            "connected": (0, 200, 0, 255),
            "connecting": (255, 165, 0, 255),
            "disconnected": (150, 150, 150, 255),
            "error": (220, 0, 0, 255),
        }

    def _get_tray_image(self):
        icon_map = {
            "connected": TRAY_ACTIVE_ICON_FILE,
            "connecting": APP_ICON_FILE,
            "disconnected": TRAY_INACTIVE_ICON_FILE,
            "error": TRAY_ERROR_ICON_FILE,
        }
        image = load_icon_image(icon_map.get(self.current_status, APP_ICON_FILE))
        if image is not None:
            return image
        color = self._fallback_colors.get(self.current_status, (150, 150, 150, 255))
        return create_tray_icon(color)

    def _on_status(self, status, text):
        self.current_status = status
        self.status_text = text
        self._update_icon()

    def _update_icon(self):
        if not self.icon:
            return
        self.icon.icon = self._get_tray_image()
        self.icon.title = f"{APP_NAME} - {self.status_text}"

    def _on_settings(self, icon, item):
        if self._settings_open:
            return
        self._settings_open = True
        if self._tk_root:
            self._tk_root.after(0, self._show_settings_window)
        else:
            threading.Thread(target=self._show_settings_window, daemon=True).start()

    def _show_settings_window(self):
        try:
            SettingsWindow(self.worker, on_close=self._on_settings_closed, on_quit=self.quit_app, tk_root=self._tk_root)
        except Exception:
            self._settings_open = False

    def _on_settings_closed(self):
        self._settings_open = False

    def quit_app(self):
        self.worker.stop()
        if self.icon:
            self.icon.stop()
        if self._tk_root:
            try:
                self._tk_root.after(0, self._tk_root.destroy)
            except tk.TclError:
                pass

    def _on_quit(self, icon, item):
        self.quit_app()

    def _get_status_text(self):
        return self.status_text

    def _on_get_api_key(self, icon, item):
        webbrowser.open(RA_SETTINGS_URL)

    def run(self):
        import pystray

        icon_class = get_tray_icon_class(pystray)
        menu = pystray.Menu(
            pystray.MenuItem(f"{APP_NAME} v{APP_VERSION}", None, enabled=False),
            pystray.MenuItem(lambda text: self._get_status_text(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Settings", self._on_settings, default=True),
            pystray.MenuItem("Open RA Settings (Web)", self._on_get_api_key),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._on_quit),
        )

        ico = load_icon_image(APP_ICON_FILE) or create_tray_icon((150, 150, 150, 255))

        self.icon = icon_class(APP_NAME, ico, APP_NAME, menu)
        self._update_icon()

        # Auto-start if configured
        cfg = load_config()
        if cfg["username"] and cfg["apikey"]:
            self.worker.start(cfg)

        self.icon.run()

    def run_with_tk(self, show_settings=False):
        """macOS: Tk owns the main thread, pystray runs in a background thread."""
        with _suppress_tk_menu_assertion():
            self._tk_root = tk.Tk()
        self._tk_root.withdraw()

        threading.Thread(target=self.run, daemon=True).start()

        if show_settings:
            self._tk_root.after(100, self._open_initial_settings)

        self._tk_root.mainloop()

    def _open_initial_settings(self):
        if self._settings_open:
            return
        self._settings_open = True
        self._show_settings_window()


# ---------------------------------------------------------------------------
# Settings GUI (tkinter)
# ---------------------------------------------------------------------------
class SettingsWindow:
    BG = "#0b0d12"
    SURFACE = "#131821"
    BORDER = "#2a313d"
    TEXT = "#f3f7ff"
    MUTED = "#a4afbf"
    ENTRY_BG = "#0d1219"
    ACCENT = "#f0b14a"
    GREEN = "#57f287"
    RED = "#ed4245"
    FONT = SYSTEM_FONT

    def __init__(self, worker: RPCWorker, on_close=None, on_quit=None, tk_root=None):
        self.worker = worker
        self.on_close = on_close
        self.on_quit = on_quit
        self._destroyed = False
        self._is_connecting = False
        self._toggle_lock = threading.Lock()
        self._tk_root = tk_root
        self.cfg = load_config()
        self._tooltips = []

        if tk_root:
            self.root = tk.Toplevel(tk_root)
        else:
            self.root = tk.Tk()
        self.root.title(f"{APP_NAME}")
        self.root.resizable(False, False)
        self.root.configure(bg=self.BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)
        try:
            if os.name == "nt":
                self.root.iconbitmap(APP_ICON_FILE)
            else:
                from PIL import ImageTk
                _icon_img = load_icon_image(APP_ICON_FILE)
                if _icon_img:
                    _icon_photo = ImageTk.PhotoImage(_icon_img)
                    self.root.iconphoto(True, _icon_photo)
                    self._icon_photo_ref = _icon_photo  # prevent GC
        except Exception:
            pass

        style = ttk.Style(self.root)
        style.theme_use("clam")
        for name, bg, fg, abg in [
            ("Accent.TButton", self.ACCENT, "#081018", "#ffc86a"),
            ("Disconnect.TButton", "#2a313d", self.TEXT, "#394355"),
            ("Quit.TButton", self.RED, "white", "#c03537"),
        ]:
            style.configure(name, background=bg, foreground=fg, font=(self.FONT, 10, "bold"), padding=(14, 8), borderwidth=0)
            style.map(name, background=[("active", abg), ("disabled", "#333")])
        style.configure("Panel.TCheckbutton", background=self.SURFACE, foreground=self.TEXT, font=(self.FONT, 10))
        style.map("Panel.TCheckbutton", background=[("active", self.SURFACE)], foreground=[("disabled", self.MUTED)])

        main = tk.Frame(self.root, bg=self.BG, padx=20, pady=16)
        main.pack(fill="both", expand=True)

        # -- Header --
        tk.Label(main, text=APP_NAME, bg=self.BG, fg=self.ACCENT, font=(self.FONT, 16, "bold")).pack(anchor="w")
        tk.Label(main, text="Mirror your RetroAchievements activity to Discord.", bg=self.BG, fg=self.MUTED, font=(self.FONT, 9)).pack(anchor="w", pady=(2, 12))

        # -- Status row --
        status_frame = self._card(main)
        status_frame.pack(fill="x")
        status_row = tk.Frame(status_frame, bg=self.SURFACE)
        status_row.pack(fill="x")

        # Discord status
        dc_frame = tk.Frame(status_row, bg=self.SURFACE)
        dc_frame.pack(side="left", fill="x", expand=True)
        tk.Label(dc_frame, text="Discord", bg=self.SURFACE, fg=self.MUTED, font=(self.FONT, 9, "bold")).pack(anchor="w")
        dc_val = tk.Frame(dc_frame, bg=self.SURFACE)
        dc_val.pack(anchor="w", pady=(4, 0))
        self.status_dot = tk.Label(dc_val, text="\u25cf", bg=self.SURFACE, fg=self.MUTED, font=(self.FONT, 10))
        self.status_dot.pack(side="left")
        self.status_var = tk.StringVar(value=self.worker.status_text)
        self.status_label = tk.Label(dc_val, textvariable=self.status_var, bg=self.SURFACE, fg=self.TEXT, font=(self.FONT, 10, "bold"))
        self.status_label.pack(side="left", padx=(4, 0))

        # RA status
        ra_frame = tk.Frame(status_row, bg=self.SURFACE)
        ra_frame.pack(side="left", fill="x", expand=True, padx=(16, 0))
        tk.Label(ra_frame, text="RetroAchievements", bg=self.SURFACE, fg=self.MUTED, font=(self.FONT, 9, "bold")).pack(anchor="w")
        ra_val = tk.Frame(ra_frame, bg=self.SURFACE)
        ra_val.pack(anchor="w", pady=(4, 0))
        self.ra_status_dot = tk.Label(ra_val, text="\u25cf", bg=self.SURFACE, fg=self.MUTED, font=(self.FONT, 10))
        self.ra_status_dot.pack(side="left")
        self.ra_status_var = tk.StringVar(value=self.worker.ra_status_text)
        self.ra_status_label = tk.Label(ra_val, textvariable=self.ra_status_var, bg=self.SURFACE, fg=self.TEXT, font=(self.FONT, 10, "bold"))
        self.ra_status_label.pack(side="left", padx=(4, 0))

        # -- Two column layout --
        cols = tk.Frame(main, bg=self.BG)
        cols.pack(fill="x", pady=(12, 0))

        # Left: Account
        left = self._card(cols)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="Account", bg=self.SURFACE, fg=self.TEXT, font=(self.FONT, 11, "bold")).pack(anchor="w")

        tk.Label(left, text="RA Username", bg=self.SURFACE, fg=self.MUTED, font=(self.FONT, 9)).pack(anchor="w", pady=(10, 0))
        self.username_var = tk.StringVar(value=self.cfg["username"])
        self.username_entry = self._entry(left, self.username_var)
        self.username_entry.pack(fill="x", pady=(4, 0), ipady=6)

        tk.Label(left, text="Web API Key", bg=self.SURFACE, fg=self.MUTED, font=(self.FONT, 9)).pack(anchor="w", pady=(10, 0))
        self.apikey_var = tk.StringVar(value=self.cfg["apikey"])
        self.apikey_entry = self._entry(left, self.apikey_var, show="*")
        self.apikey_entry.pack(fill="x", pady=(4, 0), ipady=6)

        # Right: Behavior
        right = self._card(cols)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        tk.Label(right, text="Behavior", bg=self.SURFACE, fg=self.TEXT, font=(self.FONT, 11, "bold")).pack(anchor="w")

        spin_row = tk.Frame(right, bg=self.SURFACE)
        spin_row.pack(fill="x", pady=(10, 0))

        # Poll interval
        pi_frame = tk.Frame(spin_row, bg=self.SURFACE)
        pi_frame.pack(side="left", fill="x", expand=True)
        pi_lbl = tk.Frame(pi_frame, bg=self.SURFACE)
        pi_lbl.pack(anchor="w")
        tk.Label(pi_lbl, text="Poll Interval (s)", bg=self.SURFACE, fg=self.MUTED, font=(self.FONT, 9)).pack(side="left")
        pi_info = tk.Label(pi_lbl, text="?", bg=self.SURFACE, fg=self.ACCENT, font=(self.FONT, 8, "bold"), cursor="hand2")
        pi_info.pack(side="left", padx=(4, 0))
        self._tooltips.append(Tooltip(pi_info, "How often CheevoPresence checks RA for updates.\nDefault: 5 seconds."))
        self.interval_var = tk.IntVar(value=self.cfg.get("interval", 5))
        self.interval_spinbox = self._spinbox(pi_frame, self.interval_var, 5, 120)
        self.interval_spinbox.pack(fill="x", pady=(4, 0), ipady=5)

        # Timeout
        to_frame = tk.Frame(spin_row, bg=self.SURFACE)
        to_frame.pack(side="left", fill="x", expand=True, padx=(12, 0))
        to_lbl = tk.Frame(to_frame, bg=self.SURFACE)
        to_lbl.pack(anchor="w")
        tk.Label(to_lbl, text="Timeout (s)", bg=self.SURFACE, fg=self.MUTED, font=(self.FONT, 9)).pack(side="left")
        to_info = tk.Label(to_lbl, text="?", bg=self.SURFACE, fg=self.ACCENT, font=(self.FONT, 8, "bold"), cursor="hand2")
        to_info.pack(side="left", padx=(4, 0))
        self._tooltips.append(Tooltip(to_info, "Seconds before marking inactive and clearing Discord presence.\nRA refreshes ~every 130s. Set 0 to disable."))
        self.timeout_var = tk.IntVar(value=self.cfg.get("timeout", 130))
        self.timeout_spinbox = self._spinbox(to_frame, self.timeout_var, 0, 3600, 10)
        self.timeout_spinbox.pack(fill="x", pady=(4, 0), ipady=5)

        # Checkboxes
        checks = tk.Frame(right, bg=self.SURFACE)
        checks.pack(fill="x", pady=(10, 0))
        self.profile_btn_var = tk.BooleanVar(value=self.cfg.get("show_profile_button", True))
        self.profile_check = ttk.Checkbutton(checks, text="Show profile button", variable=self.profile_btn_var, style="Panel.TCheckbutton")
        self.profile_check.pack(anchor="w")
        self.gamepage_btn_var = tk.BooleanVar(value=self.cfg.get("show_gamepage_button", True))
        self.gamepage_check = ttk.Checkbutton(checks, text="Show game page button", variable=self.gamepage_btn_var, style="Panel.TCheckbutton")
        self.gamepage_check.pack(anchor="w")
        self.autostart_var = tk.BooleanVar(value=is_autostart_enabled())
        _autostart_label = "Open at login" if sys.platform == "darwin" else "Launch on startup"
        self.autostart_check = ttk.Checkbutton(checks, text=_autostart_label, variable=self.autostart_var, style="Panel.TCheckbutton")
        self.autostart_check.pack(anchor="w")

        # -- Buttons --
        btn_frame = tk.Frame(main, bg=self.BG)
        btn_frame.pack(fill="x", pady=(14, 0))
        self.connection_btn = ttk.Button(btn_frame, width=18, command=self._toggle_connection)
        self.connection_btn.pack(side="left")
        self.lock_hint = tk.Label(btn_frame, text="Disconnect to edit settings.", bg=self.BG, fg="#555", font=(self.FONT, 9))
        self.quit_btn = ttk.Button(btn_frame, text="Exit App", style="Quit.TButton", command=self._exit_app)
        self.quit_btn.pack(side="right")

        # -- Footer links --
        footer = tk.Frame(main, bg=self.BG)
        footer.pack(fill="x", pady=(12, 0))
        footer_links = [
            (f"v{APP_VERSION}", None),
            ("Get API Key", RA_SETTINGS_URL),
            ("RetroAchievements", "https://retroachievements.org"),
            ("GitHub", "https://github.com/denzi-gh/CheevoPresence"),
            ("Ko-fi", "https://ko-fi.com/denzi"),
        ]
        for i, (text, url) in enumerate(footer_links):
            if i > 0:
                tk.Label(footer, text=" \u00b7 ", bg=self.BG, fg="#555", font=(self.FONT, 9)).pack(side="left")
            fg = self.MUTED if url else "#555"
            lbl = tk.Label(footer, text=text, bg=self.BG, fg=fg, font=(self.FONT, 9), cursor="hand2" if url else "")
            lbl.pack(side="left")
            if url:
                lbl.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
                lbl.bind("<Enter>", lambda e, l=lbl: l.configure(fg=self.ACCENT))
                lbl.bind("<Leave>", lambda e, l=lbl: l.configure(fg=self.MUTED))

        # Center window
        self.root.update_idletasks()
        w = max(680, self.root.winfo_reqwidth() + 60)
        h = self.root.winfo_reqheight() + 10
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(w, h)
        self.root.maxsize(w + 200, h)

        self._refresh_connection_button()
        self._poll_status()
        if not self._tk_root:
            self.root.mainloop()

    def _card(self, parent):
        return tk.Frame(parent, bg=self.SURFACE, highlightbackground=self.BORDER, highlightthickness=1, bd=0, padx=14, pady=12)

    def _entry(self, parent, var, show=None):
        return tk.Entry(parent, textvariable=var, show=show, bg=self.ENTRY_BG, fg=self.TEXT,
                        insertbackground=self.TEXT, disabledbackground="#090e14", disabledforeground=self.MUTED,
                        relief="flat", bd=0, highlightthickness=1, highlightbackground=self.BORDER, highlightcolor=self.ACCENT,
                        font=(self.FONT, 10))

    def _spinbox(self, parent, var, from_, to, increment=1):
        return tk.Spinbox(parent, from_=from_, to=to, increment=increment, textvariable=var, width=8,
                          bg=self.ENTRY_BG, fg=self.TEXT, disabledbackground="#090e14", disabledforeground=self.MUTED,
                          buttonbackground=self.SURFACE, relief="flat", bd=0,
                          highlightthickness=1, highlightbackground=self.BORDER, highlightcolor=self.ACCENT,
                          font=(self.FONT, 10))

    def _on_window_close(self):
        self._destroyed = True
        if self.on_close:
            self.on_close()
        self.root.destroy()

    def _queue_ui(self, callback):
        if self._destroyed:
            return False
        try:
            self.root.after(0, callback)
            return True
        except tk.TclError:
            return False

    def _set_inputs_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for w in (self.username_entry, self.apikey_entry, self.interval_spinbox, self.timeout_spinbox,
                  self.profile_check, self.gamepage_check, self.autostart_check):
            w.configure(state=state)
        if enabled:
            self.lock_hint.pack_forget()
        else:
            self.lock_hint.pack(side="left", padx=(12, 0))

    def _refresh_connection_button(self):
        if self._is_connecting:
            self.connection_btn.configure(text="Connecting...", style="Accent.TButton", state="disabled")
        elif self.worker.is_stopping():
            self.connection_btn.configure(text="Stopping...", style="Disconnect.TButton", state="disabled")
        elif self.worker.running:
            self.connection_btn.configure(text="Disconnect", style="Disconnect.TButton", state="normal")
        else:
            self.connection_btn.configure(text="Connect", style="Accent.TButton", state="normal")

    def _poll_status(self):
        if self._destroyed:
            return
        try:
            colors = {"connected": self.GREEN, "connecting": "#fee75c", "disconnected": self.MUTED, "error": self.RED}
            color = colors.get(self.worker.current_status, self.MUTED)
            ra_color = self.GREEN if self.worker.ra_connected else self.RED
            dc_text = self.worker.status_text
            if len(dc_text) > 45:
                dc_text = dc_text[:42] + "..."
            self.status_var.set(dc_text)
            self.status_dot.configure(fg=color)
            self.status_label.configure(fg=color)
            ra_text = self.worker.ra_status_text
            if len(ra_text) > 45:
                ra_text = ra_text[:42] + "..."
            self.ra_status_var.set(ra_text)
            self.ra_status_dot.configure(fg=ra_color)
            self.ra_status_label.configure(fg=ra_color)
            self._refresh_connection_button()
            self._set_inputs_enabled(not self.worker.is_busy() and not self._is_connecting)
            self.root.after(1000, self._poll_status)
        except tk.TclError:
            pass

    def _toggle_connection(self):
        if self._is_connecting or self.worker.is_stopping():
            return

        config_to_save = None
        if not self.worker.running:
            username = self.username_var.get().strip()
            apikey = self.apikey_var.get().strip()
            if not username or not apikey:
                messagebox.showwarning("Missing Info", "Please enter your RA Username and Web API Key.")
                return
            try:
                interval = max(5, self.interval_var.get())
                timeout = max(0, self.timeout_var.get())
            except tk.TclError:
                messagebox.showwarning("Invalid Input", "Please enter valid numbers.")
                return
            config_to_save = {
                **self.cfg,
                "username": username, "apikey": apikey,
                "show_profile_button": self.profile_btn_var.get(),
                "show_gamepage_button": self.gamepage_btn_var.get(),
                "interval": interval, "timeout": timeout,
                "start_on_boot": self.autostart_var.get(),
            }
            self._is_connecting = True
            self._refresh_connection_button()
            self._set_inputs_enabled(False)

        def do_toggle():
            with self._toggle_lock:
                if self.worker.running:
                    self.worker.stop()
                else:
                    self.cfg = normalize_config(config_to_save)
                    try:
                        save_config(self.cfg)
                    except OSError:
                        self._is_connecting = False
                        self._queue_ui(self._refresh_connection_button)
                        self._queue_ui(lambda: self._set_inputs_enabled(True))
                        self._queue_ui(lambda: messagebox.showerror("Save Failed", "Could not write the configuration file."))
                        return

                    autostart_error = set_autostart(self.cfg["start_on_boot"])
                    if autostart_error:
                        self.cfg["start_on_boot"] = is_autostart_enabled()
                        try:
                            save_config(self.cfg)
                        except OSError:
                            pass
                        self._queue_ui(lambda value=self.cfg["start_on_boot"]: self.autostart_var.set(value))
                        self._queue_ui(lambda msg=autostart_error: messagebox.showerror("Startup Setting Failed", msg))

                    try:
                        ra_get_user_summary(self.cfg["username"], self.cfg["apikey"])
                    except requests.RequestException as e:
                        self._is_connecting = False
                        self._queue_ui(self._refresh_connection_button)
                        self._queue_ui(lambda: self._set_inputs_enabled(True))
                        self._queue_ui(lambda msg=format_api_error(e): messagebox.showerror("Connection Failed", msg))
                        return
                    except APIResponseError:
                        self._is_connecting = False
                        self._queue_ui(self._refresh_connection_button)
                        self._queue_ui(lambda: self._set_inputs_enabled(True))
                        self._queue_ui(lambda: messagebox.showerror("Connection Failed", "API error: unexpected response"))
                        return
                    except Exception:
                        self._is_connecting = False
                        self._queue_ui(self._refresh_connection_button)
                        self._queue_ui(lambda: self._set_inputs_enabled(True))
                        self._queue_ui(lambda: messagebox.showerror("Connection Failed", "Unexpected error"))
                        return

                    self.worker.start(self.cfg)
                    self._is_connecting = False
            if not self._destroyed:
                self._queue_ui(self._refresh_connection_button)
                self._queue_ui(lambda: self._set_inputs_enabled(not self.worker.is_busy() and not self._is_connecting))

        threading.Thread(target=do_toggle, daemon=True).start()

    def _exit_app(self):
        self.connection_btn.configure(state="disabled")
        self.quit_btn.configure(state="disabled")
        self._on_window_close()
        if self.on_quit:
            threading.Thread(target=self.on_quit, daemon=True).start()


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
def main():
    # Check for --tray flag (silent start for autostart)
    tray_mode = "--tray" in sys.argv

    if not acquire_single_instance():
        if not tray_mode:
            notify_already_running()
        return

    app = TrayApp()

    if sys.platform == "darwin":
        # macOS: Tk must live on the main thread
        app.run_with_tk(show_settings=not tray_mode)
    elif tray_mode:
        app.run()
    else:
        # Windows/Linux: pystray on main thread, Tk in worker threads
        threading.Thread(target=app._open_initial_settings, daemon=True).start()
        app.run()


if __name__ == "__main__":
    main()
