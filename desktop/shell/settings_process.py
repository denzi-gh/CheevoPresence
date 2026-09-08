"""Launch the settings child while keeping the host as the sole log writer."""

from __future__ import annotations

import logging
import subprocess
import threading

from desktop.core.log_events import AREA_SETTINGS, log_event
from desktop.runtime.logging_setup import decode_child_log_line

logger = logging.getLogger(__name__)


def _forward_settings_output_line(line, fallback_pid=None):
    payload = decode_child_log_line(line)
    if payload is None:
        raw_line = str(line).rstrip("\r\n")
        if raw_line:
            log_event(
                logger,
                AREA_SETTINGS,
                "client_output",
                pid=fallback_pid,
                output=raw_line,
            )
        return

    target = logging.getLogger(payload["logger"])
    level = payload["level"]
    if not target.isEnabledFor(level):
        return

    record = target.makeRecord(
        payload["logger"],
        level,
        "",
        0,
        payload["message"],
        (),
        None,
    )
    if payload["created"] is not None:
        record.created = payload["created"]
        record.msecs = (record.created - int(record.created)) * 1000
    if payload["pid"] is not None:
        record.process = payload["pid"]
    elif fallback_pid is not None:
        record.process = fallback_pid
    if payload["thread"] is not None:
        record.threadName = payload["thread"]
    target.handle(record)


def _capture_settings_output(process):
    stream = process.stdout
    if stream is None:
        return
    try:
        for line in stream:
            _forward_settings_output_line(line, fallback_pid=process.pid)
    except (OSError, ValueError) as exc:
        log_event(
            logger,
            AREA_SETTINGS,
            "client_output_failed",
            level=logging.WARNING,
            pid=process.pid,
            error_type=exc.__class__.__name__,
        )
    finally:
        try:
            stream.close()
        except OSError:
            pass


def launch_settings_process(command, env, *, start_new_session=False):
    """Start a settings child and asynchronously forward all of its output."""
    process = subprocess.Popen(
        command,
        env=env,
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
