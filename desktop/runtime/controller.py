"""Application controller for desktop runtime coordination."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from desktop.core.api import format_api_error
from desktop.core.log_events import (
    AREA_AUTOSTART,
    AREA_CONFIG,
    AREA_RA,
    AREA_SETTINGS,
    AREA_SHUTDOWN,
    AREA_STARTUP,
    AREA_WORKER,
    log_event,
)
from desktop.core.ra_client import APIResponseError, RAClient
from desktop.core.roles import debug_forced_role_permission, resolve_dev_mode
from desktop.core.settings import normalize_config
from desktop.platform import get_platform_services
from desktop.runtime.logging_setup import (
    get_log_level,
    normalize_log_level,
    set_log_level,
    tail_log_lines,
)
from desktop.runtime.storage import (
    get_log_dir,
    load_config,
    load_console_icons,
    save_config,
)
from desktop.runtime.update_service import (
    UpdateInstallResult,
    UpdateService,
    UpdateStatus,
    install_update_for_current_process,
)
from desktop.runtime.worker import RPCWorker

logger = logging.getLogger(__name__)


@dataclass
class ConnectResult:

    success: bool
    config: dict | None = None
    warning_title: str | None = None
    warning_message: str | None = None
    error_title: str | None = None
    error_message: str | None = None


class SettingsController(Protocol):
    """Structural interface the settings UI needs from a controller."""

    worker: Any
    platform: Any
    config: dict

    def load_config(self) -> dict: ...
    def get_update_status(self) -> UpdateStatus: ...
    def connect(self, config: dict) -> ConnectResult: ...
    def disconnect(self) -> bool: ...
    def install_update(self) -> UpdateInstallResult: ...
    def tail_logs(self, lines: int = 200) -> dict: ...
    def set_log_level(self, level: str) -> dict: ...


class AppController:

    def __init__(self, platform=None, ra_client=None):
        self.platform = platform or get_platform_services()
        self.ra_client = ra_client or RAClient()
        log_event(
            logger,
            AREA_STARTUP,
            "controller_initializing",
            platform=self.platform.__class__.__name__,
        )
        self._action_lock = threading.Lock()
        self.config = load_config(self.platform)
        self.update_service = UpdateService(self.platform)
        self.worker = RPCWorker(
            initial_config=self.config,
            console_icons=load_console_icons(),
        )
        self.start_update_check()

    def set_status_callback(self, callback):
        self.worker.set_status_callback(callback)

    def load_config(self):
        self.config = load_config(self.platform)
        self.worker.replace_config(self.config)
        return dict(self.config)

    def tail_logs(self, lines=200):
        return {
            "lines": tail_log_lines(self.platform, lines),
            "path": get_log_dir(self.platform),
            "level": logging.getLevelName(get_log_level()),
        }

    def set_log_level(self, level):
        target = normalize_log_level(level)
        previous = get_log_level()
        fields = {
            "previous_level": logging.getLevelName(previous),
            "new_level": logging.getLevelName(target),
        }
        if target >= previous:
            log_event(logger, AREA_SETTINGS, "log_level_changed", **fields)
        applied = set_log_level(target)
        if target < previous:
            log_event(logger, AREA_SETTINGS, "log_level_changed", **fields)
        return {"success": True, "level": logging.getLevelName(applied)}

    def save_config(self, config):
        with self._action_lock:
            previous_start_on_boot = bool(self.config.get("start_on_boot", False))
            self.config = normalize_config(config)
            warning_title = None
            warning_message = None

            autostart_error = None
            if bool(self.config["start_on_boot"]) != previous_start_on_boot:
                autostart_error = self.platform.set_autostart(self.config["start_on_boot"])
                if autostart_error:
                    log_event(
                        logger,
                        AREA_AUTOSTART,
                        "update_failed",
                        level=logging.WARNING,
                        detail=autostart_error,
                    )
                    self.config["start_on_boot"] = self.platform.is_autostart_enabled()
                    warning_title = "Startup Setting Failed"
                    warning_message = autostart_error

            try:
                save_config(self.config, self.platform)
            except OSError:
                log_event(
                    logger,
                    AREA_CONFIG,
                    "controller_save_failed",
                    level=logging.ERROR,
                    exc_info=True,
                )
                return {
                    "success": False,
                    "config": dict(self.config),
                    "error_title": "Save Failed",
                    "error_message": "Could not write the configuration file.",
                    "warning_title": warning_title,
                    "warning_message": warning_message,
                }

            self.worker.replace_config(self.config)
            return {
                "success": autostart_error is None,
                "config": dict(self.config),
                "warning_title": warning_title,
                "warning_message": warning_message,
            }

    def get_update_status(self):
        return self.update_service.get_status()

    def start_update_check(self):
        self.update_service.start_check()

    def start_saved_session(self):
        with self._action_lock:
            config = self.load_config()
            if not config["username"] or not config["apikey"]:
                log_event(
                    logger,
                    AREA_WORKER,
                    "saved_session_skipped",
                    reason="missing_credentials",
                    username_present=bool(config["username"]),
                    apikey_present=bool(config["apikey"]),
                )
                return False
            log_event(logger, AREA_WORKER, "saved_session_start")
            return self.worker.start(config)

    def connect(self, config):
        with self._action_lock:
            self.config = normalize_config(config)
            log_event(
                logger,
                AREA_SETTINGS,
                "connect_requested",
                username_present=bool(self.config["username"]),
                apikey_present=bool(self.config["apikey"]),
                start_on_boot=bool(self.config["start_on_boot"]),
            )
            try:
                save_config(self.config, self.platform)
            except OSError:
                log_event(
                    logger,
                    AREA_CONFIG,
                    "controller_save_failed",
                    level=logging.ERROR,
                    exc_info=True,
                )
                return ConnectResult(
                    success=False,
                    config=dict(self.config),
                    error_title="Save Failed",
                    error_message="Could not write the configuration file.",
                )

            warning_title = None
            warning_message = None
            autostart_error = self.platform.set_autostart(self.config["start_on_boot"])
            if autostart_error:
                log_event(
                    logger,
                    AREA_AUTOSTART,
                    "update_failed",
                    level=logging.WARNING,
                    detail=autostart_error,
                )
                self.config["start_on_boot"] = self.platform.is_autostart_enabled()
                try:
                    save_config(self.config, self.platform)
                except OSError:
                    pass
                warning_title = "Startup Setting Failed"
                warning_message = autostart_error

            try:
                user_summary = self.ra_client.get_user_summary(
                    self.config["username"],
                    self.config["apikey"],
                )
                log_event(logger, AREA_RA, "credential_validation_succeeded")
            except requests.RequestException as exc:
                log_event(
                    logger,
                    AREA_RA,
                    "credential_validation_failed",
                    level=logging.WARNING,
                    error_type=exc.__class__.__name__,
                    detail=format_api_error(exc),
                )
                return ConnectResult(
                    success=False,
                    config=dict(self.config),
                    warning_title=warning_title,
                    warning_message=warning_message,
                    error_title="Connection Failed",
                    error_message=format_api_error(exc),
                )
            except APIResponseError:
                log_event(
                    logger,
                    AREA_RA,
                    "credential_validation_failed",
                    level=logging.WARNING,
                    reason="unexpected_payload",
                )
                return ConnectResult(
                    success=False,
                    config=dict(self.config),
                    warning_title=warning_title,
                    warning_message=warning_message,
                    error_title="Connection Failed",
                    error_message="API error: unexpected response",
                )
            except Exception:  # noqa: BLE001 credential boundary; failure is logged
                log_event(
                    logger,
                    AREA_RA,
                    "credential_validation_failed",
                    level=logging.ERROR,
                    exc_info=True,
                    reason="unexpected_error",
                )
                return ConnectResult(
                    success=False,
                    config=dict(self.config),
                    warning_title=warning_title,
                    warning_message=warning_message,
                    error_title="Connection Failed",
                    error_message="Unexpected error",
                )

            try:
                profile = self.ra_client.get_user_profile_v2(
                    self.config["username"],
                    self.config["apikey"],
                )
                displayable_roles = profile.get("displayableRoles")
            except (requests.RequestException, APIResponseError) as exc:
                displayable_roles = None
                log_event(
                    logger,
                    AREA_RA,
                    "role_lookup_failed",
                    level=logging.WARNING,
                    error_type=exc.__class__.__name__,
                    detail=format_api_error(exc),
                )

            derived_dev_mode = resolve_dev_mode(
                user_summary.get("Permissions"),
                displayable_roles,
                forced_permission=debug_forced_role_permission(),
            )
            if self.config.get("dev_mode", False) != derived_dev_mode:
                self.config["dev_mode"] = derived_dev_mode
                try:
                    save_config(self.config, self.platform)
                    log_event(
                        logger,
                        AREA_CONFIG,
                        "developer_mode_derived",
                        enabled=derived_dev_mode,
                    )
                except OSError:
                    log_event(
                        logger,
                        AREA_CONFIG,
                        "role_save_failed",
                        level=logging.ERROR,
                        exc_info=True,
                    )
                    return ConnectResult(
                        success=False,
                        config=dict(self.config),
                        warning_title=warning_title,
                        warning_message=warning_message,
                        error_title="Save Failed",
                        error_message="Could not write the configuration file.",
                    )

            started = self.worker.start(self.config)
            if not started:
                log_event(
                    logger,
                    AREA_WORKER,
                    "start_failed_after_validation",
                    level=logging.WARNING,
                )
                return ConnectResult(
                    success=False,
                    config=dict(self.config),
                    warning_title=warning_title,
                    warning_message=warning_message,
                    error_title="Connection Failed",
                    error_message="Could not start the monitoring worker.",
                )

            log_event(logger, AREA_SETTINGS, "connect_completed", worker_started=True)
            return ConnectResult(
                success=True,
                config=dict(self.config),
                warning_title=warning_title,
                warning_message=warning_message,
            )

    def disconnect(self, timeout=35):
        log_event(logger, AREA_WORKER, "disconnect_requested", timeout_sec=timeout)
        stopped = self.worker.stop(timeout=timeout)
        log_event(logger, AREA_WORKER, "disconnect_completed", stopped=stopped)
        return stopped

    def shutdown(self, timeout=35):
        log_event(logger, AREA_SHUTDOWN, "controller_requested", timeout_sec=timeout)
        return self.disconnect(timeout=timeout)

    def install_update(self):
        return install_update_for_current_process(self.update_service)
