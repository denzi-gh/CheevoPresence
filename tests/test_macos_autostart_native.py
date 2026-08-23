import os
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    from desktop.platform import macos as macos_platform
except ImportError:
    macos_platform = None

from desktop.core.constants import TRAY_FLAG


@unittest.skipUnless(sys.platform == "darwin", "requires the macOS platform adapter")
@unittest.skipIf(macos_platform is None, "macos platform module unavailable")
class MacosAutostartNativeTests(unittest.TestCase):
    """Writes a real LaunchAgent plist to a temp dir; launchctl stays stubbed
    so CI never touches launchd."""

    def test_launch_agent_plist_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            plist_path = os.path.join(root, macos_platform.LAUNCH_AGENT_FILE)
            with (
                patch.object(macos_platform, "get_launch_agent_path", return_value=plist_path),
                patch.object(macos_platform, "_has_stable_install_path", return_value=True),
                patch.object(macos_platform, "_launchctl_reload", return_value=None),
                patch.object(macos_platform, "_run_launchctl") as launchctl,
            ):
                self.assertIsNone(macos_platform.set_autostart(True))
                self.assertTrue(os.path.exists(plist_path))
                with open(plist_path, "rb") as handle:
                    payload = plistlib.load(handle)
                self.assertEqual(macos_platform.LAUNCH_AGENT_ID, payload["Label"])
                self.assertTrue(payload["RunAtLoad"])
                self.assertEqual(TRAY_FLAG, payload["ProgramArguments"][-1])

                self.assertIsNone(macos_platform.set_autostart(False))
                self.assertFalse(os.path.exists(plist_path))
                # Disable calls launchctl bootout, but only through the stub.
                self.assertTrue(launchctl.called)


if __name__ == "__main__":
    unittest.main()
