import logging
import os
import tempfile
import unittest

from desktop.runtime import storage


class FakePlatform:
    """Minimal platform adapter that base64-rounds the API key like generic."""

    def __init__(self, root):
        self.root = root

    def get_config_dir(self, app_name, runtime_root_dir):
        return os.path.join(self.root, app_name)

    def protect_api_key(self, value):
        return f"protected:{value}" if value else ""

    def unprotect_api_key(self, value):
        if isinstance(value, str) and value.startswith("protected:"):
            return value[len("protected:") :]
        return value or ""


SECRET_API_KEY = "TOP_SECRET_KEY_VALUE"


class ConfigLoggingTests(unittest.TestCase):
    def test_save_and_load_log_presence_without_leaking_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            platform = FakePlatform(tmpdir)
            logger = logging.getLogger("desktop.runtime.storage")

            with self.assertLogs(logger, level="INFO") as logs:
                storage.save_config(
                    {"username": "bob", "apikey": SECRET_API_KEY},
                    platform,
                )
                storage.load_config(platform)

            output = "\n".join(logs.output)
            self.assertIn("[CONFIG] save", output)
            self.assertIn("[CONFIG] load", output)
            self.assertIn("apikey_present=True", output)
            self.assertNotIn(SECRET_API_KEY, output)


if __name__ == "__main__":
    unittest.main()
