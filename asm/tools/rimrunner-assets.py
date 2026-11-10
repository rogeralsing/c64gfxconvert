#!/usr/bin/env python3
"""Decode a paused C64 memory capture into raw graphics and PNG previews.

The capture must contain ram.bin (65536 bytes), vic.bin (64), color.bin
(1024), and cia2.bin (16). Supply charrom.bin (4096) when VIC-visible
character ROM is needed. This is a single-state decoder, not a raster tracer.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from PIL import Image


SIZES = {"ram.bin": 65536, "vic.bin": 64, "color.bin": 1024, "cia2.bin": 16}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def load_palette(path):
    entries = []
    for line in path.read_text().splitlines():
        fields = line.split("#", 1)[0].split()
        if fields:
            entries.append(tuple(int(value, 16) for value in fields[:3]))
    if len(entries) != 16 or any(len(color) != 3 for color in entries):
        raise ValueError("Expected a VICE palette containing exactly 16 RGB colors.")
    return entries


def indexed_image(width, height, pixels, palette):
    image = Image.new("P", (width, height))
    image.putpalette([value for color in palette for value in color] + [0] * (768 - 48))
    image.putdata(pixels)
    return image


def glyph_pixels(data, background, foreground, multicolor_palette=None):
    pixels = []
    for value in data:
        if multicolor_palette is None:
            pixels.extend(foreground if value & (0x80 >> x) else background for x in range(8))
        else:
            for shift in (6, 4, 2, 0):
                color = multicolor_palette[(value >> shift) & 3]
                pixels.extend((color, color))
    return pixels


def glyph_sheet(charset, palette, background, foreground, multicolor_palette=None):
    image = indexed_image(16 * 9, 16 * 9, [background] * (16 * 9) ** 2, palette)
    for character in range(256):
        pixels = glyph_pixels(charset[character * 8:character * 8 + 8], background,
                              foreground, multicolor_palette)
        tile = indexed_image(8, 8, pixels, palette)
        image.paste(tile, ((character % 16) * 9, (character // 16) * 9))
    return image


def extract(capture, output, palette_path):
    capture = capture.resolve()
    output = output.resolve()
    payloads = {name: (capture / name).read_bytes() for name in SIZES}
    for name, size in SIZES.items():
        if len(payloads[name]) != size:
            raise ValueError(f"{name} must contain exactly {size} bytes.")
    rom_path = capture / "charrom.bin"
    rom = rom_path.read_bytes() if rom_path.exists() else None
    if rom is not None:
        if len(rom) != 4096:
            raise ValueError("charrom.bin must contain exactly 4096 bytes.")
        payloads["charrom.bin"] = rom
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Output directory must be empty: {output}")

    ram, vic, color, cia = (payloads[name] for name in SIZES)
    palette = load_palette(palette_path)
    pins = (cia[0] | (~cia[2] & 255)) & 3
    bank = (~pins & 3) * 0x4000
    screen_address = bank + ((vic[0x18] >> 4) & 15) * 0x400
    charset_address = bank + ((vic[0x18] >> 1) & 7) * 0x800
    bitmap_address = bank + (vic[0x18] & 8) * 0x400
    rom_reads = set()

    def read_vic(address, size):
        result = bytearray()
        for location in range(address, address + size):
            location &= 0xffff
            if (location & 0x7000) == 0x1000:
                if rom is None:
                    raise ValueError(f"VIC fetch at ${location:04x} requires charrom.bin; RAM is not equivalent.")
                result.append(rom[location & 0xfff])
                rom_reads.add(location)
            else:
                result.append(ram[location])
        return bytes(result)

    bitmap_mode = bool(vic[0x11] & 0x20)
    multicolor_mode = bool(vic[0x16] & 0x10)
    extended_mode = bool(vic[0x11] & 0x40)
    if extended_mode and (bitmap_mode or multicolor_mode):
        raise ValueError("Capture uses an invalid/unsupported ECM combination; capture a stable raster region.")
    mode = ("multicolor bitmap" if multicolor_mode else "hires bitmap") if bitmap_mode else (
        "extended color characters" if extended_mode else
        "multicolor characters" if multicolor_mode else "standard characters")

    charset = read_vic(charset_address, 2048)
    screen = read_vic(screen_address, 1000)
    colors = bytes(value & 15 for value in color[:1000])
    background = vic[0x21] & 15
    foreground = next((value for value, _ in Counter(colors).most_common()
                       if value != background), 1)
    generic_mc = [background, vic[0x22] & 15, vic[0x23] & 15, foreground & 7]
    files = {"charset.bin": charset, "screen.bin": screen, "color.bin": colors}
    images = {
        "charset-hires.png": glyph_sheet(charset, palette, background, foreground),
        "charset-multicolor.png": glyph_sheet(charset, palette, background, foreground, generic_mc),
    }

    bitmap = read_vic(bitmap_address, 8000) if bitmap_mode else None
    if bitmap is not None:
        files["bitmap.bin"] = bitmap
    pixels = [background] * 64000
    for cell in range(1000):
        code, local = screen[cell], colors[cell]
        if bitmap_mode:
            tile = bitmap[cell * 8:cell * 8 + 8]
            if multicolor_mode:
                tile_pixels = glyph_pixels(tile, background, local,
                                            [background, code >> 4, code & 15, local])
            else:
                tile_pixels = glyph_pixels(tile, code & 15, code >> 4)
        else:
            character = code & 63 if extended_mode else code
            tile = charset[character * 8:character * 8 + 8]
            cell_background = vic[0x21 + (code >> 6)] & 15 if extended_mode else background
            if multicolor_mode and local & 8:
                tile_pixels = glyph_pixels(tile, background, local & 7,
                                            [background, vic[0x22] & 15, vic[0x23] & 15, local & 7])
            else:
                tile_pixels = glyph_pixels(tile, cell_background, local)
        x, y = (cell % 40) * 8, (cell // 40) * 8
        for row in range(8):
            pixels[(y + row) * 320 + x:(y + row) * 320 + x + 8] = tile_pixels[row * 8:row * 8 + 8]
    images["background-single-state.png"] = indexed_image(320, 200, pixels, palette)

    sprites = []
    sheet = Image.new("RGBA", (4 * 32, 2 * 29), (0, 0, 0, 0))
    pointers = read_vic(screen_address + 0x3f8, 8)
    for number, pointer in enumerate(pointers):
        address = bank + pointer * 64
        data = read_vic(address, 64)
        local = vic[0x27 + number] & 15
        multicolor = bool(vic[0x1c] & (1 << number))
        sprite_palette = [None, vic[0x25] & 15, local, vic[0x26] & 15] if multicolor else [None, local]
        image = Image.new("RGBA", (24, 21), (0, 0, 0, 0))
        sprite_pixels = image.load()
        for y in range(21):
            bits = int.from_bytes(data[y * 3:y * 3 + 3], "big")
            for x in range(12 if multicolor else 24):
                value = (bits >> (22 - x * 2)) & 3 if multicolor else (bits >> (23 - x)) & 1
                index = sprite_palette[value]
                if index is not None:
                    sprite_pixels[x * (2 if multicolor else 1), y] = (*palette[index], 255)
                    if multicolor:
                        sprite_pixels[x * 2 + 1, y] = (*palette[index], 255)
        stem = f"sprite-{number}-${address:04x}"
        files[stem + ".bin"] = data
        images[stem + ".png"] = image
        sheet.paste(image, ((number % 4) * 32 + 4, (number // 4) * 29 + 4))
        sprites.append({"number": number, "pointer": pointer, "address": f"${address:04x}",
                        "x": vic[number * 2] + (((vic[0x10] >> number) & 1) * 256),
                        "y": vic[number * 2 + 1],
                        "enabled": bool(vic[0x15] & (1 << number)), "multicolor": multicolor,
                        "palette_indices": sprite_palette, "x_expanded": bool(vic[0x1d] & (1 << number)),
                        "y_expanded": bool(vic[0x17] & (1 << number)),
                        "foreground_priority": not bool(vic[0x1b] & (1 << number)),
                        "raw_bytes": 64, "picture_bytes": 63,
                        "raw_file": stem + ".bin", "png_file": stem + ".png"})
    images["sprites-observed.png"] = sheet
    manifest = {
        "format": "C64 single-state graphics extraction v1",
        "capture": str(capture), "mode": mode,
        "inputs": {name: {"bytes": len(data), "sha256": sha256(data)} for name, data in payloads.items()},
        "addresses": {"vic_bank": f"${bank:04x}", "screen": f"${screen_address:04x}",
                      "charset": f"${charset_address:04x}", "bitmap": f"${bitmap_address:04x}" if bitmap_mode else None},
        "vic_registers": list(vic), "cia2_registers": list(cia),
        "palette": {"source": str(palette_path.resolve()), "sha256": sha256(palette_path.read_bytes()),
                    "rgb": palette, "background_index": background,
                    "hires_glyph_preview_foreground": foreground, "multicolor_glyph_preview_indices": generic_mc},
        "sprites": sprites, "character_rom_fetch_count": len(rom_reads),
        "limitations": [
            "One paused state; raster changes, other level graphics, and unseen animation frames are not reconstructed.",
            "Background is the logical 320x200 cell grid, without fine scroll, border masking, sprites, or raster splits.",
            "Glyph sheets use generic observed palettes. Actual character colors belong to each screen cell.",
            "Sprite PNGs preserve 24x21 source dimensions; hardware expansion and screen position are recorded separately.",
            "Observed sprite pointers include disabled slots and may contain non-sprite data.",
            "Extraction records original game data and does not grant a license to redistribute it.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (output / name).write_bytes(data)
    for name, image in images.items():
        image.save(output / name)
    manifest["outputs"] = {path.name: {"bytes": path.stat().st_size, "sha256": sha256(path.read_bytes())}
                           for path in sorted(output.iterdir()) if path.is_file()}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output), "mode": mode,
                      "addresses": manifest["addresses"], "observed_sprites": 8,
                      "enabled_sprites": sum(sprite["enabled"] for sprite in sprites)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--palette", type=Path, default=Path(__file__).resolve().parents[2] / "palettes/colodore.vpl")
    arguments = parser.parse_args()
    extract(arguments.capture, arguments.output, arguments.palette)
