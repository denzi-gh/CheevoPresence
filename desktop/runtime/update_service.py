"""Runtime update checking, download, and staging service."""

from __future__ import annotations

import logging
import hashlib
import os
import re
import shutil
import sys
import tempfile
import threading
from dataclasses import dataclass

import requests

from desktop.core.api import format_api_error
from desktop.core.constants import APP_VERSION, RELEASES_LATEST_API_URL, RELEASES_PAGE_URL
from desktop.core.update import (
    is_newer_version,
    load_update_override,
    normalize_version_label,
)
from desktop.runtime.storage import UPDATE_OVERRIDE_FILE

logger = logging.getLogger(__name__)


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
    asset_sha256: str | None = None
    checksum_url: str | None = None


@dataclass
class UpdateInstallResult:
    """Describe the result of an attempted self-update installation."""

    success: bool
    error_title: str | None = None
    error_message: str | None = None


def copy_update_status(status):
    """Return a detached copy of an update status dataclass."""
    return UpdateStatus(
        checked=status.checked,
        available=status.available,
        current_version=status.current_version,
        latest_version=status.latest_version,
        release_url=status.release_url,
        asset_name=status.asset_name,
        asset_url=status.asset_url,
        asset_sha256=status.asset_sha256,
        checksum_url=status.checksum_url,
    )


class UpdateService:
    """Coordinate GitHub release checks and platform update staging."""

    def __init__(
        self,
        platform,
        session=None,
        current_version=APP_VERSION,
        releases_page_url=RELEASES_PAGE_URL,
        latest_api_url=RELEASES_LATEST_API_URL,
        override_file=UPDATE_OVERRIDE_FILE,
    ):
        self.platform = platform
        self.session = session or requests.Session()
        self.current_version = current_version
        self.releases_page_url = releases_page_url
        self.latest_api_url = latest_api_url
        self.override_file = override_file
        self._status = UpdateStatus(current_version=current_version)
        self._lock = threading.Lock()
        self._thread = None

    def get_status(self):
        """Return the latest cached update-check result."""
        with self._lock:
            return copy_update_status(self._status)

    def start_check(self):
        """Kick off a one-shot background check for a newer app version."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                logger.info("Update check already running")
                return
            logger.info("Starting update check")
            self._thread = threading.Thread(target=self.check_for_updates, daemon=True)
            self._thread.start()

    def check_for_updates(self):
        """Fetch the latest release metadata and cache whether an update exists."""
        status = self._build_update_status()
        with self._lock:
            self._status = status
        return copy_update_status(status)

    def install_update(self, relaunch_args=None, source_pid=None):
        """Download and stage the latest release asset for automatic restart."""
        status = self.get_status()
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
        asset_sha256 = status.asset_sha256
        checksum_url = status.checksum_url
        if not asset_name or not asset_url:
            asset_name, asset_url, asset_sha256, checksum_url = self._fetch_latest_update_asset()
        if not asset_name or not asset_url:
            logger.warning("Update install unavailable no_asset=True")
            return UpdateInstallResult(
                success=False,
                error_title="Update Unavailable",
                error_message="Could not find a downloadable update for this operating system in the latest release.",
            )
        try:
            expected_sha256 = asset_sha256 or self._fetch_asset_checksum(
                checksum_url,
                asset_name,
            )
        except requests.RequestException as exc:
            logger.warning("Update checksum fetch failed error=%s", format_api_error(exc))
            return UpdateInstallResult(
                success=False,
                error_title="Download Failed",
                error_message=format_api_error(exc),
            )
        except OSError:
            logger.exception("Update checksum read failed")
            return UpdateInstallResult(
                success=False,
                error_title="Update Failed",
                error_message="Could not read the update checksum.",
            )
        if not expected_sha256:
            logger.warning("Update install unavailable verification_missing=True")
            return UpdateInstallResult(
                success=False,
                error_title="Update Verification Unavailable",
                error_message="The latest update cannot be installed automatically because it does not include a SHA-256 checksum.",
            )

        download_dir = tempfile.mkdtemp(prefix="CheevoPresence-download-")
        download_path = os.path.join(download_dir, asset_name)
        try:
            logger.info("Update install staging asset=%s", asset_name)
            self._download_release_asset(asset_url, download_path)
            if not self._verify_download_sha256(download_path, expected_sha256):
                self._cleanup_update_download(download_dir)
                return UpdateInstallResult(
                    success=False,
                    error_title="Update Verification Failed",
                    error_message="The downloaded update did not match its SHA-256 checksum.",
                )
            install_error = self.platform.stage_update_install(
                download_path,
                relaunch_args=list(relaunch_args or []),
                source_pid=source_pid if source_pid is not None else os.getpid(),
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

    def _build_update_status(self):
        """Build an update status from override or latest GitHub release metadata."""
        override = load_update_override(self.override_file, self.current_version)
        if override:
            return UpdateStatus(
                checked=True,
                available=True,
                current_version=self.current_version,
                latest_version=override["latest_version"],
                release_url=override["release_url"],
                asset_name=override["asset_name"],
                asset_url=override["asset_url"],
                asset_sha256=override["asset_sha256"],
                checksum_url=override["checksum_url"],
            )

        latest_version = None
        release_url = self.releases_page_url
        available = False
        asset_name = None
        asset_url = None
        asset_sha256 = None
        checksum_url = None

        try:
            payload = self._fetch_latest_release()
            latest_version = normalize_version_label(payload.get("tag_name"))
            release_url = payload.get("html_url") or self.releases_page_url
            if latest_version:
                available = is_newer_version(latest_version, self.current_version)
            if available:
                asset = self.platform.select_update_asset(payload.get("assets") or [])
                if asset:
                    asset_name = str(asset.get("name") or "").strip() or None
                    asset_url = str(asset.get("browser_download_url") or "").strip() or None
                    asset_sha256 = self._asset_sha256_from_metadata(asset)
                    checksum_url = self._find_checksum_url(payload.get("assets") or [], asset_name)
        except Exception:
            pass

        return UpdateStatus(
            checked=True,
            available=available,
            current_version=self.current_version,
            latest_version=latest_version,
            release_url=release_url,
            asset_name=asset_name,
            asset_url=asset_url,
            asset_sha256=asset_sha256,
            checksum_url=checksum_url,
        )

    def _fetch_latest_release(self):
        """Fetch the latest GitHub release metadata."""
        response = self.session.get(
            self.latest_api_url,
            timeout=10,
            headers={"Accept": "application/vnd.github+json"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Unexpected release payload.")
        return payload

    def _fetch_latest_update_asset(self):
        """Fetch the latest release metadata and return the preferred asset pair."""
        payload = self._fetch_latest_release()
        asset = self.platform.select_update_asset(payload.get("assets") or [])
        if not asset:
            return None, None, None, None
        asset_name = str(asset.get("name") or "").strip() or None
        asset_url = str(asset.get("browser_download_url") or "").strip() or None
        asset_sha256 = self._asset_sha256_from_metadata(asset)
        checksum_url = self._find_checksum_url(payload.get("assets") or [], asset_name)
        return asset_name, asset_url, asset_sha256, checksum_url

    def _download_release_asset(self, asset_url, download_path):
        """Download a release asset to a local file using streamed writes."""
        if asset_url and os.path.exists(asset_url):
            shutil.copy2(asset_url, download_path)
            return
        response = self.session.get(asset_url, timeout=30, stream=True)
        response.raise_for_status()
        with open(download_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    handle.write(chunk)

    def _asset_sha256_from_metadata(self, asset):
        """Extract a sha256 digest from GitHub asset metadata when present."""
        digest = asset.get("digest")
        if isinstance(digest, str):
            match = re.fullmatch(r"sha256:([0-9a-fA-F]{64})", digest.strip())
            if match:
                return match.group(1).lower()
        value = asset.get("sha256") or asset.get("asset_sha256")
        if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value.strip()):
            return value.strip().lower()
        return None

    def _find_checksum_url(self, assets, asset_name):
        """Find a checksum asset URL that matches the selected release asset."""
        if not asset_name:
            return None
        expected_names = {
            f"{asset_name}.sha256".lower(),
            f"{asset_name}.sha256sum".lower(),
            "sha256sums.txt",
        }
        for asset in assets or []:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "").strip().lower()
            if name in expected_names:
                return str(asset.get("browser_download_url") or "").strip() or None
        return None

    def _fetch_asset_checksum(self, checksum_url, asset_name):
        """Fetch and parse a sha256 checksum file for the selected asset."""
        if not checksum_url:
            return None
        if os.path.exists(checksum_url):
            with open(checksum_url, "r", encoding="utf-8") as handle:
                text = handle.read()
        else:
            response = self.session.get(checksum_url, timeout=15)
            response.raise_for_status()
            text = response.text
        return self._parse_sha256_text(text, asset_name)

    def _parse_sha256_text(self, text, asset_name):
        """Parse a sha256 checksum from common checksum file formats."""
        if not isinstance(text, str):
            return None
        lines = text.splitlines() or [text]
        for line in lines:
            if asset_name and asset_name not in line and len(lines) > 1:
                continue
            match = re.search(r"\b([0-9a-fA-F]{64})\b", line)
            if match:
                return match.group(1).lower()
        return None

    def _verify_download_sha256(self, path, expected_sha256):
        """Return whether a downloaded file matches the expected sha256."""
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 256), b""):
                digest.update(chunk)
        return digest.hexdigest().lower() == expected_sha256.lower()

    def _cleanup_update_download(self, download_dir):
        """Remove a temporary update download directory when staging fails."""
        shutil.rmtree(download_dir, ignore_errors=True)


def install_update_for_current_process(service):
    """Install an update using the current process launch context."""
    return service.install_update(
        relaunch_args=sys.argv[1:],
        source_pid=os.getpid(),
    )
