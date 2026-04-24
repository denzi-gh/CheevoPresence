# <img src=".github/assets/tray-default.png" width="30"/> CheevoPresence

CheevoPresence is a desktop app for Windows, macOS, and Linux that mirrors your RetroAchievements activity to Discord Rich Presence.

It watches your current RetroAchievements session, detects whether you are actively playing, and updates Discord with your game, platform, achievement progress, and quick links to your RetroAchievements profile and game page.

![CheevoPresence settings window](./.github/assets/cheevopresence-settings-window.png)

## What It Does

- Shows your current RetroAchievements session as a live Discord Rich Presence with the actual game you are playing
- Detects when you are no longer actively playing and clears the Discord presence
- Supports profile and game-page buttons in Discord
- Runs quietly in the background

This app was made with the intent to be as easy and lightweight as possible. You start the app, put in your RetroAchievements Username and your Web API Key and it works. Close the Window and youre gucci.

![CheevoPresence settings window](./.github/assets/discordquickinfo.png)

![CheevoPresence settings window](./.github/assets/discordactivity.png)


## Getting Started

To use CheevoPresence, you need:

- A [RetroAchievements](https://retroachievements.org/) account
- Your RetroAchievements Web API key
- Discord installed and running on the same PC

### Linux Requirements

CheevoPresence supports any modern Linux distribution with **Python 3.10+** and GTK3 / AppIndicator3 libraries. It has been tested on Ubuntu, Debian, Fedora, Arch, Linux Mint, Pop!_OS, and Regolith.

| Distribution | Install command |
|---|---|
| **Debian / Ubuntu / Mint / Pop!_OS** | `sudo apt install python3 python3-tk libgtk-3-0 libappindicator3-1 gir1.2-appindicator3-0.1` |
| **Fedora** | `sudo dnf install python3 python3-tkinter gtk3 libappindicator-gtk3` |
| **Arch / Manjaro** | `sudo pacman -S python tk gtk3 libappindicator-gtk3` |

> The DEB package pulls in these dependencies automatically via `apt`. If you use the portable tarball or AppImage, install the packages above first.

**Supported Desktop Environments**

| Desktop Environment | Tray Support |
|---|---|
| KDE Plasma | Native |
| XFCE | Native |
| GNOME | Requires AppIndicator extension (e.g., AppIndicator Support) |
| Cinnamon, MATE | Native |
| Regolith / i3wm | Native (i3bar supports Xembed tray icons) |

### First-Time Setup

1. Launch `CheevoPresence.exe` on Windows, `CheevoPresence.app` on macOS, or `CheevoPresence` on Linux
2. Enter your RetroAchievement username
3. Enter your Web API key
4. Choose your preferred behavior settings
5. Click `Connect`

If everything is set up correctly, CheevoPresence will begin updating your Discord Rich Presence automatically.


> Make sure to close the Settings Window normally, pressing the "Exit App" Button will end the process entirely.


### Tray/Menu-Bar Status

#### Windows
CheevoPresence uses different tray icons to show its current state:

| Icon | Tray icon state | Meaning |
| --- | --- | --- |
| <img src="./.github/assets/tray-default.png" alt="Default tray icon" width="20" /> | Default app icon | Starting up or connecting |
| <img src="./.github/assets/tray-active.png" alt="Green tray icon" width="20" /> | Green icon | Connected and actively updating Discord |
| <img src="./.github/assets/tray-inactive.png" alt="Gray tray icon" width="20" /> | Gray icon | Idle, stopped, not playing, or not currently active |
| <img src="./.github/assets/tray-error.png" alt="Red tray icon" width="20" /> | Red icon | Something needs attention, such as Discord not being open, a network issue, or an API/config problem |

#### macOS
CheevoPresence uses a monochrome menu-bar icon that stays template-styled to match the system UI.

| Preview | Menu-bar state | Meaning |
| --- | --- | --- |
| <img src="./.github/assets/macOS_active.png" alt="macOS active menu-bar state" width="42" /> | Active | Connected and actively updating Discord |
| <img src="./.github/assets/macOS_inactive.png" alt="macOS inactive menu-bar state" width="42" /> | Inactive | Idle, stopped, not playing, or not currently active |
| <img src="./.github/assets/macOS_error.png" alt="macOS error menu-bar state" width="42" /> | Error | Something needs attention, such as Discord not being open, a network issue, or an API/config problem |

#### Linux
CheevoPresence uses colored tray icons through the system tray / AppIndicator.

| Icon | Tray icon state | Meaning |
| --- | --- | --- |
| <img src="./cheevoRP_icon.png" alt="Default tray icon" width="20" /> | Default app icon | Starting up or connecting |
| <img src="./cheevoRP_active.png" alt="Green tray icon" width="20" /> | Green icon | Connected and actively updating Discord |
| <img src="./cheevoRP_inactive.png" alt="Gray tray icon" width="20" /> | Gray icon | Idle, stopped, not playing, or not currently active |
| <img src="./cheevoRP_error.png" alt="Red tray icon" width="20" /> | Red icon | Something needs attention, such as Discord not being open, a network issue, or an API/config problem |

> **Note for GNOME users:** System tray support may require an AppIndicator extension.

## Configuration and Privacy

CheevoPresence does not expect you to keep secrets inside the repository.

- The repository-level `config.json` is ignored by Git
- Runtime configuration is stored under `%APPDATA%\CheevoPresence\config.json` on Windows
- Runtime configuration is stored under `~/Library/Application Support/CheevoPresence/config.json` on macOS
- Runtime configuration is stored under `~/.config/CheevoPresence/config.json` on Linux
- The API key is stored in a protected form on Windows, in the macOS Keychain on macOS, and in the Linux system keyring (GNOME Keyring / KDE Wallet / Secret Service) on Linux, rather than being written back as plain text in the repo
- `config.example.json` exists only as a clean template



## Building the App Yourself

If you want to modify or package CheevoPresence yourself, use the platform-specific build guides:

- Windows: [`.github/buildWindows.md`](./.github/buildWindows.md)
- macOS: [`.github/buildMacOS.md`](./.github/buildMacOS.md)
- Linux: [`.github/buildLinux.md`](./.github/buildLinux.md)


## Support the Project

If CheevoPresence made your setup a little nicer and you feel like supporting the project, a small tip on [Ko-fi](https://ko-fi.com/denzi) would be genuinely appreciated.

Thanks for checking out CheevoPresence.
