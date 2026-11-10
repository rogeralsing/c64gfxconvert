#!/usr/bin/env python3
"""Crop complete top character rows from an unchanged True Paint MCI source.

Exports native screen, bitmap, and shared Color RAM bytes for the configured
character rows. PNGs are decoded references; the blended PNG is a 50/50 phase
average, not a simulation of native PAL temporal flicker.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from PIL import Image


SKY_ROWS = 12
SKY_COLUMNS = 40
SKY_HEIGHT = SKY_ROWS * 8
SKY_WIDTH = SKY_COLUMNS * 8
SKY_CELLS = SKY_ROWS * SKY_COLUMNS
SPANS = {"screen-a.bin": (2, SKY_CELLS), "screen-b.bin": (17410, SKY_CELLS),
         "bitmap-a.bin": (1026, SKY_CELLS * 8), "bitmap-b.bin": (9218, SKY_CELLS * 8),
         "color.bin": (18434, SKY_CELLS), "background.bin": (1002, 1)}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(source, output):
    source, output = source.resolve(), output.resolve()
    root = Path(__file__).resolve().parents[2]
    data = source.read_bytes()
    decoder = load_module("mci_sine_source", root / "mci-viewer/sine-data.py")
    background, phases = decoder.decode_mci(data)
    assets = load_module("rimrunner_assets", Path(__file__).with_name("rimrunner-assets.py"))
    palette_path = root / "palettes/colodore.vpl"
    palette = assets.load_palette(palette_path)
    previews = []
    for phase in range(2):
        pixels = [int(color) for row in phases[phase, :SKY_HEIGHT] for color in row for _ in range(2)]
        if phase:
            pixels = [color for y in range(SKY_HEIGHT) for color in
                      [background, *pixels[y * SKY_WIDTH:y * SKY_WIDTH + SKY_WIDTH - 1]]]
        previews.append(assets.indexed_image(SKY_WIDTH, SKY_HEIGHT, pixels, palette))
    images = {"phase-a.png": previews[0], "phase-b.png": previews[1],
              "phase-blend.png": Image.blend(previews[0].convert("RGB"), previews[1].convert("RGB"), 0.5)}
    names = [*SPANS, *images, "manifest.json"]
    if any((output / name).resolve() == source for name in names):
        raise ValueError("Prepared outputs must not overwrite the source MCI file.")
    payloads = {name: data[start:start + count] for name, (start, count) in SPANS.items()}
    output.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (output / name).write_bytes(payload)
    for name, image in images.items():
        image.save(output / name)
    if digest(source.read_bytes()) != digest(data):
        raise RuntimeError("Source MCI changed during preparation.")
    manifest = {
        "format": f"Rimrunner True Paint MCI top-{SKY_HEIGHT} sky crop v1",
        "source": str(source), "source_bytes": len(data), "source_sha256": digest(data),
        "source_load_address": "$9c00",
        "crop": {"x": 0, "y": 0, "width_hires_pixels": SKY_WIDTH, "height_pixels": SKY_HEIGHT,
                 "source_width_hires_pixels": SKY_WIDTH, "source_height_pixels": 200,
                 "character_columns": SKY_COLUMNS, "character_rows": SKY_ROWS, "resampled": False},
        "phase_b_offset_hires_pixels": 1, "background_index": background,
        "native_outputs": {name: {"source_offset": SPANS[name][0], "bytes": len(payload),
                                  "sha256": digest(payload)} for name, payload in payloads.items()},
        "previews": {name: {"bytes": (output / name).stat().st_size,
                            "sha256": digest((output / name).read_bytes())} for name in images},
        "palette": {"source": str(palette_path), "sha256": digest(palette_path.read_bytes())},
        "notes": [
            "Native BIN payloads are exact contiguous source slices, without color fitting, conversion, or resampling.",
            "Phase B PNG includes its native one-hires-pixel right shift; the left edge uses the shared background and the rightmost pixel is clipped.",
            "phase-blend.png averages the two displayed RGB phases at 50/50 in sRGB; it does not reproduce native temporal flicker.",
            "The source MCI file is read only and remains unchanged.",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output), "source_sha256": manifest["source_sha256"],
                      "crop_hires_pixels": [0, 0, SKY_WIDTH, SKY_HEIGHT],
                      "native_bytes": {name: len(payload) for name, payload in payloads.items()}}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    prepare(arguments.source, arguments.output)
