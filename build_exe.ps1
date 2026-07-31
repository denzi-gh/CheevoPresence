$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

python -c "import webview" 2>$null
if ($LASTEXITCODE -ne 0) {
  throw "pywebview is not installed for this Python. Run: python -m pip install -r requirements/windows.txt"
}

# version metadata (pulled from constants.py)
$appVersion = python -c "from desktop.core.constants import APP_VERSION; print(APP_VERSION)"
if ($LASTEXITCODE -ne 0) { throw "Could not read APP_VERSION from desktop/core/constants.py" }
$appVersion = $appVersion.Trim()
$parts = $appVersion.Split('.')
$vTuple = "$($parts[0]), $($parts[1]), $($parts[2]), 0"

$versionFile = Join-Path $projectRoot "version_info.txt"
@"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($vTuple), prodvers=($vTuple),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'denzi-gh'),
      StringStruct('FileDescription', 'CheevoPresence - RetroAchievements Discord Rich Presence'),
      StringStruct('FileVersion', '$appVersion'),
      StringStruct('InternalName', 'CheevoPresence'),
      StringStruct('LegalCopyright', 'Copyright (c) denzi-gh'),
      StringStruct('OriginalFilename', 'CheevoPresence.exe'),
      StringStruct('ProductName', 'CheevoPresence'),
      StringStruct('ProductVersion', '$appVersion')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -LiteralPath $versionFile -Encoding UTF8

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name "CheevoPresence" `
  --icon "cheevoRP_icon.ico" `
  --version-file "version_info.txt" `
  --noupx `
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
