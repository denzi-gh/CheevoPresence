import sys
import types
import unittest
from unittest import mock

from desktop.shell.linux import indicator


class LinuxIndicatorLoaderTests(unittest.TestCase):
    def test_loader_imports_glib_unix_before_glib(self):
        calls = []
        fake_gi = types.ModuleType("gi")
        fake_repository = types.ModuleType("gi.repository")
        fake_repository.GLibUnix = object()
        fake_repository.GLib = object()
        fake_repository.Gtk = object()
        fake_repository.AyatanaAppIndicator3 = object()

        def require_version(namespace, version):
            calls.append((namespace, version))

        fake_gi.require_version = require_version

        modules = {
            "gi": fake_gi,
            "gi.repository": fake_repository,
        }

        with mock.patch.dict(sys.modules, modules):
            gtk, glib, appindicator = indicator._load_indicator_modules()

        self.assertIs(fake_repository.Gtk, gtk)
        self.assertIs(fake_repository.GLib, glib)
        self.assertIs(fake_repository.AyatanaAppIndicator3, appindicator)
        self.assertEqual(("GLibUnix", "2.0"), calls[0])
        self.assertIn(("Gtk", "3.0"), calls)
        self.assertIn(("AyatanaAppIndicator3", "0.1"), calls)

    def test_backend_prefers_status_icon_on_x11(self):
        Gtk = types.SimpleNamespace(StatusIcon=object())
        AppIndicator = object()

        backend = indicator._select_linux_tray_backend(
            Gtk,
            AppIndicator,
            session_type="x11",
        )

        self.assertEqual("statusicon", backend)

    def test_backend_prefers_appindicator_on_wayland(self):
        Gtk = types.SimpleNamespace(StatusIcon=object())
        AppIndicator = object()

        backend = indicator._select_linux_tray_backend(
            Gtk,
            AppIndicator,
            session_type="wayland",
        )

        self.assertEqual("appindicator", backend)

    def test_backend_uses_status_icon_when_appindicator_missing(self):
        Gtk = types.SimpleNamespace(StatusIcon=object())

        backend = indicator._select_linux_tray_backend(
            Gtk,
            None,
            session_type="wayland",
        )

        self.assertEqual("statusicon", backend)

    def test_backend_fails_when_no_native_tray_exists(self):
        Gtk = types.SimpleNamespace()

        with self.assertRaises(indicator.LinuxTrayUnavailable):
            indicator._select_linux_tray_backend(Gtk, None)


if __name__ == "__main__":
    unittest.main()
