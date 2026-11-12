#!/usr/bin/env python3
"""Generate numerical ball data and ECM projection tables for a byte field."""

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from generate import bayer8, make_font, palette, tile


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "build" / "metaballs"
WIDTH, HEIGHT = 40, 25
KERNEL_SIZE, RADIUS, PEAK = 25, 12, 4
PRIMARY_PERIOD = 128
PRIMARY_STEP = 3
DRIFT_X_PERIOD = 251
DRIFT_Y_PERIOD = 239
MOTION_PERIOD = math.lcm(PRIMARY_PERIOD, DRIFT_X_PERIOD, DRIFT_Y_PERIOD)
PREVIEW_FRAMES = 256
PAL_CLOCK = 985248
CLEAR_INTERVAL_SECONDS = 10
PREVIEW_UPDATE_CYCLES = 3 * 312 * 63
BACKGROUNDS = (6, 4, 10, 7)
FOREGROUNDS = (4, 10, 7, 1)


def make_kernel():
    """Return a slow-building brightness field with a faint, broad rim."""
    radius_squared = RADIUS * RADIUS
    denominator = 5 * radius_squared**4
    values = []
    for y in range(KERNEL_SIZE):
        for x in range(KERNEL_SIZE):
            remaining = max(0, radius_squared - (x - RADIUS)**2 - (y - RADIUS)**2)
            # Retain the outer glow while delaying the stronger middle values.
            blended = 2 * remaining**2 * radius_squared**2 + 3 * remaining**4
            values.append((PEAK * blended + denominator // 2) // denominator)
    return bytes(values)


def primary_positions(index):
    phase = math.tau * index / PRIMARY_PERIOD
    x_midpoint = (WIDTH - 1) / 2
    x_amplitude = x_midpoint - 3
    # Reserve three horizontal and one vertical cells for the secondary sine.
    # The sums reach the first/last screen cell without moving beyond them.
    return ((round(x_midpoint + x_amplitude * math.sin(phase)) - RADIUS,
             round(11 * math.sin(2 * phase))),
            (round(x_midpoint + x_amplitude * math.sin(2 * phase)) - RADIUS,
             round(11 * math.sin(phase))),
            (round(x_midpoint - x_amplitude * math.sin(phase)) - RADIUS,
             -round(11 * math.sin(2 * phase))))


def horizontal_drift(index):
    phase = math.tau * index / DRIFT_X_PERIOD
    fundamental = round(3 * math.sin(phase))
    return fundamental, -fundamental, round(3 * math.sin(2 * phase))


def vertical_drift(index):
    phase = math.tau * index / DRIFT_Y_PERIOD
    fundamental = round(math.sin(phase))
    return fundamental, -fundamental, round(math.sin(2 * phase))


def motion_state(frame):
    return (frame * PRIMARY_STEP % PRIMARY_PERIOD,
            frame % DRIFT_X_PERIOD, frame % DRIFT_Y_PERIOD)


def ball_positions(frame):
    primary, drift_x, drift_y = motion_state(frame)
    bases = primary_positions(primary)
    dx, dy = horizontal_drift(drift_x), vertical_drift(drift_y)
    return tuple((left + dx[ball], top + dy[ball])
                 for ball, (left, top) in enumerate(bases))


def positions_binary():
    return bytes(primary_positions(index)[ball][axis] & 0xff
                 for ball in range(3) for axis in range(2)
                 for index in range(PRIMARY_PERIOD))


def drift_binary(component, period):
    return bytes(component(index)[ball] & 0xff if index < period else 0
                 for ball in range(3) for index in range(256))


def make_full_font():
    # Keep the original 33 glyphs, then continue to a completely filled tile.
    ranks = bayer8()
    extra = bytes(
        sum(1 << (7 - x) for x in range(8) if ranks[y][x] < count)
        for count in (*range(33, 63), 64) for y in range(8)
    )
    return make_font() + extra


def projection(value):
    """Use each 64-value interval for a complete color blend, without scaling."""
    return value, FOREGROUNDS[value >> 6]


def make_kernel_blitters(kernel):
    """Compile nonzero constant weights into shared, clipped row entry points."""
    rows = [kernel[y * KERNEL_SIZE:(y + 1) * KERNEL_SIZE] for y in range(KERNEL_SIZE)]
    unique_rows = list(dict.fromkeys(rows))
    row_indices = [unique_rows.index(row) for row in rows]
    lines = [
        "// Generated from the numerical kernel. Mirrored rows share code.",
        "// Entry n starts at the first nonzero column >= n, or the row return.",
        f".const KERNEL_MAX_WEIGHT = {max(kernel)}",
        ".align $100",
        "saturation:",
    ]
    saturated = [min(255, value) for value in range(256 + max(kernel))]
    for offset in range(0, len(saturated), 16):
        lines.append("    .byte " + ",".join(map(str, saturated[offset:offset + 16])))
    lines.append("kernel_blit_tables_lo:")
    lines.append("    .byte " + ",".join(f"<kernel_blit_entries_{row:02d}" for row in row_indices))
    lines.append("kernel_blit_tables_hi:")
    lines.append("    .byte " + ",".join(f">kernel_blit_entries_{row:02d}" for row in row_indices))

    for row_index, row in enumerate(unique_rows):
        entries = []
        for column in range(KERNEL_SIZE + 1):
            following = next((x for x in range(column, KERNEL_SIZE) if row[x]), None)
            entries.append(f"kernel_blit_return_{row_index:02d}" if following is None
                           else f"kernel_blit_pixel_{row_index:02d}_{following:02d}")
        lines.append(f"kernel_blit_entries_{row_index:02d}:")
        lines.append("    .word " + ",".join(entries))

    for row_index, row in enumerate(unique_rows):
        for column, weight in enumerate(row):
            if not weight:
                continue
            lines.extend((f"kernel_blit_pixel_{row_index:02d}_{column:02d}:",
                          f"    ldy #{column}",
                          "    lda (field_ptr),y",
                          "    tax",
                          f"    lda saturation+{weight},x",
                          "    sta (field_ptr),y"))
        lines.extend((f"kernel_blit_return_{row_index:02d}:", "    rts"))
    lines.append("kernel_blitters_end:")
    return "\n".join(lines) + "\n"


def field(kernel, positions, previous=None, clear=False):
    values = (bytearray(WIDTH * HEIGHT) if previous is None or clear else
              bytearray(max(0, value - 1) for value in previous))
    for left, top in positions:
        for y in range(max(0, -top), min(KERNEL_SIZE, HEIGHT - top)):
            for x in range(max(0, -left), min(KERNEL_SIZE, WIDTH - left)):
                index = (top + y) * WIDTH + left + x
                values[index] = min(255, values[index] + kernel[y * KERNEL_SIZE + x])
    return bytes(values)


def render(values, font, rgb):
    image = Image.new("RGB", (WIDTH * 8, HEIGHT * 8))
    for index, value in enumerate(values):
        code, color = projection(value)
        image.paste(tile(font, code & 63, rgb[color], rgb[BACKGROUNDS[code >> 6]]),
                    (index % WIDTH * 8, index // WIDTH * 8))
    return image


def make_previews(kernel, font):
    rgb = palette()
    frames = []
    previous = None
    previous_interval = 0
    for frame in range(PREVIEW_FRAMES):
        # Nominal host timing only; the native verifier observes the real timer.
        interval = frame * PREVIEW_UPDATE_CYCLES // (PAL_CLOCK * CLEAR_INTERVAL_SECONDS)
        previous = field(kernel, ball_positions(frame), previous,
                         clear=interval != previous_interval)
        previous_interval = interval
        frames.append(render(previous, font, rgb).resize(
            (640, 400), Image.Resampling.NEAREST))
    # This is a host-rendered model preview. Native cadence is measured separately.
    frames[0].save(OUTPUT / "preview.gif", save_all=True, append_images=frames[1:],
                   duration=round(PREVIEW_UPDATE_CYCLES * 1000 / PAL_CLOCK),
                   loop=0, optimize=False, disposal=2)

    sheet = Image.new("RGB", (1008, 350), "#17191d")
    draw = ImageDraw.Draw(sheet)
    font_path = Path("/System/Library/Fonts/Menlo.ttc")
    label = ImageFont.truetype(str(font_path), 15) if font_path.exists() else ImageFont.load_default()
    title = ImageFont.truetype(str(font_path), 21) if font_path.exists() else label
    draw.text((12, 16), "BALL CONTRIBUTIONS / ADD / PROJECT", font=title, fill="white")
    for count in range(1, 4):
        x = 12 + (count - 1) * 332
        draw.text((x, 60), f"{count} BALL{'S' if count > 1 else ''} / PEAK {count * PEAK}",
                  font=label, fill="#b4b9c2")
        values = field(kernel, [(WIDTH // 2 - RADIUS, HEIGHT // 2 - RADIUS)] * count)
        image = render(values, font, rgb)
        sheet.paste(image, (x, 87))
        image.save(OUTPUT / f"overlap-{count}.png")
    draw.text((12, 307), "0 BLUE / 63 PURPLE / 127 PINK / 191 YELLOW / 255 WHITE", font=label, fill="white")
    sheet.save(OUTPUT / "additive-study.png")

    ramp = Image.new("RGB", (608, 336), "#17191d")
    draw = ImageDraw.Draw(ramp)
    for segment, name in enumerate(("BLUE TO PURPLE", "PURPLE TO PINK", "PINK TO YELLOW", "YELLOW TO WHITE")):
        top = 16 + segment * 80
        draw.text((48, top), f"{segment * 64:3d}-{segment * 64 + 63:3d} / {name}", font=label, fill="white")
        for step in range(64):
            code, color = projection(segment * 64 + step)
            sample = tile(font, code & 63, rgb[color], rgb[BACKGROUNDS[segment]])
            for row in range(4):
                ramp.paste(sample, (48 + step * 8, top + 26 + row * 8))
    ramp.save(OUTPUT / "color-ramp.png")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    kernel = make_kernel()
    font = make_full_font()
    mapping = [projection(value) for value in range(256)]
    for name, data in (("kernel.bin", kernel), ("positions.bin", positions_binary()),
                       ("drift-x.bin", drift_binary(horizontal_drift, DRIFT_X_PERIOD)),
                       ("drift-y.bin", drift_binary(vertical_drift, DRIFT_Y_PERIOD)),
                       ("fade.bin", bytes(max(0, value - 1) for value in range(256))),
                       ("font.bin", font), ("map-screen.bin", bytes(code for code, _ in mapping)),
                       ("map-color.bin", bytes(color for _, color in mapping))):
        (OUTPUT / name).write_bytes(data)
    (OUTPUT / "kernel-blitters.asm").write_text(make_kernel_blitters(kernel))
    rows = [list(kernel[y * KERNEL_SIZE:(y + 1) * KERNEL_SIZE]) for y in range(KERNEL_SIZE)]
    (OUTPUT / "kernel.json").write_text(json.dumps({
        "width": KERNEL_SIZE, "height": KERNEL_SIZE, "range": [0, PEAK],
        "kind": "brightness contributions, no character or color codes", "values": rows,
    }, indent=2) + "\n")
    (OUTPUT / "kernel.txt").write_text("\n".join(
        " ".join(f"{value:2d}" for value in row) for row in rows) + "\n")
    (OUTPUT / "manifest.json").write_text(json.dumps({
        "field": {"width": WIDTH, "height": HEIGHT, "bytes": 1000, "range": [0, 255],
                  "history": "retained between updates; zeroed at startup and every 10 seconds",
                  "decay": "max(0, previous - 1) before adding the current balls",
                  "reset_interval_seconds": CLEAR_INTERVAL_SECONDS,
                  "reset_interval_cycles": PAL_CLOCK * CLEAR_INTERVAL_SECONDS,
                  "reset_timing": "continuous chained CIA2 timers; consume deadline at the next update before adding balls",
                  "addition": "unsigned saturating: min(255, old + contribution)"},
        "kernel": {"width": KERNEL_SIZE, "height": KERNEL_SIZE, "peak": PEAK,
                   "radius_cells": RADIUS,
                   "formula": f"u=max(0,1-(dx*dx+dy*dy)/144); round({PEAK}*(0.4*u^2+0.6*u^4))"},
        "preview_frames": PREVIEW_FRAMES,
        "ball_count": 3,
        "positions_layout": "six 128-byte primary-component planes: ball0x, ball0y, ball1x, ball1y, ball2x, ball2y; signed bytes",
        "drift_layout": "each drift file contains three 256-byte signed planes, one per ball; unused entries after its period are zero padding",
        "motion": {"origin_x_range": [-12, 27], "origin_y_range": [-12, 12],
                   "center_x_range": [0, 39], "center_y_range": [0, 24],
                   "center_reaches_screen_edges": True,
                   "primary_period": PRIMARY_PERIOD, "primary_step": PRIMARY_STEP,
                   "drift_x_period": DRIFT_X_PERIOD, "drift_y_period": DRIFT_Y_PERIOD,
                   "joint_state_period_updates": MOTION_PERIOD,
                   "paths": ["(round(19.5+16.5*sin(P))-12 + round(3*sin(X)), round(11*sin(2*P)) + round(sin(Y)))",
                             "(round(19.5+16.5*sin(2*P))-12 - round(3*sin(X)), round(11*sin(P)) - round(sin(Y)))",
                             "(round(19.5-16.5*sin(P))-12 + round(3*sin(2*X)), -round(11*sin(2*P)) + round(sin(2*Y)))"],
                   "phases": "P=2*pi*((3*frame)%128)/128; X=2*pi*(frame%251)/251; Y=2*pi*(frame%239)/239"},
        "clipping": "intersect each 25x25 kernel with the 40x25 field; discard contributions outside, including fully offscreen balls",
        "backgrounds": BACKGROUNDS,
        "foregrounds": FOREGROUNDS,
        "projection": "screen_code = byte; foreground = foregrounds[byte >> 6]; four complete 64-value color intervals",
        "ramp_intervals": [
            {"range": [0, 63], "from": "blue", "to": "purple"},
            {"range": [64, 127], "from": "purple", "to": "pink"},
            {"range": [128, 191], "from": "pink", "to": "yellow"},
            {"range": [192, 255], "from": "yellow", "to": "white"},
        ],
        "ramp_anchors": {"0": "blue", "63": "purple", "64": "purple", "127": "pink",
                         "128": "pink", "191": "yellow", "192": "yellow", "255": "white"},
        "byte_endpoint": "256 is outside an unsigned byte; 255 is already solid white",
        "font": {"glyphs": 64, "bytes": 512, "original_glyphs_preserved": 33,
                 "extra_glyphs": "glyphs 33..62 contain ranks below the glyph index; glyph 63 is solid",
                 "coverage_counts": [*range(63), 64],
                 "phase": "nested through the entire 0..100% ramp; omit 63/64 coverage to fit 64 slots"},
        "preview": "preview.gif is a finite 256-frame host-model excerpt at nominal three-PAL-frame cadence; resets use that nominal clock, while native timer timing is verified separately",
    }, indent=2) + "\n")
    make_previews(kernel, font)
    print(f"Generated numerical 25x25 ball (0..{PEAK}), 1000-byte field contract and 256-entry ECM projection LUTs.")


if __name__ == "__main__":
    main()
