#!/usr/bin/env python3
"""Recover enlarged multicolor pixels without blending or palette conversion."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

from c64_palette import load_palette, snap_palette


def numbers(value, separator, count):
    try:
        result = tuple(int(part) for part in value.lower().split(separator))
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected integer coordinates or dimensions.") from error
    if len(result) != count:
        raise argparse.ArgumentTypeError(f"Expected {count} integers separated by '{separator}'.")
    return result


def cell_argument(value):
    result = numbers(value, "x", 2)
    if min(result) < 1:
        raise argparse.ArgumentTypeError("Cell dimensions must be positive.")
    return result


def origin_argument(value):
    result = numbers(value, ",", 2)
    if min(result) < 0:
        raise argparse.ArgumentTypeError("Origin must be nonnegative.")
    return result


def crop_argument(value):
    result = numbers(value, ",", 4)
    if min(result[:2]) < 0 or min(result[2:]) < 1:
        raise argparse.ArgumentTypeError("Crop needs nonnegative X,Y and positive width,height.")
    return result


def detect_axis(pixels, axis, noise_floor):
    """Find the largest period containing every lossless edge, or 90% for JPEG.

    Divisors of the true cell size also align with every edge. Multiples do not
    align with transitions between individual cells. JPEG noise is ignored only
    during detection; sampled output values always come directly from the source.
    """
    difference = np.abs(np.diff(pixels.astype(np.int16), axis=axis)).max(axis=2)
    energy = np.maximum(difference - noise_floor, 0).sum(axis=1 - axis, dtype=np.float64)
    total = float(energy.sum())
    if total == 0:
        raise ValueError("No pixel grid found: flat or low-contrast image. Supply --cell WIDTHxHEIGHT.")
    positions = np.arange(1, len(energy) + 1)
    candidates = []
    required_confidence = 0.9 if noise_floor else 1.0 - 1e-12
    # At least three cells must fit. Larger/sparser grids need explicit --cell.
    for step in range(2, min(256, pixels.shape[axis] // 3) + 1):
        phases = np.bincount(positions % step, weights=energy, minlength=step)
        origin = int(phases.argmax())
        confidence = float(phases[origin] / total)
        if confidence >= required_confidence:
            candidates.append((step, origin, confidence))
    if not candidates:
        raise ValueError("No clear enlarged pixel grid found. Supply --cell WIDTHxHEIGHT and, if needed, --origin X,Y.")
    return max(candidates, key=lambda item: item[0])


def extract(source, cell=None, origin=None, crop=None):
    with Image.open(source) as image:
        source_format = image.format
        source_size = image.size
        if image.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
            raise ValueError(f"Unsupported mode {image.mode}: use an 8-bit RGB/RGBA or indexed image.")
        has_alpha = "A" in image.mode or "transparency" in image.info
        pixels = np.asarray(image.convert("RGBA" if has_alpha else "RGB"))
        icc_profile = image.info.get("icc_profile")

    left, top, width, height = crop or (0, 0, *source_size)
    if left + width > source_size[0] or top + height > source_size[1]:
        raise ValueError("Crop lies outside the source image.")
    pixels = pixels[top:top + height, left:left + width]
    confidence = None
    if cell is None:
        # Lossless images retain every edge, including transitions of one RGB unit.
        noise_floor = 20 if source_format == "JPEG" else 0
        step_x, phase_x, confidence_x = detect_axis(pixels, 1, noise_floor)
        step_y, phase_y, confidence_y = detect_axis(pixels, 0, noise_floor)
        cell = (step_x, step_y)
        detected_origin = (phase_x, phase_y)
        confidence = [confidence_x, confidence_y]
    else:
        detected_origin = (0, 0)
    origin = origin if origin is not None else detected_origin
    step_x, step_y = cell
    phase_x, phase_y = origin
    columns = (width - phase_x) // step_x
    rows = (height - phase_y) // step_y
    if columns < 1 or rows < 1:
        raise ValueError("No complete pixel cells fit inside the selected region.")

    xs = phase_x + np.arange(columns) * step_x + step_x // 2
    ys = phase_y + np.arange(rows) * step_y + step_y // 2
    sampled = pixels[ys[:, None], xs[None, :]]
    output = Image.fromarray(np.repeat(sampled, 2, axis=1))
    record = {
        "source": str(source.resolve()),
        "source_format": source_format,
        "source_size": list(source_size),
        "cell_size": list(cell),
        "origin": list(origin),
        "grid_confidence": confidence,
        "source_region": [left + phase_x, top + phase_y, columns * step_x, rows * step_y],
        "trimmed_edges": [phase_x, phase_y, width - phase_x - columns * step_x,
                          height - phase_y - rows * step_y],
        "logical_size": [columns, rows],
        "output_size": list(output.size),
        "sampling": "source cell center; exact decoded channels; each sample repeated twice horizontally",
    }
    return output, record, icc_profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, nargs="+", help="Source PNG/JPEG images; shell globs are supported.")
    parser.add_argument("-o", "--output-dir", type=Path, required=True, help="Directory for PNGs and manifest.json.")
    parser.add_argument("--cell", type=cell_argument, help="Source pixels per multicolor cell, e.g. 10x5; otherwise detect.")
    parser.add_argument("--origin", type=origin_argument, help="First complete cell X,Y, relative to the crop; otherwise detect.")
    parser.add_argument("--crop", type=crop_argument, help="Optional source rectangle X,Y,WIDTH,HEIGHT, before extraction.")
    parser.add_argument("--palette", type=Path, help="Optionally snap colors to a 16-color VICE .vpl palette, without dithering.")
    args = parser.parse_args()

    palette = None
    if args.palette is not None:
        try:
            palette = load_palette(args.palette)
        except (OSError, ValueError) as error:
            parser.error(str(error))

    destinations = [args.output_dir / f"{source.stem}.png" for source in args.inputs]
    manifest_path = args.output_dir / "manifest.json"
    all_destinations = destinations + [manifest_path]
    resolved = [destination.resolve() for destination in all_destinations]
    if len(set(resolved)) != len(resolved):
        parser.error("Input names collide in the output directory. Use separate directories.")
    sources = {source.resolve() for source in args.inputs}
    for destination in all_destinations:
        if destination.resolve() in sources or destination.exists():
            parser.error(f"Refusing to overwrite: {destination}")

    records = []
    for source, destination in zip(args.inputs, destinations):
        try:
            output, record, icc_profile = extract(source, args.cell, args.origin, args.crop)
        except (OSError, ValueError) as error:
            print(f"{source}: {error}", file=sys.stderr)
            return 1
        if palette is not None:
            output, palette_record = snap_palette(output, palette)
            record["palette"] = {
                "source": str(args.palette.resolve()),
                "colors": palette.tolist(),
                "mapping": "nearest RGB; no dithering",
                **palette_record,
            }
            # Palette RGB values use their own display space, not a source ICC profile.
            icc_profile = None
        args.output_dir.mkdir(parents=True, exist_ok=True)
        save_options = {"icc_profile": icc_profile} if icc_profile else {}
        # Exclusive creation protects existing files even if another process writes
        # after the preflight check. Inputs are never modified.
        with destination.open("xb") as stream:
            output.save(stream, format="PNG", **save_options)
        record["output"] = str(destination.resolve())
        records.append(record)
        print(f"{source.name}: cell {record['cell_size'][0]}x{record['cell_size'][1]}, "
              f"region {','.join(map(str, record['source_region']))} -> "
              f"{output.width}x{output.height} {destination}")
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump({"images": records}, stream, indent=2)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
