#!/usr/bin/env python3
"""Prepare captured Rimrunner world data and original mounted running poses.

The eight poses follow the original mounted renderer, including its independent
AC/AD body animation and the A8 straight-running rider pose. They are not made
by moving the separate dismounted rider beside the animal.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from PIL import Image


WORLD_REGIONS = [(0, 36, 2, 0, 14, 6), (36, 127, 0, 0, 14, 3),
                 (127, 147, 1, 4, 14, 11), (147, 165, 1, 11, 14, 11),
                 (165, 200, 1, 11, 0, 3)]
TILE_OFFSETS = [(24, 0), (48, 0), (24, 21), (48, 21),
                (0, 42), (24, 42), (48, 42), (0, 0)]
LEG_BASES = [0x80, 0x85, 0x8a, 0x8f, 0x94, 0x99, 0x9e, 0xa3]
BODY_POINTERS = [0xad, 0xad, 0xac, 0xac, 0xad, 0xad, 0xac, 0xac]
RIDER_TOP_Y = [8, 8, 7, 7, 8, 8, 7, 7]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_sized(path, size):
    data = path.read_bytes()
    if len(data) != size:
        raise ValueError(f"Expected {size} bytes: {path}")
    return data


def composite_sprite(canvas, ram, pointer, x, y):
    address = 0x4000 + pointer * 64
    data = ram[address:address + 63]
    for row in range(21):
        bits = int.from_bytes(data[row * 3:row * 3 + 3], "big")
        for column in range(12):
            value = (bits >> (22 - column * 2)) & 3
            if value:
                target = (y + row) * 72 + x + column * 2
                canvas[target:target + 2] = bytes((value, value))


def pack_tile(canvas, x, y):
    result = bytearray()
    for row in range(21):
        for byte_column in range(3):
            packed = 0
            for pair in range(4):
                source_x = x + byte_column * 8 + pair * 2
                first = canvas[(y + row) * 72 + source_x]
                second = canvas[(y + row) * 72 + source_x + 1]
                if first != second or first > 3:
                    raise ValueError("Mounted pose does not retain multicolor pixel pairs.")
                packed = (packed << 2) | first
            result.append(packed)
    return bytes(result) + b"\0"


def mounted_image(canvas, palette):
    pixels = [(0, 0, 0, 0) if code == 0 else (*palette[[0, 0, 5, 13][code]], 255)
              for code in canvas]
    image = Image.new("RGBA", (72, 63))
    image.putdata(pixels)
    return image


def prepare(captures, source_ram, output):
    captures, source_ram, output = captures.resolve(), source_ram.resolve(), output.resolve()
    source_paths = [captures / "raster-00/ram.bin", captures / "raster-04/ram.bin",
                    captures / "raster-07/ram.bin", captures / "raster-00/color.bin", source_ram]
    far_ram = read_sized(source_paths[0], 65536)
    near_ram = read_sized(source_paths[1], 65536)
    hud_ram = read_sized(source_paths[2], 65536)
    colors = bytes(value & 15 for value in read_sized(source_paths[3], 1024)[:1000])
    rider_ram = read_sized(source_ram, 65536)
    charsets = [far_ram[0x4800:0x5000], near_ram[0x5000:0x5800], hud_ram[0x4000:0x4800]]
    screen = far_ram[0x4000:0x43e8]
    for row in range(5, 25):
        if len(set(colors[row * 40:(row + 1) * 40])) != 1:
            raise ValueError(f"World row {row} needs Color RAM scrolling; runtime expects uniform rows.")

    module_path = Path(__file__).with_name("rimrunner-assets.py")
    spec = importlib.util.spec_from_file_location("rimrunner_assets", module_path)
    decoder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(decoder)
    palette_path = Path(__file__).resolve().parents[2] / "palettes/colodore.vpl"
    palette = decoder.load_palette(palette_path)

    world_pixels = []
    for y in range(200):
        _, _, charset_id, background, mc1, mc2 = next(region for region in WORLD_REGIONS
                                                    if region[0] <= y < region[1])
        for column in range(40):
            cell = y // 8 * 40 + column
            value = charsets[charset_id][screen[cell] * 8 + y % 8]
            local = colors[cell]
            if local & 8:
                indices = [background, mc1, mc2, local & 7]
                for shift in (6, 4, 2, 0):
                    color = indices[(value >> shift) & 3]
                    world_pixels.extend((color, color))
            else:
                world_pixels.extend(local if value & (0x80 >> x) else background for x in range(8))
    world_image = decoder.indexed_image(320, 200, world_pixels, palette)

    frames, source_frames, packed_frames, frame_records = [], [], bytearray(), []
    for frame, (base, body_pointer, rider_y) in enumerate(zip(LEG_BASES, BODY_POINTERS, RIDER_TOP_Y)):
        canvas = bytearray(72 * 63)
        parts = [(base, 0, 0), (base + 1, 0, 21), (base + 2, 0, 42),
                 (base + 3, 24, 42), (base + 4, 48, 42), (body_pointer, 24, 21),
                 (0xa8, 24, rider_y), (0xab, 24, rider_y + 21)]
        for pointer, x, y in parts:
            composite_sprite(canvas, rider_ram, pointer, x, y)
        source_frames.append(mounted_image(canvas, palette))
        source_composite_sha256 = digest(bytes(canvas))
        canvas = bytearray(value for y in range(63) for value in canvas[y * 72:(y + 1) * 72][::-1])
        if any(canvas[y * 72 + x] for y in range(42) for x in range(24)):
            raise ValueError("Mounted pose needs more than the agreed seven hardware sprite tiles.")
        tiles = [pack_tile(canvas, x, y) for x, y in TILE_OFFSETS[:7]] + [bytes(64)]
        packed_frames.extend(b"".join(tiles))
        frames.append(mounted_image(canvas, palette))
        frame_records.append({"frame": frame, "leg_base_pointer": f"${base:02x}",
                              "body_pointer": f"${body_pointer:02x}",
                              "rider_top_pointer": "$a8", "rider_bottom_pointer": "$ab",
                              "rider_top_y": rider_y, "rider_bottom_y": rider_y + 21,
                              "source_composite_sha256": source_composite_sha256,
                              "source_png": f"mounted-source-pose-{frame}.png",
                              "source_parts_in_paint_order": [
                                  {"pointer": f"${pointer:02x}", "address": f"${0x4000 + pointer * 64:04x}",
                                   "x": x, "y": y} for pointer, x, y in parts],
                              "sha256": digest(b"".join(tiles))})

    binaries = {f"charset-{index}.bin": data for index, data in enumerate(charsets)}
    binaries.update({"screen.bin": screen, "color.bin": colors,
                     "mounted-frames.bin": bytes(packed_frames),
                     "mounted-offsets.bin": bytes(value for offset in TILE_OFFSETS for value in offset)})
    if len(packed_frames) != 4096:
        raise ValueError("Expected eight poses of eight 64-byte hardware sprite tiles.")
    protected = {path.resolve() for path in source_paths}
    if any((output / name).resolve() in protected for name in binaries):
        raise ValueError("Prepared assets must not overwrite capture inputs.")

    output.mkdir(parents=True, exist_ok=True)
    for name, data in binaries.items():
        (output / name).write_bytes(data)
    world_image.save(output / "world-preview.png")
    atlas = Image.new("RGBA", (4 * 80, 2 * 71), (0, 0, 0, 0))
    source_atlas = Image.new("RGBA", (4 * 80, 2 * 71), (0, 0, 0, 0))
    for frame, image in enumerate(frames):
        image.save(output / f"mounted-pose-{frame}.png")
        atlas.paste(image, ((frame % 4) * 80 + 4, (frame // 4) * 71 + 4))
        source_frames[frame].save(output / f"mounted-source-pose-{frame}.png")
        source_atlas.paste(source_frames[frame], ((frame % 4) * 80 + 4, (frame // 4) * 71 + 4))
    atlas.save(output / "mounted-poses.png")
    source_atlas.save(output / "mounted-source-poses.png")
    manifest = {
        "format": "Rimrunner native parallax prepared assets v1",
        "source_captures": str(captures), "source_rider_ram": str(source_ram),
        "inputs": {str(path): {"bytes": path.stat().st_size, "sha256": digest(path.read_bytes())}
                   for path in dict.fromkeys(source_paths)},
        "world": {"columns": 40, "rows": 25, "repeat_width_hires_pixels": 320,
                  "charset_source_addresses": ["$4800", "$5000", "$4000"],
                  "screen_source_address": "$4000", "uniform_color_rows": list(range(5, 25)),
                  "raster_regions": [
                      {"first_y": first, "end_y": end, "charset": charset,
                       "background": bg, "multicolor_1": mc1, "multicolor_2": mc2}
                      for first, end, charset, bg, mc1, mc2 in WORLD_REGIONS]},
        "mounted": {"width": 72, "height": 63, "frames": frame_records,
                    "slots_per_frame": 8, "bytes_per_slot": 64, "bytes_per_frame": 512,
                    "enabled_sprite_mask": "$7f", "multicolor_sprite_mask": "$7f",
                    "tile_offsets": TILE_OFFSETS, "palette_indices": [None, 0, 5, 13],
                    "mirrored_for_travel_direction": True,
                    "travel_direction": "right; world scrolls left",
                    "sequence": "Canonical straight-running loop from original $8c20-$8cd2 renderer",
                    "seed": {"leg_base_before_first_advance": "$a3", "body_pointer": "$ac", "body_count": 0},
                    "renderer_sha256": digest(rider_ram[0x8c20:0x8cd3]),
                    "rider_priority": "Rider A8 and AB paint over animal parts; opaque black is retained"},
        "outputs": {name: {"bytes": len(data), "sha256": digest(data)} for name, data in binaries.items()},
        "limitations": [
            "The world repeats one captured 40-column viewport; it is not the complete recovered level map.",
            "Original raster palette and charset cuts are preserved as metadata; the runtime must apply them.",
            "Running poses use a canonical original-renderer phase, not an observed initial animation phase.",
            "The rider uses the straight-running A8 pose; aim/fire-specific A9 and AA poses are not included.",
            "Prepared original game graphics carry no new reuse or redistribution license.",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output), "world_columns": 40, "mounted_frames": 8,
                      "mounted_tiles": 7, "mounted_frame_bytes": 512}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-captures", type=Path, required=True)
    parser.add_argument("--source-ram", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.world_captures, args.source_ram, args.output)
