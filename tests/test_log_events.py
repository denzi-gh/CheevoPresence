import logging
import unittest

from desktop.runtime.log_events import (
    REDACTED,
    format_event,
    log_event,
    sanitize_log_fields,
    sanitize_log_value,
)


class FormatEventTests(unittest.TestCase):
    def test_basic_event(self):
        self.assertEqual(
            "[TRAY] backend_selected backend=appindicator",
            format_event("TRAY", "backend_selected", backend="appindicator"),
        )

    def test_booleans_and_none(self):
        self.assertEqual(
            "[TRAY] modules_loaded gtk=True appindicator=False pipe=none",
            format_event("TRAY", "modules_loaded", gtk=True, appindicator=False, pipe=None),
        )

    def test_values_with_spaces_are_quoted(self):
        self.assertEqual(
            '[PLATFORM] environment pretty_name="Ubuntu 24.04 LTS"',
            format_event("PLATFORM", "environment", pretty_name="Ubuntu 24.04 LTS"),
        )

    def test_empty_string_is_quoted(self):
        self.assertEqual('[X] e v=""', format_event("X", "e", v=""))


class SanitizeTests(unittest.TestCase):
    def test_sensitive_keys_are_redacted(self):
        fields = sanitize_log_fields(
            {
                "apikey": "SECRET",
                "apikey_protected": "PROTECTED",
                "token": "TOK",
                "authorization": "Bearer abc",
                "username_present": True,
            }
        )
        self.assertEqual(REDACTED, fields["apikey"])
        self.assertEqual(REDACTED, fields["apikey_protected"])
        self.assertEqual(REDACTED, fields["token"])
        self.assertEqual(REDACTED, fields["authorization"])
        self.assertEqual("True", fields["username_present"])

    def test_redaction_is_case_insensitive(self):
        self.assertEqual(REDACTED, sanitize_log_fields({"APIKey": "x"})["APIKey"])

    def test_url_query_is_stripped(self):
        value = sanitize_log_value(
            "https://retroachievements.org/API/API_GetUserSummary.php?z=user&y=SECRETKEY"
        )
        self.assertEqual("https://retroachievements.org/API/API_GetUserSummary.php", value)
        self.assertNotIn("SECRETKEY", value)

    def test_event_with_apikey_never_leaks(self):
        message = format_event("RA", "poll", apikey="SUPERSECRET", endpoint="user_summary")
        self.assertNotIn("SUPERSECRET", message)
        self.assertIn("apikey=<redacted>", message)


class LogEventTests(unittest.TestCase):
    def test_log_event_emits_formatted_message(self):
        logger = logging.getLogger("test.log_events")
        with self.assertLogs(logger, level="INFO") as logs:
            log_event(logger, "CONFIG", "save", success=True, apikey="SECRET")
        output = "\n".join(logs.output)
        self.assertIn("[CONFIG] save success=True apikey=<redacted>", output)
        self.assertNotIn("SECRET", output)

    def test_log_event_respects_level(self):
        logger = logging.getLogger("test.log_events.level")
        with self.assertLogs(logger, level="WARNING") as logs:
            log_event(logger, "RA", "request_failed", level=logging.WARNING, error_type="Timeout")
        self.assertIn("WARNING", logs.output[0])
        self.assertIn("[RA] request_failed error_type=Timeout", logs.output[0])


if __name__ == "__main__":
    unittest.main()
