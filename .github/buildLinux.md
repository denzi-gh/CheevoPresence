# Building CheevoPresence on Linux

This guide covers two ways to build CheevoPresence on Linux: a **Flatpak bundle** (recommended for distribution) or running **directly from source**.

## Option A — Flatpak bundle (via Docker)

The Flatpak build runs entirely inside Docker, so no Flatpak toolchain needs to be installed on the host.

### Requirements

- Linux (or Windows with Docker Desktop)
- Docker with the `privileged` capability available
- PowerShell (`pwsh`) **or** the ability to run the Docker commands manually

### 1. Clone the repository

```bash
git clone https://github.com/denzi-gh/CheevoPresence.git
cd CheevoPresence
```

### 2. Run the build script

```powershell
./build_flatpak.ps1
```

On the first run this downloads roughly 2 GB of Flatpak runtimes into a Docker volume (`cheevopresence-flatpak-state`). Subsequent runs reuse that volume.

To skip rebuilding the Docker image when only the source has changed:

```powershell
./build_flatpak.ps1 -SkipImageBuild
```

### Build output

```text
dist/io.github.denzi_gh.CheevoPresence.flatpak
```

### 3. Install and run

```bash
flatpak install dist/io.github.denzi_gh.CheevoPresence.flatpak
flatpak run io.github.denzi_gh.CheevoPresence
```

---

## Option B — Run from source (no Flatpak)

### Requirements

- Python 3.11 or 3.12 on `PATH`
- `pip`
- System package `python3-gi` (PyGObject) for autostart and notification support

Install the system dependency on Debian/Ubuntu:

```bash
sudo apt install python3-gi
```

On Fedora/RHEL:

```bash
sudo dnf install python3-gobject
```

### 1. Clone the repository

```bash
git clone https://github.com/denzi-gh/CheevoPresence.git
cd CheevoPresence
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements/linux.txt
```

### 4. Run

```bash
python launch_linux.py
```

---

## Troubleshooting

- If `python3` is not found, install it via your distribution's package manager (`apt`, `dnf`, `pacman`, etc.).
- If the Docker build fails with a permissions error, ensure your user is in the `docker` group or prefix the command with `sudo`.
- If notifications or autostart do not work, make sure `python3-gi` (PyGObject) is installed as a system package — it is not available via pip.
- If the Flatpak runtimes fail to download, check that the privileged Docker container can reach the internet.
