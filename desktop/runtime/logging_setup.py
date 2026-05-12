"""Shared runtime logging setup for desktop shells."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from desktop.runtime.storage import get_log_file

LOGGER_NAME = "desktop"
LOG_FORMAT = "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"
MAX_LOG_BYTES = 1024 * 1024
BACKUP_COUNT = 5
HANDLER_MARKER = "_cheevo_runtime_log_handler"


def _is_runtime_handler(handler):
    """Return whether a handler is owned by this setup helper."""
    return bool(getattr(handler, HANDLER_MARKER, False))


def _same_log_file(handler, log_file):
    """Return whether a rotating handler already points at the target file."""
    current = getattr(handler, "baseFilename", None)
    return bool(current and os.path.abspath(current) == os.path.abspath(log_file))


def setup_logging(platform=None, level=logging.INFO):
    """Configure rotating file logging once and return the target log path."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    log_file = get_log_file(platform)
    for handler in logger.handlers:
        if _is_runtime_handler(handler) and _same_log_file(handler, log_file):
            return log_file

    for handler in list(logger.handlers):
        if _is_runtime_handler(handler):
            logger.removeHandler(handler)
            handler.close()

    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        handler = RotatingFileHandler(
            log_file,
            maxBytes=MAX_LOG_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        if getattr(sys, "frozen", False):
            handler = logging.NullHandler()
        else:
            handler = logging.StreamHandler(sys.stderr)

    setattr(handler, HANDLER_MARKER, True)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    logger.info("Logging initialized")
    return log_file
