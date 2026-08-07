"""Regression tests for the pure version helpers in desktop/core/update.py.

These gate both the real update path (UpdateService._build_update_status)
and the update-test.json override, so their comparison semantics must not
regress silently.
"""

import json
import os
import tempfile
import unittest

from desktop.core.update import (
    _version_key,
    is_newer_version,
    load_update_override,
    normalize_version_label,
)


class VersionKeyTests(unittest.TestCase):
    def test_full_version_parses_as_int_tuple(self):
        self.assertEqual((1, 3, 2), _version_key("1.3.2"))
        self.assertEqual((1, 3, 2), _version_key("v1.3.2"))

    def test_missing_parts_default_to_zero(self):
        self.assertEqual((1, 4, 0), _version_key("1.4"))
        self.assertEqual((2, 0, 0), _version_key("2"))

    def test_prerelease_suffix_is_ignored(self):
        self.assertEqual((1, 4, 0), _version_key("v1.4.0-beta"))
        self.assertEqual((1, 4, 0), _version_key("1.4.0rc1"))

    def test_surrounding_text_is_tolerated(self):
        self.assertEqual((1, 3, 2), _version_key("  release v1.3.2  "))

    def test_non_string_and_unparseable_input(self):
        self.assertIsNone(_version_key(None))
        self.assertIsNone(_version_key(132))
        self.assertIsNone(_version_key(("1", "3", "2")))
        self.assertIsNone(_version_key("latest"))
        self.assertIsNone(_version_key(""))


class NormalizeVersionLabelTests(unittest.TestCase):
    def test_normalizes_to_three_parts(self):
        self.assertEqual("1.3.2", normalize_version_label("v1.3.2"))
        self.assertEqual("1.4.0", normalize_version_label("1.4"))
        self.assertEqual("1.4.0", normalize_version_label("v1.4.0-beta"))

    def test_unparseable_input_returns_none(self):
        self.assertIsNone(normalize_version_label(None))
        self.assertIsNone(normalize_version_label("latest"))


class IsNewerVersionTests(unittest.TestCase):
    def test_numeric_not_lexicographic_comparison(self):
        # The classic string-comparison trap: "1.10.0" < "1.9.0" as strings.
        self.assertTrue(is_newer_version("1.10.0", "1.9.0"))
        self.assertFalse(is_newer_version("1.9.0", "1.10.0"))

    def test_patch_minor_and_major_bumps(self):
        self.assertTrue(is_newer_version("1.3.3", "1.3.2"))
        self.assertTrue(is_newer_version("1.4.0", "1.3.9"))
        self.assertTrue(is_newer_version("2.0.0", "1.99.99"))

    def test_equal_and_older_versions_are_not_newer(self):
        self.assertFalse(is_newer_version("1.3.2", "1.3.2"))
        self.assertFalse(is_newer_version("v1.3.2", "1.3.2"))
        self.assertFalse(is_newer_version("1.3.1", "1.3.2"))

    def test_missing_patch_compares_as_zero(self):
        self.assertFalse(is_newer_version("1.4", "1.4.0"))
        self.assertTrue(is_newer_version("1.4", "1.3.9"))

    def test_unparseable_input_is_never_newer(self):
        self.assertFalse(is_newer_version(None, "1.3.2"))
        self.assertFalse(is_newer_version("1.3.2", None))
        self.assertFalse(is_newer_version("latest", "1.3.2"))
        self.assertFalse(is_newer_version("2.0.0", "latest"))


class LoadUpdateOverrideTests(unittest.TestCase):
    def _write_override(self, tmpdir, payload):
        path = os.path.join(tmpdir, "update-test.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return path

    def test_missing_or_empty_path_returns_none(self):
        self.assertIsNone(load_update_override("", "1.0.0"))
        self.assertIsNone(load_update_override(None, "1.0.0"))
        self.assertIsNone(load_update_override(os.path.join("does", "not", "exist"), "1.0.0"))

    def test_disabled_override_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_override(
                tmpdir,
                {"enabled": False, "latest_version": "9.9.9"},
            )
            self.assertIsNone(load_update_override(path, "1.0.0"))

    def test_override_with_older_version_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_override(tmpdir, {"latest_version": "1.0.0"})
            self.assertIsNone(load_update_override(path, "1.0.0"))

    def test_invalid_json_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "update-test.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not json")
            self.assertIsNone(load_update_override(path, "1.0.0"))

    def test_relative_asset_path_is_resolved_next_to_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            asset = os.path.join(tmpdir, "CheevoPresence.exe")
            with open(asset, "wb") as handle:
                handle.write(b"exe")
            path = self._write_override(
                tmpdir,
                {
                    "latest_version": "9.9.9",
                    "asset_path": "CheevoPresence.exe",
                    "sha256": "AB" * 32,
                },
            )

            override = load_update_override(path, "1.0.0")

            self.assertIsNotNone(override)
            self.assertEqual("9.9.9", override["latest_version"])
            self.assertEqual(os.path.abspath(asset), override["asset_url"])
            self.assertEqual("CheevoPresence.exe", override["asset_name"])
            self.assertEqual("ab" * 32, override["asset_sha256"])


if __name__ == "__main__":
    unittest.main()
