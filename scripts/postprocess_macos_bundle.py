"""Apply final bundle metadata tweaks after the macOS PyInstaller build."""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop.core.constants import APP_NAME, APP_VERSION


def main(app_path):
    bundle_path = Path(app_path).resolve()
    plist_path = bundle_path / "Contents" / "Info.plist"
    if not plist_path.exists():
        raise FileNotFoundError(f"Missing Info.plist: {plist_path}")

    with plist_path.open("rb") as handle:
        payload = plistlib.load(handle)

    payload["CFBundleDisplayName"] = APP_NAME
    payload["CFBundleName"] = APP_NAME
    payload["CFBundleIdentifier"] = "org.denzi.cheevopresence"
    payload["CFBundleShortVersionString"] = APP_VERSION
    payload["CFBundleVersion"] = APP_VERSION
    payload["LSUIElement"] = True
    payload["NSHighResolutionCapable"] = True

    with plist_path.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=False)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 scripts/postprocess_macos_bundle.py dist/CheevoPresence.app")
    main(sys.argv[1])
