#!/usr/bin/env python3
"""Prepare the native giana4 scene and tile-scoped screen-light color tables."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


PART = Path(__file__).resolve().parents[1]
REPOSITORY = PART.parent
SOURCE_KOALA = REPOSITORY / "images" / "giana4.koa"
SOURCE_PROJECT = REPOSITORY / "images" / "giana4.json"
ASSETS = PART / "assets"
COLUMNS = 40
ROWS = 25
SCREEN_OFFSET = 8002
COLOR_OFFSET = 9002
BACKGROUND_OFFSET = 10002
PLUS_ONE = (0, 1, 2, 7, 10, 15, 6, 1, 10, 9, 15, 11, 15, 1, 15, 7)
PLUS_TWO = tuple(PLUS_ONE[color] for color in PLUS_ONE)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def marker(project: dict, name: str) -> dict:
    matches = [layer for layer in project["layers"] if layer.get("name") == name]
    if len(matches) != 1 or matches[0].get("type") != "tile-markers":
        raise ValueError(f"Expected exactly one tile marker layer named {name!r}.")
    tiles = matches[0]["markers"]["tiles"]
    if len(tiles) != COLUMNS * ROWS or any(type(value) is not int or value not in (0, 1) for value in tiles):
        raise ValueError(f"{name} must contain 1,000 binary tile values.")
    cells = [cell for cell, enabled in enumerate(tiles) if enabled]
    if not cells:
        raise ValueError(f"{name} must mark at least one tile.")
    left = min(cell % COLUMNS for cell in cells)
    top = min(cell // COLUMNS for cell in cells)
    right = max(cell % COLUMNS for cell in cells)
    bottom = max(cell // COLUMNS for cell in cells)
    return {
        "name": name,
        "count": len(cells),
        "bounds": {"left": left, "top": top, "right": right, "bottom": bottom,
                   "width": right - left + 1, "height": bottom - top + 1},
        "cells": cells,
        "mask": tiles,
    }


def decoded_pixels(koala: bytes):
    """Yield native multicolor pixel positions, cells, slots, and palette indices."""
    for y in range(200):
        for x in range(160):
            cell = y // 8 * COLUMNS + x // 4
            slot = koala[2 + cell * 8 + y % 8] >> (6 - x % 4 * 2) & 3
            screen = koala[SCREEN_OFFSET + cell]
            colors = (koala[BACKGROUND_OFFSET] & 15, screen >> 4, screen & 15,
                      koala[COLOR_OFFSET + cell] & 15)
            yield x, y, cell, slot, colors[slot]


def illumination_table(koala: bytes, cells: list[int]) -> bytes:
    levels = (tuple(range(16)), PLUS_ONE, PLUS_TWO)
    screen = bytearray()
    color = bytearray()
    for cell in cells:
        original_screen = koala[SCREEN_OFFSET + cell]
        original_color = koala[COLOR_OFFSET + cell]
        for mapping in levels:
            screen.append(mapping[original_screen >> 4] << 4 | mapping[original_screen & 15])
            color.append(original_color & 0xF0 | mapping[original_color & 15])
    return bytes(screen + color)


def region_counts(koala: bytes, cells: list[int]) -> dict:
    selected = set(cells)
    colors = Counter()
    slots = Counter()
    slot_colors = [Counter() for _ in range(4)]
    for _, _, cell, slot, color in decoded_pixels(koala):
        if cell in selected:
            colors[color] += 1
            slots[slot] += 1
            slot_colors[slot][color] += 1
    return {
        "logical_pixels_by_color": dict(sorted(colors.items())),
        "logical_pixels_by_slot": dict(sorted(slots.items())),
        "slot_colors": {str(slot): dict(sorted(count.items())) for slot, count in enumerate(slot_colors)},
    }


def write_preview(koala: bytes, cells: list[int]) -> Path:
    try:
        from PIL import Image
    except ImportError as error:
        raise ValueError("--preview requires Pillow; normal preparation does not.") from error

    palettes = (REPOSITORY / "palettes.js").read_text()
    match = re.search(r"id: 'peptoette-a'.*?hex:\s*\[([^\]]+)\]", palettes, re.DOTALL)
    if not match:
        raise ValueError("Cannot find peptoette-a in palettes.js.")
    palette = [tuple(bytes.fromhex(value)) for value in re.findall(r"'([0-9A-Fa-f]{6})'", match[1])]
    if len(palette) != 16:
        raise ValueError("peptoette-a must contain 16 colors.")

    selected = set(cells)
    output = Image.new("RGB", (320 * 3, 200))
    for level, mapping in enumerate((tuple(range(16)), PLUS_ONE, PLUS_TWO)):
        pixels = []
        for _, _, cell, slot, color in decoded_pixels(koala):
            mapped = mapping[color] if cell in selected and slot != 0 else color
            pixels.extend((palette[mapped], palette[mapped]))
        frame = Image.new("RGB", (320, 200))
        frame.putdata(pixels)
        output.paste(frame, (level * 320, 0))
    destination = PART / "build" / "giana4-lighting-analysis.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    output.save(destination)
    return destination


def prepare(preview: bool = False) -> None:
    koala = SOURCE_KOALA.read_bytes()
    project_bytes = SOURCE_PROJECT.read_bytes()
    project = json.loads(project_bytes)
    if len(koala) != 10003:
        raise ValueError("giana4.koa must be a standard 10,003-byte Koala file.")
    if project.get("image", {}).get("paletteId") != "peptoette-a":
        raise ValueError("The illumination maps target the project's peptoette-a palette.")
    if koala[BACKGROUND_OFFSET] != 0 or project["image"]["backgroundColorIndex"] != 0:
        raise ValueError(
            "Per-tile illumination requires global background 0 (Black). "
            f"The Koala background is {koala[BACKGROUND_OFFSET]} and the project background is "
            f"{project['image']['backgroundColorIndex']}; export the updated giana4 files first."
        )

    game_area = marker(project, "GameArea")
    screen_light = marker(project, "ScreenLight")
    expected_game_cells = [row * COLUMNS + column for row in range(3, 11) for column in range(23, 33)]
    if game_area["cells"] != expected_game_cells:
        raise ValueError("GameArea must be the complete 10 x 8 rectangle at column 23, row 3.")
    if screen_light["count"] != 173:
        raise ValueError("ScreenLight must preserve the 173 marked source tiles.")
    if set(game_area["cells"]) & set(screen_light["cells"]):
        raise ValueError("ScreenLight and GameArea must not overlap.")

    light_cells = screen_light["cells"]
    lighting = illumination_table(koala, light_cells)
    section_size = len(light_cells) * 3
    if len(lighting) != section_size * 2:
        raise ValueError("Unexpected illumination table length.")
    for index, cell in enumerate(light_cells):
        if lighting[index * 3] != koala[SCREEN_OFFSET + cell] or \
                lighting[section_size + index * 3] != koala[COLOR_OFFSET + cell]:
            raise ValueError("The original illumination level must preserve both color bytes.")

    assembly = [
        "// Generated by tools/prepare-scene.py from the original giana4 marker layers.",
        ".const TV_COLUMN = 23",
        ".const TV_ROW = 3",
        ".const TV_WIDTH = 10",
        ".const TV_HEIGHT = 8",
        f".const LIGHT_TILE_COUNT = {len(light_cells)}",
        ".var LIGHT_CELLS = List()",
        *(f".eval LIGHT_CELLS.add({cell})" for cell in light_cells),
        "",
    ]
    counts = region_counts(koala, light_cells)
    metadata = {
        "format": "c64-giana-native-scene-v1",
        "sources": {
            "koala": {"path": str(SOURCE_KOALA.relative_to(REPOSITORY)), "sha256": sha256(koala),
                      "bytes": len(koala), "load_address": int.from_bytes(koala[:2], "little")},
            "project": {"path": str(SOURCE_PROJECT.relative_to(REPOSITORY)), "sha256": sha256(project_bytes)},
        },
        "scene": {"width": 320, "height": 200, "palette_id": "peptoette-a", "background_index": 0},
        "game_area": game_area,
        "screen_light": screen_light,
        "lighting": {
            "levels": ["original", "+1", "+2"],
            "plus_one_map": list(PLUS_ONE),
            "plus_two_map": list(PLUS_TWO),
            "fixed_color_indices": [0, 1, 2, 6, 9, 11],
            "background_policy": "Keep global background index 0 fixed at every light level.",
            "global_background_constraint": (
                "Multicolor bitmap slot 00 uses one global background color. It cannot brighten per tile. "
                "The source uses black 0 for this slot, which remains black. "
                "Orange 8 in the three local color slots can brighten normally."
            ),
            "screen_light_counts": counts,
            "game_area_counts": region_counts(koala, game_area["cells"]),
            "table": {"path": "assets/lighting.bin", "bytes": len(lighting), "sha256": sha256(lighting),
                      "screen_offset": 0, "color_offset": section_size, "levels_per_tile": 3,
                      "layout": "All tile-major original/+1/+2 screen bytes, then all tile-major original/+1/+2 color bytes.",
                      "screen_index": "3 * light_cell_index + level",
                      "color_index": f"{section_size} + 3 * light_cell_index + level"},
            "behavior": (
                "Apply only to ScreenLight cells. Preserve original bitmap bytes, global background, "
                "black 0, white 1, red 2, dark blue 6, brown 9, dark gray 11, "
                "and every color byte outside the mask. "
                "Color RAM high nibbles are retained in the generated bytes. Level 0 restores exact source bytes. "
                "GameArea is disjoint and receives no lighting changes."
            ),
        },
        "preservation": {
            "source_files_modified": False,
            "koala_asset_is_exact_copy": True,
            "bitmap_modified": False,
            "marker_masks_modified": False,
            "game_area_modified_by_preparation": False,
            "palette_conversion_performed": False,
        },
    }
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "giana4.koa").write_bytes(koala)
    (ASSETS / "lighting.bin").write_bytes(lighting)
    (ASSETS / "scene.asm").write_text("\n".join(assembly))
    (ASSETS / "scene.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Prepared giana4.koa, scene.asm, scene.json, lighting.bin ({len(light_cells)} light tiles; {len(lighting)} bytes).")
    if preview:
        print(f"Preview: {write_preview(koala, light_cells).relative_to(REPOSITORY)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="also render original/+1/+2 views with Pillow")
    arguments = parser.parse_args()
    try:
        prepare(arguments.preview)
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, f"prepare-scene: {error}\n")
