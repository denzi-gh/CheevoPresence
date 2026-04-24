# Building CheevoPresence for Linux

This guide covers building CheevoPresence for Linux in three formats:
- **Tarball** (portable, self-extracting archive)
- **AppImage** (single-file portable executable)
- **DEB** (Debian/Ubuntu package)

## Prerequisites

### For End Users (Running from Release)

If you download a pre-built release (tarball or AppImage):

- **Python 3.10+** must be installed on your system.
- **GTK3** and **AppIndicator3** libraries are required for the system tray icon.

On Debian/Ubuntu:
```bash
sudo apt update
sudo apt install python3 python3-tk libgtk-3-0 libappindicator3-1 gir1.2-appindicator3-0.1
```

On Fedora:
```bash
sudo dnf install python3 python3-tkinter gtk3 libappindicator-gtk3
```

On Arch/Manjaro:
```bash
sudo pacman -S python tk gtk3 libappindicator-gtk3
```

> The DEB package will pull in these dependencies automatically via `apt`.

### For Developers (Building from Source)

- Python 3.10+ with `pip` and `venv`
- `bash`
- For DEB: `dpkg-deb`
- For AppImage: `appimagetool` (optional)

## Quick Build

```bash
# Build all formats
./build_linux.sh all

# Or build individually
./build_linux.sh tarball
./build_linux.sh appimage
./build_linux.sh deb
```

Outputs go to `dist/linux/`.

## Run from Source

If you prefer not to build:

```bash
pip install -r requirements.txt
python launch_linux.py
```

## System Tray Support

The app uses `pystray` with GTK3/AppIndicator backends.

| Desktop Environment | Tray Support |
|---|---|
| KDE Plasma | Native |
| XFCE | Native |
| GNOME | Requires tray icon extension (e.g., AppIndicator Support) |
| Cinnamon, MATE | Native |

## Discord / Vesktop

- **Discord**: Works out of the box.
- **Vesktop**: Make sure **arRPC** is enabled in Vesktop settings so the Discord IPC socket is available.

## Configuration

Config is stored at `~/.config/CheevoPresence/config.json` following the XDG Base Directory specification.

The API key is stored securely using the system keyring (GNOME Keyring, KDE Wallet, or any Secret Service implementation). If no keyring is available, it falls back to base64 encoding.

## Autostart

The app creates a `.desktop` file at `~/.config/autostart/CheevoPresence.desktop` when "Launch on system startup" is enabled in Settings.
