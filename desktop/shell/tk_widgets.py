"""Reusable Tk widgets used by the settings shell."""

import tkinter as tk


class Tooltip:
    """Show a compact hover tooltip for a Tk widget."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)
        widget.bind("<ButtonPress>", self.hide)

    def show(self, _event=None):
        """Render the tooltip next to the owning widget."""
        if self.tip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() + 10
        y = self.widget.winfo_rooty() - 2
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw,
            text=self.text,
            justify="left",
            bg="#1a1e26",
            fg="#e0e4ec",
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=6,
            font=("Segoe UI", 9),
            wraplength=280,
        ).pack()

    def hide(self, _event=None):
        """Close the tooltip if it is currently visible."""
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None
