#!/usr/bin/env python3
"""Pack editable native glass-shine art into one 24x21 hires C64 sprite."""

import hashlib
import json
from pathlib import Path

from PIL import Image


ASSETS = Path(__file__).resolve().parents[1] / "assets"
ORIGINAL_REFERENCE_SHA256 = "48361b03d5c4eaf9aab57ed7f21d0695a83359c21a6fc9fb88d52ccc7cd6a946"


def main():
    source_path = ASSETS / "tv-highlight-mask.json"
    source_bytes = source_path.read_bytes()
    art = json.loads(source_bytes)
    rows = art["rows"]
    assert art["size"] == [24, 21] and art["runtime_color"] == 3
    assert len(rows) == 21 and all(len(row) == 24 and set(row) <= {".", "#"} for row in rows)
    palette = [tuple(int(value, 16) for value in line.split()[:3])
               for line in (ASSETS / "peptoette-a.vpl").read_text().splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    corners = json.loads((ASSETS / "tv-corners-profile.json").read_text())
    sprite = bytearray(64)
    logical = Image.new("RGBA", (24, 21), (0, 0, 0, 0))
    lit_pixels = 0
    for y, row in enumerate(rows):
        for x, pixel in enumerate(row):
            if pixel == ".":
                continue
            # Highlight origin is TV-local (0,3), inside the rounded TL opening.
            depth = y + 3 - corners["baseline_y"][0]
            outside_width = corners["outside_pixels_by_depth"][depth] if 0 <= depth < 8 else 0
            assert x >= outside_width, (x, y)
            sprite[y * 3 + x // 8] |= 0x80 >> (x % 8)
            logical.putpixel((x, y), (*palette[3], 255))
            lit_pixels += 1
    for y, row in enumerate(rows):
        for x, pixel in enumerate(row):
            assert bool(sprite[y * 3 + x // 8] & (0x80 >> (x % 8))) == (pixel == "#")
    assert sprite[63] == 0
    (ASSETS / "tv-highlight.bin").write_bytes(sprite)
    logical.save(ASSETS / "tv-highlight-preview.png")
    receipt = {
        "source_mask_file": source_path.name,
        "source_mask_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "original_reference_png_sha256": ORIGINAL_REFERENCE_SHA256,
        "native_dimensions": [24, 21],
        "design": art["design"],
        "format": "C64 hires sprite: 24x21 bits, 3 bytes/row, byte63 zero padding",
        "set_bit": "cyan3 opaque glass shine", "clear_bit": "transparent",
        "runtime_color": 3, "tv_local_origin": [0, 3],
        "bytes": len(sprite), "lit_pixels": lit_pixels,
        "decoded_pixels_verified": 504, "rounded_corner_overlap_pixels": 0,
        "sprite_sha256": hashlib.sha256(sprite).hexdigest(),
    }
    (ASSETS / "tv-highlight-import.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"TV shine: native 24x21 curved dither, {lit_pixels} cyan pixels, 64 bytes.")


if __name__ == "__main__":
    main()
