"""Build Discord Rich Presence payloads from RetroAchievements data."""

from dataclasses import dataclass
from urllib.parse import quote

from pypresence import ActivityType

from desktop.core.api import APIResponseError, trimmer

DEVELOPER_ACTIVITY_MESSAGES = {
    "inspecting memory",
    "developing achievements",
}


@dataclass(frozen=True)
class PresenceBuildResult:
    """Discord payload plus metadata used for status text and safe logging."""

    update_kwargs: dict
    game_title: str
    console_name: str
    console_id: str
    achievement_count: int
    achievement_total: int
    button_count: int
    developer_activity: bool


def coerce_progress_int(value):
    """Coerce loose API progress values into non-negative integers."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def build_achievement_state(total, achieved, achieved_hc):
    """Translate raw progress counts into the Discord state label."""
    if total <= 0:
        return "No achievements available", 0
    if achieved <= 0:
        return "No achievements yet", 0
    if achieved_hc < achieved:
        return "\U0001F3C6 Softcore", achieved
    return "\U0001F3C6 Hardcore", achieved_hc


def is_developer_activity(rich_presence_message):
    """Return whether the RA rich presence text means achievement dev work."""
    if not isinstance(rich_presence_message, str):
        return False
    return rich_presence_message.strip().casefold() in DEVELOPER_ACTIVITY_MESSAGES


def build_display_game_title(game_title, developer_activity):
    """Decorate the Discord game title when the user is developing achievements."""
    if developer_activity:
        return f"\U0001F6E0\ufe0f {game_title} \U0001F6E0\ufe0f"
    return game_title


class PresenceBuilder:
    """Translate validated RA payloads into pypresence update arguments."""

    def __init__(self, config, console_icons):
        self.config = config
        self.console_icons = console_icons

    def build(self, username, last_game_id, rich_presence_message, game_data, progress_data, start_time):
        """Build the Discord presence payload for the active game session."""
        game_title = game_data.get("GameTitle", "Unknown")
        if not isinstance(game_title, str):
            raise APIResponseError

        developer_activity = is_developer_activity(rich_presence_message)
        display_game_title = build_display_game_title(game_title, developer_activity)

        console_name = game_data.get("ConsoleName", "Unknown")
        if not isinstance(console_name, str):
            raise APIResponseError

        console_id = str(game_data.get("ConsoleID", "0"))
        image_icon = game_data.get("ImageIcon", "")
        if image_icon is None:
            image_icon = ""
        if not isinstance(image_icon, str):
            raise APIResponseError

        gid_str = str(last_game_id)
        progress = progress_data.get(gid_str, {})
        if progress is None:
            progress = {}
        if not isinstance(progress, dict):
            raise APIResponseError

        total = coerce_progress_int(progress.get("NumPossibleAchievements", 0))
        achieved = coerce_progress_int(progress.get("NumAchieved", 0))
        achieved_hc = coerce_progress_int(progress.get("NumAchievedHardcore", 0))
        state_str, achievement_count = build_achievement_state(
            total,
            achieved,
            achieved_hc,
        )

        show_achievement_progress = self.config.get("show_achievement_progress", True)
        party = [achievement_count, total] if show_achievement_progress and total > 0 else None
        if show_achievement_progress and total > 0:
            large_tooltip = f"{achievement_count}/{total} achievements"
        else:
            large_tooltip = game_title

        game_url = f"https://retroachievements.org/game/{last_game_id}"
        profile_url = f"https://retroachievements.org/user/{quote(username)}"

        buttons = []
        if self.config.get("show_gamepage_button", True):
            buttons.append({"label": "View on RetroAchievements", "url": game_url})
        if self.config.get("show_profile_button", True):
            buttons.append({"label": f"{username}'s RA Page", "url": profile_url})
        if not buttons:
            buttons = None

        large_img = (
            f"https://media.retroachievements.org{image_icon}"
            if image_icon
            else None
        )
        small_img = self.console_icons.get(console_id)

        update_kwargs = dict(
            activity_type=ActivityType.PLAYING,
            name=trimmer(display_game_title),
            details=trimmer(rich_presence_message) if rich_presence_message else None,
            state=state_str,
            start=start_time,
            large_image=large_img,
            large_text=large_tooltip,
            small_image=small_img,
            small_text=console_name,
            buttons=buttons,
        )
        if party:
            update_kwargs["party_id"] = f"ra_{last_game_id}"
            update_kwargs["party_size"] = party

        return PresenceBuildResult(
            update_kwargs=update_kwargs,
            game_title=game_title,
            console_name=console_name,
            console_id=console_id,
            achievement_count=achievement_count,
            achievement_total=total,
            button_count=len(buttons or []),
            developer_activity=developer_activity,
        )
