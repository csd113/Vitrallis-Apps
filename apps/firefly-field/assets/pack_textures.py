#!/usr/bin/env python3
"""Repack shipped PNG previews; Pillow is an optional artwork-build tool only."""
from pathlib import Path
import zlib


def main():
    from PIL import Image
    root = Path(__file__).resolve().parent
    for name, size in (("meadow", (480, 272)), ("glow", (64, 64)),
                       ("firefly", (20, 14)), ("grass", (18, 42))):
        with Image.open(root / (name + ".png")) as image:
            if image.size != size:
                raise ValueError("Unexpected dimensions for " + name)
            pixels = image.convert("RGBA").tobytes()
        (root / (name + ".rgba.z")).write_bytes(zlib.compress(pixels, 9))


if __name__ == "__main__":
    main()
