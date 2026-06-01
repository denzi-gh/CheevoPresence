import unittest
from unittest import mock

from desktop.platform import linux_secrets


class FakeKeyring:
    def __init__(self):
        self.values = {}
        self.deleted = []

    def set_password(self, service, account, value):
        self.values[(service, account)] = value

    def get_password(self, service, account):
        return self.values.get((service, account))

    def delete_password(self, service, account):
        self.deleted.append((service, account))
        self.values.pop((service, account), None)


class LinuxSecretsTests(unittest.TestCase):
    def test_secret_service_token_round_trips_through_keyring(self):
        keyring = FakeKeyring()

        with mock.patch.object(linux_secrets, "_load_keyring", return_value=keyring):
            token = linux_secrets.protect_api_key("secret")

            self.assertEqual(linux_secrets.build_secret_token(), token)
            self.assertEqual("secret", linux_secrets.unprotect_api_key(token))

    def test_empty_secret_deletes_keyring_value(self):
        keyring = FakeKeyring()

        with mock.patch.object(linux_secrets, "_load_keyring", return_value=keyring):
            self.assertEqual("", linux_secrets.protect_api_key(""))

            self.assertEqual(
                [
                    (
                        linux_secrets.KEYRING_SERVICE,
                        linux_secrets.KEYRING_ACCOUNT,
                    )
                ],
                keyring.deleted,
            )

    def test_secret_service_failure_falls_back_to_generic_encoding(self):
        with mock.patch.object(
            linux_secrets,
            "_load_keyring",
            side_effect=ImportError("no keyring"),
        ):
            token = linux_secrets.protect_api_key("secret")

        self.assertFalse(token.startswith(linux_secrets.KEYRING_TOKEN_PREFIX))
        self.assertEqual("secret", linux_secrets.unprotect_api_key(token))

    def test_secret_service_token_returns_empty_when_keyring_unavailable(self):
        token = linux_secrets.build_secret_token()

        with mock.patch.object(
            linux_secrets,
            "_load_keyring",
            side_effect=RuntimeError("locked"),
        ):
            self.assertEqual("", linux_secrets.unprotect_api_key(token))


if __name__ == "__main__":
    unittest.main()
