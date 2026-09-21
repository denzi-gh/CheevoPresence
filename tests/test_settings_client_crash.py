import os
import unittest
from unittest.mock import Mock, patch

from desktop.shell import settings_client
from desktop.shell.ipc import SETTINGS_ADDRESS_ENV, SETTINGS_AUTH_ENV


class SettingsClientCrashTests(unittest.TestCase):
    def test_fatal_startup_error_is_saved_as_a_settings_crash(self):
        reporter = Mock()
        platform = object()
        error = RuntimeError("settings startup failed")

        with patch.dict(
            os.environ,
            {
                SETTINGS_ADDRESS_ENV: "tcp://127.0.0.1:1234",
                SETTINGS_AUTH_ENV: "settings-test-auth-token",
            },
        ), patch(
            "desktop.runtime.logging_setup.setup_child_logging"
        ) as setup_logging, patch(
            "desktop.platform.get_platform_services",
            return_value=platform,
        ), patch(
            "desktop.runtime.crash_reporting.install_crash_reporting",
            return_value=reporter,
        ) as install_reporting, patch(
            "desktop.shell.ipc.RemoteAppController",
            side_effect=error,
        ), patch.object(
            settings_client,
            "_show_startup_error",
        ) as show_error:
            settings_client.main()

        setup_logging.assert_called_once_with()
        install_reporting.assert_called_once_with(platform, process_role="settings")
        capture = reporter.capture_exception.call_args
        self.assertIs(RuntimeError, capture.args[0])
        self.assertIs(error, capture.args[1])
        self.assertEqual("settings_client_main", capture.kwargs["origin"])
        show_error.assert_called_once_with("settings startup failed")


if __name__ == "__main__":
    unittest.main()
