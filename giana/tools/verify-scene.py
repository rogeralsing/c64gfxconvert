#!/usr/bin/env python3
"""Verify the built Giana scene in PAL VICE against the original Koala and masks.

Run after ./giana/build.sh. No monitor writes or special test build are used.
The default run covers every graphics state and the original music's first
complete structural score loop, using an independently captured RSID reference.
"""

import argparse
from collections import Counter
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "giana/build"
sys.path.insert(0, str(ROOT / "mydemo/discoball"))
from vice_support import Monitor, connect_monitor, read_labels, vice_command


LIGHT_ONE = (0, 1, 2, 7, 10, 15, 6, 1, 10, 9, 15, 11, 15, 1, 15, 7)
LIGHT_MAPS = (tuple(range(16)), LIGHT_ONE, tuple(LIGHT_ONE[color] for color in LIGHT_ONE))
LIGHT_SEQUENCE = (0, 1, 2, 1)
PROTECTED_COLORS = (0, 1, 2, 6, 9, 11)
REGION_BOUNDS = (0, 3, 5, 7, 10)
REGION_COLUMNS = tuple(region for region, (left, right) in enumerate(zip(REGION_BOUNDS, REGION_BOUNDS[1:]))
                       for _ in range(left, right))
REGION_SOURCE_ROWS = (
    tuple(-1 if y in (0, 1, 63) else y - 2 if y < 28 else y if y < 36 else y + 1
          for y in range(64)),
    tuple(-1 if y in (0, 63) else y - 1 if y < 28 else y if y < 36 else y + 1
          for y in range(64)),
    tuple(-1 if y == 0 else y - 1 if y < 28 else y for y in range(64)),
    tuple(range(64)),
)
REGION_MASK_ROWS = (0x81, 0x81, 0x01, 0x00)
INTRO_MAIN_COLORS = (7, 6, 7, 6, 7, 6, 7, 1, 7, 7)
INTRO_HEIGHTS = (8, 8, 8, 8, 8, 8, 10, 10, 6, 6)
INTRO_JUMP_FEET = (28, 25, 24, 25, 27, 30)
INTRO_BALL_X = (11, 12, 13, 14, 15, 16, 17, 16, 15, 14, 13, 12)
INTRO_BALL_Y = (9, 7, 5, 5, 5, 5, 6, 8, 11, 14, 18, 23)
SPRITE_MAIN_COLORS = ((7, 6) * 4 + (1, 1, 7, 7, 1, 1, 1, 1) + (5,) * 6 + (7, 7)
                      + INTRO_MAIN_COLORS)
ENEMY_TYPES = {0: "bee", 2: "crab", 5: "owl", 7: "slinky"}
PLAYBACK_ORDER = ((0, 0), (1, 1))  # Boy room Level1, then man room Level2.


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_sid_events(path):
    clock = 0
    result = []
    for line in path.read_text().splitlines():
        fields = line.split()
        if len(fields) != 3:
            continue
        try:
            delta, register, value = map(int, fields)
        except ValueError:
            continue
        clock += delta
        if 0 <= register <= 24:
            result.append((clock, register, value))
    return result


def vic_bank(cia):
    """CIA2 input bits are pulled high; DDR-based banking preserves IEC pins."""
    pins = (cia[0] | (~cia[2] & 0xff)) & 3
    return (~pins) & 3


class MciReference:
    """Decode both original True Paint fields independently of part generation."""

    def __init__(self, palette):
        self.path = ROOT / "images/giana-man.mci"
        self.source = self.path.read_bytes()
        assert len(self.source) == 19434 and self.source[:2] == b"\x00\x9c", "Expected the original True Paint MCI"
        self.project_path = ROOT / "images/giana-man.json"
        self.project = json.loads(self.project_path.read_text())
        assert self.project["image"]["graphicsMode"] == "mci" and self.project["image"]["paletteId"] == "peptoette-a"
        self.bitmaps = (self.source[1026:9026], self.source[9218:17218])
        self.screens = (self.source[2:1002], self.source[17410:18410])
        self.colors = self.source[18434:19434]
        self.background = self.source[1002]
        assert self.background < 16 and all(color < 16 for color in self.colors)
        self.palette = palette
        self.images = []
        for phase in range(2):
            pixels = []
            for y in range(200):
                row = []
                for x in range(160):
                    cell = y // 8 * 40 + x // 4
                    bits = self.bitmaps[phase][cell * 8 + y % 8]
                    code = bits >> (6 - 2 * (x % 4)) & 3
                    screen = self.screens[phase][cell]
                    color = (self.background, screen >> 4, screen & 15, self.colors[cell])[code]
                    row.extend((palette[color], palette[color]))
                pixels.extend(([palette[self.background]] + row[:-1]) if phase else row)
            image = Image.new("RGB", (320, 200))
            image.putdata(pixels)
            self.images.append(image)

    def verify_field(self, phase, ram, vic, colors, cia):
        assert phase in (0, 1)
        bank = vic_bank(cia)
        assert bank == (0, 2)[phase], ("MCI field bank", phase, bank)
        screen = bank * 0x4000 + (vic[0x18] >> 4) * 0x400
        bitmap = bank * 0x4000 + (0x2000 if vic[0x18] & 8 else 0)
        assert (screen, bitmap) == ((0x0400, 0x2000), (0x8400, 0xa000))[phase]
        assert vic[0x11] & 0x7f == 0x3b and vic[0x16] & 0x3f == 0x18 + phase
        assert vic[0x18] & 0xfe == 0x18 and vic[0x15] == 0
        assert vic[0x21] & 15 == self.background
        assert ram[bitmap:bitmap + 8000] == self.bitmaps[phase], (phase, "MCI bitmap differs from source")
        assert ram[screen:screen + 1000] == self.screens[phase], (phase, "MCI screen colors differ from source")
        assert colors == self.colors, (phase, "MCI Color RAM differs from source")
        return {"phase": phase, "vic_bank": bank, "screen_address": screen, "bitmap_address": bitmap,
                "horizontal_scroll": vic[0x16] & 7}


class RoomArchiveReference:
    """Independently decode the retained second-room image archive."""

    def __init__(self):
        self.path = ROOT / "images/giana7.koa"
        self.source = self.path.read_bytes()
        assert len(self.source) == 10003, "Expected a standard ending Koala image"
        self.bitmap = self.source[2:8002]
        self.screen = self.source[8002:9002]
        self.colors = bytes(value & 15 for value in self.source[9002:10002])
        self.background = self.source[10002] & 15
        self.packed = (ROOT / "giana/assets/ending-packbits.bin").read_bytes()
        reverse = bytearray()
        cursor = len(self.packed)
        while cursor:
            cursor -= 1
            tag = self.packed[cursor]
            count = (tag & 127) + 1
            if tag & 128:
                assert cursor, "Ending repeat has no source byte"
                cursor -= 1
                reverse.extend((self.packed[cursor],) * count)
            else:
                assert cursor >= count, "Ending literal packet exceeds its source"
                for _ in range(count):
                    cursor -= 1
                    reverse.append(self.packed[cursor])
        unpacked = bytes(reversed(reverse))
        assert len(unpacked) == 9500, "Second room must contain bitmap, screen and packed color nibbles"
        assert unpacked[:9000] == self.source[2:9002], "Packed room bitmap/screen differs from original Koala"
        color_nibbles = bytes(nibble for pair in unpacked[9000:] for nibble in (pair >> 4, pair & 15))
        assert color_nibbles == self.colors, "Packed room colors differ from original Koala"


class SceneReference:
    """Decode source files directly, independently of generated runtime tables."""

    def __init__(self, source_level=1, room=0):
        self.room = room
        self.source_level = source_level
        self.terrain_colors = (9, 14, 8) if source_level == 1 else (9, 10, 2)
        self.source_colors = (14, 8, 9) if source_level == 1 else (0, 10, 2)
        self.game_screen = self.terrain_colors[1] * 16 + self.terrain_colors[2]
        self.empty_code = 1 if source_level == 1 else 0
        self.player_height = 10 if source_level == 1 else 8
        image_number = 5 if room == 0 else 7
        self.source_path = ROOT / f"images/giana{image_number}.koa"
        self.project_path = ROOT / f"images/giana{image_number}.json"
        self.source = self.source_path.read_bytes()
        assert len(self.source) == 10003, "Expected a standard Koala image"
        self.bitmap = self.source[2:8002]
        self.screen = self.source[8002:9002]
        self.colors = bytes(color & 15 for color in self.source[9002:10002])
        self.background = self.source[10002] & 15
        project = json.loads(self.project_path.read_text())
        masks = {}
        for name in ("GameArea", "ScreenLight"):
            matching = [layer for layer in project["layers"]
                        if layer.get("type") == "tile-markers" and layer["name"] == name]
            assert len(matching) == 1, f"Expected exactly one {name} marker layer"
            tiles = matching[0]["markers"]["tiles"]
            assert len(tiles) == 1000 and all(value in (0, 1) for value in tiles)
            masks[name] = {index for index, value in enumerate(tiles) if value}
        self.game = masks["GameArea"]
        self.light = masks["ScreenLight"]
        assert self.game == {row * 40 + column for row in range(3, 11) for column in range(23, 33)}
        assert self.light and not self.game & self.light
        assert self.background == 9
        self.tiles = (ROOT / f"giana/assets/level{source_level}-tiles.bin").read_bytes()
        self.tile_map = (ROOT / f"giana/assets/level{source_level}-tv-map.bin").read_bytes()
        self.accents = (ROOT / f"giana/assets/level{source_level}-accents.bin").read_bytes()
        self.accent_tables = tuple((ROOT / "giana/assets" / name).read_bytes() for name in (
            f"level{source_level}-perspective-accents.bin", f"level{source_level}-perspective-middle-accents.bin",
            f"level{source_level}-perspective-right-accents.bin", f"level{source_level}-accents.bin"))
        assert len(self.tiles) % 8 == 0 and len(self.tile_map) == 128 * 8 and len(self.accents) == 512
        assert all(len(table) == 512 for table in self.accent_tables)
        self.shared_sprite_atlas = (ROOT / "giana/assets/sprites.bin").read_bytes()
        self.extra_enemy_frames = (ROOT / "giana/assets/level2-enemies.bin").read_bytes()
        self.intro_planes = (ROOT / "giana/assets/intro-sprites.bin").read_bytes()
        self.level2_player_planes = (ROOT / "giana/assets/level2-sprites.bin").read_bytes() if source_level == 2 else None
        self.sprite_atlas = ((self.level2_player_planes + self.shared_sprite_atlas[512:]
                              if source_level == 2 else self.shared_sprite_atlas)
                             + self.extra_enemy_frames + self.intro_planes)
        actor_prefix = "" if source_level == 1 else "level2-"
        self.player_path = (ROOT / f"giana/assets/{actor_prefix}sprite-player-path.bin").read_bytes()
        self.original_route_support = (json.loads((ROOT / "giana/assets/sprites-import.json").read_text())
                                       ["motion"]["support_kind_by_step"])
        self.actor_ground = (ROOT / "giana/assets/sprite-ground.bin").read_bytes() if source_level == 1 else None
        self.original_map = (ROOT / f"giana/assets/original-level{source_level}-map.bin").read_bytes()
        if source_level == 2:
            assert self.original_map == self.decode_level2_stream(), "Level2 source map differs from the original block stream"
        self.collision_flags = (ROOT / "giana/assets/original-sprites-collision.bin").read_bytes()
        assert (len(self.sprite_atlas), len(self.player_path)) == (2176, 512)
        assert self.actor_ground is None or len(self.actor_ground) == 256
        assert (len(self.original_map), len(self.collision_flags)) == (5120, 256)
        self.highlight_source_path = ROOT / "giana/assets/tv-highlight-mask.json"
        self.highlight_source = self.highlight_source_path.read_bytes()
        source_rows = json.loads(self.highlight_source)["rows"]
        assert len(source_rows) == 21 and all(len(row) == 24 and set(row) <= {".", "#"} for row in source_rows)
        # The approved editable art is the source; generated sprite bytes and
        # previews do not supply expected native pixels.
        self.highlight_pixels = {(184 + x, 27 + y): 3
                                 for y, row in enumerate(source_rows) for x, pixel in enumerate(row) if pixel == "#"}
        highlight_data = bytearray(64)
        for x, y in self.highlight_pixels:
            highlight_data[(y - 27) * 3 + (x - 184) // 8] |= 1 << (7 - (x - 184) % 8)
        self.highlight_data = bytes(highlight_data)
        assert self.highlight_pixels, "Glass highlight source must contain visible art"
        self.corner_positions = ((208, 74), (264, 74), (208, 117), (264, 117))
        corner_profile = (6, 4, 3, 2, 1, 1, 0, 0)
        corner_baselines = (2, 0, 62, 63)
        self.corner_pixels = {}
        corner_data = bytearray(256)
        for slot, ((x_hw, y_hw), baseline) in enumerate(zip(self.corner_positions, corner_baselines)):
            origin_x, origin_y = x_hw - 24, y_hw - 50
            for depth, width in enumerate(corner_profile):
                y = 24 + baseline + (depth if slot < 2 else -depth)
                columns = range(width) if slot % 2 == 0 else range(24 - width, 24)
                for column in columns:
                    x = origin_x + column
                    assert 184 <= x < 264 and 24 <= y < 88
                    self.corner_pixels[(x, y)] = 0
                    corner_data[slot * 64 + (y - origin_y) * 3 + column // 8] |= 0x80 >> (column % 8)
        self.corner_data = bytes(corner_data)
        assert len(self.corner_pixels) == 68
        self.music = (ROOT / "giana/assets/music-original.bin").read_bytes()
        self.music_source = (ROOT / "giana/assets/music-source.sid").read_bytes()
        reference_path = BUILD / "music-discovery/original-call-reference.json"
        if not reference_path.exists():
            subprocess.run([sys.executable, str(ROOT / "giana/tools/prepare-music-reference.py")], check=True)
        self.music_reference = json.loads(reference_path.read_text())
        assert len(self.music) == 7709 and self.music_reference["source_sha256"] == digest(self.music_source)
        assert self.music_reference["subtune_one_based"] == 3
        assert self.shared_sprite_atlas[512:] + self.extra_enemy_frames == self.decode_original_enemy_art(), (
            "Enemy art differs from original native frames")
        self.original_enemies = self.decode_original_enemy_spawns()
        for frame in range(34):
            data = self.sprite_atlas[frame * 64:(frame + 1) * 64]
            height = self.player_height if frame < 8 else 9 if frame < 24 else INTRO_HEIGHTS[frame - 24]
            assert data[63] == 0
            for row in range(21):
                for pair in range(12):
                    if row >= height or pair >= 6:
                        assert self.sprite_code(data, pair, row) == 0, (frame, pair, row)
        self.palette_path = ROOT / "palettes/peptoette-a.vpl"
        self.palette = [tuple(int(value, 16) for value in line.split()[:3])
                        for line in self.palette_path.read_text().splitlines()
                        if line.strip() and not line.lstrip().startswith("#")]
        assert len(self.palette) == 16
        assert self.intro_planes == self.decode_original_intro_art(), "Intro art differs from original native frames"
        if source_level == 2:
            assert self.level2_player_planes == self.decode_level2_player_art(), "Level2 Giana differs from original area-sampled art"
        self.decode_original_terrain()
        self.enemy_schedules = self.read_level2_enemy_schedules() if source_level == 2 else None
        for region, source_rows in enumerate(REGION_SOURCE_ROWS):
            for target_y, source_y in enumerate(source_rows):
                if source_level == 1 and source_y >= 0 and REGION_MASK_ROWS[region] & (1 << (target_y // 8)):
                    assert all(self.terrain_pixel(x, source_y) != 3 for x in range(512)), (
                        "Black edge-cell masks must not erase source accents", region, target_y)
        self.protected_pixels = []
        for cell in self.light:
            colors = (self.background, self.screen[cell] >> 4, self.screen[cell] & 15, self.colors[cell])
            for row in range(8):
                offset = cell * 8 + row
                for shift in (6, 4, 2, 0):
                    color = colors[(self.bitmap[offset] >> shift) & 3]
                    if color in PROTECTED_COLORS:
                        self.protected_pixels.append((cell, offset, shift, color))

    @staticmethod
    def decode_original_enemy_art():
        """Area-sample original multicolor frames using exact integer weights."""
        groups = (
            ("original-sprites-owl.bin", "a7852467282ae17687868613b1000f3392ba571519dee0b0aa258e24de5606c3", 1, 9),
            ("original-level2-enemies-bee.bin", "a2c34ddf77cd07e43012d87cad47744ed4800df25a6c978fa1f0ae2d62cd9ebd", 7, 9),
            ("original-level2-enemies-crab.bin", "8c59673f5994afc9d5b2aeeebbb96dfdbc33785fed46b3608d9eabeb926562dc", 1, 6),
            ("original-level2-enemies-slinky.bin", "342ab3465ac4f1cd639b032eee7db8e5eb8fdcaa3f726ad5b78a3f87e7e4fcf0", 5, 9),
            ("original-level2-enemies-bee-right.bin", "31be654991c6c6b291e6d0bdf638bed5be0f602b51c1d8bf9db87e4e9db66a11", 7, 9),
        )
        result = bytearray()
        for filename, expected_hash, main_color, target_height in groups:
            source = (ROOT / "giana/assets" / filename).read_bytes()
            assert digest(source) == expected_hash, f"Original enemy art changed: {filename}"
            for offset in range(0, len(source), 64):
                frame = source[offset:offset + 64]
                reduced = bytearray(64)
                for y in range(target_height):
                    for x in range(6):
                        votes = Counter()
                        total = 0
                        for sy in range(21):
                            # Crab uses all21 rows reduced to6; other species
                            # retain the approved two-fifths vertical sampling.
                            numerator, denominator = (21, 6) if target_height == 6 else (5, 2)
                            weight = max(0, min((y + 1) * numerator, (sy + 1) * denominator)
                                         - max(y * numerator, sy * denominator))
                            if not weight:
                                continue
                            for sx in range(x * 4, x * 4 + 4):
                                total += weight
                                code = (frame[sy * 3 + sx // 8] >> (6 - 2 * ((sx % 8) // 2))) & 3
                                if code:
                                    votes[code] += weight
                        if 2 * sum(votes.values()) >= total:
                            code = max(votes, key=lambda value: (votes[value], value == 2, (0, 10, main_color, 2)[value]))
                            reduced[y * 3 + x // 4] |= code << (6 - 2 * (x % 4))
                result.extend(reduced)
        return bytes(result)

    @staticmethod
    def decode_original_enemy_spawns():
        assets = ROOT / "giana/assets"
        files = (
            ("original-level2-enemies-spawns.bin", "96103e1b46bf536997a7871cca1570266099c97faf87252f351861ed4cfe8a04"),
            ("original-level2-enemies-descriptors.bin", "3f1429b36ee027126c65517f3a93037bd7db50c0b56d17dd1dcca8bc21bdc30d"),
            ("original-level2-enemies-y-table.bin", "cc541aa2465e4315a984ccceb9dfea8cbfc932f1891a4f58dc86a4b73626213c"),
        )
        raw = []
        for filename, expected_hash in files:
            data = (assets / filename).read_bytes()
            assert digest(data) == expected_hash, f"Original enemy source changed: {filename}"
            raw.append(data)
        spawns, descriptors, y_table = raw
        assert len(spawns) == 31 and spawns[-1] == 255 and len(descriptors) == 92
        result = []
        for offset in range(0, 30, 3):
            column, row, kind = spawns[offset:offset + 3]
            if kind == 11:
                continue  # Original dynamic pickups are separate from enemies.
            assert kind in ENEMY_TYPES
            descriptor_offset = (0, 2, 5, 7).index(kind) * 23
            descriptor = descriptors[descriptor_offset:descriptor_offset + 23]
            result.append({"source_entry": offset // 3, "column": column, "row": row, "type": kind,
                           "world_x": 2 * column - 4, "source_top": y_table[row] - 61,
                           "source_x": 8 * column - 16, "activation": 2 * (column - 40),
                           "color": descriptor[2], "speed": descriptor[14], "support_mode": descriptor[16]})
        assert len(result) == 8
        return result

    def read_level2_enemy_schedules(self):
        """Check serialized motion against original art, spawns and solid pixels.

        Patrol choices are intentionally faked. These checks enforce their public
        contract independently of the offline route solver, rather than copying
        that solver to generate a second set of expected trajectories.
        """
        self.enemy_schedule_arrays = []
        schedules = [[{"x": 0, "y": 0, "frame": 255, "source_entry": None, "type": None}
                      for _ in range(2)] for _ in range(512)]
        lifetimes = {enemy["source_entry"]: [] for enemy in self.original_enemies}
        type_frames = {5: ((8, 2),), 0: ((10, 2), (22, 2)),
                       2: ((12, 2), (14, 2)), 7: ((16, 3), (19, 3))}
        self.enemy_semantics = []
        for slot in range(2):
            arrays = {channel: (ROOT / f"giana/assets/level2-enemy{slot}-{channel}.bin").read_bytes()
                      for channel in ("x", "y", "frame")}
            assert all(len(data) == 512 for data in arrays.values())
            self.enemy_schedule_arrays.append(arrays)
            for step, pose in enumerate(arrays["frame"]):
                if pose == 255:
                    continue
                assert step <= 472, (step, slot, "Enemy beyond the finite Level2 camera route")
                x = arrays["x"][step]
                x -= 256 if x >= 128 else 0
                y = arrays["y"][step]
                assert -5 <= x < 40 and 0 <= y < 64, (step, slot, x, y)
                kind = next((kind for kind, groups in type_frames.items()
                             if any(first <= pose < first + count for first, count in groups)), None)
                assert kind is not None, (step, slot, pose, "Unknown original enemy pose")
                candidates = [enemy for enemy in self.original_enemies if enemy["type"] == kind]
                original = min(candidates, key=lambda enemy: abs(step + x - enemy["world_x"]))
                entry = original["source_entry"]
                assert step >= original["activation"], (step, entry, "Enemy before its original spawn trigger")
                # An enemy may settle onto a nearby clear reduced floor before
                # entry (up to8MC), then patrol within2MC of that fixed anchor.
                offset = step + x - original["world_x"]
                assert -10 <= offset <= 10, (step, entry, "Enemy outside its local patrol", offset)
                phase = (4 * (step - original["activation"]) // 7)
                first, count = next(group for group in type_frames[kind] if group[0] <= pose < sum(group))
                assert pose - first == phase % count, (step, entry, "Original seven-update animation timer", pose, phase)
                assert SPRITE_MAIN_COLORS[pose] == original["color"], (entry, "Original enemy main color")
                actor = {"x": x, "y": y, "frame": pose, "source_entry": entry, "type": kind}
                schedules[step][slot] = actor
                lifetimes[entry].append((step, slot, x, y, pose))
                data = self.sprite_atlas[pose * 64:(pose + 1) * 64]
                points = {(x + px, y + py) for py in range(21) for px in range(6)
                          if self.sprite_code(data, px, py) and 0 <= x + px < 40}
                assert points, (step, entry, "Enemy schedule has no visible opaque pixels")
                assert all(0 <= py < 64 and REGION_SOURCE_ROWS[REGION_COLUMNS[px // 4]][py] >= 0
                           for px, py in points), (step, entry, "Enemy over the TV edge mask")
                support = []
                for held_camera in (step, step + 1):
                    overlap = {(px, py) for px, py in points if self.rendered_solid(held_camera, px, py, True)}
                    assert not overlap, (step, held_camera, entry, "Opaque enemy entered rendered terrain", sorted(overlap))
                    support.append(sum((px, py + 1) not in points and self.rendered_solid(held_camera, px, py + 1, True)
                                       for px, py in points))
                self.enemy_semantics.append({"step": step, "source_entry": entry, "type": kind,
                                             "slot": slot, "x": x, "y": y, "frame": pose,
                                             "held_camera_support_pixels": support, "foot_y": 1 + max(py for px, py in points),
                                             "fully_inside": 0 <= x <= 34})
        summaries = []
        for entry, states in lifetimes.items():
            assert states, (entry, "Original enemy omitted")
            assert len({slot for _, slot, _, _, _ in states}) == 1, (entry, "Enemy changed hardware slot")
            original = next(enemy for enemy in self.original_enemies if enemy["source_entry"] == entry)
            world_positions = [step + x for step, _, x, _, _ in states]
            assert max(world_positions) - min(world_positions) <= 4, (entry, "Enemy exceeded bounded patrol width")
            for previous, current in zip(states, states[1:]):
                elapsed = current[0] - previous[0]
                if elapsed > 1:
                    assert (previous[2] <= 0 or previous[2] >= 34) and (current[2] <= 0 or current[2] >= 34), (
                        entry, previous[0], current[0], "Enemy disappeared inside the TV")
                world_delta = (current[0] + current[2]) - (previous[0] + previous[2])
                assert abs(world_delta) <= original["speed"] * elapsed, (entry, current[0], "Enemy exceeded native source speed", world_delta)
            body_states = [state for state in self.enemy_semantics if state["source_entry"] == entry]
            unsupported = [state for state in body_states if state["fully_inside"] and
                           not state["held_camera_support_pixels"][0]]
            hover_runs = []
            current_run = []
            for state in body_states:
                if (state["fully_inside"] and not state["held_camera_support_pixels"][0] and
                        (not current_run or state["step"] == current_run[-1]["step"] + 1 and
                         state["foot_y"] == current_run[-1]["foot_y"])):
                    current_run.append(state)
                else:
                    if len(current_run) > 3:
                        hover_runs.append([current_run[0]["step"], current_run[-1]["step"]])
                    current_run = [state] if state["fully_inside"] and not state["held_camera_support_pixels"][0] else []
            if len(current_run) > 3:
                hover_runs.append([current_run[0]["step"], current_run[-1]["step"]])
            if original["type"] != 0:
                assert not hover_runs, (entry, "Unsupported walking enemy hovered", hover_runs)
            summaries.append({"source_entry": entry, "type": original["type"], "name": ENEMY_TYPES[original["type"]],
                              "first": states[0][0], "last": states[-1][0], "states": len(states),
                              "slot": states[0][1], "world_x_range": [min(world_positions), max(world_positions)],
                              "original_world_x": original["world_x"],
                              "unsupported_interior_states": len(unsupported), "unsupported_flat_runs": hover_runs,
                              "held_camera_supported_states": [sum(bool(state["held_camera_support_pixels"][phase])
                                                                     for state in body_states) for phase in (0, 1)]})
        self.enemy_schedule_summary = summaries
        return tuple(tuple(actors) for actors in schedules)

    def expected_level2_enemies(self, step):
        return self.enemy_schedules[step]

    def decode_original_intro_art(self):
        """Composite retained original planes and reduce with integer area weights."""
        inputs = (
            ("original-intro-small-walk.bin", "169267a5a7cecd5132dd4c509a8c462bbe558208e927d278bdf8a479e1526833"),
            ("original-intro-small-jump.bin", "192d22864c0dd217bfbf8cb801e501c5e5beb25518285a743f805c348dd726b3"),
            ("original-intro-electric.bin", "46e6c9cc8c90f92d2a933f7fe9d5d6915a958bb020c038fabbab4ea7aabf3066"),
            ("original-intro-ball.bin", "0832cc04daeff9213d23124e9ec3bcc5a3f442ccd61e9ed528ad85de5377d00d"),
        )
        sources = []
        for filename, expected_hash in inputs:
            data = (ROOT / "giana/assets" / filename).read_bytes()
            assert digest(data) == expected_hash, (filename, "Original intro source changed")
            sources.append(data)

        def composite(data, electric=False):
            image = [[None] * 24 for _ in range(23)]
            for layer in (2, 1, 0):
                frame = data[layer * 64:(layer + 1) * 64]
                for y in range(21):
                    for x in range(24):
                        byte = frame[y * 3 + x // 8]
                        if electric or layer == 2:
                            color = ((7, 1, 7)[layer] if electric else 1) if byte & (0x80 >> (x % 8)) else None
                        else:
                            color = (None, 10, (7, 6)[layer], 2)[(byte >> (6 - 2 * ((x % 8) // 2))) & 3]
                        if color is not None:
                            image[y + layer][x] = color
            return image

        def reduce(image, height, candidates, coverage_denominator, extra_color=None):
            source_height = len(image)
            quantized = {color: min(candidates, key=lambda target: sum(
                (a - b) ** 2 for a, b in zip(self.palette[color], self.palette[target])))
                for color in range(16)}
            planes = [bytearray(64) for _ in range(2 if extra_color is not None else 1)]
            for y in range(height):
                for x in range(6):
                    votes = Counter()
                    total = 0
                    for source_y in range(source_height):
                        weight = max(0, min((y + 1) * source_height, (source_y + 1) * height)
                                     - max(y * source_height, source_y * height))
                        for source_x in range(x * 4, x * 4 + 4):
                            total += weight
                            color = image[source_y][source_x]
                            if color is not None:
                                votes[quantized[color]] += weight
                    if sum(votes.values()) * coverage_denominator < total:
                        continue
                    color = max(votes, key=lambda candidate: (votes[candidate], candidate == 7, candidate))
                    plane, code = (1, 2) if color == extra_color else (0, {10: 1, 7: 2, 2: 3}[color])
                    planes[plane][y * 3 + x // 4] |= code << (6 - 2 * (x % 4))
            return b"".join(planes)

        walk, jump, electric, balls = sources
        result = bytearray()
        for triplet in (walk[:192], walk[384:576], jump):
            result.extend(reduce(composite(triplet), 8, (10, 7, 6, 2), 5, 6))
        result.extend(reduce(composite(electric, True), 10, (7, 1), 5, 1))
        for offset in (0, 64):
            frame = balls[offset:offset + 64]
            image = [[(None, 10, 7, 2)[(frame[y * 3 + x // 8] >> (6 - 2 * ((x % 8) // 2))) & 3]
                      for x in range(24)] for y in range(21)]
            assert all(color is None for row in image[:5] for color in row)
            result.extend(reduce(image[5:], 6, (10, 7, 2), 2))
        return bytes(result)

    def decode_level2_player_art(self):
        """Composite the original three planes, then area-vote them at23/8.

        Integer area weights keep this independent of the builder's floating
        point reduction. Each output multicolor pixel covers4 source pixels.
        """
        original = (ROOT / "giana/assets/original-sprites-giana.bin").read_bytes()
        assert digest(original) == "00cc787a7bed3d67516782d9eb2816088844317a714d2e27d5c8e45beafc2944"
        result = bytearray()
        candidates = (10, 7, 6, 2)
        quantized = {color: min(candidates, key=lambda target: sum(
            (a - b) ** 2 for a, b in zip(self.palette[color], self.palette[target]))) for color in range(16)}
        for pose in range(4):
            pixels = [[None] * 24 for _ in range(23)]
            for layer in (2, 1, 0):
                source = original[(pose * 3 + layer) * 64:(pose * 3 + layer + 1) * 64]
                for y in range(21):
                    for x in range(24):
                        byte = source[y * 3 + x // 8]
                        if layer == 2:
                            color = 1 if byte & (0x80 >> (x % 8)) else None
                        else:
                            color = (None, 10, (7, 6)[layer], 2)[(byte >> (6 - 2 * ((x % 8) // 2))) & 3]
                        if color is not None:
                            pixels[y + layer][x] = color
            planes = [bytearray(64), bytearray(64)]
            for y in range(8):
                for x in range(6):
                    weights = Counter()
                    total = 0
                    for source_y in range(23):
                        weight = max(0, min((y + 1) * 23, (source_y + 1) * 8) - max(y * 23, source_y * 8))
                        for source_x in range(x * 4, x * 4 + 4):
                            total += weight
                            color = pixels[source_y][source_x]
                            if color is not None:
                                weights[quantized[color]] += weight
                    if 5 * sum(weights.values()) < total:
                        continue
                    color = max(weights, key=lambda candidate: (weights[candidate], candidate == 7, candidate))
                    plane, code = (1, 2) if color == 6 else (0, {10: 1, 7: 2, 2: 3}[color])
                    planes[plane][y * 3 + x // 4] |= code << (6 - 2 * (x % 4))
            result.extend(planes[0])
            result.extend(planes[1])
        return bytes(result)

    @staticmethod
    def decode_level2_stream():
        """Expand original block records independently of the asset builder."""
        assets = ROOT / "giana/assets"
        source_files = (
            ("original-level2-stream.bin", "c8a93fc534bcea121b4632a417e3582797246e083dd9496641681929b8e71ce1"),
            ("original-level2-block-pointers.bin", "2f8b7e4a97adbb557db2495b599f5a57106647681f8c1d6f1c0d675e9e0b4caf"),
            ("original-level2-block-data.bin", "49b9c157f3180a60ae3adbafddf054991604c310bd6367d50b39e9df82e816e6"),
        )
        source = []
        for name, expected_hash in source_files:
            data = (assets / name).read_bytes()
            assert digest(data) == expected_hash, f"Original Level2 source changed: {name}"
            source.append(data)
        stream, pointers, blocks = source
        result = bytearray(256 * 20)
        assert stream[-1] == 255 and (len(stream) - 1) % 5 == 0
        for offset in range(0, len(stream) - 1, 5):
            block, low, high, across, down = stream[offset:offset + 5]
            assert block * 2 + 2 <= len(pointers) and across and down
            source_offset = int.from_bytes(pointers[block * 2:block * 2 + 2], "little") - 0x9286
            assert 0 <= source_offset < len(blocks) - 1
            width, height = blocks[source_offset] + 1, blocks[source_offset + 1] + 1
            pattern = blocks[source_offset + 2:source_offset + 2 + width * height]
            assert len(pattern) == width * height
            for y in range(height * down):
                for x in range(width * across):
                    destination = low + high * 256 + y * 256 + x
                    assert 0 <= destination < len(result)
                    result[destination] = pattern[(y % height) * width + x % width]
        return bytes(result)

    def decode_original_terrain(self):
        """Sample the original character scene, never the generated TV tile data."""
        charset = (ROOT / "giana/assets/original-charset.bin").read_bytes()
        attributes = (ROOT / "giana/assets/original-char-colors.bin").read_bytes()
        assert len(charset) == 2048 and len(attributes) == 256
        destinations = (8, 9, 14, 5, 7) if self.source_level == 1 else (*self.terrain_colors, 5, 7)
        quantized = []
        for rgb in self.palette:
            errors = [sum((a - b) ** 2 for a, b in zip(rgb, self.palette[color]))
                      for color in destinations]
            quantized.append(destinations[errors.index(min(errors))])
        quantized[self.source_colors[0]] = self.terrain_colors[0] if self.source_level == 2 else 14
        def sample(mapping):
            semantic = []
            for y in range(64):
                source_y = (10 * y + 5) // 4
                row = []
                for x in range(512):
                    source_x = x * 4 + 2
                    character = mapping[(source_y // 8) * 256 + x // 2]
                    bits = charset[character * 8 + source_y % 8]
                    attribute = attributes[character]
                    if attribute & 8:
                        code = (bits >> (6 - 2 * ((source_x % 8) // 2))) & 3
                        original = (*self.source_colors, attribute & 7)[code]
                    else:
                        original = attribute if bits & (0x80 >> (source_x % 8)) else self.source_colors[0]
                    row.append(quantized[original])
                semantic.append(tuple(row))
            return tuple(semantic)

        self.semantic_rows = sample(self.original_map)
        self.spent_block_rows = None
        if self.source_level == 1:
            used = bytearray(self.original_map)
            for row, characters in enumerate(((0x4c, 0x4d, 0x4e), (0x4f, 0x50, 0x51)), 3):
                used[row * 256 + 46:row * 256 + 49] = bytes(characters)
            self.spent_block_rows = sample(used)

    def terrain_pixel(self, world_x, source_y, event_step=None):
        color = self.semantic_rows[source_y][world_x]
        if (self.source_level == 1 and event_step is not None and event_step >= 80
                and 92 <= world_x < 98 and 9 <= source_y < 16):
            if event_step == 80:
                color = self.semantic_rows[source_y + 1][world_x] if source_y < 15 else 14
            else:
                color = self.spent_block_rows[source_y][world_x]
        return self.terrain_colors.index(color) if color in self.terrain_colors else 3

    @lru_cache(maxsize=4096)
    def expected_accent_flags(self, region, phase, column):
        flags = 0
        for row in range(8):
            samples = Counter(self.semantic_rows[y][(column * 4 + phase + x) % 512]
                              for y in REGION_SOURCE_ROWS[region][row * 8:row * 8 + 8] if y >= 0
                              for x in range(4))
            if samples[7] and samples[7] >= samples[5]:
                flags |= 1 << row
        return flags

    @lru_cache(maxsize=1024)
    def expected_bitmap(self, step, event_step=None):
        bitmap = bytearray(self.bitmap)
        for y in range(64):
            for byte_x in range(10):
                packed = 0
                for pixel in range(4):
                    world_x = (step + byte_x * 4 + pixel) % 512
                    source_y = REGION_SOURCE_ROWS[REGION_COLUMNS[byte_x]][y]
                    code = 3 if source_y < 0 else self.terrain_pixel(world_x, source_y, event_step)
                    packed = (packed << 2) | code
                cell = (y // 8 + 3) * 40 + 23 + byte_x
                bitmap[cell * 8 + y % 8] = packed
        return bytes(bitmap)

    def expected_colors(self, step, level, hidden=False):
        mapping = LIGHT_MAPS[level]
        screen = bytearray(self.screen)
        colors = bytearray(self.colors)
        for cell in self.light:
            original = self.screen[cell]
            screen[cell] = (mapping[original >> 4] << 4) | mapping[original & 15]
            colors[cell] = mapping[self.colors[cell]]
        for column in range(10):
            region = REGION_COLUMNS[column]
            flags = self.expected_accent_flags(region, step % 4, (step // 4 + column) % 128)
            for row in range(8):
                cell = (row + 3) * 40 + 23 + column
                screen[cell] = 0x99 if hidden else self.game_screen
                colors[cell] = 9 if hidden else 0 if REGION_MASK_ROWS[region] & (1 << row) else 7 if flags & (1 << row) else 5
        return bytes(screen), bytes(colors)

    def decode(self, bitmap, screen, color_ram):
        rgb = bytearray()
        for y in range(200):
            for column in range(40):
                cell = (y // 8) * 40 + column
                packed = bitmap[cell * 8 + y % 8]
                colors = (self.background, screen[cell] >> 4, screen[cell] & 15, color_ram[cell])
                for shift in (6, 4, 2, 0):
                    rgb.extend(self.palette[colors[(packed >> shift) & 3]] * 2)
        return Image.frombytes("RGB", (320, 200), bytes(rgb))

    def verify_protected_pixels(self, bitmap, screen, color_ram):
        for cell, offset, shift, original_color in self.protected_pixels:
            colors = (self.background, screen[cell] >> 4, screen[cell] & 15, color_ram[cell])
            assert colors[(bitmap[offset] >> shift) & 3] == original_color, (cell, original_color)

    def verify_music_state(self, frame, ram):
        call = self.music_reference["calls"][frame]
        assert ram[0x41d0:0x4289] == bytes.fromhex(call["state"]), (frame, "Original SID mutable state differs")
        assert ram[0x4ac2:0x4acb] == bytes.fromhex(call["bookmark"]), (frame, "Original SID bookmarks differ")
        assert ram[0x41ec] == 0, "Cue1 must leave the sampler and CIA2 path disabled"
        for first, end in ((0x41c0, 0x41d0), (0x4289, 0x4ac2), (0x4acb, 0x5fdd)):
            assert ram[first:end] == self.music[first - 0x41c0:end - 0x41c0], (frame, "Original driver/score changed", hex(first))

    @staticmethod
    def sprite_code(data, pair, row):
        return (data[row * 3 + pair // 4] >> (6 - 2 * (pair % 4))) & 3

    @staticmethod
    def project_actor_foot(foot, x_mc):
        center = max(0, min(39, x_mc + 3))
        if foot < 28:
            return foot + (2 if center < 12 else 1 if center < 28 else 0)
        if foot >= 36 and center < 20:
            return foot - 1
        return foot

    def clipped_sprite(self, frame, x_mc, enabled):
        if not enabled:
            return bytes(64)
        data = bytearray(self.sprite_atlas[frame * 64:(frame + 1) * 64])
        for row in range(21):
            for pair in range(12):
                if not 0 <= x_mc + pair < 40:
                    data[row * 3 + pair // 4] &= ~(3 << (6 - 2 * (pair % 4)))
        return bytes(data)

    def expected_sprites(self, frame, step=None):
        if step is None:
            step = 0 if frame == 0 else ((frame - 1) // 4) % 512
        foot = self.player_path[step]
        pose = 2 * (step & 3)
        height = self.player_height
        form = "punk"
        player_x = 10
        if self.source_level == 1 and step < 100:
            if step < 93:
                height, form = 8, "small"
                pose = 28 if (not self.original_route_support[step] or 78 <= step < 84) else 24 + 2 * (step & 1)
                if step == 66:
                    pose = 26
                if 64 <= step <= 66:
                    player_x = 9
                if 79 <= step <= 81:
                    player_x = 11
                if 78 <= step < 84:
                    foot = INTRO_JUMP_FEET[step - 78]
            else:
                pose, height, form = 30, 10, "electric"
        player_visible = foot != 255
        player_y = 74 + self.project_actor_foot(foot, player_x) - height if player_visible else 0
        if self.source_level == 1:
            enemy_x = 40 - (step & 63)
            enemy_ground = self.actor_ground[(((step & ~63) + 43) % 512) // 2]
            enemy_visible = player_visible and -5 <= enemy_x <= 39 and enemy_ground != 255 and enemy_ground >= 28
            enemy_y = 74 + self.project_actor_foot(enemy_ground, enemy_x) - 9 if enemy_visible else 0
            enemies = ({"x": enemy_x, "y": enemy_y - 74, "frame": 8 + ((step >> 1) & 1) if enemy_visible else 255,
                        "source_entry": None, "type": 5},
                       {"x": 0, "y": 0, "frame": 255, "source_entry": None, "type": None})
            if 81 <= step <= 92:
                enemies = (enemies[0], {"x": INTRO_BALL_X[step - 81], "y": INTRO_BALL_Y[step - 81],
                                       "frame": 32 + (step & 1), "source_entry": None, "type": None})
        else:
            enemies = self.expected_level2_enemies(step)
        poses = (pose, pose + 1, *(enemy["frame"] for enemy in enemies))
        positions = ((player_x, player_y), (player_x, player_y), *((enemy["x"], enemy["y"] + 74) for enemy in enemies))
        enabled = (player_visible, player_visible, *(player_visible and enemy["frame"] != 255 for enemy in enemies))
        buffers = [self.clipped_sprite(pose, position[0], visible)
                   for pose, position, visible in zip(poses, positions, enabled)]
        if self.source_level == 1 and step in (81, 82):
            # Native emergence reveals two source-canvas rows, then four.
            partial = bytearray(buffers[3])
            partial[(2 if step == 81 else 4) * 3:] = bytes(64 - (2 if step == 81 else 4) * 3)
            buffers[3] = bytes(partial)
        main_colors = [SPRITE_MAIN_COLORS[pose] if pose != 255 else 1 for pose in poses]
        if form == "electric":
            main_colors[:2] = ((7, 1, 3, 1)[(step - 93) & 3], 1)
        return {"step": step, "poses": poses, "positions": positions, "visible": enabled,
                "height": height, "form": form,
                "pickup_slots": (3,) if self.source_level == 1 and 81 <= step <= 92 else (),
                "enabled": sum((1 << slot) for slot, visible in enumerate(enabled) if visible),
                "x_high": 6 | sum(1 << (slot + 4) for slot in (2, 3) if enabled[slot] and positions[slot][0] >= 24),
                "main_colors": tuple(main_colors),
                "enemy_entries": tuple(enemy["source_entry"] for enemy in enemies),
                "enemy_types": tuple(enemy["type"] for enemy in enemies), "buffers": tuple(buffers)}

    def verify_sprites(self, frame, ram, vic, work_addresses, step=None, hidden=False):
        actors = self.expected_sprites(frame, step)
        expected_enables = 0x07 if hidden else 0x0f | actors["enabled"] << 4
        assert vic[0x15] == expected_enables, (frame, "sprite enables", vic[0x15], expected_enables)
        x_high_mask = 255 if hidden else 0x3f | (actors["enabled"] << 4)
        assert vic[0x10] & x_high_mask == (6 if hidden else actors["x_high"]), (frame, "sprite X high bits")
        assert all(vic[register] == 0 for register in (0x17, 0x1b, 0x1d)), "Sprites must be foreground and unexpanded"
        assert vic[0x1c] == 0xf0, "Multiplexed corners and highlight must be hires; all four actor planes must be multicolor"
        assert tuple(vic[register] & 15 for register in range(0x25, 0x2b)) == (10, 2, 0, 0, 0, 3)
        assert ram[0x07f8:0x0800] == bytes((8, 9, 11, 0x3d, *(address // 64 for address in work_addresses)))
        assert ram[0x0c00:0x0e80] == self.shared_sprite_atlas, "Immutable original sprite atlas changed"
        if self.source_level == 2:
            assert ram[0x1a00:0x1c00] == self.level2_player_planes, "Immutable Level2 Giana art changed"
        assert ram[0x1c00:0x1f80] == self.extra_enemy_frames, "Immutable original enemy art changed"
        assert ram[0x0f40:0x0f80] == self.highlight_data, "Highlight differs from retained source grid"
        assert ram[0x0200:0x0300] == self.corner_data, "Corner masks differ from the fixed physical-pixel radius profile"
        for slot, position in ((0, self.corner_positions[0]), (1, self.corner_positions[1]), (2, self.corner_positions[3])):
            assert (vic[slot * 2] + (256 if vic[0x10] & (1 << slot) else 0), vic[slot * 2 + 1]) == position, (
                frame, slot, "Corner position")
        assert (vic[6], vic[7]) == (208, 77), "Highlight must stay three pixels below the TV top-left"
        for slot, (address, position, expected_data) in enumerate(zip(work_addresses, actors["positions"], actors["buffers"])):
            x_mc, y_hw = position
            if hidden or not actors["visible"][slot]:
                continue
            hardware_slot = slot + 4
            assert vic[hardware_slot * 2] == (208 + 2 * x_mc) & 255, (frame, slot, "sprite X")
            assert vic[hardware_slot * 2 + 1] == y_hw, (frame, slot, "sprite Y")
            assert ram[address:address + 64] == expected_data, (frame, slot, "sprite pose or clipping")
            assert vic[0x27 + hardware_slot] & 15 == actors["main_colors"][slot], (frame, slot, "Original sprite color")
        return actors

    def sprite_pixels(self, actors):
        pixels = {}
        # Lower hardware sprite numbers win where the two Giana planes overlap.
        for slot in reversed(range(4)):
            if not actors["visible"][slot]:
                continue
            x_mc, y_hw = actors["positions"][slot]
            colors = (None, 10, actors["main_colors"][slot], 2)
            for row in range(21):
                y = y_hw - 50 + row
                for pair in range(12):
                    code = self.sprite_code(actors["buffers"][slot], pair, row)
                    if not code:
                        continue
                    x = x_mc + pair
                    assert 0 <= x < 40 and 24 <= y < 88, (slot, x, y, "sprite outside TV")
                    region = REGION_COLUMNS[x // 4]
                    assert REGION_SOURCE_ROWS[region][y - 24] >= 0, (slot, x, y, "sprite over perspective mask")
                    screen_x = 184 + x * 2
                    pixels[(screen_x, y)] = colors[code]
                    pixels[(screen_x + 1, y)] = colors[code]
        # The fixed hires glass highlight occupies hardware slot3, above actors.
        # Moving-actor containment above stays strict, including black masks.
        pixels.update(self.highlight_pixels)
        # Three foremost slots draw four corners, with the left slot reused.
        pixels.update(self.corner_pixels)
        return pixels

    def sprite_opaque_pixels(self, actors, slot):
        if not actors["visible"][slot]:
            return set()
        x_mc, y_hw = actors["positions"][slot]
        return {(x_mc + pair, y_hw - 50 + row)
                for row in range(21) for pair in range(12)
                if self.sprite_code(actors["buffers"][slot], pair, row)}

    def hazard_pixels(self, actors):
        return set().union(*(self.sprite_opaque_pixels(actors, slot) for slot in (2, 3)
                             if slot not in actors["pickup_slots"]))

    def visible_enemy_entries(self, actors):
        """Count an enemy only if an opaque pixel survives sprite priority."""
        covered = set(self.corner_pixels) | set(self.highlight_pixels)
        result = set()
        for slot in range(4):
            points = {(184 + x * 2 + offset, y)
                      for x, y in self.sprite_opaque_pixels(actors, slot) for offset in (0, 1)}
            if slot >= 2 and actors["enemy_entries"][slot - 2] is not None and points - covered:
                result.add(actors["enemy_entries"][slot - 2])
            covered.update(points)
        return result

    @staticmethod
    def verify_left_corner(vic, pointers, bottom):
        assert pointers[0] == (10 if bottom else 8), "Wrong frame selected for multiplexed left corner"
        assert (vic[0], vic[1]) == (208, 117 if bottom else 74), "Wrong multiplexed corner position"
        assert vic[0x10] & 7 == 6 and vic[0x15] & 7 == 7, "All rounded corners must remain enabled"
        assert all(vic[register] & 1 == 0 for register in (0x17, 0x1b, 0x1c, 0x1d))
        assert vic[0x27] & 15 == 0

    def rendered_solid(self, camera_step, x_mc, target_y, visible=False, event_step=None):
        if not 0 <= x_mc < 40 or not 0 <= target_y < 64:
            return False
        source_y = REGION_SOURCE_ROWS[REGION_COLUMNS[x_mc // 4]][target_y]
        if source_y < 0:
            return False
        world_x = (camera_step + x_mc) % 512
        character = self.original_map[((10 * source_y + 5) // 32) * 256 + world_x // 2]
        solid = self.collision_flags[character] in (1, 0x80)
        return solid and (not visible or self.terrain_pixel(world_x, source_y, event_step) != self.empty_code)

    def player_support(self, camera_step, actors):
        player = self.sprite_opaque_pixels(actors, 0) | self.sprite_opaque_pixels(actors, 1)
        assert player
        bottom = max(y for _, y in player)
        feet = sorted(x for x, y in player if y == bottom)
        foot_y = bottom - 23
        logical_contact = sum(self.rendered_solid(camera_step, x, foot_y) for x in feet)
        visible_contact = sum(self.rendered_solid(camera_step, x, foot_y, True, actors["step"]) for x in feet)
        logical_penetration = sum(self.rendered_solid(camera_step, x, foot_y - 1) for x in feet)
        visible_penetration = sum(self.rendered_solid(camera_step, x, foot_y - 1, True, actors["step"]) for x in feet)
        visible_body_penetration = sum(self.rendered_solid(camera_step, x, y - 24, True, actors["step"]) for x, y in player)
        enemy = self.hazard_pixels(actors)
        enemy_contact = sum((x, bottom + 1) in enemy for x in feet)
        visible_below = [y - foot_y for y in range(max(0, foot_y), 64)
                         if any(self.rendered_solid(camera_step, x, y, True, actors["step"]) for x in feet)]
        return {"step": actors["step"], "foot_y": foot_y, "foot_columns": feet,
                "logical_contact_pixels": logical_contact, "visible_contact_pixels": visible_contact,
                "logical_penetration_pixels": logical_penetration, "visible_penetration_pixels": visible_penetration,
                "visible_body_penetration_pixels": visible_body_penetration,
                "enemy_contact_pixels": enemy_contact,
                "logical_state": "penetrating" if logical_penetration else "grounded" if logical_contact else "airborne",
                "visible_state": "penetrating" if visible_penetration else "grounded" if visible_contact else "airborne",
                "visible_support_gap": min(visible_below) if visible_below else None}

    def route_support_states(self):
        count = 512 if self.source_level == 1 else 472
        return [self.player_support(step, self.expected_sprites(step * 4 + 1)) for step in range(count)]

    def verify_opening_contract(self, actors_by_step):
        """Check the visible story against original level geometry and opaque art."""
        assert self.source_level == 1
        assert all(step in actors_by_step for step in range(105)), "Opening proof needs every camera state through104"
        assert actors_by_step[0]["form"] == "small" and actors_by_step[0]["height"] == 8
        player = {step: self.sprite_opaque_pixels(actors_by_step[step], 0)
                        | self.sprite_opaque_pixels(actors_by_step[step], 1) for step in range(105)}
        for step in range(105):
            for camera in (step, step + 1):
                support = self.player_support(camera, actors_by_step[step])
                assert not support["visible_body_penetration_pixels"], (
                    step, camera, "Opening art enters terrain during its current or held camera phase")
        platform_contacts = []
        for step in range(78):
            support = self.player_support(step, actors_by_step[step])
            if (support["foot_y"] == 32 and support["visible_contact_pixels"]
                    and any(80 <= step + x < 116 for x in support["foot_columns"])):
                platform_contacts.append(step)
        assert {72, 73, 74, 75, 76, 77} <= set(platform_contacts), "Small Giana did not settle on the first platform"

        top = min(y for _, y in player[80])
        head_contact = [(x, y) for x, y in player[80]
                        if y == top and 92 <= 80 + x < 98 and self.rendered_solid(80, x, y - 25, True)]
        assert top < min(y for _, y in player[79]) and head_contact, "The upward jump missed the first power-up block"
        ball_steps = [step for step in range(105) if actors_by_step[step]["pickup_slots"]]
        assert ball_steps == list(range(81, 93)), "The ball must emerge after the block strike and remain until pickup"
        balls = {step: self.sprite_opaque_pixels(actors_by_step[step], 3) for step in ball_steps}
        assert all(balls.values()), "The released ball has no opaque pixels"
        assert max(y for _, y in balls[81]) <= 34, "The ball did not emerge above the struck block"
        assert min(y for _, y in balls[83]) < min(y for _, y in balls[81]), "The emerging ball never rose"
        exposed = [max(y for _, y in balls[step]) - min(y for _, y in balls[step]) + 1 for step in (81, 82, 83)]
        assert exposed == [2, 4, 6], ("The ball did not progressively emerge", exposed)
        for step in ball_steps:
            assert balls[step] - player[step] - self.sprite_opaque_pixels(actors_by_step[step], 2), (
                step, "Released ball is completely hidden by another actor")
            assert not any(self.rendered_solid(camera, x, y - 24, True, step)
                           for camera in (step, step + 1) for x, y in balls[step]), (
                step, "The emerging ball enters rendered terrain")
        world_xs = [step + actors_by_step[step]["positions"][3][0] for step in ball_steps]
        assert world_xs == [92, 94, 96, 98, 100, 102, 104, 104, 104, 104, 104, 104]
        pickup_contacts = [step for step in ball_steps if player[step] & balls[step]]
        assert pickup_contacts == [92], ("The ball must visibly touch small Giana before disappearing", pickup_contacts)
        assert actors_by_step[92]["form"] == "small" and not actors_by_step[93]["pickup_slots"]
        for step in range(93, 100):
            actors = actors_by_step[step]
            assert actors["form"] == "electric" and actors["poses"][:2] == (30, 31)
            assert self.player_support(step, actors)["visible_contact_pixels"], (step, "Electric Giana floats above the platform")
        assert {actors_by_step[step]["main_colors"][0] for step in range(93, 100)} == {1, 3, 7}
        for step in range(100, 105):
            actors = actors_by_step[step]
            assert actors["form"] == "punk" and actors["height"] == 10
            assert actors["poses"][:2] == (2 * (step & 3), 2 * (step & 3) + 1)
            assert actors["main_colors"][:2] == (7, 6) and not actors["pickup_slots"]
        return {"small_start_step": 0, "settled_first_platform_steps": platform_contacts,
                "first_powerup_block_head_contact_step": 80,
                "first_powerup_block_contact_world_columns": sorted(80 + x for x, _ in head_contact),
                "ball_visible_steps": ball_steps, "ball_emergence_rows": exposed,
                "ball_world_x_by_visible_step": world_xs, "ball_opaque_pickup_contact_steps": pickup_contacts,
                "electric_steps": list(range(93, 100)), "punk_start_step": 100,
                "opening_camera_states_checked": 105,
                "current_and_held_camera_body_penetrations": 0, "ball_terrain_penetrations": 0}

    def route_motion_diagnostics(self, states):
        count = len(states)
        cyclic = self.source_level == 1
        supported = [bool(state["visible_contact_pixels"] or state["enemy_contact_pixels"])
                     and not state["visible_body_penetration_pixels"] for state in states]
        feet = [state["foot_y"] for state in states]
        deltas = [feet[step] - feet[step - 1] if step or cyclic else 0 for step in range(count)]
        launches = []
        landings = []
        hover_runs = []
        midair_relaunches = []
        acceleration_resets = []
        missed_landings = []
        anchor = next((step for step, contact in enumerate(supported) if contact), 0)
        descending = False
        steps = ((anchor + offset) % count for offset in range(1, count + 1)) if cyclic else range(1, count)
        for step in steps:
            previous = (step - 1) % count
            if supported[step]:
                if not supported[previous]:
                    landings.append(step)
                descending = False
            else:
                if supported[previous]:
                    launches.append(step)
                    descending = False
                if descending and deltas[step] < 0:
                    midair_relaunches.append(step)
                if deltas[step] > 0:
                    descending = True
                if not supported[previous] and deltas[step] - deltas[previous] < -1:
                    acceleration_resets.append(step)
            if deltas[step] > 0:
                crossed = [(x, y) for x in states[step]["foot_columns"]
                           for y in range(feet[previous], feet[step])
                           if self.rendered_solid(step, x, y, True)]
                if crossed:
                    missed_landings.append({"step": step, "first_crossed_pixel": list(crossed[0])})
        for start in range(count):
            if supported[start] or ((start or cyclic) and not supported[start - 1] and feet[start - 1] == feet[start]):
                continue
            length = 0
            while (length < count if cyclic else start + length < count) and not supported[(start + length) % count] and feet[(start + length) % count] == feet[start]:
                length += 1
            if length > 3:
                following = (start + length) % count
                rounded_apex = ((cyclic or 0 < start and start + length < count)
                                and length == 4 and feet[start - 1] == feet[start] + 1
                                and (feet[following] == feet[start] + 1 or supported[following]))
                hover_runs.append({"start": start, "length": length, "foot_y": feet[start],
                                   "rounded_ballistic_apex": rounded_apex})
        counts = Counter(state["visible_state"] for state in states)
        return {"visible_counts": dict(counts), "terrain_contact_steps": counts["grounded"],
                "enemy_support_steps": sum(bool(state["enemy_contact_pixels"]) for state in states),
                "unsupported_steps": sum(not contact for contact in supported),
                "body_penetration_states": [state["step"] for state in states if state["visible_body_penetration_pixels"]],
                "launch_steps": launches, "landing_steps": landings, "hover_runs": hover_runs,
                "midair_relaunch_steps": midair_relaunches, "upward_acceleration_resets": acceleration_resets,
                "missed_landings": missed_landings,
                "maximum_y_step": max(abs(delta) for delta in deltas)}

    def ground_diagnostic(self, states, destination, title):
        image = Image.new("RGB", (1024, 192), (24, 24, 24))
        draw = ImageDraw.Draw(image)
        counts = Counter(state["visible_state"] for state in states)
        draw.text((8, 4), f"{title}: grounded {counts['grounded']}, air {counts['airborne']}, penetration {counts['penetrating']}", fill="white")
        draw.text((8, 17), "Terrain beneath player center; dots show actual opaque feet: green=contact, yellow=air, red=penetration", fill=(220, 220, 220))
        for step, state in enumerate(states):
            column = (step // 4 + 3) % 128
            flags = self.expected_accent_flags(1, step % 4, column)
            world_x = (step + 13) % 512
            for y, source_y in enumerate(REGION_SOURCE_ROWS[1]):
                accent = 0 if REGION_MASK_ROWS[1] & (1 << (y // 8)) else 7 if flags & (1 << (y // 8)) else 5
                color = 0 if source_y < 0 else (*self.terrain_colors, accent)[self.terrain_pixel(world_x, source_y)]
                draw.rectangle((step * 2, 32 + y * 2, step * 2 + 1, 33 + y * 2), fill=self.palette[color])
            point_color = {"grounded": (40, 255, 70), "airborne": (255, 255, 0), "penetrating": (255, 30, 30)}[state["visible_state"]]
            y = max(0, min(63, state["foot_y"]))
            draw.rectangle((step * 2, 32 + y * 2, step * 2 + 1, 33 + y * 2), fill=point_color)
        for step in range(0, 512, 64):
            draw.text((step * 2, 163), str(step), fill="white")
        draw.text((8, 178), f"Horizontal axis: active camera/actor steps 0..{len(states) - 1}; terrain sampled beneath Giana.", fill=(220, 220, 220))
        image.save(destination)

    def verify_actor_clearance(self, actors):
        step = actors["step"]
        assert actors["visible"][0] and actors["visible"][1], (step, "Giana disappeared")
        player = self.sprite_opaque_pixels(actors, 0) | self.sprite_opaque_pixels(actors, 1)
        assert player, (step, "Giana has no visible art")
        enemy = self.hazard_pixels(actors)
        assert not player & enemy, (step, "Opaque Giana/enemy collision", sorted(player & enemy))
        enemy_x = actors["positions"][2][0]
        if self.source_level == 1 and actors["visible"][2] and max(10, enemy_x) <= min(15, enemy_x + 5):
            assert enemy
            clearance = min(y for _, y in enemy) - max(y for _, y in player) - 1
            return step & ~63, clearance
        return None

    def composite_sprites(self, bitmap_image, sprite_pixels):
        result = bitmap_image.copy()
        for position, color in sprite_pixels.items():
            result.putpixel(position, self.palette[color])
        return result


def breakpoint(monitor, address):
    response = monitor.run(f"break {address:04x}")
    match = re.search(r"BREAK:\s*(\d+)", response)
    assert match, response
    return int(match[1])


def check_corner_phase(monitor, output, name, reference, bottom):
    monitor.run("bank ram")
    pointers = monitor.memory(output / f"corner-{name}-pointers.bin", 0x07f8, 0x07ff)
    monitor.run("bank io")
    vic = monitor.memory(output / f"corner-{name}-vic.bin", 0xd000, 0xd03f)
    reference.verify_left_corner(vic, pointers, bottom)
    monitor.run("bank cpu")


def verify_mci_tail(monitor, output, labels, reference, mci, args, handoff, frozen_image, old_breaks, prefix):
    """Follow the real loader and its music IRQ, then capture complete MCI fields."""
    for identifier in old_breaks:
        monitor.run(f"disable {identifier}")
    music_start_break = breakpoint(monitor, labels["mciMusicStart"])
    music_done_break = breakpoint(monitor, labels["mciMusicDone"])
    monitor.run(f"disable {music_done_break}")
    field_break = breakpoint(monitor, labels["mciFrameComplete"])
    music_samples = []
    fields = []
    stage_samples = []
    stage_frames = {}
    field_images = []
    previous_music_cycles = handoff["music_start_cycles"]
    previous_frame = handoff["frame"]
    frozen_captures = []
    first_field_cycles = None
    first_field_frame = None
    while previous_frame < args.frames or len(fields) < 120:
        monitor.run("x")
        pc, raster, cycles = monitor.registers()
        monitor.run("bank ram")
        control = monitor.memory(output / "mci-control.bin", labels["mciState"], labels["mciResidentEnd"] - 1)
        def value(name):
            return control[labels[name] - labels["mciState"]]
        frame_offset = labels["mciMusicFrame"] - labels["mciState"]
        actual_frame = int.from_bytes(control[frame_offset:frame_offset + 2], "little")
        state, stage = value("mciState"), value("mciLoadStage")
        assert state in (1, 2) and stage in (1, 2, 3, 4), (actual_frame, "Invalid MCI loader state", state, stage)
        stage_frames.setdefault(stage, actual_frame)
        monitor.run("bank cpu")
        if pc == labels["mciMusicStart"]:
            assert actual_frame == previous_frame + 1, ("MCI music tick skipped/repeated", actual_frame, previous_frame)
            assert actual_frame < len(reference.music_reference["calls"]), "Extend the actual VSID reference for the measured loader window"
            cadence = cycles - previous_music_cycles
            # The first IRQ replaces a polling call. Its entry/save instructions
            # may move that one call within the same raster line.
            allowed = 63 if not music_samples else 9
            assert abs(cadence - 19656) <= allowed, (actual_frame, "MCI music cadence", cadence)
            assert 64 <= raster <= 65, (actual_frame, "MCI music raster", raster)
            monitor.run(f"disable {music_start_break}")
            monitor.run(f"enable {music_done_break}")
            monitor.run("x")
            done_pc, done_raster, done_cycles = monitor.registers()
            assert done_pc == labels["mciMusicDone"] and done_raster < 115, (actual_frame, "MCI music deadline", done_pc, done_raster)
            monitor.run(f"disable {music_done_break}")
            monitor.run(f"enable {music_start_break}")
            monitor.run("bank ram")
            ram = monitor.memory(output / "mci-ram.bin", 0, 0xffff)
            reference.verify_music_state(actual_frame, ram)
            sample = {"frame": actual_frame, "music_start_cycles": cycles, "music_done_cycles": done_cycles,
                      "music_update_cycles": done_cycles - cycles, "music_start_raster": raster,
                      "music_completion_raster": done_raster, "music_cadence_cycles": cadence,
                      "music_sequence_position": ram[0x41e4], "mci_state": state, "load_stage": stage}
            music_samples.append(sample)
            stage_samples.append({"frame": actual_frame, "state": state, "stage": stage, "cycles": cycles})
            previous_frame, previous_music_cycles = actual_frame, cycles
            assert actual_frame - handoff["frame"] <= 512 or first_field_cycles is not None, "MCI loading exceeded ten PAL seconds"
            if state == 1 and stage == 1 and len(frozen_captures) < 3:
                monitor.run("bank io")
                vic = monitor.memory(output / "mci-loading-vic.bin", 0xd000, 0xd03f)
                assert vic[0x11] & 0x10, "The old room must remain visible during the first load job"
                monitor.run("bank cpu")
                screenshot = output / f"frozen-{actual_frame:04d}.png"
                monitor.run(f'screenshot "{screenshot}" 2')
                actual = Image.open(screenshot).convert("RGB").crop((32, 35, 352, 235))
                assert actual.tobytes() == frozen_image.tobytes(), (actual_frame, "First load job changed the frozen room")
                frozen_captures.append(actual_frame)
            monitor.run("bank cpu")
        elif pc == labels["mciFrameComplete"]:
            assert state == 2 and stage == 4 and raster == 256, (actual_frame, "Incomplete MCI field", state, stage, raster)
            monitor.run("bank ram")
            ram = monitor.memory(output / "mci-ram.bin", 0, 0xffff)
            phase = ram[labels["mciPhase"]]
            count = int.from_bytes(ram[labels["mciFieldCounter"]:labels["mciFieldCounter"] + 2], "little")
            assert count == len(fields), (actual_frame, "MCI completed-field counter", count, len(fields))
            assert phase == len(fields) % 2, (actual_frame, "MCI phase did not alternate", phase)
            if fields:
                assert abs(cycles - fields[-1]["cycles"] - 19656) <= 9, (actual_frame, "MCI field cadence", cycles - fields[-1]["cycles"])
            monitor.run("bank io")
            vic = monitor.memory(output / "mci-vic.bin", 0xd000, 0xd03f)
            colors = bytes(color & 15 for color in monitor.memory(output / "mci-colors.bin", 0xd800, 0xdbe7))
            cia = monitor.memory(output / "mci-cia.bin", 0xdd00, 0xdd03)
            layout = mci.verify_field(phase, ram, vic, colors, cia)
            monitor.run("bank cpu")
            screenshot = output / f"mci-field-{len(fields):04d}.png"
            monitor.run(f'screenshot "{screenshot}" 2')
            with Image.open(screenshot) as image:
                actual = image.convert("RGB").crop((32, 35, 352, 235))
            actual_bytes, expected_bytes = actual.tobytes(), mci.images[phase].tobytes()
            differences = sum(actual_bytes[offset:offset + 3] != expected_bytes[offset:offset + 3]
                              for offset in range(0, len(actual_bytes), 3))
            assert differences == 0, (actual_frame, phase, "MCI native pixel differences", differences)
            fields.append({"music_frame": actual_frame, "cycles": cycles, "raster": raster,
                           "field": count, "pixel_differences": differences, **layout})
            if first_field_cycles is None:
                first_field_cycles, first_field_frame = cycles, actual_frame
            if count < 2:
                actual.save(BUILD / f"{prefix}-mci-phase-{phase}.png")
                actual.resize((1280, 800), Image.Resampling.NEAREST).save(BUILD / f"{prefix}-mci-phase-{phase}-4x.png")
            if len(field_images) < 120:
                field_images.append(actual)
        else:
            raise AssertionError(("Unexpected post-game checkpoint", hex(pc), actual_frame))
    monitor.run(f"disable {music_start_break}")
    monitor.run(f"disable {field_break}")
    assert len(fields) >= 120 and {field["phase"] for field in fields} == {0, 1}
    assert frozen_captures, "The real first load job never showed its frozen-room stage"
    field_images[0].save(BUILD / f"{prefix}-mci.gif", save_all=True, append_images=field_images[1:],
                         duration=20, loop=0, optimize=False, disposal=1)
    (output / "mci-fields.json").write_text(json.dumps(fields, indent=2) + "\n")
    (output / "mci-music-timing.json").write_text(json.dumps(music_samples, indent=2) + "\n")
    return {"music_samples": music_samples, "fields": fields, "stage_samples": stage_samples,
            "first_field_frame": first_field_frame, "first_field_cycles": first_field_cycles,
            "first_field_delay_pal_frames": first_field_frame - handoff["frame"],
            "frozen_room_screenshot_frames": frozen_captures, "stage_first_music_frames": stage_frames}


def verify(args):
    reference_path = BUILD / "music-discovery/original-call-reference.json"
    if not reference_path.exists() or len(json.loads(reference_path.read_text())["calls"]) <= args.frames:
        subprocess.run([sys.executable, str(ROOT / "giana/tools/prepare-music-reference.py"),
                        "--frames", str(max(5206, args.frames + 1))], check=True)
    references = tuple(SceneReference(level + 1, room) for room, level in PLAYBACK_ORDER)
    scene_references = dict(zip(PLAYBACK_ORDER, references))
    reference = references[0]
    ending_reference = RoomArchiveReference()
    mci_reference = MciReference(reference.palette)
    assert args.frames < len(reference.music_reference["calls"]), "Capture the independent original SID reference for this complete frame range"
    prefix = args.name or ("boy-man-startup" if args.autostart_mode == 2 else "boy-man-chain")
    output = BUILD / f"{prefix}-check"
    output.mkdir(parents=True, exist_ok=True)
    motions = []
    event_steps = []
    for level_reference in references:
        support_states = level_reference.route_support_states()
        motion = level_reference.route_motion_diagnostics(support_states)
        motions.append(motion)
        level_reference.ground_diagnostic(support_states, BUILD / f"{prefix}-level{level_reference.source_level}-strip.png",
                                         f"Level{level_reference.source_level} ground-contact route")
        assert not motion["body_penetration_states"], (level_reference.source_level, motion["body_penetration_states"])
        assert not motion["missed_landings"], (level_reference.source_level, motion["missed_landings"])
        assert not motion["midair_relaunch_steps"], (level_reference.source_level, motion["midair_relaunch_steps"])
        assert not motion["upward_acceleration_resets"], (level_reference.source_level, motion["upward_acceleration_resets"])
        assert all(run["rounded_ballistic_apex"] for run in motion["hover_runs"]), (level_reference.source_level, motion["hover_runs"])
        if level_reference.source_level == 1:
            level_reference.verify_opening_contract({step: level_reference.expected_sprites(step * 4 + 1)
                                                     for step in range(105)})
        event_steps.append(set(motion["launch_steps"]) | set(motion["landing_steps"]) | {0, 1, 470, 471})
    event_steps[0].update(set(range(115)) | {215, 230, 300, 430, 440})
    (BUILD / f"{prefix}-motion.json").write_text(json.dumps({"levels": motions}, indent=2) + "\n")
    motion = motions[0]
    event_frames = {2, 225, 544, 1637, 1681, 1761, 1921, 2045, 2049}
    labels = read_labels(BUILD / "main.sym")
    program = BUILD / "giana.d64"
    runtime = BUILD / "giana-unpacked.prg"
    required = ("initTerrain", "frameStart", "frameDone", "frameCounter", "lightLevel", "incomingTile", "tilePixelX",
                "scrollCountdown", "terrainTiles", "terrainTilesEnd", "terrainMapStart", "terrainMapEnd",
                "terrainAccentMap", "terrainPerspectiveAccentMap", "terrainPerspectiveMiddleAccentMap",
                "terrainPerspectiveRightAccentMap", "tinySpriteFrames", "spriteWork0", "spriteWork1", "spriteWork2", "spriteWork3",
                "actorGround", "actorPlayerPath", "tvHighlightSprite", "cornerMaskFrames",
                "musicFrameStart", "musicFrameDone", "activeLevel", "levelTransition", "levelCameraStep",
                "actorStepLo", "actorStepHi", "actorPlayerPath2", "terrain2Tiles",
                "terrain2TilesEnd", "terrain2MapStart", "terrain2MapEnd", "terrain2AccentMap",
                "terrain2PerspectiveAccentMap", "terrain2PerspectiveMiddleAccentMap", "terrain2PerspectiveRightAccentMap",
                "tinySpriteFrames2", "actorPlayerHeight", "extraEnemyFrames", "cornerSplitStart", "cornerSplitDone",
                "cornerTopRestored", "level2Enemy0X", "level2Enemy0Y", "level2Enemy0Frame",
                "level2Enemy1X", "level2Enemy1Y", "level2Enemy1Frame", "endingState", "endingPacked", "endingPackedEnd",
                "beginMciPart", "mciState", "mciLoadStage", "mciMusicFrame", "mciMusicStart", "mciMusicDone",
                "mciFrameComplete", "mciPhase", "mciFieldCounter", "mciResidentEnd", "introSpriteFrames")
    assert all(name in labels for name in required), "Build the scene before verifying it"
    work_addresses = tuple(labels[name] for name in ("spriteWork0", "spriteWork1", "spriteWork2", "spriteWork3"))
    assert labels["tinySpriteFrames"] == 0x0c00 and work_addresses == (0x0e80, 0x0ec0, 0x0f00, 0x0f80)
    assert labels["tvHighlightSprite"] == 0x0f40
    assert labels["tinySpriteFrames2"] == 0x1a00
    assert labels["extraEnemyFrames"] == 0x1c00
    assert labels["endingPacked"] == 0xe000 and labels["endingPackedEnd"] - labels["endingPacked"] == len(ending_reference.packed)
    assert all(address % 64 == 0 and address + 64 <= 0x1000 for address in work_addresses), "VIC work buffers must avoid the character-ROM window"
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    executable = args.vice or os.environ.get("VICE") or shutil.which("x64sc")
    assert executable, "Set VICE or --vice to a PAL-capable x64sc executable"
    command = vice_command(executable, program, port, reference.palette_path)
    # The real demo disk contains the drive loader and both later image jobs.
    # Host PRG injection or a generated one-file autostart disk cannot prove it.
    option = command.index("-autostartprgmode")
    del command[option:option + 2]
    command += ["-initbreak", "reset", "-warp", "-sidengine", "1", "-sidmodel", "0", "-residsamp", "2",
                "-sounddev", "dump", "-soundarg", str(output / "sid-registers.txt")]
    command += ["-drive8truedrive"]
    result = {"passed": False, "emulator": "PAL VICE x64sc", "disk_sha256": digest(program.read_bytes()),
              "runtime_prg_sha256": digest(runtime.read_bytes()),
              "source_sha256": digest(reference.source),
              "project_sha256": digest(reference.project_path.read_bytes()),
              "game_area_cells": len(reference.game), "screen_light_cells": len(reference.light),
              "viewport_physical": [184, 24, 80, 64], "light_maps": [list(mapping) for mapping in LIGHT_MAPS],
              "protected_colors": list(PROTECTED_COLORS), "global_background": reference.background,
              "perspective_region_bounds_chars": list(REGION_BOUNDS),
              "perspective_source_rows": [list(rows) for rows in REGION_SOURCE_ROWS],
              "perspective_black_mask_rows": list(REGION_MASK_ROWS)}
    result.update({"startup_check": args.autostart_mode == 2, "true_drive_demo_disk": True, "command": command,
                   "music_original_module_sha256": digest(reference.music),
                   "music_original_sid_sha256": digest(reference.music_source), "music_subtune": 3,
                   "music_sid_model": "PAL reSID MOS6581"})
    started = time.monotonic()
    samples = []
    transitions = []
    screenshots = []
    animation = []
    checked_levels = set()
    saved_levels = set()
    saved_source_levels = set()
    observed_scene_order = []
    checked_objects = set()
    sky_blue_verified = False
    blue_clothes_verified = False
    level_actor_steps = [set(), set()]
    level_camera_steps = [set(), set()]
    level_world_columns = [set(), set()]
    level_changes = []
    transition_frames = []
    seen_player_poses = set()
    seen_enemy_poses = set()
    seen_level1_owl_poses = set()
    seen_enemy_entries = set()
    captured_enemy_entries = set()
    maximum_visible_enemies = 0
    maximum_opaque_visible_enemies = 0
    captured_two_enemies = False
    captured_enemy_types = set()
    enemy_representatives = []
    seen_sprite_enables = set()
    seen_clip_modes = set()
    owl_overlap_steps = set()
    cleared_owl_sections = set()
    owl_clearances = []
    previous_actor_step = None
    previous_player_y = None
    maximum_actor_y_delta = 0
    previous_actor_level = None
    previous_cycles = None
    previous_music_cycles = None
    previous_level = None
    last_transition = -100
    last_scene_change = -100
    previous_scene = None
    expected_active = 0
    expected_transition = 0
    expected_camera = 0
    expected_scroll_countdown = 4
    expected_actor_level = 0
    expected_actor_step = 0
    ending_expected = False
    ending_states = []
    ending_blank_frames = []
    ending_visible_frames = []
    ending_screenshots = []
    ending_previous_state = 0
    ending_layout = {"vic_bank": 0, "bitmap_address": 0x2000, "screen_address": 0x0400}
    room7_first_game_frame = None
    room7_selected_saved = False
    expected_light_countdown = 14
    expected_light_phase = 0
    previous_actor_room = None
    room_level_actor_steps = [[set(), set()], [set(), set()]]
    room_level_camera_steps = [[set(), set()], [set(), set()]]
    room_level_world_columns = [[set(), set()], [set(), set()]]
    room_seen_enemy_entries = [set(), set()]
    room_checked_light_levels = [set(), set()]
    opening_native_states = [{}, {}]
    opening_saved_steps = [set(), set()]
    mci_tail = None
    handoff_sample = None
    process = None
    connection = None
    monitor = None
    try:
        with (output / "vice.log").open("w") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            connection = connect_monitor(process, port)
            monitor = Monitor(connection)
            if args.autostart_mode == 2:
                connection.settimeout(180)
            monitor.run("r")
            monitor.run("sidefx off")
            # Spindle's temporary boot code also executes in the BASIC area.
            # Its PCs can equal the later game's music/frame labels before job0
            # restores those bytes. Gate on a real high-RAM game routine first.
            startup_break = breakpoint(monitor, labels["initTerrain"])
            monitor.run("x")
            startup_pc, _, _ = monitor.registers()
            assert startup_pc == labels["initTerrain"], "Spindle did not reach the restored game"
            monitor.run(f"disable {startup_break}")
            monitor.run("bank ram")
            initial_ram = monitor.memory(output / "restored-startup-ram.bin", 0, 0xffff)
            assert initial_ram[0x41c0:0x5fdd] == reference.music, "Disk job0 did not restore the original music module"
            runtime_bytes = runtime.read_bytes()
            runtime_begin = int.from_bytes(runtime_bytes[:2], "little")
            first, end = labels["beginMciPart"], labels["mciResidentEnd"]
            assert initial_ram[first:end] == runtime_bytes[2 + first - runtime_begin:2 + end - runtime_begin], "Disk job0 did not restore the MCI controller"
            assert any(initial_ram[0xce00:0xcf00]), "Spindle resident loader is missing"
            monitor.run("bank cpu")
            music_start_break = breakpoint(monitor, labels["musicFrameStart"])
            music_done_break = breakpoint(monitor, labels["musicFrameDone"])
            monitor.run(f"disable {music_done_break}")
            split_start_break = breakpoint(monitor, labels["cornerSplitStart"])
            split_done_break = breakpoint(monitor, labels["cornerSplitDone"])
            monitor.run(f"disable {split_done_break}")
            frame_start_break = breakpoint(monitor, labels["frameStart"])
            top_restored_break = breakpoint(monitor, labels["cornerTopRestored"])
            monitor.run(f"disable {top_restored_break}")
            done_break = breakpoint(monitor, labels["frameDone"])
            monitor.run(f"disable {done_break}")
            handoff_break = breakpoint(monitor, labels["beginMciPart"])
            for frame in range(args.frames + 1):
                monitor.run("x")
                music_pc, music_raster, music_start_cycles = monitor.registers()
                assert music_pc == labels["musicFrameStart"] and music_raster == 64, (frame, music_pc, music_raster)
                music_cadence = None if previous_music_cycles is None else music_start_cycles - previous_music_cycles
                if music_cadence is not None:
                    assert abs(music_cadence - 19656) <= 9, (frame, "Music call cadence", music_cadence)
                previous_music_cycles = music_start_cycles
                monitor.run(f"disable {music_start_break}")
                monitor.run(f"enable {music_done_break}")
                monitor.run("x")
                music_done_pc, music_done_raster, music_done_cycles = monitor.registers()
                assert music_done_pc == labels["musicFrameDone"]
                music_update_cycles = music_done_cycles - music_start_cycles
                assert 0 < music_update_cycles < (115 - 64) * 63 and music_done_raster < 115, (
                    frame, "Music missed the left-corner split deadline", music_update_cycles, music_done_raster)
                monitor.run(f"disable {music_done_break}")
                monitor.run(f"enable {music_start_break}")
                monitor.run("x")
                split_pc, split_raster, split_cycles = monitor.registers()
                assert split_pc == labels["cornerSplitStart"] and 115 <= split_raster < 117, (frame, "Corner split start", split_raster)
                if not ending_expected:
                    check_corner_phase(monitor, output, "before", reference, bottom=False)
                monitor.run(f"disable {split_start_break}")
                monitor.run(f"enable {split_done_break}")
                monitor.run("x")
                split_done_pc, split_done_raster, split_done_cycles = monitor.registers()
                assert split_done_pc == labels["cornerSplitDone"] and split_done_raster < 117, (
                    frame, "Bottom-left corner missed sprite DMA", split_done_raster)
                if not ending_expected:
                    check_corner_phase(monitor, output, "after", reference, bottom=True)
                monitor.run(f"disable {split_done_break}")
                monitor.run(f"enable {split_start_break}")
                monitor.run("x")
                pc, raster, cycles = monitor.registers()
                # RAM-bank bytes $00/$01 are shadow RAM. The register response
                # reports the actual CPU port that controls BASIC banking.
                cpu_fields = re.search(r"^\.;[0-9a-fA-F]{4}\s+(.*)$", monitor.transcript[-1], re.M)[1].split()
                assert int(cpu_fields[5], 16) == 0x36, "BASIC must be banked out for the terrain at $A000"
                assert pc == labels["frameStart"], f"Frame {frame}: stopped at ${pc:04x}"
                assert raster == 144, (frame, raster)
                cadence = None if previous_cycles is None else cycles - previous_cycles
                if cadence is not None:
                    # Transparent sprite rows still perform DMA. Their moving
                    # end positions can stall the raster poll within line144.
                    assert abs(cadence - 19656) < 63, (frame, cadence)
                previous_cycles = cycles
                monitor.run(f"enable {top_restored_break}")
                monitor.run("x")
                restored_pc, restored_raster, restored_cycles = monitor.registers()
                assert restored_pc == labels["cornerTopRestored"], (frame, "Left corner restore")
                monitor.run(f"disable {top_restored_break}")
                monitor.run("bank ram")
                ram = monitor.memory(output / "ram.bin", 0, 0xffff)
                actual_frame = int.from_bytes(ram[labels["frameCounter"]:labels["frameCounter"] + 2], "little")
                assert actual_frame == frame, (frame, actual_frame)
                assert ram[labels["endingPacked"]:labels["endingPackedEnd"]] == ending_reference.packed, (frame, "Retained ending data under KERNAL changed")
                reference.verify_music_state(frame, ram)
                level = ram[labels["lightLevel"]]
                active = ram[labels["activeLevel"]]
                transition = ram[labels["levelTransition"]]
                step = int.from_bytes(ram[labels["levelCameraStep"]:labels["levelCameraStep"] + 2], "little")
                ending_state = ram[labels["endingState"]]
                actual_actor_step = ram[labels["actorStepLo"]] + 256 * ram[labels["actorStepHi"]]
                room = 1 if ending_state == 2 else 0
                assert ending_state in (0, 1, 2) and ending_state >= ending_previous_state, (frame, "Room transition regressed", ending_state)
                if ending_state != ending_previous_state:
                    ending_states.append({"frame": frame, "state": ending_state})
                    ending_previous_state = ending_state
                if ending_state == 1:
                    assert ending_expected, (frame, "Second room appeared before boy-room Level1 completed")
                    assert (active, step) in ((0, 512), (1, 0)), (frame, "Unexpected camera while preparing second room", active, step)
                    ending_blank_frames.append(frame)
                    assert len(ending_blank_frames) <= 110, (frame, "Second room stayed blank too long")
                    monitor.run("bank io")
                    vic = monitor.memory(output / "vic.bin", 0xd000, 0xd03f)
                    assert vic[0x15] == 0, (frame, "Sprites remained enabled during room transition")
                    assert not vic[0x11] & 0x10, (frame, "Partially prepared room was revealed")
                    monitor.run("bank cpu")
                else:
                    if room == 1 and room7_first_game_frame is None:
                        assert ending_expected and ending_blank_frames, (frame, "Second room skipped its transition")
                        room7_first_game_frame = frame
                        ending_expected = False
                        expected_active = expected_actor_level = 1
                        expected_camera = expected_actor_step = 0
                        expected_transition = 0
                        expected_scroll_countdown = ((4 - frame % 4) % 4) or 4
                        expected_light_phase = 0
                        expected_light_countdown = ((14 - frame % 16) % 16) or 16
                        last_transition = frame
                    if room == 0:
                        assert not ending_expected and room7_first_game_frame is None, (frame, "Boy room continued instead of changing to the man room")
                    else:
                        ending_visible_frames.append(frame)
                    level = ram[labels["lightLevel"]]
                    light_countdown = ram[labels["lightCountdown"]]
                    light_phase = ram[labels["lightPhase"]]
                    assert (light_countdown, light_phase, level) == (expected_light_countdown, expected_light_phase,
                                                                           LIGHT_SEQUENCE[expected_light_phase]), (
                        frame, "Room lighting clock", (light_countdown, light_phase, level),
                        (expected_light_countdown, expected_light_phase, LIGHT_SEQUENCE[expected_light_phase]))
                    if light_countdown == 1:
                        assert frame % 4 == 1, (frame, "Lighting shares a sprite or terrain update frame")
                    if level != previous_level:
                        transitions.append({"frame": frame, "level": level})
                        last_transition = frame
                        previous_level = level
                    active = ram[labels["activeLevel"]]
                    transition = ram[labels["levelTransition"]]
                    step = int.from_bytes(ram[labels["levelCameraStep"]:labels["levelCameraStep"] + 2], "little")
                    assert (active, transition, step) == (expected_active, expected_transition, expected_camera), (
                        frame, "Level/camera transition", (active, transition, step),
                        (expected_active, expected_transition, expected_camera))
                    assert ram[labels["scrollCountdown"]] == expected_scroll_countdown, (frame, "Scroll cadence")
                    visible = transition in (0, 255)
                    assert visible, (frame, "Unexpected same-room level refill", room, active, transition)
                    pair = (room, active)
                    assert pair in PLAYBACK_ORDER, (frame, "Unexpected room/level pair", pair)
                    if not observed_scene_order or observed_scene_order[-1] != pair:
                        assert len(observed_scene_order) < len(PLAYBACK_ORDER), (frame, "Scene replayed", pair)
                        assert pair == PLAYBACK_ORDER[len(observed_scene_order)], (frame, "Scene order", observed_scene_order, pair)
                        observed_scene_order.append(pair)
                    incoming = 40 + step if visible else 40 if transition == 254 else 40 - transition
                    assert ram[labels["incomingTile"]] == incoming // 4 % 128, (frame, "Incoming map column")
                    assert ram[labels["tilePixelX"]] == incoming % 4, (frame, "Incoming tile pixel")
                    scene = (room, active, visible)
                    if scene != previous_scene:
                        last_scene_change = frame
                        if previous_scene is not None and (room, active) != previous_scene[:2]:
                            level_changes.append({"frame": frame, "from_room": previous_scene[0] + 1,
                                                  "room": room + 1, "from": previous_scene[1] + 1, "to": active + 1})
                        previous_scene = scene
                    reference = scene_references[pair]
                    bitmap = reference.expected_bitmap(step % 512, actual_actor_step if visible else None)
                    if visible or transition == 254:
                        assert ram[0x2000:0x3f40] == bitmap, f"Frame {frame}: Level{active + 1} bitmap differs from original source decode"
                    else:
                        outside = bytearray(ram[0x2000:0x3f40])
                        for cell in reference.game:
                            outside[cell * 8:cell * 8 + 8] = reference.bitmap[cell * 8:cell * 8 + 8]
                        assert outside == reference.bitmap, (frame, "Refill changed bitmap outside TV")
                    screen, expected_colors = reference.expected_colors(step % 512, level, hidden=not visible)
                    assert ram[0x0400:0x07e8] == screen, f"Frame {frame}: scene screen colors differ at level {level}"
                    if frame == 0:
                        for index, source_reference in enumerate(references):
                            stem, suffix = ("terrain", "") if index == 0 else ("terrain2", "2")
                            assert ram[labels[stem + "Tiles"]:labels[stem + "TilesEnd"]] == source_reference.tiles
                            assert ram[labels[stem + "MapStart"]:labels[stem + "MapEnd"]] == source_reference.tile_map
                            for name, table in zip(("PerspectiveAccentMap", "PerspectiveMiddleAccentMap",
                                                    "PerspectiveRightAccentMap", "AccentMap"), source_reference.accent_tables):
                                assert ram[labels[stem + name]:labels[stem + name] + 512] == table
                            for name, data in (("actorGround", source_reference.actor_ground), ("actorPlayerPath", source_reference.player_path)):
                                if data is not None:
                                    address = labels[name + suffix]
                                    assert ram[address:address + len(data)] == data
                        for slot in range(2):
                            for channel in ("x", "y", "frame"):
                                data = references[1].enemy_schedule_arrays[slot][channel]
                                address = labels[f"level2Enemy{slot}{channel.capitalize()}"]
                                assert ram[address:address + len(data)] == data
                        assert ram[0x1a00:0x1c00] == references[1].level2_player_planes
                        intro_address = labels["introSpriteFrames"]
                        assert ram[intro_address:intro_address + 640] == reference.intro_planes
                        assert ram[labels["cornerMaskFrames"]:labels["cornerMaskFrames"] + 256] == reference.corner_data
                    monitor.run("bank io")
                    colors = bytes(value & 15 for value in monitor.memory(output / "colors.bin", 0xd800, 0xdbe7))
                    assert colors == expected_colors, f"Frame {frame}: color RAM differs at level {level}"
                    vic = monitor.memory(output / "vic.bin", 0xd000, 0xd03f)
                    assert vic[0x11] & 0x7f == 0x3b and vic[0x16] & 0x3f == 0x18 and vic[0x18] & 0xfe == 0x18
                    assert vic[0x20] & 15 == 0 and vic[0x21] & 15 == reference.background
                    actual_actor_step = ram[labels["actorStepLo"]] + 256 * ram[labels["actorStepHi"]]
                    assert actual_actor_step == expected_actor_step, (frame, "Actor camera phase", actual_actor_step, expected_actor_step)
                    actor_reference = scene_references[(room, expected_actor_level)]
                    actors = actor_reference.verify_sprites(frame, ram, vic, work_addresses,
                                                            step=expected_actor_step, hidden=not visible)
                    expected_height = actors["height"] if visible else reference.player_height
                    assert ram[labels["actorPlayerHeight"]] == expected_height, (frame, "Active Giana height")
                    sprite_pixels = reference.sprite_pixels(actors) if visible else reference.corner_pixels
                    clearance = reference.verify_actor_clearance(actors) if visible else None
                    if visible:
                        assert expected_actor_level == active, (frame, "Revealed actors use the old level route")
                        support = reference.player_support(step % 512, actors)
                        assert support["visible_body_penetration_pixels"] == 0, (frame, "Opaque body entered rendered solid", support)
                        level_camera_steps[active].add(step)
                        level_world_columns[active].update((step + x) % 512 for x in range(40))
                        level_actor_steps[active].add(actors["step"])
                        room_level_camera_steps[room][active].add(step)
                        room_level_actor_steps[room][active].add(actors["step"])
                        room_level_world_columns[room][active].update((step + x) % 512 for x in range(40))
                        if active == 0 and actors["step"] < 105:
                            opening_native_states[room].setdefault(actors["step"], actors)
                    else:
                        transition_frames.append(frame)
                    if visible and previous_actor_room == room and previous_actor_level == active and previous_actor_step is not None and actors["step"] != previous_actor_step:
                        assert actors["step"] == (previous_actor_step + 1) % 512, (frame, "Actor step skipped")
                        delta = abs(vic[11] - previous_player_y)
                        maximum_actor_y_delta = max(maximum_actor_y_delta, delta)
                    if visible:
                        previous_actor_room = room
                        previous_actor_level = active
                        previous_actor_step = actors["step"]
                        previous_player_y = vic[11]
                    if clearance is not None and active == 0:
                        section, gap = clearance
                        owl_overlap_steps.add(actors["step"])
                        cleared_owl_sections.add(section)
                        owl_clearances.append(gap)
                    seen_sprite_enables.add(vic[0x15])
                    if visible and actors["visible"][0]:
                        if actors["form"] == "punk":
                            seen_player_poses.add(actors["poses"][0] // 2)
                    visible_entries = reference.visible_enemy_entries(actors) if visible else set()
                    if visible and active == 1:
                        seen_enemy_entries.update(visible_entries)
                        room_seen_enemy_entries[room].update(visible_entries)
                        maximum_opaque_visible_enemies = max(maximum_opaque_visible_enemies, len(visible_entries))
                    visible_enemy_count = sum(actors["visible"][slot] for slot in (2, 3)
                                              if slot not in actors["pickup_slots"]) if visible else 0
                    maximum_visible_enemies = max(maximum_visible_enemies, visible_enemy_count)
                    for slot in (2, 3):
                        if not visible or not actors["visible"][slot] or slot in actors["pickup_slots"]:
                            continue
                        seen_enemy_poses.add(actors["poses"][slot])
                        if active == 0:
                            seen_level1_owl_poses.add(actors["poses"][slot])
                        enemy_x = actors["positions"][slot][0]
                        if enemy_x < 0:
                            seen_clip_modes.add("left")
                        if enemy_x + 6 > 40:
                            seen_clip_modes.add("right")
                        if 0 <= enemy_x and enemy_x + 6 <= 40:
                            seen_clip_modes.add("inside")
                        if enemy_x >= 24:
                            seen_clip_modes.add("x-high")
                    cia = monitor.memory(output / "cia2.bin", 0xdd00, 0xdd03)
                    assert vic_bank(cia) == 0 and cia[2] & 3 == 0, (frame, "Room must retain loader-safe VIC bank0")
                    if level not in room_checked_light_levels[room]:
                        reference.verify_protected_pixels(ram[0x2000:0x3f40], ram[0x0400:0x07e8], colors)
                        checked_levels.add(level)
                        room_checked_light_levels[room].add(level)
                    monitor.run("bank cpu")
                    representative_types = {kind for slot, kind in enumerate(actors["enemy_types"], 2)
                                            if visible and active == 1 and kind is not None
                                            and 8 <= actors["positions"][slot][0] <= 25}
                    both_inside = visible and active == 1 and all(actors["visible"][slot] and
                                  0 <= actors["positions"][slot][0] <= 34 for slot in (2, 3))
                    opening_image_needed = (visible and active == 0 and actors["step"] < 115
                                            and actors["step"] not in opening_saved_steps[room])
                    # At raster 144 the upper display is current and the lower display
                    # retains the previous frame. Capture only after lighting has
                    # remained stable for a complete visible frame.
                    capture = frame > 0 and frame - last_transition >= 2 and frame - last_scene_change >= 2 and (
                        (frame % 8 == 2) or frame in event_frames or
                        (visible and frame % 4 == 1 and actors["step"] in event_steps[active]) or
                        frame == args.frames or level not in saved_levels or visible and (room, active) not in saved_source_levels or
                        (visible and active == 1 and bool(visible_entries - captured_enemy_entries)) or
                        (both_inside and not captured_two_enemies) or
                        opening_image_needed or
                        bool(representative_types - captured_enemy_types))
                    if capture:
                        screenshot = output / f"frame-{frame:04d}.png"
                        monitor.run(f'screenshot "{screenshot}" 2')
                        with Image.open(screenshot) as image:
                            actual = image.convert("RGB")
                        display = actual.crop((32, 35, 352, 235))
                        expected = reference.composite_sprites(reference.decode(bitmap, screen, colors), sprite_pixels)
                        actual_rgb, expected_rgb = display.tobytes(), expected.tobytes()
                        differences = sum(actual_rgb[offset:offset + 3] != expected_rgb[offset:offset + 3]
                                          for offset in range(0, len(actual_rgb), 3))
                        assert differences == 0, (frame, level, differences)
                        if visible and actors["visible"][0]:
                            blue_pixels = [position for position, color in sprite_pixels.items() if color == 6]
                            assert all(display.getpixel(position) == reference.palette[6] for position in blue_pixels)
                            blue_clothes_verified |= bool(blue_pixels)
                        if visible and active == 0:
                            assert display.getpixel((240, 24)) == reference.palette[14], "Level1 TV sky must be light blue"
                            sky_blue_verified = True
                        for column, region in enumerate(REGION_COLUMNS) if visible else ():
                            for y, source_y in enumerate(REGION_SOURCE_ROWS[region]):
                                if source_y < 0:
                                    for x in range(8):
                                        position = (184 + column * 8 + x, 24 + y)
                                        assert position not in reference.highlight_pixels, "Highlight must avoid perspective masks"
                                        assert display.getpixel(position) == reference.palette[0], (
                                            "Perspective masks must stay black", position)
                        probes = {
                            2: (("bush", 17, 44, 5),),
                            225: (("bonus", 94, 11, 7),),
                            544: (("pipe", 146, 35, 7), ("nearby_bush", 165, 46, 5)),
                        }
                        for name, world_x, world_y, color in probes.get(frame, ()):
                            offset_x = (world_x - step) % 512
                            assert offset_x < 40
                            position = (184 + offset_x * 2, 24 + world_y)
                            if position not in sprite_pixels:
                                assert display.getpixel(position) == reference.palette[color], name
                                checked_objects.add(name)
                        screenshots.append({"frame": frame, "room": room + 1, "light": level, "source_level": active + 1,
                                            "camera_step": step, "transition": transition,
                                            "actor_step": actors["step"], "player_form": actors["form"],
                                            "enemy_entries": sorted(visible_entries)})
                        if opening_image_needed:
                            opening_saved_steps[room].add(actors["step"])
                        if visible and active == 1:
                            for entry in visible_entries - captured_enemy_entries:
                                actual.save(BUILD / f"{prefix}-enemy-{entry}.png")
                            captured_enemy_entries.update(visible_entries)
                            tv_crop = display.crop((184, 24, 264, 88)).resize((320, 256), Image.Resampling.NEAREST)
                            for kind in representative_types - captured_enemy_types:
                                name = ENEMY_TYPES[kind]
                                actual.save(BUILD / f"{prefix}-{name}.png")
                                tv_crop.save(BUILD / f"{prefix}-{name}-tv.png")
                                enemy_representatives.append({"type": kind, "name": name, "frame": frame,
                                                              "camera_step": step, "image": f"{prefix}-{name}.png",
                                                              "tv_crop": f"{prefix}-{name}-tv.png"})
                            captured_enemy_types.update(representative_types)
                            if both_inside and not captured_two_enemies:
                                actual.save(BUILD / f"{prefix}-two-enemies.png")
                                tv_crop.save(BUILD / f"{prefix}-two-enemies-tv.png")
                                captured_two_enemies = True
                        if visible and (room, active) not in saved_source_levels:
                            actual.save(BUILD / f"{prefix}-room{room + 1}-level{active + 1}-selected.png")
                            saved_source_levels.add((room, active))
                        if level not in saved_levels:
                            actual.save(BUILD / f"{prefix}-level-{level}.png")
                            saved_levels.add(level)
                        if frame == 544 or (args.frames < 544 and frame == args.frames):
                            actual.save(BUILD / f"{prefix}.png")
                        if frame in (1637, 1681, 1761, 1921, 2045, 2049):
                            actual.save(BUILD / f"{prefix}-end-{actors['step']:03d}.png")
                        if frame % 8 == 2 and (frame <= 4096 or room == 1 and frame <= room7_first_game_frame + 320):
                            animation.append(actual)
                        if room == 1:
                            ending_screenshots.append(frame)
                            if not room7_selected_saved:
                                actual.save(BUILD / f"{prefix}-selected.png")
                                display.resize((1280, 800), Image.Resampling.NEAREST).save(BUILD / f"{prefix}-selected-4x.png")
                                room7_selected_saved = True
                monitor.run(f"enable {done_break}")
                monitor.run("x")
                done_pc, done_raster, done_cycles = monitor.registers()
                handoff_now = done_pc == labels["beginMciPart"]
                assert done_pc == labels["frameDone"] or handoff_now
                if handoff_now:
                    assert (room, active, step, transition) == (1, 1, 472, 255), (
                        frame, "MCI part started before man-room Level2 finished")
                monitor.run(f"disable {done_break}")
                update_cycles = done_cycles - cycles
                assert 0 < update_cycles < (312 + 64 - 144) * 63, (frame, update_cycles, done_raster)
                samples.append({"frame": frame, "level": level, "start_cycles": cycles, "start_raster": raster,
                                "corner_split_raster": split_raster, "corner_split_start_cycles": split_cycles,
                                "corner_split_completion_raster": split_done_raster,
                                "corner_split_update_cycles": split_done_cycles - split_cycles,
                                "corner_top_restore_raster": restored_raster,
                                "corner_top_restore_cycles": restored_cycles - cycles,
                                "room": room + 1 if ending_state != 1 else None,
                                "source_level": active + 1, "level_camera_step": step, "level_transition": transition,
                                "cadence_cycles": cadence, "update_cycles": update_cycles,
                                "completion_raster": done_raster, "actor_step": actual_actor_step, "ending_state": ending_state,
                                "sprite_enables": vic[0x15], "music_start_cycles": music_start_cycles,
                                "music_done_cycles": music_done_cycles, "music_update_cycles": music_update_cycles,
                                "music_start_raster": music_raster, "music_completion_raster": music_done_raster,
                                "music_cadence_cycles": music_cadence,
                                "music_sequence_position": ram[0x41e4]})
                if handoff_now:
                    handoff_sample = samples[-1]
                    frozen_image = reference.composite_sprites(reference.decode(bitmap, screen, colors), sprite_pixels)
                    mci_tail = verify_mci_tail(
                        monitor, output, labels, reference, mci_reference, args, handoff_sample, frozen_image,
                        (music_start_break, music_done_break, split_start_break, split_done_break,
                         frame_start_break, top_restored_break, done_break, handoff_break), prefix)
                    break
                # Model the visible scheduler contract from the sampled state.
                # Each refill consumes one normal PAL frame and never suppresses
                # a music call. Room-light frames deliberately hold the refill.
                if ending_state == 1:
                    pass
                elif transition == 255 and (room, active) == PLAYBACK_ORDER[0]:
                    ending_expected = True
                elif transition == 255:
                    raise AssertionError((frame, "The final scene returned instead of entering MCI", room, active))
                else:
                    if frame % 4 == 0:
                        expected_actor_level = active
                        expected_actor_step = step % 512
                    expected_scroll_countdown -= 1
                    if expected_scroll_countdown == 0:
                        expected_scroll_countdown = 4
                        expected_camera += 1
                        if expected_camera == (512 if active == 0 else 472):
                            expected_transition = 255
                if ending_state != 1:
                    expected_light_countdown -= 1
                    if expected_light_countdown == 0:
                        expected_light_countdown = 16
                        expected_light_phase = (expected_light_phase + 1) % 4
                if frame % 256 == 0:
                    print(f"Verified PAL frame {frame}/{args.frames}; Level{active + 1} pixel {step}; light {level}; transition {transition}; ending {ending_state}", flush=True)
        assert checked_levels == {0, 1, 2}, "Run at least 32 frames to exercise every automatic light level"
        # Flush the real SID write sink before comparing every complete call.
        connection.sendall(b"quit\n")
        connection.close()
        connection = None
        process.wait(timeout=5)
        sid_events = read_sid_events(output / "sid-registers.txt")
        event_index = 0
        compared_writes = 0
        all_music_samples = samples + (mci_tail["music_samples"] if mci_tail else [])
        for sample in all_music_samples:
            while event_index < len(sid_events) and sid_events[event_index][0] < sample["music_start_cycles"]:
                event_index += 1
            values = []
            while event_index < len(sid_events) and sid_events[event_index][0] < sample["music_done_cycles"]:
                values.append(list(sid_events[event_index][1:]))
                event_index += 1
            expected_values = reference.music_reference["calls"][sample["frame"]]["events"]
            assert values == expected_values, (sample["frame"], "SID writes differ from original RSID call", values, expected_values)
            compared_writes += len(values)
        total_playback_writes = sum(clock >= all_music_samples[0]["music_start_cycles"]
                                    for clock, _, _ in sid_events)
        assert total_playback_writes == compared_writes, "Unexpected SID writes outside the original music calls"
        sequence_wraps = [sample["frame"] for previous, sample in zip(all_music_samples, all_music_samples[1:])
                          if previous["music_sequence_position"] == 0x5d and sample["music_sequence_position"] == 0x28]
        if args.frames >= reference.music_reference["first_sequence_wrap_tick"]:
            assert sequence_wraps and sequence_wraps[0] == reference.music_reference["first_sequence_wrap_tick"]
        assert saved_levels == {0, 1, 2}, "Run at least 35 frames to capture every light level"
        assert sky_blue_verified
        assert blue_clothes_verified
        if args.frames >= 544:
            assert checked_objects == {"bush", "bonus", "pipe", "nearby_bush"}
        if args.frames >= 2052:
            assert level_actor_steps[0] == set(range(512))
            assert seen_player_poses == {0, 1, 2, 3} and seen_level1_owl_poses == {8, 9}
            assert seen_sprite_enables <= {0x07, 0x3f, 0x7f, 0xbf, 0xff}
            assert seen_clip_modes == {"left", "right", "inside", "x-high"}
            assert cleared_owl_sections == {0, 64, 128, 192, 320, 448}
            assert len(owl_overlap_steps) == 66
        if (1, 1) in observed_scene_order:
            assert [(change["from_room"], change["from"], change["room"], change["to"])
                    for change in level_changes] == [(1, 1, 2, 2)]
            assert ending_states and ending_blank_frames and ending_visible_frames and ending_screenshots
            assert ending_visible_frames[0] - ending_blank_frames[0] <= 110
            assert ending_visible_frames[-1] == (handoff_sample["frame"] if handoff_sample else args.frames)
            assert samples[-1]["ending_state"] == 2, "Second room did not remain active"
        if args.frames >= 4605:
            assert handoff_sample is not None, "The man-room Level2 did not end in the MCI part"
        if handoff_sample is not None:
            assert observed_scene_order == list(PLAYBACK_ORDER), ("Wrong playable scene sequence", observed_scene_order)
            assert level_camera_steps == [set(range(513)), set(range(473))]
            assert level_actor_steps == [set(range(512)), set(range(472))]
            assert all(columns == set(range(512)) for columns in level_world_columns), "Both complete original maps must reach the TV"
            assert saved_source_levels == set(PLAYBACK_ORDER), ("Unexpected room/level screenshot", saved_source_levels)
            expected_entries = {enemy["source_entry"] for enemy in references[1].original_enemies}
            assert seen_enemy_entries == expected_entries and captured_enemy_entries == expected_entries, (
                "Original enemies not all seen in native screenshots", seen_enemy_entries, captured_enemy_entries)
            expected_enemy_poses = {actor["frame"] for actors in references[1].enemy_schedules[:472]
                                    for actor in actors if actor["frame"] != 255} | {8, 9}
            assert seen_enemy_poses == expected_enemy_poses, ("Native enemy pose coverage", seen_enemy_poses, expected_enemy_poses)
            assert maximum_visible_enemies == maximum_opaque_visible_enemies == 2 and captured_two_enemies
            assert captured_enemy_types == set(ENEMY_TYPES), ("Missing native enemy art proof", captured_enemy_types)
            assert handoff_sample is not None and mci_tail and len(mci_tail["fields"]) >= 120, "MCI handoff/fields not verified"
            assert len(ending_visible_frames) >= 16
            assert room_level_actor_steps == [[set(range(512)), set()], [set(), set(range(472))]], "Unexpected actor coverage by scene"
            assert room_level_camera_steps == [[set(range(513)), set()], [set(), set(range(473))]], "Unexpected camera coverage by scene"
            assert room_level_world_columns == [[set(range(512)), set()], [set(), set(range(512))]], "Unexpected original-map coverage by scene"
            assert room_seen_enemy_entries == [set(), expected_entries], "Level2 enemies must appear only in the man room"
            for room in range(2):
                assert room_checked_light_levels[room] == {0, 1, 2}, (room, "Room lighting levels missing")
        opening_reports = [scene_references[(room, 0)].verify_opening_contract(states)
                           if (room, 0) in scene_references and all(step in states for step in range(105)) else None
                           for room, states in enumerate(opening_native_states)]
        assert opening_native_states[0][0]["form"] == "small", "Native startup did not show small Giana"
        assert not opening_native_states[1] and not opening_saved_steps[1], "The man room replayed the Level1 opening"
        if args.frames >= 425:
            assert opening_reports[0] is not None, "The first-room opening was not fully verified"
        if handoff_sample is not None:
            assert opening_reports[0] is not None and opening_reports[1] is None, "The opening belongs only to boy-room Level1"
            assert opening_saved_steps == [set(range(115)), set()], "Native opening screenshots must cover the boy room only"
        animation[0].save(BUILD / f"{prefix}.gif", save_all=True, append_images=animation[1:],
                          duration=160, loop=0, optimize=False, disposal=1)
        (output / "timing.json").write_text(json.dumps(samples, indent=2) + "\n")
        updates = [sample["update_cycles"] for sample in samples]
        cadences = [sample["cadence_cycles"] for sample in samples if sample["cadence_cycles"] is not None]
        result.update({"passed": True, "frame_range": [0, all_music_samples[-1]["frame"]], "frames_verified": len(all_music_samples),
                       "game_checkpoints_verified": len(samples),
                       "unique_scroll_states_per_level": [len(states) for states in level_camera_steps],
                       "map_columns_visible_per_level": [len(columns) for columns in level_world_columns],
                       "level_end_camera_steps": [512, 472], "level_transitions": level_changes,
                       "ordered_scene_sequence_verified": handoff_sample is not None and observed_scene_order == list(PLAYBACK_ORDER),
                       "expected_scene_order": [[room + 1, level + 1] for room, level in PLAYBACK_ORDER],
                       "observed_scene_order": [[room + 1, level + 1] for room, level in observed_scene_order],
                       "both_original_maps_in_selected_rooms_verified": handoff_sample is not None,
                       "opening_sequence_verified_per_room": [report is not None for report in opening_reports],
                       "opening_sequence_per_room": opening_reports,
                       "opening_original_art_independently_decoded": True,
                       "opening_sprite_atlas_sha256": digest(reference.intro_planes),
                       "opening_actor_steps_in_native_screenshots_per_room": [sorted(steps) for steps in opening_saved_steps],
                       "second_room_source_sha256": digest(ending_reference.source),
                       "second_room_packed_sha256": digest(ending_reference.packed),
                       "second_room_packed_bytes": len(ending_reference.packed),
                       "second_room_nibble_archive_independently_decoded_to_source": True,
                       "second_room_archive_preserved_under_kernal_each_game_frame": True,
                       "second_room_source": str(ending_reference.path.relative_to(ROOT)),
                       "second_room_background": ending_reference.background,
                       "second_room_layout": ending_layout,
                       "second_room_blank_frames": ending_blank_frames,
                       "second_room_first_game_frame": room7_first_game_frame,
                       "second_room_game_frames_verified": len(ending_visible_frames),
                       "second_room_native_screenshot_frames": ending_screenshots,
                       "second_room_source_and_game_pixels_verified": bool(ending_screenshots),
                       "second_room_game_and_lighting_running": bool(ending_visible_frames),
                       "screen_light_cells_per_room": [len(scene.light) for scene in references],
                       "actor_steps_verified_per_room_and_level": [[len(states) for states in row] for row in room_level_actor_steps],
                       "camera_steps_verified_per_room_and_level": [[len(states) for states in row] for row in room_level_camera_steps],
                       "level2_enemy_entries_seen_per_room": [sorted(entries) for entries in room_seen_enemy_entries],
                       "light_levels_verified_per_room": [sorted(levels) for levels in room_checked_light_levels],
                       "transition_hidden_pal_frames": transition_frames,
                       "per_level_screen_bytes": [source.game_screen for source in references],
                       "expected_terrain_from_original_character_sources": True,
                       "level2_source_block_stream_independently_expanded": True,
                       "automatic_light_sequence": list(LIGHT_SEQUENCE), "light_interval_pal_frames": 16,
                       "light_transitions": transitions, "light_levels_verified": sorted(checked_levels),
                       "light_remaps_from_original_verified": True, "game_outside_marked_cells_changes": 0,
                       "game_bitmap_changes_outside_game_area": 0, "protected_multicolor_pixels_per_level": len(reference.protected_pixels),
                       "protected_color_pixel_changes": 0, "vic_mode_and_bank_verified": True,
                       "sky_blue_verified": sky_blue_verified, "object_color_probes": sorted(checked_objects),
                       "blue_clothes_verified": blue_clothes_verified,
                       "actor_steps_verified_per_level": [len(steps) for steps in level_actor_steps],
                       "actor_level_switch_tested": (1, 1) in observed_scene_order,
                       "giana_poses_verified": sorted(seen_player_poses), "owl_frames_verified": sorted(seen_level1_owl_poses),
                       "enemy_frames_verified": sorted(seen_enemy_poses),
                       "level2_enemy_entries_seen": sorted(seen_enemy_entries),
                       "level2_enemy_entries_in_native_screenshots": sorted(captured_enemy_entries),
                       "maximum_simultaneous_enemies": maximum_visible_enemies,
                       "maximum_opaque_visible_enemies": maximum_opaque_visible_enemies,
                       "native_enemy_representatives": enemy_representatives,
                       "level2_original_enemy_spawn_summary": references[1].enemy_schedule_summary,
                       "level2_original_enemy_motion_invariants": references[1].enemy_semantics,
                       "enemy_art_independently_reduced_from_original": True,
                       "sprite_enable_states": sorted(seen_sprite_enables), "sprite_clip_modes": sorted(seen_clip_modes),
                       "sprite_pixels_outside_tv": 0, "moving_actor_pixels_over_perspective_masks": 0,
                       "highlight_source_sha256": digest(reference.highlight_source),
                       "highlight_source_file": str(reference.highlight_source_path.relative_to(ROOT)),
                       "highlight_sprite_sha256": digest(reference.highlight_data),
                       "highlight_opaque_cyan_pixels": len(reference.highlight_pixels),
                       "highlight_color": 3, "highlight_pixels_over_perspective_masks": 0,
                       "highlight_rectangle_physical": [184, 27, 24, 21],
                       "highlight_hires_source_and_placement_verified": True,
                       "rounded_corner_black_hires_pixels": len(reference.corner_pixels),
                       "rounded_corner_profile_physical_pixels": [6, 4, 3, 2, 1, 1, 0, 0],
                       "rounded_corner_runtime_address": 0x0200,
                       "rounded_corners_foremost_verified": True,
                       "left_corner_sprite_multiplexed": True,
                       "left_corner_split_completion_raster_max": max(sample["corner_split_completion_raster"] for sample in samples),
                       "rounded_corners_bitmap_modifications": 0,
                       "music_calls_verified": len(all_music_samples), "music_sid_register_writes_compared": compared_writes,
                       "music_sid_register_writes_total_after_first_call": total_playback_writes,
                       "music_unexpected_sid_register_writes_between_calls": 0,
                       "music_register_sequence_matches_original_rsid": True,
                       "music_mutable_state_matches_original_rsid_each_call": True,
                       "music_structural_score_wrap_frames": sequence_wraps,
                       "music_complete_first_loop_verified": bool(sequence_wraps),
                       "music_sequence_positions": sorted({sample["music_sequence_position"] for sample in all_music_samples}),
                       "music_update_cycles_min": min(sample["music_update_cycles"] for sample in all_music_samples),
                       "music_update_cycles_max": max(sample["music_update_cycles"] for sample in all_music_samples),
                       "music_completion_raster_min": min(sample["music_completion_raster"] for sample in all_music_samples),
                       "music_completion_raster_max": max(sample["music_completion_raster"] for sample in all_music_samples),
                       "music_sampler_cia2_disabled": True,
                       "giana_visible_all_actor_steps": [len(steps) == count for steps, count in zip(level_actor_steps, (512, 472))],
                       "opaque_actor_collision_pixels": 0,
                       "owl_encounters_cleared": sorted(cleared_owl_sections),
                       "owl_overlap_states_verified": len(owl_overlap_steps),
                       "minimum_owl_clearance_pixels": min(owl_clearances) if owl_clearances else None,
                       "owl_clearance_policy": "Exact opaque pixel separation; bounding-box clearance is diagnostic only",
                       "rendered_ground_contacts": motion["terrain_contact_steps"], "owl_head_support_steps": motion["enemy_support_steps"],
                       "unsupported_actor_steps": motion["unsupported_steps"], "ground_contact_motion": motion,
                       "ground_contact_motion_per_level": motions,
                       "opaque_body_terrain_penetration_pixels": 0,
                       "maximum_actor_y_step_pixels": maximum_actor_y_delta,
                       "black_perspective_masks_verified": True,
                       "screenshot_frames": screenshots, "screenshot_pixels_compared_each": 64000,
                       "screenshot_pixel_differences": 0, "palette": "peptoette-a",
                       "update_cycles_min": min(updates), "update_cycles_max": max(updates),
                       "completion_raster_min": min(sample["completion_raster"] for sample in samples),
                       "completion_raster_max": max(sample["completion_raster"] for sample in samples),
                       "cadence_cycles_min": min(cadences), "cadence_cycles_max": max(cadences),
                       "animation": f"{prefix}.gif", "animation_frames": len(animation), "animation_frame_duration_ms": 160,
                       "elapsed_seconds": round(time.monotonic() - started, 3)})
        if mci_tail:
            result.update({"mci_source": str(mci_reference.path.relative_to(ROOT)),
                           "mci_source_sha256": digest(mci_reference.source),
                           "mci_project_sha256": digest(mci_reference.project_path.read_bytes()),
                           "mci_handoff_after_game_frame": handoff_sample["frame"],
                           "mci_load_stage_first_music_frames": mci_tail["stage_first_music_frames"],
                           "mci_first_completed_field_music_frame": mci_tail["first_field_frame"],
                           "mci_first_field_delay_pal_frames": mci_tail["first_field_delay_pal_frames"],
                           "mci_frozen_room_screenshot_frames": mci_tail["frozen_room_screenshot_frames"],
                           "mci_music_calls_verified": len(mci_tail["music_samples"]),
                           "mci_fields_verified": len(mci_tail["fields"]),
                           "mci_field_phases_verified": sorted({field["phase"] for field in mci_tail["fields"]}),
                           "mci_original_field_bytes_and_colors_verified": True,
                           "mci_native_screenshot_pixel_differences": 0,
                           "mci_phase_b_physical_pixel_offset": 1,
                           "mci_field_cadence_cycles_min": min(right["cycles"] - left["cycles"] for left, right in zip(mci_tail["fields"], mci_tail["fields"][1:])),
                           "mci_field_cadence_cycles_max": max(right["cycles"] - left["cycles"] for left, right in zip(mci_tail["fields"], mci_tail["fields"][1:])),
                           "mci_animation": f"{prefix}-mci.gif"})
    except Exception as cause:
        result["error"] = f"{type(cause).__name__}: {cause}"
        raise
    finally:
        if monitor:
            (output / "monitor.log").write_text("\n".join(monitor.transcript))
        if connection:
            try:
                connection.sendall(b"quit\n")
            except OSError:
                pass
            connection.close()
        if process:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        (BUILD / f"{prefix}-verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vice", help="Path to x64sc; defaults to VICE or PATH")
    parser.add_argument("--frames", type=int, default=5205, help="PAL music-frame endpoint; minimum 35; 5205 covers boy-room Level1, man-room Level2, MCI and the original SID score loop")
    parser.add_argument("--autostart-mode", type=int, choices=(1, 2), default=1, help="Use 2 for separately named startup proof; both modes boot the real true-drive demo disk")
    parser.add_argument("--name", help="Output prefix beneath giana/build; defaults to boy-man-chain or boy-man-startup")
    args = parser.parse_args()
    if args.frames < 35:
        parser.error("--frames must be at least 35 to capture every lighting state")
    if args.name and (Path(args.name).name != args.name or args.name in (".", "..")):
        parser.error("--name must be a single output name without path separators")
    verify(args)


if __name__ == "__main__":
    main()
