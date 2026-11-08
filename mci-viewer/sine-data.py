#!/usr/bin/env python3
"""Prepare fixed-palette source strips for the stock C64 MCI sine player.

Requires NumPy and Pillow. Each 16-line destination band owns 24 source lines:
four above, sixteen within the band, and four below. The two phases share one
Color RAM value per column and band, while retaining independent screen pairs.
"""

import argparse
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
from PIL import Image


PALETTE = np.array([
    [0, 0, 0], [255, 255, 255], [150, 40, 46], [91, 214, 206],
    [159, 45, 173], [65, 185, 54], [39, 36, 196], [239, 243, 71],
    [159, 72, 21], [94, 53, 0], [218, 95, 102], [71, 71, 71],
    [120, 120, 120], [145, 255, 132], [104, 100, 255], [174, 174, 174],
], dtype=np.uint8)
BRIGHTNESS_BANDS = [[0], [6, 9], [2, 11], [4, 8], [14, 12],
                    [5, 10], [3, 15], [13, 7], [1]]


def decode_mci(data):
    if len(data) != 19434 or data[:2] != b"\x00\x9c":
        raise ValueError("Expected an uncompressed 19,434-byte True Paint MCI.")
    background = data[1002]
    shared = np.frombuffer(data[18434:19434], dtype=np.uint8)
    if background > 15 or np.any(shared > 15):
        raise ValueError("MCI colors must use C64 indices 0–15.")
    phases = np.empty((2, 200, 160), dtype=np.uint8)
    for phase in range(2):
        screen_offset = 2 if phase == 0 else 17410
        bitmap_offset = 1026 if phase == 0 else 9218
        for y in range(200):
            for column in range(40):
                tile = y // 8 * 40 + column
                screen = data[screen_offset + tile]
                colors = [background, screen >> 4, screen & 15, int(shared[tile])]
                bits = data[bitmap_offset + tile * 8 + y % 8]
                for pixel in range(4):
                    phases[phase, y, column * 4 + pixel] = colors[bits >> (6 - pixel * 2) & 3]
    return background, phases


def color_costs():
    rgb = PALETTE.astype(np.float64) / 255
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    roots = np.cbrt(linear @ np.array([
        [0.4122214708, 0.2119034982, 0.0883024619],
        [0.5363325363, 0.6806995451, 0.2817188376],
        [0.0514459929, 0.1073969566, 0.6299787005],
    ]))
    lab = roots @ np.array([
        [0.2104542553, 1.9779984951, 0.0259040371],
        [0.7936177850, -2.4285922050, 0.7827717662],
        [-0.0040720468, 0.4505937099, -0.8086757660],
    ])
    lightness = np.empty(16)
    for band in BRIGHTNESS_BANDS:
        lightness[band] = np.mean(lab[band, 0])
    primary = (lightness[:, None] - lightness[None, :]) ** 2
    secondary = np.sum((lab[:, None, 1:] - lab[None, :, 1:]) ** 2, axis=2)
    return primary, secondary


def fit_strips(background, phases):
    primary, secondary = color_costs()
    triples = np.array(list(itertools.combinations(
        [color for color in range(16) if color != background], 3)), dtype=np.uint8)
    mappings = np.empty((len(triples), 16), dtype=np.uint8)
    primary_costs = np.empty((len(triples), 16))
    secondary_costs = np.empty((len(triples), 16))
    for index, triple in enumerate(triples):
        allowed = [background, *map(int, triple)]
        for target in range(16):
            best = min(allowed, key=lambda color: (primary[target, color], secondary[target, color]))
            mappings[index, target] = best
            primary_costs[index, target] = primary[target, best]
            secondary_costs[index, target] = secondary[target, best]

    strips = np.empty((13 * 40, 2, 24, 4), dtype=np.uint8)
    histograms = np.empty((13 * 40, 2, 16), dtype=np.float64)
    for band in range(13):
        rows = np.clip(np.arange(band * 16 - 4, band * 16 + 20), 0, 199)
        reachable_rows = 24 if band < 12 else 16
        for column in range(40):
            cell = band * 40 + column
            strips[cell] = phases[:, rows, column * 4:column * 4 + 4]
            for phase in range(2):
                histograms[cell, phase] = np.bincount(
                    strips[cell, phase, :reachable_rows].ravel(), minlength=16)
    primary_errors = np.einsum("bpt,ct->bpc", histograms, primary_costs)
    secondary_errors = np.einsum("bpt,ct->bpc", histograms, secondary_costs)
    best_primary = np.full((520, 2, 16), np.inf)
    best_secondary = np.full((520, 2, 16), np.inf)
    best_triples = np.zeros((520, 2, 16), dtype=np.int32)
    cells = np.arange(520)
    for shared in range(16):
        if shared == background:
            continue
        candidates = np.flatnonzero(np.any(triples == shared, axis=1))
        for phase in range(2):
            errors = primary_errors[:, phase, candidates]
            minimum = np.min(errors, axis=1)
            ties = np.abs(errors - minimum[:, None]) <= 1e-12
            chroma = np.where(ties, secondary_errors[:, phase, candidates], np.inf)
            chosen = candidates[np.argmin(chroma, axis=1)]
            best_triples[:, phase, shared] = chosen
            best_primary[:, phase, shared] = primary_errors[cells, phase, chosen]
            best_secondary[:, phase, shared] = secondary_errors[cells, phase, chosen]
    totals = np.sum(best_primary, axis=1)
    minima = np.min(totals, axis=1)
    ties = np.abs(totals - minima[:, None]) <= 1e-12
    chroma = np.where(ties, np.sum(best_secondary, axis=1), np.inf)
    shared_colors = np.argmin(chroma, axis=1).astype(np.uint8)
    sources = np.empty((2, 520, 24), dtype=np.uint8)
    screen_pairs = np.empty((2, 520), dtype=np.uint8)
    fitted = np.empty_like(phases)
    bitmaps = np.empty((2, 8000), dtype=np.uint8)
    screens = np.empty((2, 1000), dtype=np.uint8)
    colors = np.empty(1000, dtype=np.uint8)
    for cell in range(520):
        band, column = divmod(cell, 40)
        shared = int(shared_colors[cell])
        for phase in range(2):
            triple_index = best_triples[cell, phase, shared]
            pair = [int(color) for color in triples[triple_index] if color != shared]
            allowed = [background, *pair, shared]
            mapped = mappings[triple_index, strips[cell, phase]]
            codes = np.empty_like(mapped)
            for code, color in enumerate(allowed):
                codes[mapped == color] = code
            sources[phase, cell] = ((codes[:, 0] << 6) | (codes[:, 1] << 4) |
                                    (codes[:, 2] << 2) | codes[:, 3])
            screen_pairs[phase, cell] = pair[0] << 4 | pair[1]
            for local_y in range(16):
                y = band * 16 + local_y
                if y >= 200:
                    break
                tile = y // 8 * 40 + column
                fitted[phase, y, column * 4:column * 4 + 4] = mapped[local_y + 4]
                bitmaps[phase, tile * 8 + y % 8] = sources[phase, cell, local_y + 4]
                screens[phase, tile] = screen_pairs[phase, cell]
                colors[tile] = shared
    return sources, bitmaps, screens, colors, fitted


def blended_preview(phases, background):
    first = np.repeat(PALETTE[phases[0]], 2, axis=1)
    second = np.empty_like(first)
    second[:, 0] = PALETTE[background]
    second[:, 1:] = np.repeat(PALETTE[phases[1]], 2, axis=1)[:, :-1]
    return ((first.astype(np.uint16) + second.astype(np.uint16) + 1) // 2).astype(np.uint8)


def prepare(source, output):
    data = source.read_bytes()
    background, phases = decode_mci(data)
    sources, bitmaps, screens, colors, fitted = fit_strips(background, phases)
    payloads = {
        "source-a.bin": sources[0].tobytes(), "source-b.bin": sources[1].tobytes(),
        "bitmap-a.bin": bitmaps[0].tobytes(), "bitmap-b.bin": bitmaps[1].tobytes(),
        "screen-a.bin": screens[0].tobytes(), "screen-b.bin": screens[1].tobytes(),
        "colors.bin": colors.tobytes(), "background.bin": bytes([background]),
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (output / name).write_bytes(payload)
    original_preview = blended_preview(phases, background)
    fitted_preview = blended_preview(fitted, background)
    for name, pixels in [("original.png", original_preview), ("fitted.png", fitted_preview)]:
        Image.fromarray(pixels).resize((960, 600), Image.Resampling.NEAREST).save(output / name)
    comparison = np.concatenate([original_preview, fitted_preview], axis=1)
    Image.fromarray(comparison).resize((1280, 400), Image.Resampling.NEAREST).save(output / "comparison.png")
    difference = PALETTE[fitted].astype(np.float64) - PALETTE[phases].astype(np.float64)
    receipt = {
        "source": str(source.resolve()), "source_sha256": hashlib.sha256(data).hexdigest(),
        "format": "MCI sine source strips v1", "bands": 13,
        "output_rows_per_band": 16, "source_rows_per_band": 24,
        "source_layout": "(band * 40 + column) * 24 + source_strip_row",
        "source_y": "clamp(band * 16 - 4 + source_strip_row, 0, 199)",
        "runtime_strip_row": "(output_y & 15) + 4 + sine_displacement",
        "maximum_displacement_pixels": 4, "background": background,
        "fitting": "joint minimum brightness-band SSE, then Oklab chroma SSE over both phases",
        "zero_wave_metrics": {
            "changed_phase_pixel_percent": float(np.mean(fitted != phases) * 100),
            "rgb_rmse": float(np.sqrt(np.mean(difference ** 2))),
        },
        "files": {name: {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
                  for name, payload in payloads.items()},
    }
    (output / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"output": str(output.resolve()), **receipt["zero_wave_metrics"],
                      "source_bytes_per_phase": sources[0].size}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.source, args.output_dir)
