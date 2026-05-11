#!/usr/bin/env python3
"""Generate pip-sources.json and requirements-flatpak-locked.txt.

Run this script from the repo root (or let build_inside_docker.sh call it)
whenever flatpak/requirements-flatpak.txt changes:

    python3 flatpak/generate_pip_sources.py

Requires (pre-installed inside the build Docker image):
    pip-tools           (provides pip-compile)
    flatpak-pip-generator

Both output files must be committed alongside the manifest:
    flatpak/pip-sources.json              – wheel download sources
    flatpak/requirements-flatpak-locked.txt – fully-pinned lock file
"""

import os
import subprocess
import sys


def _run(cmd, **kwargs):
    print(f"+ {' '.join(str(c) for c in cmd)}", flush=True)
    subprocess.run(cmd, check=True, **kwargs)


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    flatpak_dir = os.path.join(root, "flatpak")

    req_in = os.path.join(flatpak_dir, "requirements-flatpak.txt")
    req_locked = os.path.join(flatpak_dir, "requirements-flatpak-locked.txt")
    pip_sources = os.path.join(flatpak_dir, "pip-sources.json")

    # Step 1: pin all transitive deps with pip-compile
    print("\n=== Step 1: pin transitive deps with pip-compile ===")
    _run(
        [
            "pip-compile",
            "--no-header",
            "--no-annotate",
            "--output-file",
            req_locked,
            req_in,
        ]
    )

    # Step 2: generate wheel download sources for flatpak-builder
    print("\n=== Step 2: generate pip-sources.json with flatpak-pip-generator ===")
    _run(
        [
            "flatpak-pip-generator",
            "--python-version",
            "3.12",
            "--requirements-file",
            req_locked,
            "--output",
            pip_sources,
        ]
    )

    print(f"\nDone.\n  {req_locked}\n  {pip_sources}")


if __name__ == "__main__":
    main()

