#!/usr/bin/env python3
"""Reduce verified original C64 Stage 2 enemies and decode their spawn records.

The normal build is offline and uses only retained source slices. Optional
--program re-extracts those slices from the exact original disk file 1.
"""

import argparse
from collections import Counter
import hashlib
import json
from math import ceil
from pathlib import Path


PART = Path(__file__).resolve().parents[1]
ASSETS = PART / "assets"
PROGRAM_SHA256 = "0f1a720961fa52102fcfd52e46e40df07e5e307328ad087d55cc00506f904880"
INPUT_HASHES = {
    "original-level2-enemies-bee.bin": "a2c34ddf77cd07e43012d87cad47744ed4800df25a6c978fa1f0ae2d62cd9ebd",
    "original-level2-enemies-bee-right.bin": "31be654991c6c6b291e6d0bdf638bed5be0f602b51c1d8bf9db87e4e9db66a11",
    "original-level2-enemies-crab.bin": "8c59673f5994afc9d5b2aeeebbb96dfdbc33785fed46b3608d9eabeb926562dc",
    "original-level2-enemies-slinky.bin": "342ab3465ac4f1cd639b032eee7db8e5eb8fdcaa3f726ad5b78a3f87e7e4fcf0",
    "original-level2-enemies-spawns.bin": "96103e1b46bf536997a7871cca1570266099c97faf87252f351861ed4cfe8a04",
    "original-level2-enemies-descriptors.bin": "3f1429b36ee027126c65517f3a93037bd7db50c0b56d17dd1dcca8bc21bdc30d",
    "original-level2-enemies-y-table.bin": "cc541aa2465e4315a984ccceb9dfea8cbfc932f1891a4f58dc86a4b73626213c",
    "peptoette-a.vpl": "4a762159d75af98b510d43b709c4a1243f85ad706e594cf4a24fee0165f7b6ed",
}
MC0, MC1 = 10, 2
HEIGHT = 9
TYPES = (
    {"name": "bee", "type": 0, "color": 7, "frames": (0x66, 0x67),
     "global_first": 10, "left_first": 10, "left_count": 2, "right_first": 22, "right_count": 2},
    {"name": "crab", "type": 2, "color": 1, "height": 6, "frames": (0x71, 0x72, 0x74, 0x75),
     "global_first": 12, "left_first": 12, "left_count": 2, "right_first": 14, "right_count": 2},
    {"name": "slinky", "type": 7, "color": 5, "frames": (0x9a, 0x9b, 0x9c, 0x9f, 0xa0, 0xa1),
     "global_first": 16, "left_first": 16, "left_count": 3, "right_first": 19, "right_count": 3},
)
EXTRA_POSE_GROUPS = ({"name": "bee-right", "type": 0, "color": 7, "frames": (0x69, 0x6a),
                      "global_first": 22},)
POSE_GROUPS = (*TYPES, *EXTRA_POSE_GROUPS)
DESCRIPTOR_TYPES = (0, 2, 5, 7)
DESCRIPTOR_ADDRESSES = (0x306b, 0x308d, 0x30c0, 0x30e2)
SOURCE_SPANS = {
    "original-level2-enemies-spawns.bin": ((0x3d7a, 0x3d99),),
    "original-level2-enemies-descriptors.bin": tuple((a, a + 23) for a in DESCRIPTOR_ADDRESSES),
    "original-level2-enemies-y-table.bin": ((0x3205, 0x3221),),
    **{f"original-level2-enemies-{item['name']}.bin":
       tuple((0xc000 + frame * 64, 0xc000 + (frame + 1) * 64) for frame in item["frames"])
       for item in POSE_GROUPS},
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_verified(name):
    data = (ASSETS / name).read_bytes()
    if digest(data) != INPUT_HASHES[name]:
        raise ValueError(f"Original source changed: {name}")
    return data


def extract_sources(path):
    program = path.read_bytes()
    if digest(program) != PROGRAM_SHA256 or program[:2] != b"\x20\x08":
        raise ValueError("Expected the exact original game directory file 1")
    memory = bytearray(65536)
    memory[0x0820:0x0820 + len(program) - 2] = program[2:]
    assert int.from_bytes(memory[0x3d22:0x3d24], "little") == 0x3d7a
    for kind, address in zip(DESCRIPTOR_TYPES, DESCRIPTOR_ADDRESSES):
        assert int.from_bytes(memory[0x303b + kind * 2:0x303d + kind * 2], "little") == address
    for name, spans in SOURCE_SPANS.items():
        data = b"".join(memory[first:end] for first, end in spans)
        assert digest(data) == INPUT_HASHES[name]
        (ASSETS / name).write_bytes(data)


def decode_frame(raw, color):
    colors = (None, MC0, color, MC1)
    return [[colors[(raw[y * 3 + x // 8] >> (6 - 2 * ((x % 8) // 2))) & 3]
             for x in range(24)] for y in range(21)]


def reduce_frame(source, main_color, height=HEIGHT):
    """Area votes preserve original art; shorter crabs fit the reduced tunnels."""
    scale_y = 2.5 if height == HEIGHT else 21 / height
    result = []
    for y in range(height):
        row = []
        for x in range(6):
            votes = Counter()
            total = 0
            for source_y in range(int(y * scale_y), min(21, ceil((y + 1) * scale_y))):
                weight = max(0, min((y + 1) * scale_y, source_y + 1, 21) - max(y * scale_y, source_y))
                for source_x in range(x * 4, x * 4 + 4):
                    total += weight
                    color = source[source_y][source_x]
                    if color is not None:
                        votes[color] += weight
            row.append(max(votes, key=lambda color: (votes[color], color == main_color, color))
                       if total and sum(votes.values()) / total >= 0.5 else None)
        result.append(row)
    return result


def pack_frame(image, color):
    result = bytearray(64)
    codes = {None: 0, MC0: 1, color: 2, MC1: 3}
    for y, row in enumerate(image):
        for x, pixel in enumerate(row):
            result[y * 3 + x // 4] |= codes[pixel] << (6 - 2 * (x % 4))
    assert result[63] == 0 and not any(result[HEIGHT * 3:])
    decoded = decode_frame(result, color)
    assert all(decoded[y][x] == (image[y][x // 2] if y < len(image) and x < 12 else None)
               for y in range(21) for x in range(24))
    return bytes(result)


def bbox(image):
    points = [(x * 2, y) for y, row in enumerate(image) for x, color in enumerate(row) if color is not None]
    assert points
    return [min(x for x, y in points), min(y for x, y in points),
            max(x for x, y in points) + 2, max(y for x, y in points) + 1]


def decode_spawns():
    raw = read_verified("original-level2-enemies-spawns.bin")
    descriptors = read_verified("original-level2-enemies-descriptors.bin")
    rows = read_verified("original-level2-enemies-y-table.bin")
    assert len(raw) == 31 and raw[-1] == 0xff and len(descriptors) == 92
    properties = {}
    for index, kind in enumerate(DESCRIPTOR_TYPES):
        record = descriptors[index * 23:(index + 1) * 23]
        properties[kind] = {"source_address": DESCRIPTOR_ADDRESSES[index], "initial_sprite": record[0],
                            "sprite_mode_flags": record[1], "color": record[2], "movement_kind": record[3],
                            "right_frames": [record[4], record[5]], "left_frames": [record[6], record[7]],
                            "speed_source_pixels_per_tick": record[14], "animation_timer": record[15],
                            "support_mode": record[16], "initial_direction": "left"}
    enemies, pickups = [], []
    for index in range(10):
        column, row, kind = raw[index * 3:index * 3 + 3]
        record = {"source_entry_index": index, "source_address": 0x3d7a + index * 3,
                  "stored_column": column, "trigger_map_column": column - 1, "row_parameter": row,
                  "type": kind, "source_hardware_y": rows[row] + 29,
                  "source_top_y": rows[row] + 29 - 90}
        if kind == 11:
            pickups.append(record)
            continue
        assert kind in properties
        # Original X=335 is relative to the fine-scrolled character matrix.
        # At the canonical post-wrap fine phase 7, source X = 8*C - 16.
        record.update({"source_world_left_x_at_fine7": column * 8 - 16,
                       "world_left_x_mc": column * 2 - 4,
                       "scaled_top_y_numerator": record["source_top_y"] * 2,
                       "scaled_top_y_denominator": 5,
                       "scaled_top_y_floor": record["source_top_y"] * 2 // 5,
                       "scaled_canvas_bottom_y_ceil": ((record["source_top_y"] + 21) * 2 + 4) // 5,
                       "descriptor": properties[kind]})
        enemies.append(record)
    assert len(enemies) == 8 and len(pickups) == 2
    assert Counter(item["type"] for item in enemies) == {0: 1, 2: 2, 5: 1, 7: 4}
    return enemies, pickups, properties


def write_preview(frames, palette):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return
    image = Image.new("RGB", (6 * 128, len(POSE_GROUPS) * 180), (32, 32, 32))
    draw = ImageDraw.Draw(image)
    for row, item in enumerate(POSE_GROUPS):
        for column, (original, reduced) in enumerate(frames[item["name"]]):
            left, top = column * 128, row * 180
            draw.text((left + 2, top + 2), f"{item['name']} ${item['frames'][column]:02X}", fill="white")
            for y, pixels in enumerate(original):
                for x, color in enumerate(pixels):
                    if color is not None:
                        draw.rectangle((left + x * 4, top + 18 + y * 4,
                                        left + x * 4 + 3, top + 21 + y * 4), fill=palette[color])
            for y, pixels in enumerate(reduced):
                for x, color in enumerate(pixels):
                    if color is not None:
                        draw.rectangle((left + x * 16, top + 112 + y * 6,
                                        left + x * 16 + 15, top + 117 + y * 6), fill=palette[color])
    image.save(ASSETS / "level2-enemies-preview.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, help="Re-extract original enemy data from verified disk file 1")
    args = parser.parse_args()
    if args.program:
        extract_sources(args.program)
    palette = [tuple(int(value, 16) for value in line.split()[:3])
               for line in read_verified("peptoette-a.vpl").decode().splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    atlas = bytearray()
    frame_receipts = []
    preview = {}
    for item in POSE_GROUPS:
        source = read_verified(f"original-level2-enemies-{item['name']}.bin")
        assert len(source) == len(item["frames"]) * 64
        preview[item["name"]] = []
        for index, native_frame in enumerate(item["frames"]):
            original = decode_frame(source[index * 64:(index + 1) * 64], item["color"])
            reduced = reduce_frame(original, item["color"], item.get("height", HEIGHT))
            atlas.extend(pack_frame(reduced, item["color"]))
            preview[item["name"]].append((original, reduced))
            frame_receipts.append({"global_frame": item["global_first"] + index, "type": item["type"],
                                   "original_frame": native_frame, "original_address": 0xc000 + native_frame * 64,
                                   "color": item["color"], "canvas_height": len(reduced),
                                   "opaque_bbox_physical": bbox(reduced),
                                   "opaque_multicolor_pixels": sum(c is not None for row in reduced for c in row)})
    assert len(atlas) == 896
    enemies, pickups, properties = decode_spawns()
    (ASSETS / "level2-enemies.bin").write_bytes(atlas)
    assembly = ["// Generated by tools/prepare-enemies.py. Import at the caller's page-aligned PC.",
                ".const LEVEL2_ENEMY_FIRST_FRAME = 10", ".const LEVEL2_ENEMY_FRAME_COUNT = 14",
                ".const LEVEL2_ENEMY_CANVAS_HEIGHT = 9", ".const LEVEL2_ENEMY_WIDTH_MC = 6"]
    for item in TYPES:
        name = item["name"].upper()
        for key in ("color", "left_first", "left_count", "right_first", "right_count"):
            assembly.append(f".const LEVEL2_ENEMY_{name}_{key.upper()} = {item[key]}")
    assembly.extend(['.var level2EnemyFramesFile = LoadBinary("level2-enemies.bin")',
                     "extraEnemyFrames:", "    .fill level2EnemyFramesFile.getSize(), level2EnemyFramesFile.get(i)",
                     "extraEnemyFramesEnd:",
                     '.assert "Fourteen original enemy poses", extraEnemyFramesEnd - extraEnemyFrames, 896',
                     '.assert "Enemy frames are 64-byte aligned", extraEnemyFrames & $3f, 0', ""])
    (ASSETS / "enemies.asm").write_text("\n".join(assembly))
    receipt = {
        "original_program_sha256": PROGRAM_SHA256, "source_sha256": INPUT_HASHES,
        "source_spans": {name: list(spans) for name, spans in SOURCE_SPANS.items()},
        "stage_spawn_pointer_address": 0x3d22, "stage_spawn_pointer": 0x3d7a,
        "spawn_record_layout": "stored_column,row_parameter,type; ten triples followed by FF",
        "spawn_x_formula_source_pixels": "8*(map_column-39)+335-24-fine; map_column=stored_column-1",
        "spawn_canonical_fine_scroll": 7,
        "spawn_x_fine_scroll_note": "fine=7 selects the canonical post-wrap phase; other native phases offset X by up to 7 source pixels",
        "spawn_y_formula_source_pixels": "y_table[row]+29-90; y_table starts at $3205; map starts at screen row5",
        "source_sprite_multicolors": [10, 2], "output_multicolors": [10, 2],
        "output_sprite_geometry_physical": [24, 21], "output_visible_canvas_physical": [12, 9],
        "reduction": "Area vote four source X pixels; 2.5 source Y pixels normally, 3.5 for the six-row crabs; opacity >=50%; tie individual color then larger C64 index",
        "types": [{**item, "frames": list(item["frames"])} for item in TYPES],
        "extra_pose_groups": [{**item, "frames": list(item["frames"])} for item in EXTRA_POSE_GROUPS],
        "frames": frame_receipts, "enemies": enemies, "dynamic_pickups": pickups,
        "original_descriptors": properties,
        "native_movement": "All four types use movement kind0. Mode0 owl/crab/slinky probe terrain, fall4 source pixels when unsupported and turn at a wall; mode2 bee skips gravity. Horizontal speeds1 and2 source pixels per tick respectively. Slinky deformation is a three-pose walk cycle, not the native ballistic branch.",
        "owl_reuse": {"global_frames": [8, 9], "file": "sprites.bin", "color": 1},
        "atlas_bytes": len(atlas), "atlas_sha256": digest(atlas), "packed_pixels_verified": len(frame_receipts) * 24 * 21,
    }
    (ASSETS / "level2-enemies-import.json").write_text(json.dumps(receipt, indent=2) + "\n")
    write_preview(preview, palette)
    print(f"Stage2 original enemies: {len(frame_receipts)} poses, {len(atlas)} bytes, {len(enemies)} enemy records + {len(pickups)} dynamic pickups.")
    print(f"Atlas SHA-256: {digest(atlas)}")


if __name__ == "__main__":
    main()
