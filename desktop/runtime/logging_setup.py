"""Shared runtime logging setup for desktop shells."""

import copy
import json
import logging
import os
import secrets
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from desktop.core.log_events import (
    AREA_STARTUP,
    log_event,
    redact_log_text,
    sanitize_log_value,
)
from desktop.runtime.storage import get_log_file

LOGGER_NAME = "desktop"
LOG_FORMAT = (
    "%(asctime)s %(levelname)s process=%(process_role)s pid=%(process)d "
    "thread=%(threadName)s session=%(log_session)s %(name)s: %(message)s"
)
MAX_LOG_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 5
HANDLER_MARKER = "_cheevo_runtime_log_handler"
CHILD_LOG_PREFIX = "@cheevo-log "
LOG_SESSION_ENV = "CHEEVO_LOG_SESSION"
# Set CHEEVO_LOG_LEVEL=DEBUG (or INFO/WARNING) to override the default level.
LOG_LEVEL_ENV = "CHEEVO_LOG_LEVEL"
_LOG_SESSION_ID = os.environ.get(LOG_SESSION_ENV, "").strip() or secrets.token_hex(4)
MAX_LOG_RECORD_CHARS = 64 * 1024


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


def _record_message(record, formatter):
    try:
        message = record.getMessage()
    except Exception:  # noqa: BLE001 logging must not break the caller
        message = f"<unformattable log message error_type={record.msg.__class__.__name__}>"
    try:
        if record.exc_info:
            message = f"{message}\n{formatter.formatException(record.exc_info)}"
        if record.stack_info:
            message = f"{message}\n{formatter.formatStack(record.stack_info)}"
    except Exception:  # noqa: BLE001 malformed exception state must remain loggable
        message = f"{message}\n<exception formatting failed>"
    return message


class ChildLogFormatter(logging.Formatter):
    """Encode one settings-client record for the host's single log writer."""

    def format(self, record):
        message = _record_message(record, self)
        message = redact_log_text(message)
        if len(message) > MAX_LOG_RECORD_CHARS:
            message = f"{message[:MAX_LOG_RECORD_CHARS]}...<truncated>"
        payload = {
            "created": record.created,
            "level": record.levelno,
            "logger": record.name,
            "message": message,
            "pid": record.process,
            "session": _LOG_SESSION_ID,
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
    session = payload.get("session")
    return {
        "created": created if isinstance(created, (int, float)) else None,
        "level": level,
        "logger": name,
        "message": message,
        "pid": pid if isinstance(pid, int) else None,
        "session": session if isinstance(session, str) else None,
        "thread": thread_name if isinstance(thread_name, str) else None,
    }


class SafeLogFormatter(logging.Formatter):
    """Render every record as one redacted line with stable runtime context."""

    def __init__(self, process_role="host"):
        super().__init__(LOG_FORMAT)
        self.process_role = process_role

    def formatTime(self, record, datefmt=None):
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def format(self, record):
        safe_record = copy.copy(record)
        message = redact_log_text(_record_message(record, self), escape_controls=True)
        if len(message) > MAX_LOG_RECORD_CHARS:
            message = f"{message[:MAX_LOG_RECORD_CHARS]}...<truncated>"

        safe_record.msg = message
        safe_record.args = ()
        safe_record.exc_info = None
        safe_record.exc_text = None
        safe_record.stack_info = None
        safe_record.process_role = getattr(record, "process_role", self.process_role)
        safe_record.log_session = getattr(record, "log_session", _LOG_SESSION_ID)
        safe_record.threadName = sanitize_log_value(record.threadName)
        return super().format(safe_record)


def get_log_session_id():
    return _LOG_SESSION_ID


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
            handler.setFormatter(SafeLogFormatter())
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
    handler.setFormatter(SafeLogFormatter())
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
    level = logging.getLogger(LOGGER_NAME).level
    return logging.INFO if level == logging.NOTSET else level


def set_log_level(level):
    """Set the app logger's level *and* its file handler's level."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    for handler in logger.handlers:
        if _is_runtime_handler(handler):
            handler.setLevel(level)
    return logger.level
