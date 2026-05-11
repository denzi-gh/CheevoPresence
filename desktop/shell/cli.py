"""Command-line entrypoint for CheevoPresence — no UI, verbose logging.

Usage inside Flatpak:
    flatpak run io.github.denzi_gh.CheevoPresence --username YOU --apikey YOUR_KEY

Options:
    --username    RetroAchievements username  (required)
    --apikey      RetroAchievements Web API key  (required)
    --interval    Poll interval in seconds (default: 10)
"""

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-7s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("cheevopresence")


def _log_environment():
    log.info("=== CheevoPresence — CLI debug mode ===")
    log.info("Python:           %s", sys.version.split()[0])
    log.info("FLATPAK_ID:       %s", os.getenv("FLATPAK_ID", "(not set)"))
    log.info("XDG_RUNTIME_DIR:  %s", os.getenv("XDG_RUNTIME_DIR", "(not set)"))
    log.info("TMPDIR:           %s", os.getenv("TMPDIR", "(not set)"))
    log.info("HOME:             %s", os.getenv("HOME", "(not set)"))
    log.info("DISPLAY:          %s", os.getenv("DISPLAY", "(not set)"))


def _log_ipc_sockets():
    """List every discord-ipc-* socket we can see in the usual search paths."""
    log.info("--- Discord IPC socket search ---")
    search_dirs = []

    tmpdir = os.getenv("TMPDIR")
    if tmpdir:
        search_dirs.append(("TMPDIR", tmpdir))

    xdg = os.getenv("XDG_RUNTIME_DIR")
    if xdg:
        search_dirs.append(("XDG_RUNTIME_DIR", xdg))
        search_dirs.append(("Flatpak Discord", os.path.join(xdg, "app", "com.discordapp.Discord")))
        search_dirs.append(("Snap Discord", os.path.join(xdg, "snap.discord")))

    for label, path in search_dirs:
        if not os.path.exists(path):
            log.info("  %-22s %s  [does not exist]", label, path)
            continue
        if not os.path.isdir(path):
            log.info("  %-22s %s  [not a directory]", label, path)
            continue
        try:
            entries = os.listdir(path)
        except PermissionError:
            log.info("  %-22s %s  [permission denied]", label, path)
            continue
        sockets = sorted(f for f in entries if f.startswith("discord-ipc-"))
        if sockets:
            log.info("  %-22s %s  -> %s", label, path, ", ".join(sockets))
        else:
            log.info("  %-22s %s  [no discord-ipc-* sockets]", label, path)

    log.info("---------------------------------")


def _import_deps():
    """Import runtime dependencies with clear error messages on failure."""
    log.debug("Importing requests...")
    try:
        import requests as _r
        log.debug("  requests %s OK", _r.__version__)
    except ImportError as exc:
        log.error("MISSING DEPENDENCY: %s", exc)
        sys.exit(1)

    log.debug("Importing pypresence...")
    try:
        import pypresence as _p
        log.debug("  pypresence OK")
    except ImportError as exc:
        log.error("MISSING DEPENDENCY: %s", exc)
        sys.exit(1)

    log.debug("Importing desktop.core.api...")
    try:
        from desktop.core import api as _a  # noqa: F401
        log.debug("  desktop.core.api OK")
    except ImportError as exc:
        log.error("CANNOT IMPORT APP PACKAGE: %s", exc)
        sys.exit(1)


def _poll_once(username, apikey, state, config):
    """Run a single poll cycle. Returns updated state dict."""
    import requests
    from pypresence import ActivityType, Presence
    from pypresence import exceptions as ppe

    from desktop.core.api import (
        APIResponseError,
        format_api_error,
        ra_get_game,
        ra_get_user_progress,
        ra_get_user_summary,
        trimmer,
    )
    from desktop.runtime.storage import load_console_icons

    rpc = state.get("rpc")
    rpc_connected = state.get("rpc_connected", False)
    start_time = state.get("start_time")
    current_game_id = state.get("current_game_id")
    console_icons = state.get("console_icons") or load_console_icons()
    state["console_icons"] = console_icons

    # --- RetroAchievements API call ---
    log.debug("Calling RA API: GetUserSummary for '%s'", username)
    try:
        user_data = ra_get_user_summary(username, apikey)
        log.debug("  GetUserSummary OK — keys: %s", list(user_data.keys()))
    except requests.RequestException as exc:
        log.warning("RA API error: %s", format_api_error(exc))
        _close_rpc(rpc)
        state.update(rpc=None, rpc_connected=False, start_time=None)
        return state
    except APIResponseError:
        log.warning("RA API returned unexpected payload shape")
        _close_rpc(rpc)
        state.update(rpc=None, rpc_connected=False, start_time=None)
        return state

    last_game_id_raw = user_data.get("LastGameID", 0)
    try:
        last_game_id = max(0, int(last_game_id_raw))
    except (TypeError, ValueError):
        last_game_id = 0

    rp_msg = user_data.get("RichPresenceMsg", "")
    if not isinstance(rp_msg, str):
        rp_msg = ""
    rp_date_str = user_data.get("RichPresenceMsgDate", "") or ""

    log.info("RA status — LastGameID: %s | RichPresenceMsg: %r | RichPresenceMsgDate: %s",
             last_game_id, rp_msg, rp_date_str)

    if not last_game_id:
        log.info("STATUS: Not playing (no active game)")
        _close_rpc(rpc)
        state.update(rpc=None, rpc_connected=False, start_time=None, current_game_id=None)
        return state

    # --- Activity timeout check ---
    timeout_sec = config.get("timeout", 130)
    is_active = True
    if timeout_sec > 0 and rp_date_str:
        try:
            rp_date = datetime.strptime(rp_date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - rp_date).total_seconds()
            log.debug("RichPresence age: %.0f s (timeout: %d s)", age, timeout_sec)
            if age > timeout_sec:
                log.info("STATUS: Session timed out (last activity %.0f s ago)", age)
                is_active = False
        except ValueError:
            log.debug("Could not parse RichPresenceMsgDate: %r", rp_date_str)
    elif not rp_date_str:
        log.debug("No RichPresenceMsgDate — treating as inactive")
        is_active = False

    if not is_active:
        _close_rpc(rpc)
        state.update(rpc=None, rpc_connected=False, start_time=None, current_game_id=None)
        return state

    # --- Game metadata ---
    log.debug("Calling RA API: GetGame(%s)", last_game_id)
    try:
        game_data = ra_get_game(username, apikey, last_game_id)
        log.debug("  GetGame OK — GameTitle: %r, ConsoleName: %r",
                  game_data.get("GameTitle"), game_data.get("ConsoleName"))
    except (requests.RequestException, APIResponseError) as exc:
        log.warning("GetGame failed: %s", exc)
        _close_rpc(rpc)
        state.update(rpc=None, rpc_connected=False, start_time=None)
        return state

    log.debug("Calling RA API: GetUserProgress(%s)", last_game_id)
    try:
        progress_data = ra_get_user_progress(username, apikey, last_game_id)
        log.debug("  GetUserProgress OK")
    except (requests.RequestException, APIResponseError) as exc:
        log.warning("GetUserProgress failed: %s", exc)
        _close_rpc(rpc)
        state.update(rpc=None, rpc_connected=False, start_time=None)
        return state

    game_title = game_data.get("GameTitle", "Unknown")
    console_name = game_data.get("ConsoleName", "Unknown")
    console_id = str(game_data.get("ConsoleID", "0"))
    image_icon = game_data.get("ImageIcon", "") or ""

    if last_game_id != current_game_id:
        log.info("New game detected — resetting session timer")
        start_time = int(time.time())
        state["current_game_id"] = last_game_id
        state["start_time"] = start_time
        if rpc_connected:
            state["start_time"] = start_time

    gid_str = str(last_game_id)
    prog = progress_data.get(gid_str) or {}
    try:
        total = max(0, int(prog.get("NumPossibleAchievements", 0)))
        achieved = max(0, int(prog.get("NumAchieved", 0)))
        achieved_hc = max(0, int(prog.get("NumAchievedHardcore", 0)))
    except (TypeError, ValueError):
        total = achieved = achieved_hc = 0

    log.debug("Achievements: %d/%d (HC: %d)", achieved, total, achieved_hc)

    if total <= 0:
        state_str, achi_count = "No achievements available", 0
    elif achieved <= 0:
        state_str, achi_count = "No achievements yet", 0
    elif achieved_hc < achieved:
        state_str, achi_count = "\U0001F3C6 Softcore", achieved
    else:
        state_str, achi_count = "\U0001F3C6 Hardcore", achieved_hc

    party = [achi_count, total] if total > 0 else None
    large_tooltip = f"{achi_count}/{total} achievements" if total > 0 else game_title
    large_img = f"https://media.retroachievements.org{image_icon}" if image_icon else None
    small_img = console_icons.get(console_id)
    game_url = f"https://retroachievements.org/game/{last_game_id}"
    profile_url = f"https://retroachievements.org/user/{quote(username)}"
    buttons = [
        {"label": "View on RetroAchievements", "url": game_url},
        {"label": f"{username}'s RA Page", "url": profile_url},
    ]

    log.info("STATUS: Playing %r on %s | %s | %s", game_title, console_name, rp_msg, state_str)
    log.debug("Discord payload — large_img: %s | small_img: %s", large_img, small_img)

    # --- Discord RPC ---
    if not rpc_connected:
        log.info("Connecting to Discord IPC...")
        _log_ipc_sockets()
        try:
            if rpc:
                try:
                    rpc.close()
                except Exception:
                    pass
            rpc = Presence("1485964205713788958")
            rpc.connect()
            rpc_connected = True
            if start_time is None:
                start_time = int(time.time())
            state.update(rpc=rpc, rpc_connected=True, start_time=start_time)
            log.info("Discord IPC connected OK")
        except ppe.DiscordNotFound:
            log.error("Discord IPC: DiscordNotFound — Discord is not running")
            state.update(rpc=None, rpc_connected=False)
            return state
        except ppe.InvalidPipe:
            log.error("Discord IPC: InvalidPipe — socket exists but rejected connection")
            state.update(rpc=None, rpc_connected=False)
            return state
        except Exception as exc:
            log.error("Discord IPC connect failed: %s: %s", type(exc).__name__, exc)
            state.update(rpc=None, rpc_connected=False)
            return state

    log.debug("Updating Discord Rich Presence...")
    try:
        update_kwargs = dict(
            activity_type=ActivityType.PLAYING,
            name=trimmer(game_title),
            details=trimmer(rp_msg) if rp_msg else None,
            state=state_str,
            start=state.get("start_time"),
            large_image=large_img,
            large_text=large_tooltip,
            small_image=small_img,
            small_text=console_name,
            buttons=buttons,
        )
        if party:
            update_kwargs["party_id"] = f"ra_{last_game_id}"
            update_kwargs["party_size"] = party
        rpc.update(**update_kwargs)
        log.info("Discord RPC updated successfully")
    except Exception as exc:
        log.error("Discord RPC update failed: %s: %s", type(exc).__name__, exc)
        _close_rpc(rpc)
        state.update(rpc=None, rpc_connected=False, start_time=None)

    return state


def _close_rpc(rpc):
    if rpc is None:
        return
    try:
        rpc.clear()
    except Exception:
        pass
    try:
        rpc.close()
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        prog="cheevopresence",
        description="CheevoPresence — CLI debug mode (no UI)",
    )
    parser.add_argument("--username", required=True, help="RetroAchievements username")
    parser.add_argument("--apikey", required=True, help="RetroAchievements Web API key")
    parser.add_argument("--interval", type=int, default=10,
                        help="Poll interval in seconds (default: 10)")
    args = parser.parse_args()

    _log_environment()
    _log_ipc_sockets()
    _import_deps()

    key_preview = (args.apikey[:4] + "..." + args.apikey[-4:]) if len(args.apikey) >= 8 else "****"
    log.info("Username: %s", args.username)
    log.info("API key:  %s", key_preview)
    log.info("Interval: %d s", args.interval)

    config = {
        "username": args.username,
        "apikey": args.apikey,
        "interval": args.interval,
        "timeout": 130,
        "show_profile_button": True,
        "show_gamepage_button": True,
        "show_achievement_progress": True,
    }

    state = {}
    stop = [False]

    def handle_signal(sig, frame):
        if not stop[0]:
            stop[0] = True
            log.info("Stopping...")

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    log.info("Starting poll loop — Ctrl+C to quit")
    consecutive_errors = 0

    while not stop[0]:
        try:
            state = _poll_once(args.username, args.apikey, state, config)
            consecutive_errors = 0
        except Exception as exc:
            consecutive_errors += 1
            log.error("Unhandled error in poll cycle: %s: %s", type(exc).__name__, exc)

        if stop[0]:
            break

        wait = min(args.interval * (2 ** min(consecutive_errors, 4)), 60) if consecutive_errors else args.interval
        if consecutive_errors:
            log.info("Waiting %d s before retry (error backoff, %d consecutive errors)...",
                     wait, consecutive_errors)
        else:
            log.debug("Sleeping %d s until next poll...", wait)

        for _ in range(wait):
            if stop[0]:
                break
            time.sleep(1)

    log.info("Cleaning up Discord RPC...")
    _close_rpc(state.get("rpc"))
    log.info("Done.")


if __name__ == "__main__":
    main()
