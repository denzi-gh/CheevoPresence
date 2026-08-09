"""Tests for the macOS Keychain helpers (subprocess calls are faked)."""

import subprocess
import unittest
from unittest import mock

from desktop.platform import macos_keychain


def _completed(args, returncode=0, stdout=""):
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")


class WriteKeychainPasswordTests(unittest.TestCase):
    def test_api_key_travels_via_stdin_not_argv(self):
        with mock.patch.object(macos_keychain.subprocess, "run") as run:
            run.side_effect = lambda args, **kwargs: _completed(args)

            macos_keychain._write_keychain_password("account", "super-secret-key")

        args = run.call_args.args[0]
        self.assertEqual(["security", "-i"], args)
        for part in args:
            self.assertNotIn("super-secret-key", part)
        stdin_payload = run.call_args.kwargs["input"]
        self.assertIn('"super-secret-key"', stdin_payload)
        self.assertIn("add-generic-password", stdin_payload)

    def test_quotes_and_backslashes_are_escaped(self):
        with mock.patch.object(macos_keychain.subprocess, "run") as run:
            run.side_effect = lambda args, **kwargs: _completed(args)

            macos_keychain._write_keychain_password("account", 'ke"y\\x')

        stdin_payload = run.call_args.kwargs["input"]
        self.assertIn('"ke\\"y\\\\x"', stdin_payload)

    def test_control_characters_are_rejected(self):
        # A newline would end the interactive command and could smuggle in a
        # second security command.
        with (
            mock.patch.object(macos_keychain.subprocess, "run") as run,
            self.assertRaises(OSError),
        ):
            macos_keychain._write_keychain_password(
                "account",
                "key\ndelete-generic-password",
            )

        run.assert_not_called()

    def test_failed_write_raises_oserror(self):
        error = subprocess.CalledProcessError(1, ["security", "-i"])
        with (
            mock.patch.object(macos_keychain.subprocess, "run", side_effect=error),
            self.assertRaises(OSError),
        ):
            macos_keychain._write_keychain_password("account", "key")


class ReadKeychainPasswordTests(unittest.TestCase):
    def test_read_returns_stripped_stdout(self):
        with mock.patch.object(macos_keychain.subprocess, "run") as run:
            run.side_effect = lambda args, **kwargs: _completed(args, stdout="the-key\n")

            self.assertEqual("the-key", macos_keychain._read_keychain_password("account"))

    def test_read_failure_returns_empty_string(self):
        error = subprocess.CalledProcessError(44, ["security"])
        with mock.patch.object(macos_keychain.subprocess, "run", side_effect=error):
            self.assertEqual("", macos_keychain._read_keychain_password("account"))


if __name__ == "__main__":
    unittest.main()
