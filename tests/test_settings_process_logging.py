import logging
import subprocess
import unittest
from unittest import mock

from desktop.core.log_events import register_log_secret
from desktop.runtime.logging_setup import (
    LOG_SESSION_ENV,
    ChildLogFormatter,
    get_log_session_id,
)
from desktop.shell import settings_process


class FakeProcess:
    pid = 8124
    stdout = None


class SettingsProcessLoggingTests(unittest.TestCase):
    def test_structured_child_record_is_forwarded_with_original_logger_and_level(self):
        record = logging.LogRecord(
            "desktop.shell.settings_client",
            logging.WARNING,
            "",
            0,
            "[SETTINGS] child_problem error_type=RuntimeError",
            (),
            None,
        )
        encoded = ChildLogFormatter().format(record)

        with self.assertLogs("desktop.shell.settings_client", level="WARNING") as logs:
            settings_process._forward_settings_output_line(encoded, fallback_pid=999)

        self.assertIn("[SETTINGS] child_problem", logs.output[0])
        self.assertIn("WARNING", logs.output[0])

    def test_unstructured_child_output_is_kept(self):
        with self.assertLogs("desktop.shell.settings_process", level="INFO") as logs:
            settings_process._forward_settings_output_line(
                "native library diagnostic\n",
                fallback_pid=8124,
            )

        self.assertIn("[SETTINGS] client_output", logs.output[0])
        self.assertIn("native library diagnostic", logs.output[0])
        self.assertIn("pid=8124", logs.output[0])

    def test_child_protocol_redacts_registered_secrets(self):
        secret = "SETTINGS_CHILD_SECRET"
        register_log_secret(secret)
        record = logging.LogRecord(
            "desktop.shell.settings_client",
            logging.ERROR,
            "",
            0,
            f"child failed with {secret}",
            (),
            None,
        )

        encoded = ChildLogFormatter().format(record)

        self.assertNotIn(secret, encoded)
        self.assertIn("<redacted>", encoded)

    def test_launcher_captures_both_stdout_and_stderr(self):
        fake_process = FakeProcess()
        with mock.patch.object(
            settings_process.subprocess,
            "Popen",
            return_value=fake_process,
        ) as popen, mock.patch.object(settings_process.threading, "Thread") as thread:
            result = settings_process.launch_settings_process(
                ["python", "settings-client"],
                {"ENV": "value"},
                start_new_session=True,
            )

        self.assertIs(fake_process, result)
        popen.assert_called_once_with(
            ["python", "settings-client"],
            env={"ENV": "value", LOG_SESSION_ENV: get_log_session_id()},
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        thread.return_value.start.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
