#!/usr/bin/env python3
"""Assemble the animated Megaplot polyline for the C64."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import char_tables
import megaplot
import wave_model

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"


def build_displaced_bank(tile_to_code):
    """Pack each high-byte group into a fixed 512-slot glyph dictionary."""
    slot_count = 512
    slot_mask = slot_count - 1
    groups = [[] for _ in range(256)]
    for pattern, code in tile_to_code.items():
        groups[pattern >> 8].append((pattern & 255, code + 1))

    displacement = [0] * len(groups)
    keys_low = bytearray(slot_count)
    keys_high = bytearray(slot_count)
    values = bytearray(slot_count)
    group_order = sorted(range(len(groups)), key=lambda high: (-len(groups[high]), high))
    for high in group_order:
        group = groups[high]
        if not group:
            continue
        for offset in range(slot_count):
            if all(not values[(offset + low) & slot_mask] for low, _ in group):
                displacement[high] = offset
                for low, code in group:
                    slot = (offset + low) & slot_mask
                    keys_low[slot] = low
                    keys_high[slot] = high
                    values[slot] = code
                break
        else:
            raise ValueError(f"Could not assign glyph slots for high pattern byte {high:02x}")

    displacement_low = bytes(offset & 255 for offset in displacement)
    displacement_high = bytes(offset >> 8 for offset in displacement)
    for pattern in range(65536):
        low, high = pattern & 255, pattern >> 8
        offset = displacement_low[high] | (displacement_high[high] << 8)
        slot = (offset + low) & slot_mask
        code = values[slot] if (keys_low[slot], keys_high[slot]) == (low, high) else 0
        expected = tile_to_code.get(pattern, -1) + 1
        if code != expected:
            raise AssertionError(f"Glyph dictionary mismatch for pattern {pattern:04x}")

    return {
        "hashkl": keys_low,
        "hashkh": keys_high,
        "hashv": values,
        "hash-disp-lo": displacement_low,
        "hash-disp-hi": displacement_high,
    }


def build_assets(background=None):
    tile_to_code, tiles, _ = megaplot.build_font()
    reverse_low = bytearray(256)
    reverse_high = bytearray(256)
    for pattern, code in tile_to_code.items():
        reverse_low[code + 1] = pattern & 255
        reverse_high[code + 1] = pattern >> 8
    assets = {
        "charset": megaplot.charset_bytes(tiles),
        "revlo": reverse_low,
        "revhi": reverse_high,
        **char_tables.build_packed_pairs(tile_to_code),
        "char-short-decisions": char_tables.build_short_decisions(),
        **build_displaced_bank(tile_to_code),
        **wave_model.sine_assets(),
    }
    if background == "noice":
        from noice_background import build_noice_template
        assets["background"] = build_noice_template(tile_to_code)
    return assets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--segments", type=int, default=wave_model.DEFAULT_SEGMENTS,
                        help=(f"number of joined line segments ({wave_model.MIN_SEGMENTS}–"
                              f"{wave_model.MAX_SEGMENTS}, default {wave_model.DEFAULT_SEGMENTS})"))
    parser.add_argument("--background", choices=("noice",), help="draw the wave over the NOICE line art")
    args = parser.parse_args()
    if not wave_model.MIN_SEGMENTS <= args.segments <= wave_model.MAX_SEGMENTS:
        parser.error(f"--segments must be between {wave_model.MIN_SEGMENTS} and {wave_model.MAX_SEGMENTS}")

    output = BUILD / args.background if args.background else BUILD
    output.mkdir(parents=True, exist_ok=True)
    assets = build_assets(args.background)
    background = assets.pop("background", None)
    for name, data in assets.items():
        (BUILD / f"{name}.bin").write_bytes(data)
    if background is not None:
        (output / "background.bin").write_bytes(background)
        (output / "charset.bin").write_bytes(assets["charset"])

    program = output / "megaplot.prg"
    symbols = output / "main.sym"
    kickass = Path.home() / ".local/bin/kickass"
    result = subprocess.run(
        [kickass, "main.asm", "-odir", output, "-o", program, "-symbolfile",
         f":segments={args.segments}", f":background={args.background or 'blank'}"],
        cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    (output / "build.log").write_text(result.stdout)
    if result.returncode or "Internal error" in result.stdout or not symbols.is_file() or not symbols.stat().st_size:
        raise SystemExit(f"Assembly or symbol generation failed. See {output / 'build.log'}")

    report = {
        "segments": args.segments,
        "nodes": args.segments + 1,
        "background": args.background,
        "program": program.name,
        "programSha256": hashlib.sha256(program.read_bytes()).hexdigest(),
    }
    (output / "megaplot.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Built {program} ({args.segments} segments, {args.segments + 1} nodes)")


if __name__ == "__main__":
    main()
