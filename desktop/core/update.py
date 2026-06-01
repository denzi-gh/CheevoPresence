"""Shared update-version helpers for the desktop app."""

import json
import os
import re


def _version_key(value):
    """Convert a version-like string into a comparable numeric tuple."""
    if not isinstance(value, str):
        return None
    match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", value.strip())
    if not match:
        return None
    parts = [int(group) if group is not None else 0 for group in match.groups()]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def normalize_version_label(value):
    """Return a normalized dotted version string if one can be parsed."""
    key = _version_key(value)
    if key is None:
        return None
    return ".".join(str(part) for part in key)


def is_newer_version(candidate, current):
    """Return whether the candidate version is newer than the current version."""
    candidate_key = _version_key(candidate)
    current_key = _version_key(current)
    if candidate_key is None or current_key is None:
        return False
    return candidate_key > current_key


def load_update_override(path, current_version):
    """Load an optional local update override file used for release-flow testing."""
    if not path or not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None

    if payload.get("enabled", True) is False:
        return None

    latest_version = normalize_version_label(
        payload.get("latest_version") or payload.get("tag_name")
    )
    if not latest_version or not is_newer_version(latest_version, current_version):
        return None

    asset_url = payload.get("asset_url")
    asset_path = payload.get("asset_path")
    if asset_path:
        if not os.path.isabs(asset_path):
            asset_path = os.path.join(os.path.dirname(path), asset_path)
        asset_url = os.path.abspath(asset_path)
    elif isinstance(asset_url, str) and asset_url:
        asset_url = asset_url.strip()

    asset_name = payload.get("asset_name")
    if not asset_name and asset_url:
        asset_name = os.path.basename(asset_url)

    release_url = payload.get("release_url") or path
    asset_sha256 = payload.get("sha256") or payload.get("asset_sha256")
    if isinstance(asset_sha256, str):
        asset_sha256 = asset_sha256.strip().lower()
    else:
        asset_sha256 = None
    checksum_url = payload.get("checksum_url")
    checksum_path = payload.get("checksum_path")
    if checksum_path:
        if not os.path.isabs(checksum_path):
            checksum_path = os.path.join(os.path.dirname(path), checksum_path)
        checksum_url = os.path.abspath(checksum_path)
    elif isinstance(checksum_url, str) and checksum_url:
        checksum_url = checksum_url.strip()
    else:
        checksum_url = None

    return {
        "latest_version": latest_version,
        "release_url": release_url,
        "asset_name": asset_name,
        "asset_url": asset_url,
        "asset_sha256": asset_sha256,
        "checksum_url": checksum_url,
    }
