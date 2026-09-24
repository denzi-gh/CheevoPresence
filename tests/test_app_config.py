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
        cfg = AppConfig(username="bob", interval=60)
        self.assertEqual(cfg, AppConfig.from_dict(cfg.to_dict()))

    def test_poll_interval_defaults_to_45_seconds(self):
        self.assertEqual(45, AppConfig().interval)
        self.assertEqual(45, DEFAULT_CONFIG["interval"])
        self.assertEqual(45, normalize_config({})["interval"])

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
        for interval in (-1, 0, 1, 5, 15, 30, 44, "5"):
            with self.subTest(interval=interval):
                self.assertEqual(45, normalize_config({"interval": interval})["interval"])
        self.assertEqual(120, normalize_config({"interval": 9999})["interval"])

    def test_valid_custom_intervals_are_preserved(self):
        for interval in (45, 46, 60, 120):
            with self.subTest(interval=interval):
                self.assertEqual(interval, normalize_config({"interval": interval})["interval"])
        self.assertEqual(60, normalize_config({"interval": "60"})["interval"])

    def test_invalid_intervals_use_the_default(self):
        for interval in (None, "", "not-a-number", [], {}, float("inf"), float("nan")):
            with self.subTest(interval=interval):
                self.assertEqual(45, normalize_config({"interval": interval})["interval"])

    def test_current_schema_cannot_bypass_the_minimum(self):
        cfg = normalize_config({"schema_version": SCHEMA_VERSION, "interval": 5})
        self.assertEqual(45, cfg["interval"])

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

    def test_legacy_poll_intervals_are_migrated_once(self):
        for version in (None, 0, 1, "1", "invalid"):
            for interval, expected in (
                (5, 45), (15, 45), (30, 45), (44, 45), ("5", 45),
                (45, 45), (60, 60), (120, 120),
            ):
                with self.subTest(version=version, interval=interval):
                    raw = {"interval": interval, "apikey_protected": "protected:key"}
                    if version is not None:
                        raw["schema_version"] = version
                    migrated = migrate_config(raw)

                    self.assertEqual(expected, migrated["interval"])
                    self.assertEqual(SCHEMA_VERSION, migrated["schema_version"])
                    self.assertEqual("protected:key", migrated["apikey_protected"])
                    self.assertEqual(migrated, migrate_config(migrated))

    def test_missing_or_invalid_legacy_interval_uses_the_default(self):
        for raw in ({}, {"interval": None}, {"interval": "bad"}):
            with self.subTest(raw=raw):
                self.assertEqual(45, migrate_config(raw)["interval"])

    def test_non_dict_returns_empty_dict(self):
        self.assertEqual({}, migrate_config(None))

    def test_does_not_mutate_input(self):
        raw = {"username": "bob", "interval": 5}
        migrate_config(raw)
        self.assertEqual({"username": "bob", "interval": 5}, raw)


if __name__ == "__main__":
    unittest.main()
