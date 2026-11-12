#!/usr/bin/env python3
"""Verify additive byte fields and their actual PAL VIC-II ECM presentation."""

import hashlib
import json
import math
from pathlib import Path
import re
import socket
import statistics
import subprocess

from PIL import Image

import verify as ecm_verify


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "build/metaballs"
BACKGROUNDS = (6, 4, 10, 7)
FOREGROUNDS = (4, 10, 7, 1)
PAL_CLOCK = 985248
PAL_FRAME_CYCLES = 19656
KERNEL_PEAK = 4
SATURATION_SEED = 254
PRIMARY_PERIOD, X_PERIOD, Y_PERIOD = 128, 251, 239
EXCERPT_FRAMES = 384
SAMPLE_FRAMES = (0, 96, 192, 288, 383)
TIMER_A_PERIOD = 30789
TIMER_B_PERIOD = 320
RESET_INTERVAL = TIMER_A_PERIOD * TIMER_B_PERIOD
COUNTER_LABELS = ("frame_index", "drift_x_index", "drift_y_index")
REQUIRED_LABELS = (
    "frame_start", "add_start", "map_start", "presentation_start", "frame_ready", *COUNTER_LABELS,
    "brightness_field", "font", "kernel", "positions", "drift_x", "drift_y", "screen_map", "color_map", "fade_map", "render_end",
    "timer_arm", "timer_poll", "timer_low_sampled", "timer_sampled", "clear_start", "clear_done",
    "fade_start", "timer_started", "timer_current", "timer_previous", "reset_count",
    *(f"render_row_{row}" for row in range(25)),
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class Monitor(ecm_verify.Monitor):
    def dump(self, name, first, last):
        path = OUTPUT / name
        self.run(f'bsave "{path}" 0 {first:04x} {last:04x}')
        data = path.read_bytes()
        if len(data) != last - first + 1:
            raise AssertionError(f"Incomplete native memory dump: {path}")
        return data

    def registers(self):
        result = self.run("r")
        match = re.search(r"^\.;([0-9a-fA-F]{4})\s+(.*)$", result, re.M)
        if not match:
            raise AssertionError(f"Incomplete VICE registers response: {result}")
        fields = match[2].split()
        return {"pc": int(match[1], 16), "raster": int(fields[-3]),
                "raster_cycle": int(fields[-2]), "clock": int(fields[-1])}

    def checkpoint(self, address):
        result = self.run(f"break {address:04x}")
        match = re.search(r"BREAK:\s*(\d+)", result)
        if not match:
            raise AssertionError(f"VICE did not set breakpoint ${address:04x}.")
        return int(match[1])

    def inject(self, address, data, name):
        path = OUTPUT / name
        path.write_bytes(data)
        self.run("bank ram")
        self.run(f'bload "{path}" 0 {address:04x}')
        self.run("bank cpu")


def projection(value):
    """Independent arithmetic contract, rather than the generated lookup tables."""
    return value, FOREGROUNDS[value >> 6]


def kernel_values():
    values = []
    denominator = 5 * 144 ** 4
    for y in range(25):
        for x in range(25):
            remaining = max(0, 144 - (x - 12) ** 2 - (y - 12) ** 2)
            numerator = KERNEL_PEAK * (2 * remaining ** 2 * 144 ** 2 + 3 * remaining ** 4)
            values.append((numerator + denominator // 2) // denominator)
    return bytes(values)


def primary_positions(index):
    phase = math.tau * index / PRIMARY_PERIOD
    slow = math.sin(phase)
    fast = math.sin(2 * phase)
    return ((round(19.5 + 16.5 * slow) - 12, round(11 * fast)),
            (round(19.5 + 16.5 * fast) - 12, round(11 * slow)),
            (round(19.5 - 16.5 * slow) - 12, -round(11 * fast)))


def horizontal_drift(index):
    phase = math.tau * index / X_PERIOD
    slow = round(3 * math.sin(phase))
    return slow, -slow, round(3 * math.sin(2 * phase))


def vertical_drift(index):
    phase = math.tau * index / Y_PERIOD
    slow = round(math.sin(phase))
    return slow, -slow, round(math.sin(2 * phase))


def state_at(update):
    return (3 * update) % PRIMARY_PERIOD, update % X_PERIOD, update % Y_PERIOD


def advance_state(state):
    primary, drift_x, drift_y = state
    return (primary + 3) % PRIMARY_PERIOD, (drift_x + 1) % X_PERIOD, (drift_y + 1) % Y_PERIOD


def positions_for_state(state):
    primary, drift_x, drift_y = state
    main = primary_positions(primary)
    dx, dy = horizontal_drift(drift_x), vertical_drift(drift_y)
    return tuple((left + dx[ball], top + dy[ball]) for ball, (left, top) in enumerate(main))


def field_for_positions(positions, kernel, seed=0):
    """Sample each visible cell; offscreen source pixels never enter the field."""
    initial = bytes([seed]) * 1000 if isinstance(seed, int) else seed
    if len(initial) != 1000:
        raise AssertionError("The retained brightness field must contain exactly 1000 cells.")
    field = []
    for screen_y in range(25):
        for screen_x in range(40):
            total = initial[screen_y * 40 + screen_x]
            for left, top in positions:
                source_x, source_y = screen_x - left, screen_y - top
                if 0 <= source_x < 25 and 0 <= source_y < 25:
                    total += kernel[source_y * 25 + source_x]
            field.append(min(255, total))
    return bytes(field)


def evolve_field(previous, state, kernel, clear=False):
    faded = bytes(1000) if clear else bytes(max(0, value - 1) for value in previous)
    return field_for_positions(positions_for_state(state), kernel, faded)


def mapped_field(field):
    codes, colors = zip(*(projection(value) for value in field))
    return bytes(codes), bytes(colors)


def decode_ecm(screen, colors, font, palette):
    image = Image.new("RGB", (320, 200))
    pixels = image.load()
    for cell, code in enumerate(screen):
        foreground = palette[colors[cell] & 15]
        background = palette[BACKGROUNDS[code >> 6]]
        left, top = cell % 40 * 8, cell // 40 * 8
        for y in range(8):
            bits = font[(code & 63) * 8 + y]
            for x in range(8):
                pixels[left + x, top + y] = foreground if bits & (128 >> x) else background
    return image


def check_assets():
    kernel = kernel_values()
    if (OUTPUT / "kernel.bin").read_bytes() != kernel:
        raise AssertionError("Generated kernel differs from the independent integer radial formula.")
    expected_positions = bytearray()
    for ball in range(3):
        for axis in range(2):
            for frame in range(PRIMARY_PERIOD):
                coordinate = primary_positions(frame)[ball][axis]
                if not -128 <= coordinate <= 127:
                    raise AssertionError("Generated motion must fit signed eight-bit coordinates.")
                expected_positions.append(coordinate & 255)
    if (OUTPUT / "positions.bin").read_bytes() != expected_positions:
        raise AssertionError("Generated primary motion differs from the independent 128-phase contract.")
    expected_drift_x = bytes(
        (horizontal_drift(index)[ball] & 255) if index < X_PERIOD else 0
        for ball in range(3) for index in range(256)
    )
    expected_drift_y = bytes(
        (vertical_drift(index)[ball] & 255) if index < Y_PERIOD else 0
        for ball in range(3) for index in range(256)
    )
    if (OUTPUT / "drift-x.bin").read_bytes() != expected_drift_x:
        raise AssertionError("Generated horizontal drift differs from the independent 251-phase contract.")
    if (OUTPUT / "drift-y.bin").read_bytes() != expected_drift_y:
        raise AssertionError("Generated vertical drift differs from the independent 239-phase contract.")
    nonzero_kernel_pixels = sum(value != 0 for value in kernel)
    possible_origins = set()
    for ball in range(3):
        dx_values = {horizontal_drift(index)[ball] for index in range(X_PERIOD)}
        dy_values = {vertical_drift(index)[ball] for index in range(Y_PERIOD)}
        for primary in range(PRIMARY_PERIOD):
            left, top = primary_positions(primary)[ball]
            possible_origins.update((left + dx, top + dy) for dx in dx_values for dy in dy_values)
    minimum_visible_pixels = nonzero_kernel_pixels
    maximum_edge_overhang = 0
    for left, top in possible_origins:
        center_x, center_y = left + 12, top + 12
        if not 0 <= center_x <= 39 or not 0 <= center_y <= 24:
            raise AssertionError("Every ball center must stay on the 40x25 screen.")
        edge_overhang = max(-left, left + 25 - 40, -top, top + 25 - 25, 0)
        maximum_edge_overhang = max(maximum_edge_overhang, edge_overhang)
        visible_pixels = sum(
            kernel[y * 25 + x] != 0
            for y in range(25) for x in range(25)
            if 0 <= left + x < 40 and 0 <= top + y < 25
        )
        minimum_visible_pixels = min(minimum_visible_pixels, visible_pixels)
    screen_map, color_map = mapped_field(bytes(range(256)))
    if (OUTPUT / "map-screen.bin").read_bytes() != screen_map:
        raise AssertionError("Generated screen lookup differs from full-range arithmetic projection.")
    if (OUTPUT / "map-color.bin").read_bytes() != color_map:
        raise AssertionError("Generated color lookup differs from full-range arithmetic projection.")
    fade_lookup = bytes(max(0, value - 1) for value in range(256))
    if (OUTPUT / "fade.bin").read_bytes() != fade_lookup:
        raise AssertionError("Generated fade lookup must subtract exactly one, with a floor at zero.")
    font = (OUTPUT / "font.bin").read_bytes()
    if len(font) != 512:
        raise AssertionError("Metaballs must contain exactly 64 eight-byte glyphs.")
    glyphs = [font[index * 8:(index + 1) * 8] for index in range(64)]
    if len(set(glyphs)) != 64:
        raise AssertionError("All 64 glyphs must be distinct.")
    if glyphs[32] != bytes([0xaa, 0x55] * 4):
        raise AssertionError("Glyph 32 must be the original 50% checkerboard.")
    previous = bytes(8)
    for index, mask in enumerate(glyphs):
        expected_pixels = index if index < 63 else 64
        if sum(row.bit_count() for row in mask) != expected_pixels:
            raise AssertionError(f"Glyph {index} must contain {expected_pixels} set pixels.")
        if any(old & new != old for old, new in zip(previous, mask)):
            raise AssertionError("Successive glyphs must preserve every previously set pixel.")
        previous = mask
    motion_contract = {"all_independent_phases_bounded": True,
                       "distinct_origins_checked": len(possible_origins),
                       "maximum_edge_overhang_cells": maximum_edge_overhang,
                       "minimum_visible_area_fraction": minimum_visible_pixels / nonzero_kernel_pixels}
    return (kernel, font, bytes(expected_positions), expected_drift_x, expected_drift_y,
            screen_map, color_map, fade_lookup, motion_contract)


def verify():
    subprocess.run([str(HERE / "build-metaballs.sh")], cwd=HERE, check=True)
    (kernel, font, positions, drift_x, drift_y,
     screen_map, color_map, fade_lookup, motion_contract) = check_assets()
    motion_period = math.lcm(PRIMARY_PERIOD // math.gcd(PRIMARY_PERIOD, 3), X_PERIOD, Y_PERIOD)
    if motion_period != 7_678_592 or state_at(motion_period) != state_at(0):
        raise AssertionError("Motion state period differs from the independent LCM contract.")
    if any(state_at(motion_period // factor) == state_at(0) for factor in (2, X_PERIOD, Y_PERIOD)):
        raise AssertionError("A proper divisor unexpectedly repeats the full motion state.")
    symbols = (OUTPUT / "metaballs.sym").read_text()
    labels = {name: int(address, 16) for name, address in
              re.findall(r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", symbols)}
    if any(name not in labels for name in REQUIRED_LABELS):
        raise AssertionError("Missing native labels required for verification.")
    palette_path = HERE.parents[1] / "palettes/colodore.vpl"
    palette = [tuple(int(channel, 16) for channel in line.split()[:3])
               for line in palette_path.read_text().splitlines()
               if line.strip() and not line.startswith("#")]
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    program = OUTPUT / "metaballs.prg"
    command = [
        "/opt/homebrew/bin/x64sc", "-default", "+saveres", "-minimized", "-pal",
        "-speed", "100", "+warp", "+autostart-warp", "+confirmonexit",
        "-sounddev", "dummy", "+refreshonbreak", "+binarymonitor",
        "-initbreak", "reset", "-autostartprgmode", "1", "-autostart", str(program),
        "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", str(palette_path),
        "-VICIIsaturation", "1000", "-VICIIcontrast", "1000",
        "-VICIIbrightness", "1000", "-VICIIgamma", "1000",
        "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}",
    ]
    report = {"pass": False, "program": str(program), "program_sha256": sha256(program.read_bytes()),
              "pal": True, "speed_percent": 100, "warp": False,
              "field": "1000 retained offscreen bytes; subtract one with a zero floor, then saturating ball addition",
              "fade_per_update": 1,
              "reset_interval_cycles": RESET_INTERVAL,
              "reset_events": [],
              "motion_period_scope": "Counter trajectory only; retained field history is not asserted to repeat",
              "global_backgrounds": BACKGROUNDS, "segment_foregrounds": FOREGROUNDS,
              "projection": "Screen code equals byte brightness; four full 64-value intervals",
              "renderer": "Single unrolled pass writes brightness screen code and foreground Color RAM",
              "motion_contract": motion_contract,
              "motion_state_period_updates": motion_period,
              "full_motion_cycle_verified": False,
              "excerpt_frames": EXCERPT_FRAMES,
              "command": command, "frames": [], "screenshots": [], "row_windows": [], "injected_cases": []}
    images = []
    process, connection, monitor = None, None, None
    with (OUTPUT / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            report["owned_pid"] = process.pid
            connection = ecm_verify.connect_monitor(process, port)
            monitor = Monitor(connection)
            monitor.run("sidefx off")
            for resource, expected in (("MachineVideoStandard", 1), ("Speed", 100),
                                       ("InitialWarpMode", 0), ("AutostartWarp", 0)):
                value = monitor.run(f'resourceget "{resource}"')
                if f"{resource}={expected}" not in value:
                    raise AssertionError(f"Unexpected VICE resource: {value}")
            active = {name: monitor.checkpoint(labels[name]) for name in
                      ("frame_start", "map_start", "presentation_start", "frame_ready", "timer_arm",
                       "timer_poll", "timer_low_sampled", "timer_sampled", "clear_start", "clear_done", "fade_start")}

            def arrive(name):
                monitor.run("x")
                registers = monitor.registers()
                if registers["pc"] != labels[name]:
                    raise AssertionError(f"Expected {name}, stopped at ${registers['pc']:04x}.")
                return registers

            def arrive_one_of(*names):
                monitor.run("x")
                registers = monitor.registers()
                for name in names:
                    if registers["pc"] == labels[name]:
                        return name, registers
                raise AssertionError(f"Unexpected checkpoint ${registers['pc']:04x}; expected {names}.")

            def ram_snapshot(name):
                monitor.run("bank ram")
                data = monitor.dump(name, 0, 65535)
                monitor.run("bank cpu")
                return data

            def word(ram, name):
                return int.from_bytes(ram[labels[name]:labels[name] + 2], "little")

            def native_state(ram):
                return tuple(ram[labels[name]] for name in COUNTER_LABELS)

            def read_native(expected_field, state):
                monitor.run("bank ram")
                ram = monitor.dump("native-ram.bin", 0, 65535)
                monitor.run("bank io")
                io = monitor.dump("native-io.bin", 0xd000, 0xdfff)
                monitor.run("bank cpu")
                if native_state(ram) != state:
                    raise AssertionError(f"Native motion counters differ from expected state {state}.")
                for name, expected in (("font", font), ("kernel", kernel), ("positions", positions),
                                       ("drift_x", drift_x), ("drift_y", drift_y),
                                       ("screen_map", screen_map), ("color_map", color_map), ("fade_map", fade_lookup)):
                    address = labels[name]
                    if ram[address:address + len(expected)] != expected:
                        raise AssertionError(f"Native {name} changed or loaded incorrectly.")
                field_address = labels["brightness_field"]
                field = ram[field_address:field_address + 1000]
                if field != expected_field:
                    different = sum(a != b for a, b in zip(field, expected_field))
                    raise AssertionError(f"Native additive field differs in {different} cells, state {state}.")
                front = (io[0x18] >> 4) * 0x400
                if front != 0x0400:
                    raise AssertionError("VIC must use the fixed screen at $0400.")
                if (io[0x11] & 0x7f) != 0x5b or (io[0x16] & 0x1f) != 8 or (io[0x18] & 14) != 8:
                    raise AssertionError("VIC is not in 40x25 ECM with font at $2000.")
                if tuple(value & 15 for value in io[0x21:0x25]) != BACKGROUNDS:
                    raise AssertionError("ECM global backgrounds differ from blue/purple/pink/yellow.")
                if io[0x20] & 15 != BACKGROUNDS[0]:
                    raise AssertionError("Border must match the zero-field blue background.")
                if io[0xd00] & 3 != 3 or io[0xd02] & 3 != 3 or io[0x15] != 0:
                    raise AssertionError("VIC bank zero or sprite disable is incorrect.")
                screen = ram[front:front + 1000]
                colors = bytes(value & 15 for value in io[0x800:0xbe8])
                expected_screen, expected_colors = mapped_field(expected_field)
                if screen != expected_screen or colors != expected_colors:
                    raise AssertionError("Native screen/color projection differs from arithmetic mapping.")
                primary_index, dx_index, dy_index = native_state(ram)

                def signed_component(address):
                    value = ram[address]
                    return value if value < 128 else value - 256

                centers = []
                for ball in range(3):
                    left = (signed_component(labels["positions"] + ball * 256 + primary_index)
                            + signed_component(labels["drift_x"] + ball * 256 + dx_index))
                    top = (signed_component(labels["positions"] + ball * 256 + 128 + primary_index)
                           + signed_component(labels["drift_y"] + ball * 256 + dy_index))
                    centers.append((left + 12, top + 12))
                return field, screen, colors, centers

            pending_capture = None
            expected_history = bytes(1000)
            # Bound the CIA force-load/start pipeline phase using hardware
            # counter samples; every subsequent period remains exactly10s.
            phase_candidates = set(range(9))
            handled_resets = 0
            previous_timer_count = TIMER_B_PERIOD - 1
            previous_poll_clock = None
            timer_arm_clock = None
            for index in range(EXCERPT_FRAMES + 1):
                state = state_at(index)
                started = arrive("frame_start")
                if index == 0:
                    armed = arrive("timer_arm")
                    timer_arm_clock = armed["clock"]
                    report["timer_arm_clock"] = timer_arm_clock
                arrive("timer_poll")
                while True:
                    event, registers = arrive_one_of("timer_low_sampled", "timer_sampled")
                    if event == "timer_low_sampled":
                        sample_clock = registers["clock"] - 1
                    else:
                        break
                timer_ram = ram_snapshot("timer-sample.bin")
                current_timer_count = word(timer_ram, "timer_current")
                if word(timer_ram, "timer_previous") != previous_timer_count:
                    raise AssertionError("Timer polling did not remember the previous coherent count.")
                if word(timer_ram, "reset_count") != handled_resets:
                    raise AssertionError("Reset count changed outside the independently scheduled reset.")
                phase_candidates = {offset for offset in phase_candidates
                                    if ((TIMER_B_PERIOD - 1 - max(0, (sample_clock - timer_arm_clock - offset)
                                                                  // TIMER_A_PERIOD)) % TIMER_B_PERIOD)
                                    == current_timer_count}
                if not phase_candidates:
                    raise AssertionError("CIA2 counter does not follow the exact 30789x320 clock schedule.")
                elapsed_periods = {(sample_clock - timer_arm_clock - offset) // RESET_INTERVAL
                                   for offset in phase_candidates}
                if len(elapsed_periods) != 1:
                    raise AssertionError("CIA startup phase does not determine an unambiguous deadline.")
                elapsed_periods = max(0, elapsed_periods.pop())
                should_clear = elapsed_periods > handled_resets
                if should_clear:
                    if elapsed_periods != handled_resets + 1:
                        raise AssertionError("The program missed an entire 10-second polling interval.")
                    clearing = arrive("clear_start")
                    before_clear = ram_snapshot("natural-clear-before.bin")
                    field_address = labels["brightness_field"]
                    if before_clear[field_address:field_address + 1000] != expected_history:
                        raise AssertionError("Retained history changed before the scheduled clear.")
                    guards = ((labels["fade_map"] - 32, bytes([0xa5]) * 32),
                              (field_address + 1000, bytes([0xc7]) * 24),
                              (field_address + 1024, bytes([0xd3]) * 1024))
                    monitor.inject(field_address, bytes([165]) * 1000, "natural-clear-input.bin")
                    for guard_index, (address, sentinel) in enumerate(guards):
                        monitor.inject(address, sentinel, f"natural-clear-guard-{guard_index}.bin")
                    cleared = arrive("clear_done")
                    after_clear = ram_snapshot("natural-clear-after.bin")
                    if after_clear[field_address:field_address + 1000] != bytes(1000):
                        raise AssertionError("Scheduled clear did not zero all 1000 logical cells.")
                    for guard_index, (address, sentinel) in enumerate(guards):
                        if after_clear[address:address + len(sentinel)] != sentinel:
                            raise AssertionError("Scheduled clear wrote outside the logical field.")
                        monitor.inject(address, before_clear[address:address + len(sentinel)],
                                       f"restored-natural-clear-guard-{guard_index}.bin")
                    handled_resets += 1
                    if word(after_clear, "reset_count") != handled_resets or native_state(after_clear) != state:
                        raise AssertionError("Scheduled clear changed motion counters or the reset count incorrectly.")
                    deadline_low = timer_arm_clock + handled_resets * RESET_INTERVAL + min(phase_candidates)
                    deadline_high = timer_arm_clock + handled_resets * RESET_INTERVAL + max(phase_candidates)
                    poll_interval = sample_clock - previous_poll_clock
                    if clearing["clock"] < deadline_low or clearing["clock"] - deadline_low > poll_interval + 128:
                        raise AssertionError("Clear occurred before the deadline or later than the first update after it.")
                    report["reset_events"].append({"index": index, "number": handled_resets,
                                                   "deadline_clock_range": [deadline_low, deadline_high],
                                                   "sample_clock": sample_clock, "clear_start": clearing,
                                                   "elapsed_cycles_since_arm": clearing["clock"] - timer_arm_clock,
                                                   "clear_done": cleared, "padding_guards_unchanged": True,
                                                   "motion_state": state})
                else:
                    arrive("fade_start")
                previous_timer_count = current_timer_count
                previous_poll_clock = sample_clock
                computed = arrive("map_start")
                presenting = arrive("presentation_start")
                if pending_capture is not None:
                    # The previous direct render must scan out before capture.
                    # The next presentation checkpoint precedes every RAM write.
                    if presenting["clock"] - pending_capture["ready_clock"] < PAL_FRAME_CYCLES:
                        raise AssertionError("Screenshot capture occurred before a complete VIC scan.")
                    path = OUTPUT / f"frame-{pending_capture['index']:03d}-vice.png"
                    monitor.run(f'scrsh "{path}" 2')
                    comparison = ecm_verify.compare_screenshot(path, pending_capture["image"])
                    report["screenshots"].append({"index": pending_capture["index"],
                                                  "motion_state": pending_capture["state"],
                                                  "file": path.name, **comparison})
                    pending_capture = None
                frame_origin = presenting["clock"] - presenting["raster"] * 63 - presenting["raster_cycle"]
                if index in SAMPLE_FRAMES:
                    row_checkpoints = {name: monitor.checkpoint(labels[name]) for name in
                                       (*(f"render_row_{row}" for row in range(25)), "render_end")}
                    row_starts = [arrive(f"render_row_{row}") for row in range(25)]
                    render_ended = arrive("render_end")
                    rows = []
                    for row, row_start in enumerate(row_starts):
                        row_end = row_starts[row + 1] if row < 24 else render_ended
                        # Conservative bounds include the whole old badline and
                        # end before the next badline even begins.
                        previous_fetch_end = frame_origin + (52 + row * 8) * 63
                        next_fetch_start = frame_origin + PAL_FRAME_CYCLES + (51 + row * 8) * 63
                        if row_start["clock"] < previous_fetch_end or row_end["clock"] >= next_fetch_start:
                            raise AssertionError(f"Direct renderer overlaps row {row}'s VIC fetch window.")
                        rows.append({"row": row, "start": row_start, "end": row_end,
                                     "after_old_badline_cycles": row_start["clock"] - previous_fetch_end,
                                     "before_next_badline_cycles": next_fetch_start - row_end["clock"]})
                    report["row_windows"].append({"index": index, "motion_state": state, "rows": rows})
                    for checkpoint in row_checkpoints.values():
                        monitor.run(f"delete {checkpoint}")
                ready = arrive("frame_ready")
                if presenting["raster"] not in (55, 56):
                    raise AssertionError("Direct renderer did not start in its raster window.")
                next_top_fetch = frame_origin + PAL_FRAME_CYCLES + 51 * 63
                if not frame_origin + PAL_FRAME_CYCLES <= ready["clock"] < next_top_fetch:
                    raise AssertionError("Direct renderer did not finish before the next visible badline.")
                render_cycles = ready["clock"] - presenting["clock"]
                expected_history = evolve_field(expected_history, state, kernel, clear=should_clear)
                expected_field = expected_history
                field, screen, colors, centers = read_native(expected_field, state)
                image = decode_ecm(screen, colors, font, palette)
                sample = {"index": index, "phase": state[0], "motion_state": state, "frame_start": started,
                          "timer_sample_clock": sample_clock, "reset_count": handled_resets,
                          "timer_elapsed_cycles": sample_clock - timer_arm_clock,
                          "cleared_this_update": should_clear,
                          "map_start": computed, "presentation_start": presenting,
                          "frame_ready": ready, "compute_cycles": computed["clock"] - started["clock"],
                          "render_cycles": render_cycles,
                          "before_next_top_fetch_cycles": next_top_fetch - ready["clock"],
                          "field_sha256": sha256(field), "screen_sha256": sha256(screen),
                          "color_sha256": sha256(colors), "peak_brightness": max(field),
                          "field_statistics": {"mean_brightness": sum(field) / 1000,
                                               "nonzero_cells": sum(value != 0 for value in field),
                                               "saturated_cells": field.count(255)},
                          "ball_centers": centers,
                          "field_match": True, "projection_match": True}
                report["frames"].append(sample)
                if should_clear:
                    report["reset_events"][-1]["frame_ready_clock"] = ready["clock"]
                if index < EXCERPT_FRAMES:
                    images.append(image)
                if index in SAMPLE_FRAMES:
                    pending_capture = {"index": index, "state": state, "ready_clock": ready["clock"], "image": image}
                if index % 32 == 0:
                    print(json.dumps({"frame": index, "motion_state": state, "field_match": True,
                                      "compute_cycles": sample["compute_cycles"],
                                      "presentation_raster": ready["raster"]}), flush=True)
            if tuple(report["frames"][-1]["motion_state"]) == state_at(0):
                raise AssertionError("Independent drift counters unexpectedly reset with the primary counter.")
            if handled_resets < 2:
                raise AssertionError("Native excerpt must observe at least two natural 10-second clears.")
            report["cia_startup_phase_candidates"] = sorted(phase_candidates)
            center_coverage = []
            for ball in range(3):
                points = [sample["ball_centers"][ball] for sample in report["frames"][:EXCERPT_FRAMES]]
                edges = {"left": [index for index, (x, _) in enumerate(points) if x == 0],
                         "right": [index for index, (x, _) in enumerate(points) if x == 39],
                         "top": [index for index, (_, y) in enumerate(points) if y == 0],
                         "bottom": [index for index, (_, y) in enumerate(points) if y == 24]}
                if not all(edges.values()):
                    raise AssertionError(f"Ball {ball} does not reach every screen edge in the native excerpt.")
                center_coverage.append({"ball": ball,
                                        "x_range": [min(x for x, _ in points), max(x for x, _ in points)],
                                        "y_range": [min(y for _, y in points), max(y for _, y in points)],
                                        "edge_hit_counts": {edge: len(hits) for edge, hits in edges.items()},
                                        "first_edge_hits": {edge: hits[0] for edge, hits in edges.items()}})
            report["preview_center_coverage"] = {
                "source": "Native table RAM and observed counters, with full numeric fields independently verified",
                "excerpt_frames": EXCERPT_FRAMES,
                "each_ball_reaches_every_edge": True,
                "balls": center_coverage,
            }
            for checkpoint in active.values():
                monitor.run(f"delete {checkpoint}")
            # Hardware timing is proved above. Freeze the timers before isolated
            # renderer, accumulator and fade probes so another natural deadline
            # cannot change their explicitly seeded input.
            monitor.run("bank io")
            monitor.run("> dd0e 00")
            monitor.run("> dd0f 40")
            frozen_cia = monitor.dump("frozen-cia2.bin", 0xdd00, 0xdd0f)
            monitor.run("bank cpu")
            frozen_counter = int.from_bytes(frozen_cia[6:8], "little")
            monitor.inject(labels["timer_previous"], frozen_counter.to_bytes(2, "little"), "frozen-previous.bin")
            report["timers_frozen_for_isolated_probes"] = True
            ready_checkpoint = monitor.checkpoint(labels["frame_ready"])
            map_checkpoint = monitor.checkpoint(labels["map_start"])
            arrive("map_start")
            injected = bytes(index & 255 for index in range(1000))
            monitor.inject(labels["brightness_field"], injected, "projection-input.bin")
            monitor.run(f"delete {map_checkpoint}")
            arrive("frame_ready")
            projection_state = state_at(EXCERPT_FRAMES + 1)
            read_native(injected, projection_state)
            report["injected_cases"].append({"name": "every_byte_brightness_through_native_projection",
                                              "values_tested": list(range(256)), "pass": True})
            add_checkpoint = monitor.checkpoint(labels["add_start"])
            arrive("add_start")
            seeded = bytes([SATURATION_SEED]) * 1000
            monitor.inject(labels["brightness_field"], seeded, "saturation-input.bin")
            monitor.run(f"delete {add_checkpoint}")
            arrive("frame_ready")
            saturation_state = advance_state(projection_state)
            contributions = field_for_positions(positions_for_state(saturation_state), kernel)
            overflow_cells = sum(SATURATION_SEED + value > 255 for value in contributions)
            saturated = field_for_positions(positions_for_state(saturation_state), kernel, seed=SATURATION_SEED)
            read_native(saturated, saturation_state)
            if not overflow_cells:
                raise AssertionError("The saturation case did not exercise an overflowing sum.")
            report["injected_cases"].append({"name": "saturating_addition_over_255",
                                              "seed_brightness": SATURATION_SEED, "motion_state": saturation_state,
                                              "overflow_cells": overflow_cells,
                                              "saturated_cells": saturated.count(255), "pass": True})

            # Test the real add stage before rendering, guarding both sides of the field.
            # Two invisible balls isolate each edge case; one case also overlaps
            # three clipped balls to exercise addition at the upper-left corner.
            invisible = ((-128, 127), (127, -128))
            origins = (
                ("left", (-12, 0)), ("right", (28, 0)),
                ("top", (8, -12)), ("bottom", (8, 13)),
                ("top_left", (-12, -12)), ("top_right", (28, -12)),
                ("bottom_left", (-12, 13)), ("bottom_right", (28, 13)),
                ("last_cell_center", (27, 12)), ("last_inside_origin", (15, 0)),
                ("outside_left", (-25, 0)), ("outside_right", (40, 0)),
                ("outside_top", (0, -25)), ("outside_bottom", (0, 25)),
                ("negative_extreme", (-128, -128)), ("positive_extreme", (127, 127)),
            )
            clipping_cases = [(name, (origin, *invisible)) for name, origin in origins]
            clipping_cases.append(("overlapping_top_left", ((-12, -12),) * 3))
            add_checkpoint = monitor.checkpoint(labels["add_start"])
            map_checkpoint = monitor.checkpoint(labels["map_start"])
            for name, case_positions in clipping_cases:
                arrive("add_start")
                monitor.run("bank ram")
                before = monitor.dump("clipping-before.bin", 0, 65535)
                monitor.run("bank cpu")
                state = native_state(before)
                primary_index, dx_index, dy_index = state
                patched_positions = bytearray(positions)
                patched_drift_x, patched_drift_y = bytearray(drift_x), bytearray(drift_y)
                for ball, (left, top) in enumerate(case_positions):
                    patched_positions[ball * 256 + primary_index] = left & 255
                    patched_positions[ball * 256 + 128 + primary_index] = top & 255
                    patched_drift_x[ball * 256 + dx_index] = 0
                    patched_drift_y[ball * 256 + dy_index] = 0
                guards = (
                    (labels["fade_map"] - 32, bytes([0xa5]) * 32),
                    (labels["brightness_field"] + 1000, bytes([0xc7]) * 24),
                    (labels["brightness_field"] + 1024, bytes([0xd3]) * 1024),
                )
                monitor.inject(labels["brightness_field"], bytes(1000), "clipping-zero-field.bin")
                monitor.inject(labels["positions"], patched_positions, "clipping-positions.bin")
                monitor.inject(labels["drift_x"], patched_drift_x, "clipping-drift-x.bin")
                monitor.inject(labels["drift_y"], patched_drift_y, "clipping-drift-y.bin")
                for index, (address, sentinel) in enumerate(guards):
                    monitor.inject(address, sentinel, f"clipping-guard-{index}.bin")
                arrive("map_start")
                monitor.run("bank ram")
                after = monitor.dump("clipping-after.bin", 0, 65535)
                monitor.run("bank cpu")
                expected_field = field_for_positions(case_positions, kernel)
                field_address = labels["brightness_field"]
                if after[field_address:field_address + 1000] != expected_field:
                    raise AssertionError(f"Native clipping differs from visible-cell sampling: {name}.")
                for address, sentinel in guards:
                    if after[address:address + len(sentinel)] != sentinel:
                        raise AssertionError(f"Native clipping wrote outside the visible field: {name}.")
                monitor.inject(labels["positions"], positions, "restored-positions.bin")
                monitor.inject(labels["drift_x"], drift_x, "restored-drift-x.bin")
                monitor.inject(labels["drift_y"], drift_y, "restored-drift-y.bin")
                for index, (address, sentinel) in enumerate(guards):
                    monitor.inject(address, before[address:address + len(sentinel)],
                                   f"restored-clipping-guard-{index}.bin")
                arrive("frame_ready")
                read_native(expected_field, state)
                report["injected_cases"].append({"name": f"clipping_{name}",
                                                  "positions": case_positions,
                                                  "nonzero_cells": sum(value != 0 for value in expected_field),
                                                  "guards_unchanged": True, "pass": True})
            monitor.run(f"delete {add_checkpoint}")
            monitor.run(f"delete {map_checkpoint}")
            start_checkpoint = monitor.checkpoint(labels["frame_start"])
            add_checkpoint = monitor.checkpoint(labels["add_start"])
            state_cases = (
                ("all_near_wrap", (124, 249, 237), 3),
                ("large_update", state_at(1_000_003), 3),
                ("period_end", state_at(motion_period - 1), 2),
            )
            for name, initial_state, steps in state_cases:
                arrive("frame_start")
                for counter, value in zip(COUNTER_LABELS, initial_state):
                    monitor.inject(labels[counter], bytes([value]), f"motion-state-{counter}.bin")
                expected_state = initial_state
                observed_states = []
                for offset in range(steps):
                    if offset:
                        arrive("frame_start")
                        expected_state = advance_state(expected_state)
                    arrive("add_start")
                    monitor.inject(labels["brightness_field"], bytes(1000), "motion-zero-field.bin")
                    arrive("frame_ready")
                    expected_field = field_for_positions(positions_for_state(expected_state), kernel)
                    read_native(expected_field, expected_state)
                    observed_states.append(expected_state)
                report["injected_cases"].append({"name": f"motion_state_{name}",
                                                  "field_seed": 0, "seed_stage": "after fade, before ball addition",
                                                  "verified_states": observed_states, "pass": True})
            arrive("frame_start")
            fade_checkpoint = monitor.checkpoint(labels["fade_start"])
            fade_started = arrive("fade_start")
            monitor.run(f"delete {fade_checkpoint}")
            monitor.run("bank ram")
            before_fade = monitor.dump("fade-before.bin", 0, 65535)
            monitor.run("bank cpu")
            fade_state = native_state(before_fade)
            fade_input = bytes(index & 255 for index in range(1000))
            fade_guards = (
                (labels["fade_map"] - 32, bytes([0xa5]) * 32),
                (labels["brightness_field"] + 1000, bytes([0xc7]) * 24),
                (labels["brightness_field"] + 1024, bytes([0xd3]) * 1024),
            )
            monitor.inject(labels["brightness_field"], fade_input, "fade-input.bin")
            for guard_index, (address, sentinel) in enumerate(fade_guards):
                monitor.inject(address, sentinel, f"fade-guard-{guard_index}.bin")
            faded_at = arrive("add_start")
            monitor.run("bank ram")
            after_fade = monitor.dump("fade-after.bin", 0, 65535)
            monitor.run("bank cpu")
            expected_faded = bytes(max(0, value - 1) for value in fade_input)
            field_address = labels["brightness_field"]
            if after_fade[field_address:field_address + 1000] != expected_faded:
                raise AssertionError("Native fade must map every byte to max(0, value - 1).")
            for guard_index, (address, sentinel) in enumerate(fade_guards):
                if after_fade[address:address + len(sentinel)] != sentinel:
                    raise AssertionError("Native fade wrote outside its 1000 logical cells.")
                monitor.inject(address, before_fade[address:address + len(sentinel)],
                               f"restored-fade-guard-{guard_index}.bin")
            arrive("frame_ready")
            expected_field = field_for_positions(positions_for_state(fade_state), kernel, expected_faded)
            read_native(expected_field, fade_state)
            report["injected_cases"].append({"name": "fade_every_byte_with_zero_floor",
                                              "values_tested": list(range(256)),
                                              "boundary_outputs": {"0": 0, "1": 0, "255": 254},
                                              "guards_unchanged": True,
                                              "fade_start": fade_started, "fade_end": faded_at,
                                              "fade_cycles": faded_at["clock"] - fade_started["clock"],
                                              "pass": True})
            clear_checkpoints = {name: monitor.checkpoint(labels[name]) for name in ("clear_start", "clear_done")}
            timer_cases = (("equal", 319, 319, False), ("high_byte_decrease", 256, 255, False),
                           ("last_count_before_wrap", 1, 0, False), ("reload_wrap", 0, 319, True))
            for name, previous_count, current_count, expected_clear in timer_cases:
                arrive("frame_start")
                before_case = ram_snapshot("timer-case-before.bin")
                timer_state = native_state(before_case)
                before_count = word(before_case, "reset_count")
                timer_input = bytes((cell * 37 + 19) & 255 for cell in range(1000))
                monitor.inject(labels["brightness_field"], timer_input, "timer-case-input.bin")
                monitor.inject(labels["timer_previous"], previous_count.to_bytes(2, "little"), "timer-case-previous.bin")
                monitor.run("bank io")
                monitor.run(f"> dd06 {current_count & 255:02x} {(current_count >> 8):02x}")
                monitor.run("bank cpu")
                if expected_clear:
                    arrive("clear_start")
                    arrive("clear_done")
                arrive("add_start")
                after_case = ram_snapshot("timer-case-after.bin")
                expected_before_add = bytes(1000) if expected_clear else bytes(max(0, value - 1) for value in timer_input)
                field_address = labels["brightness_field"]
                if after_case[field_address:field_address + 1000] != expected_before_add:
                    raise AssertionError(f"Timer boundary case selected the wrong clear/fade path: {name}.")
                if word(after_case, "reset_count") != before_count + int(expected_clear):
                    raise AssertionError(f"Timer boundary case changed reset count incorrectly: {name}.")
                if word(after_case, "timer_previous") != current_count:
                    raise AssertionError(f"Timer boundary case did not remember the current counter: {name}.")
                arrive("frame_ready")
                expected_field = field_for_positions(positions_for_state(timer_state), kernel, expected_before_add)
                read_native(expected_field, timer_state)
                report["injected_cases"].append({"name": f"timer_boundary_{name}",
                                                  "previous_counter": previous_count,
                                                  "current_counter": current_count,
                                                  "cleared": expected_clear, "pass": True})
            for checkpoint in clear_checkpoints.values():
                monitor.run(f"delete {checkpoint}")
            monitor.run(f"delete {add_checkpoint}")
            monitor.run(f"delete {start_checkpoint}")
            monitor.run(f"delete {ready_checkpoint}")
            samples = report["frames"]
            intervals = [b["frame_ready"]["clock"] - a["frame_ready"]["clock"]
                         for a, b in zip(samples, samples[1:])]
            durations = [round(cycles * 1000 / PAL_CLOCK) for cycles in intervals]
            images[0].resize((640, 400), Image.Resampling.NEAREST).save(
                OUTPUT / "native.gif", save_all=True,
                append_images=[image.resize((640, 400), Image.Resampling.NEAREST) for image in images[1:]],
                duration=durations, loop=0, optimize=False,
                comment=f"{EXCERPT_FRAMES}-frame native excerpt; not the complete motion period".encode())
            images[0].resize((960, 600), Image.Resampling.NEAREST).save(OUTPUT / "native-preview.png")
            report.update({"pass": True, "native_updates_verified": len(samples),
                           "retained_field_history_verified": True,
                           "motion_counter_wraps_verified": True,
                           "field_cells_compared": len(samples) * 1000, "font_unchanged": True,
                           "phase_continuous_font": True,
                           "compute_cycles": {"min": min(s["compute_cycles"] for s in samples),
                                              "max": max(s["compute_cycles"] for s in samples),
                                              "mean": statistics.mean(s["compute_cycles"] for s in samples)},
                           "render_cycles": {"min": min(s["render_cycles"] for s in samples),
                                             "max": max(s["render_cycles"] for s in samples),
                                             "mean": statistics.mean(s["render_cycles"] for s in samples)},
                           "baseline_equivalence": {
                               "checked": False, "frames_compared": 0,
                               "skipped_reason": "Timed reset scene uses an independent clocked-history oracle",
                           },
                           "presentation_cycles": {"min": min(intervals), "max": max(intervals),
                                                   "mean": statistics.mean(intervals)},
                           "measured_fps": PAL_CLOCK / statistics.median(intervals),
                           "native_gif": "native.gif"})
        except Exception as error:
            report["error"] = repr(error)
            raise
        finally:
            if monitor:
                (OUTPUT / "monitor.log").write_text("\n".join(monitor.transcript))
            if connection:
                try:
                    connection.sendall(b"quit\n")
                except OSError:
                    pass
                connection.close()
            if process and process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            report["owned_process_exit_code"] = process.returncode if process else None
            (OUTPUT / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"pass": report["pass"], "excerpt_frames": report["excerpt_frames"],
                      "fps": report["measured_fps"], "verification": str(OUTPUT / "verification.json")}))


if __name__ == "__main__":
    verify()
