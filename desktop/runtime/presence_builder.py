"""Build Discord Rich Presence payloads from RetroAchievements data."""

from dataclasses import dataclass
from urllib.parse import quote

from pypresence import ActivityType

from desktop.core.api import trimmer
from desktop.core.ra_client import APIResponseError

PLAY_MODE_HARDCORE = "hardcore"
PLAY_MODE_SOFTCORE = "softcore"

DEVELOPER_ACTIVITY_TITLES = {
    "developing achievements": "Developing RetroAchievements",
    "fixing achievements": "Fixing RetroAchievements",
    "inspecting memory": "Inspecting Memory for RetroAchievements",
}
DEVELOPER_ACTIVITY_MESSAGES = frozenset(DEVELOPER_ACTIVITY_TITLES)


@dataclass(frozen=True)
class PresenceBuildResult:

    update_kwargs: dict
    game_title: str
    console_name: str
    console_id: str
    achievement_count: int
    achievement_total: int
    button_count: int
    developer_activity: bool


def coerce_progress_int(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def build_achievement_state(total, achieved, achieved_hc, play_mode=None):
    if total <= 0:
        return "No achievements available", 0
    if achieved <= 0:
        return "No achievements yet", 0
    if play_mode == PLAY_MODE_HARDCORE:
        return "\U0001F3C6 Hardcore", achieved_hc
    if play_mode == PLAY_MODE_SOFTCORE:
        return "\U0001F3C6 Softcore", achieved
    return f"\U0001F3C6 {achieved}/{total}", achieved


def is_developer_activity(rich_presence_message):
    return _normalize_developer_activity(rich_presence_message) in DEVELOPER_ACTIVITY_MESSAGES


def _normalize_developer_activity(rich_presence_message):
    if not isinstance(rich_presence_message, str):
        return ""
    return rich_presence_message.strip().casefold()


def build_display_game_title(game_title, developer_activity):
    if developer_activity:
        return f"\U0001F6E0\ufe0f {game_title} \U0001F6E0\ufe0f"
    return game_title


def build_activity_fields(game_title, rich_presence_message, use_developer_titles):
    developer_key = _normalize_developer_activity(rich_presence_message)
    developer_activity = developer_key in DEVELOPER_ACTIVITY_MESSAGES
    if developer_activity and use_developer_titles:
        return DEVELOPER_ACTIVITY_TITLES[developer_key], game_title, developer_activity
    display_game_title = build_display_game_title(game_title, developer_activity)
    details = rich_presence_message if rich_presence_message else None
    return display_game_title, details, developer_activity


class PresenceBuilder:

    def __init__(self, config, console_icons):
        self.config = config
        self.console_icons = console_icons

    def build(
        self,
        username,
        last_game_id,
        rich_presence_message,
        game_data,
        progress_data,
        start_time,
        *,
        play_mode=None,
    ):
        game_title = game_data.get("GameTitle", "Unknown")
        if not isinstance(game_title, str):
            raise APIResponseError

        display_name, details, developer_activity = build_activity_fields(
            game_title,
            rich_presence_message,
            self.config.get("use_retroachievements_developer_titles", True),
        )

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
            play_mode,
        )

        show_achievement_progress = self.config.get("show_achievement_progress", True)
        # While the mode is unknown the state already shows the counter
        neutral_counter_state = play_mode is None and total > 0 and achieved > 0
        party = (
            [achievement_count, total]
            if show_achievement_progress and total > 0 and not neutral_counter_state
            else None
        )
        if show_achievement_progress and total > 0:
            large_tooltip = f"{achievement_count}/{total} achievements"
        else:
            large_tooltip = game_title

        game_url = f"https://retroachievements.org/game/{last_game_id}"
        quoted_username = quote(username)
        profile_url = f"https://retroachievements.org/user/{quoted_username}"
        developer_sets_url = f"{profile_url}/developer/sets"

        buttons = []
        if self.config.get("show_gamepage_button", True):
            buttons.append({"label": "View on RetroAchievements", "url": game_url})
        if self.config.get("show_profile_button", True):
            if developer_activity and self.config.get("show_developer_sets_button", True):
                buttons.append(
                    {
                        "label": f"View {username}'s Created Sets",
                        "url": developer_sets_url,
                    }
                )
            else:
                buttons.append({"label": f"{username}'s RA Page", "url": profile_url})
        if not buttons:
            buttons = None

        large_img = (
            f"https://media.retroachievements.org{image_icon}"
            if image_icon
            else None
        )
        small_img = self.console_icons.get(console_id)

        update_kwargs = {
            "activity_type": ActivityType.PLAYING,
            "name": trimmer(display_name),
            "details": trimmer(details) if details else None,
            "state": state_str,
            "start": start_time,
            "large_image": large_img,
            "large_text": large_tooltip,
            "small_image": small_img,
            "small_text": console_name,
            "buttons": buttons,
        }
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
