import os
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from desktop.core.log_events import register_log_secret
from desktop.runtime.crash_reporting import (
    MAX_CRASH_REPORT_BYTES,
    MAX_CRASH_REPORTS,
    CrashReporter,
)
from desktop.runtime.storage import get_crash_dir


class FakePlatform:
    def __init__(self, root):
        self.root = root

    def get_config_dir(self, app_name, runtime_root_dir):
        return os.path.join(self.root, app_name)


def _exception_info(message="crash for testing"):
    try:
        raise RuntimeError(message)
    except RuntimeError:
        return sys.exc_info()


class CrashReporterTests(unittest.TestCase):
    def test_report_is_redacted_bounded_and_owner_only(self):
        secret = "CRASH_REPORT_SECRET_12345"
        register_log_secret(secret)
        exc_type, exc_value, exc_traceback = _exception_info(
            f"failed with {secret} at https://example.test/path?token={secret}"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = CrashReporter(FakePlatform(tmpdir), process_role="host")
            with self.assertLogs(
                "desktop.runtime.crash_reporting",
                level="CRITICAL",
            ) as logs:
                report_path = reporter.capture_exception(
                    exc_type,
                    exc_value,
                    exc_traceback,
                    origin="test_boundary",
                    thread_name="TestThread",
                )

            with open(report_path, "r", encoding="utf-8") as handle:
                report = handle.read()

            self.assertNotIn(secret, report)
            self.assertNotIn("?token=", report)
            self.assertIn("CheevoPresence crash report", report)
            self.assertIn("process_role=host", report)
            self.assertIn("origin=test_boundary", report)
            self.assertIn("thread=TestThread", report)
            self.assertIn("RuntimeError", report)
            self.assertIn("report_saved=True", logs.records[0].getMessage())
            self.assertLessEqual(os.path.getsize(report_path), MAX_CRASH_REPORT_BYTES)
            if os.name != "nt":
                self.assertEqual(0o600, os.stat(report_path).st_mode & 0o777)

    def test_oversized_report_is_truncated_on_a_utf8_boundary(self):
        exc_type, exc_value, exc_traceback = _exception_info("\U0001f4a5" * 100_000)
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "desktop.runtime.crash_reporting.log_event"
        ):
            report_path = CrashReporter(FakePlatform(tmpdir)).capture_exception(
                exc_type,
                exc_value,
                exc_traceback,
            )

            with open(report_path, "r", encoding="utf-8") as handle:
                report = handle.read()
            report_size = os.path.getsize(report_path)

        self.assertLessEqual(report_size, MAX_CRASH_REPORT_BYTES)
        self.assertTrue(report.endswith("...<crash report truncated>\n"))

    def test_retention_keeps_only_newest_reports(self):
        exc_type, exc_value, exc_traceback = _exception_info()
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "desktop.runtime.crash_reporting.log_event"
        ):
            platform = FakePlatform(tmpdir)
            reporter = CrashReporter(platform)
            for index in range(MAX_CRASH_REPORTS + 3):
                reporter.capture_exception(
                    exc_type,
                    exc_value,
                    exc_traceback,
                    origin=f"retention_{index}",
                )

            reports = [
                name
                for name in os.listdir(get_crash_dir(platform))
                if name.startswith("crash-") and name.endswith(".log")
            ]

        self.assertEqual(MAX_CRASH_REPORTS, len(reports))

    def test_hooks_capture_then_delegate_and_ignore_normal_exit(self):
        previous_sys_hook = Mock()
        previous_thread_hook = Mock()
        reporter = CrashReporter(process_role="test")
        exc_type, exc_value, exc_traceback = _exception_info()
        thread_args = SimpleNamespace(
            exc_type=exc_type,
            exc_value=exc_value,
            exc_traceback=exc_traceback,
            thread=SimpleNamespace(name="FailedWorker"),
        )

        with patch.object(sys, "excepthook", previous_sys_hook), patch.object(
            threading,
            "excepthook",
            previous_thread_hook,
        ), patch.object(reporter, "capture_exception") as capture:
            reporter.install()
            try:
                sys.excepthook(exc_type, exc_value, exc_traceback)
                threading.excepthook(thread_args)
                sys.excepthook(SystemExit, SystemExit(0), None)
            finally:
                reporter.uninstall()

            self.assertIs(sys.excepthook, previous_sys_hook)
            self.assertIs(threading.excepthook, previous_thread_hook)

        self.assertEqual(2, capture.call_count)
        self.assertEqual("main_thread", capture.call_args_list[0].kwargs["origin"])
        self.assertEqual(
            "background_thread",
            capture.call_args_list[1].kwargs["origin"],
        )
        self.assertEqual("FailedWorker", capture.call_args_list[1].kwargs["thread_name"])
        self.assertEqual(2, previous_sys_hook.call_count)
        previous_thread_hook.assert_called_once_with(thread_args)

    def test_report_write_failure_never_masks_original_exception(self):
        reporter = CrashReporter()
        exc_type, exc_value, exc_traceback = _exception_info()

        with patch.object(
            reporter,
            "_write_report",
            side_effect=OSError("disk unavailable"),
        ), patch("desktop.runtime.crash_reporting.log_event") as log:
            report_path = reporter.capture_exception(
                exc_type,
                exc_value,
                exc_traceback,
            )

        self.assertIsNone(report_path)
        self.assertFalse(log.call_args.kwargs["report_saved"])
        self.assertEqual("OSError", log.call_args.kwargs["capture_error_type"])


if __name__ == "__main__":
    unittest.main()
