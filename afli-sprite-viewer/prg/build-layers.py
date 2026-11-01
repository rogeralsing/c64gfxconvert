#!/usr/bin/env python3
"""Build standalone PAL FLI or AFLI/sprite PRGs from converter layer ZIP archives."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import zipfile


SOURCE_DIR = Path(__file__).resolve().parent
ROOT = SOURCE_DIR.parent.parent
BASE = runpy.run_path(str(SOURCE_DIR / "build-prgs.py"))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_layers(path):
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise ValueError(f"{path.name}: corrupt ZIP entry {bad}.")
        manifest = json.loads(archive.read("manifest.json"))
        multicolor = manifest.get("format") == "c64-fli-sprite-layers"
        if manifest.get("format") not in {"c64-afli-sprite-layers", "c64-fli-sprite-layers"} or manifest.get("version") != 1:
            raise ValueError(f"{path.name}: unsupported converter layer format.")
        if multicolor:
            screens = archive.read(manifest["files"]["screen"])
            bitmap = archive.read(manifest["files"]["bitmap"])
            color_ram = archive.read(manifest["files"]["colorRam"])
            if len(screens) != 8192 or len(bitmap) != 8000 or len(color_ram) != 1000:
                raise ValueError(f"{path.name}: expected 8,192 screen, 8,000 bitmap and 1,000 Color RAM bytes.")
            if any(color > 15 for color in color_ram):
                raise ValueError(f"{path.name}: Color RAM values must be C64 color indices.")
            background = manifest.get("backgroundColor", {}).get("index")
            if type(background) is not int or not 0 <= background < 16:
                raise ValueError(f"{path.name}: background color must be an index from 0 through 15.")
            # The bank packer consumes the shared screen/bitmap byte layout.
            # This internal wrapper is not an AFLI export of multicolor data.
            image = b"\x00\x40" + screens + bitmap + bytes(191)
        else:
            image = archive.read(manifest["files"]["afli"])
            color_ram = bytes(1000)
        mask = archive.read(manifest["files"]["spriteMask"])
    if len(image) != 16385 or image[:2] != b"\x00\x40":
        raise ValueError(f"{path.name}: expected a 16,385-byte AFLI-editor image.")
    width = 160 if multicolor else 320
    if manifest.get("image", {}).get("width") != width or manifest["image"].get("height") != 200:
        raise ValueError(f"{path.name}: expected a {width} by 200 image.")
    if multicolor and (manifest["image"].get("pixelAspectRatio") != [2, 1] or
                       manifest.get("canvas") != {"width": 320, "height": 200}):
        raise ValueError(f"{path.name}: multicolor layers require a 320 by 200 display canvas and 2:1 pixels.")
    if manifest.get("layout", {}).get("spriteRect") != {"x": 112, "y": 0, "width": 192, "height": 200}:
        raise ValueError(f"{path.name}: unsupported sprite field geometry.")
    packing = manifest.get("mask", {})
    if len(mask) != 4800 or packing.get("format") != "packed-raster-mask" or packing.get("bitOrder") != "msb-first":
        raise ValueError(f"{path.name}: expected a 4,800-byte MSB-first sprite raster mask.")
    color = manifest.get("spriteColor", {}).get("index")
    if type(color) is not int or not 0 <= color < 16:
        raise ValueError(f"{path.name}: sprite color must be an index from 0 through 15.")
    return image, mask, manifest, color_ram


def make_bank(image, mask, second):
    """Keep the bank's visible image half and pack 64 independently selected sprites."""
    bank = bytearray(16384)
    protected = set()
    # Overlapping boundary rows let the late bank change preserve all fetches.
    for y in range(80 if second else 0, 200 if second else 88):
        row = y & 7
        for column in range(14, 40):
            tile = (y >> 3) * 40 + column
            screen = row * 1024 + tile
            bitmap = 8192 + tile * 8 + row
            bank[screen] = image[2 + screen]
            bank[bitmap] = image[2 + bitmap]
            protected.update((screen, bitmap))
    if second:
        slots = list(range(0x2000, 0x2c80, 64))
        slots += [matrix * 1024 + offset for matrix, count in [(0, 6), (1, 6), (2, 2)]
                  for offset in range(0, count * 64, 64)]
    else:
        slots = list(range(0x2dc0, 0x2dc0 + 64 * 64, 64))
    assert len(slots) == 64 and len(set(slots)) == 64
    for slot in slots:
        assert slot % 64 == 0 and not any(address in protected for address in range(slot, slot + 64))
        assert not any(address % 1024 >= 1016 and address < 8192 for address in range(slot, slot + 64))
    for matrix in range(8):
        for sprite in range(8):
            bank[matrix * 1024 + 1016 + sprite] = slots[matrix * 8 + sprite] // 64
    written = {}
    for y in range(87 if second else 0, 200 if second else 89):
        matrix = max(0, y - 1) & 7
        sprite_row = (y + 16) % 21
        for sprite in range(8):
            offset = slots[matrix * 8 + sprite] + sprite_row * 3
            for byte in range(3):
                value = mask[y * 24 + sprite * 3 + byte]
                address = offset + byte
                if address in written and written[address] != value:
                    raise ValueError("Sprite row packing aliases two different source rows.")
                bank[address] = value
                written[address] = value
    return bytes(bank), slots


def kernel(color):
    text, events = BASE["scanline_kernel"]()
    old = "row134:\n    nop\n    lda #$68\n    sta $d018\n    lda #$3e\n    sta $d011"
    new = "row134:\n    ldy #$3f\n    lda #$68\n    sta $d018\n    lda #$3e\n    sta $d011"
    assert text.count(old) == 1
    text = text.replace(old, new)
    old = "row135:\n    nop\n    lda #$78\n    sta $d018\n    lda #$3f\n    sta $d011"
    new = "row135:\n    stx $dd00\n    lda #$78\n    sta $d018\n    sty $d011"
    assert text.count(old) == 1
    text = text.replace(old, new)
    old = "    bmi waitFrameWrap\n    lda #1"
    assert text.count(old) == 1
    return text.replace(old, f"    bmi waitFrameWrap\n    lda #{color}"), events


def build(inputs, output, entry_nops):
    player = (ROOT / "ifli-viewer/diashow_eng.prg").read_bytes()
    if sha256(player) != BASE["PLAYER_SHA256"]:
        raise ValueError("The pinned GoDot player changed.")
    template = (SOURCE_DIR / "layers.asm").read_text()
    patches = [*BASE["PATCHES"],
               (0x0e6c, "00", "02", "begin every image in VIC bank A"),
               (0x0f02, "ad 00 dd 49 02 8d 00 dd", "a9 02 8d 00 dd ea ea ea", "restore VIC bank A after the image")]
    names = [re.sub(r"[^a-zA-Z0-9_-]+", "-", path.stem).strip("-") for path in inputs]
    if len(set(names)) != len(names) or any(not name for name in names):
        raise ValueError("Input archive names would collide.")
    layers = [read_layers(path) for path in inputs]
    output.mkdir(parents=True, exist_ok=False)
    summaries = []
    for path, name, (image, mask, manifest, color_ram) in zip(inputs, names, layers):
        destination = output / name
        destination.mkdir()
        multicolor = manifest["format"] == "c64-fli-sprite-layers"
        background = manifest["backgroundColor"]["index"] if multicolor else 0
        mode_patches = [(address, original, "18" if multicolor and address == 0x0e76 else replacement, purpose)
                        for address, original, replacement, purpose in patches]
        patched = bytearray(player[2:])
        patched[5:9] = b"8192"
        for address, original, replacement, purpose in mode_patches:
            start = address - 0x0801
            old = bytes.fromhex(original)
            if patched[start:start + len(old)] != old:
                raise ValueError(f"Pinned player instruction mismatch at ${address:04x}.")
            patched[start:start + len(old)] = bytes.fromhex(replacement)
        color = manifest["spriteColor"]["index"]
        bank_a, pointers_a = make_bank(image, mask, False)
        bank_b, pointers_b = make_bank(image, mask, True)
        scanlines, events = kernel(color)
        assembly = template.replace("    // ENTRY_DELAY", "    nop\n" * entry_nops)
        assembly = assembly.replace("    // GENERATED_SCANLINES", scanlines).replace("SPRITE_COLOR_VALUE", str(color))
        assembly = assembly.replace("BACKGROUND_COLOR_VALUE", str(background))
        rendered = destination / "boot-rendered.asm"
        rendered.write_text(assembly)
        subprocess.run([str(Path.home() / ".local/bin/kickass"), str(rendered.resolve()),
                        "-o", str(destination.resolve() / "boot.prg"), "-odir", str(destination.resolve()),
                        "-symbolfile"], check=True)
        bootstrap = (destination / "boot.prg").read_bytes()
        if bootstrap[:2] != b"\x00\x20" or 0x2000 + len(bootstrap) - 2 >= 0x4000:
            raise ValueError("Bootstrap overlaps the graphics bank.")
        ram = bytearray(0xc3e8 - 0x0801)
        ram[:len(patched)] = patched
        start = 0x2000 - 0x0801
        ram[start:start + len(bootstrap) - 2] = bootstrap[2:]
        ram[0x4000 - 0x0801:0x8000 - 0x0801] = bank_a
        ram[0x8000 - 0x0801:0x83e8 - 0x0801] = color_ram
        ram[0x83e8 - 0x0801:0xc3e8 - 0x0801] = bank_b
        program = b"\x01\x08" + ram
        target = destination / f"{name}.prg"
        target.write_bytes(program)
        (destination / "bank-a-expected.bin").write_bytes(bank_a)
        (destination / "bank-b-expected.bin").write_bytes(bank_b)
        if multicolor:
            (destination / "screen.bin").write_bytes(image[2:8194])
            (destination / "bitmap.bin").write_bytes(image[8194:16194])
            (destination / "color-ram.bin").write_bytes(color_ram)
        else:
            (destination / "image.afl").write_bytes(image)
        (destination / "GoDot-LICENSE.txt").write_bytes((SOURCE_DIR.parent / "GoDot-LICENSE.txt").read_bytes())
        receipt = {
            "format": f"standalone PAL {'FLI' if multicolor else 'AFLI'} Virtual + Sprites PRG",
            "input": str(path.resolve()), "input_sha256": sha256(path.read_bytes()),
            "output": str(target.resolve()), "output_sha256": sha256(program), "bytes": len(program),
            "source_image_payload_sha256": sha256(image), "sprite_mask_sha256": sha256(mask),
            "source_mode": "fli" if multicolor else "afli", "source_image": manifest["image"],
            "background_color": manifest.get("backgroundColor") if multicolor else None,
            "color_ram_sha256": sha256(color_ram) if multicolor else None,
            "sprite_color": manifest["spriteColor"], "sprite_pixels": sum(byte.bit_count() for byte in mask),
            "player_sha256": sha256(player), "player_source": BASE["PLAYER_SOURCE"],
            "builder_sha256": sha256(Path(__file__).read_bytes()),
            "bootstrap_source_sha256": sha256(template.encode()), "bootstrap_sha256": sha256(bootstrap),
            "entry": "$2000", "frame_counter": "$02f0", "entry_nops": entry_nops,
            "image_origin": [32, 32], "image_raster_origin": 48, "image_height": 200,
            "valid_source_rect": [112, 0, 320, 200], "sprite_source_rect": [112, 0, 304, 200],
            "bank_switch_raster": 135, "bitmap_bank_split_y": 87, "sprite_bank_split_y": 88,
            "kernel_cycles_per_late_line": 14,
            "sprite_pointer_matrix": "max(0, source_y - 1) & 7", "sprite_row": "(source_y + 16) % 21",
            "banks": [
                {"address": "$4000", "expected": "bank-a-expected.bin", "sha256": sha256(bank_a), "bitmap_rows": [0, 88], "sprite_rows": [0, 89], "sprite_block_offsets": pointers_a},
                {"address": "$c000", "expected": "bank-b-expected.bin", "sha256": sha256(bank_b), "bitmap_rows": [80, 200], "sprite_rows": [87, 200], "sprite_block_offsets": pointers_b}
            ],
            "y_update_events": events,
            "patches": [{"address": f"${a:04x}", "original": o, "replacement": r, "purpose": p} for a,o,r,p in mode_patches],
            "validation": "Unverified until actual PAL VICE pixel, raster, and frame comparisons pass."
        }
        (destination / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        summaries.append({key: receipt[key] for key in ["input", "output", "output_sha256", "bytes", "sprite_pixels"]})
        print(f"Created {target} ({len(program)} bytes)", flush=True)
    (output / "build-receipt.json").write_text(json.dumps(summaries, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--entry-nops", type=int, default=12)
    parser.add_argument("inputs", nargs="+", type=Path)
    arguments = parser.parse_args()
    if not 0 <= arguments.entry_nops <= 64:
        parser.error("--entry-nops must be between 0 and 64")
    build(arguments.inputs, arguments.output, arguments.entry_nops)
