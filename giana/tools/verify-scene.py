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


class SceneReference:
    """Decode source files directly, independently of generated runtime tables."""

    def __init__(self, source_level=1):
        self.source_level = source_level
        self.terrain_colors = (9, 14, 8) if source_level == 1 else (9, 10, 2)
        self.source_colors = (14, 8, 9) if source_level == 1 else (0, 10, 2)
        self.game_screen = self.terrain_colors[1] * 16 + self.terrain_colors[2]
        self.empty_code = 1 if source_level == 1 else 0
        self.player_height = 10 if source_level == 1 else 8
        self.source_path = ROOT / "images/giana5.koa"
        self.project_path = ROOT / "images/giana5.json"
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
        self.level2_player_planes = (ROOT / "giana/assets/level2-sprites.bin").read_bytes() if source_level == 2 else None
        self.sprite_atlas = (self.level2_player_planes + self.shared_sprite_atlas[512:]
                             if source_level == 2 else self.shared_sprite_atlas)
        actor_prefix = "" if source_level == 1 else "level2-"
        self.player_path = (ROOT / f"giana/assets/{actor_prefix}sprite-player-path.bin").read_bytes()
        self.actor_ground = (ROOT / f"giana/assets/{actor_prefix}sprite-ground.bin").read_bytes()
        self.original_map = (ROOT / f"giana/assets/original-level{source_level}-map.bin").read_bytes()
        if source_level == 2:
            assert self.original_map == self.decode_level2_stream(), "Level2 source map differs from the original block stream"
        self.collision_flags = (ROOT / "giana/assets/original-sprites-collision.bin").read_bytes()
        assert (len(self.sprite_atlas), len(self.player_path), len(self.actor_ground)) == (640, 512, 256)
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
        for frame in range(10):
            data = self.sprite_atlas[frame * 64:(frame + 1) * 64]
            height = self.player_height if frame < 8 else 9
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
        if source_level == 2:
            assert self.level2_player_planes == self.decode_level2_player_art(), "Level2 Giana differs from original area-sampled art"
        self.decode_original_terrain()
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
        semantic = []
        for y in range(64):
            source_y = (10 * y + 5) // 4
            row = []
            for x in range(512):
                source_x = x * 4 + 2
                character = self.original_map[(source_y // 8) * 256 + x // 2]
                bits = charset[character * 8 + source_y % 8]
                attribute = attributes[character]
                if attribute & 8:
                    code = (bits >> (6 - 2 * ((source_x % 8) // 2))) & 3
                    original = (*self.source_colors, attribute & 7)[code]
                else:
                    original = attribute if bits & (0x80 >> (source_x % 8)) else self.source_colors[0]
                row.append(quantized[original])
            semantic.append(tuple(row))
        self.semantic_rows = tuple(semantic)

    def terrain_pixel(self, world_x, source_y):
        color = self.semantic_rows[source_y][world_x]
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
    def expected_bitmap(self, step):
        bitmap = bytearray(self.bitmap)
        for y in range(64):
            for byte_x in range(10):
                packed = 0
                for pixel in range(4):
                    world_x = (step + byte_x * 4 + pixel) % 512
                    source_y = REGION_SOURCE_ROWS[REGION_COLUMNS[byte_x]][y]
                    code = 3 if source_y < 0 else self.terrain_pixel(world_x, source_y)
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
        player_visible = foot != 255
        player_y = 74 + self.project_actor_foot(foot, 10) - self.player_height if player_visible else 0
        enemy_x = 40 - (step & 63)
        enemy_ground = self.actor_ground[(((step & ~63) + 43) % 512) // 2]
        enemy_visible = player_visible and -5 <= enemy_x <= 39 and enemy_ground != 255 and enemy_ground >= 28
        enemy_y = 74 + self.project_actor_foot(enemy_ground, enemy_x) - 9 if enemy_visible else 0
        poses = (2 * (step & 3), 2 * (step & 3) + 1, 8 + ((step >> 1) & 1))
        positions = ((10, player_y), (10, player_y), (enemy_x, enemy_y))
        enabled = (player_visible, player_visible, enemy_visible)
        buffers = tuple(self.clipped_sprite(pose, position[0], visible)
                        for pose, position, visible in zip(poses, positions, enabled))
        return {"step": step, "poses": poses, "positions": positions, "visible": enabled,
                "enabled": (3 if player_visible else 0) | (4 if enemy_visible else 0),
                "x_high": 0x0a | (0x80 if enemy_x >= 24 else 0), "buffers": buffers}

    def verify_sprites(self, frame, ram, vic, work_addresses, step=None, hidden=False):
        actors = self.expected_sprites(frame, step)
        expected_enables = 0x0f if hidden else 0x1f | actors["enabled"] << 5
        assert vic[0x15] == expected_enables, (frame, "sprite enables", vic[0x15], expected_enables)
        assert vic[0x10] == (0x0a if hidden else actors["x_high"]), (frame, "sprite X high bits")
        assert all(vic[register] == 0 for register in (0x17, 0x1b, 0x1d)), "Sprites must be foreground and unexpanded"
        assert vic[0x1c] == 0xe0, "Four corner masks and highlight must be hires; actors must be multicolor"
        assert tuple(vic[register] & 15 for register in range(0x25, 0x2f)) == (10, 2, 0, 0, 0, 0, 3, 7, 6, 1)
        assert ram[0x07f8:0x0800] == bytes((8, 9, 10, 11, 0x3d, *(address // 64 for address in work_addresses)))
        assert ram[0x0c00:0x0e80] == self.shared_sprite_atlas, "Immutable original sprite atlas changed"
        if self.source_level == 2:
            assert ram[0x1a00:0x1c00] == self.level2_player_planes, "Immutable Level2 Giana art changed"
        assert ram[0x0f40:0x0f80] == self.highlight_data, "Highlight differs from retained source grid"
        assert ram[0x0200:0x0300] == self.corner_data, "Corner masks differ from the fixed physical-pixel radius profile"
        for slot, position in enumerate(self.corner_positions):
            assert (vic[slot * 2] + (256 if vic[0x10] & (1 << slot) else 0), vic[slot * 2 + 1]) == position, (
                frame, slot, "Corner position")
        assert (vic[8], vic[9]) == (208, 77), "Highlight must stay three pixels below the TV top-left"
        for slot, (address, position, expected_data) in enumerate(zip(work_addresses, actors["positions"], actors["buffers"])):
            x_mc, y_hw = position
            hardware_slot = slot + 5
            assert vic[hardware_slot * 2] == (208 + 2 * x_mc) & 255, (frame, slot, "sprite X")
            assert vic[hardware_slot * 2 + 1] == y_hw, (frame, slot, "sprite Y")
            assert ram[address:address + 64] == expected_data, (frame, slot, "sprite pose or clipping")
        return actors

    def sprite_pixels(self, actors):
        pixels = {}
        # Lower hardware sprite numbers win where the two Giana planes overlap.
        for slot in (2, 1, 0):
            if not actors["visible"][slot]:
                continue
            x_mc, y_hw = actors["positions"][slot]
            colors = (None, 10, (7, 6, 1)[slot], 2)
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
        # The fixed hires glass highlight occupies hardware slot 4, above actors.
        # Moving-actor containment above stays strict, including black masks.
        pixels.update(self.highlight_pixels)
        # The four opaque-black corner masks have the foremost hardware slots.
        pixels.update(self.corner_pixels)
        return pixels

    def sprite_opaque_pixels(self, actors, slot):
        if not actors["visible"][slot]:
            return set()
        x_mc, y_hw = actors["positions"][slot]
        return {(x_mc + pair, y_hw - 50 + row)
                for row in range(21) for pair in range(12)
                if self.sprite_code(actors["buffers"][slot], pair, row)}

    def rendered_solid(self, camera_step, x_mc, target_y, visible=False):
        if not 0 <= x_mc < 40 or not 0 <= target_y < 64:
            return False
        source_y = REGION_SOURCE_ROWS[REGION_COLUMNS[x_mc // 4]][target_y]
        if source_y < 0:
            return False
        world_x = (camera_step + x_mc) % 512
        character = self.original_map[((10 * source_y + 5) // 32) * 256 + world_x // 2]
        solid = self.collision_flags[character] in (1, 0x80)
        return solid and (not visible or self.terrain_pixel(world_x, source_y) != self.empty_code)

    def player_support(self, camera_step, actors):
        player = self.sprite_opaque_pixels(actors, 0) | self.sprite_opaque_pixels(actors, 1)
        assert player
        bottom = max(y for _, y in player)
        feet = sorted(x for x, y in player if y == bottom)
        foot_y = bottom - 23
        logical_contact = sum(self.rendered_solid(camera_step, x, foot_y) for x in feet)
        visible_contact = sum(self.rendered_solid(camera_step, x, foot_y, True) for x in feet)
        logical_penetration = sum(self.rendered_solid(camera_step, x, foot_y - 1) for x in feet)
        visible_penetration = sum(self.rendered_solid(camera_step, x, foot_y - 1, True) for x in feet)
        visible_body_penetration = sum(self.rendered_solid(camera_step, x, y - 24, True) for x, y in player)
        enemy = self.sprite_opaque_pixels(actors, 2)
        owl_contact = sum((x, bottom + 1) in enemy for x in feet)
        visible_below = [y - foot_y for y in range(max(0, foot_y), 64)
                         if any(self.rendered_solid(camera_step, x, y, True) for x in feet)]
        return {"step": actors["step"], "foot_y": foot_y, "foot_columns": feet,
                "logical_contact_pixels": logical_contact, "visible_contact_pixels": visible_contact,
                "logical_penetration_pixels": logical_penetration, "visible_penetration_pixels": visible_penetration,
                "visible_body_penetration_pixels": visible_body_penetration,
                "owl_contact_pixels": owl_contact,
                "logical_state": "penetrating" if logical_penetration else "grounded" if logical_contact else "airborne",
                "visible_state": "penetrating" if visible_penetration else "grounded" if visible_contact else "airborne",
                "visible_support_gap": min(visible_below) if visible_below else None}

    def route_support_states(self):
        count = 512 if self.source_level == 1 else 472
        return [self.player_support(step, self.expected_sprites(step * 4 + 1)) for step in range(count)]

    def route_motion_diagnostics(self, states):
        count = len(states)
        cyclic = self.source_level == 1
        supported = [bool(state["visible_contact_pixels"] or state["owl_contact_pixels"])
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
                "owl_support_steps": sum(bool(state["owl_contact_pixels"]) for state in states),
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
        enemy = self.sprite_opaque_pixels(actors, 2)
        assert not player & enemy, (step, "Opaque Giana/owl collision", sorted(player & enemy))
        enemy_x = actors["positions"][2][0]
        if actors["visible"][2] and max(10, enemy_x) <= min(15, enemy_x + 5):
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


def verify(args):
    references = (SceneReference(1), SceneReference(2))
    reference = references[0]
    assert args.frames < len(reference.music_reference["calls"]), "Capture the independent original SID reference for this complete frame range"
    prefix = "levels-startup" if args.autostart_mode == 2 else "levels"
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
        event_steps.append(set(motion["launch_steps"]) | set(motion["landing_steps"]) | {0, 1, 470, 471})
    event_steps[0].update(set(range(80, 101)) | {215, 230, 300, 430, 440})
    (BUILD / f"{prefix}-motion.json").write_text(json.dumps({"levels": motions}, indent=2) + "\n")
    motion = motions[0]
    event_frames = {2, 225, 544, 1637, 1681, 1761, 1921, 2045, 2049}
    labels = read_labels(BUILD / "main.sym")
    program = BUILD / "giana.prg"
    required = ("frameStart", "frameDone", "frameCounter", "lightLevel", "incomingTile", "tilePixelX",
                "scrollCountdown", "terrainTiles", "terrainTilesEnd", "terrainMapStart", "terrainMapEnd",
                "terrainAccentMap", "terrainPerspectiveAccentMap", "terrainPerspectiveMiddleAccentMap",
                "terrainPerspectiveRightAccentMap", "tinySpriteFrames", "spriteWork0", "spriteWork1", "spriteWork2",
                "actorGround", "actorPlayerPath", "tvHighlightSprite", "cornerMaskFrames",
                "musicFrameStart", "musicFrameDone", "activeLevel", "levelTransition", "levelCameraStep",
                "actorStepLo", "actorStepHi", "actorGround2", "actorPlayerPath2", "terrain2Tiles",
                "terrain2TilesEnd", "terrain2MapStart", "terrain2MapEnd", "terrain2AccentMap",
                "terrain2PerspectiveAccentMap", "terrain2PerspectiveMiddleAccentMap", "terrain2PerspectiveRightAccentMap",
                "tinySpriteFrames2", "actorPlayerHeight")
    assert all(name in labels for name in required), "Build the scene before verifying it"
    work_addresses = tuple(labels[name] for name in ("spriteWork0", "spriteWork1", "spriteWork2"))
    assert labels["tinySpriteFrames"] == 0x0c00 and work_addresses == (0x0e80, 0x0ec0, 0x0f00)
    assert labels["tvHighlightSprite"] == 0x0f40
    assert labels["tinySpriteFrames2"] == 0x1a00
    assert all(address % 64 == 0 and address + 64 <= 0x1000 for address in work_addresses), "VIC work buffers must avoid the character-ROM window"
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    executable = args.vice or os.environ.get("VICE") or shutil.which("x64sc")
    assert executable, "Set VICE or --vice to a PAL-capable x64sc executable"
    command = vice_command(executable, program, port, reference.palette_path)
    command[command.index("-autostartprgmode") + 1] = str(args.autostart_mode)
    command += ["-initbreak", "reset", "-warp", "-sidengine", "1", "-sidmodel", "0", "-residsamp", "2",
                "-sounddev", "dump", "-soundarg", str(output / "sid-registers.txt")]
    if args.autostart_mode == 2:
        command += ["-drive8truedrive", "-autostartprgdiskimage", str(output / "autostart.d64")]
    result = {"passed": False, "emulator": "PAL VICE x64sc", "prg_sha256": digest(program.read_bytes()),
              "source_sha256": digest(reference.source),
              "project_sha256": digest(reference.project_path.read_bytes()),
              "game_area_cells": len(reference.game), "screen_light_cells": len(reference.light),
              "viewport_physical": [184, 24, 80, 64], "light_maps": [list(mapping) for mapping in LIGHT_MAPS],
              "protected_colors": list(PROTECTED_COLORS), "global_background": reference.background,
              "perspective_region_bounds_chars": list(REGION_BOUNDS),
              "perspective_source_rows": [list(rows) for rows in REGION_SOURCE_ROWS],
              "perspective_black_mask_rows": list(REGION_MASK_ROWS)}
    result.update({"autostart_prg_mode": args.autostart_mode, "command": command,
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
            music_start_break = breakpoint(monitor, labels["musicFrameStart"])
            music_done_break = breakpoint(monitor, labels["musicFrameDone"])
            monitor.run(f"disable {music_done_break}")
            breakpoint(monitor, labels["frameStart"])
            done_break = breakpoint(monitor, labels["frameDone"])
            monitor.run(f"disable {done_break}")
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
                assert 0 < music_update_cycles < (144 - 64) * 63, (frame, "Music missed graphics raster144", music_update_cycles)
                monitor.run(f"disable {music_done_break}")
                monitor.run(f"enable {music_start_break}")
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
                monitor.run("bank ram")
                ram = monitor.memory(output / "ram.bin", 0, 0xffff)
                actual_frame = int.from_bytes(ram[labels["frameCounter"]:labels["frameCounter"] + 2], "little")
                assert actual_frame == frame, (frame, actual_frame)
                reference.verify_music_state(frame, ram)
                level = ram[labels["lightLevel"]]
                expected_phase = 0 if frame < 14 else (1 + (frame - 14) // 16) % 4
                assert level == LIGHT_SEQUENCE[expected_phase], (frame, level, expected_phase)
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
                incoming = 40 + step if visible else 40 if transition == 254 else 40 - transition
                assert ram[labels["incomingTile"]] == incoming // 4 % 128, (frame, "Incoming map column")
                assert ram[labels["tilePixelX"]] == incoming % 4, (frame, "Incoming tile pixel")
                scene = (active, visible)
                if scene != previous_scene:
                    last_scene_change = frame
                    if previous_scene is not None and active != previous_scene[0]:
                        level_changes.append({"frame": frame, "from": previous_scene[0] + 1, "to": active + 1})
                    previous_scene = scene
                reference = references[active]
                assert ram[labels["actorPlayerHeight"]] == reference.player_height, (frame, "Active Giana height")
                bitmap = reference.expected_bitmap(step % 512)
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
                            address = labels[name + suffix]
                            assert ram[address:address + len(data)] == data
                    assert ram[0x1a00:0x1c00] == references[1].level2_player_planes
                    assert ram[labels["cornerMaskFrames"]:labels["cornerMaskFrames"] + 256] == reference.corner_data
                monitor.run("bank io")
                colors = bytes(value & 15 for value in monitor.memory(output / "colors.bin", 0xd800, 0xdbe7))
                assert colors == expected_colors, f"Frame {frame}: color RAM differs at level {level}"
                vic = monitor.memory(output / "vic.bin", 0xd000, 0xd03f)
                assert vic[0x11] & 0x7f == 0x3b and vic[0x16] & 0x3f == 0x18 and vic[0x18] & 0xfe == 0x18
                assert vic[0x20] & 15 == 0 and vic[0x21] & 15 == reference.background
                actual_actor_step = ram[labels["actorStepLo"]] + 256 * ram[labels["actorStepHi"]]
                assert actual_actor_step == expected_actor_step, (frame, "Actor camera phase", actual_actor_step, expected_actor_step)
                actor_reference = references[expected_actor_level]
                actors = actor_reference.verify_sprites(frame, ram, vic, work_addresses,
                                                        step=expected_actor_step, hidden=not visible)
                sprite_pixels = reference.sprite_pixels(actors) if visible else reference.corner_pixels
                clearance = reference.verify_actor_clearance(actors) if visible else None
                if visible:
                    assert expected_actor_level == active, (frame, "Revealed actors use the old level route")
                    support = reference.player_support(step % 512, actors)
                    assert support["visible_body_penetration_pixels"] == 0, (frame, "Opaque body entered rendered solid", support)
                    level_camera_steps[active].add(step)
                    level_world_columns[active].update((step + x) % 512 for x in range(40))
                    level_actor_steps[active].add(actors["step"])
                else:
                    transition_frames.append(frame)
                if visible and previous_actor_level == active and previous_actor_step is not None and actors["step"] != previous_actor_step:
                    assert actors["step"] == (previous_actor_step + 1) % 512, (frame, "Actor step skipped")
                    delta = abs(vic[11] - previous_player_y)
                    maximum_actor_y_delta = max(maximum_actor_y_delta, delta)
                if visible:
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
                    seen_player_poses.add(actors["poses"][0] // 2)
                if visible and actors["visible"][2]:
                    seen_enemy_poses.add(actors["poses"][2])
                    enemy_x = actors["positions"][2][0]
                    if enemy_x < 0:
                        seen_clip_modes.add("left")
                    if enemy_x + 6 > 40:
                        seen_clip_modes.add("right")
                    if 0 <= enemy_x and enemy_x + 6 <= 40:
                        seen_clip_modes.add("inside")
                    if enemy_x >= 24:
                        seen_clip_modes.add("x-high")
                if frame == 0:
                    cia = monitor.memory(output / "cia2.bin", 0xdd00, 0xdd03)
                    assert cia[0] & 3 == 3 and cia[2] & 3 == 3
                if level not in checked_levels:
                    reference.verify_protected_pixels(ram[0x2000:0x3f40], ram[0x0400:0x07e8], colors)
                    checked_levels.add(level)
                monitor.run("bank cpu")
                # At raster 144 the upper display is current and the lower display
                # retains the previous frame. Capture only after lighting has
                # remained stable for a complete visible frame.
                capture = frame > 0 and frame - last_transition >= 2 and frame - last_scene_change >= 2 and (
                    (frame <= 4096 and frame % 8 == 2) or frame in event_frames or
                    (visible and frame % 4 == 1 and actors["step"] in event_steps[active]) or
                    frame == args.frames or level not in saved_levels or visible and active not in saved_source_levels)
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
                    screenshots.append({"frame": frame, "light": level, "source_level": active + 1,
                                        "camera_step": step, "transition": transition})
                    if visible and active not in saved_source_levels:
                        actual.save(BUILD / f"level{active + 1}-selected.png")
                        saved_source_levels.add(active)
                    if level not in saved_levels:
                        actual.save(BUILD / f"{prefix}-level-{level}.png")
                        saved_levels.add(level)
                    if frame == 544 or (args.frames < 544 and frame == args.frames):
                        actual.save(BUILD / f"{prefix}.png")
                    if frame in (1637, 1681, 1761, 1921, 2045, 2049):
                        actual.save(BUILD / f"{prefix}-end-{actors['step']:03d}.png")
                    if frame <= 4096 and frame % 8 == 2:
                        animation.append(actual)
                monitor.run(f"enable {done_break}")
                monitor.run("x")
                done_pc, done_raster, done_cycles = monitor.registers()
                assert done_pc == labels["frameDone"]
                monitor.run(f"disable {done_break}")
                update_cycles = done_cycles - cycles
                assert 0 < update_cycles < (312 + 64 - 144) * 63, (frame, update_cycles, done_raster)
                samples.append({"frame": frame, "level": level, "start_cycles": cycles, "start_raster": raster,
                                "source_level": active + 1, "level_camera_step": step, "level_transition": transition,
                                "cadence_cycles": cadence, "update_cycles": update_cycles,
                                "completion_raster": done_raster, "actor_step": actors["step"],
                                "sprite_enables": vic[0x15], "music_start_cycles": music_start_cycles,
                                "music_done_cycles": music_done_cycles, "music_update_cycles": music_update_cycles,
                                "music_start_raster": music_raster, "music_completion_raster": music_done_raster,
                                "music_cadence_cycles": music_cadence,
                                "music_sequence_position": ram[0x41e4]})
                # Model the visible scheduler contract from the sampled state.
                # Each refill consumes one normal PAL frame and never suppresses
                # a music call. Room-light frames deliberately hold the refill.
                if transition == 255:
                    expected_active ^= 1
                    expected_camera = 0
                    expected_transition = 40
                elif transition == 254:
                    if frame % 16 != 13:
                        expected_actor_level = active
                        expected_actor_step = 0
                        expected_scroll_countdown = (3 - frame % 4) or 4
                        expected_transition = 0
                elif transition:
                    if frame % 16 != 13:
                        expected_transition = transition - 1 or 254
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
                if frame % 256 == 0:
                    print(f"Verified PAL frame {frame}/{args.frames}; Level{active + 1} pixel {step}; light {level}; transition {transition}", flush=True)
        assert checked_levels == {0, 1, 2}, "Run at least 32 frames to exercise every automatic light level"
        # Flush the real SID write sink before comparing every complete call.
        connection.sendall(b"quit\n")
        connection.close()
        connection = None
        process.wait(timeout=5)
        sid_events = read_sid_events(output / "sid-registers.txt")
        event_index = 0
        compared_writes = 0
        for sample in samples:
            while event_index < len(sid_events) and sid_events[event_index][0] < sample["music_start_cycles"]:
                event_index += 1
            values = []
            while event_index < len(sid_events) and sid_events[event_index][0] < sample["music_done_cycles"]:
                values.append(list(sid_events[event_index][1:]))
                event_index += 1
            expected_values = reference.music_reference["calls"][sample["frame"]]["events"]
            assert values == expected_values, (sample["frame"], "SID writes differ from original RSID call", values, expected_values)
            compared_writes += len(values)
        sequence_wraps = [sample["frame"] for previous, sample in zip(samples, samples[1:])
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
            assert seen_player_poses == {0, 1, 2, 3} and seen_enemy_poses == {8, 9}
            assert seen_sprite_enables == {0x0f, 0x7f, 0xff}
            assert seen_clip_modes == {"left", "right", "inside", "x-high"}
            assert cleared_owl_sections == {0, 64, 128, 192, 320, 448}
            assert len(owl_overlap_steps) == 66
        if args.frames >= 4096:
            assert [(change["from"], change["to"]) for change in level_changes[:2]] == [(1, 2), (2, 1)]
            assert level_camera_steps == [set(range(513)), set(range(473))]
            assert level_actor_steps == [set(range(512)), set(range(472))]
            assert all(columns == set(range(512)) for columns in level_world_columns), "Both complete original maps must reach the TV"
            assert saved_source_levels == {0, 1}
            assert samples[-1]["source_level"] == 1 and samples[-1]["level_transition"] == 0
        animation[0].save(BUILD / f"{prefix}.gif", save_all=True, append_images=animation[1:],
                          duration=160, loop=0, optimize=False, disposal=1)
        (output / "timing.json").write_text(json.dumps(samples, indent=2) + "\n")
        updates = [sample["update_cycles"] for sample in samples]
        cadences = [sample["cadence_cycles"] for sample in samples if sample["cadence_cycles"] is not None]
        result.update({"passed": True, "frame_range": [0, args.frames], "frames_verified": len(samples),
                       "unique_scroll_states_per_level": [len(states) for states in level_camera_steps],
                       "map_columns_visible_per_level": [len(columns) for columns in level_world_columns],
                       "level_end_camera_steps": [512, 472], "level_transitions": level_changes,
                       "level1_level2_level1_verified": args.frames >= 4096,
                       "transition_hidden_pal_frames": transition_frames,
                       "per_level_screen_bytes": [source.game_screen for source in references],
                       "expected_terrain_from_original_character_sources": True,
                       "level2_source_block_stream_independently_expanded": True,
                       "automatic_light_sequence": list(LIGHT_SEQUENCE), "light_interval_pal_frames": 16,
                       "light_transitions": transitions, "light_levels_verified": sorted(checked_levels),
                       "light_remaps_from_original_verified": True, "outside_marked_cells_changes": 0,
                       "bitmap_changes_outside_game_area": 0, "protected_multicolor_pixels_per_level": len(reference.protected_pixels),
                       "protected_color_pixel_changes": 0, "vic_mode_and_bank_verified": True,
                       "sky_blue_verified": sky_blue_verified, "object_color_probes": sorted(checked_objects),
                       "blue_clothes_verified": blue_clothes_verified,
                       "actor_steps_verified_per_level": [len(steps) for steps in level_actor_steps],
                       "actor_reset_tested": args.frames >= 4096,
                       "giana_poses_verified": sorted(seen_player_poses), "owl_frames_verified": sorted(seen_enemy_poses),
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
                       "rounded_corners_static_foremost_verified": True,
                       "rounded_corners_bitmap_modifications": 0,
                       "music_calls_verified": len(samples), "music_sid_register_writes_compared": compared_writes,
                       "music_register_sequence_matches_original_rsid": True,
                       "music_mutable_state_matches_original_rsid_each_call": True,
                       "music_structural_score_wrap_frames": sequence_wraps,
                       "music_complete_first_loop_verified": bool(sequence_wraps),
                       "music_sequence_positions": sorted({sample["music_sequence_position"] for sample in samples}),
                       "music_update_cycles_min": min(sample["music_update_cycles"] for sample in samples),
                       "music_update_cycles_max": max(sample["music_update_cycles"] for sample in samples),
                       "music_completion_raster_min": min(sample["music_completion_raster"] for sample in samples),
                       "music_completion_raster_max": max(sample["music_completion_raster"] for sample in samples),
                       "music_sampler_cia2_disabled": True,
                       "giana_visible_all_actor_steps": [len(steps) == count for steps, count in zip(level_actor_steps, (512, 472))],
                       "opaque_actor_collision_pixels": 0,
                       "owl_encounters_cleared": sorted(cleared_owl_sections),
                       "owl_overlap_states_verified": len(owl_overlap_steps),
                       "minimum_owl_clearance_pixels": min(owl_clearances) if owl_clearances else None,
                       "owl_clearance_policy": "Exact opaque pixel separation; bounding-box clearance is diagnostic only",
                       "rendered_ground_contacts": motion["terrain_contact_steps"], "owl_head_support_steps": motion["owl_support_steps"],
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
    parser.add_argument("--frames", type=int, default=5205, help="PAL frame range endpoint; minimum 35")
    parser.add_argument("--autostart-mode", type=int, choices=(1, 2), default=1, help="VICE PRG load mode; 2 exercises true-drive disk autostart")
    args = parser.parse_args()
    if args.frames < 35:
        parser.error("--frames must be at least 35 to capture every lighting state")
    verify(args)


if __name__ == "__main__":
    main()
