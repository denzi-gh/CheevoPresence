import logging
import os
import tempfile
import unittest

from desktop.runtime.diagnostics import (
    collect_linux_diagnostics,
    log_startup_diagnostics,
    parse_os_release,
)


class OsReleaseParserTests(unittest.TestCase):
    def test_parses_quoted_and_unquoted_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "os-release")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    '# comment line\n'
                    'ID=ubuntu\n'
                    'VERSION_ID="24.04"\n'
                    "PRETTY_NAME='Kubuntu 24.04'\n"
                    "\n"
                    "INVALID_LINE_WITHOUT_EQUALS\n"
                )
            data = parse_os_release(path)
        self.assertEqual("ubuntu", data["ID"])
        self.assertEqual("24.04", data["VERSION_ID"])
        self.assertEqual("Kubuntu 24.04", data["PRETTY_NAME"])
        self.assertNotIn("INVALID_LINE_WITHOUT_EQUALS", data)

    def test_missing_file_does_not_crash(self):
        self.assertEqual({}, parse_os_release("/nonexistent/os-release"))


class LinuxDiagnosticsTests(unittest.TestCase):
    def test_collect_linux_diagnostics_returns_expected_keys(self):
        diagnostics = collect_linux_diagnostics()
        for key in (
            "distro_id",
            "distro_version",
            "pretty_name",
            "desktop",
            "session_type",
            "display_set",
            "wayland_display_set",
        ):
            self.assertIn(key, diagnostics)
        self.assertIsInstance(diagnostics["display_set"], bool)


class StartupDiagnosticsTests(unittest.TestCase):
    def test_logs_paths_event_with_log_file(self):
        logger = logging.getLogger("desktop.runtime.diagnostics")
        with self.assertLogs(logger, level="INFO") as logs:
            log_startup_diagnostics()
        output = "\n".join(logs.output)
        self.assertIn("[STARTUP] app_started", output)
        self.assertIn("[PATHS] resolved", output)
        self.assertIn("log_file=", output)


if __name__ == "__main__":
    unittest.main()
