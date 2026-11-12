#!/usr/bin/env python3
"""Reserve a shared Color RAM channel inside the supplied black sphere opening."""

from collections import Counter, deque
from itertools import combinations
from pathlib import Path


PALETTE = [0, 0, 0, 6, 4, 10, 15, 1, 10, 4, 6, 0, 0, 0, 0, 0]


def opening(bitmap, screen, colors, background, center):
    pixels, selectors = [], []
    for y in range(200):
        row, codes = bytearray(), bytearray()
        for x in range(160):
            cell = (y // 8) * 40 + x // 4
            code = (bitmap[cell * 8 + y % 8] >> (6 - 2 * (x % 4))) & 3
            row.append((background, screen[cell] >> 4, screen[cell] & 15, colors[cell])[code])
            codes.append(code)
        pixels.append(row)
        selectors.append(codes)
    seed = (center[0] // 2, center[1])
    if pixels[seed[1]][seed[0]] != 0:
        raise ValueError("The disco opening must have a black center")
    mask = [bytearray(160) for _ in range(200)]
    mask[seed[1]][seed[0]] = 1
    queue = deque([seed])
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < 160 and 0 <= ny < 200 and not mask[ny][nx] and pixels[ny][nx] == 0:
                mask[ny][nx] = 1
                queue.append((nx, ny))
    return selectors, mask


def prepare(bitmap, bitmap_b, screen, screen_b, colors, background, center):
    if background != 0:
        raise ValueError("The disco opening requires a static black background color")
    fields = [bytearray(bitmap), bytearray(bitmap_b)]
    screens = [bytearray(screen), bytearray(screen_b)]
    decoded = [opening(data, attributes, colors, background, center)
               for data, attributes in zip(fields, (screen, screen_b))]
    cells = []
    for cell in range(1000):
        left, top = (cell % 40) * 4, (cell // 40) * 8
        if any(mask[y][x] for _, mask in decoded
               for y in range(top, top + 8) for x in range(left, left + 4)):
            cells.append(cell)
    if not cells:
        raise ValueError("No Color RAM cells intersect the disco opening")
    palette_file = Path(__file__).resolve().parents[2] / "palettes" / "colodore.vpl"
    rgb = [tuple(int(value, 16) for value in line.split()[:3])
           for line in palette_file.read_text().splitlines()
           if line.strip() and not line.startswith("#")]

    def distance(first, second):
        return sum((a - b) ** 2 for a, b in zip(rgb[first], rgb[second]))

    def retained_colors(histogram):
        nonblack = sorted(color for color in histogram if color != 0)
        choices = combinations(nonblack, min(2, len(nonblack)))
        best = None
        for kept in choices:
            if 1 in nonblack and 1 not in kept:
                continue
            replacements = {0: 0}
            for color in nonblack:
                if color in kept:
                    replacements[color] = color
                else:
                    # White belongs to the contour: neither remove nor create it.
                    targets = (0,) + tuple(value for value in kept if value != 1)
                    replacements[color] = min(targets, key=lambda value: (distance(color, value), value))
            changed = sum(count for color, count in histogram.items() if replacements[color] != color)
            error = sum(count * distance(color, replacements[color]) for color, count in histogram.items())
            score = changed, error, kept
            if best is None or score < best[0]:
                best = score, kept, replacements
        return best[1], best[2]

    original_colors = colors
    colors = bytearray(colors)
    recolored = [0, 0]
    for cell in cells:
        colors[cell] = 0
        left, top = (cell % 40) * 4, (cell // 40) * 8
        for phase, (data, attributes, (codes, mask)) in enumerate(zip(fields, screens, decoded)):
            original_palette = (background, attributes[cell] >> 4, attributes[cell] & 15, original_colors[cell])
            histogram = Counter(original_palette[codes[y][x]]
                                for y in range(top, top + 8) for x in range(left, left + 4)
                                if not mask[y][x])
            kept, replacements = retained_colors(histogram)
            first = kept[0] if kept else 0
            second = kept[1] if len(kept) > 1 else 0
            attributes[cell] = (first << 4) | second
            for y in range(top, top + 8):
                for x in range(left, left + 4):
                    if mask[y][x]:
                        code = 3
                    else:
                        original = original_palette[codes[y][x]]
                        replacement = replacements[original]
                        recolored[phase] += replacement != original
                        code = 0 if replacement == 0 else 1 if replacement == first else 2
                    shift = 6 - 2 * (x % 4)
                    offset = cell * 8 + y % 8
                    data[offset] = (data[offset] & (255 ^ (3 << shift))) | (code << shift)
    metadata = {"cells": cells, "palette": PALETTE, "phase_count": 16,
                "tick_divider": 4, "selector": 3, "color_layout": "uniform",
                "coverage": "full_opening", "edge_recolored_multicolor_pixels": recolored,
                "edge_recolored_pixels": [count * 2 for count in recolored],
                "white_contour_preserved": True}
    lines = [
        "// Color changes are shared by both MCI fields and confined to the opening.",
        f".label discoCellCount = {len(cells)}",
        "updateDiscoColors:", "    lda rasterTick", "    and #3", "    cmp #1",
        "    beq !update+", "    rts", "!update:", "    inc discoPhase",
        "    lda discoPhase", "    and #15", "    sta discoPhase", "    tax",
        "    lda discoPalette,x",
    ]
    lines.extend(f"    sta ${0xd800 + cell:04x}" for cell in cells)
    lines += ["discoColorsUpdated:", "    rts", "discoPhase: .byte 15", ".align $100",
              "discoPalette: .byte " + ",".join(map(str, PALETTE))]
    return (bytes(fields[0]), bytes(fields[1]), bytes(screens[0]), bytes(screens[1]),
            bytes(colors), metadata, "\n".join(lines) + "\n")
