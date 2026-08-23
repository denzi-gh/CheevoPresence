import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import requests

from desktop.runtime.worker import RPCWorker

EMERALD_PLAYTIME = 130592


class PlaytimePresence:
    def __init__(self, worker, stop_after):
        self.worker = worker
        self.stop_after = stop_after
        self.updates = []
        self.pipe = None

    def connect(self):
        pass

    def update(self, **kwargs):
        self.updates.append(kwargs)
        if len(self.updates) >= self.stop_after:
            self.worker._stop_event.set()

    def clear(self):
        pass

    def close(self):
        pass


def _summary(game_id=668):
    return {
        "LastGameID": game_id,
        "RichPresenceMsg": "Playing Level 1",
        "RichPresenceMsgDate": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "RecentAchievements": {},
    }


def _game():
    return {
        "GameTitle": "Mega Game",
        "ConsoleName": "GBA",
        "ConsoleID": "5",
        "ImageIcon": "/Images/126553.png",
    }


def _progress(game_id=668):
    return {
        str(game_id): {
            "NumPossibleAchievements": 197,
            "NumAchieved": 29,
            "NumAchievedHardcore": 29,
        }
    }


class WorkerPlaytimeTests(unittest.TestCase):
    def _run_loop(self, game_infos, stop_after=1, show_total_playtime=True):
        worker = RPCWorker(
            initial_config={
                "username": "user",
                "apikey": "key",
                "show_achievement_progress": True,
                "show_total_playtime": show_total_playtime,
            },
            console_icons={"5": "gba-icon"},
        )
        presences = []

        def presence_factory(client_id, pipe=None):
            presence = PlaytimePresence(worker, stop_after)
            presence.pipe = pipe
            presences.append(presence)
            return presence

        worker._presence_factory = presence_factory
        worker.running = True
        worker._sleep = lambda seconds: None

        with (
            patch("desktop.runtime.worker.ra_get_user_summary", return_value=_summary()),
            patch("desktop.runtime.worker.ra_get_game", return_value=_game()),
            patch("desktop.runtime.worker.ra_get_user_progress", return_value=_progress()),
            patch(
                "desktop.runtime.worker.ra_get_game_info_and_user_progress",
                side_effect=game_infos,
            ) as info_calls,
        ):
            worker._loop()

        updates = [kwargs for presence in presences for kwargs in presence.updates]
        return worker, updates, info_calls

    def test_playtime_backdates_the_presence_start(self):
        _worker, updates, info_calls = self._run_loop(
            game_infos=[{"UserTotalPlaytime": EMERALD_PLAYTIME}],
        )

        self.assertEqual(1, info_calls.call_count)
        expected = int(time.time()) - EMERALD_PLAYTIME
        self.assertAlmostEqual(expected, updates[0]["start"], delta=10)

    def test_fetch_failure_falls_back_to_the_session_start(self):
        _worker, updates, _info_calls = self._run_loop(
            game_infos=[requests.ConnectionError("offline")],
            stop_after=2,
        )

        # The second poll carries the gateway's session start stamped at
        # connect time — not a backdated one.
        self.assertAlmostEqual(int(time.time()), updates[1]["start"], delta=10)

    def test_zero_playtime_falls_back_to_the_session_start(self):
        worker, updates, _info_calls = self._run_loop(
            game_infos=[{"UserTotalPlaytime": 0}],
            stop_after=2,
        )

        self.assertIsNone(worker._playtime_start)
        self.assertAlmostEqual(int(time.time()), updates[1]["start"], delta=10)

    def test_disabled_option_never_calls_the_endpoint(self):
        _worker, updates, info_calls = self._run_loop(
            game_infos=[{"UserTotalPlaytime": EMERALD_PLAYTIME}],
            stop_after=2,
            show_total_playtime=False,
        )

        info_calls.assert_not_called()
        self.assertAlmostEqual(int(time.time()), updates[1]["start"], delta=10)


if __name__ == "__main__":
    unittest.main()
