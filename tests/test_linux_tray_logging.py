import logging
import unittest
from types import SimpleNamespace
from unittest import mock

from desktop.shell.linux import indicator
from desktop.shell.linux.indicator import LinuxIndicatorApp


class FakeStatusIcon:
    def __init__(self, embedded):
        self._embedded = embedded

    def is_embedded(self):
        return self._embedded


class StatusIconEmbeddedLoggingTests(unittest.TestCase):
    def _check(self, status_icon):
        # _check_status_icon_embedded only touches the icon argument and the
        # module logger, so it is safe to call without a fully built app.
        app = LinuxIndicatorApp.__new__(LinuxIndicatorApp)
        logger = logging.getLogger("desktop.shell.linux.indicator")
        with self.assertLogs(logger, level="INFO") as logs:
            app._check_status_icon_embedded(status_icon)
        return "\n".join(logs.output)

    def test_embedded_icon_logs_info(self):
        output = self._check(FakeStatusIcon(True))
        self.assertIn("[TRAY] statusicon_embedded embedded=True", output)

    def test_unembedded_icon_logs_warning(self):
        output = self._check(FakeStatusIcon(False))
        self.assertIn("WARNING", output)
        self.assertIn("[TRAY] statusicon_not_embedded", output)
        self.assertIn("reason=desktop_did_not_show_icon", output)


class FakeSettingsProcess:
    def __init__(self, signal_error=None):
        self.pid = 4613
        self.returncode = None
        self.signals = []
        self._signal_error = signal_error

    def poll(self):
        return self.returncode

    def send_signal(self, number):
        if self._signal_error is not None:
            raise self._signal_error
        self.signals.append(number)

    def terminate(self):
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode


class ReopenSettingsTests(unittest.TestCase):
    """Asking for Settings while a client is up must surface that window."""

    def _app(self, process):
        app = LinuxIndicatorApp.__new__(LinuxIndicatorApp)
        app._shutdown_started = False
        app._settings_open = False
        app._settings_process = process
        return app

    def test_running_client_is_raised_instead_of_launching_a_second_one(self):
        process = FakeSettingsProcess()
        app = self._app(process)

        with mock.patch.object(indicator, "PRESENT_SIGNAL", 10), mock.patch.object(
            indicator.subprocess,
            "Popen",
            side_effect=AssertionError("must not start a second client"),
        ):
            app.open_settings()

        self.assertEqual([10], process.signals)
        self.assertIs(process, app._settings_process)

    def test_unreachable_client_is_replaced(self):
        process = FakeSettingsProcess(signal_error=ProcessLookupError())
        app = self._app(process)
        app._settings_service = SimpleNamespace(
            address="addr", auth_token="token", get_launch_env=dict
        )

        with mock.patch.object(indicator, "PRESENT_SIGNAL", 10), mock.patch.object(
            indicator.subprocess, "Popen", return_value=FakeSettingsProcess()
        ) as popen:
            app.open_settings()

        popen.assert_called_once()
        self.assertIsNot(process, app._settings_process)


if __name__ == "__main__":
    unittest.main()
