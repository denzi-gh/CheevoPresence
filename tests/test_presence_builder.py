import unittest

from pypresence import ActivityType

from desktop.core.api import APIResponseError
from desktop.runtime.presence_builder import PresenceBuilder


def _game(**overrides):
    payload = {
        "GameTitle": "Mega Game",
        "ConsoleName": "NES",
        "ConsoleID": "7",
        "ImageIcon": "/Images/000123.png",
    }
    payload.update(overrides)
    return payload


def _progress(**overrides):
    payload = {
        "123": {
            "NumPossibleAchievements": 10,
            "NumAchieved": 4,
            "NumAchievedHardcore": 3,
        }
    }
    payload["123"].update(overrides)
    return payload


class PresenceBuilderTests(unittest.TestCase):
    def _builder(self, **config):
        defaults = {
            "show_profile_button": True,
            "show_gamepage_button": True,
            "show_achievement_progress": True,
        }
        defaults.update(config)
        return PresenceBuilder(defaults, {"7": "nes-icon"})

    def test_builds_default_presence_payload(self):
        result = self._builder().build(
            username="some user",
            last_game_id=123,
            rich_presence_message="Playing Level 1",
            game_data=_game(),
            progress_data=_progress(),
            start_time=99,
        )

        self.assertEqual(ActivityType.PLAYING, result.update_kwargs["activity_type"])
        self.assertEqual("Mega Game", result.update_kwargs["name"])
        self.assertEqual("Playing Level 1", result.update_kwargs["details"])
        self.assertEqual("\U0001F3C6 Softcore", result.update_kwargs["state"])
        self.assertEqual(99, result.update_kwargs["start"])
        self.assertEqual(
            "https://media.retroachievements.org/Images/000123.png",
            result.update_kwargs["large_image"],
        )
        self.assertEqual("4/10 achievements", result.update_kwargs["large_text"])
        self.assertEqual("nes-icon", result.update_kwargs["small_image"])
        self.assertEqual("NES", result.update_kwargs["small_text"])
        self.assertEqual("ra_123", result.update_kwargs["party_id"])
        self.assertEqual([4, 10], result.update_kwargs["party_size"])
        self.assertEqual(2, result.button_count)
        self.assertIn("some%20user", result.update_kwargs["buttons"][1]["url"])

    def test_hardcore_progress_uses_hardcore_count(self):
        result = self._builder().build(
            "user",
            123,
            "Playing",
            _game(),
            _progress(NumAchieved=4, NumAchievedHardcore=4),
            1,
        )

        self.assertEqual("\U0001F3C6 Hardcore", result.update_kwargs["state"])
        self.assertEqual([4, 10], result.update_kwargs["party_size"])

    def test_can_hide_buttons_and_achievement_counter(self):
        result = self._builder(
            show_profile_button=False,
            show_gamepage_button=False,
            show_achievement_progress=False,
        ).build("user", 123, "", _game(), _progress(), 1)

        self.assertIsNone(result.update_kwargs["buttons"])
        self.assertEqual("Mega Game", result.update_kwargs["large_text"])
        self.assertNotIn("party_id", result.update_kwargs)
        self.assertIsNone(result.update_kwargs["details"])

    def test_developer_activity_decorates_title_and_metadata(self):
        result = self._builder().build(
            "user",
            123,
            "developing achievements",
            _game(),
            _progress(),
            1,
        )

        self.assertTrue(result.developer_activity)
        self.assertIn("Mega Game", result.update_kwargs["name"])
        self.assertNotEqual("Mega Game", result.update_kwargs["name"])

    def test_rejects_unexpected_payload_shapes(self):
        with self.assertRaises(APIResponseError):
            self._builder().build("user", 123, "Playing", _game(GameTitle=123), _progress(), 1)

        with self.assertRaises(APIResponseError):
            self._builder().build("user", 123, "Playing", _game(), {"123": []}, 1)


if __name__ == "__main__":
    unittest.main()
