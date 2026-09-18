import io
import logging
import os
import re
import tempfile
import unittest
from logging.handlers import RotatingFileHandler
from unittest.mock import patch

from desktop.core.log_events import register_log_secret
from desktop.runtime.controller import AppController
from desktop.runtime.logging_setup import (
    BACKUP_COUNT,
    HANDLER_MARKER,
    LOG_LEVEL_ENV,
    MAX_LOG_BYTES,
    decode_child_log_line,
    get_log_level,
    normalize_log_level,
    set_log_level,
    setup_child_logging,
    setup_logging,
    tail_log_lines,
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

    def test_unconfigured_log_level_reports_application_default(self):
        app_logger = logging.getLogger("desktop")
        original_level = app_logger.level
        try:
            app_logger.setLevel(logging.NOTSET)
            self.assertEqual(logging.INFO, get_log_level())
        finally:
            app_logger.setLevel(original_level)

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

    def test_set_log_level_updates_runtime_handlers_and_future_children(self):
        app_logger = logging.getLogger("desktop")
        original_level = app_logger.level
        handler = logging.NullHandler()
        setattr(handler, HANDLER_MARKER, True)
        handler.setLevel(logging.INFO)
        app_logger.addHandler(handler)
        try:
            with patch.dict(os.environ, {LOG_LEVEL_ENV: ""}):
                self.assertEqual(logging.DEBUG, set_log_level("debug"))
                self.assertEqual(logging.DEBUG, app_logger.level)
                self.assertEqual(logging.DEBUG, handler.level)
                self.assertEqual("DEBUG", os.environ[LOG_LEVEL_ENV])
        finally:
            app_logger.removeHandler(handler)
            handler.close()
            app_logger.setLevel(original_level)

    def test_log_level_rejects_unknown_and_ambiguous_values(self):
        for value in ("verbose", logging.NOTSET, True, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_log_level(value)

    def test_tail_log_lines_returns_bounded_recent_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            platform = FakePlatform(tmpdir)
            log_file = setup_logging(platform)
            logging.getLogger("desktop.test").info("tail first")
            logging.getLogger("desktop.test").info("tail second")
            logging.getLogger("desktop.test").info("tail third")

            tail = tail_log_lines(platform, lines=2)

            self.assertEqual(2, len(tail))
            self.assertIn("tail second", tail[0])
            self.assertIn("tail third", tail[1])
            self.assertEqual([], tail_log_lines(FakePlatform(f"{tmpdir}-missing")))
            self.assertTrue(os.path.exists(log_file))
            self._close_runtime_handlers()

    def test_controller_exposes_host_log_tail_and_level(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {LOG_LEVEL_ENV: ""},
        ):
            platform = FakePlatform(tmpdir)
            setup_logging(platform)
            try:
                logging.getLogger("desktop.test").info("controller tail marker")
                controller = object.__new__(AppController)
                controller.platform = platform

                tail = controller.tail_logs(lines=1)
                level = controller.set_log_level("ERROR")

                self.assertIn("controller tail marker", tail["lines"][0])
                self.assertEqual(get_log_dir(platform), tail["path"])
                self.assertEqual("INFO", tail["level"])
                self.assertEqual({"success": True, "level": "ERROR"}, level)
                self.assertEqual(logging.ERROR, get_log_level())
            finally:
                self._close_runtime_handlers()

    def test_file_formatter_redacts_direct_exceptions_into_one_line(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            platform = FakePlatform(tmpdir)
            secret = "DIRECT_EXCEPTION_SECRET"
            register_log_secret(secret)
            log_file = setup_logging(platform)
            try:
                raise RuntimeError(
                    f"failed {secret} at https://example.test/api?token={secret}"
                )
            except RuntimeError:
                logging.getLogger("desktop.test").exception("direct logger failure")
            self._close_runtime_handlers()

            with open(log_file, "r", encoding="utf-8") as handle:
                lines = handle.read().splitlines()

        self.assertEqual(2, len(lines))
        self.assertNotIn(secret, "\n".join(lines))
        self.assertNotIn("?token=", "\n".join(lines))
        self.assertIn("RuntimeError", lines[-1])
        self.assertIn(r"\nTraceback", lines[-1])
        self.assertRegex(
            lines[-1],
            re.compile(
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z ERROR "
                r"process=host pid=\d+ thread=MainThread session=[0-9a-f]{8} "
            ),
        )


if __name__ == "__main__":
    unittest.main()
