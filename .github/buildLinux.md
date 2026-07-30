# Building CheevoPresence on Linux

This guide is for people who cloned the repository and want to build the
`CheevoPresence` Linux executable themselves.

## Requirements

- A modern Linux desktop (X11 or Wayland with a system tray / AppIndicator host)
- Python 3.11 or 3.12 with Tk support
- The PyGObject stack: GObject Introspection, GTK 3, and an AppIndicator
  (Ayatana preferred, classic AppIndicator as a fallback)

These GTK bindings are provided by distro packages, not by `pip`, so install them
through your package manager first.

### Debian / Ubuntu

```bash
sudo apt install \
  python3 python3-venv python3-tk \
  python3-gi python3-gi-cairo \
  gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
```

### Fedora

```bash
sudo dnf install \
  python3 python3-tkinter \
  python3-gobject gtk3 \
  libayatana-appindicator-gtk3
```

## 1. Clone the repository

```bash
git clone https://github.com/denzi-gh/CheevoPresence.git
cd CheevoPresence
```

## 2. Run the build script

```bash
./build_linux.sh
```

That script will:

- Find a desktop-capable Python interpreter (it verifies that `tkinter`, GTK 3,
  and an AppIndicator binding all import)
- Create or reuse a build venv in `build/linux-venv` with `--system-site-packages`
  so the system PyGObject bindings are visible inside the venv
- Install `requirements/linux.txt` plus a pinned PyInstaller into that venv
  (cached by a dependency fingerprint, so reruns are fast)
- Run a one-file, windowed PyInstaller build
- Generate the launcher icon and a `.desktop` entry

## Build outputs

After a successful build you will get:

```text
dist/CheevoPresence
dist/CheevoPresence.png
dist/CheevoPresence.desktop
```

## 3. Run the build

```bash
./dist/CheevoPresence
```

Pass `--tray` to start directly in the tray without opening the Settings window:

```bash
./dist/CheevoPresence --tray
```

## The Settings window on Linux

Settings is an HTML page. A native window needs WebKit2GTK through pywebview, and
WebKit2GTK cannot be shipped inside the executable — it resolves its
`WebKitWebProcess` helper from a directory compiled in when the distro built it, so
it does not survive being relocated into a PyInstaller bundle.

So the packaged build serves the page on `127.0.0.1` and opens it in your default
browser. That needs no system packages and behaves the same on every distro,
including immutable ones. Closing the tab ends the settings session; the tray keeps
running either way.

Installing `webkit2gtk-4.1` does **not** give the packaged build a native window.
PyInstaller replaces `GI_TYPELIB_PATH` with the bundle's own directory, so system
GObject typelibs are invisible to the frozen executable. You get a native window only
when running from a source checkout on a machine that has both `python3-gi` and
WebKit2GTK:

```bash
# Arch          sudo pacman -S webkit2gtk-4.1
# Debian/Ubuntu sudo apt install gir1.2-webkit2-4.1
# Fedora        sudo dnf install webkit2gtk4.1
python3 launch_linux.py
```

Set `CHEEVO_SETTINGS_UI=browser` to force the browser path even when a native
backend is available — useful when reproducing a report. This will be changed in the future, the Linux Release needs serious refactoring..

## Choosing a specific Python interpreter

If `build_linux.sh` does not pick the interpreter you want, point it at one explicitly:

```bash
CHEEVO_LINUX_PYTHON=/usr/bin/python3.12 ./build_linux.sh
```

## Troubleshooting

- If the script says no desktop-capable Python was found, install the distro
  packages listed above and try again — the interpreter must be able to import
  `tkinter`, `gi` (GTK 3), and an AppIndicator binding.
- The PyGObject bindings come from the system, so the build venv must keep
  `--system-site-packages` (the script handles this). Installing GTK via `pip`
  is not supported.
- If the build venv gets into a bad state, remove `build/linux-venv` and rerun
  the script.
