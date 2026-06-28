import threading
import unittest
from unittest.mock import patch

from desktop.runtime.controller import AppController


class FakePlatform:
    def __init__(self):
        self.startup_toggle_label = "Launch on login"

    def set_autostart(self, _enabled):
        return None

    def is_autostart_enabled(self):
        return False


class FakeRAClient:
    def __init__(self, permissions):
        self.permissions = permissions

    def get_user_summary(self, _username, _apikey):
        return {"Permissions": self.permissions}


class FakeWorker:
    def __init__(self):
        self.started_config = None

    def start(self, config):
        self.started_config = dict(config)
        return True


class ControllerRoleTests(unittest.TestCase):
    def _controller(self, permissions):
        controller = object.__new__(AppController)
        controller.platform = FakePlatform()
        controller.ra_client = FakeRAClient(permissions)
        controller.worker = FakeWorker()
        controller._action_lock = threading.Lock()
        controller.config = {}
        return controller

    def test_elevated_permissions_enable_dev_mode_and_save_config(self):
        controller = self._controller(2)
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

    def test_normal_permissions_do_not_disable_manual_dev_mode(self):
        controller = self._controller(1)
        config = {
            "username": "user",
            "apikey": "key",
            "dev_mode": True,
        }

        with patch("desktop.runtime.controller.save_config") as save_config:
            result = controller.connect(config)

        self.assertTrue(result.success)
        self.assertTrue(result.config["dev_mode"])
        self.assertTrue(controller.worker.started_config["dev_mode"])
        self.assertEqual(1, save_config.call_count)

    def test_normal_permissions_keep_dev_mode_off_when_disabled(self):
        controller = self._controller(1)
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


if __name__ == "__main__":
    unittest.main()
