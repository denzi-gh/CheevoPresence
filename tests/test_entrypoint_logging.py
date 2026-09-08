import unittest
from unittest import mock

from desktop.shell import entrypoint


class FakePlatform:
    def __init__(self, *, acquired=True, helper=False):
        self.acquired = acquired
        self.helper = helper
        self.exit_requested = False
        self.notified = False
        self.cleaned = False

    def handle_special_args(self, _argv):
        return self.helper

    def request_running_app_exit(self):
        self.exit_requested = True
        return True

    def acquire_single_instance(self):
        return self.acquired

    def notify_already_running(self):
        self.notified = True

    def cleanup_startup_artifacts(self):
        self.cleaned = True


class EntrypointLoggingOwnershipTests(unittest.TestCase):
    def _run(self, platform, argv):
        run_app = mock.Mock()
        controller = object()
        with mock.patch.object(
            entrypoint,
            "get_platform_services",
            return_value=platform,
        ), mock.patch.object(entrypoint, "setup_logging") as setup, mock.patch.object(
            entrypoint,
            "log_startup_diagnostics",
        ) as diagnostics, mock.patch.object(
            entrypoint,
            "AppController",
            return_value=controller,
        ), mock.patch.object(entrypoint.sys, "argv", argv):
            entrypoint.run_shell("windows", run_app)
        return setup, diagnostics, run_app, controller

    def test_duplicate_instance_never_opens_log_file(self):
        platform = FakePlatform(acquired=False)

        setup, diagnostics, run_app, _controller = self._run(platform, ["app"])

        setup.assert_not_called()
        diagnostics.assert_not_called()
        run_app.assert_not_called()
        self.assertTrue(platform.notified)

    def test_exit_helper_never_opens_log_file(self):
        platform = FakePlatform()

        setup, diagnostics, run_app, _controller = self._run(
            platform,
            ["app", "--exit"],
        )

        setup.assert_not_called()
        diagnostics.assert_not_called()
        run_app.assert_not_called()
        self.assertTrue(platform.exit_requested)

    def test_update_helper_never_opens_log_file(self):
        platform = FakePlatform(helper=True)

        setup, diagnostics, run_app, _controller = self._run(platform, ["app"])

        setup.assert_not_called()
        diagnostics.assert_not_called()
        run_app.assert_not_called()

    def test_instance_owner_configures_logging_before_constructing_app(self):
        platform = FakePlatform()

        setup, diagnostics, run_app, controller = self._run(platform, ["app"])

        setup.assert_called_once_with(platform)
        diagnostics.assert_called_once_with(platform)
        run_app.assert_called_once_with(controller, tray_mode=False)
        self.assertTrue(platform.cleaned)


if __name__ == "__main__":
    unittest.main()
