#!/usr/bin/env python3
"""Join the original MCI sky and road art without changing their pixel encoding.

The first 12 character rows come from the background image. The remaining 13
rows come from the top of the road image. Both phases, their separate screen
attributes, and shared Color RAM are copied directly; no fitting is performed.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from PIL import Image


COLUMNS = 40
ROWS = 25
SKY_ROWS = 12
ROAD_ROWS = ROWS - SKY_ROWS
WIDTH = COLUMNS * 8
HEIGHT = ROWS * 8
SPANS = {"screen-a.bin": (2, COLUMNS * ROWS), "screen-b.bin": (17410, COLUMNS * ROWS),
         "bitmap-a.bin": (1026, COLUMNS * ROWS * 8), "bitmap-b.bin": (9218, COLUMNS * ROWS * 8),
         "color.bin": (18434, COLUMNS * ROWS), "background.bin": (1002, 1)}
BANDS = [("sky", 0, 12), ("fence", 12, 4), ("road", 16, 4), ("front", 20, 5)]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(background_source, road_source, output):
    background_source, road_source, output = background_source.resolve(), road_source.resolve(), output.resolve()
    root = Path(__file__).resolve().parents[3]
    background_data = background_source.read_bytes()
    road_data = road_source.read_bytes()
    decoder = load_module("mci_sine_source", Path(__file__).with_name("mci-source.py"))
    background_color, _ = decoder.decode_mci(background_data)
    road_color, _ = decoder.decode_mci(road_data)
    if background_color != road_color:
        raise ValueError("MCI sources need the same global background color for a byte-preserving composite.")

    composite = bytearray(background_data)
    copy_regions = []
    for name, (start, _) in SPANS.items():
        if name == "background.bin":
            continue
        bytes_per_cell = 8 if name.startswith("bitmap") else 1
        sky_bytes = SKY_ROWS * COLUMNS * bytes_per_cell
        road_bytes = ROAD_ROWS * COLUMNS * bytes_per_cell
        composite[start + sky_bytes:start + sky_bytes + road_bytes] = road_data[start:start + road_bytes]
        copy_regions.append({"payload": name, "source": "road", "source_offset": start,
                             "composite_offset": start + sky_bytes, "bytes": road_bytes})
    composite = bytes(composite)
    _, phases = decoder.decode_mci(composite)
    assets = load_module("rimrunner_assets", Path(__file__).with_name("rimrunner-assets.py"))
    palette_path = root / "palettes/colodore.vpl"
    palette = assets.load_palette(palette_path)
    previews = []
    for phase in range(2):
        pixels = [int(color) for row in phases[phase] for color in row for _ in range(2)]
        if phase:
            pixels = [color for y in range(HEIGHT) for color in
                      [background_color, *pixels[y * WIDTH:y * WIDTH + WIDTH - 1]]]
        previews.append(assets.indexed_image(WIDTH, HEIGHT, pixels, palette))
    images = {"phase-a.png": previews[0], "phase-b.png": previews[1],
              "phase-blend.png": Image.blend(previews[0].convert("RGB"), previews[1].convert("RGB"), 0.5)}
    payloads = {name: composite[start:start + count] for name, (start, count) in SPANS.items()}
    payloads["composite.mci"] = composite
    protected = {background_source, road_source}
    if any((output / name).resolve() in protected for name in [*payloads, *images, "manifest.json"]):
        raise ValueError("Composite outputs must not replace either source MCI file.")
    output.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (output / name).write_bytes(payload)
    for name, image in images.items():
        image.save(output / name)
    if background_source.read_bytes() != background_data or road_source.read_bytes() != road_data:
        raise RuntimeError("A source MCI file changed during preparation.")
    manifest = {
        "format": "Rimrunner byte-preserving True Paint MCI sky-road composite v1",
        "sources": {"background": {"path": str(background_source), "bytes": len(background_data),
                                    "sha256": digest(background_data)},
                    "road": {"path": str(road_source), "bytes": len(road_data), "sha256": digest(road_data)}},
        "display": {"width_hires_pixels": WIDTH, "height_pixels": HEIGHT,
                    "character_columns": COLUMNS, "character_rows": ROWS,
                    "phase_count": 2, "phase_b_offset_hires_pixels": 1,
                    "background_index": background_color, "resampled": False},
        "composition": [{"source": "background", "source_crop": [0, 0, WIDTH, SKY_ROWS * 8],
                         "destination": [0, 0, WIDTH, SKY_ROWS * 8], "cells": SKY_ROWS * COLUMNS},
                        {"source": "road", "source_crop": [0, 0, WIDTH, ROAD_ROWS * 8],
                         "destination": [0, SKY_ROWS * 8, WIDTH, ROAD_ROWS * 8], "cells": ROAD_ROWS * COLUMNS}],
        "bands": [{"name": name, "first_character_row": first, "character_rows": rows,
                   "first_y": first * 8, "height_pixels": rows * 8,
                   "first_cell": first * COLUMNS, "cells": rows * COLUMNS,
                   "bitmap_offset": first * COLUMNS * 8, "bitmap_bytes": rows * COLUMNS * 8}
                  for name, first, rows in BANDS],
        "road_copy_regions": copy_regions,
        "outputs": {name: {"bytes": len(payload), "sha256": digest(payload)} for name, payload in payloads.items()},
        "previews": {name: {"bytes": (output / name).stat().st_size,
                            "sha256": digest((output / name).read_bytes())} for name in images},
        "palette": {"path": str(palette_path), "sha256": digest(palette_path.read_bytes())},
        "notes": [
            "Both complete MCI phases, separate screen attributes, and shared Color RAM are preserved by direct byte copies.",
            "Unused MCI header/padding bytes come from the background source; both source files remain unchanged.",
            "The composition uses background rows0..95 and road rows0..103, without scaling or quantization.",
            "Phase B preview has its global one-hires-pixel right shift; the left edge uses the shared background.",
            "phase-blend.png is a 50/50 sRGB phase average, not a simulation of native temporal flicker.",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output), "composite_bytes": len(composite),
                      "bands": [{"name": band["name"], "first_y": band["first_y"],
                                 "height_pixels": band["height_pixels"]} for band in manifest["bands"]],
                      "native_bytes": {name: len(payload) for name, payload in payloads.items()}}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--background", type=Path, required=True)
    parser.add_argument("--road", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    prepare(arguments.background, arguments.road, arguments.output)
