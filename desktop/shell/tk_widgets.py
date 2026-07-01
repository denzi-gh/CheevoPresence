"""Reusable Tk widgets used by the settings shell."""

import tkinter as tk
import tkinter.font as tkfont


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
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


ROLE_BADGE_STYLES = {
    "junior_developer": {
        "accent": "#F0B450",
        "fill": "#2F2823",
        "border": "#69512B",
        "icon": "code",
    },
    "developer": {
        "accent": "#5FD07F",
        "fill": "#1A3027",
        "border": "#3B7048",
        "icon": "code",
    },
    "code_reviewer": {
        "accent": "#B0A0F0",
        "fill": "#2B2740",
        "border": "#5D528F",
        "icon": "search",
    },
    "event_manager": {
        "accent": "#D98FE6",
        "fill": "#30243A",
        "border": "#7A4A85",
        "icon": "star",
    },
    "artist": {
        "accent": "#F28D4F",
        "fill": "#34281F",
        "border": "#805238",
        "icon": "palette",
    },
    "play_tester": {
        "accent": "#F2D35C",
        "fill": "#332F1E",
        "border": "#7D6E35",
        "icon": "controller",
    },
    "writer": {
        "accent": "#7DC5FF",
        "fill": "#1D2D3A",
        "border": "#4B7598",
        "icon": "pen",
    },
    "moderator": {
        "accent": "#6FCFE2",
        "fill": "#1C323B",
        "border": "#457380",
        "icon": "shield",
    },
    "admin": {
        "accent": "#EF6461",
        "fill": "#351F23",
        "border": "#874244",
    },
}
DEFAULT_ROLE_BADGE_STYLE = {
    key: value for key, value in ROLE_BADGE_STYLES["junior_developer"].items() if key != "icon"
}


def role_badge_style(tier):
    return ROLE_BADGE_STYLES.get(tier, DEFAULT_ROLE_BADGE_STYLE)


class RoleBadge(tk.Canvas):

    ICON_SIZE = 11
    PADDING_LEFT = 8
    PADDING_RIGHT = 9
    PADDING_Y = 3
    GAP = 6
    HEIGHT = 22

    def __init__(self, parent, font_family="Segoe UI", **kwargs):
        super().__init__(
            parent,
            bg=kwargs.pop("bg", "#131821"),
            highlightthickness=0,
            bd=0,
            height=self.HEIGHT,
            **kwargs,
        )
        self.badge_font = tkfont.Font(family=font_family, size=11, weight="bold")
        self.label = ""
        self.tier = ""

    def set_role(self, label, tier):
        self.label = str(label or "")
        self.tier = str(tier or "")
        self.delete("all")
        if not self.label:
            self.configure(width=1, height=1)
            return

        style = role_badge_style(self.tier)
        text_width = self.badge_font.measure(self.label)
        icon = style.get("icon")
        icon_width = self.ICON_SIZE + self.GAP if icon else 0
        width = (
            self.PADDING_LEFT
            + icon_width
            + text_width
            + self.PADDING_RIGHT
            + 2
        )
        height = self.HEIGHT
        self.configure(width=width, height=height)
        self._rounded_rect(1, 1, width - 1, height - 1, height // 2, style["fill"], style["border"])

        icon_x = self.PADDING_LEFT
        if icon:
            icon_y = (height - self.ICON_SIZE) / 2
            if icon == "shield":
                self._draw_shield(icon_x, icon_y, style["accent"])
            elif icon == "search":
                self._draw_search(icon_x, icon_y, style["accent"])
            elif icon == "star":
                self._draw_star(icon_x, icon_y, style["accent"])
            elif icon == "palette":
                self._draw_palette(icon_x, icon_y, style["accent"])
            elif icon == "controller":
                self._draw_controller(icon_x, icon_y, style["accent"])
            elif icon == "pen":
                self._draw_pen(icon_x, icon_y, style["accent"])
            else:
                self._draw_code(icon_x, icon_y, style["accent"])

        self.create_text(
            icon_x + icon_width,
            height / 2,
            anchor="w",
            text=self.label,
            fill=style["accent"],
            font=self.badge_font,
        )

    def _rounded_rect(self, x1, y1, x2, y2, radius, fill, outline):
        self.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=fill, outline=fill)
        self.create_rectangle(x1, y1 + radius, x2, y2 - radius, fill=fill, outline=fill)
        self.create_oval(x1, y1, x1 + radius * 2, y1 + radius * 2, fill=fill, outline=fill)
        self.create_oval(x2 - radius * 2, y1, x2, y1 + radius * 2, fill=fill, outline=fill)
        self.create_oval(x1, y2 - radius * 2, x1 + radius * 2, y2, fill=fill, outline=fill)
        self.create_oval(x2 - radius * 2, y2 - radius * 2, x2, y2, fill=fill, outline=fill)
        self.create_line(x1 + radius, y1, x2 - radius, y1, fill=outline)
        self.create_line(x1 + radius, y2, x2 - radius, y2, fill=outline)
        self.create_arc(x1, y1, x1 + radius * 2, y1 + radius * 2, start=90, extent=90, outline=outline)
        self.create_arc(x2 - radius * 2, y1, x2, y1 + radius * 2, start=0, extent=90, outline=outline)
        self.create_arc(x1, y2 - radius * 2, x1 + radius * 2, y2, start=180, extent=90, outline=outline)
        self.create_arc(x2 - radius * 2, y2 - radius * 2, x2, y2, start=270, extent=90, outline=outline)

    def _scale_points(self, points, x, y):
        scale = self.ICON_SIZE / 24
        return [(x + px * scale, y + py * scale) for px, py in points]

    def _flatten_points(self, points):
        return [coordinate for point in points for coordinate in point]

    def _draw_code(self, x, y, color):
        for points in (
            [(8, 7), (3, 12), (8, 17)],
            [(16, 7), (21, 12), (16, 17)],
        ):
            scaled = self._scale_points(points, x, y)
            self.create_line(
                *self._flatten_points(scaled),
                fill=color,
                width=1.3,
                capstyle="round",
                joinstyle="round",
            )

    def _draw_shield(self, x, y, color):
        points = [(12, 3), (5, 6), (5, 11), (7.2, 15.5), (12, 20), (16.8, 15.5), (19, 11), (19, 6), (12, 3)]
        self.create_line(
            *self._flatten_points(self._scale_points(points, x, y)),
            fill=color,
            width=1.2,
            capstyle="round",
            joinstyle="round",
        )

    def _draw_search(self, x, y, color):
        scale = self.ICON_SIZE / 24
        self.create_oval(
            x + 4 * scale,
            y + 4 * scale,
            x + 17 * scale,
            y + 17 * scale,
            outline=color,
            width=1.2,
        )
        self.create_line(
            x + 15.5 * scale,
            y + 15.5 * scale,
            x + 21 * scale,
            y + 21 * scale,
            fill=color,
            width=1.2,
            capstyle="round",
        )

    def _draw_star(self, x, y, color):
        points = [
            (12, 3),
            (14.7, 8.5),
            (21, 9.2),
            (16.3, 13.5),
            (17.6, 20),
            (12, 16.8),
            (6.4, 20),
            (7.7, 13.5),
            (3, 9.2),
            (9.3, 8.5),
            (12, 3),
        ]
        self.create_line(
            *self._flatten_points(self._scale_points(points, x, y)),
            fill=color,
            width=1.15,
            capstyle="round",
            joinstyle="round",
        )

    def _draw_dot(self, x, y, cx, cy, color, radius=1.0):
        scale = self.ICON_SIZE / 24
        self.create_oval(
            x + (cx - radius) * scale,
            y + (cy - radius) * scale,
            x + (cx + radius) * scale,
            y + (cy + radius) * scale,
            fill=color,
            outline=color,
        )

    def _draw_palette(self, x, y, color):
        scale = self.ICON_SIZE / 24
        self.create_oval(
            x + 2.5 * scale,
            y + 2.5 * scale,
            x + 21.5 * scale,
            y + 21.5 * scale,
            outline=color,
            width=1.2,
        )
        for cx, cy in ((13.5, 6.5), (17.5, 10.5), (8.5, 7.5), (6.5, 12.5)):
            self._draw_dot(x, y, cx, cy, color, radius=0.95)

    def _draw_controller(self, x, y, color):
        scale = self.ICON_SIZE / 24
        self.create_oval(
            x + 2 * scale,
            y + 8 * scale,
            x + 22 * scale,
            y + 19 * scale,
            outline=color,
            width=1.2,
        )
        self.create_line(
            *self._flatten_points(self._scale_points([(5.5, 13), (9.5, 13)], x, y)),
            fill=color,
            width=1.2,
            capstyle="round",
        )
        self.create_line(
            *self._flatten_points(self._scale_points([(7.5, 11), (7.5, 15)], x, y)),
            fill=color,
            width=1.2,
            capstyle="round",
        )
        self._draw_dot(x, y, 16, 14, color, radius=0.9)
        self._draw_dot(x, y, 18.5, 11.5, color, radius=0.9)

    def _draw_pen(self, x, y, color):
        self.create_line(
            *self._flatten_points(self._scale_points([(3, 21), (5.5, 18.5)], x, y)),
            fill=color,
            width=1.3,
            capstyle="round",
            joinstyle="round",
        )
        self.create_line(
            *self._flatten_points(
                self._scale_points([(5.5, 18.5), (18, 6), (20, 4), (18, 6)], x, y)
            ),
            fill=color,
            width=1.3,
            capstyle="round",
            joinstyle="round",
        )
        self.create_line(
            *self._flatten_points(self._scale_points([(14.5, 5.5), (18.5, 9.5)], x, y)),
            fill=color,
            width=1.2,
            capstyle="round",
        )
