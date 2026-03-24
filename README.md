# <img src=".github/assets/tray-default.png" width="30"/> CheevoPresence

CheevoPresence is a (for now only) Windows desktop app that mirrors your RetroAchievements activity to Discord Rich Presence.

It watches your current RetroAchievements session, detects whether you are actively playing, and updates Discord with your game, platform, achievement progress, and quick links to your RetroAchievements profile and game page.

![CheevoPresence settings window](./.github/assets/cheevopresence-settings-window.png)

## What It Does

- Shows your current RetroAchievements session as a live Discord Rich Presence
- Detects when you are no longer actively playing and clears the Discord presence
- Supports profile and game-page buttons in Discord
- Runs quietly in the Windows system tray
- Lets you launch the app automatically with Windows Startup

This app was made with the intent to be as easy and lightweight as possible. You start the app, put in your RetroAchievements Username and your Web API Key and it works. Close the Window and youre gucci.

![CheevoPresence settings window](./.github/assets/discordquickinfo.png)

![CheevoPresence settings window](./.github/assets/discordactivity.png)


## Getting Started

To use CheevoPresence, you need:

- A [RetroAchievements](https://retroachievements.org/) account
- Your RetroAchievements Web API key
- Discord installed and running on the same PC

### First-Time Setup

1. Launch `CheevoPresence.exe`
2. Enter your RetroAchievement username
3. Enter your Web API key
4. Choose your preferred behavior settings
5. Click `Connect`

If everything is set up correctly, CheevoPresence will begin updating your Discord Rich Presence automatically.


> Make sure to close the Settings Window normally, pressing the "Exit App" Button will end the process entirely.


### Tray Icon Meanings

CheevoPresence uses different tray icons to show its current state:

| Icon | Tray icon state | Meaning |
| --- | --- | --- |
| <img src="./.github/assets/tray-default.png" alt="Default tray icon" width="20" /> | Default app icon | Starting up or connecting |
| <img src="./.github/assets/tray-active.png" alt="Green tray icon" width="20" /> | Green icon | Connected and actively updating Discord |
| <img src="./.github/assets/tray-inactive.png" alt="Gray tray icon" width="20" /> | Gray icon | Idle, stopped, not playing, or not currently active |
| <img src="./.github/assets/tray-error.png" alt="Red tray icon" width="20" /> | Red icon | Something needs attention, such as Discord not being open, a network issue, or an API/config problem |

## Configuration and Privacy

CheevoPresence does not expect you to keep secrets inside the repository.

- The repository-level `config.json` is ignored by Git
- Runtime configuration is stored under `%APPDATA%\CheevoPresence\config.json`
- The API key is stored in a protected form on Windows rather than being written back as plain text in the repo
- `config.example.json` exists only as a clean template



## Building the App Yourself

If you want to modify, test, or package CheevoPresence yourself, you can build the executable locally.

### Build Prerequisites

- Windows
- Python
- The packages from `requirements.txt`
- PyInstaller

Install PyInstaller separately:

```powershell
pip install pyinstaller
```

### Build With the Included Script

The project already includes a PowerShell build script:

```powershell
.\build_exe.ps1
```

This builds a one-file, windowed executable named:

```text
dist\CheevoPresence.exe
```

### What the Build Script Includes

The bundled build currently packages:

- `ra_discord_rp.py`
- `console_icons.ini`
- `cheevoRP_icon.ico`
- `cheevoRP_inactive.ico`
- `cheevoRP_active.ico`
- `cheevoRP_error.ico`

### Manual PyInstaller Command

If you prefer to build manually instead of using the script, this is the equivalent command:

```powershell
python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name "CheevoPresence" `
  --icon "cheevoRP_icon.ico" `
  --hidden-import "pystray._win32" `
  --add-data "console_icons.ini;." `
  --add-data "cheevoRP_icon.ico;." `
  --add-data "cheevoRP_inactive.ico;." `
  --add-data "cheevoRP_active.ico;." `
  --add-data "cheevoRP_error.ico;." `
  "ra_discord_rp.py"
```

## Support the Project

If CheevoPresence made your setup a little nicer and you feel like supporting the project, a small tip on [Ko-fi](https://ko-fi.com/denzi) would be genuinely appreciated.

Thanks for checking out CheevoPresence.
