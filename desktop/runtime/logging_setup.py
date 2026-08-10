"""Shared runtime logging setup for desktop shells."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from desktop.core.log_events import AREA_STARTUP, log_event
from desktop.runtime.storage import get_log_file

LOGGER_NAME = "desktop"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MAX_LOG_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 5
HANDLER_MARKER = "_cheevo_runtime_log_handler"
# Set CHEEVO_LOG_LEVEL=DEBUG (or INFO/WARNING) to override the default level.
LOG_LEVEL_ENV = "CHEEVO_LOG_LEVEL"


def _resolve_level(level):
    requested = os.environ.get(LOG_LEVEL_ENV, "").strip().upper()
    if requested:
        resolved = logging.getLevelName(requested)
        if isinstance(resolved, int):
            return resolved
    return level


def _is_runtime_handler(handler):
    return bool(getattr(handler, HANDLER_MARKER, False))


def _same_log_file(handler, log_file):
    current = getattr(handler, "baseFilename", None)
    return bool(current and os.path.abspath(current) == os.path.abspath(log_file))


def setup_logging(platform=None, level=logging.INFO):
    level = _resolve_level(level)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    for noisy_logger in ("urllib3", "requests"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

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
    log_event(logger, AREA_STARTUP, "logging_initialized", log_file=log_file)
    return log_file
