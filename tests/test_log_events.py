import ast
import logging
import unittest
from pathlib import Path

from desktop.core.log_events import (
    REDACTED,
    format_event,
    log_event,
    redact_log_text,
    register_log_secret,
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

    def test_embedded_url_query_is_stripped(self):
        value = redact_log_text(
            "request failed for https://retroachievements.org/API/a?y=SECRETKEY"
        )
        self.assertEqual(
            "request failed for https://retroachievements.org/API/a",
            value,
        )

    def test_nested_sensitive_values_are_redacted(self):
        value = sanitize_log_value(
            {
                "context": {"access_token": "NESTED_SECRET"},
                "attempt": 2,
            }
        )
        self.assertNotIn("NESTED_SECRET", value)
        self.assertIn(REDACTED, value)

    def test_cyclic_nested_values_remain_loggable(self):
        value = {}
        value["self"] = value

        output = sanitize_log_value(value)

        self.assertIn("<cycle>", output)

    def test_sensitive_assignments_in_plain_text_are_redacted(self):
        value = redact_log_text("failure context={'apikey': 'PLAIN_SECRET'}")
        self.assertNotIn("PLAIN_SECRET", value)
        self.assertIn(REDACTED, value)

    def test_registered_secret_is_redacted_from_arbitrary_text(self):
        register_log_secret("REGISTERED_SECRET_VALUE")
        value = redact_log_text("unexpected failure REGISTERED_SECRET_VALUE in callback")
        self.assertNotIn("REGISTERED_SECRET_VALUE", value)
        self.assertIn(REDACTED, value)

    def test_control_characters_are_escaped(self):
        value = sanitize_log_value("first\nsecond\tthird\x00")
        self.assertNotIn("\n", value)
        self.assertNotIn("\t", value)
        self.assertNotIn("\x00", value)
        self.assertIn(r"\n", value)
        self.assertIn(r"\t", value)
        self.assertIn(r"\x00", value)

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


class StructuredLoggingPolicyTests(unittest.TestCase):
    def test_desktop_modules_do_not_bypass_structured_logging(self):
        project_root = Path(__file__).resolve().parents[1]
        violations = []
        raw_methods = {"debug", "info", "warning", "error", "exception", "critical"}
        for path in (project_root / "desktop").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in raw_methods:
                    continue
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "logger":
                    violations.append(f"{path.relative_to(project_root)}:{node.lineno}")

        self.assertEqual([], violations, "Use log_event() at: " + ", ".join(violations))


if __name__ == "__main__":
    unittest.main()
