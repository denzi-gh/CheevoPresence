#!/usr/bin/env bash
# Shipped inside CheevoPresence-linux-x86_64.tar.gz as install.sh.

set -euo pipefail

app_name="CheevoPresence"
package_dir="$(cd "$(dirname "$0")" && pwd)"

data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
bin_dir="$HOME/.local/bin"
desktop_dir="$data_home/applications"
icon_theme_dir="$data_home/icons/hicolor"
icon_dir="$icon_theme_dir/256x256/apps"
autostart_file="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/${app_name}.desktop"

exe_path="$bin_dir/$app_name"
desktop_path="$desktop_dir/${app_name}.desktop"
icon_path="$icon_dir/${app_name}.png"

quote_desktop_exec_arg() {
  local text="${1//%/%%}"
  if [[ "$text" =~ ^[A-Za-z0-9_/:=@%+.,-]+$ ]]; then
    printf '%s' "$text"
    return
  fi
  text="${text//\\/\\\\}"
  text="${text//\"/\\\"}"
  text="${text//\`/\\\`}"
  text="${text//\$/\\\$}"
  printf '"%s"' "$text"
}

refresh_desktop_caches() {
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$desktop_dir" >/dev/null 2>&1 || true
  fi
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$icon_theme_dir" >/dev/null 2>&1 || true
  fi
}

uninstall() {
  rm -f "$exe_path" "$desktop_path" "$icon_path" "$autostart_file"
  refresh_desktop_caches
  echo "$app_name removed."
  echo "Settings and logs were kept in ${XDG_CONFIG_HOME:-$HOME/.config}/$app_name"
  echo "Delete that folder too if you want a clean slate."
}

install_app() {
  if [[ ! -f "$package_dir/$app_name" ]]; then
    echo "Could not find $app_name next to this script." >&2
    echo "Extract the whole archive and run ./install.sh from inside it." >&2
    exit 1
  fi

  mkdir -p "$bin_dir" "$desktop_dir" "$icon_dir"

  # Replacing a running binary in place would kill it mid-write.
  rm -f "$exe_path"
  cp "$package_dir/$app_name" "$exe_path"
  chmod +x "$exe_path"

  if [[ -f "$package_dir/${app_name}.png" ]]; then
    cp "$package_dir/${app_name}.png" "$icon_path"
  fi

  cat > "$desktop_path" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=$app_name
Comment=Mirror RetroAchievements activity to Discord Rich Presence
Exec=$(quote_desktop_exec_arg "$exe_path")
Icon=$app_name
Terminal=false
Categories=Utility;
StartupWMClass=$app_name
EOF
  chmod 644 "$desktop_path"

  refresh_desktop_caches

  echo "$app_name installed."
  echo "  binary   $exe_path"
  echo "  launcher $desktop_path"
  echo
  echo "Start it from your application menu, or run: $app_name"

  case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *)
      echo
      echo "Note: $bin_dir is not on your PATH, so the '$app_name' command will"
      echo "not work in a terminal until you add it. The menu entry works either way."
      ;;
  esac
}

case "${1:-}" in
  --uninstall)
    uninstall
    ;;
  "")
    install_app
    ;;
  *)
    echo "Usage: $0 [--uninstall]" >&2
    exit 2
    ;;
esac
