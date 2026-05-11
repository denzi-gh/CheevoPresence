#!/usr/bin/env bash
# Runs inside the privileged Docker container.
# Expected working directory: /src (repo root).
set -euo pipefail

APP_ID="io.github.denzi_gh.CheevoPresence"
MANIFEST="flatpak/${APP_ID}.yml"
REPO="/src/flatpak-repo"
BUILD_DIR="/src/.flatpak-builder/build"
STATE_DIR="/src/.flatpak-builder"
BUNDLE_DIR="/src/dist"

echo ""
echo "=== [1/5] Convert ICO → PNG ==="
convert cheevoRP_icon.ico[0] -resize 256x256 cheevoRP_icon.png
echo "cheevoRP_icon.png written."

echo ""
echo "=== [2/5] Pin Python requirements with pip-compile ==="
pip-compile --no-header --no-annotate \
    --output-file /src/flatpak/requirements-flatpak-locked.txt \
    /src/flatpak/requirements-flatpak.txt

echo ""
echo "=== [3/5] Install Flatpak runtimes (cached in volume on repeat runs) ==="
dbus-run-session -- flatpak install -y --system --noninteractive flathub \
    org.freedesktop.Platform//24.08 \
    org.freedesktop.Sdk//24.08 \
    || true  # continue if already installed

echo ""
echo "=== [4/5] Build Flatpak ==="
flatpak-builder \
    --repo="${REPO}" \
    --force-clean \
    --state-dir="${STATE_DIR}" \
    "${BUILD_DIR}" \
    "${MANIFEST}"

echo ""
echo "=== [5/5] Export .flatpak bundle ==="
mkdir -p "${BUNDLE_DIR}"
flatpak build-bundle \
    "${REPO}" \
    "${BUNDLE_DIR}/${APP_ID}.flatpak" \
    "${APP_ID}"

echo ""
echo "Build complete."
echo "Bundle: ${BUNDLE_DIR}/${APP_ID}.flatpak"
