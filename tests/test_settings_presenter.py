import unittest

from desktop.shell.settings_presenter import truncate_status_text


class SettingsPresenterTests(unittest.TestCase):
    def test_short_status_text_is_unchanged(self):
        self.assertEqual("Connected", truncate_status_text("Connected"))

    def test_long_status_text_is_truncated_with_ellipsis(self):
        text = "x" * 50

        self.assertEqual(("x" * 42) + "...", truncate_status_text(text))


if __name__ == "__main__":
    unittest.main()
