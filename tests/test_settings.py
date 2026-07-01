import unittest

from desktop.core.settings import normalize_config


class SettingsTests(unittest.TestCase):
    def test_dev_mode_defaults_to_disabled_when_missing(self):
        cfg = normalize_config({})

        self.assertFalse(cfg["dev_mode"])

    def test_dev_mode_accepts_boolean_value(self):
        cfg = normalize_config({"dev_mode": True})

        self.assertTrue(cfg["dev_mode"])

    def test_dev_mode_accepts_string_values(self):
        self.assertTrue(normalize_config({"dev_mode": "on"})["dev_mode"])
        self.assertFalse(normalize_config({"dev_mode": "off"})["dev_mode"])

    def test_developer_titles_default_to_enabled_when_missing(self):
        cfg = normalize_config({})

        self.assertTrue(cfg["use_retroachievements_developer_titles"])

    def test_developer_titles_accept_boolean_value(self):
        cfg = normalize_config({"use_retroachievements_developer_titles": False})

        self.assertFalse(cfg["use_retroachievements_developer_titles"])

    def test_developer_titles_accept_string_value(self):
        cfg = normalize_config({"use_retroachievements_developer_titles": "off"})

        self.assertFalse(cfg["use_retroachievements_developer_titles"])

    def test_developer_sets_button_defaults_to_enabled_when_missing(self):
        cfg = normalize_config({})

        self.assertTrue(cfg["show_developer_sets_button"])

    def test_developer_sets_button_accepts_boolean_value(self):
        cfg = normalize_config({"show_developer_sets_button": False})

        self.assertFalse(cfg["show_developer_sets_button"])

    def test_developer_sets_button_accepts_string_value(self):
        cfg = normalize_config({"show_developer_sets_button": "off"})

        self.assertFalse(cfg["show_developer_sets_button"])


if __name__ == "__main__":
    unittest.main()
