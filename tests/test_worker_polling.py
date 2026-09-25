import unittest
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import requests
from worker_fakes import NOW, WorkerHarness, activity, game_info, player_game, progress

from desktop.core.ra_client import APIResponseError
from desktop.core.roles import DEBUG_FORCE_ROLE_PERMISSION_ENV


def http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


class ChangeDetectionTests(unittest.TestCase):
    def test_unchanged_poll_only_fetches_v2_activity_after_initialization(self):
        run = WorkerHarness([activity()] * 4).run()
        self.assertEqual([
            ["activity", "info", "mode"], ["activity"], ["activity"], ["activity"],
        ], run.requests)
        self.assertEqual([45] * 4, run.waits)
        self.assertEqual(4, len(run.gateway.updates))
        self.assertEqual("NES", run.snapshots[0].mirrored_presence.console_name)
        self.assertEqual("https://media.retroachievements.org/Images/000123.png", run.gateway.updates[0]["large_image"])

    def test_game_change_initializes_once_even_with_the_same_timestamp(self):
        run = WorkerHarness([activity(), activity(game_id=456), activity(game_id=456)]).run()
        self.assertEqual([
            ["activity", "info", "mode"], ["activity", "info", "mode"], ["activity"],
        ], run.requests)
        self.assertEqual([123, 456], [call.args[2] for call in run.api["info"].call_args_list])
        self.assertEqual([123, 456, 456], [s.mirrored_presence.game_id for s in run.snapshots])

    def test_activity_ping_without_text_change_refreshes_progress_once(self):
        ping = activity(rich_presence_updated_at=NOW + timedelta(seconds=45))
        run = WorkerHarness([activity(), ping, ping])
        run.api["progress"].side_effect = None
        run.api["progress"].return_value = progress(achieved=5)
        run.run()
        self.assertEqual(["activity", "progress", "mode"], run.requests[1])
        self.assertEqual(["activity"], run.requests[2])
        self.assertEqual([4, 5, 5], [s.mirrored_presence.achievement_count for s in run.snapshots])
        self.assertEqual(["Playing Level 1"] * 3, [u["details"] for u in run.gateway.updates])

    def test_text_change_without_ping_updates_presence_without_detail_requests(self):
        run = WorkerHarness([activity(), activity(rich_presence="Playing Level 2")]).run()
        self.assertEqual(["activity"], run.requests[1])
        self.assertEqual("Playing Level 2", run.gateway.updates[1]["details"])

    def test_title_changes_update_cached_title_and_keep_formatting_options(self):
        run = WorkerHarness([
            activity(game_title="~Hack~ Old Game"), activity(game_title="~Homebrew~ New Game"),
        ], strip_game_type_from_title=True, show_console_name_in_title=True,
            show_achievement_progress=False).run()
        self.assertEqual(["activity"], run.requests[1])
        self.assertEqual(["Old Game (NES)", "New Game (NES)"], [u["name"] for u in run.gateway.updates])
        self.assertEqual("New Game", run.gateway.updates[1]["large_text"])

    def test_developer_activity_and_live_settings_use_cached_details(self):
        developing = activity(rich_presence="Developing Achievements")
        run = WorkerHarness([activity(), developing, developing])

        def disable_titles(iteration, harness):
            if iteration == 2:
                harness.worker.replace_config(harness.worker.config | {"use_retroachievements_developer_titles": False})

        run.run(after_iteration=disable_titles)
        self.assertEqual("Developing RetroAchievements", run.gateway.updates[1]["name"])
        self.assertEqual("Mega Game", run.gateway.updates[1]["details"])
        self.assertEqual("Developing Achievements", run.gateway.updates[2]["details"])
        self.assertTrue(run.snapshots[1].mirrored_presence.developer_activity)
        self.assertTrue(run.gateway.updates[1]["buttons"][1]["url"].endswith("/developer/sets"))
        self.assertEqual([["activity"], ["activity"]], run.requests[1:])

    def test_progress_still_updates_status_when_achievement_tooltip_is_disabled(self):
        run = WorkerHarness([activity(), activity(rich_presence_updated_at=NOW + timedelta(seconds=45))],
                            show_achievement_progress=False)
        run.api["progress"].side_effect = None
        run.api["progress"].return_value = progress(achieved=6)
        run.run()
        self.assertEqual("\U0001F3C6 6/10", run.gateway.updates[1]["state"])
        self.assertNotIn("party_size", run.gateway.updates[1])

    def test_controller_seed_avoids_an_immediate_duplicate_poll_and_profile_request(self):
        seeded = activity(visible_role=None, displayable_roles=None)
        run = WorkerHarness([seeded]).run(
            iterations=2, initial_activity=seeded, permissions=3, permissions_loaded=True,
        )
        self.assertEqual([["info", "mode"], ["activity"]], run.requests)
        self.assertTrue(run.snapshots[0].ra_dev_mode)
        self.assertEqual("Developer", run.snapshots[0].ra_role_label)


class InactivityTests(unittest.TestCase):
    def test_unchanged_timestamp_expires_without_more_detail_requests(self):
        run = WorkerHarness([activity()] * 3)

        def advance_clock(iteration, harness):
            harness.now = NOW + timedelta(seconds=131 * iteration)

        run.run(after_iteration=advance_clock)
        self.assertEqual(1, len(run.gateway.updates))
        self.assertIsNone(run.snapshots[1].mirrored_presence)
        self.assertEqual("Not actively playing", run.snapshots[1].status_text)
        self.assertEqual([["activity"], ["activity"]], run.requests[1:])

    def test_no_game_clears_presence_and_returning_game_is_reinitialized(self):
        run = WorkerHarness([activity(), activity(game_id=None, game_title=None), activity()]).run()
        self.assertEqual("Not playing", run.snapshots[1].status_text)
        self.assertIsNone(run.snapshots[1].mirrored_presence)
        self.assertEqual(["activity"], run.requests[1])
        self.assertEqual(["activity", "info", "mode"], run.requests[2])

    def test_timeout_zero_allows_old_activity_but_not_missing_activity(self):
        old = activity(rich_presence_updated_at=NOW - timedelta(days=1))
        run = WorkerHarness([old, replace(old, rich_presence_updated_at=None)], timeout=0).run()
        self.assertEqual(1, len(run.gateway.updates))
        self.assertEqual("Not actively playing", run.snapshots[1].status_text)


class DetailFallbackTests(unittest.TestCase):
    def test_missing_metadata_fetches_only_game_details(self):
        run = WorkerHarness([activity(), activity()])
        del run.api["info"].return_value["ConsoleName"]
        run.run()
        self.assertEqual([["activity", "info", "game", "mode"], ["activity"]], run.requests)
        self.assertEqual(4, run.snapshots[0].mirrored_presence.achievement_count)

    def test_missing_progress_fetches_only_progress(self):
        run = WorkerHarness([activity(), activity()])
        del run.api["info"].return_value["NumAwardedToUser"]
        run.run()
        self.assertEqual([["activity", "info", "progress", "mode"], ["activity"]], run.requests)
        self.assertEqual(4, run.snapshots[0].mirrored_presence.achievement_count)

    def test_empty_successful_response_uses_targeted_fallbacks_once(self):
        run = WorkerHarness([activity(), activity()])
        run.api["info"].return_value = {}
        run.run()
        self.assertEqual([["activity", "info", "game", "progress", "mode"], ["activity"]], run.requests)
        self.assertEqual(int(NOW.timestamp()), run.gateway.updates[1]["start"])

    def test_zero_achievement_counts_are_complete_and_need_no_fallback(self):
        run = WorkerHarness([activity()])
        run.api["info"].return_value = game_info(NumAchievements=0, NumAwardedToUser=0, NumAwardedToUserHardcore=0)
        run.run()
        self.assertEqual([["activity", "info", "mode"]], run.requests)
        self.assertEqual("No achievements available", run.gateway.updates[0]["state"])

    def test_v2_title_supplies_missing_combined_title(self):
        run = WorkerHarness([activity()])
        del run.api["info"].return_value["Title"]
        run.run()
        self.assertEqual([["activity", "info", "mode"]], run.requests)
        self.assertEqual("Mega Game", run.gateway.updates[0]["name"])

    def test_game_without_achievements_works_without_total_playtime(self):
        ping = activity(rich_presence_updated_at=NOW + timedelta(seconds=45))
        run = WorkerHarness([activity(), ping, ping], show_total_playtime=False)
        run.api["progress"].side_effect = None
        run.api["progress"].return_value = progress(achieved=0, hardcore=0, total=0)
        run.run()
        self.assertEqual([
            ["activity", "game", "progress", "mode"], ["activity", "progress", "mode"], ["activity"],
        ], run.requests)
        self.assertEqual(["No achievements available"] * 3, [u["state"] for u in run.gateway.updates])


class PollingFailureTests(unittest.TestCase):
    def test_combined_endpoint_failure_never_triggers_more_requests_in_the_iteration(self):
        errors = [requests.Timeout(), requests.ConnectionError(), APIResponseError()]
        errors += [http_error(status) for status in (401, 403, 429, 500, 503)]
        for error in errors:
            with self.subTest(error=type(error), response=getattr(error, "response", None)):
                run = WorkerHarness([activity()])
                run.api["info"].side_effect = error
                run.run()
                self.assertEqual([["activity", "info"]], run.requests)
                self.assertEqual([60], run.waits)
                self.assertEqual([], run.gateway.updates)
                self.assertFalse(run.snapshots[0].ra_connected)

    def test_v2_failure_clears_presence_and_recovery_reuses_good_details(self):
        for error in (requests.Timeout(), APIResponseError(), http_error(429)):
            with self.subTest(error=type(error)):
                run = WorkerHarness([activity(), error, activity()]).run()
                self.assertEqual([45, 60, 45], run.waits)
                self.assertFalse(run.snapshots[1].ra_connected)
                self.assertIsNone(run.snapshots[1].mirrored_presence)
                self.assertTrue(run.snapshots[2].ra_connected)
                self.assertEqual([["activity"], ["activity"]], run.requests[1:])

    def test_failed_activity_refresh_retries_unchanged_timestamp_until_success(self):
        ping = activity(rich_presence_updated_at=NOW + timedelta(seconds=45))
        run = WorkerHarness([activity(), ping, ping, ping])
        run.api["progress"].side_effect = [requests.Timeout(), progress(achieved=7)]
        run.run()
        self.assertEqual([
            ["activity", "info", "mode"], ["activity", "progress"],
            ["activity", "progress", "mode"], ["activity"],
        ], run.requests)
        self.assertEqual(7, run.snapshots[2].mirrored_presence.achievement_count)

    def test_failed_game_initialization_retries_without_publishing_old_game(self):
        run = WorkerHarness([activity(), activity(game_id=456), activity(game_id=456)])
        run.api["info"].side_effect = [game_info(), requests.Timeout(), game_info()]
        run.run()
        self.assertIsNone(run.snapshots[1].mirrored_presence)
        self.assertEqual([123, 456], [s.mirrored_presence.game_id for s in run.snapshots if s.mirrored_presence])
        self.assertEqual(["activity", "info", "mode"], run.requests[2])

    def test_active_game_mode_lookup_failure_retries_before_publishing(self):
        run = WorkerHarness([activity(), activity()])
        run.api["mode"].side_effect = [(), http_error(503), (), (player_game(123, hard=NOW),)]
        run.run()
        self.assertEqual([60, 45], run.waits)
        self.assertEqual(1, len(run.gateway.updates))
        self.assertEqual("\U0001F3C6 Hardcore", run.gateway.updates[0]["state"])
        self.assertEqual([["activity", "info", "mode", "mode"]] * 2, run.requests)

    def test_incomplete_fallback_response_is_not_cached_as_zero_progress(self):
        run = WorkerHarness([activity(), activity()])
        del run.api["info"].return_value["NumAwardedToUser"]
        run.api["progress"].side_effect = [{}, progress()]
        run.run()
        self.assertEqual([60, 45], run.waits)
        self.assertEqual(1, len(run.gateway.updates))
        self.assertEqual(4, run.snapshots[1].mirrored_presence.achievement_count)

    def test_discord_failure_does_not_repeat_ra_details(self):
        run = WorkerHarness([activity(), activity()])
        run.gateway.update_error = RuntimeError("Discord pipe closed")
        run.run()
        self.assertEqual([60, 45], run.waits)
        self.assertEqual(["activity"], run.requests[1])
        self.assertEqual(1, len(run.gateway.updates))

    def test_discord_unavailable_does_not_repeat_ra_details(self):
        run = WorkerHarness([activity(), activity()])
        run.gateway.connect_available = False
        run.run(after_iteration=lambda _i, h: setattr(h.gateway, "connect_available", True))
        self.assertEqual(["activity"], run.requests[1])
        self.assertEqual(1, len(run.gateway.updates))

    def test_stop_during_combined_request_prevents_further_requests(self):
        run = WorkerHarness([activity()])

        def stop(*_args):
            run.worker._stop_event.set()
            return {}

        run.api["info"].side_effect = stop
        run.run()
        self.assertEqual(1, run.api["info"].call_count)
        for endpoint in ("game", "progress", "mode"):
            run.api[endpoint].assert_not_called()
        self.assertFalse(run.worker.is_busy())


class PollingRolesTests(unittest.TestCase):
    def test_role_changes_are_applied_from_each_poll_without_detail_requests(self):
        run = WorkerHarness([
            activity(), activity(visible_role="writer", displayable_roles=("writer", "developer")),
            activity(visible_role="code-reviewer", displayable_roles=("code-reviewer",)),
            activity(),
        ]).run()
        self.assertEqual(["Artist", "Writer", "Code Reviewer", "Artist"], [s.ra_role_label for s in run.snapshots])
        self.assertEqual([False, True, True, False], [s.ra_dev_mode for s in run.snapshots])
        self.assertEqual([["activity"]] * 3, run.requests[1:])

    def test_unknown_role_uses_profile_permissions_once_per_session(self):
        unknown = activity(visible_role="new-role", displayable_roles=None)
        run = WorkerHarness([unknown, requests.Timeout(), unknown, unknown])
        run.api["profile"].return_value = {"Permissions": 3}
        run.run()
        self.assertEqual(1, run.api["profile"].call_count)
        self.assertEqual("Developer", run.snapshots[0].ra_role_label)
        self.assertTrue(run.snapshots[2].ra_dev_mode)
        self.assertEqual(["activity"], run.requests[2])

    def test_explicit_empty_displayable_roles_override_legacy_dev_mode(self):
        run = WorkerHarness([activity(visible_role=None, displayable_roles=())])
        run.api["profile"].return_value = {"Permissions": 5}
        run.run()
        self.assertEqual("Admin", run.snapshots[0].ra_role_label)
        self.assertFalse(run.snapshots[0].ra_dev_mode)

    def test_profile_failure_uses_backoff_and_retries_without_game_requests(self):
        unknown = activity(visible_role=None, displayable_roles=None)
        run = WorkerHarness([unknown, unknown, unknown])
        run.api["profile"].side_effect = [requests.Timeout(), {"Permissions": 3}]
        run.run()
        self.assertEqual(["activity", "profile"], run.requests[0])
        self.assertEqual([60, 45, 45], run.waits)
        self.assertEqual(["activity"], run.requests[2])

    def test_new_session_and_identity_reset_permissions_and_game_cache(self):
        unknown = activity(visible_role=None, displayable_roles=None)
        run = WorkerHarness([unknown])
        run.api["profile"].side_effect = [{"Permissions": 3}, {"Permissions": 1}]
        run.run()
        run.run(config={"username": "another", "apikey": "another-key"})
        self.assertEqual(2, run.api["profile"].call_count)
        self.assertEqual(2, run.api["info"].call_count)
        self.assertTrue(run.snapshots[0].ra_dev_mode)
        self.assertFalse(run.snapshots[1].ra_dev_mode)
        self.assertEqual(("another", "another-key"), run.api["profile"].call_args.args)

    def test_debug_role_override_needs_no_permissions_request(self):
        with patch.dict("os.environ", {DEBUG_FORCE_ROLE_PERMISSION_ENV: "3"}):
            run = WorkerHarness([activity(visible_role=None, displayable_roles=None)]).run()
        run.api["profile"].assert_not_called()
        self.assertEqual("Developer", run.snapshots[0].ra_role_label)


if __name__ == "__main__":
    unittest.main()
