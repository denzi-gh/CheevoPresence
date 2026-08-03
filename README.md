<div align="center">

<img src=".github/assets/tray-default.png" width="110" alt="CheevoPresence logo" />

# CheevoPresence

**Mirror your RetroAchievements Activity to Discord**

[![Latest Release](https://img.shields.io/github/v/release/denzi-gh/CheevoPresence?style=for-the-badge&logo=github&label=Latest%20Release&color=5865F2)](https://github.com/denzi-gh/CheevoPresence/releases/latest)
[![Downloads](https://img.shields.io/endpoint?url=https%3A%2F%2Fdenzi.dev%2Fapi%2Fdownloads%2Fdenzi-gh%2FCheevoPresence&style=for-the-badge)](https://github.com/denzi-gh/CheevoPresence/releases)
[![Support on Ko-fi](https://img.shields.io/badge/Ko--fi-Support-FF5E5B?style=for-the-badge&logo=kofi&logoColor=white)](https://ko-fi.com/denzi)

</div>

<br>

CheevoPresence is a desktop app for Windows, macOS, and Linux that mirrors your RetroAchievements activity to Discord Rich Presence.

It watches your current RetroAchievements session, detects whether you are actively playing, and updates Discord with your game, platform, achievement progress, and quick links to your RetroAchievements profile, created sets, or game page.

<p align="center">
  <img src="./.github/assets/cheevopresence1.3.0.png" alt="CheevoPresence settings window" />
</p>

---

## What It Does

- Shows your current RetroAchievements session as a live Discord Rich Presence with the actual game you are playing
- Shows a live in-app preview of what is currently being mirrored to Discord
- Detects when you are no longer actively playing and clears the Discord presence
- Supports profile and game-page buttons in Discord
- Detects RetroAchievements developer and staff roles, with optional developer activity titles
- Runs quietly in the background

This app was made with the intent to be as easy and lightweight as possible. You start the app, put in your RetroAchievements username and Web API key, click `Connect`, and it works. Close the settings window and CheevoPresence keeps running in the tray/menu bar.

<p align="center">
  <img src="./.github/assets/discordquickinfo.png" alt="CheevoPresence settings window" />
  &nbsp;&nbsp;
  <img src="./.github/assets/discordactivity.png" alt="CheevoPresence settings window" />
</p>

---

## Getting Started

To use CheevoPresence, you need:

- A [RetroAchievements](https://retroachievements.org/) account
- Your RetroAchievements Web API key
- Discord installed and running on the same PC

### First-Time Setup

1. Launch CheevoPresence
2. Enter your RetroAchievement username
3. Enter your Web API key
4. Choose your preferred behavior settings
5. Click `Connect`

If everything is set up correctly, CheevoPresence will begin updating your Discord Rich Presence automatically.

The settings window also shows your current Discord/RetroAchievements status, a live preview of the presence being sent to Discord, logs, diagnostics, and update notices.

RetroAchievements developer options unlock automatically for accounts with a detected developer-capable role. They can show developer activity titles and optionally link to your created sets while developing achievements.

> [!IMPORTANT]
> Make sure to close the Settings Window normally, pressing the "Exit App" Button will end the process entirely.

### Tray/Menu-Bar Status

#### Windows / Linux

CheevoPresence uses different tray icons to show its current state:

<div align="center">

| Icon | Tray icon state | Meaning |
| :---: | :--- | :--- |
| <img src="./.github/assets/tray-default.png" alt="Default tray icon" width="20" /> | Default app icon | Starting up or connecting |
| <img src="./.github/assets/tray-active.png" alt="Green tray icon" width="20" /> | Green icon | Connected and actively updating Discord |
| <img src="./.github/assets/tray-inactive.png" alt="Gray tray icon" width="20" /> | Gray icon | Idle, stopped, not playing, or not currently active |
| <img src="./.github/assets/tray-error.png" alt="Red tray icon" width="20" /> | Red icon | Something needs attention, such as Discord not being open, a network issue, or an API/config problem |

</div>

#### macOS

CheevoPresence uses a monochrome menu-bar icon that stays template-styled to match the system UI.

<div align="center">

| Preview | Menu-bar state | Meaning |
| :---: | :--- | :--- |
| <img src="./.github/assets/macOS_active.png" alt="macOS active menu-bar state" width="42" /> | Active | Connected and actively updating Discord |
| <img src="./.github/assets/macOS_inactive.png" alt="macOS inactive menu-bar state" width="42" /> | Inactive | Idle, stopped, not playing, or not currently active |
| <img src="./.github/assets/macOS_error.png" alt="macOS error menu-bar state" width="42" /> | Error | Something needs attention, such as Discord not being open, a network issue, or an API/config problem |

</div>

---

## Configuration and Privacy

CheevoPresence does not expect you to keep secrets inside the repository.

- The repository-level `config.json` is ignored by Git
- Runtime configuration is stored under `%APPDATA%\CheevoPresence\config.json` on Windows
- Runtime configuration is stored under `~/Library/Application Support/CheevoPresence/config.json` on macOS
- Runtime configuration is stored under `${XDG_CONFIG_HOME:-~/.config}/CheevoPresence/config.json` on Linux
- The API key is stored in a protected form on Windows, in the macOS Keychain on macOS, and in the Linux local config encoding on Linux rather than being written back as plain text in the repo
- `config.example.json` exists only as a clean template

### Diagnostic Logs

CheevoPresence writes local diagnostic logs so problems can be diagnosed without exposing anything in the app UI.

- Windows logs: `%APPDATA%\CheevoPresence\logs`
- macOS logs: `~/Library/Application Support/CheevoPresence/logs`
- Linux logs: `${XDG_STATE_HOME:-~/.local/state}/CheevoPresence/logs`

> [!NOTE]
> If something is not working, zip that folder and send it to me via Discord or post it in the Issue. It contains no API Keys or full Paths :)

---

## Building the App Yourself

If you want to modify or package CheevoPresence yourself, use the platform-specific build guides:

- Windows: [`.github/buildWindows.md`](./.github/buildWindows.md)
- macOS: [`.github/buildMacOS.md`](./.github/buildMacOS.md)
- Linux: [`.github/buildLinux.md`](./.github/buildLinux.md)

---

## Support the Project

If CheevoPresence made your setup a little nicer and you feel like supporting the project, a small tip on [Ko-fi](https://ko-fi.com/denzi) would be genuinely appreciated.

<p align="center">
  <a href="https://ko-fi.com/denzi">
    <img src="https://img.shields.io/badge/Buy%20me%20a%20coffee-Ko--fi-FF5E5B?style=for-the-badge&logo=kofi&logoColor=white" alt="Support on Ko-fi" />
  </a>
</p>

<div align="center">

Thanks for checking out CheevoPresence.

</div>
