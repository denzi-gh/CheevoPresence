"""Generate the macOS app icon and menu-bar template assets."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ICON = ROOT / ".github" / "assets" / "tray-default.png"
OUTPUT_DIR = ROOT / "build" / "macos" / "generated"
ICONSET_DIR = OUTPUT_DIR / "CheevoPresence.iconset"
ICNS_PATH = OUTPUT_DIR / "CheevoPresence.icns"
MENU_TEMPLATE_PATH = OUTPUT_DIR / "cheevoRP_menubar_template.png"

ICONSET_SIZES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def _load_source_image():
    if not SOURCE_ICON.exists():
        raise FileNotFoundError(f"Missing source icon: {SOURCE_ICON}")
    return Image.open(SOURCE_ICON).convert("RGBA")


def build_iconset(image):
    if ICONSET_DIR.exists():
        shutil.rmtree(ICONSET_DIR)
    ICONSET_DIR.mkdir(parents=True, exist_ok=True)

    for filename, size in ICONSET_SIZES.items():
        resized = image.resize((size, size), Image.LANCZOS)
        resized.save(ICONSET_DIR / filename)

    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(ICNS_PATH)],
        check=True,
    )


def _build_menu_trophy_mask(size):
    grid_size = 24
    pixel = size // grid_size

    mask = Image.new("L", (grid_size, grid_size), 0)
    draw = ImageDraw.Draw(mask)

    draw.rectangle((7, 3, 16, 4), fill=255)
    draw.rectangle((5, 5, 18, 6), fill=255)
    draw.rectangle((6, 7, 17, 10), fill=255)
    draw.rectangle((7, 11, 16, 11), fill=255)
    draw.rectangle((8, 12, 15, 12), fill=255)

    draw.rectangle((1, 5, 5, 9), fill=255)
    draw.rectangle((2, 6, 4, 8), fill=0)
    draw.rectangle((18, 5, 22, 9), fill=255)
    draw.rectangle((19, 6, 21, 8), fill=0)

    draw.rectangle((10, 13, 13, 16), fill=255)
    draw.rectangle((9, 17, 14, 18), fill=255)
    draw.rectangle((7, 19, 16, 20), fill=255)

    
    return mask.resize((pixel * grid_size, pixel * grid_size), Image.NEAREST).resize(
        (size, size),
        Image.LANCZOS,
    )


def build_menu_template(_image):
    alpha = _build_menu_trophy_mask(256).resize((64, 64), Image.LANCZOS)
    template = Image.new("RGBA", alpha.size, (0, 0, 0, 255))
    template.putalpha(alpha)
    template.save(MENU_TEMPLATE_PATH)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source = _load_source_image()
    build_iconset(source)
    build_menu_template(source)
    print(f"Generated {ICNS_PATH}")
    print(f"Generated {MENU_TEMPLATE_PATH}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - build helper
        print(exc, file=sys.stderr)
        raise
