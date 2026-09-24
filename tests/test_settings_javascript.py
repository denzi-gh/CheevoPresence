import shutil
import subprocess
import unittest
from pathlib import Path


class SettingsJavaScriptTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for settings JavaScript tests")
    def test_polling_recovers_and_updates_the_preview(self):
        result = subprocess.run(
            [shutil.which("node"), "--test", str(Path(__file__).with_name("settings_polling.cjs"))],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
