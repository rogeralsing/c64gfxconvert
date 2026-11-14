#!/usr/bin/env python3
"""Verify the built Giana scene in PAL VICE against the original Koala and masks.

Run after ./giana/build.sh. No monitor writes or special test build are used.
The default run covers all 512 terrain positions and its 2,048-frame wrap.
"""

import argparse
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

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "giana/build"
sys.path.insert(0, str(ROOT / "mydemo/discoball"))
from vice_support import Monitor, connect_monitor, read_labels, vice_command


LIGHT_ONE = (0, 1, 2, 7, 10, 15, 6, 1, 10, 9, 15, 11, 15, 1, 15, 7)
LIGHT_MAPS = (tuple(range(16)), LIGHT_ONE, tuple(LIGHT_ONE[color] for color in LIGHT_ONE))
LIGHT_SEQUENCE = (0, 1, 2, 1)
PROTECTED_COLORS = (0, 1, 2, 6, 9, 11)


def digest(data):
    return hashlib.sha256(data).hexdigest()


class SceneReference:
    """Decode source files directly, independently of generated runtime tables."""

    def __init__(self):
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
        self.tiles = (ROOT / "giana/assets/level1-tiles.bin").read_bytes()
        self.tile_map = (ROOT / "giana/assets/level1-tv-map.bin").read_bytes()
        self.accents = (ROOT / "giana/assets/level1-accents.bin").read_bytes()
        assert len(self.tiles) % 8 == 0 and len(self.tile_map) == 128 * 8 and len(self.accents) == 512
        self.palette_path = ROOT / "palettes/peptoette-a.vpl"
        self.palette = [tuple(int(value, 16) for value in line.split()[:3])
                        for line in self.palette_path.read_text().splitlines()
                        if line.strip() and not line.lstrip().startswith("#")]
        assert len(self.palette) == 16
        self.protected_pixels = []
        for cell in self.light:
            colors = (self.background, self.screen[cell] >> 4, self.screen[cell] & 15, self.colors[cell])
            for row in range(8):
                offset = cell * 8 + row
                for shift in (6, 4, 2, 0):
                    color = colors[(self.bitmap[offset] >> shift) & 3]
                    if color in PROTECTED_COLORS:
                        self.protected_pixels.append((cell, offset, shift, color))

    @lru_cache(maxsize=512)
    def expected_bitmap(self, step):
        bitmap = bytearray(self.bitmap)
        for y in range(64):
            for byte_x in range(10):
                packed = 0
                for pixel in range(4):
                    world_x = (step + byte_x * 4 + pixel) % 512
                    tile = self.tile_map[(y // 8) * 128 + world_x // 4]
                    source = self.tiles[tile * 8 + y % 8]
                    packed = (packed << 2) | ((source >> (6 - 2 * (world_x % 4))) & 3)
                cell = (y // 8 + 3) * 40 + 23 + byte_x
                bitmap[cell * 8 + y % 8] = packed
        return bytes(bitmap)

    def expected_colors(self, step, level):
        mapping = LIGHT_MAPS[level]
        screen = bytearray(self.screen)
        colors = bytearray(self.colors)
        for cell in self.light:
            original = self.screen[cell]
            screen[cell] = (mapping[original >> 4] << 4) | mapping[original & 15]
            colors[cell] = mapping[self.colors[cell]]
        for column in range(10):
            flags = self.accents[(step % 4) * 128 + (step // 4 + column) % 128]
            for row in range(8):
                cell = (row + 3) * 40 + 23 + column
                screen[cell] = 0xe8
                colors[cell] = 7 if flags & (1 << row) else 5
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


def breakpoint(monitor, address):
    response = monitor.run(f"break {address:04x}")
    match = re.search(r"BREAK:\s*(\d+)", response)
    assert match, response
    return int(match[1])


def verify(args):
    reference = SceneReference()
    output = BUILD / "giana5-check"
    output.mkdir(parents=True, exist_ok=True)
    labels = read_labels(BUILD / "main.sym")
    program = BUILD / "giana.prg"
    required = ("frameStart", "frameDone", "frameCounter", "lightLevel", "incomingTile", "tilePixelX",
                "scrollCountdown", "terrainTiles", "terrainTilesEnd", "terrainMapStart", "terrainMapEnd",
                "terrainAccentMap")
    assert all(name in labels for name in required), "Build the scene before verifying it"
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    executable = args.vice or os.environ.get("VICE") or shutil.which("x64sc")
    assert executable, "Set VICE or --vice to a PAL-capable x64sc executable"
    command = vice_command(executable, program, port, reference.palette_path)
    command += ["-initbreak", "reset", "-warp"]
    result = {"passed": False, "emulator": "PAL VICE x64sc", "prg_sha256": digest(program.read_bytes()),
              "source_sha256": digest(reference.source),
              "project_sha256": digest(reference.project_path.read_bytes()),
              "game_area_cells": len(reference.game), "screen_light_cells": len(reference.light),
              "viewport_physical": [184, 24, 80, 64], "light_maps": [list(mapping) for mapping in LIGHT_MAPS],
              "protected_colors": list(PROTECTED_COLORS), "global_background": reference.background}
    started = time.monotonic()
    samples = []
    transitions = []
    screenshots = []
    animation = []
    checked_levels = set()
    saved_levels = set()
    checked_objects = set()
    sky_blue_verified = False
    previous_cycles = None
    previous_level = None
    last_transition = -100
    process = None
    connection = None
    monitor = None
    try:
        with (output / "vice.log").open("w") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            connection = connect_monitor(process, port)
            monitor = Monitor(connection)
            monitor.run("r")
            monitor.run("sidefx off")
            breakpoint(monitor, labels["frameStart"])
            done_break = breakpoint(monitor, labels["frameDone"])
            monitor.run(f"disable {done_break}")
            for frame in range(args.frames + 1):
                monitor.run("x")
                pc, raster, cycles = monitor.registers()
                assert pc == labels["frameStart"], f"Frame {frame}: stopped at ${pc:04x}"
                assert raster == 144, (frame, raster)
                cadence = None if previous_cycles is None else cycles - previous_cycles
                if cadence is not None:
                    assert abs(cadence - 19656) <= 9, (frame, cadence)
                previous_cycles = cycles
                monitor.run("bank ram")
                ram = monitor.memory(output / "ram.bin", 0, 0xffff)
                actual_frame = int.from_bytes(ram[labels["frameCounter"]:labels["frameCounter"] + 2], "little")
                assert actual_frame == frame, (frame, actual_frame)
                level = ram[labels["lightLevel"]]
                expected_phase = 0 if frame < 14 else (1 + (frame - 14) // 16) % 4
                assert level == LIGHT_SEQUENCE[expected_phase], (frame, level, expected_phase)
                if level != previous_level:
                    transitions.append({"frame": frame, "level": level})
                    last_transition = frame
                    previous_level = level
                step = frame // 4
                assert ram[labels["incomingTile"]] == (10 + step // 4) % 128
                assert ram[labels["tilePixelX"]] == step % 4
                assert ram[labels["scrollCountdown"]] == 4 - frame % 4
                bitmap = reference.expected_bitmap(step % 512)
                screen, expected_colors = reference.expected_colors(step % 512, level)
                assert ram[0x2000:0x3f40] == bitmap, f"Frame {frame}: bitmap differs from independent terrain decode"
                assert ram[0x0400:0x07e8] == screen, f"Frame {frame}: scene screen colors differ at level {level}"
                if frame == 0:
                    assert ram[labels["terrainTiles"]:labels["terrainTilesEnd"]] == reference.tiles
                    assert ram[labels["terrainMapStart"]:labels["terrainMapEnd"]] == reference.tile_map
                    assert ram[labels["terrainAccentMap"]:labels["terrainAccentMap"] + 512] == reference.accents
                monitor.run("bank io")
                colors = bytes(value & 15 for value in monitor.memory(output / "colors.bin", 0xd800, 0xdbe7))
                assert colors == expected_colors, f"Frame {frame}: color RAM differs at level {level}"
                vic = monitor.memory(output / "vic.bin", 0xd000, 0xd03f)
                assert vic[0x11] & 0x7f == 0x3b and vic[0x16] & 0x3f == 0x18 and vic[0x18] & 0xfe == 0x18
                assert vic[0x15] == 0 and vic[0x20] & 15 == 0 and vic[0x21] & 15 == reference.background
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
                capture = frame > 0 and frame - last_transition >= 2 and (
                    (frame <= 257 and frame % 4 == 1) or frame == 544 or
                    frame == args.frames or level not in saved_levels)
                if capture:
                    screenshot = output / f"frame-{frame:04d}.png"
                    monitor.run(f'screenshot "{screenshot}" 2')
                    with Image.open(screenshot) as image:
                        actual = image.convert("RGB")
                    display = actual.crop((32, 35, 352, 235))
                    expected = reference.decode(bitmap, screen, colors)
                    actual_rgb, expected_rgb = display.tobytes(), expected.tobytes()
                    differences = sum(actual_rgb[offset:offset + 3] != expected_rgb[offset:offset + 3]
                                      for offset in range(0, len(actual_rgb), 3))
                    assert differences == 0, (frame, level, differences)
                    assert display.getpixel((184, 24)) == reference.palette[14], "TV sky must be light blue"
                    sky_blue_verified = True
                    probes = {
                        2: (("bush", 17, 45, 5),),
                        225: (("bonus", 94, 11, 7),),
                        544: (("pipe", 146, 35, 7), ("nearby_bush", 165, 46, 5)),
                    }
                    for name, world_x, world_y, color in probes.get(frame, ()):
                        offset_x = (world_x - step) % 512
                        assert offset_x < 40
                        assert display.getpixel((184 + offset_x * 2, 24 + world_y)) == reference.palette[color], name
                        checked_objects.add(name)
                    screenshots.append({"frame": frame, "level": level})
                    if level not in saved_levels:
                        actual.save(BUILD / f"giana5-level-{level}.png")
                        saved_levels.add(level)
                    if frame == 544:
                        actual.save(BUILD / "giana5-blue-sky.png")
                    if frame <= 257 and frame % 4 == 1:
                        animation.append(actual)
                monitor.run(f"enable {done_break}")
                monitor.run("x")
                done_pc, done_raster, done_cycles = monitor.registers()
                assert done_pc == labels["frameDone"]
                monitor.run(f"disable {done_break}")
                update_cycles = done_cycles - cycles
                assert 0 < update_cycles < (312 + 74 - 144) * 63, (frame, update_cycles, done_raster)
                samples.append({"frame": frame, "level": level, "start_cycles": cycles, "start_raster": raster,
                                "cadence_cycles": cadence, "update_cycles": update_cycles,
                                "completion_raster": done_raster})
                if frame % 256 == 0:
                    print(f"Verified PAL frame {frame}/{args.frames}; world pixel {step % 512}; light {level}", flush=True)
        assert checked_levels == {0, 1, 2}, "Run at least 32 frames to exercise every automatic light level"
        assert saved_levels == {0, 1, 2}, "Run at least 35 frames to capture every light level"
        assert sky_blue_verified
        if args.frames >= 544:
            assert checked_objects == {"bush", "bonus", "pipe", "nearby_bush"}
        animation[0].save(BUILD / "giana5.gif", save_all=True, append_images=animation[1:],
                          duration=80, loop=0, optimize=False, disposal=1)
        (output / "timing.json").write_text(json.dumps(samples, indent=2) + "\n")
        updates = [sample["update_cycles"] for sample in samples]
        cadences = [sample["cadence_cycles"] for sample in samples if sample["cadence_cycles"] is not None]
        result.update({"passed": True, "frame_range": [0, args.frames], "frames_verified": len(samples),
                       "unique_scroll_states": min(512, args.frames // 4 + 1),
                       "map_loop_tested": args.frames >= 2048, "map_loop_frames": 2048,
                       "automatic_light_sequence": list(LIGHT_SEQUENCE), "light_interval_pal_frames": 16,
                       "light_transitions": transitions, "light_levels_verified": sorted(checked_levels),
                       "light_remaps_from_original_verified": True, "outside_marked_cells_changes": 0,
                       "bitmap_changes_outside_game_area": 0, "protected_multicolor_pixels_per_level": len(reference.protected_pixels),
                       "protected_color_pixel_changes": 0, "vic_mode_and_bank_verified": True,
                       "sky_blue_verified": sky_blue_verified, "object_color_probes": sorted(checked_objects),
                       "screenshot_frames": screenshots, "screenshot_pixels_compared_each": 64000,
                       "screenshot_pixel_differences": 0, "palette": "peptoette-a",
                       "update_cycles_min": min(updates), "update_cycles_max": max(updates),
                       "completion_raster_min": min(sample["completion_raster"] for sample in samples),
                       "completion_raster_max": max(sample["completion_raster"] for sample in samples),
                       "cadence_cycles_min": min(cadences), "cadence_cycles_max": max(cadences),
                       "animation": "giana5.gif", "animation_frames": len(animation),
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
        (BUILD / "giana5-verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vice", help="Path to x64sc; defaults to VICE or PATH")
    parser.add_argument("--frames", type=int, default=2048, help="PAL frame range endpoint; minimum 35")
    args = parser.parse_args()
    if args.frames < 35:
        parser.error("--frames must be at least 35 to capture every lighting state")
    verify(args)


if __name__ == "__main__":
    main()
