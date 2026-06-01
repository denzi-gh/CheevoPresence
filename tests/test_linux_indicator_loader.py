import os
import sys
import tempfile
import types
import unittest
from unittest import mock

from PIL import Image

from desktop.shell.linux import indicator


class LinuxIndicatorLoaderTests(unittest.TestCase):
    def test_loader_imports_gtk_and_prefers_ayatana_appindicator(self):
        calls = []
        fake_gi = types.ModuleType("gi")
        fake_repository = types.ModuleType("gi.repository")
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
        self.assertIn(("Gtk", "3.0"), calls)
        self.assertIn(("AyatanaAppIndicator3", "0.1"), calls)

    def test_loader_ignores_broken_glib_unix_signal_deprecation(self):
        class FakeRepository(types.ModuleType):
            def __getattr__(self, name):
                if name == "GLib":
                    fake_overrides.deprecated_attr(
                        "GLib",
                        "unix_signal_add_full",
                        "GLibUnix.signal_add",
                    )
                    fake_overrides.deprecated_attr("GLib", "other", "replacement")
                    return fake_glib
                if name == "Gtk":
                    return fake_gtk
                if name == "AyatanaAppIndicator3":
                    return fake_appindicator
                raise AttributeError(name)

        fake_gi = types.ModuleType("gi")
        fake_overrides = types.ModuleType("gi.overrides")
        fake_repository = FakeRepository("gi.repository")
        fake_glib = object()
        fake_gtk = object()
        fake_appindicator = object()
        deprecated_attrs = []

        def require_version(_namespace, _version):
            pass

        def deprecated_attr(namespace, attr, replacement):
            deprecated_attrs.append((namespace, attr, replacement))

        fake_gi.require_version = require_version
        fake_gi.overrides = fake_overrides
        fake_overrides.deprecated_attr = deprecated_attr

        modules = {
            "gi": fake_gi,
            "gi.overrides": fake_overrides,
            "gi.repository": fake_repository,
        }

        with mock.patch.dict(sys.modules, modules):
            gtk, glib, appindicator = indicator._load_indicator_modules()

        self.assertIs(fake_gtk, gtk)
        self.assertIs(fake_glib, glib)
        self.assertIs(fake_appindicator, appindicator)
        self.assertIs(fake_overrides.deprecated_attr, deprecated_attr)
        self.assertEqual([("GLib", "other", "replacement")], deprecated_attrs)

    def test_backend_prefers_appindicator_on_x11(self):
        Gtk = types.SimpleNamespace(StatusIcon=object())
        AppIndicator = object()

        backend = indicator._select_linux_tray_backend(
            Gtk,
            AppIndicator,
            session_type="x11",
        )

        self.assertEqual("appindicator", backend)

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

    def test_appindicator_uses_icon_name_with_theme_path(self):
        class FakeIndicator:
            def __init__(self):
                self.theme_paths = []
                self.icons = []
                self.menu = None
                self.status = None

            def set_icon_theme_path(self, path):
                self.theme_paths.append(path)

            def set_icon_full(self, icon_name, description):
                self.icons.append((icon_name, description))

            def set_title(self, _title):
                pass

            def set_menu(self, menu):
                self.menu = menu

            def set_status(self, status):
                self.status = status

        class FakeIndicatorFactory:
            created_args = None

            @staticmethod
            def new_with_path(app_id, icon_name, category, icon_dir):
                FakeIndicatorFactory.created_args = (
                    app_id,
                    icon_name,
                    category,
                    icon_dir,
                )
                return FakeIndicator()

        app = indicator.LinuxIndicatorApp.__new__(indicator.LinuxIndicatorApp)
        app.AppIndicator = types.SimpleNamespace(
            Indicator=FakeIndicatorFactory,
            IndicatorCategory=types.SimpleNamespace(APPLICATION_STATUS="application"),
            IndicatorStatus=types.SimpleNamespace(ACTIVE="active"),
        )
        app.current_status = "connected"
        app._build_menu = lambda: object()

        with mock.patch.object(
            indicator,
            "get_linux_indicator_icon",
            return_value=(
                "/tmp/cheevo-icons",
                "cheevo-presence-connected",
                "/tmp/cheevo-icons/cheevo-presence-connected.png",
            ),
        ):
            created = app._create_indicator()

        self.assertEqual(
            (
                indicator.APP_NAME,
                "cheevo-presence-connected",
                "application",
                "/tmp/cheevo-icons",
            ),
            FakeIndicatorFactory.created_args,
        )
        self.assertEqual(["/tmp/cheevo-icons"], created.theme_paths)
        self.assertEqual(
            [("cheevo-presence-connected", indicator.APP_NAME)],
            created.icons,
        )
        self.assertEqual("active", created.status)

    def test_png_copy_refreshes_stale_runtime_icon(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "source.png")
            runtime_dir = os.path.join(tmpdir, "runtime")
            output_path = os.path.join(runtime_dir, "linux-tray-test.png")

            os.makedirs(runtime_dir)
            Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(source_path)
            Image.new("RGBA", (64, 64), (0, 0, 255, 255)).save(output_path)
            os.utime(output_path, (1, 1))

            with mock.patch.object(indicator, "get_runtime_dir", return_value=runtime_dir):
                result = indicator._png_copy_for_icon(source_path, "linux-tray-test")

            self.assertEqual(output_path, result)
            with Image.open(output_path) as image:
                self.assertEqual((64, 64), image.size)
                self.assertEqual((255, 0, 0, 255), image.convert("RGBA").getpixel((0, 0)))

    def test_backend_fails_when_no_native_tray_exists(self):
        Gtk = types.SimpleNamespace()

        with self.assertRaises(indicator.LinuxTrayUnavailable):
            indicator._select_linux_tray_backend(Gtk, None)


if __name__ == "__main__":
    unittest.main()
