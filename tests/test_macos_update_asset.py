"""Tests for the architecture-aware macOS update asset selection."""

import unittest

from desktop.platform.macos import select_update_asset


def _asset(name):
    return {"name": name, "browser_download_url": f"https://example.test/{name}"}


class MacosSelectUpdateAssetTests(unittest.TestCase):
    def test_prefers_exact_arch_tagged_asset(self):
        assets = [
            _asset("CheevoPresence-macos.zip"),
            _asset("CheevoPresence-macos-arm64.zip"),
        ]

        selected = select_update_asset(assets, machine="arm64")

        self.assertEqual("CheevoPresence-macos-arm64.zip", selected["name"])

    def test_accepts_legacy_untagged_asset_as_fallback(self):
        assets = [
            _asset("notes.txt"),
            _asset("CheevoPresence-macos.zip"),
        ]

        selected = select_update_asset(assets, machine="arm64")

        self.assertEqual("CheevoPresence-macos.zip", selected["name"])

    def test_rejects_asset_tagged_for_other_arch_on_arm64(self):
        assets = [
            _asset("CheevoPresence-macos-x86_64.zip"),
            _asset("CheevoPresence-macos-intel.zip"),
        ]

        self.assertIsNone(select_update_asset(assets, machine="arm64"))

    def test_rejects_arm64_asset_on_x86_64(self):
        assets = [_asset("CheevoPresence-macos-arm64.zip")]

        self.assertIsNone(select_update_asset(assets, machine="x86_64"))

    def test_x86_64_machine_selects_its_own_asset(self):
        assets = [
            _asset("CheevoPresence-macos-arm64.zip"),
            _asset("CheevoPresence-macos-x86_64.zip"),
        ]

        selected = select_update_asset(assets, machine="x86_64")

        self.assertEqual("CheevoPresence-macos-x86_64.zip", selected["name"])

    def test_ignores_malformed_entries(self):
        assets = [None, "text", {"name": ""}, _asset("CheevoPresence-macos-arm64.zip")]

        selected = select_update_asset(assets, machine="arm64")

        self.assertEqual("CheevoPresence-macos-arm64.zip", selected["name"])

    def test_no_assets_returns_none(self):
        self.assertIsNone(select_update_asset([], machine="arm64"))
        self.assertIsNone(select_update_asset(None, machine="arm64"))


if __name__ == "__main__":
    unittest.main()
