import hashlib
import os
import sys
import tempfile
import unittest
from unittest import mock

from desktop.runtime.update_service import UPDATE_OVERRIDE_ENV, UpdateService


class FakeResponse:
    def __init__(self, payload=None, chunks=None):
        self.payload = payload if payload is not None else {}
        self.chunks = chunks or []
        self.text = ""

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload

    def iter_content(self, chunk_size):
        return iter(self.chunks)


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class RaisingSession:
    def __init__(self, exc):
        self.exc = exc

    def get(self, url, **kwargs):
        raise self.exc


class FakePlatform:
    def __init__(self):
        self.staged = None

    def select_update_asset(self, assets):
        for asset in assets:
            if asset.get("name") == "CheevoPresence.exe":
                return asset
        return None

    def supports_self_update(self):
        return True

    def stage_update_install(self, download_path, relaunch_args, source_pid):
        self.staged = (download_path, relaunch_args, source_pid)


class UpdateServiceTests(unittest.TestCase):
    def test_check_for_updates_selects_platform_asset(self):
        payload = {
            "tag_name": "v9.9.9",
            "html_url": "https://example.test/release",
            "assets": [
                {"name": "notes.txt", "browser_download_url": "https://example.test/notes"},
                {"name": "CheevoPresence.exe", "browser_download_url": "https://example.test/exe"},
            ],
        }
        service = UpdateService(
            FakePlatform(),
            session=FakeSession(FakeResponse(payload)),
            current_version="1.0.0",
            override_file="",
        )

        status = service.check_for_updates()

        self.assertTrue(status.checked)
        self.assertTrue(status.available)
        self.assertEqual("9.9.9", status.latest_version)
        self.assertEqual("CheevoPresence.exe", status.asset_name)
        self.assertEqual("https://example.test/exe", status.asset_url)

    def test_check_for_updates_uses_override_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            asset_path = os.path.join(tmpdir, "CheevoPresence.exe")
            override_path = os.path.join(tmpdir, "update-test.json")
            with open(asset_path, "wb") as handle:
                handle.write(b"exe")
            with open(override_path, "w", encoding="utf-8") as handle:
                handle.write(
                    '{"latest_version":"2.0.0","asset_path":"CheevoPresence.exe"}'
                )

            service = UpdateService(
                FakePlatform(),
                session=FakeSession(FakeResponse({})),
                current_version="1.0.0",
                override_file=override_path,
            )

            status = service.check_for_updates()

            self.assertTrue(status.available)
            self.assertEqual(os.path.abspath(asset_path), status.asset_url)

    def test_check_failure_is_reported_in_status(self):
        import requests

        service = UpdateService(
            FakePlatform(),
            session=RaisingSession(requests.ConnectionError("boom")),
            current_version="1.0.0",
            override_file="",
        )

        status = service.check_for_updates()

        self.assertTrue(status.checked)
        self.assertFalse(status.available)
        self.assertEqual("API error: network unavailable", status.check_error)
        self.assertEqual(
            "API error: network unavailable",
            service.get_status().check_error,
        )

    def test_unexpected_check_failure_uses_generic_error(self):
        service = UpdateService(
            FakePlatform(),
            session=RaisingSession(RuntimeError("boom")),
            current_version="1.0.0",
            override_file="",
        )

        status = service.check_for_updates()

        self.assertTrue(status.checked)
        self.assertFalse(status.available)
        self.assertEqual("Update check failed.", status.check_error)

    def test_successful_check_clears_check_error(self):
        payload = {"tag_name": "v1.0.0", "html_url": "https://example.test/release"}
        service = UpdateService(
            FakePlatform(),
            session=FakeSession(FakeResponse(payload)),
            current_version="1.0.0",
            override_file="",
        )

        status = service.check_for_updates()

        self.assertTrue(status.checked)
        self.assertIsNone(status.check_error)

    def _override_service(self, tmpdir):
        asset_path = os.path.join(tmpdir, "CheevoPresence.exe")
        override_path = os.path.join(tmpdir, "update-test.json")
        with open(asset_path, "wb") as handle:
            handle.write(b"exe")
        with open(override_path, "w", encoding="utf-8") as handle:
            handle.write('{"latest_version":"2.0.0","asset_path":"CheevoPresence.exe"}')
        return UpdateService(
            FakePlatform(),
            session=FakeSession(FakeResponse({})),
            current_version="1.0.0",
            override_file=override_path,
        )

    def test_frozen_build_ignores_override_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._override_service(tmpdir)

            environ = {key: value for key, value in os.environ.items() if key != UPDATE_OVERRIDE_ENV}
            with (
                mock.patch.object(sys, "frozen", True, create=True),
                mock.patch.dict(os.environ, environ, clear=True),
            ):
                status = service.check_for_updates()

            self.assertTrue(status.checked)
            self.assertFalse(status.available)
            self.assertIsNone(status.asset_url)

    def test_frozen_build_honors_override_with_env_opt_in(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._override_service(tmpdir)

            with (
                mock.patch.object(sys, "frozen", True, create=True),
                mock.patch.dict(os.environ, {UPDATE_OVERRIDE_ENV: "1"}),
            ):
                status = service.check_for_updates()

            self.assertTrue(status.available)
            self.assertEqual("2.0.0", status.latest_version)

    def test_install_update_downloads_and_stages_asset(self):
        platform = FakePlatform()
        service = UpdateService(
            platform,
            session=FakeSession(FakeResponse(chunks=[b"abc", b"def"])),
            current_version="1.0.0",
            override_file="",
        )
        service._status.available = True
        service._status.asset_name = "CheevoPresence.exe"
        service._status.asset_url = "https://example.test/exe"
        service._status.asset_sha256 = hashlib.sha256(b"abcdef").hexdigest()

        result = service.install_update(relaunch_args=["--tray"], source_pid=123)

        self.assertTrue(result.success)
        staged_path, relaunch_args, source_pid = platform.staged
        self.assertEqual(["--tray"], relaunch_args)
        self.assertEqual(123, source_pid)
        with open(staged_path, "rb") as handle:
            self.assertEqual(b"abcdef", handle.read())

    def test_install_update_confines_malicious_asset_name_to_download_dir(self):
        platform = FakePlatform()
        service = UpdateService(
            platform,
            session=FakeSession(FakeResponse(chunks=[b"abc"])),
            current_version="1.0.0",
            override_file="",
        )
        service._status.available = True
        service._status.asset_name = "../../evil.exe"
        service._status.asset_url = "https://example.test/exe"
        service._status.asset_sha256 = hashlib.sha256(b"abc").hexdigest()

        result = service.install_update()

        self.assertTrue(result.success)
        staged_path, _, _ = platform.staged
        self.assertEqual("evil.exe", os.path.basename(staged_path))
        self.assertTrue(
            os.path.basename(os.path.dirname(staged_path)).startswith(
                "CheevoPresence-download-"
            )
        )

    def test_install_update_refuses_unverified_asset(self):
        platform = FakePlatform()
        service = UpdateService(
            platform,
            session=FakeSession(FakeResponse(chunks=[b"abc"])),
            current_version="1.0.0",
            override_file="",
        )
        service._status.available = True
        service._status.asset_name = "CheevoPresence.exe"
        service._status.asset_url = "https://example.test/exe"

        result = service.install_update()

        self.assertFalse(result.success)
        self.assertEqual("Update Verification Unavailable", result.error_title)
        self.assertIsNone(platform.staged)

    def test_install_update_refuses_checksum_mismatch(self):
        platform = FakePlatform()
        service = UpdateService(
            platform,
            session=FakeSession(FakeResponse(chunks=[b"abc"])),
            current_version="1.0.0",
            override_file="",
        )
        service._status.available = True
        service._status.asset_name = "CheevoPresence.exe"
        service._status.asset_url = "https://example.test/exe"
        service._status.asset_sha256 = hashlib.sha256(b"different").hexdigest()

        result = service.install_update()

        self.assertFalse(result.success)
        self.assertEqual("Update Verification Failed", result.error_title)
        self.assertIsNone(platform.staged)


if __name__ == "__main__":
    unittest.main()
