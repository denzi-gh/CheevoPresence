# <img src=".github/assets/tray-default.png" width="30"/> CheevoPresence

CheevoPresence is a desktop app for Windows, macOS, and Linux that mirrors your RetroAchievements activity to Discord Rich Presence.

It watches your current RetroAchievements session, detects whether you are actively playing, and updates Discord with your game, platform, achievement progress, and quick links to your RetroAchievements profile and game page.

![CheevoPresence settings window](./.github/assets/cheevopresence-settings-window.png)

## What It Does

- Shows your current RetroAchievements session as a live Discord Rich Presence with the actual game you are playing
- Detects when you are no longer actively playing and clears the Discord presence
- Supports profile and game-page buttons in Discord
- Runs quietly in the background
- Linux support via Flatpak

This app was made with the intent to be as easy and lightweight as possible. You start the app, put in your RetroAchievements Username and your Web API Key and it works. Close the Window and youre gucci.

![CheevoPresence settings window](./.github/assets/discordquickinfo.png)

![CheevoPresence settings window](./.github/assets/discordactivity.png)


## Getting Started

To use CheevoPresence, you need:

- A [RetroAchievements](https://retroachievements.org/) account
- Your RetroAchievements Web API key
- Discord installed and running on the same PC

### First-Time Setup

#### Windows and macOS

1. Launch `CheevoPresence.exe` on Windows or `CheevoPresence.app` on macOS
2. Enter your RetroAchievement username
3. Enter your Web API key
4. Choose your preferred behavior settings
5. Click `Connect`

If everything is set up correctly, CheevoPresence will begin updating your Discord Rich Presence automatically.


> Make sure to close the Settings Window normally, pressing the "Exit App" Button will end the process entirely.

#### Linux

On Linux, CheevoPresence runs as a CLI app inside a Flatpak. There is no settings window or tray icon. See the [Linux (Flatpak)](#linux-flatpak) section for installation and usage.


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

## Configuration and Privacy

CheevoPresence does not expect you to keep secrets inside the repository.

- The repository-level `config.json` is ignored by Git
- Runtime configuration is stored under `%APPDATA%\CheevoPresence\config.json` on Windows
- Runtime configuration is stored under `~/Library/Application Support/CheevoPresence/config.json` on macOS
- Runtime configuration is stored under `~/.config/CheevoPresence/config.json` on Linux
- The API key is stored in a protected form on Windows and in the macOS Keychain on macOS rather than being written back as plain text in the repo. On Linux the API key is passed as a command-line argument.
- `config.example.json` exists only as a clean template



## Linux (Flatpak)

On Linux, CheevoPresence is distributed as a Flatpak bundle. This gives it a consistent environment across distributions and handles sandboxing and portal integration automatically.

### What to Expect

- On Linux, CheevoPresence runs as a CLI app rather than a GUI. There is no settings window or tray icon. You pass your credentials as command-line arguments and the app runs in the foreground, printing status to the terminal.
- Discord Rich Presence communicates over the Discord IPC socket. The Flatpak requests access to `/run/user/$UID/discord-ipc-*` sockets, which is how Discord exposes IPC on Linux.
- Self-update checks are disabled inside the Flatpak; updates come through the Flatpak bundle itself.

### Known Limitations

- Both native Discord and Flatpak Discord are supported. CheevoPresence automatically detects the IPC socket at `$XDG_RUNTIME_DIR/discord-ipc-0` (native) or `$XDG_RUNTIME_DIR/app/com.discordapp.Discord/discord-ipc-0` (Flatpak Discord). The browser version of Discord is not supported.
- The Flatpak uses the `org.freedesktop.Platform` runtime (version 24.08), so Python and all dependencies are bundled inside and do not rely on system packages.

### Installing the Flatpak

Download `io.github.denzi_gh.CheevoPresence.flatpak` from the releases page, then:

```bash
flatpak install --user io.github.denzi_gh.CheevoPresence.flatpak
flatpak run io.github.denzi_gh.CheevoPresence --username YOUR_RA_USERNAME --apikey YOUR_WEB_API_KEY
```

Your Web API key is available from your [RetroAchievements settings page](https://retroachievements.org/controlpanel.php).

To uninstall:

```bash
flatpak uninstall --user io.github.denzi_gh.CheevoPresence
```

### Building the Flatpak Yourself

The Flatpak is built using Docker (Fedora 41 base image with `flatpak-builder`). You need Docker installed and running.

From the repository root on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File build_flatpak.ps1
```

On subsequent runs, skip the Docker image rebuild with:

```powershell
powershell -ExecutionPolicy Bypass -File build_flatpak.ps1 -SkipImageBuild
```

The finished bundle is written to `dist/io.github.denzi_gh.CheevoPresence.flatpak`.

On Linux directly, run the inner build script after installing the prerequisites listed in `flatpak/Dockerfile.build`:

```bash
bash flatpak/build_inside_docker.sh
```

## Building the App Yourself

If you want to modify or package CheevoPresence yourself, use the platform-specific build guides:

- Windows: [`.github/buildWindows.md`](./.github/buildWindows.md)
- macOS: [`.github/buildMacOS.md`](./.github/buildMacOS.md)
- Linux: see the [Building the Flatpak Yourself](#building-the-flatpak-yourself) section above


## Support the Project

If CheevoPresence made your setup a little nicer and you feel like supporting the project, a small tip on [Ko-fi](https://ko-fi.com/denzi) would be genuinely appreciated.

Thanks for checking out CheevoPresence.
