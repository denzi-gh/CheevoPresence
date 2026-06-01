import unittest

from desktop.shell.ipc import IPC_LOG_THROTTLE_SECONDS, SettingsHostService


class IpcRequestLogThrottleTests(unittest.TestCase):
    def _service(self):
        service = SettingsHostService.__new__(SettingsHostService)
        service._last_request_log = {}
        return service

    def test_non_throttled_methods_always_log(self):
        service = self._service()
        self.assertTrue(service._should_log_request("connect", 100.0))
        self.assertTrue(service._should_log_request("connect", 100.5))

    def test_get_state_is_throttled(self):
        service = self._service()
        base = 1000.0
        self.assertTrue(service._should_log_request("get_state", base))
        # Within the throttle window the repeated poll is suppressed.
        self.assertFalse(service._should_log_request("get_state", base + 1))
        self.assertFalse(
            service._should_log_request("get_state", base + IPC_LOG_THROTTLE_SECONDS - 0.1)
        )
        # Once the window elapses it logs again.
        self.assertTrue(
            service._should_log_request("get_state", base + IPC_LOG_THROTTLE_SECONDS)
        )


if __name__ == "__main__":
    unittest.main()
