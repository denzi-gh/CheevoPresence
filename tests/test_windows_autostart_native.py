import os
import unittest
from unittest.mock import patch

try:
    from desktop.platform import windows as windows_platform
except ImportError:  # tkinter can be missing on headless CI images
    windows_platform = None

TEST_REG_NAME = "CheevoPresenceCITest"


@unittest.skipUnless(os.name == "nt", "requires the real Windows registry")
@unittest.skipIf(windows_platform is None, "windows platform module unavailable")
class WindowsAutostartNativeTests(unittest.TestCase):
    """Real HKCU roundtrip under a test value name, so CI exercises winreg."""

    def _delete_test_value(self):
        import winreg

        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                windows_platform.STARTUP_REG_KEY,
                0,
                winreg.KEY_SET_VALUE,
            )
        except OSError:
            return
        try:
            winreg.DeleteValue(key, TEST_REG_NAME)
        except FileNotFoundError:
            pass
        finally:
            winreg.CloseKey(key)

    def test_registry_roundtrip(self):
        import winreg

        with patch.object(windows_platform, "STARTUP_REG_NAME", TEST_REG_NAME):
            try:
                self.assertIsNone(windows_platform.set_autostart(True))
                self.assertTrue(windows_platform.is_autostart_enabled())

                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    windows_platform.STARTUP_REG_KEY,
                    0,
                    winreg.KEY_READ,
                )
                try:
                    value, _kind = winreg.QueryValueEx(key, TEST_REG_NAME)
                finally:
                    winreg.CloseKey(key)
                self.assertIn("--tray", value)

                self.assertIsNone(windows_platform.set_autostart(False))
                self.assertFalse(windows_platform.is_autostart_enabled())
            finally:
                self._delete_test_value()


if __name__ == "__main__":
    unittest.main()
