$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

python -c "import webview" 2>$null
if ($LASTEXITCODE -ne 0) {
  throw "pywebview is not installed for this Python. Run: python -m pip install -r requirements/windows.txt"
}

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name "CheevoPresence" `
  --icon "cheevoRP_icon.ico" `
  --paths "$projectRoot" `
  --hidden-import "pystray._win32" `
  --hidden-import "desktop.shell.ipc" `
  --hidden-import "desktop.shell.settings_client" `
  --hidden-import "desktop.shell.web_settings" `
  --hidden-import "webview" `
  --collect-submodules "webview" `
  --exclude-module "desktop.platform.macos" `
  --exclude-module "desktop.shell.macos.entrypoint" `
  --exclude-module "desktop.shell.macos.menu_bar" `
  --exclude-module "objc" `
  --exclude-module "Foundation" `
  --exclude-module "AppKit" `
  --exclude-module "Quartz" `
  --exclude-module "PyObjCTools" `
  --add-data "console_icons.ini;." `
  --add-data "desktop/shell/web_assets;desktop/shell/web_assets" `
  --add-data ".github/assets/tray-default.png;.github/assets" `
  --add-data "cheevoRP_icon.ico;." `
  --add-data "cheevoRP_inactive.ico;." `
  --add-data "cheevoRP_active.ico;." `
  --add-data "cheevoRP_error.ico;." `
  "launch_windows.py"
