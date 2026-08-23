import os
import tempfile
import unittest
from unittest.mock import patch

try:
    from desktop.platform import windows as windows_platform
except ImportError:  # tkinter can be missing on headless CI images
    windows_platform = None


@unittest.skipIf(windows_platform is None, "windows platform module unavailable")
class CleanupStaleUpdateArtifactsTests(unittest.TestCase):
    def test_sweep_removes_matching_dirs_and_leaves_everything_else(self):
        with tempfile.TemporaryDirectory() as root:
            update_dir = os.path.join(root, "CheevoPresence-update-abc123")
            download_dir = os.path.join(root, "CheevoPresence-download-def456")
            other_dir = os.path.join(root, "SomeOtherApp-update-xyz")
            os.mkdir(update_dir)
            os.mkdir(download_dir)
            os.mkdir(other_dir)
            # Matching name but a plain file: must be left alone.
            stray_file = os.path.join(root, "CheevoPresence-update-notes.txt")
            with open(stray_file, "w", encoding="utf-8") as handle:
                handle.write("keep")

            removed = windows_platform.cleanup_stale_update_artifacts(temp_root=root)

            self.assertEqual(2, removed)
            self.assertFalse(os.path.exists(update_dir))
            self.assertFalse(os.path.exists(download_dir))
            self.assertTrue(os.path.isdir(other_dir))
            self.assertTrue(os.path.exists(stray_file))

    def test_sweep_tolerates_a_missing_temp_root(self):
        missing = os.path.join(tempfile.gettempdir(), "cheevo-does-not-exist")
        self.assertEqual(0, windows_platform.cleanup_stale_update_artifacts(temp_root=missing))


@unittest.skipIf(windows_platform is None, "windows platform module unavailable")
class UpdateHelperCleanupTests(unittest.TestCase):
    def test_helper_spawns_only_the_relaunch_and_never_cmd_exe(self):
        with tempfile.TemporaryDirectory() as root:
            helper_dir = os.path.join(root, "CheevoPresence-update-helper")
            target_dir = os.path.join(root, "install")
            download_dir = os.path.join(root, "CheevoPresence-download-x")
            os.mkdir(helper_dir)
            os.mkdir(target_dir)
            os.mkdir(download_dir)
            target_path = os.path.join(target_dir, "CheevoPresence.exe")
            source_path = os.path.join(download_dir, "CheevoPresence.exe")
            with open(target_path, "wb") as handle:
                handle.write(b"old build")
            with open(source_path, "wb") as handle:
                handle.write(b"new build")

            argv = [
                windows_platform.UPDATE_HELPER_FLAG,
                windows_platform.UPDATE_TARGET_FLAG,
                target_path,
                windows_platform.UPDATE_SOURCE_FLAG,
                source_path,
                windows_platform.UPDATE_PARENT_PID_FLAG,
                "0",
            ]
            with (
                patch.object(
                    windows_platform,
                    "get_exe_path",
                    return_value=os.path.join(helper_dir, "CheevoPresence.exe"),
                ),
                patch.object(windows_platform.subprocess, "Popen") as popen,
            ):
                self.assertTrue(windows_platform.handle_special_args(argv))

            self.assertEqual(1, popen.call_count)
            spawned_argv = popen.call_args.args[0]
            self.assertEqual(target_path, spawned_argv[0])
            for token in spawned_argv:
                self.assertNotIn("cmd.exe", str(token).lower())

            with open(target_path, "rb") as handle:
                self.assertEqual(b"new build", handle.read())
            self.assertFalse(os.path.exists(download_dir))
            self.assertTrue(os.path.isdir(helper_dir))


if __name__ == "__main__":
    unittest.main()
