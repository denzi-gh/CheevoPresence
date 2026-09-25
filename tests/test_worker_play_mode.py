import unittest
from datetime import timedelta

from worker_fakes import NOW, WorkerHarness, activity, player_game

from desktop.runtime.worker import mode_from_player_games


class ModeFromPlayerGamesTests(unittest.TestCase):
    def test_latest_unlock_across_games_decides_the_mode_and_hardcore_wins_ties(self):
        games = (player_game(123, hard=NOW - timedelta(days=1)), player_game(456, soft=NOW))
        self.assertEqual("softcore", mode_from_player_games(games))
        self.assertEqual("hardcore", mode_from_player_games(games + (player_game(789, hard=NOW),)))

    def test_missing_history_yields_no_mode(self):
        self.assertIsNone(mode_from_player_games(()))
        self.assertIsNone(mode_from_player_games((player_game(),)))


class WorkerPlayModeTests(unittest.TestCase):
    def test_last_unlock_sets_the_mode_word_and_counter(self):
        run = WorkerHarness([activity()])
        run.api["mode"].side_effect = None
        run.api["mode"].return_value = (player_game(123), player_game(456, hard=NOW))
        with self.assertLogs("desktop.runtime.worker", level="DEBUG") as logs:
            run.run()
        self.assertEqual("\U0001F3C6 Hardcore", run.gateway.updates[0]["state"])
        self.assertEqual([3, 10], run.gateway.updates[0]["party_size"])
        self.assertIn("play_mode_changed mode=hardcore", "\n".join(logs.output))

    def test_new_unlock_flips_the_mode_when_activity_changes(self):
        run = WorkerHarness([activity(), activity(rich_presence_updated_at=NOW + timedelta(seconds=45))])
        run.api["mode"].side_effect = [
            (player_game(123, soft=NOW),),
            (player_game(123, soft=NOW, hard=NOW + timedelta(seconds=45)),),
        ]
        run.run()
        self.assertEqual(["\U0001F3C6 Softcore", "\U0001F3C6 Hardcore"], [u["state"] for u in run.gateway.updates])
        self.assertEqual([4, 10], run.gateway.updates[0]["party_size"])
        self.assertEqual([3, 10], run.gateway.updates[1]["party_size"])

    def test_no_unlock_history_shows_the_neutral_counter(self):
        run = WorkerHarness([activity()]).run()
        self.assertEqual("\U0001F3C6 4/10", run.gateway.updates[0]["state"])
        self.assertNotIn("party_size", run.gateway.updates[0])

    def test_active_game_outside_recent_ten_is_included_in_mode_evidence(self):
        run = WorkerHarness([activity()])
        recent = tuple(player_game(i, soft=NOW - timedelta(days=1)) for i in range(10, 20))
        run.api["mode"].side_effect = [recent, (player_game(123, hard=NOW),)]
        run.run()
        self.assertEqual("\U0001F3C6 Hardcore", run.gateway.updates[0]["state"])
        self.assertEqual({"limit": 10}, run.api["mode"].call_args_list[0].kwargs)
        self.assertEqual({"game_id": 123, "limit": 1}, run.api["mode"].call_args_list[1].kwargs)

    def test_missing_active_player_game_keeps_recent_game_evidence(self):
        run = WorkerHarness([activity()])
        run.api["mode"].side_effect = [(player_game(456, soft=NOW),), ()]
        run.run()
        self.assertEqual("\U0001F3C6 Softcore", run.gateway.updates[0]["state"])


if __name__ == "__main__":
    unittest.main()
