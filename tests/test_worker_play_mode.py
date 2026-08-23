import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from desktop.runtime.worker import RPCWorker, mode_from_summary


class PlayModePresence:
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


def _unlock(date, hardcore):
    return {"DateAwarded": date, "HardcoreAchieved": 1 if hardcore else 0}


def _summary(game_id=123, recent=None):
    return {
        "LastGameID": game_id,
        "RichPresenceMsg": "Playing Level 1",
        "RichPresenceMsgDate": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "RecentAchievements": recent if recent is not None else {},
    }


def _game():
    return {
        "GameTitle": "Mega Game",
        "ConsoleName": "NES",
        "ConsoleID": "7",
        "ImageIcon": "/Images/000123.png",
    }


def _progress(game_id=123, achieved=4, hc=3, total=10):
    return {
        str(game_id): {
            "NumPossibleAchievements": total,
            "NumAchieved": achieved,
            "NumAchievedHardcore": hc,
        }
    }


class ModeFromSummaryTests(unittest.TestCase):
    def test_latest_unlock_across_games_decides_the_mode(self):
        recent = {
            "123": {
                "1": _unlock("2026-08-01 10:00:00", hardcore=True),
                "2": "not a dict",
                "3": {"DateAwarded": "garbage", "HardcoreAchieved": 1},
            },
            "456": {"4": _unlock("2026-08-20 10:00:00", hardcore=False)},
        }
        self.assertEqual("softcore", mode_from_summary({"RecentAchievements": recent}))

        # A hardcore unlock at the same second must win the tie.
        recent["123"]["5"] = _unlock("2026-08-20 10:00:00", hardcore=True)
        self.assertEqual("hardcore", mode_from_summary({"RecentAchievements": recent}))

    def test_missing_history_yields_no_mode(self):
        self.assertIsNone(mode_from_summary({"RecentAchievements": {}}))
        self.assertIsNone(mode_from_summary({"RecentAchievements": []}))
        self.assertIsNone(mode_from_summary({}))
        self.assertIsNone(mode_from_summary(None))


class WorkerPlayModeTests(unittest.TestCase):
    def _run_loop(self, summaries, games, progresses, stop_after):
        worker = RPCWorker(
            initial_config={
                "username": "user",
                "apikey": "key",
                "show_achievement_progress": True,
            },
            console_icons={"7": "nes-icon"},
        )
        presences = []

        def presence_factory(client_id, pipe=None):
            presence = PlayModePresence(worker, stop_after)
            presence.pipe = pipe
            presences.append(presence)
            return presence

        worker._presence_factory = presence_factory
        worker.running = True
        worker._sleep = lambda seconds: None

        with (
            patch(
                "desktop.runtime.worker.ra_get_user_summary",
                side_effect=summaries,
            ) as summary_calls,
            patch("desktop.runtime.worker.ra_get_game", side_effect=games),
            patch("desktop.runtime.worker.ra_get_user_progress", side_effect=progresses),
            # DEBUG so steady-state presence_update_attempt lines (second poll
            # onwards) are captured too.
            self.assertLogs("desktop.runtime.worker", level="DEBUG") as logs,
        ):
            worker._loop()

        updates = [kwargs for presence in presences for kwargs in presence.updates]
        return worker, updates, summary_calls, "\n".join(logs.output)

    def test_last_unlock_sets_the_mode_word(self):
        _worker, updates, summary_calls, output = self._run_loop(
            summaries=[_summary(recent={"99": {"1": _unlock("2026-08-20 10:00:00", hardcore=True)}})],
            games=[_game()],
            progresses=[_progress()],
            stop_after=1,
        )

        self.assertEqual("\U0001F3C6 Hardcore", updates[0]["state"])
        self.assertEqual([3, 10], updates[0]["party_size"])
        self.assertIn("play_mode_changed mode=hardcore", output)
        self.assertRegex(output, r"presence_update_attempt .*mode=hardcore")
        kwargs = summary_calls.call_args.kwargs
        self.assertEqual(1, kwargs["recent_achievements"])
        self.assertGreater(kwargs["recent_games"], 0)

    def test_new_unlock_flips_the_mode(self):
        softcore_only = {"123": {"1": _unlock("2026-08-20 10:00:00", hardcore=False)}}
        with_hardcore = {
            "123": {
                "1": _unlock("2026-08-20 10:00:00", hardcore=False),
                "2": _unlock("2026-08-23 10:00:00", hardcore=True),
            }
        }
        _worker, updates, _summary_calls, _output = self._run_loop(
            summaries=[_summary(recent=softcore_only), _summary(recent=with_hardcore)],
            games=[_game(), _game()],
            progresses=[_progress(), _progress()],
            stop_after=2,
        )

        self.assertEqual("\U0001F3C6 Softcore", updates[0]["state"])
        self.assertEqual("\U0001F3C6 Hardcore", updates[1]["state"])

    def test_no_unlock_history_shows_the_neutral_counter(self):
        worker, updates, _summary_calls, _output = self._run_loop(
            summaries=[_summary(recent={})],
            games=[_game()],
            progresses=[_progress()],
            stop_after=1,
        )

        self.assertEqual("\U0001F3C6 4/10", updates[0]["state"])
        self.assertNotIn("party_size", updates[0])
        self.assertIsNone(worker._play_mode)


if __name__ == "__main__":
    unittest.main()
