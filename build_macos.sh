#!/bin/zsh

set -euo pipefail

project_root="$(cd "$(dirname "$0")" && pwd)"
cd "$project_root"

build_venv_dir="$project_root/build/macos/venv"
build_python_marker="$build_venv_dir/.base_python"
dependency_marker="$build_venv_dir/.dependencies.sha256"
codesign_identity="${CHEEVO_MACOS_CODESIGN_IDENTITY:--}"

python_supports_tk() {
  local candidate="$1"

  "${candidate}" - <<'PY' >/dev/null 2>&1
import sys
import tkinter as tk

root = tk.Tk()
root.withdraw()
root.update_idletasks()
root.destroy()
sys.exit(0)
PY
}

dependency_fingerprint() {
  {
    cat requirements/base.txt
    printf '\n'
    cat requirements/macos.txt
    printf '\n'
    cat requirements/build.txt
  } | shasum -a 256 | awk '{print $1}'
}

select_build_python() {
  local -a candidates
  local cached_python=""
  local candidate=""
  local resolved=""
  typeset -A seen

  if [[ -n "${CHEEVO_MACOS_PYTHON:-}" ]]; then
    candidates+=("${CHEEVO_MACOS_PYTHON}")
  fi

  if [[ -x "${build_venv_dir}/bin/python" && -f "${build_python_marker}" ]]; then
    cached_python="$(<"${build_python_marker}")"
    if [[ -n "${cached_python}" ]]; then
      candidates+=("${cached_python}")
    fi
  fi

  candidates+=(
    "/opt/homebrew/bin/python3.12"
    "/opt/homebrew/bin/python3.11"
    "/opt/homebrew/opt/python@3.12/bin/python3.12"
    "/usr/local/bin/python3.12"
    "/usr/local/opt/python@3.12/bin/python3.12"
    "python3.12"
    "python3.11"
    "python3"
  )

  for candidate in "${candidates[@]}"; do
    if [[ -z "${candidate}" ]]; then
      continue
    fi
    if [[ -x "${candidate}" ]]; then
      resolved="${candidate}"
    else
      resolved="$(command -v "${candidate}" 2>/dev/null || true)"
    fi
    if [[ -z "${resolved}" || -n "${seen[${resolved}]:-}" ]]; then
      continue
    fi
    seen["${resolved}"]=1
    if python_supports_tk "${resolved}"; then
      printf '%s\n' "${resolved}"
      return 0
    fi
  done

  return 1
}

ensure_build_venv() {
  local base_python="$1"
  local current_fingerprint=""
  local stored_fingerprint=""
  local should_install=0

  if [[ ! -x "${build_venv_dir}/bin/python" ]] || [[ ! -f "${build_python_marker}" ]] || [[ "$(<"${build_python_marker}")" != "${base_python}" ]]; then
    rm -rf "${build_venv_dir}"
    "${base_python}" -m venv "${build_venv_dir}"
    printf '%s\n' "${base_python}" > "${build_python_marker}"
    should_install=1
  fi

  current_fingerprint="$(dependency_fingerprint)"
  if [[ -f "${dependency_marker}" ]]; then
    stored_fingerprint="$(<"${dependency_marker}")"
  fi
  if [[ "${stored_fingerprint}" != "${current_fingerprint}" ]]; then
    should_install=1
  fi

  if [[ "${should_install}" -eq 1 ]]; then
    "${build_venv_dir}/bin/python" -m pip install --disable-pip-version-check --upgrade pip setuptools wheel
    "${build_venv_dir}/bin/python" -m pip install --disable-pip-version-check -r requirements/macos.txt -r requirements/build.txt
    printf '%s\n' "${current_fingerprint}" > "${dependency_marker}"
  fi
}

sign_macos_bundle() {
  local app_path="$1"
  local -a codesign_args

  if [[ ! -d "${app_path}" ]]; then
    echo "Missing macOS app bundle to sign: ${app_path}" >&2
    return 1
  fi

  codesign_args=(--force --deep --sign "${codesign_identity}")
  if [[ "${codesign_identity}" != "-" ]]; then
    codesign_args+=(--options runtime)
  fi

  echo "Signing ${app_path} with identity: ${codesign_identity}"
  /usr/bin/codesign "${codesign_args[@]}" "${app_path}"
  /usr/bin/codesign --verify --deep --strict --verbose=2 "${app_path}"
}

build_python="$(select_build_python || true)"
if [[ -z "${build_python}" ]]; then
  echo "No Tk-capable Python runtime was found for the macOS build." >&2
  echo "Install a Python build with working Tk support, for example:" >&2
  echo "  brew install python@3.12 python-tk@3.12 tcl-tk" >&2
  echo "Or set CHEEVO_MACOS_PYTHON to a python.org/Homebrew interpreter before running this script." >&2
  exit 1
fi

echo "Using macOS build interpreter: ${build_python}"
ensure_build_venv "${build_python}"

build_python="${build_venv_dir}/bin/python"
echo "Using macOS build venv: ${build_python}"

"${build_python}" scripts/build_macos_assets.py

"${build_python}" - <<'PY'
import importlib

importlib.import_module("desktop.shell.macos.menu_bar")
print("Verified desktop.shell.macos.menu_bar import")
PY

PYTHONPATH="$project_root${PYTHONPATH:+:$PYTHONPATH}" "${build_python}" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "CheevoPresence" \
  --icon "build/macos/generated/CheevoPresence.icns" \
  --paths "$project_root" \
  --osx-bundle-identifier "org.denzi.cheevopresence" \
  --hidden-import "desktop.platform.macos" \
  --hidden-import "desktop.shell.macos.entrypoint" \
  --hidden-import "desktop.shell.ipc" \
  --hidden-import "desktop.shell.macos.menu_bar" \
  --hidden-import "desktop.shell.settings_client" \
  --hidden-import "desktop.shell.web_settings" \
  --hidden-import "objc" \
  --hidden-import "Foundation" \
  --hidden-import "AppKit" \
  --hidden-import "Quartz" \
  --hidden-import "PyObjCTools.AppHelper" \
  --exclude-module "desktop.platform.windows" \
  --exclude-module "desktop.shell.windows.entrypoint" \
  --exclude-module "desktop.shell.windows.tray" \
  --exclude-module "pystray._win32" \
  --add-data "console_icons.ini:." \
  --add-data "desktop/shell/web_assets:desktop/shell/web_assets" \
  --add-data ".github/assets/tray-default.png:.github/assets" \
  --add-data "build/macos/generated/cheevoRP_menubar_template.png:." \
  "launch_macos.py"

"${build_python}" scripts/postprocess_macos_bundle.py "dist/CheevoPresence.app"
sign_macos_bundle "dist/CheevoPresence.app"
arch_label="$(uname -m)"
/usr/bin/ditto -c -k --keepParent "dist/CheevoPresence.app" "dist/CheevoPresence-macos-${arch_label}.zip"

echo "Built dist/CheevoPresence.app"
echo "Packaged dist/CheevoPresence-macos-${arch_label}.zip"
