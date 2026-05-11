"""Linux-specific adapters for config, autostart, secrets, and tray behavior.

Flatpak awareness
-----------------
When the app runs inside a Flatpak sandbox (FLATPAK_ID is set) several OS
interactions must go through XDG portals instead of direct syscalls:

- Autostart  → org.freedesktop.portal.Background
- Notifications → org.freedesktop.portal.Notification
- Self-update   → disabled (Flatpak manages its own updates)

The Discord IPC socket lives at $XDG_RUNTIME_DIR/discord-ipc-{0..9}.
The manifest must grant --filesystem=xdg-run/discord-ipc-0 (and -1 through
-9) so pypresence can reach it.  The keyring is reached via
--talk-name=org.freedesktop.secrets which is already in the manifest.
"""

import base64
import os
import socket
import subprocess
import sys
import threading

from desktop.core.constants import APP_NAME, APP_VERSION
from desktop.platform.generic import GenericPlatformServices

try:
    import fcntl
except ImportError:  # pragma: no cover - only relevant on non-POSIX platforms
    fcntl = None

FLATPAK_APP_ID = "io.github.denzi_gh.CheevoPresence"
AUTOSTART_DESKTOP_ENTRY = f"{APP_NAME}.desktop"
EXIT_SOCKET_NAME = "exit.sock"
KEYRING_SERVICE = APP_NAME
KEYRING_ACCOUNT = "retroachievements-api-key"
KEYRING_TOKEN_PREFIX = f"keyring://{KEYRING_SERVICE}/"


def is_flatpak():
    """Return True when the app is running inside a Flatpak sandbox."""
    return bool(os.getenv("FLATPAK_ID"))

_single_instance_handle = None
_exit_listener_socket = None
_exit_listener_thread = None
_exit_listener_stop_event = None


def get_config_dir(app_name=APP_NAME):
    """Return the XDG-compliant config directory for this app."""
    xdg_config_home = os.getenv("XDG_CONFIG_HOME")
    if xdg_config_home:
        return os.path.join(xdg_config_home, app_name)
    return os.path.join(os.path.expanduser("~/.config"), app_name)


def get_cache_dir(app_name=APP_NAME):
    """Return the XDG-compliant cache directory used for locks and sockets."""
    xdg_cache_home = os.getenv("XDG_CACHE_HOME")
    if xdg_cache_home:
        return os.path.join(xdg_cache_home, app_name)
    return os.path.join(os.path.expanduser("~/.cache"), app_name)


def get_runtime_dir(app_name=APP_NAME):
    """Return the XDG runtime directory for lock files and sockets."""
    xdg_runtime_dir = os.getenv("XDG_RUNTIME_DIR")
    if xdg_runtime_dir:
        return os.path.join(xdg_runtime_dir, app_name)
    return get_cache_dir(app_name)


def get_autostart_dir():
    """Return the XDG autostart directory."""
    xdg_config_home = os.getenv("XDG_CONFIG_HOME")
    if xdg_config_home:
        return os.path.join(xdg_config_home, "autostart")
    return os.path.join(os.path.expanduser("~/.config"), "autostart")


def get_autostart_desktop_path():
    """Return the full path for the autostart .desktop entry."""
    return os.path.join(get_autostart_dir(), AUTOSTART_DESKTOP_ENTRY)


def get_exit_socket_path():
    """Return the local socket path used for external shutdown requests."""
    return os.path.join(get_runtime_dir(), EXIT_SOCKET_NAME)


def get_exe_path():
    """Return the path to the running executable or script."""
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.abspath(sys.argv[0])


def _build_keyring_token(account=KEYRING_ACCOUNT):
    """Build the config token that points at the stored keyring item."""
    return f"{KEYRING_TOKEN_PREFIX}{account}"


def _parse_keyring_token(value):
    """Extract the keyring account from a stored config token."""
    if not isinstance(value, str) or not value.startswith(KEYRING_TOKEN_PREFIX):
        return None
    account = value[len(KEYRING_TOKEN_PREFIX):].strip()
    return account or None


def _read_keyring_password(service, account):
    """Read the stored API key from the system keyring."""
    try:
        import keyring
        return keyring.get_password(service, account) or ""
    except Exception:
        return ""


def _write_keyring_password(service, account, value):
    """Write the API key to the system keyring."""
    import keyring
    keyring.set_password(service, account, value)


def _delete_keyring_password(service, account):
    """Remove the API key from the system keyring."""
    try:
        import keyring
        keyring.delete_password(service, account)
    except Exception:
        pass


def protect_api_key(value):
    """Store the API key in the system keyring and return a reference token.

    Falls back to base64 encoding when the keyring is unavailable.
    """
    if not value:
        try:
            _delete_keyring_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        except Exception:
            pass
        return ""
    try:
        _write_keyring_password(KEYRING_SERVICE, KEYRING_ACCOUNT, value)
        return _build_keyring_token()
    except Exception:
        return base64.b64encode(value.encode("utf-8")).decode("ascii")


def unprotect_api_key(value):
    """Resolve a stored API key token back into plaintext.

    Handles both keyring tokens and plain base64 fallback values.
    """
    if not isinstance(value, str) or not value:
        return ""
    account = _parse_keyring_token(value)
    if account:
        return _read_keyring_password(KEYRING_SERVICE, account)
    try:
        return base64.b64decode(value).decode("utf-8")
    except (ValueError, TypeError, UnicodeDecodeError):
        return ""


def acquire_single_instance():
    """Acquire a non-blocking advisory file lock so only one instance runs."""
    global _single_instance_handle

    if fcntl is None:
        return True

    try:
        lock_dir = get_runtime_dir()
        os.makedirs(lock_dir, exist_ok=True)
        handle = open(os.path.join(lock_dir, "instance.lock"), "w", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.write(str(os.getpid()))
        handle.flush()
        _single_instance_handle = handle
        return True
    except OSError:
        return False


def _portal_notify(summary, body):
    """Send a notification through the org.freedesktop.portal.Notification D-Bus portal."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib

        notification = GLib.Variant(
            "a{sv}",
            {
                "title": GLib.Variant("s", summary),
                "body": GLib.Variant("s", body),
                "priority": GLib.Variant("s", "normal"),
            },
        )
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Notification",
            "AddNotification",
            GLib.Variant("(sa{sv})", ("already-running", notification.unpack())),
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        return True
    except Exception:
        return False


def notify_already_running():
    """Notify the user when a second instance is launched."""
    message = f"{APP_NAME} is already running in the system tray."
    if is_flatpak():
        if _portal_notify(APP_NAME, message):
            return
    try:
        subprocess.run(
            ["notify-send", APP_NAME, message, "--icon=dialog-information"],
            check=False,
            capture_output=True,
        )
        return
    except OSError:
        pass
    try:
        from tkinter import messagebox
        messagebox.showinfo(APP_NAME, message)
    except Exception:
        pass


def request_running_app_exit():
    """Ask the running tray instance to shut itself down."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(2)
            conn.connect(get_exit_socket_path())
            conn.sendall(b"exit\n")
        return True
    except OSError:
        return False


def start_exit_listener(callback):
    """Listen on a local socket for external shutdown requests."""
    global _exit_listener_socket, _exit_listener_thread, _exit_listener_stop_event

    if not callable(callback):
        return None
    if _exit_listener_thread is not None and _exit_listener_thread.is_alive():
        return _exit_listener_thread

    socket_path = get_exit_socket_path()
    listener = None
    try:
        runtime_dir = os.path.dirname(socket_path)
        os.makedirs(runtime_dir, mode=0o700, exist_ok=True)
        try:
            os.chmod(runtime_dir, 0o700)
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


def _get_launch_command():
    """Return the best launch-at-login command for this runtime."""
    exe_path = get_exe_path()
    if getattr(sys, "frozen", False):
        return [exe_path, "--tray"]
    if exe_path.endswith(".py"):
        return [sys.executable, exe_path, "--tray"]
    return [exe_path, "--tray"]


def _build_desktop_entry(exec_command):
    """Build the XDG .desktop entry content for autostart."""
    exec_line = " ".join(exec_command)
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Exec={exec_line}\n"
        "Icon=cheevopresence\n"
        "Comment=Mirror RetroAchievements activity to Discord\n"
        "Categories=Utility;\n"
        "Terminal=false\n"
        "StartupNotify=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def _portal_set_autostart(enable):
    """Request autostart permission through the org.freedesktop.portal.Background portal.

    The portal presents a system confirmation dialog to the user.  Returns True
    on success, False when the portal call fails or is denied.
    """
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib

        options = GLib.Variant(
            "a{sv}",
            {
                "reason": GLib.Variant(
                    "s",
                    f"Allow {APP_NAME} to run automatically at login.",
                ),
                "autostart": GLib.Variant("b", enable),
                "commandline": GLib.Variant("as", ["flatpak", "run", FLATPAK_APP_ID, "--tray"]),
                "dbus-activatable": GLib.Variant("b", False),
            },
        )
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        # The Background portal requires a parent window handle; pass an empty
        # string which causes the portal to present the dialog without a parent.
        result = bus.call_sync(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Background",
            "RequestBackground",
            GLib.Variant("(sa{sv})", ("", options.unpack())),
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        # result is a (o,) tuple containing the Request object path; a response
        # signal would be needed for the final answer, but for our purposes
        # a successful call (no exception) means the portal accepted the request.
        return result is not None
    except Exception:
        return False


def set_autostart(enable):
    """Enable or disable autostart via the portal (Flatpak) or a .desktop entry."""
    if is_flatpak():
        ok = _portal_set_autostart(enable)
        if not ok:
            return "Could not update autostart: the Background portal request was denied or unavailable."
        return None
    desktop_path = get_autostart_desktop_path()
    try:
        if enable:
            os.makedirs(os.path.dirname(desktop_path), exist_ok=True)
            content = _build_desktop_entry(_get_launch_command())
            with open(desktop_path, "w", encoding="utf-8") as handle:
                handle.write(content)
        else:
            try:
                os.remove(desktop_path)
            except FileNotFoundError:
                pass
        return None
    except OSError as exc:
        return f"Could not update the Linux autostart setting: {exc}"


def is_autostart_enabled():
    """Return whether autostart is currently enabled.

    Inside Flatpak the Background portal does not expose a synchronous query
    API, so we fall back to checking whether the Flatpak autostart override
    file exists in the user data dir.
    """
    if is_flatpak():
        # Flatpak writes an autostart entry to the per-app data dir when the
        # Background portal grants permission.  Check for its presence.
        data_dir = os.getenv("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
        autostart_flag = os.path.join(
            data_dir,
            "flatpak",
            "overrides",
            FLATPAK_APP_ID,
            "autostart",
        )
        return os.path.isfile(autostart_flag)
    return os.path.isfile(get_autostart_desktop_path())


class LinuxPlatformServices(GenericPlatformServices):
    """Bundle the Linux-specific hooks needed by the desktop runtime."""

    startup_toggle_label = "Launch on system startup"
    settings_menu_default = True

    def get_config_dir(self, app_name, runtime_root_dir):
        """Store config in the XDG config directory on Linux."""
        return get_config_dir(app_name)

    def protect_api_key(self, value):
        """Protect the API key using the system keyring or base64 fallback."""
        return protect_api_key(value)

    def unprotect_api_key(self, value):
        """Restore a stored API key back to plain text."""
        return unprotect_api_key(value)

    def acquire_single_instance(self):
        """Acquire the shared Linux single-instance file lock."""
        return acquire_single_instance()

    def notify_already_running(self):
        """Show the duplicate-launch notice via notify-send or tkinter."""
        return notify_already_running()

    def request_running_app_exit(self):
        """Ask the running tray instance to exit via the Unix socket."""
        return request_running_app_exit()

    def start_exit_listener(self, callback):
        """Start listening for external shutdown requests."""
        return start_exit_listener(callback)

    def set_autostart(self, enable):
        """Write or remove the XDG autostart .desktop entry."""
        return set_autostart(enable)

    def is_autostart_enabled(self):
        """Return whether autostart is currently configured."""
        return is_autostart_enabled()

    def supports_self_update(self):
        """Disable self-update inside Flatpak; Flatpak manages its own updates."""
        return False
