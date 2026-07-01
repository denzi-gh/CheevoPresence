import threading
import unittest
from unittest.mock import patch

import requests

from desktop.core.roles import DEBUG_FORCE_ROLE_PERMISSION_ENV
from desktop.runtime.controller import AppController


class FakePlatform:
    def __init__(self):
        self.startup_toggle_label = "Launch on login"

    def set_autostart(self, _enabled):
        return None

    def is_autostart_enabled(self):
        return False


class FakeRAClient:
    def __init__(self, permissions, displayable_roles=None, profile_error=None):
        self.permissions = permissions
        self.displayable_roles = displayable_roles
        self.profile_error = profile_error

    def get_user_summary(self, _username, _apikey):
        return {"Permissions": self.permissions}

    def get_user_profile_v2(self, _username, _apikey):
        if self.profile_error is not None:
            raise self.profile_error
        return {"displayableRoles": self.displayable_roles}


class FakeWorker:
    def __init__(self):
        self.started_config = None

    def start(self, config):
        self.started_config = dict(config)
        return True


class ControllerRoleTests(unittest.TestCase):
    def setUp(self):
        self._env_patch = patch.dict("os.environ", {DEBUG_FORCE_ROLE_PERMISSION_ENV: ""})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()

    def _controller(self, permissions, displayable_roles=None, profile_error=None):
        controller = object.__new__(AppController)
        controller.platform = FakePlatform()
        controller.ra_client = FakeRAClient(
            permissions,
            displayable_roles=displayable_roles,
            profile_error=profile_error,
        )
        controller.worker = FakeWorker()
        controller._action_lock = threading.Lock()
        controller.config = {}
        return controller

    def test_developer_role_enables_dev_mode_and_save_config(self):
        controller = self._controller(1, displayable_roles=["developer"])
        config = {
            "username": "user",
            "apikey": "key",
            "dev_mode": False,
        }

        with patch("desktop.runtime.controller.save_config") as save_config:
            result = controller.connect(config)

        self.assertTrue(result.success)
        self.assertTrue(result.config["dev_mode"])
        self.assertTrue(controller.worker.started_config["dev_mode"])
        self.assertEqual(2, save_config.call_count)
        self.assertTrue(save_config.call_args_list[-1].args[0]["dev_mode"])

    def test_non_developer_roles_clear_manual_dev_mode(self):
        controller = self._controller(6, displayable_roles=["artist"])
        config = {
            "username": "user",
            "apikey": "key",
            "dev_mode": True,
        }

        with patch("desktop.runtime.controller.save_config") as save_config:
            result = controller.connect(config)

        self.assertTrue(result.success)
        self.assertFalse(result.config["dev_mode"])
        self.assertFalse(controller.worker.started_config["dev_mode"])
        self.assertEqual(2, save_config.call_count)
        self.assertFalse(save_config.call_args_list[-1].args[0]["dev_mode"])

    def test_non_developer_roles_keep_dev_mode_off_when_disabled(self):
        controller = self._controller(1, displayable_roles=["artist"])
        config = {
            "username": "user",
            "apikey": "key",
            "dev_mode": False,
        }

        with patch("desktop.runtime.controller.save_config"):
            result = controller.connect(config)

        self.assertTrue(result.success)
        self.assertFalse(result.config["dev_mode"])
        self.assertFalse(controller.worker.started_config["dev_mode"])

    def test_role_lookup_failure_falls_back_to_permissions(self):
        controller = self._controller(3, profile_error=requests.HTTPError("nope"))
        config = {
            "username": "user",
            "apikey": "key",
            "dev_mode": False,
        }

        with patch("desktop.runtime.controller.save_config") as save_config:
            result = controller.connect(config)

        self.assertTrue(result.success)
        self.assertTrue(result.config["dev_mode"])
        self.assertTrue(controller.worker.started_config["dev_mode"])
        self.assertEqual(2, save_config.call_count)

    def test_debug_forced_permission_enables_dev_mode_for_normal_permissions(self):
        controller = self._controller(1, displayable_roles=["artist"])
        config = {
            "username": "user",
            "apikey": "key",
            "dev_mode": False,
        }

        with (
            patch.dict("os.environ", {DEBUG_FORCE_ROLE_PERMISSION_ENV: "2"}),
            patch("desktop.runtime.controller.save_config") as save_config,
        ):
            result = controller.connect(config)

        self.assertTrue(result.success)
        self.assertTrue(result.config["dev_mode"])
        self.assertTrue(controller.worker.started_config["dev_mode"])
        self.assertEqual(2, save_config.call_count)


if __name__ == "__main__":
    unittest.main()
