import threading
import unittest
from unittest.mock import patch

import requests
from worker_fakes import activity

from desktop.core.ra_client import APIResponseError
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
        self.activity_error = None
        self.calls = []

    def get_user_activity(self, _username, _apikey):
        self.calls.append("activity")
        if self.activity_error:
            raise self.activity_error
        return activity(
            visible_role=self.displayable_roles[0] if self.displayable_roles else None,
            displayable_roles=tuple(self.displayable_roles) if self.displayable_roles is not None else None,
        )

    def get_user_profile(self, _username, _apikey):
        self.calls.append("profile")
        if self.profile_error is not None:
            raise self.profile_error
        return {"Permissions": self.permissions}


class FakeWorker:
    def __init__(self):
        self.started_config = None
        self.seed = None

    def start(self, config, **seed):
        self.started_config = dict(config)
        self.seed = seed
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
        self.assertEqual(["activity"], controller.ra_client.calls)
        self.assertEqual(("developer",), controller.worker.seed["initial_activity"].displayable_roles)
        self.assertFalse(controller.worker.seed["permissions_loaded"])

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

    def test_missing_v2_roles_fall_back_to_profile_permissions(self):
        controller = self._controller(3)
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
        self.assertEqual(["activity", "profile"], controller.ra_client.calls)
        self.assertEqual(3, controller.worker.seed["permissions"])
        self.assertTrue(controller.worker.seed["permissions_loaded"])

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
        self.assertEqual(["activity"], controller.ra_client.calls)

    def test_v2_failure_does_not_start_worker_or_attempt_legacy_requests(self):
        for error in (requests.Timeout(), requests.ConnectionError(), APIResponseError()):
            with self.subTest(error=type(error)):
                controller = self._controller(3)
                controller.ra_client.activity_error = error
                with patch("desktop.runtime.controller.save_config"):
                    result = controller.connect({"username": "user", "apikey": "key"})
                self.assertFalse(result.success)
                self.assertIsNone(controller.worker.started_config)
                self.assertEqual(["activity"], controller.ra_client.calls)

    def test_permissions_fallback_failure_does_not_start_worker(self):
        controller = self._controller(3, profile_error=requests.Timeout())
        with patch("desktop.runtime.controller.save_config"):
            result = controller.connect({"username": "user", "apikey": "key"})
        self.assertFalse(result.success)
        self.assertIsNone(controller.worker.started_config)
        self.assertEqual(["activity", "profile"], controller.ra_client.calls)

    def test_known_visible_role_with_hidden_developer_role_unlocks_dev_mode(self):
        controller = self._controller(1, displayable_roles=["artist", "developer"])
        with patch("desktop.runtime.controller.save_config"):
            result = controller.connect({"username": "user", "apikey": "key"})
        self.assertTrue(result.success)
        self.assertTrue(result.config["dev_mode"])
        self.assertEqual(["activity"], controller.ra_client.calls)


if __name__ == "__main__":
    unittest.main()
