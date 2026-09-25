"""Saved polling intervals migrate through storage without losing credentials."""

import json
import tempfile
import unittest
from pathlib import Path

from desktop.core.settings import SCHEMA_VERSION
from desktop.runtime import storage


class FakePlatform:
    def __init__(self, root):
        self.root = root

    def get_config_dir(self, _app_name, _runtime_root_dir):
        return self.root

    def protect_api_key(self, value):
        return f"protected:{value}" if value else ""

    def unprotect_api_key(self, value):
        return value.removeprefix("protected:")


class ConfigMigrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.platform = FakePlatform(directory.name)
        self.config_file = Path(directory.name) / "config.json"

    def test_legacy_config_load_save_and_reload_preserve_credentials_and_custom_values(self):
        for version in (None, 1):
            for interval, expected in ((5, 45), (30, 45), (44, 45), (45, 45), (60, 60), (120, 120)):
                with self.subTest(version=version, interval=interval):
                    saved = {
                        "username": "bob",
                        "apikey_protected": "protected:test-key",
                        "interval": interval,
                        "timeout": 260,
                        "show_total_playtime": False,
                    }
                    if version is not None:
                        saved["schema_version"] = version
                    self.config_file.write_text(json.dumps(saved), encoding="utf-8")

                    loaded = storage.load_config(self.platform)

                    self.assertEqual(expected, loaded["interval"])
                    self.assertEqual(SCHEMA_VERSION, loaded["schema_version"])
                    self.assertEqual("bob", loaded["username"])
                    self.assertEqual("test-key", loaded["apikey"])
                    self.assertEqual(260, loaded["timeout"])
                    self.assertFalse(loaded["show_total_playtime"])
                    # Loading migrates in memory; normal saves persist the new schema.
                    self.assertEqual(saved, json.loads(self.config_file.read_text(encoding="utf-8")))

                    storage.save_config(loaded, self.platform)
                    persisted = json.loads(self.config_file.read_text(encoding="utf-8"))

                    self.assertEqual(expected, persisted["interval"])
                    self.assertEqual(SCHEMA_VERSION, persisted["schema_version"])
                    self.assertNotIn("apikey", persisted)
                    self.assertEqual("protected:test-key", persisted["apikey_protected"])
                    self.assertEqual(loaded, storage.load_config(self.platform))

    def test_current_schema_file_cannot_restore_a_short_interval(self):
        self.config_file.write_text(
            json.dumps({"schema_version": SCHEMA_VERSION, "interval": 5}),
            encoding="utf-8",
        )

        self.assertEqual(45, storage.load_config(self.platform)["interval"])

    def test_saving_a_short_interval_enforces_the_minimum_and_protects_the_key(self):
        storage.save_config(
            {"schema_version": SCHEMA_VERSION, "interval": 5, "apikey": "test-key"},
            self.platform,
        )

        persisted = json.loads(self.config_file.read_text(encoding="utf-8"))
        self.assertEqual(45, persisted["interval"])
        self.assertNotIn("apikey", persisted)
        self.assertEqual("protected:test-key", persisted["apikey_protected"])
        self.assertEqual(45, storage.load_config(self.platform)["interval"])
