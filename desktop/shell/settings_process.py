"""Launch the settings child while keeping the host as the sole log writer."""

from __future__ import annotations

import logging
import subprocess
import threading

from desktop.core.log_events import AREA_SETTINGS, format_event
from desktop.runtime.logging_setup import (
    LOG_SESSION_ENV,
    decode_child_log_line,
    get_log_session_id,
)

logger = logging.getLogger(__name__)


def _emit_settings_record(
    logger_name,
    level,
    message,
    *,
    created=None,
    pid=None,
    thread=None,
    session=None,
):
    target = logging.getLogger(logger_name)
    if not target.isEnabledFor(level):
        return

    record = target.makeRecord(logger_name, level, "", 0, message, (), None)
    if created is not None:
        record.created = created
        record.msecs = (created - int(created)) * 1000
    if pid is not None:
        record.process = pid
    if thread is not None:
        record.threadName = thread
    record.process_role = "settings"
    record.log_session = session or get_log_session_id()
    target.handle(record)


def _forward_settings_output_line(line, fallback_pid=None):
    payload = decode_child_log_line(line)
    if payload is None:
        raw_line = str(line).rstrip("\r\n")
        if raw_line:
            _emit_settings_record(
                logger.name,
                logging.INFO,
                format_event(
                    AREA_SETTINGS,
                    "client_output",
                    pid=fallback_pid,
                    output=raw_line,
                ),
                pid=fallback_pid,
            )
        return

    _emit_settings_record(
        payload["logger"],
        payload["level"],
        payload["message"],
        created=payload["created"],
        pid=payload["pid"] or fallback_pid,
        thread=payload["thread"],
        session=payload["session"],
    )


def _capture_settings_output(process):
    stream = process.stdout
    if stream is None:
        return
    try:
        for line in stream:
            _forward_settings_output_line(line, fallback_pid=process.pid)
    except (OSError, ValueError) as exc:
        _emit_settings_record(
            logger.name,
            logging.WARNING,
            format_event(
                AREA_SETTINGS,
                "client_output_failed",
                pid=process.pid,
                error_type=exc.__class__.__name__,
            ),
            pid=process.pid,
        )
    finally:
        try:
            stream.close()
        except OSError:
            pass


def launch_settings_process(command, env, *, start_new_session=False):
    """Start a settings child and asynchronously forward all of its output."""
    child_env = dict(env)
    child_env[LOG_SESSION_ENV] = get_log_session_id()
    process = subprocess.Popen(
        command,
        env=child_env,
        start_new_session=start_new_session,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    thread = threading.Thread(
        target=_capture_settings_output,
        args=(process,),
        daemon=True,
        name=f"SettingsOutput-{process.pid}",
    )
    process._cheevo_output_thread = thread
    thread.start()
    return process


def finish_settings_output_capture(process, timeout=1):
    """Give the output reader a bounded chance to drain after child exit."""
    thread = getattr(process, "_cheevo_output_thread", None)
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=timeout)


__all__ = ["finish_settings_output_capture", "launch_settings_process"]
