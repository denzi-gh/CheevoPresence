"""Regression tests: the IPC auth token must never appear on the command line.

Command lines are visible to other processes (Task Manager/WMI on Windows,
/proc/<pid>/cmdline on Linux); the token may only travel via the launch
environment (SettingsHostService.get_launch_env()).
"""

import unittest

from desktop.shell.ipc import SETTINGS_ADDRESS_ENV, SETTINGS_AUTH_ENV
from desktop.shell.linux.indicator import LinuxIndicatorApp
from desktop.shell.windows.tray import TrayApp


class _StubSettingsService:
    address = "127.0.0.1:54321"
    auth_token = "super-secret-token"

    def get_launch_env(self):
        return {
            SETTINGS_ADDRESS_ENV: self.address,
            SETTINGS_AUTH_ENV: self.auth_token,
        }


def _settings_command(app_cls):
    app = object.__new__(app_cls)
    app._settings_service = _StubSettingsService()
    return app_cls._settings_command(app)


class SettingsClientLaunchTests(unittest.TestCase):
    def assert_no_secrets_in_command(self, command):
        for part in command:
            self.assertNotIn(_StubSettingsService.auth_token, str(part))
            self.assertNotIn(_StubSettingsService.address, str(part))

    def test_windows_settings_command_omits_token_and_address(self):
        command = _settings_command(TrayApp)

        self.assert_no_secrets_in_command(command)
        self.assertIn("--windows-settings-client", command)

    def test_linux_settings_command_omits_token_and_address(self):
        command = _settings_command(LinuxIndicatorApp)

        self.assert_no_secrets_in_command(command)
        self.assertIn("--linux-settings-client", command)


if __name__ == "__main__":
    unittest.main()
