"""Tests for the Windows API-key protection helpers.

The DPAPI path only runs on Windows; the base64 fallback path (used off
Windows) and the input-validation behavior are exercised on every platform.
"""

import base64
import unittest
from unittest import mock

from desktop.platform import windows_secrets


class ProtectRoundTripTests(unittest.TestCase):
    def test_round_trip_on_this_platform(self):
        # DPAPI on Windows, base64 elsewhere — either way it must round-trip.
        protected = windows_secrets.protect_api_key("s3cr3t-key")

        self.assertNotEqual("s3cr3t-key", protected)
        self.assertEqual("s3cr3t-key", windows_secrets.unprotect_api_key(protected))

    def test_empty_value_protects_to_empty(self):
        self.assertEqual("", windows_secrets.protect_api_key(""))

    def test_unprotect_rejects_empty_and_non_string(self):
        self.assertEqual("", windows_secrets.unprotect_api_key(""))
        self.assertEqual("", windows_secrets.unprotect_api_key(None))
        self.assertEqual("", windows_secrets.unprotect_api_key(12345))

    def test_unprotect_rejects_non_base64(self):
        self.assertEqual("", windows_secrets.unprotect_api_key("not base64 !!!"))


class Base64FallbackTests(unittest.TestCase):
    """Force the non-Windows branch regardless of the host OS."""

    def test_protect_uses_base64_when_not_windows(self):
        with mock.patch.object(windows_secrets.os, "name", "posix"):
            protected = windows_secrets.protect_api_key("hello")

        self.assertEqual("hello", base64.b64decode(protected).decode("utf-8"))

    def test_unprotect_reverses_base64_when_not_windows(self):
        token = base64.b64encode(b"hello").decode("ascii")
        with mock.patch.object(windows_secrets.os, "name", "posix"):
            self.assertEqual("hello", windows_secrets.unprotect_api_key(token))

    def test_unprotect_returns_empty_on_non_utf8_when_not_windows(self):
        token = base64.b64encode(b"\xff\xfe").decode("ascii")
        with mock.patch.object(windows_secrets.os, "name", "posix"):
            self.assertEqual("", windows_secrets.unprotect_api_key(token))


if __name__ == "__main__":
    unittest.main()
