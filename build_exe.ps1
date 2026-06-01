$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name "CheevoPresence" `
  --icon "cheevoRP_icon.ico" `
  --paths "$projectRoot" `
  --hidden-import "pystray._win32" `
  --exclude-module "desktop.platform.macos" `
  --exclude-module "desktop.shell.macos.entrypoint" `
  --exclude-module "desktop.shell.ipc" `
  --exclude-module "desktop.shell.macos.menu_bar" `
  --exclude-module "desktop.shell.settings_client" `
  --exclude-module "objc" `
  --exclude-module "Foundation" `
  --exclude-module "AppKit" `
  --exclude-module "Quartz" `
  --exclude-module "PyObjCTools" `
  --add-data "console_icons.ini;." `
  --add-data "cheevoRP_icon.ico;." `
  --add-data "cheevoRP_inactive.ico;." `
  --add-data "cheevoRP_active.ico;." `
  --add-data "cheevoRP_error.ico;." `
  "launch_windows.py"
