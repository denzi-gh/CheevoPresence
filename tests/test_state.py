"""Tests for WorkerState.from_dict / MirroredPresence.from_dict."""

import unittest

from desktop.runtime.state import MirroredPresence, WorkerState


class MirroredPresenceFromDictTests(unittest.TestCase):
    def test_none_and_non_dict_yield_none(self):
        self.assertIsNone(MirroredPresence.from_dict(None))
        self.assertIsNone(MirroredPresence.from_dict("nope"))

    def test_coerces_ints_and_filters_buttons(self):
        presence = MirroredPresence.from_dict(
            {
                "game_id": "123",
                "achievement_count": "4",
                "achievement_total": None,
                "title": "Mega Game",
                "buttons": ["not-a-dict", {"label": "x", "url": "y"}],
            }
        )

        self.assertEqual(123, presence.game_id)
        self.assertEqual(4, presence.achievement_count)
        self.assertEqual(0, presence.achievement_total)
        self.assertEqual([{"label": "x", "url": "y"}], presence.buttons)

    def test_non_list_buttons_become_empty(self):
        presence = MirroredPresence.from_dict({"buttons": "oops"})
        self.assertEqual([], presence.buttons)


class WorkerStateFromDictTests(unittest.TestCase):
    def test_non_dict_yields_safe_defaults(self):
        state = WorkerState.from_dict(None)

        self.assertFalse(state.running)
        self.assertEqual("disconnected", state.current_status)
        self.assertEqual("Not running", state.status_text)
        self.assertIsNone(state.ra_permissions)
        self.assertIsNone(state.mirrored_presence)

    def test_invalid_permissions_coerce_to_none(self):
        self.assertIsNone(WorkerState.from_dict({"ra_permissions": "abc"}).ra_permissions)
        self.assertEqual(3, WorkerState.from_dict({"ra_permissions": "3"}).ra_permissions)

    def test_nested_mirrored_presence_is_rebuilt(self):
        state = WorkerState.from_dict(
            {"running": True, "mirrored_presence": {"title": "Mega Game", "buttons": []}}
        )

        self.assertTrue(state.running)
        self.assertIsInstance(state.mirrored_presence, MirroredPresence)
        self.assertEqual("Mega Game", state.mirrored_presence.title)


if __name__ == "__main__":
    unittest.main()
