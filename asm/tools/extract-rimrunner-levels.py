#!/usr/bin/env python3
"""Extract Rimrunner's native repeating layer maps from its initial RAM capture.

Native tile IDs, row-major character definitions, font resources, and the level
selector retain their original byte order. PNGs show logical map layers, not a
cycle-exact raster composition. Original game assets are written only to the
chosen build output directory.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from PIL import Image, ImageDraw


TABLES = {"near_maps": 0x9de7, "middle_maps": 0x9ded, "widths": 0x9df3,
          "near_definitions": 0x9df9, "middle_definitions": 0x9dff,
          "background_maps": 0x9e05, "level_order": 0x9e0b}
PALETTES = {"middle_background": 0x9e14, "middle_mc1": 0x9e17, "middle_mc2": 0x9e1a,
            "road_background": 0x9e1d, "near_mc1": 0x9e26, "near_mc2": 0x9e29,
            "level_background": 0x9e2c, "far_mc1": 0x9e35, "far_mc2": 0x9e38,
            "far_top_color": 0x9e3b, "far_bottom_color": 0x9e3e,
            "middle_color": 0x9e41, "road_color": 0x9e44,
            "near_color": 0x9e47, "far_top_rows": 0x9e4a}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def native_slice(ram, address, count):
    if not 0 <= address <= address + count <= 65536:
        raise ValueError(f"Source span falls outside captured RAM: ${address:04x}, {count} bytes")
    return ram[address:address + count]


def word(ram, address):
    return int.from_bytes(native_slice(ram, address, 2), "little")


def resource_slots(ram, tags_address, pointers_address):
    tags = list(native_slice(ram, tags_address, 3))
    pointers = [word(ram, pointers_address + index * 2) for index in range(3)]
    if sorted(tags) != [0, 1, 2]:
        raise ValueError(f"Expected three resource tags at ${tags_address:04x}: {tags}")
    # The original loader indexes tags by theme; each value selects a cache slot.
    mapping = {theme: pointers[slot] for theme, slot in enumerate(tags)}
    return mapping, {"tags_address": f"${tags_address:04x}", "tags": tags,
                     "pointers_address": f"${pointers_address:04x}",
                     "slot_addresses": [f"${address:04x}" for address in pointers]}


def expand_tiles(ids, definitions, rows):
    stride = rows * 4
    return bytes(character for row in range(rows) for tile_id in ids
                 for character in definitions[tile_id * stride + row * 4:tile_id * stride + row * 4 + 4])


def layer_image(codes, columns, rows, charset, cell_colors, backgrounds, mc1, mc2, palette):
    pixels = []
    for y in range(rows * 8):
        row = y // 8
        local = cell_colors[row]
        background = backgrounds[row]
        for column in range(columns):
            character = codes[row * columns + column]
            bits = charset[character * 8 + y % 8]
            if local & 8:
                colors = [background, mc1, mc2, local & 7]
                for shift in (6, 4, 2, 0):
                    pixels.extend([colors[(bits >> shift) & 3]] * 2)
            else:
                pixels.extend(local if bits & (0x80 >> x) else background for x in range(8))
    image = Image.new("P", (columns * 8, rows * 8))
    image.putpalette([value for color in palette for value in color] + [0] * (768 - 48))
    image.putdata(pixels)
    return image


def tile_atlas(definitions, rows, charset, local, background, mc1, mc2, palette):
    count = len(definitions) // (rows * 4)
    cell_height = rows * 8 + 14
    image = Image.new("RGB", (8 * 36, ((count + 7) // 8) * cell_height), (24, 24, 24))
    draw = ImageDraw.Draw(image)
    for tile_id in range(count):
        data = definitions[tile_id * rows * 4:(tile_id + 1) * rows * 4]
        tile = layer_image(data, 4, rows, charset, [local] * rows, [background] * rows, mc1, mc2, palette)
        x, y = (tile_id % 8) * 36, (tile_id // 8) * cell_height
        draw.text((x + 2, y), str(tile_id), fill=(255, 255, 255))
        image.paste(tile.convert("RGB"), (x + 2, y + 12))
    return image


def extract_levels(source, output):
    source, output = source.resolve(), output.resolve()
    ram = source.read_bytes()
    if len(ram) != 65536:
        raise ValueError("Expected a complete 65,536-byte physical RAM capture.")
    if output == source.parent:
        raise ValueError("Keep generated output separate from the immutable source capture.")
    palette_path = Path(__file__).resolve().parents[2] / "palettes/colodore.vpl"
    spec = importlib.util.spec_from_file_location("rimrunner_assets", Path(__file__).with_name("rimrunner-assets.py"))
    decoder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(decoder)
    palette = decoder.load_palette(palette_path)
    far_slots, far_slot_record = resource_slots(ram, 0x81d9, 0x81e3)
    near_slots, near_slot_record = resource_slots(ram, 0x81d5, 0x81dd)
    suffix = native_slice(ram, 0x5530, 0x2d0)
    level_order = native_slice(ram, TABLES["level_order"], 9)
    if any(set_id > 2 for set_id in level_order):
        raise ValueError("Level selector points outside the three observed resource sets.")
    current_level = ram[0x02c0]
    if not 1 <= current_level <= 9:
        raise ValueError(f"Initial captured level is outside the verified 1..9 cycle: {current_level}")
    current_set = level_order[current_level - 1]
    generated, sets, checks = {}, [], []
    output.mkdir(parents=True, exist_ok=True)

    def write(name, data):
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        generated[name] = {"bytes": len(data), "sha256": digest(data)}
        return name

    def save(name, image):
        target = output / name
        image.save(target)
        generated[name] = {"bytes": target.stat().st_size, "sha256": digest(target.read_bytes())}

    write("level-order.bin", level_order)
    write("native-tables.bin", native_slice(ram, 0x9de7, 0x66))
    write("near-charset-shared-suffix.bin", suffix)
    for set_id in range(3):
        prefix = f"set-{set_id}/"
        far_charset = native_slice(ram, far_slots[set_id], 2048)
        near_prefix = native_slice(ram, near_slots[set_id], 0x530)
        near_charset = near_prefix + suffix
        if near_charset[:8] != bytes(8):
            raise ValueError(f"Road character zero is not blank in set {set_id}.")
        font_files = {"far": write(prefix + "far-charset.bin", far_charset),
                      "near_prefix": write(prefix + "near-charset-prefix.bin", near_prefix),
                      "near": write(prefix + "near-charset.bin", near_charset)}
        background_address = word(ram, TABLES["background_maps"] + set_id * 2)
        background = native_slice(ram, background_address, 960)
        background_file = write(prefix + "background-chars.bin", background)
        palettes = {name: ram[address + (0 if name == "level_background" else set_id)]
                    for name, address in PALETTES.items() if name != "level_background"}
        first_level = next(level for level, theme in enumerate(level_order, 1) if theme == set_id)
        preview_background = ram[PALETTES["level_background"] + first_level - 1]
        upper_rows = palettes["far_top_rows"]
        if not 0 <= upper_rows <= 12:
            raise ValueError("Far Color RAM height exceeds its 12-row layer.")
        far_colors = [palettes["far_top_color"]] * upper_rows + [palettes["far_bottom_color"]] * (12 - upper_rows)
        save(prefix + "preview-background.png", layer_image(background, 80, 12, far_charset,
             far_colors, [preview_background] * 12, palettes["far_mc1"], palettes["far_mc2"], palette))
        record = {"set": set_id, "first_level": first_level, "palettes": palettes,
                  "preview_far_background_index": preview_background,
                  "fonts": {"files": font_files, "far_source_address": f"${far_slots[set_id]:04x}",
                            "far_bytes": 2048, "near_prefix_source_address": f"${near_slots[set_id]:04x}",
                            "near_prefix_bytes": 1328, "near_shared_suffix_address": "$5530", "near_shared_suffix_bytes": 720},
                  "background": {"file": background_file, "source_address": f"${background_address:04x}",
                                 "rows": 12, "columns": 80, "bytes": 960, "screen_first_row": 5},
                  "road": {"screen_first_row": 19, "rows": 2, "character": 0,
                           "background": palettes["road_background"], "color_ram": palettes["road_color"]}}
        expanded_maps = {}
        for kind, rows, width_offset, screen_address in [("middle", 2, 1, 0x42a8), ("near", 4, 0, 0x4348)]:
            maximum_column = ram[TABLES["widths"] + set_id * 2 + width_offset]
            columns = maximum_column + 1
            if columns % 4:
                raise ValueError(f"{kind} width is not divisible by its four-character tile width.")
            map_address = word(ram, TABLES[kind + "_maps"] + set_id * 2)
            definition_address = word(ram, TABLES[kind + "_definitions"] + set_id * 2)
            ids = native_slice(ram, map_address, columns // 4)
            definition_count = max(ids) + 1
            definitions = native_slice(ram, definition_address, definition_count * rows * 4)
            if max(definitions) >= 166:
                raise ValueError(f"{kind} definitions exceed the captured theme-specific 166-glyph prefix.")
            expanded = expand_tiles(ids, definitions, rows)
            expanded_maps[kind] = (expanded, columns, rows, screen_address)
            files = {"ids": write(prefix + kind + "-ids.bin", ids),
                     "definitions": write(prefix + kind + "-defs.bin", definitions),
                     "expanded_preview": write(prefix + kind + "-expanded-chars.bin", expanded)}
            if kind == "middle":
                bg, mc1, mc2, local = (palettes[key] for key in ("middle_background", "middle_mc1", "middle_mc2", "middle_color"))
            else:
                bg, mc1, mc2, local = (palettes[key] for key in ("road_background", "near_mc1", "near_mc2", "near_color"))
            save(prefix + "preview-" + kind + ".png", layer_image(expanded, columns, rows, near_charset,
                 [local] * rows, [bg] * rows, mc1, mc2, palette))
            save(prefix + "atlas-" + kind + ".png", tile_atlas(definitions, rows, near_charset, local, bg, mc1, mc2, palette))
            record[kind] = {"files": files, "map_source_address": f"${map_address:04x}",
                            "definitions_source_address": f"${definition_address:04x}",
                            "tile_count": len(ids), "used_tile_ids": sorted(set(ids)),
                            "definition_count": definition_count, "bytes_per_definition": rows * 4,
                            "tile_columns": 4, "rows": rows, "columns": columns,
                            "native_maximum_column": maximum_column, "id_base": 0, "terminator": None,
                            "screen_first_row": 17 if kind == "middle" else 21,
                            "definition_layout": "row-major, four character codes per row"}
        if set_id == current_set:
            for kind, (expanded, columns, rows, address) in expanded_maps.items():
                expected = bytes(value for row in range(rows) for value in expanded[row * columns:row * columns + 40])
                actual = native_slice(ram, address, rows * 40)
                mismatches = sum(a != b for a, b in zip(expected, actual))
                checks.append({"set": set_id, "layer": kind, "first_tiles": 10,
                               "screen_address": f"${address:04x}", "compared_bytes": len(expected), "mismatches": mismatches})
            expected_far = bytes(value for row in range(12) for value in background[row * 80:row * 80 + 40])
            checks.append({"set": set_id, "layer": "background", "screen_address": "$40c8", "compared_bytes": 480,
                           "mismatches": sum(a != b for a, b in zip(expected_far, ram[0x40c8:0x42a8]))})
            checks.append({"set": set_id, "layer": "road", "screen_address": "$42f8", "compared_bytes": 80,
                           "mismatches": sum(value != 0 for value in ram[0x42f8:0x4348])})
        sets.append(record)
    if any(check["mismatches"] for check in checks):
        raise ValueError(f"Native maps do not reproduce the initial captured viewport: {checks}")
    snapshot = source.with_name("state.vsf")
    manifest = {"format": "Rimrunner original native layer maps v1",
                "source": {"ram": str(source), "bytes": len(ram), "sha256": digest(ram),
                           "snapshot": str(snapshot) if snapshot.exists() else None,
                           "snapshot_sha256": digest(snapshot.read_bytes()) if snapshot.exists() else None},
                "pointer_tables": {name: f"${address:04x}" for name, address in TABLES.items()},
                "palette_tables": {name: f"${address:04x}" for name, address in PALETTES.items()},
                "resource_slots": {"far": far_slot_record, "near": near_slot_record},
                "sets": sets,
                "levels": [{"level": level, "set": theme, "set_directory": f"set-{theme}",
                            "background_index": ram[PALETTES["level_background"] + level - 1]}
                           for level, theme in enumerate(level_order, 1)],
                "level_cycle_source": "$b2f4: increment level; compare #$0a; wrap to level1",
                "captured_level": current_level, "captured_set": current_set,
                "initial_viewport_verification": checks,
                "original_pal_raster_events": {"far_shared_colors_clear": 90,
                    "far_font_and_scroll": 91, "far_background": 93,
                    "far_mc_palette": 95, "far_mc2_highlight": 181, "middle_solid_mask": 184,
                    "near_font_and_middle_scroll": 186, "middle_mc_palette": 187,
                    "road_background": 202, "road_scroll_zero": 203, "near_scroll_and_mc_palette": 218},
                "outputs": generated,
                "limitations": [
                    "Three complete resident map sets and nine level-to-set assignments are exported; the nine levels reuse these maps with palette variants.",
                    "Each layer has its own native wrap width. The maps do not describe a single equal-width combined panorama.",
                    "Only the captured initial level's first viewport is byte-verified against live screen RAM; other sets are structurally validated, not played end-to-end.",
                    "PNGs show logical unscrolled layer art using the first assigned level's palette. They omit raster masks, fine scroll, sprites, and exact event bus cycles.",
                    "Font and map bytes come from saved runtime RAM/snapshot; this tool does not independently replay the compressed PRG's decruncher.",
                    "Original graphics retain their existing rights; extraction adds no reuse or redistribution license.",
                ]}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output), "sets": len(sets), "level_assignments": len(level_order),
                      "current_set": current_set, "viewport_checks": checks,
                      "native_periods_characters": [{"set": entry["set"], "background": 80,
                          "middle": entry["middle"]["columns"], "near": entry["near"]["columns"]} for entry in sets]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ram", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    extract_levels(arguments.ram, arguments.output)
