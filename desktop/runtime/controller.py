"""Application controller for desktop runtime coordination."""

from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
import tempfile
from dataclasses import dataclass

import requests

from desktop.core.api import APIResponseError, format_api_error
from desktop.core.constants import APP_VERSION, RELEASES_LATEST_API_URL, RELEASES_PAGE_URL
from desktop.core.ra_client import RAClient
from desktop.core.settings import normalize_config
from desktop.core.update import (
    is_newer_version,
    load_update_override,
    normalize_version_label,
)
from desktop.platform import get_platform_services
from desktop.runtime.storage import (
    UPDATE_OVERRIDE_FILE,
    load_config,
    load_console_icons,
    save_config,
)
from desktop.runtime.worker import RPCWorker

logger = logging.getLogger(__name__)


@dataclass
class ConnectResult:
    """Describe the outcome of a controller-managed connect attempt."""

    success: bool
    config: dict | None = None
    warning_title: str | None = None
    warning_message: str | None = None
    error_title: str | None = None
    error_message: str | None = None


@dataclass
class UpdateStatus:
    """Describe the most recent update-check result for the desktop app."""

    checked: bool = False
    available: bool = False
    current_version: str = APP_VERSION
    latest_version: str | None = None
    release_url: str = RELEASES_PAGE_URL
    asset_name: str | None = None
    asset_url: str | None = None


@dataclass
class UpdateInstallResult:
    """Describe the result of an attempted self-update installation."""

    success: bool
    error_title: str | None = None
    error_message: str | None = None


class AppController:
    """Coordinate config, platform hooks, and the background worker."""

    def __init__(self, platform=None, ra_client=None):
        self.platform = platform or get_platform_services()
        self.ra_client = ra_client or RAClient()
        logger.info(
            "Controller initializing platform=%s",
            self.platform.__class__.__name__,
        )
        self._action_lock = threading.Lock()
        self._update_lock = threading.Lock()
        self._update_thread = None
        self.config = load_config(self.platform)
        self._update_status = UpdateStatus()
        self.worker = RPCWorker(
            initial_config=self.config,
            console_icons=load_console_icons(),
        )
        self.start_update_check()

    def set_status_callback(self, callback):
        """Attach a runtime status callback used by the tray host."""
        self.worker.set_status_callback(callback)

    def load_config(self):
        """Reload the persisted config and keep the worker in sync."""
        self.config = load_config(self.platform)
        self.worker.config = dict(self.config)
        return dict(self.config)

    def get_update_status(self):
        """Return the latest cached update-check result."""
        with self._update_lock:
            status = self._update_status
            return UpdateStatus(
                checked=status.checked,
                available=status.available,
                current_version=status.current_version,
                latest_version=status.latest_version,
                release_url=status.release_url,
                asset_name=status.asset_name,
                asset_url=status.asset_url,
            )

    def start_update_check(self):
        """Kick off a one-shot background check for a newer app version."""
        with self._update_lock:
            if self._update_thread and self._update_thread.is_alive():
                logger.info("Update check already running")
                return
            logger.info("Starting update check")
            self._update_thread = threading.Thread(target=self._check_for_updates, daemon=True)
            self._update_thread.start()

    def start_saved_session(self):
        """Start monitoring immediately if stored credentials are present."""
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
        """Persist settings, validate credentials, and start monitoring."""
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
                self.ra_client.get_user_summary(
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
        """Stop the active monitoring worker."""
        with self._action_lock:
            logger.info("Disconnect requested timeout=%s", timeout)
            stopped = self.worker.stop(timeout=timeout)
            logger.info("Disconnect completed stopped=%s", stopped)
            return stopped

    def shutdown(self, timeout=35):
        """Shut the controller down before the app exits."""
        logger.info("Controller shutdown requested timeout=%s", timeout)
        return self.disconnect(timeout=timeout)

    def install_update(self):
        """Download and stage the latest release asset for automatic restart."""
        status = self.get_update_status()
        if not status.available:
            logger.info("Update install skipped no_update_available=True")
            return UpdateInstallResult(
                success=False,
                error_title="No Update Available",
                error_message="No newer CheevoPresence version is currently available.",
            )
        if not self.platform.supports_self_update():
            logger.info(
                "Update install unsupported platform=%s",
                self.platform.__class__.__name__,
            )
            return UpdateInstallResult(
                success=False,
                error_title="Update Unsupported",
                error_message="Automatic updates are only available in the packaged app build installed in a writable location.",
            )

        asset_name = status.asset_name
        asset_url = status.asset_url
        if not asset_name or not asset_url:
            asset_name, asset_url = self._fetch_latest_update_asset()
        if not asset_name or not asset_url:
            logger.warning("Update install unavailable no_asset=True")
            return UpdateInstallResult(
                success=False,
                error_title="Update Unavailable",
                error_message="Could not find a downloadable update for this operating system in the latest release.",
            )

        download_dir = tempfile.mkdtemp(prefix="CheevoPresence-download-")
        download_path = os.path.join(download_dir, asset_name)
        try:
            logger.info("Update install staging asset=%s", asset_name)
            self._download_release_asset(asset_url, download_path)
            install_error = self.platform.stage_update_install(
                download_path,
                relaunch_args=sys.argv[1:],
                source_pid=os.getpid(),
            )
        except requests.RequestException as exc:
            logger.warning("Update download failed error=%s", format_api_error(exc))
            self._cleanup_update_download(download_dir)
            return UpdateInstallResult(
                success=False,
                error_title="Download Failed",
                error_message=format_api_error(exc),
            )
        except OSError:
            logger.exception("Update download write failed")
            self._cleanup_update_download(download_dir)
            return UpdateInstallResult(
                success=False,
                error_title="Update Failed",
                error_message="Could not write the downloaded update to disk.",
            )
        except Exception:
            logger.exception("Update install preparation failed unexpectedly")
            self._cleanup_update_download(download_dir)
            return UpdateInstallResult(
                success=False,
                error_title="Update Failed",
                error_message="An unexpected error occurred while preparing the update.",
            )

        if install_error:
            logger.warning("Update install staging failed error=%s", install_error)
            self._cleanup_update_download(download_dir)
            return UpdateInstallResult(
                success=False,
                error_title="Update Failed",
                error_message=install_error,
            )
        logger.info("Update install staged successfully asset=%s", asset_name)
        return UpdateInstallResult(success=True)

    def _check_for_updates(self):
        """Fetch the latest GitHub release and cache whether an update exists."""
        override = load_update_override(UPDATE_OVERRIDE_FILE, APP_VERSION)
        if override:
            with self._update_lock:
                self._update_status = UpdateStatus(
                    checked=True,
                    available=True,
                    current_version=APP_VERSION,
                    latest_version=override["latest_version"],
                    release_url=override["release_url"],
                    asset_name=override["asset_name"],
                    asset_url=override["asset_url"],
                )
            return

        latest_version = None
        release_url = RELEASES_PAGE_URL
        available = False
        asset_name = None
        asset_url = None

        try:
            response = requests.get(
                RELEASES_LATEST_API_URL,
                timeout=10,
                headers={"Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
            payload = response.json()
            latest_version = normalize_version_label(payload.get("tag_name"))
            release_url = payload.get("html_url") or RELEASES_PAGE_URL
            if latest_version:
                available = is_newer_version(latest_version, APP_VERSION)
            if available:
                asset = self.platform.select_update_asset(payload.get("assets") or [])
                if asset:
                    asset_name = str(asset.get("name") or "").strip() or None
                    asset_url = str(asset.get("browser_download_url") or "").strip() or None
        except Exception:
            pass

        with self._update_lock:
            self._update_status = UpdateStatus(
                checked=True,
                available=available,
                current_version=APP_VERSION,
                latest_version=latest_version,
                release_url=release_url,
                asset_name=asset_name,
                asset_url=asset_url,
            )

    def _fetch_latest_update_asset(self):
        """Fetch the latest release metadata and return the preferred asset pair."""
        response = requests.get(
            RELEASES_LATEST_API_URL,
            timeout=15,
            headers={"Accept": "application/vnd.github+json"},
        )
        response.raise_for_status()
        payload = response.json()
        asset = self.platform.select_update_asset(payload.get("assets") or [])
        if not asset:
            return None, None
        asset_name = str(asset.get("name") or "").strip() or None
        asset_url = str(asset.get("browser_download_url") or "").strip() or None
        return asset_name, asset_url

    def _download_release_asset(self, asset_url, download_path):
        """Download a release asset to a local file using streamed writes."""
        if asset_url and os.path.exists(asset_url):
            shutil.copy2(asset_url, download_path)
            return
        response = requests.get(asset_url, timeout=30, stream=True)
        response.raise_for_status()
        with open(download_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    handle.write(chunk)

    def _cleanup_update_download(self, download_dir):
        """Remove a temporary update download directory when staging fails."""
        shutil.rmtree(download_dir, ignore_errors=True)
