"""Tests for the AppConfig schema, normalization, and migration."""

import unittest
from dataclasses import fields

from desktop.core.settings import (
    DEFAULT_CONFIG,
    SCHEMA_VERSION,
    AppConfig,
    migrate_config,
    normalize_config,
)


class AppConfigSchemaTests(unittest.TestCase):
    def test_default_config_matches_dataclass_fields(self):
        # Guards against DEFAULT_CONFIG and AppConfig drifting apart.
        self.assertEqual(
            {f.name for f in fields(AppConfig)},
            set(DEFAULT_CONFIG),
        )

    def test_to_dict_round_trips_through_from_dict(self):
        cfg = AppConfig(username="bob", interval=42)
        self.assertEqual(cfg, AppConfig.from_dict(cfg.to_dict()))

    def test_normalize_config_stamps_current_schema_version(self):
        self.assertEqual(SCHEMA_VERSION, normalize_config({})["schema_version"])

    def test_normalize_is_dict_compatible(self):
        cfg = normalize_config({"username": "  bob  "})
        self.assertIsInstance(cfg, dict)
        self.assertEqual("bob", cfg["username"])


class CoercionTests(unittest.TestCase):
    def test_non_dict_yields_defaults(self):
        self.assertEqual(DEFAULT_CONFIG, normalize_config(None))
        self.assertEqual(DEFAULT_CONFIG, normalize_config("nope"))

    def test_interval_is_clamped(self):
        self.assertEqual(5, normalize_config({"interval": 1})["interval"])
        self.assertEqual(120, normalize_config({"interval": 9999})["interval"])
        self.assertEqual(5, normalize_config({"interval": "not-a-number"})["interval"])

    def test_timeout_floor_and_clamp(self):
        self.assertEqual(130, normalize_config({"timeout": 30})["timeout"])
        self.assertEqual(0, normalize_config({"timeout": 0})["timeout"])
        self.assertEqual(3600, normalize_config({"timeout": 999999})["timeout"])

    def test_bool_fields_accept_strings(self):
        self.assertTrue(normalize_config({"dev_mode": "yes"})["dev_mode"])
        self.assertFalse(normalize_config({"dev_mode": "off"})["dev_mode"])
        # Unrecognized string keeps the default.
        self.assertFalse(normalize_config({"dev_mode": "maybe"})["dev_mode"])

    def test_apikey_prefers_plain_then_decoded_protected(self):
        self.assertEqual("plain", normalize_config({"apikey": "plain"})["apikey"])
        decoded = normalize_config(
            {"apikey_protected": "blob"},
            decode_api_key=lambda value: f"decoded:{value}",
        )
        self.assertEqual("decoded:blob", decoded["apikey"])


class MigrateConfigTests(unittest.TestCase):
    def test_stamps_schema_version_on_legacy_config(self):
        migrated = migrate_config({"username": "bob"})
        self.assertEqual(SCHEMA_VERSION, migrated["schema_version"])
        self.assertEqual("bob", migrated["username"])

    def test_non_dict_returns_empty_dict(self):
        self.assertEqual({}, migrate_config(None))

    def test_does_not_mutate_input(self):
        raw = {"username": "bob"}
        migrate_config(raw)
        self.assertNotIn("schema_version", raw)


if __name__ == "__main__":
    unittest.main()
