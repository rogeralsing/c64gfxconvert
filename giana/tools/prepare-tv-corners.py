#!/usr/bin/env python3
"""Pack four small CRT corner masks as native 24x21 hires C64 sprites."""

import hashlib
import json
from pathlib import Path

from PIL import Image


PART = Path(__file__).resolve().parents[1]
ASSETS = PART / "assets"


def main():
    profile_bytes = (ASSETS / "tv-corners-profile.json").read_bytes()
    source = json.loads(profile_bytes)
    assert source["tv_size"] == [80, 64] and source["sprite_size"] == [24, 21]
    assert source["frame_order"] == ["top_left", "top_right", "bottom_left", "bottom_right"]
    assert len(source["outside_pixels_by_depth"]) == 8
    assert source["sprite_color"] == 0
    atlas = bytearray()
    expected_frames = []
    visible_mask = set()
    for index, corner in enumerate(source["frame_order"]):
        frame = bytearray(64)
        points = set()
        origin_x, origin_y = source["frame_origins"][index]
        for depth, width in enumerate(source["outside_pixels_by_depth"]):
            assert 0 <= width <= 8
            global_y = source["baseline_y"][index] + (depth if corner.startswith("top") else -depth)
            local_y = global_y - origin_y
            assert 0 <= local_y < 21
            columns = range(width) if corner.endswith("left") else range(24 - width, 24)
            for local_x in columns:
                frame[local_y * 3 + local_x // 8] |= 0x80 >> (local_x % 8)
                points.add((local_x, local_y))
                visible_mask.add((origin_x + local_x, global_y))
        assert frame[63] == 0
        for y in range(21):
            for x in range(24):
                assert bool(frame[y * 3 + x // 8] & (0x80 >> (x % 8))) == ((x, y) in points)
        expected_frames.append(points)
        atlas.extend(frame)
    assert len(atlas) == 256 and len(visible_mask) == 68
    (ASSETS / "tv-corners.bin").write_bytes(atlas)

    palette = [tuple(int(value, 16) for value in line.split()[:3])
               for line in (ASSETS / "peptoette-a.vpl").read_text().splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    preview = Image.new("RGB", (80, 64), palette[14])
    geometry = json.loads((ASSETS / "level1-import.json").read_text())
    for region, source_rows in enumerate(geometry["perspective_source_rows"]):
        left, right = (value * 8 for value in geometry["perspective_columns"][region:region + 2])
        for y, source_y in enumerate(source_rows):
            if source_y < 0:
                for x in range(left, right):
                    preview.putpixel((x, y), palette[0])
    for point in visible_mask:
        preview.putpixel(point, palette[0])
    preview.save(ASSETS / "tv-corners-preview.png")
    receipt = {
        "profile_sha256": hashlib.sha256(profile_bytes).hexdigest(),
        "frame_order": source["frame_order"],
        "tv_size": source["tv_size"], "sprite_size": source["sprite_size"],
        "outside_pixels_by_depth": source["outside_pixels_by_depth"],
        "frame_origins": source["frame_origins"], "baseline_y": source["baseline_y"],
        "frame_stride_bytes": 64, "atlas_bytes": len(atlas),
        "opaque_pixels_per_frame": [len(points) for points in expected_frames],
        "total_opaque_pixels": len(visible_mask),
        "sprite_color": source["sprite_color"], "multicolor": False,
        "bit_rule": "set bits outside rounded opening, transparent elsewhere",
        "decoded_pixels_verified": 4 * 24 * 21,
        "atlas_sha256": hashlib.sha256(atlas).hexdigest(),
    }
    (ASSETS / "tv-corners-import.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("TV corners: four 64-byte hires masks, 17 opaque black pixels per corner.")


if __name__ == "__main__":
    main()
