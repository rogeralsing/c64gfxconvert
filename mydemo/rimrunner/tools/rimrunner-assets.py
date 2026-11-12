#!/usr/bin/env python3
"""Unchanged palette and indexed-image helpers from asm/tools/rimrunner-assets.py."""

from PIL import Image


def load_palette(path):
    entries = []
    for line in path.read_text().splitlines():
        fields = line.split("#", 1)[0].split()
        if fields:
            entries.append(tuple(int(value, 16) for value in fields[:3]))
    if len(entries) != 16 or any(len(color) != 3 for color in entries):
        raise ValueError("Expected a VICE palette containing exactly 16 RGB colors.")
    return entries


def indexed_image(width, height, pixels, palette):
    image = Image.new("P", (width, height))
    image.putpalette([value for color in palette for value in color] + [0] * (768 - 48))
    image.putdata(pixels)
    return image
