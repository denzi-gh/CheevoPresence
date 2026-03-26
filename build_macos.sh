#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

python3 -m PyInstaller \
  --noconfirm \
  --clean \
  --onefile \
  --windowed \
  --name "CheevoPresence" \
  --icon "cheevoRP_icon.ico" \
  --hidden-import "pystray._darwin" \
  --add-data "console_icons.ini:." \
  --add-data "cheevoRP_icon.ico:." \
  --add-data "cheevoRP_inactive.ico:." \
  --add-data "cheevoRP_active.ico:." \
  --add-data "cheevoRP_error.ico:." \
  "ra_discord_rp.py"
