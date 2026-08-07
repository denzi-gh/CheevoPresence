import unittest

from desktop.shell.ipc import SettingsHostService, _format_ipc_error


class FakeController:
    pass


class IpcSecurityTests(unittest.TestCase):
    def _service(self):
        service = object.__new__(SettingsHostService)
        service.controller = FakeController()
        service.auth_token = "correct-token"
        return service

    def test_invalid_token_is_rejected(self):
        service = self._service()

        with self.assertRaises(PermissionError):
            service._dispatch({"token": "wrong-token", "method": "get_state"})

    def test_non_string_token_is_rejected(self):
        service = self._service()

        for bad_token in (None, 123, ["correct-token"], {"token": "correct-token"}):
            with self.assertRaises(PermissionError):
                service._dispatch({"token": bad_token, "method": "get_state"})

    def test_auth_token_is_long_random_hex(self):
        service = SettingsHostService(FakeController())

        self.assertEqual(64, len(service.auth_token))
        int(service.auth_token, 16)
        self.assertNotEqual(service.auth_token, SettingsHostService(FakeController()).auth_token)

    def test_invalid_token_error_is_generic(self):
        message = _format_ipc_error(PermissionError("secret-token"))

        self.assertEqual("Invalid IPC token.", message)
        self.assertNotIn("secret-token", message)

    def test_unknown_method_reports_method_name_only(self):
        service = self._service()

        with self.assertRaises(ValueError) as ctx:
            service._dispatch({"token": "correct-token", "method": "missing"})

        self.assertEqual("Unknown IPC method: missing", str(ctx.exception))

    def test_unexpected_error_is_generic(self):
        self.assertEqual("IPC request failed.", _format_ipc_error(RuntimeError("secret")))


if __name__ == "__main__":
    unittest.main()
