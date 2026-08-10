"""Application controller for desktop runtime coordination."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import requests

from desktop.core.api import format_api_error
from desktop.core.ra_client import APIResponseError, RAClient
from desktop.core.roles import debug_forced_role_permission, resolve_dev_mode
from desktop.core.settings import normalize_config
from desktop.platform import get_platform_services
from desktop.runtime.storage import (
    load_config,
    load_console_icons,
    save_config,
)
from desktop.runtime.update_service import (
    UpdateService,
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


class AppController:

    def __init__(self, platform=None, ra_client=None):
        self.platform = platform or get_platform_services()
        self.ra_client = ra_client or RAClient()
        logger.info(
            "Controller initializing platform=%s",
            self.platform.__class__.__name__,
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
                    logger.warning("Autostart update failed error=%s", autostart_error)
                    self.config["start_on_boot"] = self.platform.is_autostart_enabled()
                    warning_title = "Startup Setting Failed"
                    warning_message = autostart_error

            try:
                save_config(self.config, self.platform)
                logger.info("Configuration saved")
            except OSError:
                logger.exception("Configuration save failed")
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
                logger.info(
                    (
                        "Saved session not started missing_credentials "
                        "username_present=%s apikey_present=%s"
                    ),
                    bool(config["username"]),
                    bool(config["apikey"]),
                )
                return False
            logger.info("Starting saved session")
            return self.worker.start(config)

    def connect(self, config):
        with self._action_lock:
            self.config = normalize_config(config)
            logger.info(
                "Connect requested username_present=%s apikey_present=%s start_on_boot=%s",
                bool(self.config["username"]),
                bool(self.config["apikey"]),
                bool(self.config["start_on_boot"]),
            )
            try:
                save_config(self.config, self.platform)
                logger.info("Configuration saved")
            except OSError:
                logger.exception("Configuration save failed")
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
                logger.warning("Autostart update failed error=%s", autostart_error)
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
                logger.info("RetroAchievements credential validation succeeded")
            except requests.RequestException as exc:
                logger.warning(
                    "RetroAchievements credential validation failed error=%s",
                    format_api_error(exc),
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
                logger.warning(
                    "RetroAchievements credential validation returned unexpected payload"
                )
                return ConnectResult(
                    success=False,
                    config=dict(self.config),
                    warning_title=warning_title,
                    warning_message=warning_message,
                    error_title="Connection Failed",
                    error_message="API error: unexpected response",
                )
            except Exception:
                logger.exception("RetroAchievements credential validation failed unexpectedly")
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
                logger.warning(
                    "RetroAchievements role lookup failed error=%s",
                    format_api_error(exc),
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
                    logger.info(
                        "Dev Mode derived from RetroAchievements permissions enabled=%s",
                        derived_dev_mode,
                    )
                except OSError:
                    logger.exception("Configuration save failed after role detection")
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
                logger.warning("Worker did not start after successful credential validation")
                return ConnectResult(
                    success=False,
                    config=dict(self.config),
                    warning_title=warning_title,
                    warning_message=warning_message,
                    error_title="Connection Failed",
                    error_message="Could not start the monitoring worker.",
                )

            logger.info("Connect completed worker_started=True")
            return ConnectResult(
                success=True,
                config=dict(self.config),
                warning_title=warning_title,
                warning_message=warning_message,
            )

    def disconnect(self, timeout=35):
        with self._action_lock:
            logger.info("Disconnect requested timeout=%s", timeout)
            stopped = self.worker.stop(timeout=timeout)
            logger.info("Disconnect completed stopped=%s", stopped)
            return stopped

    def shutdown(self, timeout=35):
        logger.info("Controller shutdown requested timeout=%s", timeout)
        return self.disconnect(timeout=timeout)

    def install_update(self):
        return install_update_for_current_process(self.update_service)
