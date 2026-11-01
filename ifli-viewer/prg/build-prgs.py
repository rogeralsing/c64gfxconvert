#!/usr/bin/env python3
"""Bundle converter FP2 exports with the pinned original GoDot PAL player."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def build(inputs, output):
    source_dir = Path(__file__).resolve().parent
    viewer_path = source_dir.parent / "diashow_eng.prg"
    viewer = viewer_path.read_bytes()
    expected_viewer = "a6585bcba70bfaba240f3fa0732a04a28451e5159a0e49f2fc81d4fa39c3eb82"
    if hashlib.sha256(viewer).hexdigest() != expected_viewer:
        raise ValueError("The PAL viewer changed; its startup addresses need review.")
    if viewer[:2] != b"\x01\x08" or viewer[7:11] != b"2065":
        raise ValueError("Unexpected PAL viewer BASIC entry.")

    output.mkdir(parents=True, exist_ok=True)
    names = [path.stem.removeprefix("^^") for path in inputs]
    if len(set(names)) != len(names):
        raise ValueError("Input filenames would produce duplicate PRG names.")
    for name in names:
        if (output / f"{name}.prg").exists():
            raise FileExistsError(f"Refusing to replace {output / f'{name}.prg'}")

    header = bytes.fromhex("f0 3f 46 55 4e 50 41 49 4e 54 20 28 4d 54 29 20 00 ad")
    images = []
    for path in inputs:
        image = path.read_bytes()
        if len(image) != 33694 or image[:18] != header:
            raise ValueError(f"{path.name}: expected an uncompressed converter FP2 export.")
        if any(color > 15 for color in image[16402:17402] + image[16210:16402] + image[33594:33694]):
            raise ValueError(f"{path.name}: invalid C64 color index.")
        images.append(image)

    subprocess.run([
        str(Path.home() / ".local/bin/kickass"), str(source_dir / "boot.asm"),
        "-o", str(source_dir / "boot.prg"), "-odir", str(source_dir),
    ], check=True)
    bootstrap = (source_dir / "boot.prg").read_bytes()
    if bootstrap[:2] != b"\x00\x20" or 0x2000 + len(bootstrap) - 2 > 0x3ff0:
        raise ValueError("The bootstrap overlaps staged image data.")

    # Retain the original player and redirect its existing BASIC SYS to $2000.
    patched_viewer = bytearray(viewer[2:])
    patched_viewer[5:9] = b"8192"
    receipts = []
    for path, name, image in zip(inputs, names, images):
        ram = bytearray(0xc38c - 0x0801)
        ram[:len(patched_viewer)] = patched_viewer
        ram[0x2000 - 0x0801:0x2000 - 0x0801 + len(bootstrap) - 2] = bootstrap[2:]
        ram[0x3ff0 - 0x0801:] = image[2:]
        # The GoDot PAL viewer needs three blank character columns at the left.
        # Mask both phase bitmaps in the PRG without changing the source FP2.
        for fp2_bitmap_offset in (8210, 25594):
            bitmap_start = 0x3ff0 - 0x0801 + fp2_bitmap_offset - 2
            for tile_row in range(25):
                row_start = bitmap_start + tile_row * 320
                ram[row_start:row_start + 24] = bytes(24)
        program = b"\x01\x08" + ram
        if len(program) != 48013:
            raise ValueError("Unexpected standalone PRG size.")
        target = output / f"{name}.prg"
        target.write_bytes(program)
        receipts.append({
            "input": str(path.resolve()),
            "input_sha256": hashlib.sha256(image).hexdigest(),
            "output": str(target.resolve()),
            "output_sha256": hashlib.sha256(program).hexdigest(),
            "bytes": len(program),
            "display_mask": {
                "left_character_columns": 3,
                "left_hires_pixels": 24,
                "additional_hires_pixels_beyond_converter": 8,
                "phases": 2,
            },
        })
        print(f"Created {target} ({len(program)} bytes)")
    (output / "build-receipt.json").write_text(json.dumps({
        "format": "standalone PAL C64 IFLI PRG",
        "player": "GoDot English PAL IFLI slideshow player, display routines",
        "player_source": "https://github.com/godot64/GoDot/blob/master/extras/iflidiashow.a",
        "player_download": "https://www.godot64.de/iflis/diashow_eng.prg",
        "player_sha256": expected_viewer,
        "bootstrap_sha256": hashlib.sha256(bootstrap).hexdigest(),
        "files": receipts,
    }, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args()
    build(args.inputs, args.output)
