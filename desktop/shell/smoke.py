from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time

from desktop.core.constants import (
    LINUX_SETTINGS_CLIENT_FLAG,
    MAC_SETTINGS_CLIENT_FLAG,
    TRAY_FLAG,
    WINDOWS_SETTINGS_CLIENT_FLAG,
)
from desktop.core.log_events import AREA_STARTUP, log_event
from desktop.runtime.controller import AppController
from desktop.shell.ipc import RemoteAppController, SettingsHostService
from desktop.shell.web_settings import SETTINGS_UI_ENV

logger = logging.getLogger(__name__)

_CLIENT_FLAGS = {
    "windows": WINDOWS_SETTINGS_CLIENT_FLAG,
    "macos": MAC_SETTINGS_CLIENT_FLAG,
    "linux": LINUX_SETTINGS_CLIENT_FLAG,
}

MIN_ALIVE_SECONDS = 10.0
MIN_GET_STATE_REQUESTS = 3
MIN_POLL_SPAN_SECONDS = 3.0
SECOND_INSTANCE_TIMEOUT_SECONDS = 15.0
DEFAULT_DEADLINE_SECONDS = 60.0


def _app_command(flag):
    # Same command shape as the tray/menu-bar hosts use.
    if getattr(sys, "frozen", False):
        return [sys.executable, flag]
    return [sys.executable, os.path.abspath(sys.argv[0]), flag]


def _verify_quit_roundtrip(service, quit_event):
    # Drives the real quit path
    try:
        RemoteAppController(service.address, service.auth_token).quit_app()
    except Exception:  # noqa: BLE001 verdict boundary; the failure reason is in the log
        log_event(
            logger,
            AREA_STARTUP,
            "smoke_failed",
            level=logging.ERROR,
            exc_info=True,
            reason="quit_request_failed",
        )
        return False
    if not quit_event.wait(timeout=5):
        log_event(
            logger,
            AREA_STARTUP,
            "smoke_failed",
            level=logging.ERROR,
            reason="quit_callback_missing",
        )
        return False
    return True


def _verify_second_instance_blocked():
    # While the smoke holds the single-instance lock, a second app process
    # must back off and exit cleanly
    probe = subprocess.Popen(_app_command(TRAY_FLAG))
    try:
        exit_code = probe.wait(timeout=SECOND_INSTANCE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        probe.terminate()
        try:
            probe.wait(timeout=5)
        except subprocess.TimeoutExpired:
            probe.kill()
        log_event(
            logger,
            AREA_STARTUP,
            "smoke_failed",
            level=logging.ERROR,
            reason="second_instance_not_blocked",
        )
        return False
    if exit_code != 0:
        log_event(
            logger,
            AREA_STARTUP,
            "smoke_failed",
            level=logging.ERROR,
            reason="second_instance_crashed",
            exit_code=exit_code,
        )
        return False
    return True


def run_smoke(platform_name, platform, deadline_seconds=None):
    deadline = deadline_seconds or DEFAULT_DEADLINE_SECONDS

    def _watchdog_fired():
        log_event(
            logger,
            AREA_STARTUP,
            "smoke_timeout",
            level=logging.ERROR,
            deadline_sec=deadline,
        )
        os._exit(2)

    watchdog = threading.Timer(deadline, _watchdog_fired)
    watchdog.daemon = True
    watchdog.start()

    poll_lock = threading.Lock()
    poll_times = []

    def _on_request(method):
        if method == "get_state":
            with poll_lock:
                poll_times.append(time.monotonic())

    # Hold the lock ourselves so the second-instance probe has something to
    # collide with
    if not platform.acquire_single_instance():
        log_event(
            logger,
            AREA_STARTUP,
            "smoke_failed",
            level=logging.ERROR,
            reason="single_instance_unavailable",
        )
        watchdog.cancel()
        return 1

    # No worker start: the smoke test needs no credentials and no Discord.
    controller = AppController(platform=platform)
    quit_event = threading.Event()
    service = SettingsHostService(
        controller,
        on_quit=quit_event.set,
        on_request=_on_request,
    )
    service.start()
    child = None
    try:
        env = os.environ.copy()
        env.update(service.get_launch_env())
        env[SETTINGS_UI_ENV] = "native"
        child = subprocess.Popen(_app_command(_CLIENT_FLAGS[platform_name]), env=env)
        log_event(logger, AREA_STARTUP, "smoke_child_started", pid=child.pid)

        started = time.monotonic()
        while True:
            if child.poll() is not None:
                log_event(
                    logger,
                    AREA_STARTUP,
                    "smoke_failed",
                    level=logging.ERROR,
                    reason="child_exited",
                    exit_code=child.returncode,
                )
                return 1
            with poll_lock:
                polls = list(poll_times)
            alive_sec = time.monotonic() - started
            if (
                alive_sec >= MIN_ALIVE_SECONDS
                and len(polls) >= MIN_GET_STATE_REQUESTS
                and polls[-1] - polls[0] >= MIN_POLL_SPAN_SECONDS
            ):
                if not _verify_quit_roundtrip(service, quit_event):
                    return 1
                if not _verify_second_instance_blocked():
                    return 1
                log_event(
                    logger,
                    AREA_STARTUP,
                    "smoke_passed",
                    polls=len(polls),
                    alive_sec=round(alive_sec, 1),
                )
                return 0
            time.sleep(0.25)
    finally:
        watchdog.cancel()
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
        service.stop()
        try:
            controller.shutdown(timeout=5)
        except Exception:
            logger.debug("smoke teardown failed", exc_info=True)
