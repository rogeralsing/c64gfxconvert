#!/usr/bin/env python3
"""Generate a separate ECM sine-plasma font, tables and model preview."""

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "build"
WIDTH, HEIGHT = 40, 25
FOREGROUND = 6
BACKGROUNDS = (4, 10, 7, 1)
INITIAL_PHASES = (0x0000, 0x4000, 0x8000, 0xC000, 0x0000)
PHASE_STEPS = (0x013D, 0x00B5, 0xFF6D, 0x0067, 0x0071)


def bayer8():
    # Preserve the existing experiment's Bayer orientation in the new copy.
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
        sum(1 << (7 - x) for x in range(8) if ranks[y][x] < abs(64 - 2 * glyph))
        for glyph in range(64) for y in range(8)
    )


def make_sine():
    return bytes(round(39 * math.sin(math.tau * index / 256)) & 255
                 for index in range(256))


def phase_state(frame):
    return tuple((initial + frame * step) & 65535
                 for initial, step in zip(INITIAL_PHASES, PHASE_STEPS))


def phase_field(frame, sine):
    a, b, c, d, e = (value >> 8 for value in phase_state(frame))
    columns = [(sine[(5 * x + a) & 255] + sine[(13 * x + b) & 255] + e) & 255
               for x in range(WIDTH)]
    rows = [(sine[(7 * y + c) & 255] + sine[(17 * y + d) & 255]) & 255
            for y in range(HEIGHT)]
    return bytes((column + row) & 255 for row in rows for column in columns)


def palette():
    lines = (ROOT.parents[1] / "palettes/colodore.vpl").read_text().splitlines()
    return [tuple(int(channel, 16) for channel in line.split()[:3])
            for line in lines if line.strip() and not line.startswith("#")]


def render(screen, font, colors):
    image = Image.new("RGB", (320, 200))
    pixels = image.load()
    for cell, code in enumerate(screen):
        left, top = cell % WIDTH * 8, cell // WIDTH * 8
        foreground, background = colors[FOREGROUND], colors[BACKGROUNDS[code >> 6]]
        for y in range(8):
            bits = font[(code & 63) * 8 + y]
            for x in range(8):
                pixels[left + x, top + y] = foreground if bits & (128 >> x) else background
    return image


def make_ramp(font, colors):
    sheet = Image.new("RGB", (552, 336), "#17191d")
    draw = ImageDraw.Draw(sheet)
    font_path = Path("/System/Library/Fonts/Menlo.ttc")
    label = ImageFont.truetype(str(font_path), 14) if font_path.exists() else ImageFont.load_default()
    for bank, name in enumerate(("PURPLE", "PINK", "YELLOW", "WHITE")):
        top = 12 + bank * 80
        draw.text((12, top), f"{bank*64:3d}-{bank*64+63:3d}: BLUE / {name} / BLUE", font=label, fill="white")
        for glyph in range(64):
            code = bank * 64 + glyph
            background = colors[BACKGROUNDS[bank]]
            for y in range(8):
                bits = font[glyph * 8 + y]
                for x in range(8):
                    color = colors[FOREGROUND] if bits & (128 >> x) else background
                    for repeat in range(4):
                        sheet.putpixel((12 + glyph * 8 + x, top + 27 + y + repeat * 8), color)
    sheet.save(OUTPUT / "phase-ramp.png")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    font, sine = make_font(), make_sine()
    (OUTPUT / "font.bin").write_bytes(font)
    (OUTPUT / "sine.bin").write_bytes(sine)
    (OUTPUT / "manifest.json").write_text(json.dumps({
        "mode": "VIC-II ECM, 40x25 cells, two screen buffers, fixed Color RAM",
        "foreground": FOREGROUND,
        "backgrounds": BACKGROUNDS,
        "font": {"glyphs": 64, "bytes": len(font),
                 "foreground_coverage": [abs(64 - 2 * glyph) for glyph in range(64)],
                 "dither": "nested 8x8 Bayer masks; full foreground at bank boundaries, empty at midpoint"},
        "sine": {"entries": len(sine), "formula": "round(39*sin(2*pi*i/256)), stored as signed bytes"},
        "phase_accumulators": {"bits": 16, "initial": INITIAL_PHASES, "steps": PHASE_STEPS,
                               "state_period_updates": 65536,
                               "advance": "add step modulo 65536 after each presented frame; use high byte for lookups"},
        "field": {"columns": "X[x]=(S[(5*x+hi(A))&255]+S[(13*x+hi(B))&255]+hi(E))&255",
                  "rows": "Y[y]=(S[(7*y+hi(C))&255]+S[(17*y+hi(D))&255])&255",
                  "screen_code": "(X[x]+Y[y])&255",
                  "history": "fresh phase field each frame; modulo addition, no retained brightness buffer"},
        "reference": "Spindle ECM plasma row-difference technique, Linus Akesson; separate adaptation of the existing ECM experiment",
        "preview": "host-preview.png is a model frame; native cadence and VIC pixels are verified separately",
    }, indent=2) + "\n")
    colors = palette()
    render(phase_field(0, sine), font, colors).resize((640, 400), Image.Resampling.NEAREST).save(
        OUTPUT / "host-preview.png")
    make_ramp(font, colors)
    print("Generated separate ECM plasma: 64 cyclic glyphs, 256 signed sine values, fixed blue foreground.")


if __name__ == "__main__":
    main()
