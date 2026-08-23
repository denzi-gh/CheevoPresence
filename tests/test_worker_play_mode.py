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


def _summary(game_id=123, recent=None, awarded=None):
    return {
        "LastGameID": game_id,
        "RichPresenceMsg": "Playing Level 1",
        "RichPresenceMsgDate": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "RecentAchievements": recent if recent is not None else {},
        "Awarded": awarded if awarded is not None else _progress(game_id),
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
    def _run_loop(self, summaries, games, stop_after, progresses=()):
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
            # Only consulted when the summary's Awarded block misses the
            # current game; an unexpected call exhausts the side_effect.
            patch(
                "desktop.runtime.worker.ra_get_user_progress",
                side_effect=list(progresses),
            ) as progress_calls,
            # DEBUG so steady-state presence_update_attempt lines (second poll
            # onwards) are captured too.
            self.assertLogs("desktop.runtime.worker", level="DEBUG") as logs,
        ):
            worker._loop()

        updates = [kwargs for presence in presences for kwargs in presence.updates]
        return worker, updates, summary_calls, progress_calls, "\n".join(logs.output)

    def test_last_unlock_sets_the_mode_word(self):
        _worker, updates, summary_calls, _progress_calls, output = self._run_loop(
            summaries=[_summary(recent={"99": {"1": _unlock("2026-08-20 10:00:00", hardcore=True)}})],
            games=[_game()],
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
        _worker, updates, _summary_calls, _progress_calls, _output = self._run_loop(
            summaries=[_summary(recent=softcore_only), _summary(recent=with_hardcore)],
            games=[_game(), _game()],
            stop_after=2,
        )

        self.assertEqual("\U0001F3C6 Softcore", updates[0]["state"])
        self.assertEqual("\U0001F3C6 Hardcore", updates[1]["state"])

    def test_no_unlock_history_shows_the_neutral_counter(self):
        worker, updates, _summary_calls, progress_calls, _output = self._run_loop(
            summaries=[_summary(recent={})],
            games=[_game()],
            stop_after=1,
        )

        self.assertEqual("\U0001F3C6 4/10", updates[0]["state"])
        self.assertNotIn("party_size", updates[0])
        self.assertIsNone(worker._play_mode)
        # Counters came from the summary's Awarded block — no dedicated call.
        progress_calls.assert_not_called()

    def test_missing_awarded_entry_falls_back_to_the_progress_endpoint(self):
        for awarded in ({}, []):
            with self.subTest(awarded=awarded):
                _worker, updates, _summary_calls, progress_calls, _output = self._run_loop(
                    summaries=[_summary(recent={}, awarded=awarded)],
                    games=[_game()],
                    progresses=[_progress()],
                    stop_after=1,
                )

                self.assertEqual(1, progress_calls.call_count)
                self.assertEqual("\U0001F3C6 4/10", updates[0]["state"])


if __name__ == "__main__":
    unittest.main()
