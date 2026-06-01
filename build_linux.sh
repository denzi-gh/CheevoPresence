#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "$0")" && pwd)"
cd "$project_root"

build_venv_dir="$project_root/build/linux-venv"
pyinstaller_work_dir="$project_root/build/linux-work"
dependency_marker="$build_venv_dir/.dependencies.sha256"
pyinstaller_version="6.19.0"

python_supports_linux_desktop() {
  local candidate="$1"

  "${candidate}" - <<'PY' >/dev/null 2>&1
import tkinter
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3
except (ImportError, ValueError):
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3
PY
}

dependency_fingerprint() {
  {
    cat requirements/base.txt
    printf '\n'
    cat requirements/linux.txt
    printf '\npyinstaller==%s\n' "${pyinstaller_version}"
  } | sha256sum | awk '{print $1}'
}

select_build_python() {
  local -a candidates=()
  local candidate=""
  local resolved=""
  declare -A seen=()

  if [[ -n "${CHEEVO_LINUX_PYTHON:-}" ]]; then
    candidates+=("${CHEEVO_LINUX_PYTHON}")
  fi

  candidates+=("python3.12" "python3.11" "python3")

  for candidate in "${candidates[@]}"; do
    if [[ -x "${candidate}" ]]; then
      resolved="${candidate}"
    else
      resolved="$(command -v "${candidate}" 2>/dev/null || true)"
    fi
    if [[ -z "${resolved}" || -n "${seen[${resolved}]:-}" ]]; then
      continue
    fi
    seen["${resolved}"]=1
    if python_supports_linux_desktop "${resolved}"; then
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

  if [[ ! -x "${build_venv_dir}/bin/python" ]]; then
    rm -rf "${build_venv_dir}"
    "${base_python}" -m venv --system-site-packages "${build_venv_dir}"
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
    "${build_venv_dir}/bin/python" -m pip install --disable-pip-version-check -r requirements/linux.txt "pyinstaller==${pyinstaller_version}"
    printf '%s\n' "${current_fingerprint}" > "${dependency_marker}"
  fi
}

write_linux_launcher_files() {
  local exe_path="$project_root/dist/CheevoPresence"
  local icon_path="$project_root/dist/CheevoPresence.png"
  local desktop_path="$project_root/dist/CheevoPresence.desktop"

  "${build_python}" - "${project_root}/cheevoRP_icon.ico" "${icon_path}" "${exe_path}" "${desktop_path}" <<'PY'
import os
import re
import sys

from PIL import Image

source_icon, output_icon, exe_path, desktop_path = sys.argv[1:]
exec_safe_re = re.compile(r"^[A-Za-z0-9_/:=@%+.,-]+$")

for output_path in (output_icon, desktop_path):
    try:
        os.remove(output_path)
    except FileNotFoundError:
        pass


def quote_desktop_exec_arg(value):
    text = str(value).replace("%", "%%")
    if text and exec_safe_re.fullmatch(text):
        return text
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    return f'"{escaped}"'

with Image.open(source_icon) as image:
    frame = image
    if getattr(image, "n_frames", 1) > 1:
        best_frame = 0
        best_area = 0
        for index in range(image.n_frames):
            image.seek(index)
            area = image.size[0] * image.size[1]
            if area > best_area:
                best_frame = index
                best_area = area
        image.seek(best_frame)
        frame = image.copy()
    frame.convert("RGBA").resize((256, 256), Image.LANCZOS).save(output_icon, format="PNG")

desktop_payload = "\n".join(
    [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        "Name=CheevoPresence",
        "Comment=Mirror RetroAchievements activity to Discord Rich Presence",
        f"Exec={quote_desktop_exec_arg(os.path.abspath(exe_path))}",
        f"Icon={os.path.abspath(output_icon)}",
        "Terminal=false",
        "Categories=Utility;",
        "StartupWMClass=CheevoPresence",
        "",
    ]
)

with open(desktop_path, "w", encoding="utf-8") as handle:
    handle.write(desktop_payload)
os.chmod(desktop_path, 0o755)
PY
}

build_python="$(select_build_python || true)"
if [[ -z "${build_python}" ]]; then
  echo "No Linux desktop-capable Python runtime was found." >&2
  echo "Install the distro packages listed in .github/buildLinux.md, then rerun this script." >&2
  exit 1
fi

echo "Using Linux build interpreter: ${build_python}"
ensure_build_venv "${build_python}"

build_python="${build_venv_dir}/bin/python"
echo "Using Linux build venv: ${build_python}"

PYTHONPATH="$project_root${PYTHONPATH:+:$PYTHONPATH}" "${build_python}" -m PyInstaller \
  --noconfirm \
  --clean \
  --onefile \
  --windowed \
  --name "CheevoPresence" \
  --distpath "$project_root/dist" \
  --workpath "$pyinstaller_work_dir" \
  --paths "$project_root" \
  --hidden-import "desktop.platform.linux" \
  --hidden-import "desktop.shell.linux.entrypoint" \
  --hidden-import "desktop.shell.linux.indicator" \
  --hidden-import "desktop.shell.tk_settings" \
  --hidden-import "gi" \
  --hidden-import "gi.repository.GLib" \
  --hidden-import "gi.repository.Gtk" \
  --hidden-import "gi.repository.AyatanaAppIndicator3" \
  --hidden-import "gi.repository.AppIndicator3" \
  --exclude-module "desktop.platform.windows" \
  --exclude-module "desktop.shell.windows.entrypoint" \
  --exclude-module "desktop.shell.windows.tray" \
  --exclude-module "desktop.shell.windows.ui" \
  --exclude-module "desktop.platform.macos" \
  --exclude-module "desktop.shell.macos.entrypoint" \
  --exclude-module "desktop.shell.macos.ipc" \
  --exclude-module "desktop.shell.macos.menu_bar" \
  --exclude-module "desktop.shell.macos.settings" \
  --exclude-module "objc" \
  --exclude-module "Foundation" \
  --exclude-module "AppKit" \
  --exclude-module "Quartz" \
  --exclude-module "PyObjCTools" \
  --add-data "console_icons.ini:." \
  --add-data ".github/assets/tray-default.png:.github/assets" \
  --add-data "cheevoRP_icon.ico:." \
  --add-data "cheevoRP_inactive.ico:." \
  --add-data "cheevoRP_active.ico:." \
  --add-data "cheevoRP_error.ico:." \
  "launch_linux.py"

write_linux_launcher_files

echo "Built dist/CheevoPresence"
echo "Built dist/CheevoPresence.desktop"
