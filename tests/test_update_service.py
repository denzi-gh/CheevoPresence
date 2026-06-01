import os
import tempfile
import unittest

from desktop.runtime.update_service import UpdateService


class FakeResponse:
    def __init__(self, payload=None, chunks=None):
        self.payload = payload if payload is not None else {}
        self.chunks = chunks or []

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
        return None


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

        result = service.install_update(relaunch_args=["--tray"], source_pid=123)

        self.assertTrue(result.success)
        staged_path, relaunch_args, source_pid = platform.staged
        self.assertEqual(["--tray"], relaunch_args)
        self.assertEqual(123, source_pid)
        with open(staged_path, "rb") as handle:
            self.assertEqual(b"abcdef", handle.read())


if __name__ == "__main__":
    unittest.main()
