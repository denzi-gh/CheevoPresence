"""Shared runtime logging setup for desktop shells."""

import json
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
CHILD_LOG_PREFIX = "@cheevo-log "
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


def _remove_runtime_handlers(logger):
    for handler in list(logger.handlers):
        if _is_runtime_handler(handler):
            logger.removeHandler(handler)
            handler.close()


class ChildLogFormatter(logging.Formatter):
    """Encode one settings-client record for the host's single log writer."""

    def format(self, record):
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        if record.stack_info:
            message = f"{message}\n{self.formatStack(record.stack_info)}"
        payload = {
            "created": record.created,
            "level": record.levelno,
            "logger": record.name,
            "message": message,
            "pid": record.process,
            "thread": record.threadName,
        }
        return CHILD_LOG_PREFIX + json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
        )


def decode_child_log_line(line):
    """Return a validated child-record payload, or ``None`` for raw output."""
    if not isinstance(line, str) or not line.startswith(CHILD_LOG_PREFIX):
        return None
    try:
        payload = json.loads(line[len(CHILD_LOG_PREFIX) :])
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    name = payload.get("logger")
    message = payload.get("message")
    level = payload.get("level")
    if not isinstance(name, str) or not name.startswith("desktop"):
        return None
    if not isinstance(message, str):
        return None
    if not isinstance(level, int) or level < logging.DEBUG or level > logging.CRITICAL:
        return None

    pid = payload.get("pid")
    thread_name = payload.get("thread")
    created = payload.get("created")
    return {
        "created": created if isinstance(created, (int, float)) else None,
        "level": level,
        "logger": name,
        "message": message,
        "pid": pid if isinstance(pid, int) else None,
        "thread": thread_name if isinstance(thread_name, str) else None,
    }


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
            handler.setLevel(level)
            return log_file

    _remove_runtime_handlers(logger)

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


def setup_child_logging(level=logging.INFO, stream=None):
    """Send settings-client logs to the host instead of opening its log file."""
    level = _resolve_level(level)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    for noisy_logger in ("urllib3", "requests"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    _remove_runtime_handlers(logger)
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    setattr(handler, HANDLER_MARKER, True)
    handler.setLevel(level)
    handler.setFormatter(ChildLogFormatter())
    logger.addHandler(handler)
    log_event(logger, AREA_STARTUP, "logging_initialized", sink="host_forwarder")


def get_log_level():
    """Effective level of the app logger that writes cheevo.log."""
    return logging.getLogger(LOGGER_NAME).level


def set_log_level(level):
    """Set the app logger's level *and* its file handler's level."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    for handler in logger.handlers:
        if _is_runtime_handler(handler):
            handler.setLevel(level)
    return logger.level
