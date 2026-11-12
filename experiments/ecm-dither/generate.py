#!/usr/bin/env python3
"""Generate a progressive ECM font and a native 40x25 test screen."""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "build"
BACKGROUNDS = (0, 1, 6, 14)


def bayer8():
    matrix = [[0]]
    offsets = ((0, 2), (3, 1))
    while len(matrix) < 8:
        size = len(matrix)
        matrix = [
            [4 * matrix[y % size][x % size] + offsets[y // size][x // size]
             for x in range(size * 2)]
            for y in range(size * 2)
        ]
    return matrix


def make_font():
    ranks = bayer8()
    return bytes(
        sum(1 << (7 - x) for x in range(8) if ranks[y][x] < count)
        for count in range(33)
        for y in range(8)
    )


def make_screen():
    screen = bytearray(1000)
    colors = bytearray([1] * 1000)

    def cell(x, y, glyph, background, foreground):
        position = y * 40 + x
        screen[position] = glyph | (background << 6)
        colors[position] = foreground

    # The first two strips display every glyph, then reuse it with swapped colors.
    for y in range(1, 5):
        for count in range(33):
            cell(count + 3, y, count, 0, 1)
    for y in range(6, 10):
        for x in range(33):
            cell(x + 3, y, 32 - x, 1, 0)

    # A tile changes polarity above 50%; no inverse glyphs are stored.
    for y0, y1, background_a, background_b in ((12, 17, 0, 1), (19, 24, 2, 3)):
        for x in range(40):
            level = (x * 64 + 19) // 39
            swapped = level > 32
            glyph = 64 - level if swapped else level
            background = background_b if swapped else background_a
            foreground = BACKGROUNDS[background_a if swapped else background_b]
            for y in range(y0, y1):
                cell(x, y, glyph, background, foreground)
    return bytes(screen), bytes(colors)


def palette():
    lines = (ROOT.parent.parent / "palettes/colodore.vpl").read_text().splitlines()
    return [tuple(int(channel, 16) for channel in line.split()[:3])
            for line in lines if line.strip() and not line.startswith("#")]


def tile(font, glyph, foreground, background, scale=1):
    image = Image.new("RGB", (8, 8), background)
    for y, bits in enumerate(font[glyph * 8:glyph * 8 + 8]):
        for x in range(8):
            if bits & (0x80 >> x):
                image.putpixel((x, y), foreground)
    return image.resize((8 * scale, 8 * scale), Image.Resampling.NEAREST)


def native_preview(font, screen, colors, rgb):
    image = Image.new("RGB", (320, 200))
    for index, code in enumerate(screen):
        image.paste(tile(font, code & 63, rgb[colors[index]], rgb[BACKGROUNDS[code >> 6]]),
                    ((index % 40) * 8, (index // 40) * 8))
    image.save(OUTPUT / "screen.png")


def font_sheet(font, rgb):
    image = Image.new("RGB", (1120, 630), "#17191d")
    draw = ImageDraw.Draw(image)
    font_path = Path("/System/Library/Fonts/Menlo.ttc")
    label = ImageFont.truetype(str(font_path), 15) if font_path.exists() else ImageFont.load_default()
    title = ImageFont.truetype(str(font_path), 23) if font_path.exists() else label
    draw.text((32, 26), "ECM DITHER / 33 GLYPHS / 512 BYTES", font=title, fill="white")
    draw.text((32, 66), "One added pixel per glyph. Last glyph: 50% checkerboard.", font=label, fill="#b4b9c2")

    for count in range(33):
        x = 32 + (count % 17) * 62
        y = 110 + (count // 17) * 104
        image.paste(tile(font, count, rgb[1], rgb[0], 6), (x, y))
        draw.text((x, y + 55), f"{count:02d}/64", font=label, fill="#d9dde5")

    for y, a, b, heading in ((362, 0, 1, "65 coverage levels: black to white"),
                              (492, 6, 14, "Same font: blue to light blue")):
        draw.text((32, y - 30), heading, font=label, fill="white")
        for level in range(65):
            swapped = level > 32
            glyph = 64 - level if swapped else level
            foreground, background = (a, b) if swapped else (b, a)
            sample = tile(font, glyph, rgb[foreground], rgb[background], 2)
            for dy in range(0, 48, 16):
                image.paste(sample, (32 + level * 16, y + dy))
        for x, text in ((32, "0%"), (520, "50%"), (1030, "100%")):
            draw.text((x, y + 55), text, font=label, fill="#b4b9c2")
    draw.text((32, 594), "Color swap changes dither phase at 50%. Coverage steps: 1/64 = 1.5625%.",
              font=label, fill="#b4b9c2")
    image.save(OUTPUT / "font-sheet.png")


def main():
    OUTPUT.mkdir(exist_ok=True)
    compact_font = make_font()
    font = compact_font + bytes(512 - len(compact_font))
    screen, colors = make_screen()
    (OUTPUT / "font-33.bin").write_bytes(compact_font)
    (OUTPUT / "font.bin").write_bytes(font)
    (OUTPUT / "screen.bin").write_bytes(screen)
    (OUTPUT / "color.bin").write_bytes(colors)
    rgb = palette()
    native_preview(font, screen, colors, rgb)
    font_sheet(font, rgb)
    manifest = {
        "active_glyphs": 33,
        "font_bytes": len(font),
        "compact_font_bytes": len(compact_font),
        "unused_glyphs": 31,
        "foreground_pixels_per_glyph": list(range(33)),
        "coverage_levels_with_color_swap": 65,
        "background_registers": dict(zip(("$d021", "$d022", "$d023", "$d024"), BACKGROUNDS)),
        "dither": "8x8 Bayer, fixed tile origin, nested masks from 0 through 32 set bits",
        "polarity_note": "Color swapping changes dither phase at the midpoint; it preserves density, not pixel nesting.",
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Generated {len(compact_font) // 8} active glyphs; {len(font)}-byte ECM font; 65 coverage levels.")


if __name__ == "__main__":
    main()
