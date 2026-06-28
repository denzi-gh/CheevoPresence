import unittest

from desktop.core.settings import normalize_config


class SettingsTests(unittest.TestCase):
    def test_developer_titles_default_to_enabled_when_missing(self):
        cfg = normalize_config({})

        self.assertTrue(cfg["use_retroachievements_developer_titles"])

    def test_developer_titles_accept_boolean_value(self):
        cfg = normalize_config({"use_retroachievements_developer_titles": False})

        self.assertFalse(cfg["use_retroachievements_developer_titles"])

    def test_developer_titles_accept_string_value(self):
        cfg = normalize_config({"use_retroachievements_developer_titles": "off"})

        self.assertFalse(cfg["use_retroachievements_developer_titles"])


if __name__ == "__main__":
    unittest.main()
