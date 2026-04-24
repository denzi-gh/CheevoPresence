#!/usr/bin/env bash
set -euo pipefail

# CheevoPresence Linux Build Script
# Supports: tarball (portable), AppImage, and DEB packaging

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="CheevoPresence"
APP_NAME_LOWER="cheevopresence"
VERSION="1.1.1"
BUILD_DIR="${SCRIPT_DIR}/build/linux"
DIST_DIR="${SCRIPT_DIR}/dist/linux"

show_help() {
    cat <<EOF
Usage: $0 [OPTION]

Build CheevoPresence for Linux.

Options:
  tarball    Build a portable tarball (.tar.gz)
  appimage   Build an AppImage
  deb        Build a DEB package
  all        Build all formats
  help       Show this help message

Examples:
  $0 tarball
  $0 all
EOF
}

setup_env() {
    echo "==> Setting up build environment..."
    python3 -m pip install --upgrade pip
    python3 -m pip install -r requirements.txt
    python3 -m pip install pyinstaller
}

clean_build() {
    echo "==> Cleaning previous builds..."
    rm -rf "${BUILD_DIR}" "${DIST_DIR}"
    mkdir -p "${BUILD_DIR}" "${DIST_DIR}"
}

build_executable() {
    echo "==> Building executable with PyInstaller..."
    pyinstaller \
        --noconfirm \
        --onefile \
        --name "${APP_NAME}" \
        --add-data "${SCRIPT_DIR}/console_icons.ini:." \
        --add-data "${SCRIPT_DIR}/cheevoRP_icon.png:." \
        --add-data "${SCRIPT_DIR}/cheevoRP_active.png:." \
        --add-data "${SCRIPT_DIR}/cheevoRP_inactive.png:." \
        --add-data "${SCRIPT_DIR}/cheevoRP_error.png:." \
        --hidden-import="desktop.shell.linux" \
        --hidden-import="desktop.platform.linux" \
        --hidden-import="keyring" \
        --distpath "${BUILD_DIR}/dist" \
        --workpath "${BUILD_DIR}/work" \
        --specpath "${BUILD_DIR}" \
        "${SCRIPT_DIR}/launch_linux.py"
}

build_tarball() {
    echo "==> Building portable tarball..."
    local tarball_dir="${BUILD_DIR}/${APP_NAME_LOWER}-${VERSION}-linux"
    mkdir -p "${tarball_dir}"

    cp "${BUILD_DIR}/dist/${APP_NAME}" "${tarball_dir}/"
    cp "${SCRIPT_DIR}/console_icons.ini" "${tarball_dir}/"
    cp "${SCRIPT_DIR}/cheevoRP_icon.png" "${tarball_dir}/"
    cp "${SCRIPT_DIR}/cheevoRP_active.png" "${tarball_dir}/"
    cp "${SCRIPT_DIR}/cheevoRP_inactive.png" "${tarball_dir}/"
    cp "${SCRIPT_DIR}/cheevoRP_error.png" "${tarball_dir}/"
    cp "${SCRIPT_DIR}/LICENSE" "${tarball_dir}/" 2>/dev/null || true

    cat > "${tarball_dir}/README.txt" <<EOF
${APP_NAME} ${VERSION} for Linux
================================

Run the app:
  ./${APP_NAME}

Or start minimized to tray:
  ./${APP_NAME} --tray

Exit a running instance:
  ./${APP_NAME} --exit

Config is stored at:
  ~/.config/CheevoPresence/config.json

Requirements:
  - Discord or Vesktop (with arRPC enabled) must be running
  - GTK3 and AppIndicator libraries for system tray support
EOF

    chmod +x "${tarball_dir}/${APP_NAME}"

    cd "${BUILD_DIR}"
    tar -czf "${DIST_DIR}/${APP_NAME_LOWER}-${VERSION}-linux.tar.gz" "$(basename "${tarball_dir}")"
    cd "${SCRIPT_DIR}"

    echo "==> Tarball created: dist/linux/${APP_NAME_LOWER}-${VERSION}-linux.tar.gz"
}

build_appimage() {
    echo "==> Building AppImage..."

    local appdir="${BUILD_DIR}/${APP_NAME}.AppDir"
    mkdir -p "${appdir}/usr/bin" "${appdir}/usr/share/applications" "${appdir}/usr/share/icons/hicolor/64x64/apps"

    cp "${BUILD_DIR}/dist/${APP_NAME}" "${appdir}/usr/bin/${APP_NAME_LOWER}"
    cp "${SCRIPT_DIR}/console_icons.ini" "${appdir}/usr/bin/"
    cp "${SCRIPT_DIR}/cheevoRP_icon.png" "${appdir}/usr/share/icons/hicolor/64x64/apps/${APP_NAME_LOWER}.png"
    cp "${SCRIPT_DIR}/cheevoRP_icon.png" "${appdir}/${APP_NAME_LOWER}.png"

    cat > "${appdir}/${APP_NAME_LOWER}.desktop" <<EOF
[Desktop Entry]
Name=${APP_NAME}
Exec=usr/bin/${APP_NAME_LOWER}
Icon=${APP_NAME_LOWER}
Type=Application
Categories=Game;Network;
Comment=Mirror your RetroAchievements activity to Discord
EOF

    cat > "${appdir}/AppRun" <<EOF
#!/bin/bash
HERE="\$(dirname "\$(readlink -f "\${0}")")"
exec "\${HERE}/usr/bin/${APP_NAME_LOWER}" "\$@"
EOF
    chmod +x "${appdir}/AppRun"
    chmod +x "${appdir}/usr/bin/${APP_NAME_LOWER}"

    if command -v appimagetool &> /dev/null; then
        ARCH=x86_64 appimagetool "${appdir}" "${DIST_DIR}/${APP_NAME_LOWER}-${VERSION}-x86_64.AppImage"
        echo "==> AppImage created: dist/linux/${APP_NAME_LOWER}-${VERSION}-x86_64.AppImage"
    else
        echo "WARNING: appimagetool not found. Skipping AppImage build."
        echo "Install it from: https://github.com/AppImage/AppImageKit/releases"
    fi
}

build_deb() {
    echo "==> Building DEB package..."

    local pkg_dir="${BUILD_DIR}/${APP_NAME_LOWER}_${VERSION}_amd64"
    mkdir -p "${pkg_dir}/DEBIAN"
    mkdir -p "${pkg_dir}/usr/bin"
    mkdir -p "${pkg_dir}/usr/share/applications"
    mkdir -p "${pkg_dir}/usr/share/icons/hicolor/64x64/apps"
    mkdir -p "${pkg_dir}/usr/share/doc/${APP_NAME_LOWER}"

    cp "${BUILD_DIR}/dist/${APP_NAME}" "${pkg_dir}/usr/bin/${APP_NAME_LOWER}"
    chmod 755 "${pkg_dir}/usr/bin/${APP_NAME_LOWER}"
    cp "${SCRIPT_DIR}/console_icons.ini" "${pkg_dir}/usr/bin/"
    cp "${SCRIPT_DIR}/cheevoRP_icon.png" "${pkg_dir}/usr/share/icons/hicolor/64x64/apps/${APP_NAME_LOWER}.png"

    cat > "${pkg_dir}/usr/share/applications/${APP_NAME_LOWER}.desktop" <<EOF
[Desktop Entry]
Name=${APP_NAME}
Comment=Mirror your RetroAchievements activity to Discord
Exec=/usr/bin/${APP_NAME_LOWER}
Icon=${APP_NAME_LOWER}
Type=Application
Terminal=false
Categories=Game;Network;
EOF

    cat > "${pkg_dir}/DEBIAN/control" <<EOF
Package: ${APP_NAME_LOWER}
Version: ${VERSION}
Section: games
Priority: optional
Architecture: amd64
Depends: python3, libgtk-3-0, libappindicator3-1
Maintainer: denzi <denzi@example.com>
Description: Mirror your RetroAchievements activity to Discord
 CheevoPresence watches your RetroAchievements session and
 updates Discord Rich Presence with your current game, platform,
 and achievement progress.
EOF

    cp "${SCRIPT_DIR}/LICENSE" "${pkg_dir}/usr/share/doc/${APP_NAME_LOWER}/copyright" 2>/dev/null || true

    dpkg-deb --build "${pkg_dir}" "${DIST_DIR}/${APP_NAME_LOWER}_${VERSION}_amd64.deb"
    echo "==> DEB created: dist/linux/${APP_NAME_LOWER}_${VERSION}_amd64.deb"
}

main() {
    case "${1:-help}" in
        tarball)
            setup_env
            clean_build
            build_executable
            build_tarball
            ;;
        appimage)
            setup_env
            clean_build
            build_executable
            build_appimage
            ;;
        deb)
            setup_env
            clean_build
            build_executable
            build_deb
            ;;
        all)
            setup_env
            clean_build
            build_executable
            build_tarball
            build_appimage
            build_deb
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
}

main "$@"
