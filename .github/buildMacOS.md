# Building CheevoPresence on macOS

This guide is for people who cloned the repository and want to build `CheevoPresence.app` themselves.

## Requirements

- macOS
- Xcode Command Line Tools
- Homebrew
- A Tk-capable Python 3.11 or 3.12

Install the usual macOS build dependencies first:

```bash
xcode-select --install
brew install python@3.12 python-tk@3.12 tcl-tk
```

## 1. Clone the repository

```bash
git clone https://github.com/denzi-gh/CheevoPresence.git
cd CheevoPresence
```

## 2. Run the build script

```bash
./build_macos.sh
```

That script will:

- Find a Tk-capable Python interpreter
- Create or reuse a build venv in `build/macos/venv`
- Install `requirements/macos.txt` plus PyInstaller into that venv
- Generate the `.icns` app icon and menu-bar template icon
- Build the `.app` bundle
- Apply final bundle plist changes
- Create the updater zip archive

## Build outputs

After a successful build you will get:

```text
dist/CheevoPresence.app
dist/CheevoPresence-macos-<architecture>.zip
```

The zip name carries the CPU architecture of the build machine (for example
`CheevoPresence-macos-arm64.zip` on Apple Silicon), so the self-updater can
tell which architecture a release asset was built for.

## 3. Run the build

```bash
open dist/CheevoPresence.app
```

## Choosing a specific Python interpreter

If `build_macos.sh` does not find the interpreter you want, point it at one explicitly:

```bash
CHEEVO_MACOS_PYTHON=/opt/homebrew/bin/python3.12 ./build_macos.sh
```

## Troubleshooting

- If the script says no Tk-capable Python was found, install the Homebrew packages above and try again.
- If `iconutil` is missing, make sure the Xcode Command Line Tools are installed.
- If the build venv gets into a bad state, remove `build/macos/venv` and rerun the script.
