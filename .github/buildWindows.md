# Building CheevoPresence on Windows

This guide is for people who cloned the repository and want to build `CheevoPresence.exe` themselves.

## Requirements

- Windows 10 or newer
- PowerShell
- Python 3.11 or 3.12 on `PATH`
- `pip`

## 1. Clone the repository

```powershell
git clone https://github.com/denzi-gh/CheevoPresence.git
cd CheevoPresence
```

## 2. Create a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, allow local scripts for the current user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 3. Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements/windows.txt pyinstaller
```

## 4. Build the executable

```powershell
.\build_exe.ps1
```

That script runs PyInstaller in one-file, windowed mode and produces:

```text
dist\CheevoPresence.exe
```

## 5. Run the build

```powershell
.\dist\CheevoPresence.exe
```

## What the Windows build includes

The script bundles:

- `launch_windows.py`
- `console_icons.ini`
- `cheevoRP_icon.ico`
- `cheevoRP_inactive.ico`
- `cheevoRP_active.ico`
- `cheevoRP_error.ico`

## Manual build command

If you want to run PyInstaller yourself instead of using the script:

```powershell
python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name "CheevoPresence" `
  --icon "cheevoRP_icon.ico" `
  --paths "$PWD" `
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
```

## Troubleshooting

- If `python` is not found, reinstall Python and enable the "Add Python to PATH" option.
- If PyInstaller is missing, reinstall it inside the active virtual environment.
- If Windows SmartScreen warns about the generated `.exe`, that is expected for an unsigned local build.
