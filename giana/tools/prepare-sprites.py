#!/usr/bin/env python3
"""Reduce original C64 Giana and Stage 1 owl art to tiny hardware sprites.

The default rebuild uses retained, verified sprite and collision slices. An optional
--program path re-extracts those slices from the exact original disk file 1.
"""

import argparse
from collections import Counter
from functools import lru_cache
import hashlib
import json
from pathlib import Path


PART = Path(__file__).resolve().parents[1]
ASSETS = PART / "assets"
PROGRAM_SHA256 = "0f1a720961fa52102fcfd52e46e40df07e5e307328ad087d55cc00506f904880"
SOURCES = {
    "original-sprites-giana.bin": (0xcc00, 0xcf00, "00cc787a7bed3d67516782d9eb2816088844317a714d2e27d5c8e45beafc2944"),
    "original-sprites-owl.bin": (0xe480, 0xe500, "a7852467282ae17687868613b1000f3392ba571519dee0b0aa258e24de5606c3"),
    "original-sprites-collision.bin": (0x9c20, 0x9d20, "667526cbc31e27d88d7e5871b646f96ff904d5b76b81494f29e425f41083b22b"),
}
MAP_SHA256 = "e75d388d6b80e7ec82064fc6a9309c16dadedf34a73425b52e4712be1fe7c99c"
PALETTE_SHA256 = "4a762159d75af98b510d43b709c4a1243f85ad706e594cf4a24fee0165f7b6ed"
MC0, MC1 = 10, 2
GIANA_COLOR, ENEMY_COLOR = 7, 1
GIANA_FRAME_COUNT, ENEMY_FRAME_COUNT = 4, 2
PLAYER_X_MC, PLAYER_WIDTH_MC = 10, 6
PLAYER_MIN_FOOT, PLAYER_MAX_FOOT = 12, 63


def digest(data):
    return hashlib.sha256(data).hexdigest()


def extract_sources(program_path):
    program = program_path.read_bytes()
    if len(program) != 63443 or digest(program) != PROGRAM_SHA256:
        raise ValueError("Expected the exact original game directory file 1")
    assert program[:2] == b"\x20\x08"
    memory = bytearray(65536)
    memory[0x0820:0x0820 + len(program) - 2] = program[2:]
    assert memory[0x9d20:0x9d22] == bytes((MC0, MC1))
    assert [memory[address] for address in (0x146d, 0x146f, 0x1471)] == [7, 6, 1]
    assert memory[0x30c0:0x30c8] == bytes((0x92, 0, 1, 0, 0x92, 0x93, 0x92, 0x93))
    for filename, (first, last, expected) in SOURCES.items():
        data = memory[first:last]
        assert digest(data) == expected
        (ASSETS / filename).write_bytes(data)


def read_sources():
    result = {}
    for filename, (first, last, expected) in SOURCES.items():
        data = (ASSETS / filename).read_bytes()
        if len(data) != last - first or digest(data) != expected:
            raise ValueError(f"Original sprite source changed: {filename}")
        result[filename] = data
    return result


def multicolor_frame(data, main_color):
    assert len(data) == 64
    colors = (None, MC0, main_color, MC1)
    return [[colors[(data[y * 3 + x // 8] >> (6 - 2 * ((x % 8) // 2))) & 3]
             for x in range(24)] for y in range(21)]


def giana_frame(data, pose):
    """Composite the original three layers in VIC sprite-priority order."""
    image = [[None] * 24 for _ in range(23)]
    for layer in (2, 1, 0):
        frame = data[(pose * 3 + layer) * 64:(pose * 3 + layer + 1) * 64]
        if layer < 2:
            pixels = multicolor_frame(frame, (7, 6)[layer])
        else:
            pixels = [[1 if frame[y * 3 + x // 8] & (0x80 >> (x % 8)) else None
                       for x in range(24)] for y in range(21)]
        for y, row in enumerate(pixels):
            for x, color in enumerate(row):
                if color is not None:
                    image[y + layer][x] = color
    return image


def reduce_frame(source, main_color, coverage_threshold, palette, output_colors):
    """Area-vote original pixels at horizontal 1/2 and vertical 2/5 scale."""
    height = (len(source) * 2 + 4) // 5
    quantize = {color: min(output_colors, key=lambda target: sum(
        (palette[color][channel] - palette[target][channel]) ** 2 for channel in range(3)))
                for color in range(16)}
    image = []
    for y in range(height):
        row = []
        for x in range(6):
            votes = Counter()
            total = 0
            for source_y in range(y * 5 // 2, min(len(source), ((y + 1) * 5 + 1) // 2)):
                weight = max(0, min((y + 1) * 2.5, source_y + 1, len(source)) - max(y * 2.5, source_y))
                for source_x in range(x * 4, x * 4 + 4):
                    total += weight
                    color = source[source_y][source_x]
                    if color is not None:
                        votes[quantize[color]] += weight
            coverage = sum(votes.values()) / total if total else 0
            row.append(max(votes, key=lambda color: (votes[color], color == main_color, color))
                       if coverage >= coverage_threshold else None)
        image.append(row)
    return image


def pack_frame(image, main_color):
    frame = bytearray(64)
    codes = {None: 0, MC0: 1, main_color: 2, MC1: 3}
    for y, row in enumerate(image):
        for x, color in enumerate(row):
            frame[y * 3 + x // 4] |= codes[color] << (6 - 2 * (x % 4))
    assert frame[63] == 0
    return bytes(frame)


def bbox(image, pixel_width=1):
    points = [(x * pixel_width, y) for y, row in enumerate(image)
              for x, color in enumerate(row) if color is not None]
    assert points
    return [min(x for x, y in points), min(y for x, y in points),
            max(x for x, y in points) + pixel_width, max(y for x, y in points) + 1]


def prepare_motion(collision, frames):
    original_map = (ASSETS / "original-level1-map.bin").read_bytes()
    assert len(original_map) == 5120 and digest(original_map) == MAP_SHA256
    ground = bytearray()
    for column in range(256):
        row = 19
        if collision[original_map[row * 256 + column]] not in (1, 0x80):
            ground.append(0xff)
            continue
        while row > 0 and collision[original_map[(row - 1) * 256 + column]] in (1, 0x80):
            row -= 1
        ground.append((16 * row + 2) // 5)

    path, physics = physical_route(collision, original_map, ground, frames)
    (ASSETS / "sprite-ground.bin").write_bytes(ground)
    (ASSETS / "sprite-player-path.bin").write_bytes(path)
    return ground, path, {"player_screen_x_mc": PLAYER_X_MC, "player_width_mc": PLAYER_WIDTH_MC,
                          "player_center_offset_mc": PLAYER_X_MC + PLAYER_WIDTH_MC // 2,
                          "camera_steps": 512, "camera_step_pal_frames": 4,
                          "ground_source_map_sha256": MAP_SHA256,
                          "ground_solid_flags": [1, 0x80], "ground_bytes": len(ground),
                          "ground_y_counts": dict(sorted(Counter(ground).items())),
                          "path_bytes": len(path), "hidden_steps": 0,
                          "enemy_world_center": "(camera_step & ~63) + 43; hide if ground==255 or ground<28",
                          "motion_kind": "finite offline gravity/support route, not original game physics",
                          **physics}


def physical_route(collision, original_map, ground, frames):
    # Work in projected TV coordinates so velocity does not change at a seam.
    terrain_tiles = (ASSETS / "level1-tiles.bin").read_bytes()
    terrain_map = (ASSETS / "level1-tv-map.bin").read_bytes()
    geometry = json.loads((ASSETS / "level1-import.json").read_text())
    columns = [column * 4 for column in geometry["perspective_columns"]]
    source_rows = geometry["perspective_source_rows"]
    source_solid = []
    for y in range(64):
        source_row = ((2 * y + 1) * 160 // 128) // 8
        row = []
        for x in range(512):
            character = original_map[source_row * 256 + x // 2]
            tile = terrain_map[y // 8 * 128 + x // 4]
            code = (terrain_tiles[tile * 8 + y % 8] >> (6 - 2 * (x % 4))) & 3
            row.append(collision[character] in (1, 0x80) and code != 1)
        source_solid.append(row)

    girl_rows = []
    girl_soles = []
    for pose in range(4):
        rows = []
        for y in range(10):
            mask = 0
            for x in range(6):
                offset, shift = y * 3 + x // 4, 6 - 2 * (x % 4)
                if ((frames[pose * 2][offset] | frames[pose * 2 + 1][offset]) >> shift) & 3:
                    mask |= 1 << x
            rows.append(mask)
        girl_rows.append(rows)
        girl_soles.append(rows[9])
    owl_pixels = []
    for pose in range(2):
        frame = frames[8 + pose]
        owl_pixels.append([(x, y) for y in range(9) for x in range(6)
                           if (frame[y * 3 + x // 4] >> (6 - 2 * (x % 4))) & 3])

    terrain_now = []
    terrain_both = []
    enemy_rows = []
    for step in range(512):
        current, both = [], []
        for y in range(64):
            current_mask = both_mask = 0
            for x in range(6):
                screen_x = PLAYER_X_MC + x
                region = next(index for index in range(4) if columns[index] <= screen_x < columns[index + 1])
                source_y = source_rows[region][y]
                solid = source_y < 0 or source_solid[source_y][(step + screen_x) % 512]
                future = source_y < 0 or source_solid[source_y][(step + screen_x + 1) % 512]
                current_mask |= int(solid) << x
                both_mask |= int(solid or future) << x
            current.append(current_mask)
            both.append(both_mask)
        terrain_now.append(current)
        terrain_both.append(both)
        enemy = [0] * 64
        enemy_ground = ground[((step & ~63) + 43) >> 1]
        enemy_x = 40 - (step & 63)
        if enemy_ground != 0xff and enemy_ground >= 28:
            top = project_motion_foot(enemy_ground, enemy_x) - 9
            for x, y in owl_pixels[(step >> 1) & 1]:
                column, row = enemy_x + x - PLAYER_X_MC, top + y
                if 0 <= column < 6 and 0 <= row < 64:
                    enemy[row] |= 1 << column
        enemy_rows.append(enemy)

    @lru_cache(maxsize=None)
    def blocked(step, foot, hold=True):
        if not 13 <= foot <= 62:
            return True
        terrain = terrain_both if hold else terrain_now
        return any(mask & (terrain[step][foot - 10 + row] | enemy_rows[step][foot - 10 + row])
                   for row, mask in enumerate(girl_rows[step & 3]))

    @lru_cache(maxsize=None)
    def support(step, foot):
        soles = girl_soles[step & 3]
        if soles & terrain_now[step][foot]:
            return 1
        if soles & enemy_rows[step][foot]:
            return 2
        return 0

    initial_foot = project_motion_foot(ground[(PLAYER_X_MC + PLAYER_WIDTH_MC // 2) >> 1], PLAYER_X_MC)
    initial = (initial_foot * 2, 0)
    assert not blocked(0, initial_foot) and support(0, initial_foot) == 1
    costs = {initial: 0}
    history = [{}]
    strengths = tuple(range(-3, -11, -1))
    for step in range(511):
        next_step = step + 1
        following = {}
        parents = {}
        for state, cost in costs.items():
            position, velocity = state
            old_foot = position // 2
            grounded = velocity == 0 and position % 2 == 0 and support(step, old_foot)
            actions = (0, *strengths) if grounded else (None,)
            for action in actions:
                if grounded and action == 0 and not blocked(next_step, old_foot) and support(next_step, old_foot):
                    target_position, target_velocity = position, 0
                else:
                    target_velocity = min(10, (action if action else velocity) + 1)
                    target_position = position + target_velocity
                    target_foot = target_position // 2
                    if not 26 <= target_position <= 124:
                        continue
                    if target_velocity < 0:
                        for foot in range(old_foot - 1, target_foot - 1, -1):
                            if blocked(next_step, foot, False):
                                target_position, target_velocity = (foot + 1) * 2, 0
                                break
                    else:
                        for foot in range(old_foot + 1, target_foot + 1):
                            if blocked(next_step, foot, False):
                                if support(next_step, foot - 1) and not blocked(next_step, foot - 1, False):
                                    target_position, target_velocity = (foot - 1) * 2, 0
                                else:
                                    target_position = -1
                                break
                        if target_position < 0:
                            continue
                    target_foot = target_position // 2
                    if blocked(next_step, target_foot):
                        continue
                    if target_velocity >= 0 and support(next_step, target_foot):
                        target_position, target_velocity = target_foot * 2, 0
                target_foot = target_position // 2
                kind = support(next_step, target_foot) if target_velocity == 0 and target_position % 2 == 0 else 0
                jump_cost = 16 + abs(action) * 2 if action else 0
                added = (0 if kind == 1 else 5 if kind == 2 else 8) + abs(target_position - position) + jump_cost
                candidate = (target_position, target_velocity)
                candidate_cost = cost + added
                if candidate_cost < following.get(candidate, 1 << 60):
                    following[candidate] = candidate_cost
                    parents[candidate] = (state, action)
        if not following:
            raise ValueError(f"No physical route reaches camera step {next_step}; previous states={list(costs)[:8]}")
        costs = following
        history.append(parents)
        if next_step % 128 == 0:
            print(f"Physical route step {next_step}/511: {len(costs)} reachable states", flush=True)
    if initial not in costs:
        raise ValueError(f"Physical route does not close at the map wrap; final states={sorted(costs)[:12]}")
    states = [initial]
    actions = []
    current = initial
    for step in range(511, 0, -1):
        previous, action = history[step][current]
        states.append(previous)
        actions.append(action)
        current = previous
    states.reverse()
    actions.reverse()
    inverse_projection = {project_motion_foot(foot, PLAYER_X_MC): foot for foot in range(12, 64)}
    path = bytes(inverse_projection[position // 2] for position, velocity in states)
    assert len(path) == 512 and all(value != 0xff for value in path)
    assert path[-1] == path[0]
    contacts = Counter(support(step, position // 2) if velocity == 0 and position % 2 == 0 else 0
                       for step, (position, velocity) in enumerate(states))
    assert all(not blocked(step, position // 2) for step, (position, velocity) in enumerate(states))
    jumps = [{"step": step, "launch_velocity_half_pixels": action}
             for step, action in enumerate(actions, 1) if action]
    return path, {"physics_position_units": "half projected physical pixels", "gravity_half_pixels": 1,
                  "jump_velocity_choices_half_pixels": list(strengths), "jumps": jumps,
                  "terrain_supported_steps": contacts[1], "owl_supported_steps": contacts[2],
                  "airborne_steps": contacts[0], "support_kind_by_step": [support(step, position // 2)
                  if velocity == 0 and position % 2 == 0 else 0 for step, (position, velocity) in enumerate(states)],
                  "projected_position_half_pixels": [position for position, velocity in states],
                  "vertical_velocity_half_pixels": [velocity for position, velocity in states],
                  "full_body_solid_and_owl_overlap_states": 0, "phase0_next_camera_checked": True,
                  "route_cost": costs[initial]}


def project_motion_foot(foot, x_mc):
    center = min(39, max(0, x_mc + 3))
    if foot < 28:
        return foot + (2 if center < 12 else 1 if center < 28 else 0)
    return foot - 1 if foot >= 36 and center < 20 else foot


def preview(originals, reduced, palette):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return
    sheet = Image.new("RGB", (150 * len(originals), 200), (40, 40, 40))
    draw = ImageDraw.Draw(sheet)
    for index, (source, tiny) in enumerate(zip(originals, reduced)):
        left = index * 150
        for y, row in enumerate(source):
            for x, color in enumerate(row):
                if color is not None:
                    draw.rectangle((left + x * 4, y * 4, left + x * 4 + 3, y * 4 + 3), fill=palette[color])
        for y, row in enumerate(tiny):
            for x, color in enumerate(row):
                if color is not None:
                    draw.rectangle((left + x * 12, 110 + y * 6, left + x * 12 + 11, 115 + y * 6), fill=palette[color])
        draw.text((left, 180), f"{'Giana' if index < 4 else 'Owl'} {index if index < 4 else index - 4}", fill="white")
    sheet.save(ASSETS / "sprites-preview.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, help="Re-extract the retained frames from original disk file 1")
    args = parser.parse_args()
    if args.program:
        extract_sources(args.program)
    sources = read_sources()
    palette_bytes = (ASSETS / "peptoette-a.vpl").read_bytes()
    assert digest(palette_bytes) == PALETTE_SHA256
    palette = [tuple(int(value, 16) for value in line.split()[:3])
               for line in palette_bytes.decode().splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    originals = [giana_frame(sources["original-sprites-giana.bin"], pose) for pose in range(GIANA_FRAME_COUNT)]
    raw_owl = sources["original-sprites-owl.bin"]
    originals.extend(multicolor_frame(raw_owl[pose * 64:(pose + 1) * 64], ENEMY_COLOR)
                     for pose in range(ENEMY_FRAME_COUNT))
    reduced = [reduce_frame(source, GIANA_COLOR if index < 4 else ENEMY_COLOR,
                            0.2 if index < 4 else 0.5, palette,
                            (MC0, GIANA_COLOR, 6, MC1) if index < 4 else (MC0, ENEMY_COLOR, MC1))
               for index, source in enumerate(originals)]
    frame_images = []
    frame_main_colors = []
    for index, image in enumerate(reduced):
        if index < 4:
            frame_images.append([[None if color == 6 else color for color in row] for row in image])
            frame_images.append([[6 if color == 6 else None for color in row] for row in image])
            frame_main_colors.extend((GIANA_COLOR, 6))
        else:
            frame_images.append(image)
            frame_main_colors.append(ENEMY_COLOR)
    frames = [pack_frame(image, color) for image, color in zip(frame_images, frame_main_colors)]
    assert len({frames[pose * 2] + frames[pose * 2 + 1] for pose in range(4)}) == 4
    assert len(set(frames[8:])) == 2
    for index, (image, frame) in enumerate(zip(frame_images, frames)):
        decoded = multicolor_frame(frame, frame_main_colors[index])
        for y in range(21):
            for x in range(24):
                expected = image[y][x // 2] if y < len(image) and x < 12 else None
                assert decoded[y][x] == expected
    for pose in range(GIANA_FRAME_COUNT):
        base = multicolor_frame(frames[pose * 2], GIANA_COLOR)
        overlay = multicolor_frame(frames[pose * 2 + 1], 6)
        assert {((value >> shift) & 3) for value in frames[pose * 2 + 1][:63]
                for shift in (6, 4, 2, 0)} <= {0, 2}
        for y in range(21):
            for x in range(24):
                actual = base[y][x] if base[y][x] is not None else overlay[y][x]
                expected = reduced[pose][y][x // 2] if y < len(reduced[pose]) and x < 12 else None
                assert actual == expected
    ground, player_path, motion = prepare_motion(sources["original-sprites-collision.bin"], frames)
    atlas = b"".join(frames)
    assert len(atlas) == 640
    (ASSETS / "sprites.bin").write_bytes(atlas)
    assembly = [
        "// Original C64 Giana and Stage 1 owl, reduced by tools/prepare-sprites.py.",
        "// Import at a VIC-visible address aligned to 64 bytes. Code 0 is transparent.",
        f".const SPRITE_MC0 = {MC0}", f".const SPRITE_MC1 = {MC1}",
        f".const SPRITE_GIANA_COLOR = {GIANA_COLOR}", f".const SPRITE_ENEMY_COLOR = {ENEMY_COLOR}",
        ".const SPRITE_GIANA_LAYER1_COLOR = 6",
        ".const SPRITE_GIANA_FRAME_COUNT = 4", ".const SPRITE_ENEMY_FRAME_COUNT = 2",
        ".const SPRITE_GIANA_PLANES = 2", ".const SPRITE_ENEMY_PLANES = 1",
        ".const SPRITE_GIANA_STRIDE = 2", ".const SPRITE_ENEMY_STRIDE = 1",
        ".const SPRITE_GIANA_FRAME_OFFSET = 0", ".const SPRITE_ENEMY_FRAME_OFFSET = 8",
        ".const SPRITE_FRAME_COUNT = 10", ".const SPRITE_FRAME_BYTES = 64",
        f".const SPRITE_PLAYER_X_MC = {PLAYER_X_MC}", f".const SPRITE_PLAYER_WIDTH_MC = {PLAYER_WIDTH_MC}",
        ".const SPRITE_GIANA_WIDTH = 12", ".const SPRITE_GIANA_HEIGHT = 10",
        ".const SPRITE_ENEMY_WIDTH = 12", ".const SPRITE_ENEMY_HEIGHT = 9",
        '.var originalTinySpriteFile = LoadBinary("sprites.bin")',
        "tinySpriteFrames:", "    .fill originalTinySpriteFile.getSize(), originalTinySpriteFile.get(i)",
        "tinySpriteFramesEnd:",
        '.assert "Ten 64-byte tiny sprite planes", tinySpriteFramesEnd - tinySpriteFrames, SPRITE_FRAME_COUNT * SPRITE_FRAME_BYTES',
        '.assert "Tiny sprite atlas is 64-byte aligned", <tinySpriteFrames & $3f, 0', "",
    ]
    (ASSETS / "sprites.asm").write_text("\n".join(assembly))
    receipt = {
        "original_program_sha256": PROGRAM_SHA256,
        "source_slices": {name: {"first_address": first, "end_address_exclusive": last, "sha256": expected}
                          for name, (first, last, expected) in SOURCES.items()},
        "source_giana_pointer_triplets": [[0x30 + pose * 3 + layer for layer in range(3)] for pose in range(4)],
        "source_giana_layer_y_offsets": [0, 1, 2],
        "source_giana_layer_colors": [7, 6, 1],
        "source_giana_layer_multicolor": [True, True, False],
        "source_enemy_name": "Stage 1 horned owl",
        "source_enemy_pointers": [0x92, 0x93],
        "source_enemy_type": 5, "source_enemy_record_address": 0x30c0,
        "source_enemy_first_ground_trigger_column": 75,
        "shared_multicolors": [MC0, MC1], "individual_colors": [GIANA_COLOR, 6, ENEMY_COLOR],
        "scale_horizontal": "1/2", "scale_vertical": "2/5",
        "sampling": "area-vote original pixels; Giana coverage >=20%, owl coverage >=50%; palette RGB nearest",
        "format": "24x21 hardware multicolor sprite, 64 bytes/frame, code0 transparent",
        "frame_count": len(frames), "giana_frame_count": 4, "enemy_frame_count": 2,
        "giana_planes": 2, "giana_frame_stride": 2, "enemy_planes": 1, "enemy_frame_offset": 8,
        "giana_output_blue_pixels_per_pose": [sum(color == 6 for row in image for color in row)
                                               for image in reduced[:4]],
        "frame_bytes": 64, "atlas_bytes": len(atlas),
        "frame_bounding_boxes_physical": [bbox(image, 2) for image in frame_images],
        "logical_pose_bounding_boxes_physical": [bbox(image, 2) for image in reduced],
        "source_bounding_boxes_physical": [bbox(image) for image in originals],
        "frame_sha256": [digest(frame) for frame in frames],
        "atlas_sha256": digest(atlas),
        "motion": motion,
        "motion_output_sha256": {"sprite-ground.bin": digest(ground), "sprite-player-path.bin": digest(player_path)},
        "source_sha256": {name: digest(data) for name, data in sources.items()},
        "decoded_physical_pixels_verified": len(frames) * 24 * 21,
        "giana_composite_physical_pixels_verified": GIANA_FRAME_COUNT * 24 * 21,
        "original_source_colors_approximated_for_giana": {"1": 10},
    }
    (ASSETS / "sprites-import.json").write_text(json.dumps(receipt, indent=2) + "\n")
    preview(originals, reduced, palette)
    print(f"Original sprites imported: 4 two-plane Giana poses + 2 Stage 1 owl frames, {len(atlas)} bytes.")


if __name__ == "__main__":
    main()
