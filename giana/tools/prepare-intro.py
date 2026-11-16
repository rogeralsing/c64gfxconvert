#!/usr/bin/env python3
"""Prepare original small Giana, electric transformation, and beach-ball art.

An ordinary build reads retained verified source slices. --program can repeat
their extraction from the unchanged original disk directory file 1.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


PART = Path(__file__).resolve().parents[1]
ASSETS = PART / "assets"
PROGRAM_SHA256 = "0f1a720961fa52102fcfd52e46e40df07e5e307328ad087d55cc00506f904880"
SOURCE_SLICES = {
    "original-intro-small-walk.bin": {
        "spans": ((0xA080, 0xA380),),
        "sha256": "169267a5a7cecd5132dd4c509a8c462bbe558208e927d278bdf8a479e1526833",
    },
    "original-intro-small-jump.bin": {
        "spans": ((0xA680, 0xA740),),
        "sha256": "192d22864c0dd217bfbf8cb801e501c5e5beb25518285a743f805c348dd726b3",
    },
    "original-intro-electric.bin": {
        "spans": ((0xD740, 0xD800),),
        "sha256": "46e6c9cc8c90f92d2a933f7fe9d5d6915a958bb020c038fabbab4ea7aabf3066",
    },
    "original-intro-ball.bin": {
        "spans": ((0xEE40, 0xEE80), (0xF000, 0xF040)),
        "sha256": "0832cc04daeff9213d23124e9ec3bcc5a3f442ccd61e9ed528ad85de5377d00d",
    },
}
SPEC = importlib.util.spec_from_file_location("giana_sprite_helpers", PART / "tools/prepare-sprites.py")
SPRITES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SPRITES)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def extract(program_path):
    program = program_path.read_bytes()
    if len(program) != 63443 or digest(program) != PROGRAM_SHA256:
        raise ValueError("Expected the verified original Giana disk directory file 1")
    assert program[:2] == b"\x20\x08"
    memory = bytearray(65536)
    memory[0x0820:0x0820 + len(program) - 2] = program[2:]
    assert memory[0xA083] == 3 and memory[0xCC03] != 3
    assert memory[0x3D64:0x3D67] == bytes((48, 10, 11))
    for name, item in SOURCE_SLICES.items():
        data = b"".join(memory[first:end] for first, end in item["spans"])
        assert digest(data) == item["sha256"], name
        (ASSETS / name).write_bytes(data)


def read_sources():
    result = {}
    for name, item in SOURCE_SLICES.items():
        data = (ASSETS / name).read_bytes()
        assert len(data) == sum(end - first for first, end in item["spans"]), name
        assert digest(data) == item["sha256"], name
        result[name] = data
    return result


def electric_composite(data):
    """The original fixed transform triplet uses three hires layers."""
    image = [[None] * 24 for _ in range(23)]
    for layer in (2, 1, 0):
        frame = data[layer * 64:(layer + 1) * 64]
        for y in range(21):
            for x in range(24):
                if frame[y * 3 + x // 8] & (0x80 >> (x % 8)):
                    image[y + layer][x] = (7, 1, 7)[layer]
    return image


def preview(originals, reduced, names, palette):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (len(names) * 160, 230), (32, 32, 32))
    draw = ImageDraw.Draw(image)
    for index, (name, source, tiny) in enumerate(zip(names, originals, reduced)):
        left = index * 160
        draw.text((left + 4, 4), name, fill="white")
        for y, row in enumerate(source):
            for x, color in enumerate(row):
                if color is not None:
                    draw.rectangle((left + 16 + x * 4, 25 + y * 4,
                                    left + 19 + x * 4, 28 + y * 4), fill=palette[color])
        for y, row in enumerate(tiny):
            for x, color in enumerate(row):
                if color is not None:
                    draw.rectangle((left + 16 + x * 16, 140 + y * 8,
                                    left + 31 + x * 16, 147 + y * 8), fill=palette[color])
    image.save(ASSETS / "intro-sprites-preview.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, help="Repeat extraction from the exact original file 1 PRG")
    args = parser.parse_args()
    if args.program:
        extract(args.program)
    source = read_sources()
    palette_raw = (ASSETS / "peptoette-a.vpl").read_bytes()
    assert digest(palette_raw) == SPRITES.PALETTE_SHA256
    palette = [tuple(int(value, 16) for value in line.split()[:3])
               for line in palette_raw.decode().splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    walk = source["original-intro-small-walk.bin"]
    originals = [SPRITES.giana_frame(walk, pose) for pose in (0, 2)]
    originals.append(SPRITES.giana_frame(source["original-intro-small-jump.bin"], 0))
    originals.append(electric_composite(source["original-intro-electric.bin"]))
    ball = source["original-intro-ball.bin"]
    originals.extend(SPRITES.multicolor_frame(ball[pose * 64:(pose + 1) * 64], 7)
                     for pose in range(2))
    reduced = [SPRITES.reduce_frame(image, 7, 0.2, palette, (10, 7, 6, 2), (23, 8))
               for image in originals[:3]]
    reduced.append(SPRITES.reduce_frame(originals[3], 7, 0.2, palette, (7, 1), (23, 10)))
    # Discard only the five transparent source padding rows before reducing the
    # complete sixteen-row beach ball to a six-row canvas.
    assert all(pixel is None for image in originals[4:] for row in image[:5] for pixel in row)
    reduced.extend(SPRITES.reduce_frame(image[5:], 7, 0.5, palette, (10, 7, 2), (16, 6))
                   for image in originals[4:])
    names = ["Small walk 0", "Small walk 2", "Small jump", "Electric", "Beach ball 0", "Beach ball 1"]
    plane_images = []
    for image in reduced[:3]:
        plane_images.append([[None if color == 6 else color for color in row] for row in image])
        plane_images.append([[6 if color == 6 else None for color in row] for row in image])
    plane_images.append([[7 if color == 7 else None for color in row] for row in reduced[3]])
    plane_images.append([[1 if color == 1 else None for color in row] for row in reduced[3]])
    plane_images.extend(reduced[4:])
    colors = [7, 6, 7, 6, 7, 6, 7, 1, 7, 7]
    heights = [8, 8, 8, 8, 8, 8, 10, 10, 6, 6]
    frames = [SPRITES.pack_frame(image, color) for image, color in zip(plane_images, colors)]
    assert len(frames) == 10 and len(set(frames)) == 10
    for index, (frame, image, color, height) in enumerate(zip(frames, plane_images, colors, heights)):
        assert len(frame) == 64 and frame[63] == 0 and not any(frame[height * 3:]), index
        decoded = SPRITES.multicolor_frame(frame, color)
        assert all(decoded[y][x] == (image[y][x // 2] if y < height and x < 12 else None)
                   for y in range(21) for x in range(24)), index
    for index, image in enumerate(reduced[:4]):
        a = SPRITES.multicolor_frame(frames[index * 2], colors[index * 2])
        b = SPRITES.multicolor_frame(frames[index * 2 + 1], colors[index * 2 + 1])
        assert all((a[y][x] if a[y][x] is not None else b[y][x]) == image[y][x // 2]
                   for y in range(len(image)) for x in range(12))
    assert all(any(color == 6 for row in image for color in row) for image in reduced[:3])
    assert all(any(color == target for row in image for color in row)
               for image in reduced[4:] for target in (7, 10, 2))
    atlas = b"".join(frames)
    assert len(atlas) == 640
    (ASSETS / "intro-sprites.bin").write_bytes(atlas)
    assembly = [
        "// Original Giana intro art, reduced by tools/prepare-intro.py.",
        "// CPU source atlas; import at the caller's 64-byte-aligned address.",
        ".const INTRO_SMALL_WALK_0 = 0", ".const INTRO_SMALL_WALK_1 = 2",
        ".const INTRO_SMALL_JUMP = 4", ".const INTRO_ELECTRIC = 6",
        ".const INTRO_BALL_0 = 8", ".const INTRO_BALL_1 = 9",
        ".const INTRO_SMALL_HEIGHT = 8", ".const INTRO_ELECTRIC_HEIGHT = 10",
        ".const INTRO_BALL_HEIGHT = 6", ".const INTRO_WIDTH_MC = 6",
        ".const INTRO_PLANE_COUNT = 10", ".const INTRO_SPRITE_BYTES = 640",
        ".var INTRO_PLANE_COLORS = List().add(" + ",".join(map(str, colors)) + ")",
        ".var INTRO_PLANE_HEIGHTS = List().add(" + ",".join(map(str, heights)) + ")",
        '.var introSpriteFile = LoadBinary("intro-sprites.bin")',
        "introSpriteFrames:", "    .fill introSpriteFile.getSize(), introSpriteFile.get(i)",
        "introSpriteFramesEnd:",
        '.assert "Ten 64-byte intro planes", introSpriteFramesEnd - introSpriteFrames, INTRO_SPRITE_BYTES',
        '.assert "Intro atlas is 64-byte aligned", introSpriteFrames & $3f, 0', "",
    ]
    (ASSETS / "intro-sprites.asm").write_text("\n".join(assembly))
    receipt = {
        "original_program_sha256": PROGRAM_SHA256,
        "source_slices": SOURCE_SLICES,
        "source_normal_sprite_set": [0xA080, 0xAA80],
        "source_punk_sprite_set": [0xCC00, 0xD600],
        "source_normal_set_marker_address": 0xA083, "source_normal_set_marker_value": 3,
        "source_small_walk_pose_indices": [0, 2],
        "source_small_walk_pointer_triplets": [[0x30, 0x31, 0x32], [0x36, 0x37, 0x38]],
        "source_small_jump_pointer_triplet": [0x48, 0x49, 0x4A],
        "source_small_layer_colors": [7, 6, 1], "source_small_layer_multicolor": [True, True, False],
        "source_layer_y_offsets": [0, 1, 2],
        "source_electric_pointer_triplet": [0x5D, 0x5E, 0x5F],
        "source_electric_layer_colors": [7, 1, 7], "source_electric_layer_multicolor": [False] * 3,
        "source_ball_pointers": [0xB9, 0xC0], "source_ball_type": 11,
        "source_ball_descriptor_address": 0x3126,
        "source_first_pickup_spawn_address": 0x3D64, "source_first_pickup_spawn": [48, 10, 11],
        "source_first_platform_character_rectangle": [40, 10, 58, 12],
        "source_powerup_brick_character_rectangle": [46, 3, 49, 5],
        "source_powerup_marker_character": {"column": 47, "row": 3, "character": 0xF2},
        "source_used_block_characters": [[0x4C, 0x4D, 0x4E], [0x4F, 0x50, 0x51]],
        "shared_multicolors": [10, 2], "plane_individual_colors": colors,
        "plane_canvas_heights": heights,
        "logical_pose_canvas_heights": [8, 8, 8, 10, 6, 6],
        "format": "24x21 multicolor hardware sprites; code 0 transparent; CPU source planes",
        "sampling": "Original layers composited in hardware priority order. Area vote four original X pixels per MC pixel; 23 rows into 8 for small Giana and 10 for electric; ball's sixteen nonpadding rows into 6. Opacity threshold 20% for player, 50% for ball.",
        "small_original_white_approximation": {"1": 10},
        "plane_bounding_boxes_physical": [SPRITES.bbox(image, 2) for image in plane_images],
        "logical_pose_bounding_boxes_physical": [SPRITES.bbox(image, 2) for image in reduced],
        "frame_sha256": [digest(frame) for frame in frames],
        "atlas_sha256": digest(atlas), "atlas_bytes": len(atlas), "plane_count": len(frames),
        "decoded_physical_pixels_verified": len(frames) * 24 * 21,
    }
    (ASSETS / "intro-import.json").write_text(json.dumps(receipt, indent=2) + "\n")
    preview(originals, reduced, names, palette)
    print(f"Original intro art: {len(frames)} planes, {len(atlas)} bytes; small Giana 8 rows, electric 10, ball 6.")


if __name__ == "__main__":
    main()
