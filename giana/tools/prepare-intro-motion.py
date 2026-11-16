#!/usr/bin/env python3
"""Build the first-platform choreography and original bonus-brick bitmap patches."""

import argparse
import hashlib
import json
from pathlib import Path


PART = Path(__file__).resolve().parents[1]
ASSETS = PART / "assets"
INPUT_HASHES = {
    "original-level1-map.bin": "e75d388d6b80e7ec82064fc6a9309c16dadedf34a73425b52e4712be1fe7c99c",
    "original-charset.bin": "eb453a70a5c3cdf177e19868cdb663b8e0182e90a4368d78b25edbbbe24ea668",
    "original-char-colors.bin": "74ccc485e71ad8505c1c30932f07f728624f822e9277fecb659f63209287966a",
    "peptoette-a.vpl": "4a762159d75af98b510d43b709c4a1243f85ad706e594cf4a24fee0165f7b6ed",
}
HIT_STEP, SPENT_STEP = 80, 81
BALL_FIRST, ELECTRIC_FIRST, END_STEP = 81, 93, 100
JUMP_FIRST = 78
JUMP_FEET = [28, 25, 24, 25, 27, 30]
BALL_X = [11, 12, 13, 14, 15, 16, 17, 16, 15, 14, 13, 12]
BALL_Y = [9, 7, 5, 5, 5, 5, 6, 8, 11, 14, 18, 23]
BALL_ROWS = [2, 4, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6]
FLASH_COLORS = [7, 1, 3, 1]
TV_ROW, TV_COLUMN, BITMAP = 3, 23, 0x2000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_verified(name):
    data = (ASSETS / name).read_bytes()
    assert digest(data) == INPUT_HASHES[name], f"Original input changed: {name}"
    return data


def byte_array(name, values):
    lines = [f"{name}:"]
    for offset in range(0, len(values), 16):
        lines.append("    .byte " + ",".join(f"${value:02x}" for value in values[offset:offset + 16]))
    return lines


def decode_level(original_map, charset, attributes, palette):
    colors = (8, 9, 14, 5, 7)
    quantize = [min(colors, key=lambda target: sum(
        (palette[color][channel] - palette[target][channel]) ** 2 for channel in range(3)))
        for color in range(16)]
    quantize[14] = 14
    codes = {9: 0, 14: 1, 8: 2}
    result = []
    for y in range(64):
        source_y = (2 * y + 1) * 160 // 128
        row = []
        for x in range(512):
            source_x = x * 4 + 2
            character = original_map[source_y // 8 * 256 + source_x // 8]
            bits = charset[character * 8 + source_y % 8]
            attribute = attributes[character]
            if attribute < 8:
                color = attribute if bits & (0x80 >> (source_x % 8)) else 14
            else:
                color = (14, 8, 9, attribute & 7)[bits >> (6 - 2 * ((source_x % 8) // 2)) & 3]
            row.append(codes.get(quantize[color], 3))
        result.append(row)
    return result


def project(pixels, camera, geometry):
    bounds = [column * 4 for column in geometry["perspective_columns"]]
    image = []
    for y in range(64):
        row = []
        for x in range(40):
            region = next(index for index in range(4) if bounds[index] <= x < bounds[index + 1])
            source_y = geometry["perspective_source_rows"][region][y]
            row.append(3 if source_y < 0 else pixels[source_y][(camera + x) % 512])
        image.append(row)
    return image


def scroll(image, original_pixels, camera, geometry):
    """Advance one real pixel, including the row transfer at each perspective seam."""
    bounds = [column * 4 for column in geometry["perspective_columns"]]
    result = [row[:] for row in image]
    for region in range(4):
        for y in range(64):
            source_y = geometry["perspective_transfer_rows"][region][y] if region < 3 else y
            if source_y < 0:
                continue
            for x in range(bounds[region], bounds[region + 1]):
                if x == 39:
                    result[y][x] = original_pixels[y][(camera + 40) % 512]
                elif x == bounds[region + 1] - 1:
                    result[y][x] = image[source_y][x + 1]
                else:
                    result[y][x] = image[y][x + 1]
    return result


def patch(before, after):
    records = []
    for y in range(64):
        for column in range(10):
            old = new = 0
            for pair in range(4):
                old = old << 2 | before[y][column * 4 + pair]
                new = new << 2 | after[y][column * 4 + pair]
            if old != new:
                address = BITMAP + ((TV_ROW + y // 8) * 40 + TV_COLUMN + column) * 8 + y % 8
                records.append({"address": address, "value": new, "previous_value": old,
                                "screen_byte_column": column, "projected_y": y})
    return records


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    original_map = read_verified("original-level1-map.bin")
    charset = read_verified("original-charset.bin")
    attributes = read_verified("original-char-colors.bin")
    palette = [tuple(int(value, 16) for value in line.split()[:3])
               for line in read_verified("peptoette-a.vpl").decode().splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    geometry = json.loads((ASSETS / "level1-import.json").read_text())
    pixels = decode_level(original_map, charset, attributes, palette)
    tiles = (ASSETS / "level1-tiles.bin").read_bytes()
    tile_map = (ASSETS / "level1-tv-map.bin").read_bytes()
    assert all(pixels[y][x] == (tiles[tile_map[y // 8 * 128 + x // 4] * 8 + y % 8]
                                >> (6 - 2 * (x % 4)) & 3)
               for y in range(64) for x in range(512)), "Original decode differs from accepted terrain"
    assert original_map[3 * 256 + 47] == 0xf2, "First original power-up brick moved"

    bumped = [row[:] for row in pixels]
    for y in range(9, 16):
        for x in range(92, 98):
            bumped[y][x] = pixels[y + 1][x] if y < 15 else 1
    used_map = bytearray(original_map)
    used_characters = ((0x4c, 0x4d, 0x4e), (0x4f, 0x50, 0x51))
    for row, characters in enumerate(used_characters, 3):
        used_map[row * 256 + 46:row * 256 + 49] = bytes(characters)
    spent = decode_level(used_map, charset, attributes, palette)

    normal80, normal81 = project(pixels, HIT_STEP, geometry), project(pixels, SPENT_STEP, geometry)
    assert scroll(normal80, pixels, HIT_STEP, geometry) == normal81, "Perspective scroll differs from source projection"
    bump80 = project(bumped, HIT_STEP, geometry)
    bump_patch = patch(normal80, bump80)
    post_scroll_bump = scroll(bump80, pixels, HIT_STEP, geometry)
    spent81 = project(spent, SPENT_STEP, geometry)
    spent_patch = patch(post_scroll_bump, spent81)
    assert bump_patch and spent_patch
    patch_bytes = 3 * (len(bump_patch) + len(spent_patch))
    assert patch_bytes <= 256, f"Block patch data needs {patch_bytes} bytes"

    support = json.loads((ASSETS / "sprites-import.json").read_text())["motion"]["support_kind_by_step"]
    poses = [6 if step >= ELECTRIC_FIRST else 4 if support[step] == 0 or JUMP_FIRST <= step < JUMP_FIRST + len(JUMP_FEET)
             else 2 * (step & 1) for step in range(END_STEP)]
    # This walking silhouette clears the first platform's rising edge while
    # retaining the accepted jump trajectory and its supported landing.
    poses[66] = 2
    arrays = {"introPose": poses, "introJumpFoot": JUMP_FEET, "introBallX": BALL_X,
              "introBallY": BALL_Y, "introBallRows": BALL_ROWS, "introFlashColor": FLASH_COLORS}
    constants = {"INTRO_HIT_STEP": HIT_STEP, "INTRO_SPENT_STEP": SPENT_STEP,
                 "INTRO_BALL_FIRST": BALL_FIRST, "INTRO_BALL_COUNT": len(BALL_X),
                 "INTRO_ELECTRIC_FIRST": ELECTRIC_FIRST, "INTRO_END_STEP": END_STEP,
                 "INTRO_JUMP_FIRST": JUMP_FIRST, "INTRO_JUMP_COUNT": len(JUMP_FEET)}
    motion_lines = ["// Camera-indexed first-platform animation; generated by tools/prepare-intro-motion.py."]
    motion_lines.extend(f".const {name} = {value}" for name, value in constants.items())
    motion_lines.append("introMotionData:")
    for name, values in arrays.items():
        motion_lines.extend(byte_array(name, values))
    motion_lines.extend(("introMotionDataEnd:", '.assert "Intro motion fits one free page", introMotionDataEnd - introMotionData <= $100, true', ""))
    (ASSETS / "intro-motion.asm").write_text("\n".join(motion_lines))

    block_lines = ["// Complete bitmap bytes preserve surrounding original art at both patch steps.",
                   "introBlockData:"]
    for stem, records in (("Bump", bump_patch), ("Spent", spent_patch)):
        block_lines.append(f".const INTRO_{stem.upper()}_PATCH_COUNT = {len(records)}")
        for suffix, values in (("AddressLow", [record["address"] & 255 for record in records]),
                               ("AddressHigh", [record["address"] >> 8 for record in records]),
                               ("Values", [record["value"] for record in records])):
            block_lines.extend(byte_array(f"intro{stem}{suffix}", values))
    block_lines.extend(("introBlockDataEnd:", '.assert "Intro block patches fit one free page", introBlockDataEnd - introBlockData <= $100, true', ""))
    (ASSETS / "intro-block.asm").write_text("\n".join(block_lines))

    metadata = {
        "format": "giana-level1-opening-motion-v1", "clock": "Recovered actor camera step; four PAL frames per sample",
        "player_screen_x_mc": 10, "first_platform_world_mc": [80, 116], "first_platform_top_y": 32,
        "player_screen_x_overrides_mc": {"64": 9, "65": 9, "66": 9, "79": 11, "80": 11, "81": 11},
        "player_screen_x_override_reason": "The left adjustment at steps64..66 clears the first platform in both held camera phases; the right adjustment at79..81 clears the adjacent hanging brick while striking the power-up block.",
        "pose_overrides": {"66": {"relative_pose": 2, "reason": "The small walking silhouette clears the first platform edge; the jump pose overlaps one opaque solid pixel."}},
        "first_bonus_brick_original_chars": {"columns": [46, 49], "rows": [3, 5], "center_character": 0xf2},
        "first_bonus_brick_reduced_mc": {"x": [92, 98], "y": [10, 16]},
        "spent_characters": used_characters, "constants": constants, "arrays": arrays,
        "small_height": 8, "electric_height": 10, "ball_height": 6,
        "ball_top_y_is_projected": True, "jump_feet_are_unprojected": True,
        "block_bump_camera": HIT_STEP, "spent_block_camera": SPENT_STEP,
        "bump_patch": bump_patch, "spent_patch": spent_patch,
        "motion_bytes": sum(len(values) for values in arrays.values()), "block_patch_bytes": patch_bytes,
        "source_sha256": INPUT_HASHES,
        "accepted_terrain_codes_checked": 32768,
        "patch_method": "Original first brick rises one reduced source row, then original used-brick characters replace it. The spent patch compares against the actual seam-aware scroll of the bumped frame, clearing every stale pixel while preserving adjacent art.",
        "output_sha256": {name: digest((ASSETS / name).read_bytes()) for name in ("intro-motion.asm", "intro-block.asm")},
    }
    (ASSETS / "intro-motion.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Intro motion: {metadata['motion_bytes']} bytes; block patches: {len(bump_patch)} + {len(spent_patch)} bytes ({patch_bytes} bytes including addresses).")


if __name__ == "__main__":
    main()
