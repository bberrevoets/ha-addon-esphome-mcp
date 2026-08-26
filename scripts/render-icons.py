#!/usr/bin/env python3
"""Rasterize the add-on presentation files (icon.svg / logo.svg -> PNG).

Home Assistant only reads ``icon.png`` (128x128) and ``logo.png`` (~250x100)
from the add-on folder; the SVGs are the editable sources. Re-run this after
changing either SVG and commit the resulting PNGs (plain git, *never* LFS —
the Supervisor clones with plain git and would receive an LFS pointer file).

Requires: ``pip install playwright pillow`` and ``playwright install chromium``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ADDON_DIR = Path(__file__).resolve().parents[1] / "esphome-mcp"
TARGETS = {
    "icon": (128, 128),
    "logo": (250, 100),
}
MAX_BYTES = 40_000

HTML = (
    "<!doctype html><html><head><style>"
    "html,body{{margin:0;padding:0;background:transparent;overflow:hidden}}"
    "svg{{display:block}}"
    "</style></head><body>{svg}</body></html>"
)


def render(name: str, size: tuple[int, int], browser) -> Path:
    width, height = size
    src = ADDON_DIR / f"{name}.svg"
    out = ADDON_DIR / f"{name}.png"
    page = browser.new_page(
        viewport={"width": width, "height": height}, device_scale_factor=1
    )
    page.set_content(HTML.format(svg=src.read_text(encoding="utf-8")))
    page.wait_for_timeout(100)  # let fonts settle
    page.screenshot(
        path=str(out),
        omit_background=True,
        clip={"x": 0, "y": 0, "width": width, "height": height},
    )
    page.close()
    return out


def verify(path: Path, size: tuple[int, int]) -> None:
    with Image.open(path) as img:
        if img.size != size:
            sys.exit(f"{path.name}: expected {size}, got {img.size}")
        if img.mode != "RGBA":
            sys.exit(f"{path.name}: expected RGBA, got {img.mode}")
        # Corners must be transparent (rounded tile on a transparent canvas).
        if img.getpixel((0, 0))[3] != 0:
            sys.exit(f"{path.name}: top-left corner is not transparent")
    nbytes = path.stat().st_size
    if nbytes > MAX_BYTES:
        sys.exit(f"{path.name}: {nbytes} bytes exceeds {MAX_BYTES}")
    print(f"{path.relative_to(ADDON_DIR.parent)}: {size[0]}x{size[1]} RGBA, {nbytes} bytes")


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for name, size in TARGETS.items():
                verify(render(name, size, browser), size)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
