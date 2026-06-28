"""Shared Tk settings window used by desktop shell variants."""

import logging
import os
import sys
import threading
import tkinter as tk
import webbrowser
from types import SimpleNamespace
from tkinter import messagebox, ttk

from desktop.core.constants import APP_NAME, APP_VERSION, RA_SETTINGS_URL
from desktop.platform import get_platform_services
from desktop.runtime.log_events import AREA_SETTINGS, log_event
from desktop.runtime.storage import APP_ICON_FILE, APP_ICON_PNG_FILE, get_log_dir
from desktop.shell.settings_presenter import truncate_status_text
from desktop.shell.tk_widgets import Tooltip

logger = logging.getLogger(__name__)


class TkSettingsWindow:
    """Render the shared settings window and drive connect/disconnect actions."""

    BG = "#0b0d12"
    SURFACE = "#131821"
    BORDER = "#2a313d"
    TEXT = "#f3f7ff"
    MUTED = "#a4afbf"
    ENTRY_BG = "#0d1219"
    ACCENT = "#f0b14a"
    LINK = "#57a6ff"
    GREEN = "#57f287"
    RED = "#ed4245"
    FONT = "Segoe UI"

    def __init__(self, controller, on_close=None, on_quit=None, on_ready=None):
        """Build the settings window and start its status refresh loop."""
        self.controller = controller
        self.worker = controller.worker
        self.platform = controller.platform
        self.on_close = on_close
        self.on_quit = on_quit
        self.on_ready = on_ready
        self._destroyed = False
        self._is_connecting = False
        self._is_installing_update = False
        self._tooltips = []
        self._remote_error_shown = False
        self._use_custom_mac_chrome = sys.platform == "darwin"
        self._mac_drag_state = None
        self._mac_fullscreen = False
        self._mac_restore_geometry = None
        self.cfg = self.controller.load_config()

        self.root = tk.Tk()
        self._configure_root()
        if not self._poll_controller_state():
            return
        self._build_styles()
        self._build_layout()
        self._center_window()
        self.root.after(50, self.focus_window)
        self._refresh_connection_button()
        self._refresh_update_notice()
        self._poll_status()
        if self.on_ready:
            self.on_ready(self)
        self.root.mainloop()

    def focus_window(self):
        """Bring the existing window to the foreground."""
        if self._destroyed:
            return
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    def _configure_root(self):
        """Configure the top-level window and its icon behavior."""
        self.root.title(f"{APP_NAME}")
        self.root.resizable(False, False)
        self.root.configure(bg=self.BORDER if self._use_custom_mac_chrome else self.BG)
        if self._use_custom_mac_chrome:
            self.root.overrideredirect(True)
            self.root.bind("<Map>", self._on_mac_window_map)
            self.root.configure(menu=tk.Menu(self.root))
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self._set_window_icon()

    def _set_window_icon(self):
        """Set the window/taskbar icon using the format each platform supports."""
        # Windows renders the multi-resolution .ico via iconbitmap. On X11/Tk,
        # iconbitmap expects an XBM bitmap and silently rejects .ico, so the
        # window keeps the default Tk icon; iconphoto with a PNG is required.
        if sys.platform.startswith("win") and os.path.exists(APP_ICON_FILE):
            try:
                self.root.iconbitmap(APP_ICON_FILE)
                return
            except Exception:
                pass
        if os.path.exists(APP_ICON_PNG_FILE):
            try:
                # Keep a reference so the image is not garbage-collected, which
                # would blank the icon.
                self._window_icon = tk.PhotoImage(file=APP_ICON_PNG_FILE)
                self.root.iconphoto(True, self._window_icon)
            except Exception:
                pass

    def _build_styles(self):
        """Register the ttk styles used by the settings controls."""
        style = ttk.Style(self.root)
        style.theme_use("clam")
        for name, bg, fg, active_bg in [
            ("Accent.TButton", self.ACCENT, "#081018", "#ffc86a"),
            ("Disconnect.TButton", "#2a313d", self.TEXT, "#394355"),
            ("Quit.TButton", self.RED, "white", "#c03537"),
        ]:
            style.configure(
                name,
                background=bg,
                foreground=fg,
                font=(self.FONT, 10, "bold"),
                padding=(14, 8),
                borderwidth=0,
            )
            style.map(name, background=[("active", active_bg), ("disabled", "#333")])
        style.configure(
            "Panel.TCheckbutton",
            background=self.SURFACE,
            foreground=self.TEXT,
            font=(self.FONT, 10),
        )
        style.map(
            "Panel.TCheckbutton",
            background=[("active", self.SURFACE)],
            foreground=[("disabled", self.MUTED)],
        )

    def _build_layout(self):
        """Assemble the full settings window layout."""
        container = tk.Frame(
            self.root,
            bg=self.BORDER if self._use_custom_mac_chrome else self.BG,
            padx=1 if self._use_custom_mac_chrome else 0,
            pady=1 if self._use_custom_mac_chrome else 0,
        )
        container.pack(fill="both", expand=True)

        self.window_body = tk.Frame(container, bg=self.BG)
        self.window_body.pack(fill="both", expand=True)

        if self._use_custom_mac_chrome:
            self._build_mac_chrome(self.window_body)

        self.main = tk.Frame(self.window_body, bg=self.BG, padx=20, pady=16)
        self.main.pack(fill="both", expand=True)

        tk.Label(
            self.main,
            text=APP_NAME,
            bg=self.BG,
            fg=self.ACCENT,
            font=(self.FONT, 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            self.main,
            text="Mirror your RetroAchievements activity to Discord.",
            bg=self.BG,
            fg=self.MUTED,
            font=(self.FONT, 9),
        ).pack(anchor="w", pady=(2, 12))

        self._build_status_section()
        self._build_content_columns()
        self._build_buttons()
        self._build_footer()

    def _build_mac_chrome(self, parent):
        """Build the custom macOS title bar shown inside the settings window."""
        chrome = tk.Frame(parent, bg=self.SURFACE, height=34)
        chrome.pack(fill="x")
        chrome.pack_propagate(False)

        controls = tk.Frame(chrome, bg=self.SURFACE)
        controls.pack(side="left", padx=12, pady=10)

        self._build_mac_control(
            controls,
            fill="#ff5f57",
            hover_fill="#ff857f",
            command=self._on_window_close,
        )
        self._build_mac_control(
            controls,
            fill="#ffbd2e",
            hover_fill="#ffd261",
            command=self._minimize_window,
        )
        self._build_mac_control(
            controls,
            fill="#28c840",
            hover_fill="#28c840",
            command=None,
        )

        for widget in (chrome,):
            widget.bind("<ButtonPress-1>", self._begin_mac_drag)
            widget.bind("<B1-Motion>", self._perform_mac_drag)
            widget.bind("<ButtonRelease-1>", self._end_mac_drag)

    def _build_mac_control(self, parent, fill, hover_fill, command):
        """Render one macOS-style traffic light button in the custom title bar."""
        button = tk.Canvas(
            parent,
            width=14,
            height=14,
            bg=self.SURFACE,
            highlightthickness=0,
            bd=0,
            cursor="arrow",
        )
        button.pack(side="left", padx=(0, 8))
        oval = button.create_oval(1, 1, 13, 13, fill=fill, outline=fill)
        if command is not None:
            button.bind(
                "<Enter>",
                lambda _event: button.itemconfigure(oval, fill=hover_fill, outline=hover_fill),
            )
            button.bind(
                "<Leave>",
                lambda _event: button.itemconfigure(oval, fill=fill, outline=fill),
            )
            button.bind("<Button-1>", lambda _event: command())

    def _begin_mac_drag(self, event):
        """Capture the initial pointer position before dragging the custom title bar."""
        if self._mac_fullscreen:
            return
        self._mac_drag_state = (
            event.x_root,
            event.y_root,
            self.root.winfo_x(),
            self.root.winfo_y(),
        )

    def _perform_mac_drag(self, event):
        """Move the borderless window while dragging the custom title bar."""
        if self._mac_drag_state is None or self._mac_fullscreen:
            return
        start_x, start_y, window_x, window_y = self._mac_drag_state
        self.root.geometry(
            f"+{window_x + (event.x_root - start_x)}+{window_y + (event.y_root - start_y)}"
        )

    def _end_mac_drag(self, _event=None):
        """Release the custom title bar drag state."""
        self._mac_drag_state = None

    def _on_mac_window_map(self, _event=None):
        """Reapply the borderless style after the window is restored on macOS."""
        if not self._use_custom_mac_chrome or self._destroyed:
            return
        self.root.after(10, self._restore_mac_chrome)

    def _restore_mac_chrome(self):
        """Restore the custom macOS chrome after a minimize/restore cycle."""
        if self._destroyed or not self._use_custom_mac_chrome:
            return
        try:
            self.root.overrideredirect(True)
        except tk.TclError:
            pass

    def _minimize_window(self):
        """Minimize the custom-chrome macOS window."""
        if self._destroyed:
            return
        try:
            self.root.overrideredirect(False)
            self.root.iconify()
        except tk.TclError:
            pass

    def _toggle_fullscreen(self):
        """Toggle a fullscreen-style presentation for the borderless macOS window."""
        if self._destroyed:
            return
        try:
            if self._mac_fullscreen:
                if self._mac_restore_geometry:
                    self.root.geometry(self._mac_restore_geometry)
                self._mac_fullscreen = False
                return
            self._mac_restore_geometry = self.root.geometry()
            self.root.geometry(
                f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0"
            )
            self._mac_fullscreen = True
        except tk.TclError:
            pass

    def _build_status_section(self):
        """Build the Discord and RetroAchievements status summary row."""
        worker_state = self._worker_state()
        status_frame = self._card(self.main)
        status_frame.pack(fill="x")
        status_row = tk.Frame(status_frame, bg=self.SURFACE)
        status_row.pack(fill="x")

        dc_frame = tk.Frame(status_row, bg=self.SURFACE)
        dc_frame.pack(side="left", fill="x", expand=True)
        tk.Label(
            dc_frame,
            text="Discord",
            bg=self.SURFACE,
            fg=self.MUTED,
            font=(self.FONT, 9, "bold"),
        ).pack(anchor="w")
        dc_val = tk.Frame(dc_frame, bg=self.SURFACE)
        dc_val.pack(anchor="w", pady=(4, 0))
        self.status_dot = tk.Label(
            dc_val,
            text="\u25cf",
            bg=self.SURFACE,
            fg=self.MUTED,
            font=(self.FONT, 10),
        )
        self.status_dot.pack(side="left")
        self.status_var = tk.StringVar(value=worker_state.status_text)
        self.status_label = tk.Label(
            dc_val,
            textvariable=self.status_var,
            bg=self.SURFACE,
            fg=self.TEXT,
            font=(self.FONT, 10, "bold"),
        )
        self.status_label.pack(side="left", padx=(4, 0))

        ra_frame = tk.Frame(status_row, bg=self.SURFACE)
        ra_frame.pack(side="left", fill="x", expand=True, padx=(16, 0))
        tk.Label(
            ra_frame,
            text="RetroAchievements",
            bg=self.SURFACE,
            fg=self.MUTED,
            font=(self.FONT, 9, "bold"),
        ).pack(anchor="w")
        ra_val = tk.Frame(ra_frame, bg=self.SURFACE)
        ra_val.pack(anchor="w", pady=(4, 0))
        self.ra_status_dot = tk.Label(
            ra_val,
            text="\u25cf",
            bg=self.SURFACE,
            fg=self.MUTED,
            font=(self.FONT, 10),
        )
        self.ra_status_dot.pack(side="left")
        self.ra_status_var = tk.StringVar(value=worker_state.ra_status_text)
        self.ra_status_label = tk.Label(
            ra_val,
            textvariable=self.ra_status_var,
            bg=self.SURFACE,
            fg=self.TEXT,
            font=(self.FONT, 10, "bold"),
        )
        self.ra_status_label.pack(side="left", padx=(4, 0))

    def _build_content_columns(self):
        """Build the account and behavior panels."""
        cols = tk.Frame(self.main, bg=self.BG)
        cols.pack(fill="x", pady=(12, 0))
        self._build_account_panel(cols)
        self._build_behavior_panel(cols)

    def _build_account_panel(self, parent):
        """Build the account credential inputs."""
        left = self._card(parent)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(
            left,
            text="Account",
            bg=self.SURFACE,
            fg=self.TEXT,
            font=(self.FONT, 11, "bold"),
        ).pack(anchor="w")

        tk.Label(
            left,
            text="RA Username",
            bg=self.SURFACE,
            fg=self.MUTED,
            font=(self.FONT, 9),
        ).pack(anchor="w", pady=(10, 0))
        self.username_var = tk.StringVar(value=self.cfg["username"])
        self.username_entry = self._entry(left, self.username_var)
        self.username_entry.pack(fill="x", pady=(4, 0), ipady=6)

        tk.Label(
            left,
            text="Web API Key",
            bg=self.SURFACE,
            fg=self.MUTED,
            font=(self.FONT, 9),
        ).pack(anchor="w", pady=(10, 0))
        self.apikey_var = tk.StringVar(value=self.cfg["apikey"])
        self.apikey_entry = self._entry(left, self.apikey_var, show="*")
        self.apikey_entry.pack(fill="x", pady=(4, 0), ipady=6)

    def _build_behavior_panel(self, parent):
        """Build the behavior controls and startup options."""
        right = self._card(parent)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        tk.Label(
            right,
            text="Behavior",
            bg=self.SURFACE,
            fg=self.TEXT,
            font=(self.FONT, 11, "bold"),
        ).pack(anchor="w")

        spin_row = tk.Frame(right, bg=self.SURFACE)
        spin_row.pack(fill="x", pady=(10, 0))

        pi_frame = tk.Frame(spin_row, bg=self.SURFACE)
        pi_frame.pack(side="left", fill="x", expand=True)
        pi_lbl = tk.Frame(pi_frame, bg=self.SURFACE)
        pi_lbl.pack(anchor="w")
        tk.Label(
            pi_lbl,
            text="Poll Interval (s)",
            bg=self.SURFACE,
            fg=self.MUTED,
            font=(self.FONT, 9),
        ).pack(side="left")
        pi_info = tk.Label(
            pi_lbl,
            text="?",
            bg=self.SURFACE,
            fg=self.ACCENT,
            font=(self.FONT, 8, "bold"),
            cursor="hand2",
        )
        pi_info.pack(side="left", padx=(4, 0))
        self._tooltips.append(
            Tooltip(
                pi_info,
                "How often CheevoPresence checks RA for updates.\nDefault: 5 seconds.",
            )
        )
        self.interval_var = tk.IntVar(value=self.cfg.get("interval", 5))
        self.interval_spinbox = self._spinbox(pi_frame, self.interval_var, 5, 120)
        self.interval_spinbox.pack(fill="x", pady=(4, 0), ipady=5)

        to_frame = tk.Frame(spin_row, bg=self.SURFACE)
        to_frame.pack(side="left", fill="x", expand=True, padx=(12, 0))
        to_lbl = tk.Frame(to_frame, bg=self.SURFACE)
        to_lbl.pack(anchor="w")
        tk.Label(
            to_lbl,
            text="Timeout (s)",
            bg=self.SURFACE,
            fg=self.MUTED,
            font=(self.FONT, 9),
        ).pack(side="left")
        to_info = tk.Label(
            to_lbl,
            text="?",
            bg=self.SURFACE,
            fg=self.ACCENT,
            font=(self.FONT, 8, "bold"),
            cursor="hand2",
        )
        to_info.pack(side="left", padx=(4, 0))
        self._tooltips.append(
            Tooltip(
                to_info,
                "Seconds before marking inactive and clearing Discord presence.\nRA refreshes ~every 130s. Set 0 to disable.",
            )
        )
        self.timeout_var = tk.IntVar(value=self.cfg.get("timeout", 130))
        self.timeout_spinbox = self._spinbox(to_frame, self.timeout_var, 0, 3600, 10)
        self.timeout_spinbox.pack(fill="x", pady=(4, 0), ipady=5)

        checks = tk.Frame(right, bg=self.SURFACE)
        checks.pack(fill="x", pady=(10, 0))
        self.profile_btn_var = tk.BooleanVar(
            value=self.cfg.get("show_profile_button", True)
        )
        self.profile_check = ttk.Checkbutton(
            checks,
            text="Show profile button",
            variable=self.profile_btn_var,
            style="Panel.TCheckbutton",
        )
        self.profile_check.pack(anchor="w")
        self.gamepage_btn_var = tk.BooleanVar(
            value=self.cfg.get("show_gamepage_button", True)
        )
        self.gamepage_check = ttk.Checkbutton(
            checks,
            text="Show game page button",
            variable=self.gamepage_btn_var,
            style="Panel.TCheckbutton",
        )
        self.gamepage_check.pack(anchor="w")
        self.achievement_progress_var = tk.BooleanVar(
            value=self.cfg.get("show_achievement_progress", True)
        )
        self.achievement_progress_check = ttk.Checkbutton(
            checks,
            text="Show achievement counter",
            variable=self.achievement_progress_var,
            style="Panel.TCheckbutton",
        )
        self.achievement_progress_check.pack(anchor="w")
        self.developer_titles_var = tk.BooleanVar(
            value=self.cfg.get("use_retroachievements_developer_titles", True)
        )
        self.developer_titles_check = ttk.Checkbutton(
            checks,
            text="Use RetroAchievements developer titles",
            variable=self.developer_titles_var,
            style="Panel.TCheckbutton",
        )
        self.developer_titles_check.pack(anchor="w")
        self.autostart_var = tk.BooleanVar(value=self.platform.is_autostart_enabled())
        self.autostart_check = ttk.Checkbutton(
            checks,
            text=self.platform.startup_toggle_label,
            variable=self.autostart_var,
            style="Panel.TCheckbutton",
        )
        self.autostart_check.pack(anchor="w")

    def _build_buttons(self):
        """Build the bottom action row."""
        btn_frame = tk.Frame(self.main, bg=self.BG)
        btn_frame.pack(fill="x", pady=(14, 0))
        self.connection_btn = ttk.Button(
            btn_frame,
            width=18,
            command=self._toggle_connection,
        )
        self.connection_btn.pack(side="left")
        self.lock_hint = tk.Label(
            btn_frame,
            text="Disconnect to edit settings.",
            bg=self.BG,
            fg="#555",
            font=(self.FONT, 9),
        )
        self.quit_btn = ttk.Button(
            btn_frame,
            text="Exit App",
            style="Quit.TButton",
            command=self._exit_app,
        )
        self.quit_btn.pack(side="right")

    def _build_footer(self):
        """Build the footer link row."""
        footer = tk.Frame(self.main, bg=self.BG)
        footer.pack(fill="x", pady=(12, 0))
        version_group = tk.Frame(footer, bg=self.BG)
        version_group.pack(side="left")

        self.version_label = tk.Label(
            version_group,
            text=f"v{APP_VERSION}",
            bg=self.BG,
            fg="#555",
            font=(self.FONT, 9),
        )
        self.version_label.pack(side="left")

        self.update_label = tk.Label(
            version_group,
            text=" Update available",
            bg=self.BG,
            fg=self.LINK,
            font=(self.FONT, 9, "bold"),
            cursor="hand2",
        )

        footer_links = [
            ("Get API Key", lambda: webbrowser.open(RA_SETTINGS_URL)),
            ("RetroAchievements", lambda: webbrowser.open("https://retroachievements.org")),
            ("GitHub", lambda: webbrowser.open("https://github.com/denzi-gh/CheevoPresence")),
            ("Ko-fi", lambda: webbrowser.open("https://ko-fi.com/denzi")),
            ("Open Logs", self._open_log_folder),
        ]
        for text, action in footer_links:
            tk.Label(
                footer,
                text=" \u00b7 ",
                bg=self.BG,
                fg="#555",
                font=(self.FONT, 9),
            ).pack(side="left")
            label = tk.Label(
                footer,
                text=text,
                bg=self.BG,
                fg=self.MUTED,
                font=(self.FONT, 9),
                cursor="arrow",
            )
            label.pack(side="left")
            label.bind("<Button-1>", lambda e, a=action: a())
            label.bind("<Enter>", lambda e, l=label: l.configure(fg=self.ACCENT))
            label.bind("<Leave>", lambda e, l=label: l.configure(fg=self.MUTED))

    def _open_log_folder(self):
        """Open the runtime log folder in the OS file manager."""
        # The settings window always runs on the local machine, so resolve the
        # real platform services here rather than the IPC platform proxy.
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
        if not success:
            messagebox.showinfo("Logs", f"Log folder:\n{log_dir}")

    def _center_window(self):
        """Center the finished window and lock in its minimum size."""
        self.root.update_idletasks()
        width = max(680, self.root.winfo_reqwidth() + 60)
        height = self.root.winfo_reqheight() + 10
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(width, height)
        if self._use_custom_mac_chrome:
            self.root.maxsize(self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        else:
            self.root.maxsize(width + 200, height)

    def _card(self, parent):
        """Create a bordered panel container for grouped settings."""
        return tk.Frame(
            parent,
            bg=self.SURFACE,
            highlightbackground=self.BORDER,
            highlightthickness=1,
            bd=0,
            padx=14,
            pady=12,
        )

    def _entry(self, parent, var, show=None):
        """Build a themed entry field bound to a Tk variable."""
        return tk.Entry(
            parent,
            textvariable=var,
            show=show,
            bg=self.ENTRY_BG,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            disabledbackground="#090e14",
            disabledforeground=self.MUTED,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.BORDER,
            highlightcolor=self.ACCENT,
            font=(self.FONT, 10),
        )

    def _spinbox(self, parent, var, from_, to, increment=1):
        """Build a themed numeric spinbox for integer settings."""
        return tk.Spinbox(
            parent,
            from_=from_,
            to=to,
            increment=increment,
            textvariable=var,
            width=8,
            bg=self.ENTRY_BG,
            fg=self.TEXT,
            disabledbackground="#090e14",
            disabledforeground=self.MUTED,
            buttonbackground=self.SURFACE,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.BORDER,
            highlightcolor=self.ACCENT,
            font=(self.FONT, 10),
        )

    def _poll_controller_state(self):
        """Refresh controller-owned runtime state when using a remote bridge."""
        poll_state = getattr(self.controller, "poll_runtime_state", None)
        if not callable(poll_state):
            return True
        try:
            poll_state()
            return True
        except Exception:
            if not self._remote_error_shown:
                self._remote_error_shown = True
                try:
                    messagebox.showerror(
                        "Connection Lost",
                        "The CheevoPresence background app is no longer available.",
                    )
                except Exception:
                    pass
            try:
                self.root.destroy()
            except Exception:
                pass
            self._destroyed = True
            return False

    def _worker_state(self):
        """Return a snapshot-like worker state for UI decisions."""
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
        )

    def _on_window_close(self):
        """Dispose the window and notify the tray host that it closed."""
        if self._destroyed:
            return
        self._destroyed = True
        if self.on_close:
            self.on_close()
        self.root.destroy()

    def request_close(self):
        """Ask the Tk thread to close the window."""
        if self._destroyed:
            return False
        try:
            self.root.after(0, self._on_window_close)
            return True
        except tk.TclError:
            return False

    def _queue_ui(self, callback):
        """Queue a callback on the Tk thread if the window still exists."""
        if self._destroyed:
            return False
        try:
            self.root.after(0, callback)
            return True
        except tk.TclError:
            return False

    def _set_inputs_enabled(self, enabled):
        """Lock or unlock editable controls based on runtime state."""
        state = "normal" if enabled else "disabled"
        for widget in (
            self.username_entry,
            self.apikey_entry,
            self.interval_spinbox,
            self.timeout_spinbox,
            self.profile_check,
            self.gamepage_check,
            self.achievement_progress_check,
            self.developer_titles_check,
            self.autostart_check,
        ):
            widget.configure(state=state)
        if enabled:
            self.lock_hint.pack_forget()
        else:
            self.lock_hint.pack(side="left", padx=(12, 0))

    def _refresh_connection_button(self):
        """Refresh the connect button label and style from worker state."""
        worker_state = self._worker_state()
        if self._is_connecting:
            self.connection_btn.configure(
                text="Connecting...",
                style="Accent.TButton",
                state="disabled",
            )
        elif worker_state.is_stopping:
            self.connection_btn.configure(
                text="Stopping...",
                style="Disconnect.TButton",
                state="disabled",
            )
        elif worker_state.running:
            self.connection_btn.configure(
                text="Disconnect",
                style="Disconnect.TButton",
                state="normal",
            )
        else:
            self.connection_btn.configure(
                text="Connect",
                style="Accent.TButton",
                state="normal",
            )

    def _poll_status(self):
        """Mirror worker status into the settings window every second."""
        if self._destroyed:
            return
        try:
            if not self._poll_controller_state():
                return
            worker_state = self._worker_state()
            colors = {
                "connected": self.GREEN,
                "connecting": "#fee75c",
                "disconnected": self.MUTED,
                "error": self.RED,
            }
            color = colors.get(worker_state.current_status, self.MUTED)
            ra_color = self.GREEN if worker_state.ra_connected else self.RED
            discord_text = truncate_status_text(worker_state.status_text)
            self.status_var.set(discord_text)
            self.status_dot.configure(fg=color)
            self.status_label.configure(fg=color)
            ra_text = truncate_status_text(worker_state.ra_status_text)
            self.ra_status_var.set(ra_text)
            self.ra_status_dot.configure(fg=ra_color)
            self.ra_status_label.configure(fg=ra_color)
            self._refresh_connection_button()
            self._refresh_update_notice()
            worker_state = self._worker_state()
            self._set_inputs_enabled(not worker_state.is_busy and not self._is_connecting)
            self.root.after(1000, self._poll_status)
        except tk.TclError:
            pass

    def _refresh_update_notice(self):
        """Refresh the footer version label based on the cached update state."""
        if self._is_installing_update:
            return
        update_status = self.controller.get_update_status()
        if update_status.available:
            can_self_install = update_status.can_self_install
            handler = self._on_update_click if can_self_install else self._on_manual_update_click
            notice_text = " Update available" if can_self_install else " New version available"
            self.version_label.configure(
                text=f"v{APP_VERSION}",
                fg=self.LINK,
                cursor="arrow",
            )
            self.version_label.bind("<Button-1>", handler)
            self.version_label.bind("<Enter>", lambda e: self.version_label.configure(fg="#7ab9ff"))
            self.version_label.bind("<Leave>", lambda e: self.version_label.configure(fg=self.LINK))
            if not self.update_label.winfo_ismapped():
                self.update_label.pack(side="left")
            self.update_label.configure(text=notice_text, cursor="arrow")
            self.update_label.bind("<Button-1>", handler)
            self.update_label.bind("<Enter>", lambda e: self.update_label.configure(fg="#7ab9ff"))
            self.update_label.bind("<Leave>", lambda e: self.update_label.configure(fg=self.LINK))
        else:
            self.version_label.configure(
                text=f"v{APP_VERSION}",
                fg="#555",
                cursor="",
            )
            self.version_label.unbind("<Button-1>")
            self.version_label.unbind("<Enter>")
            self.version_label.unbind("<Leave>")
            if self.update_label.winfo_ismapped():
                self.update_label.pack_forget()

    def _on_manual_update_click(self, _event=None):
        """Open the GitHub releases page for updates that cannot self-install."""
        webbrowser.open(self.controller.get_update_status().release_url)

    def _on_update_click(self, _event=None):
        """Download and stage the latest packaged release for automatic restart."""
        if self._is_installing_update:
            return
        if not self.controller.get_update_status().can_self_install:
            self._on_manual_update_click()
            return
        self._is_installing_update = True
        self.version_label.configure(fg=self.LINK, cursor="")
        if not self.update_label.winfo_ismapped():
            self.update_label.pack(side="left")
        self.update_label.configure(text=" Downloading update...", fg=self.LINK, cursor="")

        def do_install():
            result = self.controller.install_update()
            if result.success:
                self._queue_ui(lambda: self.update_label.configure(text=" Restarting..."))
                self._queue_ui(self._exit_app)
                return

            self._is_installing_update = False
            self._queue_ui(self._refresh_update_notice)
            self._queue_ui(
                lambda title=result.error_title, message=result.error_message: messagebox.showerror(
                    title,
                    message,
                )
            )

        threading.Thread(target=do_install, daemon=True).start()

    def _toggle_connection(self):
        """Start or stop monitoring after validating the current form data."""
        worker_state = self._worker_state()
        if self._is_connecting or worker_state.is_stopping:
            return

        config_to_save = None
        if not worker_state.running:
            username = self.username_var.get().strip()
            apikey = self.apikey_var.get().strip()
            if not username or not apikey:
                messagebox.showwarning(
                    "Missing Info",
                    "Please enter your RA Username and Web API Key.",
                )
                return
            try:
                interval = max(5, self.interval_var.get())
                timeout = max(0, self.timeout_var.get())
            except tk.TclError:
                messagebox.showwarning("Invalid Input", "Please enter valid numbers.")
                return
            config_to_save = {
                **self.cfg,
                "username": username,
                "apikey": apikey,
                "show_profile_button": self.profile_btn_var.get(),
                "show_gamepage_button": self.gamepage_btn_var.get(),
                "show_achievement_progress": self.achievement_progress_var.get(),
                "use_retroachievements_developer_titles": self.developer_titles_var.get(),
                "interval": interval,
                "timeout": timeout,
                "start_on_boot": self.autostart_var.get(),
            }
            self._is_connecting = True
            self._refresh_connection_button()
            self._set_inputs_enabled(False)

        def do_toggle():
            if self._worker_state().running:
                self.controller.disconnect()
            else:
                result = self.controller.connect(config_to_save)
                self.cfg = result.config or self.cfg
                self._is_connecting = False
                if result.config is not None:
                    self._queue_ui(
                        lambda value=result.config["start_on_boot"]: self.autostart_var.set(
                            value
                        )
                    )
                if result.warning_message:
                    self._queue_ui(
                        lambda title=result.warning_title, message=result.warning_message: messagebox.showerror(
                            title,
                            message,
                        )
                    )
                if not result.success:
                    self._queue_ui(self._refresh_connection_button)
                    self._queue_ui(lambda: self._set_inputs_enabled(True))
                    self._queue_ui(
                        lambda title=result.error_title, message=result.error_message: messagebox.showerror(
                            title,
                            message,
                        )
                    )
                    return
            if not self._destroyed:
                self._queue_ui(self._refresh_connection_button)
                self._queue_ui(
                    lambda: self._set_inputs_enabled(
                        not self._worker_state().is_busy and not self._is_connecting
                    )
                )

        threading.Thread(target=do_toggle, daemon=True).start()

    def _exit_app(self):
        """Close the window and delegate the full app shutdown if requested."""
        self.connection_btn.configure(state="disabled")
        self.quit_btn.configure(state="disabled")
        self._on_window_close()
        if self.on_quit:
            threading.Thread(target=self.on_quit).start()
