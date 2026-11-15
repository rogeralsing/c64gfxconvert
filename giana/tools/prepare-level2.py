#!/usr/bin/env python3
"""Prepare original C64 Stage 2 from retained, verified map-compression data."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import runpy


PART = Path(__file__).resolve().parents[1]
ASSETS = PART / "assets"
PROGRAM_SHA256 = "0f1a720961fa52102fcfd52e46e40df07e5e307328ad087d55cc00506f904880"
INPUT_HASHES = {
    "original-level2-stream.bin": "c8a93fc534bcea121b4632a417e3582797246e083dd9496641681929b8e71ce1",
    "original-level2-block-pointers.bin": "2f8b7e4a97adbb557db2495b599f5a57106647681f8c1d6f1c0d675e9e0b4caf",
    "original-level2-block-data.bin": "49b9c157f3180a60ae3adbafddf054991604c310bd6367d50b39e9df82e816e6",
    "original-charset.bin": "eb453a70a5c3cdf177e19868cdb663b8e0182e90a4368d78b25edbbbe24ea668",
    "original-char-colors.bin": "74ccc485e71ad8505c1c30932f07f728624f822e9277fecb659f63209287966a",
    "peptoette-a.vpl": "4a762159d75af98b510d43b709c4a1243f85ad706e594cf4a24fee0165f7b6ed",
}
MAP_SHA256 = "2a2b29e84ae20b88172fe7ec4d23f2531360403ca8b9c8365a5a29f211bc487c"
SOURCE_SLICES = (("original-level2-stream.bin", 0x62be, 0x643b),
                 ("original-level2-block-pointers.bin", 0x9200, 0x9262),
                 ("original-level2-block-data.bin", 0x9286, 0x9495))
MAP_WIDTH, MAP_HEIGHT = 128, 8
TV_COLORS = (9, 10, 2, 5, 7)
BASE_CODES = {9: 0, 10: 1, 2: 2}
SOURCE_BACKGROUND = 0
SOURCE_MULTICOLORS = (10, 2)
PERSPECTIVE_FILES = ("level2-perspective-accents.bin", "level2-perspective-middle-accents.bin",
                     "level2-perspective-right-accents.bin", "level2-accents.bin")
PERSPECTIVE_LABELS = ("terrain2PerspectiveAccentMap", "terrain2PerspectiveMiddleAccentMap",
                      "terrain2PerspectiveRightAccentMap", "terrain2AccentMap")
# Keep the established TV geometry in one source; loading it has no write effects.
GEOMETRY = runpy.run_path(str(PART / "tools" / "prepare-level1.py"))
PERSPECTIVE_COLUMNS = GEOMETRY["PERSPECTIVE_COLUMNS"]
PERSPECTIVE_SOURCE_ROWS = GEOMETRY["PERSPECTIVE_SOURCE_ROWS"]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_verified(name):
    data = (ASSETS / name).read_bytes()
    if digest(data) != INPUT_HASHES[name]:
        raise ValueError(f"Original input changed: {name}")
    return data


def extract_sources(path):
    program = path.read_bytes()
    if digest(program) != PROGRAM_SHA256 or program[:2] != b"\x20\x08":
        raise ValueError("Expected the verified, unmodified original disk file 1")
    memory = bytearray(65536)
    memory[0x820:0x820 + len(program) - 2] = program[2:]
    assert int.from_bytes(memory[0x6002:0x6004], "little") == 0x62be
    for name, first, last in SOURCE_SLICES:
        data = memory[first:last]
        assert digest(data) == INPUT_HASHES[name]
        (ASSETS / name).write_bytes(data)


def decompress_map():
    stream = read_verified("original-level2-stream.bin")
    pointers = read_verified("original-level2-block-pointers.bin")
    blocks = read_verified("original-level2-block-data.bin")
    result = bytearray(256 * 20)
    cursor = 0
    while stream[cursor] != 0xff:
        block, low, high, repeat_x, repeat_y = stream[cursor:cursor + 5]
        cursor += 5
        address = int.from_bytes(pointers[block * 2:block * 2 + 2], "little")
        offset = address - 0x9286
        width, height = blocks[offset] + 1, blocks[offset + 1] + 1
        chars = blocks[offset + 2:offset + 2 + width * height]
        assert len(chars) == width * height and repeat_x and repeat_y
        # Destination is an offset from $AC00, not an absolute C64 address.
        destination = low + high * 256
        for ry in range(repeat_y):
            for y in range(height):
                for rx in range(repeat_x):
                    first = destination + (ry * height + y) * 256 + rx * width
                    assert 0 <= first and first + width <= len(result)
                    result[first:first + width] = chars[y * width:(y + 1) * width]
    assert cursor == len(stream) - 1
    assert digest(result) == MAP_SHA256
    return result, cursor // 5


def accent_table(semantic, rows, region):
    table = bytearray()
    conflicts = verified = edge_occurrences = 0
    edge_coordinates = set()
    black_rows = sum(1 << row for row in range(8) if -1 in rows[row * 8:row * 8 + 8])
    for phase in range(4):
        for column in range(128):
            flags = 0
            for row in range(8):
                samples = [(source_y, (column * 4 + phase + x) % 512)
                           for source_y in rows[row * 8:row * 8 + 8] if source_y >= 0
                           for x in range(4)]
                colors = Counter(semantic[y][x] for y, x in samples)
                yellow = colors[7] > 0 and colors[7] >= colors[5]
                flags |= int(yellow) << row
                conflicts += int(bool(colors[5] and colors[7]))
                actual = 7 if yellow else 5
                if not (colors[5] and colors[7]):
                    for y, x in samples:
                        if semantic[y][x] in (5, 7):
                            assert semantic[y][x] == actual
                            verified += 1
                if black_rows & (1 << row):
                    for y, x in samples:
                        if semantic[y][x] in (5, 7):
                            edge_occurrences += 1
                            edge_coordinates.add((y, x))
            table.append(flags)
    assert len(table) == 512
    return table, {"region": region, "columns": list(PERSPECTIVE_COLUMNS[region:region + 2]),
                   "file": PERSPECTIVE_FILES[region], "black_character_rows_mask": black_rows,
                   "conflict_cells": conflicts, "accent_pixels_verified_without_conflict": verified,
                   "edge_cells_source_accent_pixels": edge_occurrences,
                   "edge_cells_unique_source_accent_pixels": len(edge_coordinates)}


def assembly(tile_count):
    lines = ["// Generated by tools/prepare-level2.py from the original C64 Stage 2.",
             "// Pixel codes: 0 = brown ($9), 1 = pink ($a), 2 = red ($2), 3 = cell accent ($5/$7).",
             ".const TERRAIN2_BACKGROUND = 9", ".const TERRAIN2_SCREEN_COLORS = $a2",
             ".const TERRAIN2_EMPTY_PIXEL_CODE = 0", ".const TERRAIN2_MAP_WIDTH = 128",
             ".const TERRAIN2_MAP_HEIGHT = 8", f".const TERRAIN2_TILE_COUNT = {tile_count}",
             '.var level2TilesFile = LoadBinary("assets/level2-tiles.bin")',
             '.var level2MapFile = LoadBinary("assets/level2-tv-map.bin")', "",
             '* = $1000 "Original Stage 2 tiles and map"', "terrain2Tiles:",
             "    .fill level2TilesFile.getSize(), level2TilesFile.get(i)", "terrain2TilesEnd:",
             '.assert "Stage 2 tiles have eight bytes", terrain2TilesEnd - terrain2Tiles, TERRAIN2_TILE_COUNT * 8',
             ".align $100", "terrain2MapStart:"]
    for row in range(8):
        lines.extend([f"terrain2MapRow{row}:", f"    .fill 128, level2MapFile.get(i + {row * 128})"])
    lines.extend(["terrain2MapEnd:",
                  '.assert "Stage 2 map has eight rows", terrain2MapEnd - terrain2MapStart, 1024',
                  '.assert "Stage 2 tiles and map fit below $2000", terrain2MapEnd <= $2000, true', "",
                  '* = $b200 "Original Stage 2 accent maps"'])
    # Regular table comes first in memory; the compile-time list remains region order.
    for region in (3, 0, 1, 2):
        label = PERSPECTIVE_LABELS[region]
        lines.extend([f'.var level2AccentFile{region} = LoadBinary("assets/{PERSPECTIVE_FILES[region]}")',
                      ".align $100", f"{label}:",
                      f"    .fill level2AccentFile{region}.getSize(), level2AccentFile{region}.get(i)",
                      f'.assert "Stage 2 accent region {region} has four phases", * - {label}, 512',
                      f'.assert "Stage 2 accent region {region} is page aligned", <{label}, 0', ""])
    lines.extend(["terrain2DataEnd:", '.assert "Stage 2 accent maps end at $ba00", terrain2DataEnd, $ba00',
                  ".var TERRAIN2_PERSPECTIVE_ACCENT_MAPS = List()"])
    lines.extend(f".eval TERRAIN2_PERSPECTIVE_ACCENT_MAPS.add({label})" for label in PERSPECTIVE_LABELS)
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, help="Re-extract original slices from verified disk file 1")
    args = parser.parse_args()
    if args.program:
        extract_sources(args.program)
    original_map, record_count = decompress_map()
    charset = read_verified("original-charset.bin")
    attributes = read_verified("original-char-colors.bin")
    palette = [tuple(int(v, 16) for v in line.split()[:3])
               for line in read_verified("peptoette-a.vpl").decode().splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    quantize = [min(TV_COLORS, key=lambda target: sum((palette[source][c] - palette[target][c]) ** 2
                                                   for c in range(3))) for source in range(16)]
    quantize[SOURCE_BACKGROUND] = 9
    pixels, semantic, source_counts = [], [], Counter()
    for y in range(64):
        source_y = (2 * y + 1) * 160 // 128
        row, colors = [], []
        for x in range(512):
            source_x = x * 4 + 2
            char = original_map[(source_y // 8) * 256 + source_x // 8]
            bits, attribute = charset[char * 8 + source_y % 8], attributes[char]
            if attribute & 8:
                code = (bits >> (6 - 2 * ((source_x % 8) // 2))) & 3
                color = (SOURCE_BACKGROUND, *SOURCE_MULTICOLORS, attribute & 7)[code]
            else:
                color = attribute & 7 if bits & (0x80 >> (source_x % 8)) else SOURCE_BACKGROUND
            source_counts[color] += 1
            colors.append(quantize[color])
            row.append(BASE_CODES.get(quantize[color], 3))
        pixels.append(row)
        semantic.append(colors)
    patterns, ids, tile_map = [], {}, bytearray()
    for y in range(8):
        for x in range(128):
            pattern = bytes(sum(pixels[y * 8 + dy][x * 4 + dx] << (6 - 2 * dx) for dx in range(4))
                            for dy in range(8))
            if pattern not in ids:
                ids[pattern] = len(patterns)
                patterns.append(pattern)
            tile_map.append(ids[pattern])
    assert len(patterns) <= 256
    tile_bytes = b"".join(patterns)
    for y in range(64):
        for x in range(512):
            tile = tile_map[(y // 8) * 128 + x // 4]
            assert (tile_bytes[tile * 8 + y % 8] >> (6 - 2 * (x % 4))) & 3 == pixels[y][x]
    outputs = {"level2-tiles.bin": tile_bytes, "level2-tv-map.bin": tile_map}
    stats = []
    for region, rows in enumerate(PERSPECTIVE_SOURCE_ROWS):
        outputs[PERSPECTIVE_FILES[region]], proof = accent_table(semantic, rows, region)
        stats.append(proof)
    (ASSETS / "original-level2-map.bin").write_bytes(original_map)
    for name, data in outputs.items():
        (ASSETS / name).write_bytes(data)
    (PART / "terrain-level2.asm").write_text(assembly(len(patterns)))
    receipt = {
        "stage": 2, "original_map_dimensions_chars": [256, 20],
        "original_dimensions_physical_pixels": [2048, 160],
        "output_map_dimensions_tiles": [128, 8], "output_dimensions_physical_pixels": [1024, 64],
        "vertical_crop_pixels": 0, "sampling": "nearest center; horizontal physical scale 1/2, vertical scale 2/5",
        "source_background": 0, "source_multicolors": [10, 2], "source_music_cue": 1,
        "output_colors": list(TV_COLORS), "output_shared_colors": [9, 10, 2],
        "output_global_background": 9, "output_screen_byte": 0xa2, "output_empty_pixel_code": 0,
        "source_color_to_output_color": quantize,
        "source_color_to_output_code": [BASE_CODES.get(color, 3) for color in quantize],
        "sampled_source_color_pixel_counts": dict(sorted(source_counts.items())),
        "semantic_output_color_pixel_counts": dict(sorted(Counter(c for row in semantic for c in row).items())),
        "unique_tiles": len(patterns), "tile_bytes": len(tile_bytes), "map_bytes": len(tile_map),
        "accent_layout": "offset=phase*128+world_column; bit=row; 0=green5, 1=yellow7",
        "accent_selection": "yellow when yellow_count>0 and yellow_count>=green_count; otherwise green",
        "perspective_columns": list(PERSPECTIVE_COLUMNS),
        "perspective_source_rows": [list(rows) for rows in PERSPECTIVE_SOURCE_ROWS],
        "perspective_region_proofs": stats,
        "perspective_edge_approximation": "Code 3 accents in the 12 black-mask character cells display black; original pixel codes are retained.",
        "compressed_map_records": record_count, "original_map_sha256": digest(original_map),
        "source_sha256": INPUT_HASHES, "output_sha256": {name: digest(data) for name, data in outputs.items()},
        "reconstructed_pixel_codes_verified": 32768,
    }
    (ASSETS / "level2-import.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"Original Stage 2: {len(patterns)} tiles ({len(tile_bytes)} bytes), 128x8 map, four 512-byte accent tables.")
    print("Output SHA-256:", json.dumps(receipt["output_sha256"], sort_keys=True))


if __name__ == "__main__":
    main()
