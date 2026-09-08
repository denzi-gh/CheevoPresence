import io
import logging
import os
import tempfile
import unittest
from logging.handlers import RotatingFileHandler

from desktop.runtime.logging_setup import (
    BACKUP_COUNT,
    HANDLER_MARKER,
    MAX_LOG_BYTES,
    decode_child_log_line,
    setup_child_logging,
    setup_logging,
)
from desktop.runtime.storage import get_log_dir, get_log_file


class FakePlatform:
    def __init__(self, root):
        self.root = root

    def get_config_dir(self, app_name, runtime_root_dir):
        return os.path.join(self.root, app_name)


class RuntimeLoggingTests(unittest.TestCase):
    def _close_runtime_handlers(self):
        logger = logging.getLogger("desktop")
        for handler in list(logger.handlers):
            if getattr(handler, HANDLER_MARKER, False):
                logger.removeHandler(handler)
                handler.close()
        logger.propagate = True

    def tearDown(self):
        self._close_runtime_handlers()

    def test_log_paths_live_under_platform_config_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            platform = FakePlatform(tmpdir)

            self.assertEqual(
                os.path.join(tmpdir, "CheevoPresence", "logs"),
                get_log_dir(platform),
            )
            self.assertEqual(
                os.path.join(tmpdir, "CheevoPresence", "logs", "cheevo.log"),
                get_log_file(platform),
            )

    def test_setup_logging_clamps_http_client_loggers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            platform = FakePlatform(tmpdir)
            try:
                setup_logging(platform)

                self.assertEqual(logging.WARNING, logging.getLogger("urllib3").level)
                self.assertEqual(logging.WARNING, logging.getLogger("requests").level)
            finally:
                logging.getLogger("urllib3").setLevel(logging.NOTSET)
                logging.getLogger("requests").setLevel(logging.NOTSET)
                self._close_runtime_handlers()

    def test_setup_logging_creates_one_rotating_handler(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            platform = FakePlatform(tmpdir)

            log_file = setup_logging(platform)
            self.assertEqual(log_file, setup_logging(platform))

            logger = logging.getLogger("desktop")
            handlers = [
                handler
                for handler in logger.handlers
                if getattr(handler, HANDLER_MARKER, False)
            ]

            self.assertEqual(1, len(handlers))
            self.assertIsInstance(handlers[0], RotatingFileHandler)
            self.assertEqual(MAX_LOG_BYTES, handlers[0].maxBytes)
            self.assertEqual(BACKUP_COUNT, handlers[0].backupCount)
            self.assertTrue(os.path.isdir(os.path.dirname(log_file)))
            self.assertTrue(os.path.exists(log_file))
            self._close_runtime_handlers()

    def test_settings_child_uses_forwarding_stream_without_file_handler(self):
        stream = io.StringIO()

        setup_child_logging(stream=stream)
        logging.getLogger("desktop.shell.settings_client").info("child record")

        handlers = [
            handler
            for handler in logging.getLogger("desktop").handlers
            if getattr(handler, HANDLER_MARKER, False)
        ]
        self.assertEqual(1, len(handlers))
        self.assertNotIsInstance(handlers[0], RotatingFileHandler)

        records = [decode_child_log_line(line) for line in stream.getvalue().splitlines()]
        self.assertEqual("child record", records[-1]["message"])
        self.assertEqual("desktop.shell.settings_client", records[-1]["logger"])

    def test_repeated_setup_updates_existing_file_handler_level(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            platform = FakePlatform(tmpdir)
            setup_logging(platform, level=logging.INFO)

            setup_logging(platform, level=logging.DEBUG)

            handlers = [
                handler
                for handler in logging.getLogger("desktop").handlers
                if getattr(handler, HANDLER_MARKER, False)
            ]
            self.assertEqual(logging.DEBUG, handlers[0].level)
            self._close_runtime_handlers()


if __name__ == "__main__":
    unittest.main()
