"""Best-effort redacted crash reports for fatal Python exceptions."""

from __future__ import annotations

import logging
import os
import platform as platform_module
import secrets
import sys
import tempfile
import threading
import traceback
from datetime import datetime, timezone

from desktop.core.constants import APP_NAME, APP_VERSION
from desktop.core.log_events import AREA_ERROR, log_event, redact_log_text
from desktop.runtime.storage import get_crash_dir

logger = logging.getLogger(__name__)

MAX_CRASH_REPORTS = 10
MAX_CRASH_REPORT_BYTES = 256 * 1024
CRASH_FILE_PREFIX = "crash-"
CRASH_FILE_SUFFIX = ".log"
CRASH_TRUNCATION_MARKER = "\n...<crash report truncated>\n"


class CrashReporter:
    """Capture fatal main/background-thread exceptions without replacing output."""

    def __init__(self, platform=None, process_role="host"):
        self.platform = platform
        self.process_role = str(process_role or "unknown")
        self._previous_sys_hook = None
        self._previous_thread_hook = None
        self._sys_hook_wrapper = None
        self._thread_hook_wrapper = None

    def install(self):
        if self._sys_hook_wrapper is not None:
            return self

        self._previous_sys_hook = sys.excepthook
        self._previous_thread_hook = threading.excepthook

        def sys_hook(exc_type, exc_value, exc_traceback):
            try:
                if not _is_normal_exit(exc_type):
                    self.capture_exception(
                        exc_type,
                        exc_value,
                        exc_traceback,
                        origin="main_thread",
                        thread_name=threading.current_thread().name,
                    )
            finally:
                self._previous_sys_hook(exc_type, exc_value, exc_traceback)

        def thread_hook(args):
            try:
                if not _is_normal_exit(args.exc_type):
                    thread = getattr(args, "thread", None)
                    self.capture_exception(
                        args.exc_type,
                        args.exc_value,
                        args.exc_traceback,
                        origin="background_thread",
                        thread_name=getattr(thread, "name", None),
                    )
            finally:
                self._previous_thread_hook(args)

        self._sys_hook_wrapper = sys_hook
        self._thread_hook_wrapper = thread_hook
        sys.excepthook = sys_hook
        threading.excepthook = thread_hook
        return self

    def uninstall(self):
        """Restore prior hooks when this reporter still owns them (mainly tests)."""
        if sys.excepthook is self._sys_hook_wrapper:
            sys.excepthook = self._previous_sys_hook or sys.__excepthook__
        if threading.excepthook is self._thread_hook_wrapper:
            threading.excepthook = (
                self._previous_thread_hook or threading.__excepthook__
            )
        self._sys_hook_wrapper = None
        self._thread_hook_wrapper = None

    def capture_exception(
        self,
        exc_type,
        exc_value,
        exc_traceback,
        *,
        origin="explicit_boundary",
        thread_name=None,
    ):
        """Persist and log one exception; reporting failures never escape."""
        if _is_normal_exit(exc_type):
            return None

        thread_name = thread_name or threading.current_thread().name
        report_path = None
        capture_error_type = None
        try:
            report = self._build_report(
                exc_type,
                exc_value,
                exc_traceback,
                origin=origin,
                thread_name=thread_name,
            )
            report_path = self._write_report(report)
        except Exception as exc:  # noqa: BLE001 crash reporting must never mask the original failure
            capture_error_type = exc.__class__.__name__

        try:
            log_event(
                logger,
                AREA_ERROR,
                "unhandled_exception",
                level=logging.CRITICAL,
                exc_info=(exc_type, exc_value, exc_traceback),
                origin=origin,
                process_role=self.process_role,
                thread=thread_name,
                crash_report=report_path,
                report_saved=bool(report_path),
                capture_error_type=capture_error_type,
            )
        except Exception:  # noqa: BLE001 the original exception must remain authoritative
            return report_path
        return report_path

    def _build_report(
        self,
        exc_type,
        exc_value,
        exc_traceback,
        *,
        origin,
        thread_name,
    ):
        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        try:
            formatted_traceback = "".join(
                traceback.format_exception(exc_type, exc_value, exc_traceback)
            )
        except Exception:  # noqa: BLE001 malformed exception state still gets a report
            formatted_traceback = "<traceback formatting failed>"

        exception_name = getattr(exc_type, "__name__", "UnknownException")
        report = "\n".join(
            (
                f"{APP_NAME} crash report",
                f"timestamp_utc={timestamp}",
                f"app_version={APP_VERSION}",
                f"process_role={self.process_role}",
                f"process_id={os.getpid()}",
                f"thread={thread_name}",
                f"origin={origin}",
                f"exception_type={exception_name}",
                f"python={platform_module.python_version()}",
                f"system={platform_module.system()}",
                f"release={platform_module.release()}",
                f"frozen={bool(getattr(sys, 'frozen', False))}",
                "",
                "Traceback:",
                formatted_traceback,
            )
        )
        report = redact_log_text(report)
        report = report.rstrip() + "\n"
        encoded = report.encode("utf-8")
        if len(encoded) <= MAX_CRASH_REPORT_BYTES:
            return report
        marker = CRASH_TRUNCATION_MARKER.encode("utf-8")
        prefix = encoded[: MAX_CRASH_REPORT_BYTES - len(marker)].decode(
            "utf-8",
            errors="ignore",
        )
        return prefix + CRASH_TRUNCATION_MARKER

    def _write_report(self, report):
        crash_dir = get_crash_dir(self.platform)
        os.makedirs(crash_dir, mode=0o700, exist_ok=True)
        try:
            os.chmod(crash_dir, 0o700)
        except OSError:
            pass

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        filename = (
            f"{CRASH_FILE_PREFIX}{timestamp}-{self.process_role}-{os.getpid()}-"
            f"{secrets.token_hex(3)}{CRASH_FILE_SUFFIX}"
        )
        report_path = os.path.join(crash_dir, filename)
        temp_path = None
        try:
            fd, temp_path = tempfile.mkstemp(
                dir=crash_dir,
                prefix=".crash-",
                suffix=".tmp",
            )
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(report)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temp_path, 0o600)
            except OSError:
                pass
            os.replace(temp_path, report_path)
            temp_path = None
        finally:
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

        self._prune_reports(crash_dir)
        return report_path

    def _prune_reports(self, crash_dir):
        try:
            reports = sorted(
                (
                    name
                    for name in os.listdir(crash_dir)
                    if name.startswith(CRASH_FILE_PREFIX)
                    and name.endswith(CRASH_FILE_SUFFIX)
                ),
                reverse=True,
            )
        except OSError:
            return
        for name in reports[MAX_CRASH_REPORTS:]:
            try:
                os.remove(os.path.join(crash_dir, name))
            except OSError:
                pass


def _is_normal_exit(exc_type):
    try:
        return issubclass(exc_type, (KeyboardInterrupt, SystemExit))
    except TypeError:
        return False


def install_crash_reporting(platform=None, process_role="host"):
    """Install process-wide main-thread and background-thread crash hooks."""
    return CrashReporter(platform, process_role).install()


__all__ = ["CrashReporter", "install_crash_reporting"]
