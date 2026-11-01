#!/usr/bin/env python3
"""Bundle AFLI-editor images with the pinned GoDot PAL engine in static hires mode."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


PLAYER_SHA256 = "a6585bcba70bfaba240f3fa0732a04a28451e5159a0e49f2fc81d4fa39c3eb82"
PLAYER_DOWNLOAD = "https://www.godot64.de/iflis/diashow_eng.prg"
PLAYER_SOURCE = "https://github.com/godot64/GoDot/blob/90c8c5c05a6683edb76a82efd8d3cff6f4713c3d/extras/iflidiashow.a"
PATCHES = [
    (0x0dc7, "3b", "38", "start generated scanline phase zero"),
    (0x0dcc, "08", "18", "advance generated screen banks to compensate the DMA-delayed D018 write"),
    (0x0e71, "38", "08", "select the first screen matrix before the initial DMA"),
    (0x0e76, "19", "08", "hires, 40 columns, fixed X-scroll 0"),
    (0x0e95, "2f", "2b", "start the stable IRQ four raster lines earlier"),
    (0x0e9f, "3b", "38", "retain initial phase zero for the first VIC badline/RC reset"),
    (0x0ed2, "30", "2c", "move the second stabilizing IRQ four lines earlier"),
    (0x0ef4, "20 00 84", "20 90 20", "add 20 entry cycles through the bootstrap JMP trampoline"),
    (0x0efa, "ad 16 d0 49 01 8d 16 d0", "a9 30 8d 11 d0 ea ea ea",
     "replace the X-scroll toggle with the vertical-border postlude"),
    (0x0f0b, "2f", "2b", "re-arm the earlier stable IRQ"),
]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def build(inputs, output):
    source_dir = Path(__file__).resolve().parent
    player_path = source_dir.parent.parent / "ifli-viewer" / "diashow_eng.prg"
    player = player_path.read_bytes()
    if sha256(player) != PLAYER_SHA256 or player[:2] != b"\x01\x08" or player[7:11] != b"2065":
        raise ValueError("The pinned PAL engine changed; its code and patch addresses need review.")
    if player[0x676:0x67b] != bytes.fromhex("a9 19 8d 16 d0"):
        raise ValueError("Unexpected initial $D016 instruction.")
    if player[0x6fb:0x703] != bytes.fromhex("ad 16 d0 49 01 8d 16 d0"):
        raise ValueError("Unexpected per-frame X-scroll instruction.")

    names = [path.stem for path in inputs]
    if len(set(names)) != len(names):
        raise ValueError("Input filenames would produce duplicate PRG names.")
    images = []
    for path in inputs:
        image = path.read_bytes()
        if len(image) != 16385 or image[:2] != b"\x00\x40":
            raise ValueError(f"{path.name}: expected a 16385-byte AFLI-editor image with load address $4000.")
        screens = bytearray(image[2:8194])
        bitmap = bytearray(image[8194:16194])
        # Clear the first three columns' stored data. The hardware hires FLI
        # gray strip is excluded from the valid image area.
        for row in range(8):
            for tile_row in range(25):
                start = row * 1024 + tile_row * 40
                screens[start:start + 3] = bytes(3)
        for tile_row in range(25):
            start = tile_row * 320
            bitmap[start:start + 24] = bytes(24)
        images.append((image, screens, bitmap))

    # Every build has its own assembler products and receipts; never replace a build.
    output.mkdir(parents=True, exist_ok=False)
    (output / "GoDot-LICENSE.txt").write_bytes((source_dir.parent / "GoDot-LICENSE.txt").read_bytes())
    subprocess.run([
        str(Path.home() / ".local/bin/kickass"), str(source_dir / "boot.asm"),
        "-o", str(output.resolve() / "boot.prg"), "-odir", str(output.resolve()),
    ], check=True)
    bootstrap = (output / "boot.prg").read_bytes()
    if bootstrap[:2] != b"\x00\x20" or 0x2000 + len(bootstrap) - 2 > 0x3ff0:
        raise ValueError("The bootstrap overlaps staged graphics data.")

    patched = bytearray(player[2:])
    patched[5:9] = b"8192"  # Existing BASIC SYS now enters standalone startup.
    for address, original, replacement, _purpose in PATCHES:
        offset = address - 0x0801
        expected = bytes.fromhex(original)
        if patched[offset:offset + len(expected)] != expected:
            raise ValueError(f"Unexpected engine instruction at ${address:04x}.")
        patched[offset:offset + len(expected)] = bytes.fromhex(replacement)
    receipts = []
    for path, name, (image, screens, bitmap) in zip(inputs, names, images):
        ram = bytearray(0xc38c - 0x0801)
        ram[:len(patched)] = patched
        ram[0x2000 - 0x0801:0x2000 - 0x0801 + len(bootstrap) - 2] = bootstrap[2:]
        ram[0x4000 - 0x0801:0x6000 - 0x0801] = screens
        ram[0x6000 - 0x0801:0x7f40 - 0x0801] = bitmap
        ram[0x83e8 - 0x0801:0xa3e8 - 0x0801] = screens
        ram[0xa3e8 - 0x0801:0xc328 - 0x0801] = bitmap
        # The unused background sequences and Color RAM staging remain zero.
        program = b"\x01\x08" + ram
        if len(program) != 48013:
            raise ValueError("Unexpected standalone AFLI PRG size.")
        target = output / f"{name}.prg"
        target.write_bytes(program)
        receipts.append({
            "input": str(path.resolve()), "input_sha256": sha256(image),
            "output": str(target.resolve()), "output_sha256": sha256(program), "bytes": len(program),
            "active_bank_sha256": sha256(screens + bitmap),
            "display_mask": {"left_character_columns": 3, "left_hires_pixels": 24, "visible_image_width": 296},
        })
        print(f"Created {target} ({len(program)} bytes)")

    (output / "build-receipt.json").write_text(json.dumps({
        "format": "standalone PAL C64 AFLI PRG", "player_download": PLAYER_DOWNLOAD,
        "player_source": PLAYER_SOURCE, "player_sha256": PLAYER_SHA256,
        "bootstrap_sha256": sha256(bootstrap), "bootstrap_source_sha256": sha256((source_dir / "boot.asm").read_bytes()),
        "entry": "$2000 (BASIC SYS 8192)", "display_loop": "$2088",
        "generated_scanline_blocks": 208,
        "raster_entry_delay": {"address": "$2090", "cycles": 20, "code": "7 NOPs, BIT $02, JMP $8400"},
        "patches": [{"address": f"${address:04x}", "original": original,
                     "replacement": replacement, "purpose": purpose}
                    for address, original, replacement, purpose in PATCHES],
        "vic_banks": [
            {"dd00_low_bits": 2, "screens": "$4000-$5fff", "bitmap": "$6000-$7f3f"},
            {"dd00_low_bits": 0, "screens": "$c000-$dfff", "bitmap": "$e000-$ff3f"},
        ],
        "notes": ["Both banks contain the same static AFLI image.",
                  "Original per-scanline instructions and VIC bank switching remain unchanged.",
                  "Raster/phase and valid-bitmap border adjustments are recorded in the checked patch list.",
                  "The hires FLI left strip may appear gray; the leftmost 24 pixels are outside the valid image area.",
                  "Original AFLI files are read only and retain their hashes."],
        "files": receipts,
    }, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args()
    build(args.inputs, args.output)
