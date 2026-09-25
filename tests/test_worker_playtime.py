import unittest
from datetime import timedelta

import requests
from worker_fakes import NOW, WorkerHarness, activity, game_info

EMERALD_PLAYTIME = 130592


class WorkerPlaytimeTests(unittest.TestCase):
    def test_playtime_backdates_presence_and_is_not_reseeded_by_activity(self):
        run = WorkerHarness([activity(), activity(rich_presence_updated_at=NOW + timedelta(seconds=45))])
        run.api["info"].return_value = game_info(UserTotalPlaytime=EMERALD_PLAYTIME)
        run.run()
        self.assertEqual(1, run.api["info"].call_count)
        self.assertEqual([int(NOW.timestamp()) - EMERALD_PLAYTIME] * 2, [u["start"] for u in run.gateway.updates])

    def test_fetch_failure_uses_backoff_and_retries_before_publishing(self):
        run = WorkerHarness([activity(), activity()])
        run.api["info"].side_effect = [requests.ConnectionError("offline"), game_info(UserTotalPlaytime=EMERALD_PLAYTIME)]
        run.run()
        self.assertEqual([60, 45], run.waits)
        self.assertEqual(1, len(run.gateway.updates))
        self.assertEqual(int(NOW.timestamp()) - EMERALD_PLAYTIME, run.gateway.updates[0]["start"])
        run.api["game"].assert_not_called()
        run.api["progress"].assert_not_called()

    def test_zero_or_missing_playtime_uses_session_timer_without_repeated_fetches(self):
        for value in (0, None, "invalid"):
            with self.subTest(value=value):
                run = WorkerHarness([activity(), activity()])
                run.api["info"].return_value = game_info(UserTotalPlaytime=value)
                run.run()
                self.assertEqual(int(NOW.timestamp()), run.gateway.updates[1]["start"])
                self.assertEqual(1, run.api["info"].call_count)
        run = WorkerHarness([activity(), activity()])
        del run.api["info"].return_value["UserTotalPlaytime"]
        run.run()
        self.assertEqual(int(NOW.timestamp()), run.gateway.updates[1]["start"])
        self.assertEqual(1, run.api["info"].call_count)

    def test_disabled_option_never_calls_the_combined_endpoint(self):
        run = WorkerHarness([activity(), activity()], show_total_playtime=False).run()
        run.api["info"].assert_not_called()
        self.assertEqual(["activity", "game", "progress", "mode"], run.requests[0])
        self.assertEqual(["activity"], run.requests[1])
        self.assertEqual(int(NOW.timestamp()), run.gateway.updates[1]["start"])

    def test_enabling_playtime_fetches_once_and_reuses_combined_progress(self):
        run = WorkerHarness([activity()] * 4, show_total_playtime=False)

        def change_setting(iteration, harness):
            harness.worker.replace_config(harness.worker.config | {"show_total_playtime": iteration != 2})

        run.run(after_iteration=change_setting)
        self.assertEqual(1, run.api["info"].call_count)
        self.assertEqual(1, run.api["progress"].call_count)
        self.assertEqual(1, run.api["game"].call_count)
        self.assertEqual(int(NOW.timestamp()) - 900, run.gateway.updates[1]["start"])
        self.assertEqual(int(NOW.timestamp()), run.gateway.updates[2]["start"])
        self.assertEqual(int(NOW.timestamp()) - 900, run.gateway.updates[3]["start"])

    def test_game_change_and_resume_after_inactivity_reseed_playtime(self):
        for next_activity in (activity(game_id=456), activity(rich_presence_updated_at=NOW - timedelta(hours=1))):
            with self.subTest(next_activity=next_activity):
                run = WorkerHarness([activity(), next_activity, activity()]).run()
                expected_calls = 3 if next_activity.game_id == 456 else 2
                self.assertEqual(expected_calls, run.api["info"].call_count)


if __name__ == "__main__":
    unittest.main()
