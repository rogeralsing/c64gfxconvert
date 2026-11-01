#!/usr/bin/env python3
"""Build a separate experimental eight-sprite PAL AFLI display."""

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
    (0x0ef4, "20 00 84", "20 90 20", "enter the custom fourteen-cycle sprite AFLI kernel"),
    (0x0efa, "ad 16 d0 49 01 8d 16 d0", "a9 30 8d 11 d0 ea ea ea",
     "replace the X-scroll toggle with the vertical-border postlude"),
    (0x0f0b, "2f", "2b", "re-arm the earlier stable IRQ"),
]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def scanline_kernel():
    lines = []
    events = []
    for raster in range(49, 248):
        row = (raster - 32) % 21
        control = 0x38 | (raster & 7)
        matrix = 0x08 | (((raster - 48) & 7) << 4)
        lines.append(f"row{raster}:")
        if row == 0:
            lines.append(f"    ldx #{(raster + 20) & 255}")
        elif row in range(1, 16, 2):
            next_control = 0x70 if raster == 247 else 0x38 | ((raster + 1) & 7)
            lines.append(f"    ldy #${next_control:02x}")
        elif row in range(2, 17, 2):
            sprite = (row - 2) // 2
            address = 0xd001 + sprite * 2
            lines.append(f"    stx ${address:04x}")
            events.append({"raster": raster, "sprite": sprite, "address": f"${address:04x}",
                           "new_y": (raster - row + 20) & 255})
        else:
            lines.append("    nop")
        lines.extend([f"    lda #${matrix:02x}", "    sta $d018"])
        if row in range(2, 17, 2):
            lines.append("    sty $d011")
        else:
            lines.extend([f"    lda #${control:02x}", "    sta $d011"])
    # The last row's otherwise-unused Y preload supplies $70 without taking
    # any additional cycles in the proven image kernel. At R248c11, blank the
    # bitmap before its first visible pixel, then black each active sprite
    # before its X coordinate. Clearing D015 alone cannot stop active DMA.
    lines.extend(["rowsEnd:", "    sty $d011", "    lda #0"])
    lines.extend(f"    sta ${0xd027 + sprite:04x}" for sprite in range(8))
    lines.extend(["    sta $d015", "    lda #31"])
    lines.extend(f"    sta ${0xd001 + sprite * 2:04x}" for sprite in range(8))
    # Keep new sprite DMA disabled through raster287 (also low-byte Y31).
    # Restore the next frame only after the raster high bit wraps to zero.
    lines.extend(["waitHighRaster:", "    bit $d011", "    bpl waitHighRaster",
                  "waitFrameWrap:", "    bit $d011", "    bmi waitFrameWrap", "    lda #1"])
    lines.extend(f"    sta ${0xd027 + sprite:04x}" for sprite in range(8))
    lines.extend(["    lda #$ff", "    sta $d015", "    rts"])
    return "\n".join(lines), events


def build(inputs, output, entry_nops):
    source_dir = Path(__file__).resolve().parent
    root = source_dir.parent.parent
    player = (root / "ifli-viewer/diashow_eng.prg").read_bytes()
    if sha256(player) != PLAYER_SHA256:
        raise ValueError("The pinned GoDot engine changed.")
    images = []
    for path in inputs:
        image = path.read_bytes()
        if len(image) != 16385 or image[:2] != b"\x00\x40":
            raise ValueError(f"{path.name}: expected a 16385-byte AFLI-editor image.")
        screens = bytearray(image[2:8194])
        bitmap = bytearray(image[8194:16194])
        for bank in range(8):
            for tile_row in range(25):
                start = bank * 1024 + tile_row * 40
                screens[start:start + 14] = bytes(14)
            screens[bank * 1024 + 1016:bank * 1024 + 1024] = bytes([0xfd] * 8)
        for tile_row in range(25):
            bitmap[tile_row * 320:tile_row * 320 + 112] = bytes(112)
        checker = bytes(value for row in range(21)
                        for value in ([0xf0] * 3 if (row // 3) % 2 == 0 else [0x0f] * 3)) + b"\x00"
        bank = screens + bitmap + checker + bytes(128)
        assert len(bank) == 16384
        images.append((image, bank))
    if len({path.stem for path in inputs}) != len(inputs):
        raise ValueError("Duplicate output names.")
    output.mkdir(parents=True, exist_ok=False)
    (output / "GoDot-LICENSE.txt").write_bytes((source_dir.parent / "GoDot-LICENSE.txt").read_bytes())
    kernel, events = scanline_kernel()
    template = (source_dir / "boot.asm").read_text()
    assembly = template.replace("    // ENTRY_DELAY", "    nop\n" * entry_nops).replace("    // GENERATED_SCANLINES", kernel)
    assembled_source = output / "boot-rendered.asm"
    assembled_source.write_text(assembly)
    subprocess.run([str(Path.home() / ".local/bin/kickass"), str(assembled_source.resolve()),
                    "-o", str(output.resolve() / "boot.prg"), "-odir", str(output.resolve()),
                    "-symbolfile"], check=True)
    bootstrap = (output / "boot.prg").read_bytes()
    if bootstrap[:2] != b"\x00\x20" or 0x2000 + len(bootstrap) - 2 >= 0x4000:
        raise ValueError("Bootstrap/kernel overlaps graphics.")
    patched = bytearray(player[2:])
    patched[5:9] = b"8192"
    for address, original, replacement, purpose in PATCHES:
        start = address - 0x0801
        old = bytes.fromhex(original)
        if patched[start:start + len(old)] != old:
            raise ValueError(f"Pinned instruction mismatch ${address:04x}")
        patched[start:start + len(old)] = bytes.fromhex(replacement)
    receipts = []
    for path, (image, bank) in zip(inputs, images):
        ram = bytearray(0xc38c - 0x0801)
        ram[:len(patched)] = patched
        start = 0x2000 - 0x0801
        ram[start:start + len(bootstrap) - 2] = bootstrap[2:]
        ram[0x4000 - 0x0801:0x8000 - 0x0801] = bank
        # The original backward relocation copies the active 16,292-byte payload.
        ram[0x83e8 - 0x0801:0xc38c - 0x0801] = bank[:0x3fa4]
        program = b"\x01\x08" + ram
        target = output / f"{path.stem}.prg"
        target.write_bytes(program)
        (output / f"{path.stem}-expected-bank.bin").write_bytes(bank)
        receipts.append({"input": str(path.resolve()), "input_sha256": sha256(image),
                         "output": str(target.resolve()), "output_sha256": sha256(program),
                         "bytes": len(program), "expected_bank": f"{path.stem}-expected-bank.bin",
                         "expected_bank_sha256": sha256(bank)})
        print(f"Created {target} ({len(program)} bytes)")
    receipt = {
        "format": "experimental PAL eight-sprite AFLI PRG",
        "player_sha256": PLAYER_SHA256, "player_source": PLAYER_SOURCE,
        "bootstrap_source_sha256": sha256(template.encode()), "bootstrap_sha256": sha256(bootstrap),
        "builder_sha256": sha256(Path(__file__).read_bytes()), "entry_nops": entry_nops,
        "entry": "$2000", "idle": "$2088", "nmi": "$208b", "irq_trampoline": "$2090",
        "raster_preamble": "$2200", "rows_start": "$2800", "frame_counter": "$02f0",
        "image_raster_origin": 48, "image_height": 200,
        "display_mask": {"left_hires_pixels": 112, "visible_image_width": 208},
        "kernel": {"first_full_badline": 48, "late_badlines": [49, 247], "cpu_cycles_per_late_line": 14},
        "end_of_image": {"black_from_raster": 248, "d011": "$70",
                         "sprite_colors": 0, "new_sprite_dma": False,
                         "restore_after_raster_wrap": True},
        "sprites": {"count": 8, "x_source": [112 + 24*i for i in range(8)],
                    "x_vic": [136 + 24*i for i in range(8)], "x_msb": 224,
                    "initial_y": 31, "preamble_y": 52, "initial_visible_raster": 32,
                    "width": 24, "height": 21, "color": 1, "front": True,
                    "multicolor": False, "x_expand": False, "y_expand": False,
                    "checker_block": [4, 3], "checker_rows_hex": ["f0f0f0" if (r//3)%2 == 0 else "0f0f0f" for r in range(21)],
                    "pointer": 253, "data_addresses": ["$7f40", "$ff40"],
                    "pointer_table_offsets": [bank*1024 + 1016 for bank in range(8)],
                    "y_update_events": events},
        "patches": [{"address": f"${a:04x}", "original": o, "replacement": r, "purpose": p}
                    for a,o,r,p in PATCHES], "files": receipts,
        "timing_reference": "https://codebase64.net/doku.php?id=magazines%3Adiscovery3",
        "validation": "Experimental; actual VICE timing and pixels must be verified before claiming success."
    }
    (output / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--entry-nops", type=int, default=12)
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args()
    if not 0 <= args.entry_nops <= 64:
        parser.error("--entry-nops must be in 0..64")
    build(args.inputs, args.output, args.entry_nops)
