import threading
import unittest
from unittest.mock import patch

from desktop.core.roles import DEBUG_FORCE_ROLE_PERMISSION_ENV
from desktop.runtime.presence_builder import PresenceBuilder
from desktop.runtime.state import MirroredPresence, WorkerState
from desktop.runtime.worker import RPCWorker


def _presence_snapshot(**overrides):
    payload = {
        "game_id": 123,
        "title": "Mega Game",
        "details": "Playing Level 1",
        "state": "\U0001F3C6 Softcore",
        "console_name": "NES",
        "game_icon_url": "https://media.retroachievements.org/Images/000123.png",
        "large_text": "4/10 achievements",
        "achievement_count": 4,
        "achievement_total": 10,
        "show_achievement_progress": True,
        "buttons": [
            {
                "label": "View on RetroAchievements",
                "url": "https://retroachievements.org/game/123",
            }
        ],
        "developer_activity": False,
    }
    payload.update(overrides)
    return MirroredPresence(**payload)


class WorkerStateTests(unittest.TestCase):
    def test_get_state_returns_status_snapshot(self):
        worker = RPCWorker(initial_config={"username": "SomeUser"}, console_icons={})

        worker.status_callback("connected", "Playing")
        worker.set_ra_status(True)
        worker.set_ra_role(2)
        state = worker.get_state()

        self.assertIsInstance(state, WorkerState)
        self.assertFalse(state.running)
        self.assertFalse(state.is_busy)
        self.assertFalse(state.is_stopping)
        self.assertEqual("connected", state.current_status)
        self.assertEqual("Playing", state.status_text)
        self.assertTrue(state.ra_connected)
        self.assertEqual("Connected as SomeUser", state.ra_status_text)
        self.assertEqual(2, state.ra_permissions)
        self.assertEqual("Junior Developer", state.ra_role_label)
        self.assertEqual("junior_developer", state.ra_role_tier)
        self.assertTrue(worker.config["dev_mode"])

    def test_ra_status_clear_removes_role_snapshot(self):
        worker = RPCWorker(initial_config={}, console_icons={})
        worker.set_ra_status(True)
        worker.set_ra_role(3)

        worker.set_ra_status(False)
        state = worker.get_state()

        self.assertFalse(state.ra_connected)
        self.assertIsNone(state.ra_permissions)
        self.assertEqual("", state.ra_role_label)
        self.assertEqual("", state.ra_role_tier)

    def test_role_refresh_clears_stale_manual_dev_mode(self):
        worker = RPCWorker(initial_config={"dev_mode": True}, console_icons={})

        worker.set_ra_role(1)

        self.assertFalse(worker.config["dev_mode"])

    def test_debug_forced_permission_displays_selected_role(self):
        worker = RPCWorker(initial_config={"dev_mode": False}, console_icons={})

        with patch.dict("os.environ", {DEBUG_FORCE_ROLE_PERMISSION_ENV: "5"}):
            worker.set_ra_role(1)

        state = worker.get_state()
        self.assertEqual(5, state.ra_permissions)
        self.assertEqual("Admin", state.ra_role_label)
        self.assertEqual("admin", state.ra_role_tier)
        self.assertTrue(worker.config["dev_mode"])

    def test_debug_forced_registered_permission_clears_role(self):
        worker = RPCWorker(initial_config={"dev_mode": True}, console_icons={})

        with patch.dict("os.environ", {DEBUG_FORCE_ROLE_PERMISSION_ENV: "1"}):
            worker.set_ra_role(2)

        state = worker.get_state()
        self.assertIsNone(state.ra_permissions)
        self.assertEqual("", state.ra_role_label)
        self.assertEqual("", state.ra_role_tier)
        self.assertFalse(worker.config["dev_mode"])

    def test_ra_connected_status_uses_generic_text_without_username(self):
        worker = RPCWorker(initial_config={}, console_icons={})

        worker.set_ra_status(True)
        state = worker.get_state()

        self.assertEqual("Connected to RetroAchievements", state.ra_status_text)

    def test_stop_clears_connected_ra_status_text(self):
        worker = RPCWorker(initial_config={"username": "SomeUser"}, console_icons={})
        worker.running = True
        worker.set_ra_status(True)

        worker.stop()
        state = worker.get_state()

        self.assertFalse(state.ra_connected)
        self.assertEqual("Not connected to RetroAchievements", state.ra_status_text)

    def test_busy_and_stopping_are_derived_from_thread_lifecycle(self):
        worker = RPCWorker(initial_config={}, console_icons={})
        stop_event = threading.Event()
        thread = threading.Thread(target=stop_event.wait)
        thread.start()
        try:
            worker.thread = thread
            worker.running = False

            state = worker.get_state()

            self.assertTrue(state.is_busy)
            self.assertTrue(state.is_stopping)
            self.assertTrue(worker.is_busy())
            self.assertTrue(worker.is_stopping())
        finally:
            stop_event.set()
            thread.join(timeout=1)

    def test_status_callback_invokes_external_callback_outside_state_update(self):
        seen = []
        worker = RPCWorker(
            status_callback=lambda status, text: seen.append((status, text)),
            initial_config={},
            console_icons={},
        )

        worker.status_callback("error", "Discord is not open")

        self.assertEqual([("error", "Discord is not open")], seen)
        self.assertEqual("error", worker.get_state().current_status)

    def test_get_state_includes_mirrored_presence_snapshot(self):
        worker = RPCWorker(initial_config={}, console_icons={})
        worker.mirrored_presence = _presence_snapshot()

        state = worker.get_state()

        self.assertEqual("Mega Game", state.mirrored_presence.title)
        self.assertEqual("NES", state.mirrored_presence.console_name)
        self.assertEqual(4, state.mirrored_presence.achievement_count)

    def test_ra_status_clear_removes_mirrored_presence_snapshot(self):
        worker = RPCWorker(initial_config={}, console_icons={})
        worker.mirrored_presence = _presence_snapshot()

        worker.set_ra_status(False)

        self.assertIsNone(worker.get_state().mirrored_presence)

    def test_presence_disconnect_removes_mirrored_presence_snapshot(self):
        worker = RPCWorker(initial_config={}, console_icons={})
        worker.mirrored_presence = _presence_snapshot()

        worker._disconnect_rpc()

        self.assertIsNone(worker.get_state().mirrored_presence)

    def test_mirrored_presence_uses_discord_payload_fields(self):
        worker = RPCWorker(
            initial_config={
                "show_profile_button": True,
                "show_gamepage_button": True,
                "show_achievement_progress": False,
                "use_retroachievements_developer_titles": True,
            },
            console_icons={"7": "nes-icon"},
        )
        presence = PresenceBuilder(worker.config, worker.console_icons).build(
            username="some user",
            last_game_id=123,
            rich_presence_message="Developing Achievements",
            game_data={
                "GameTitle": "Mega Game",
                "ConsoleName": "NES",
                "ConsoleID": "7",
                "ImageIcon": "/Images/000123.png",
            },
            progress_data={
                "123": {
                    "NumPossibleAchievements": 10,
                    "NumAchieved": 4,
                    "NumAchievedHardcore": 3,
                }
            },
            start_time=99,
        )

        worker._set_mirrored_presence(123, presence)
        snapshot = worker.get_state().mirrored_presence

        self.assertEqual("Developing RetroAchievements", snapshot.title)
        self.assertEqual("Mega Game", snapshot.details)
        self.assertFalse(snapshot.show_achievement_progress)
        self.assertEqual(2, len(snapshot.buttons))
        self.assertTrue(snapshot.developer_activity)

    def test_presence_builder_uses_latest_worker_config_snapshot(self):
        worker = RPCWorker(
            initial_config={"use_retroachievements_developer_titles": True},
            console_icons={},
        )
        game_data = {
            "GameTitle": "Mega Game",
            "ConsoleName": "NES",
            "ConsoleID": "7",
            "ImageIcon": "/Images/000123.png",
        }
        progress_data = {
            "123": {
                "NumPossibleAchievements": 10,
                "NumAchieved": 4,
                "NumAchievedHardcore": 3,
            }
        }

        first = worker._presence_builder().build(
            username="some user",
            last_game_id=123,
            rich_presence_message="Developing Achievements",
            game_data=game_data,
            progress_data=progress_data,
            start_time=99,
        )
        worker.config = {
            **worker.config,
            "use_retroachievements_developer_titles": False,
        }
        second = worker._presence_builder().build(
            username="some user",
            last_game_id=123,
            rich_presence_message="Developing Achievements",
            game_data=game_data,
            progress_data=progress_data,
            start_time=99,
        )

        self.assertEqual("Developing RetroAchievements", first.update_kwargs["name"])
        self.assertEqual("Developing Achievements", second.update_kwargs["details"])
        self.assertNotEqual(first.update_kwargs["name"], second.update_kwargs["name"])


if __name__ == "__main__":
    unittest.main()
