import logging
import unittest

from desktop.shell.linux.indicator import LinuxIndicatorApp


class FakeStatusIcon:
    def __init__(self, embedded):
        self._embedded = embedded

    def is_embedded(self):
        return self._embedded


class StatusIconEmbeddedLoggingTests(unittest.TestCase):
    def _check(self, status_icon):
        # _check_status_icon_embedded only touches the icon argument and the
        # module logger, so it is safe to call without a fully built app.
        app = LinuxIndicatorApp.__new__(LinuxIndicatorApp)
        logger = logging.getLogger("desktop.shell.linux.indicator")
        with self.assertLogs(logger, level="INFO") as logs:
            app._check_status_icon_embedded(status_icon)
        return "\n".join(logs.output)

    def test_embedded_icon_logs_info(self):
        output = self._check(FakeStatusIcon(True))
        self.assertIn("[TRAY] statusicon_embedded embedded=True", output)

    def test_unembedded_icon_logs_warning(self):
        output = self._check(FakeStatusIcon(False))
        self.assertIn("WARNING", output)
        self.assertIn("[TRAY] statusicon_not_embedded", output)
        self.assertIn("reason=desktop_did_not_show_icon", output)


if __name__ == "__main__":
    unittest.main()
