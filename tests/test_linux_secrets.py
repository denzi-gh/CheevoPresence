import unittest

from desktop.platform import linux_secrets


class LinuxSecretsTests(unittest.TestCase):
    def test_protect_api_key_uses_local_encoding(self):
        token = linux_secrets.protect_api_key("secret")

        self.assertNotEqual("secret", token)
        self.assertEqual("secret", linux_secrets.unprotect_api_key(token))

    def test_empty_secret_round_trips_to_empty(self):
        self.assertEqual("", linux_secrets.protect_api_key(""))
        self.assertEqual("", linux_secrets.unprotect_api_key(""))

    def test_invalid_stored_value_returns_empty(self):
        self.assertEqual("", linux_secrets.unprotect_api_key("not-base64"))


if __name__ == "__main__":
    unittest.main()
