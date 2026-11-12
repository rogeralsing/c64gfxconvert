#!/usr/bin/env python3
"""Generate two large numeric strength views and their moving viewport model."""

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "build"
VIEW_WIDTH, VIEW_HEIGHT, PITCH = 80, 50, 128
COLUMN_PITCH = 64
WIDTH, HEIGHT = 40, 25
PALETTES = (
    (6, 11, 4, 12, 10),
    (6, 11, 4, 14, 5),
    (9, 11, 8, 12, 5),
    (5, 12, 8, 11, 9),
    (5, 12, 8, 4, 2),
)
PALETTE_NAMES = (
    "blue / dark gray / purple / medium gray / pink",
    "blue / dark gray / purple / light blue / green",
    "brown / dark gray / orange / medium gray / green",
    "green / medium gray / orange / dark gray / brown",
    "green / medium gray / orange / purple / red",
)
BACKGROUNDS = PALETTES[0][:-1]
FOREGROUNDS = PALETTES[0][1:]
INITIAL_PHASES = (0x0000, 0x4000, 0x8000, 0xC000)
PHASE_STEPS = (0x013D, 0x00B5, 0xFF6D, 0x0067)
WAVE_INITIAL = (0, 64)
WAVE_STEPS = (4, -6)
WAVE_AMPLITUDES = (4, 3)
WAVE_SPATIAL_STEPS = (8, 6)
PADDING = 0xCD
LOBES_A = (
    (12, 10, 7, 6, 1.0),
    (35, 10, 3, 3, 0.9),
    (64, 10, 10, 7, 0.95),
    (23, 31, 12, 9, 0.7),
    (52, 29, 5, 5, 1.05),
    (73, 35, 3, 4, 0.85),
    (7, 44, 3, 3, 0.8),
    (44, 47, 6, 4, 0.85),
    (78, 50, 8, 6, 0.55),
)
LOBES_B = (
    (7, 15, 3, 4, 0.9),
    (25, 8, 9, 6, 0.95),
    (49, 10, 4, 3, 1.0),
    (71, 19, 8, 10, 0.85),
    (17, 36, 6, 7, 1.0),
    (42, 30, 12, 9, 0.72),
    (59, 43, 3, 3, 0.9),
    (78, 48, 5, 4, 0.75),
    (36, 49, 4, 4, 0.8),
)


def make_map(peak, lobes):
    raw = [sum(weight * math.exp(-0.5 * (((x - cx) / sx) ** 2 + ((y - cy) / sy) ** 2))
               for cx, cy, sx, sy, weight in lobes)
           for y in range(VIEW_HEIGHT) for x in range(VIEW_WIDTH)]
    maximum = max(raw)
    return bytes(round(peak * value / maximum) for value in raw)


def padded_map(values):
    return b"".join(values[row * VIEW_WIDTH:(row + 1) * VIEW_WIDTH]
                    + bytes([PADDING]) * (PITCH - VIEW_WIDTH) for row in range(VIEW_HEIGHT))


def column_map(values):
    # B is read vertically, so each native column stores 50 contiguous values.
    return b"".join(bytes(values[y * VIEW_WIDTH + x] for y in range(VIEW_HEIGHT))
                    + bytes([PADDING]) * (COLUMN_PITCH - VIEW_HEIGHT) for x in range(VIEW_WIDTH))


def make_font():
    # The accepted metaball font: empty through solid, including its checkerboard.
    matrix = [[0]]
    offsets = ((0, 2), (3, 1))
    while len(matrix) < 8:
        size = len(matrix)
        matrix = [[4 * matrix[y % size][x % size] + offsets[y // size][x // size]
                   for x in range(size * 2)] for y in range(size * 2)]
    return bytes(sum(1 << (7 - x) for x in range(8) if matrix[y][x] < count)
                 for count in (*range(63), 64) for y in range(8))


def make_motion(span):
    return bytes(round(span / 2 + span / 2 * math.sin(math.tau * index / 256))
                 for index in range(256))


def make_wave(amplitude):
    return bytes(round(amplitude * math.sin(math.tau * index / 256)) & 255
                 for index in range(256))


def wave_state(frame):
    return tuple((initial + frame * step) & 255
                 for initial, step in zip(WAVE_INITIAL, WAVE_STEPS))


def warped_origins(cameras, waves=WAVE_INITIAL):
    (ax, _), (_, by) = cameras
    row_x = [max(0, min(40, ax + round(WAVE_AMPLITUDES[0] * math.sin(
        math.tau * ((waves[0] + y * WAVE_SPATIAL_STEPS[0]) & 255) / 256)))) for y in range(HEIGHT)]
    column_y = [max(0, min(25, by + round(WAVE_AMPLITUDES[1] * math.sin(
        math.tau * ((waves[1] + x * WAVE_SPATIAL_STEPS[1]) & 255) / 256)))) for x in range(WIDTH)]
    return row_x, column_y


def phase_state(frame):
    return tuple((initial + frame * step) & 65535
                 for initial, step in zip(INITIAL_PHASES, PHASE_STEPS))


def camera_positions(frame, motion_x, motion_y):
    ax, ay, bx, by = (value >> 8 for value in phase_state(frame))
    return (motion_x[ax], motion_y[ay]), (motion_x[bx], motion_y[by])


def compose(map_a, map_b, cameras, waves=WAVE_INITIAL):
    (_, ay), (bx, _) = cameras
    row_x, column_y = warped_origins(cameras, waves)
    return bytes(map_a[(ay + y) * VIEW_WIDTH + row_x[y] + x]
                 + map_b[(column_y[x] + y) * VIEW_WIDTH + bx + x]
                 for y in range(HEIGHT) for x in range(WIDTH))


def palette():
    lines = (ROOT.parents[1] / "palettes/colodore.vpl").read_text().splitlines()
    return [tuple(int(channel, 16) for channel in line.split()[:3])
            for line in lines if line.strip() and not line.startswith("#")]


def render(field, font, colors, palette_index=0):
    image = Image.new("RGB", (320, 200))
    pixels = image.load()
    ramp = PALETTES[palette_index]
    for cell, value in enumerate(field):
        bank = value >> 6
        foreground, background = colors[ramp[bank + 1]], colors[ramp[bank]]
        left, top = cell % WIDTH * 8, cell // WIDTH * 8
        for y in range(8):
            bits = font[(value & 63) * 8 + y]
            for x in range(8):
                pixels[left + x, top + y] = foreground if bits & (128 >> x) else background
    return image


def maps_preview(map_a, map_b, cameras):
    image = Image.new("RGB", (1320, 462), "#17191d")
    draw = ImageDraw.Draw(image)
    path = Path("/System/Library/Fonts/Menlo.ttc")
    label = ImageFont.truetype(str(path), 16) if path.exists() else ImageFont.load_default()
    for column, (name, values, peak, camera, color) in enumerate((
            ("A", map_a, 127, cameras[0], "#4bd4f5"),
            ("B", map_b, 128, cameras[1], "#ff80c8"))):
        left = 12 + column * 660
        draw.text((left, 12), f"VIEW {name}: 80x50, 0..{peak}; base viewport before waves", font=label, fill="white")
        sample = Image.frombytes("L", (VIEW_WIDTH, VIEW_HEIGHT),
                                 bytes(round(255 * value / peak) for value in values))
        image.paste(sample.convert("RGB").resize((640, 400), Image.Resampling.NEAREST), (left, 40))
        x, y = camera
        draw.rectangle((left + x * 8, 40 + y * 8,
                        left + (x + WIDTH) * 8 - 1, 40 + (y + HEIGHT) * 8 - 1),
                       outline=color, width=3)
    image.save(OUTPUT / "maps.png")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    map_a, map_b = make_map(127, LOBES_A), make_map(128, LOBES_B)
    font, motion_x, motion_y = make_font(), make_motion(40), make_motion(25)
    for name, values in (("map-a.bin", padded_map(map_a)), ("map-b.bin", column_map(map_b)),
                         ("map-a-logical.bin", map_a), ("map-b-logical.bin", map_b),
                         ("font.bin", font), ("motion-x.bin", motion_x), ("motion-y.bin", motion_y),
                         ("wave-x.bin", make_wave(WAVE_AMPLITUDES[0])),
                         ("wave-y.bin", make_wave(WAVE_AMPLITUDES[1])),
                         ("palettes.bin", bytes(color for ramp in PALETTES for color in ramp)),
                         ("color.bin", bytes(FOREGROUNDS[value >> 6] for value in range(256)))):
        (OUTPUT / name).write_bytes(values)
    for name, values, peak, lobes in (("map-a", map_a, 127, LOBES_A), ("map-b", map_b, 128, LOBES_B)):
        (OUTPUT / f"{name}.json").write_text(json.dumps({
            "width": VIEW_WIDTH, "height": VIEW_HEIGHT, "range": [0, peak], "lobes": lobes,
            "values": [list(values[row * VIEW_WIDTH:(row + 1) * VIEW_WIDTH]) for row in range(VIEW_HEIGHT)],
        }, indent=2) + "\n")
    (OUTPUT / "manifest.json").write_text(json.dumps({
        "views": {"width": VIEW_WIDTH, "height": VIEW_HEIGHT, "logical_bytes_each": 4000,
                  "padding_byte": PADDING,
                  "map_a": {"peak": 127, "lobes": LOBES_A, "native_layout": "row-major",
                            "native_pitch": PITCH, "native_bytes": PITCH * VIEW_HEIGHT},
                  "map_b": {"peak": 128, "lobes": LOBES_B, "native_layout": "column-major",
                            "native_pitch": COLUMN_PITCH, "native_bytes": COLUMN_PITCH * VIEW_WIDTH},
                  "formula": "raw=sum(w*exp(-0.5*(((x-cx)/sx)^2+((y-cy)/sy)^2))); round(peak*raw/max(raw over entire view))"},
        "viewport": {"width": WIDTH, "height": HEIGHT, "origin_x_range": [0, 40], "origin_y_range": [0, 25]},
        "motion": {"initial": INITIAL_PHASES, "steps": PHASE_STEPS,
                   "position": "X=round(20+20*sin(2*pi*hi(phase)/256)); Y=round(12.5+12.5*sin(2*pi*hi(phase)/256))",
                   "state_period_updates": 65536},
        "waves": {"initial": WAVE_INITIAL, "steps": WAVE_STEPS,
                  "amplitudes_cells": WAVE_AMPLITUDES, "spatial_phase_steps": WAVE_SPATIAL_STEPS,
                  "lookup": "round(amplitude*sin(2*pi*index/256)), signed two's complement bytes",
                  "native_lookup_bytes_each": 512,
                  "native_wrap": "two adjacent copies let unrolled row/column offsets wrap without updating the phase index",
                  "row_x": "clamp(ax+wave_x[(wave_phase_a+8*y)&255],0,40)",
                  "column_y": "clamp(by+wave_y[(wave_phase_b+6*x)&255],0,25)",
                  "state_period_updates": 128,
                  "edges": "clamp each row/column origin so every source sample remains in the logical map"},
        "strength": {"bytes": 1000, "range": [0, 255],
                     "formula": "strength[x,y]=A[row_x[y]+x,ay+y]+B[bx+x,column_y[x]+y]",
                     "history": "fully overwritten each frame; no fade, previous-frame addition or periodic reset",
                     "overflow": "A<=127 and B<=128 guarantee sum<=255; no carry can propagate between valid cells"},
        "projection": {"screen_code": "strength byte", "backgrounds": BACKGROUNDS,
                       "foregrounds": FOREGROUNDS, "font_coverage": [*range(63), 64],
                       "ramp": "four complete 64-value intervals between five selected colors",
                       "palettes": PALETTES, "palette_names": PALETTE_NAMES,
                       "control": "SPACE advances one palette on press; release before advancing again; wraps 4 to 0"},
        "preview": "host-preview.png is a model frame; native screen and VIC timing are verified separately",
    }, indent=2) + "\n")
    cameras = camera_positions(0, motion_x, motion_y)
    render(compose(map_a, map_b, cameras), font, palette()).resize(
        (640, 400), Image.Resampling.NEAREST).save(OUTPUT / "host-preview.png")
    maps_preview(map_a, map_b, cameras)
    print("Generated two 80x50 strength views, orthogonal read-time waves and the accepted metaball projection.")


if __name__ == "__main__":
    main()
