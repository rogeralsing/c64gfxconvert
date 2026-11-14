#!/usr/bin/env python3
"""Fit the verified original C64 Stage 1 into the bitmap TV tile-map format.

Run offline from any directory. The retained inputs contain only original map,
character graphics, character colors, and the display palette. No game program
or music is needed to rebuild the demo assets.
"""

import argparse
from collections import Counter
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
PROGRAM_SHA256 = "0f1a720961fa52102fcfd52e46e40df07e5e307328ad087d55cc00506f904880"
SOURCE_WIDTH = 2048
SOURCE_HEIGHT = 160
MAP_WIDTH = 128
MAP_HEIGHT = 8
TV_COLORS = (8, 9, 0, 5, 7)
BASE_CODES = {0: 0, 9: 1, 8: 2}
SOURCE_BACKGROUND = 14
SOURCE_MULTICOLORS = (8, 9)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_verified(name):
    data = (ASSETS / name).read_bytes()
    if digest(data) != INPUT_HASHES[name]:
        raise ValueError(f"Original input changed: {name}")
    return data


def extract_sources(disk_path):
    """Read original directory file 1 and retain only the three graphics slices."""
    disk = disk_path.read_bytes()
    if len(disk) != 174848:
        raise ValueError("Expected the documented original 35-track D64")

    def sectors(track):
        return 21 if track <= 17 else 19 if track <= 24 else 18 if track <= 30 else 17

    def sector(track, number):
        if not 1 <= track <= 35 or not 0 <= number < sectors(track):
            raise ValueError("Invalid D64 sector link")
        offset = (sum(sectors(previous) for previous in range(1, track)) + number) * 256
        return disk[offset:offset + 256]

    track, number = 18, 1
    seen = set()
    program_start = None
    while track:
        if (track, number) in seen:
            raise ValueError("D64 directory chain loops")
        seen.add((track, number))
        data = sector(track, number)
        for offset in range(0, 256, 32):
            entry = data[offset:offset + 32]
            if entry[2] and entry[5:21].rstrip(b"\xa0") == b"1":
                program_start = (entry[3], entry[4])
        track, number = data[:2]
    if program_start is None:
        raise ValueError("Original program file 1 is absent")

    track, number = program_start
    seen = set()
    program = bytearray()
    while track:
        if (track, number) in seen:
            raise ValueError("D64 program sector chain loops")
        seen.add((track, number))
        data = sector(track, number)
        if data[0] == 0 and not 1 <= data[1] <= 255:
            raise ValueError("Invalid D64 final-sector length")
        program.extend(data[2:] if data[0] else data[2:data[1] + 1])
        track, number = data[:2]
    if len(program) != 63443 or digest(program) != PROGRAM_SHA256:
        raise ValueError("Disk file 1 does not match the unmodified original game")
    assert program[:2] == b"\x20\x08"
    memory = bytearray(65536)
    memory[0x0820:0x0820 + len(program) - 2] = program[2:]
    for name, first, last in (("original-level1-map.bin", 0xac00, 0xc000),
                              ("original-charset.bin", 0xc000, 0xc800),
                              ("original-char-colors.bin", 0xab00, 0xac00)):
        data = memory[first:last]
        assert digest(data) == INPUT_HASHES[name]
        (ASSETS / name).write_bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disk", type=Path, help="Re-extract source slices from the documented original D64")
    args = parser.parse_args()
    if args.disk:
        extract_sources(args.disk)
    original_map = read_verified("original-level1-map.bin")
    charset = read_verified("original-charset.bin")
    attributes = read_verified("original-char-colors.bin")
    assert (len(original_map), len(charset), len(attributes)) == (5120, 2048, 256)

    palette = [tuple(int(value, 16) for value in line.split()[:3])
               for line in read_verified("peptoette-a.vpl").decode().splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    assert len(palette) == 16
    quantize = [min(TV_COLORS, key=lambda target: sum(
        (palette[source][channel] - palette[target][channel]) ** 2
        for channel in range(3))) for source in range(16)]
    # Black sky uses code 0, sharing the surrounding bitmap's black background.
    quantize[SOURCE_BACKGROUND] = 0

    pixels = []
    semantic_pixels = []
    source_colors = Counter()
    for y in range(MAP_HEIGHT * 8):
        source_y = (2 * y + 1) * SOURCE_HEIGHT // (MAP_HEIGHT * 16)
        row = []
        semantic_row = []
        for x in range(MAP_WIDTH * 4):
            # One output multicolor pixel covers four source physical pixels.
            source_x = x * 4 + 2
            character = original_map[(source_y // 8) * 256 + source_x // 8]
            bits = charset[character * 8 + source_y % 8]
            attribute = attributes[character]
            if attribute < 8:
                foreground = (bits >> (7 - source_x % 8)) & 1
                source_color = attribute if foreground else SOURCE_BACKGROUND
            else:
                code = (bits >> (6 - 2 * ((source_x % 8) // 2))) & 3
                source_color = (SOURCE_BACKGROUND, *SOURCE_MULTICOLORS, attribute & 7)[code]
            output_color = quantize[source_color]
            row.append(BASE_CODES.get(output_color, 3))
            semantic_row.append(output_color)
            source_colors[source_color] += 1
        pixels.append(row)
        semantic_pixels.append(semantic_row)

    # Keep green/yellow meaning separate from the deduplicated pixel patterns.
    # Each phase has 128 bytes; each byte packs the eight character-row flags.
    accent_flags = bytearray()
    accent_conflicts = Counter()
    accent_conflict_pixels = Counter()
    accent_conflict_examples = []
    for phase in range(4):
        for column in range(MAP_WIDTH):
            flags = 0
            for row in range(MAP_HEIGHT):
                colors = Counter(semantic_pixels[row * 8 + y][(column * 4 + phase + x) % (MAP_WIDTH * 4)]
                                 for y in range(8) for x in range(4))
                yellow = colors[7] > 0 and colors[7] >= colors[5]
                flags |= int(yellow) << row
                if colors[5] and colors[7]:
                    accent_conflicts[phase] += 1
                    accent_conflict_pixels[phase] += min(colors[5], colors[7])
                    if len(accent_conflict_examples) < 16:
                        accent_conflict_examples.append({"phase": phase, "column": column, "row": row,
                                                         "green_pixels": colors[5], "yellow_pixels": colors[7],
                                                         "selected_color": 7 if yellow else 5})
            accent_flags.append(flags)
    assert len(accent_flags) == 512

    accent_pixels_verified = 0
    for phase in range(4):
        for column in range(MAP_WIDTH):
            for row in range(MAP_HEIGHT):
                window = [semantic_pixels[row * 8 + y][(column * 4 + phase + x) % (MAP_WIDTH * 4)]
                          for y in range(8) for x in range(4)]
                if 5 in window and 7 in window:
                    continue
                actual = 7 if accent_flags[phase * MAP_WIDTH + column] & (1 << row) else 5
                for color in window:
                    if color in (5, 7):
                        assert color == actual
                        accent_pixels_verified += 1

    patterns = []
    pattern_ids = {}
    tile_map = bytearray()
    for tile_y in range(MAP_HEIGHT):
        for tile_x in range(MAP_WIDTH):
            pattern = bytes(sum(pixels[tile_y * 8 + row][tile_x * 4 + pair]
                                << (6 - pair * 2) for pair in range(4))
                            for row in range(8))
            if pattern not in pattern_ids:
                pattern_ids[pattern] = len(patterns)
                patterns.append(pattern)
            tile_map.append(pattern_ids[pattern])
    if len(patterns) > 256:
        raise ValueError("The TV map requires more than one byte per tile ID")
    tile_bytes = b"".join(patterns)

    # Reconstruct the downsampled pixel field from the final map and patterns.
    # This guards the two separate runtime inputs against ordering mistakes.
    for y, row in enumerate(pixels):
        for x, expected in enumerate(row):
            tile = tile_map[(y // 8) * MAP_WIDTH + x // 4]
            actual = (tile_bytes[tile * 8 + y % 8] >> (6 - 2 * (x % 4))) & 3
            assert actual == expected

    (ASSETS / "level1-tiles.bin").write_bytes(tile_bytes)
    (ASSETS / "level1-tv-map.bin").write_bytes(tile_map)
    (ASSETS / "level1-accents.bin").write_bytes(accent_flags)
    assembly = [
        "// Generated by tools/prepare-level1.py from the original C64 Stage 1.",
        "// Complete source layout; graphics are reduced to fit the 64-line TV.",
        "// Pixel codes: 0 = black ($0), 1 = brown ($9), 2 = orange ($8), 3 = cell accent ($5/$7).",
        ".const TERRAIN_BACKGROUND = 0",
        ".const TERRAIN_SCREEN_COLORS = $98",
        f".const TERRAIN_MAP_WIDTH = {MAP_WIDTH}",
        f".const TERRAIN_MAP_HEIGHT = {MAP_HEIGHT}",
        f".const TERRAIN_TILE_COUNT = {len(patterns)}",
        '.var level1TilesFile = LoadBinary("assets/level1-tiles.bin")',
        '.var level1MapFile = LoadBinary("assets/level1-tv-map.bin")',
        '.var level1AccentFile = LoadBinary("assets/level1-accents.bin")',
        "",
        "terrainTiles:",
        "    .fill level1TilesFile.getSize(), level1TilesFile.get(i)",
        "terrainTilesEnd:",
        '.assert "Every terrain tile contains eight bytes", terrainTilesEnd - terrainTiles, TERRAIN_TILE_COUNT * 8',
        "",
        "terrainMapStart:",
    ]
    for row in range(MAP_HEIGHT):
        assembly.extend([f"terrainMapRow{row}:",
                         f"    .fill TERRAIN_MAP_WIDTH, level1MapFile.get(i + {row * MAP_WIDTH})"])
    assembly.extend([
        "terrainMapEnd:",
        '.assert "Terrain map contains eight 128-column rows", terrainMapEnd - terrainMapStart, TERRAIN_MAP_WIDTH * TERRAIN_MAP_HEIGHT',
        "",
        ".align $100",
        "// Offset = phase * 128 + world column; bit 0 is row 0. Set means yellow.",
        "terrainAccentMap:",
        "    .fill level1AccentFile.getSize(), level1AccentFile.get(i)",
        "terrainDataEnd:",
        '.assert "Accent table has four 128-column phases", terrainDataEnd - terrainAccentMap, 512',
        '.assert "Accent table is page aligned", <terrainAccentMap, 0',
        "",
    ])
    (PART / "terrain.asm").write_text("\n".join(assembly))

    receipt = {
        "original_map_dimensions_chars": [256, 20],
        "original_dimensions_physical_pixels": [SOURCE_WIDTH, SOURCE_HEIGHT],
        "output_map_dimensions_tiles": [MAP_WIDTH, MAP_HEIGHT],
        "output_dimensions_physical_pixels": [MAP_WIDTH * 8, MAP_HEIGHT * 8],
        "vertical_crop_pixels": 0,
        "sampling": "nearest center; horizontal physical scale 1/2, vertical scale 2/5",
        "source_background": SOURCE_BACKGROUND,
        "source_multicolors": list(SOURCE_MULTICOLORS),
        "output_colors": list(TV_COLORS),
        "output_shared_colors": [0, 9, 8],
        "output_accent_colors": [5, 7],
        "source_color_to_output_color": quantize,
        "source_color_to_output_code": [BASE_CODES.get(color, 3) for color in quantize],
        "sampled_source_color_pixel_counts": dict(sorted(source_colors.items())),
        "semantic_output_color_pixel_counts": dict(sorted(Counter(color for row in semantic_pixels for color in row).items())),
        "unique_tiles": len(patterns),
        "tile_bytes": len(tile_bytes),
        "map_bytes": len(tile_map),
        "accent_bytes": len(accent_flags),
        "accent_layout": "offset=phase*128+world_column; bit=row; 0=green5, 1=yellow7",
        "accent_selection": "yellow when yellow_count>0 and yellow_count>=green_count; otherwise green",
        "accent_conflict_cells": sum(accent_conflicts.values()),
        "accent_conflict_cells_by_phase": {str(phase): accent_conflicts[phase] for phase in range(4)},
        "accent_conflict_pixels_by_phase": {str(phase): accent_conflict_pixels[phase] for phase in range(4)},
        "accent_conflict_examples": accent_conflict_examples,
        "accent_pixels_verified_without_conflict": accent_pixels_verified,
        "source_sha256": INPUT_HASHES,
        "output_sha256": {"level1-tiles.bin": digest(tile_bytes),
                          "level1-tv-map.bin": digest(tile_map),
                          "level1-accents.bin": digest(accent_flags)},
        "tile_usage": dict(sorted(Counter(tile_map).items())),
        "reconstructed_pixel_codes_verified": MAP_WIDTH * 4 * MAP_HEIGHT * 8,
    }
    (ASSETS / "level1-import.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"Original Stage 1 imported: {len(patterns)} tiles ({len(tile_bytes)} bytes), "
          f"{MAP_WIDTH}x{MAP_HEIGHT} map ({len(tile_map)} bytes), "
          f"{len(accent_flags)} accent bytes; no crop.")


if __name__ == "__main__":
    main()
