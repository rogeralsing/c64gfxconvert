#!/usr/bin/env python3
"""Verify two numeric viewports and their actual PAL ECM presentation."""

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import socket
import statistics
import subprocess

from PIL import Image


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "build"
COLOR_STREAM = (6, 11, 4, 12, 10, 15, 7, 1, 13, 3, 14, 4, 11)
PALETTE_HOLD_UPDATES = 125
PALETTE_RAMPS = tuple(tuple(COLOR_STREAM[(offset + band) % len(COLOR_STREAM)]
                            for band in range(5)) for offset in range(len(COLOR_STREAM)))
BACKGROUNDS = PALETTE_RAMPS[0][:-1]
FOREGROUNDS = PALETTE_RAMPS[0][1:]
PAL_CLOCK = 985248
PAL_FRAME_CYCLES = 19656
MAP_WIDTH, MAP_HEIGHT = 80, 50
WIDTH, HEIGHT = 40, 25
SOURCE_PITCH = 128
TRANSPOSED_PITCH = 64
PADDING_BYTE = 0xcd
EXCERPT_FRAMES = 256
SAMPLE_FRAMES = (0, 64, 128, 192, 255)
INITIAL_PHASES = (0x0000, 0x4000, 0x8000, 0xC000)
PHASE_STEPS = (0x013D, 0x00B5, 0xFF6D, 0x0067)
PHASE_LABELS = ("phase_a", "phase_b", "phase_c", "phase_d")
INITIAL_WAVES = (0, 64)
WAVE_STEPS = (2, 3)
WAVE_LABELS = ("wave_phase_a", "wave_phase_b")
WAVE_VALUES = tuple(tuple(round(amplitude * math.sin(math.tau * index / 256))
                          for index in range(256)) for amplitude in (4, 3))
LOBES = (
    ((12, 10, 7, 6, 1.0), (35, 10, 3, 3, 0.9), (64, 10, 10, 7, 0.95),
     (23, 31, 12, 9, 0.7), (52, 29, 5, 5, 1.05), (73, 35, 3, 4, 0.85),
     (7, 44, 3, 3, 0.8), (44, 47, 6, 4, 0.85), (78, 50, 8, 6, 0.55)),
    ((7, 15, 3, 4, 0.9), (25, 8, 9, 6, 0.95), (49, 10, 4, 3, 1.0),
     (71, 19, 8, 10, 0.85), (17, 36, 6, 7, 1.0), (42, 30, 12, 9, 0.72),
     (59, 43, 3, 3, 0.9), (78, 48, 5, 4, 0.75), (36, 49, 4, 4, 0.8)),
)

_spec = importlib.util.spec_from_file_location("ecm_transport", HERE / "vice_transport.py")
ecm_transport = importlib.util.module_from_spec(_spec)
exec(compile(Path(_spec.origin).read_text(), _spec.origin, "exec"), ecm_transport.__dict__)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class Monitor(ecm_transport.Monitor):
    def dump(self, name, first, last):
        path = OUTPUT / name
        self.run(f'bsave "{path}" 0 {first:04x} {last:04x}')
        data = path.read_bytes()
        if len(data) != last - first + 1:
            raise AssertionError(f"Incomplete native memory dump: {path}")
        return data

    def registers(self):
        response = self.run("r")
        match = re.search(r"^\.;([0-9a-fA-F]{4})\s+(.*)$", response, re.M)
        if not match:
            raise AssertionError(f"Incomplete VICE registers response: {response}")
        fields = match[2].split()
        return {"pc": int(match[1], 16), "raster": int(fields[-3]),
                "raster_cycle": int(fields[-2]), "clock": int(fields[-1])}

    def checkpoint(self, address, last=None):
        command = (f"break {address:04x}" if last is None
                   else f"watch store {address:04x} {last:04x}")
        response = self.run(command)
        match = re.search(r"(?:BREAK|WATCH):\s*(\d+)", response)
        if not match:
            raise AssertionError(f"VICE did not create checkpoint: {response}")
        return int(match[1])

    def inject(self, address, data, name):
        path = OUTPUT / name
        path.write_bytes(data)
        self.run("bank ram")
        self.run(f'bload "{path}" 0 {address:04x}')
        self.run("bank cpu")



def decode_ecm(field, font, palette, palette_index=0):
    image = Image.new("RGB", (320, 200))
    pixels = image.load()
    for cell, value in enumerate(field):
        foreground = palette[PALETTE_RAMPS[palette_index][1 + (value >> 6)]]
        background = palette[PALETTE_RAMPS[palette_index][value >> 6]]
        left, top = cell % WIDTH * 8, cell // WIDTH * 8
        for row in range(8):
            bits = font[(value & 63) * 8 + row]
            for column in range(8):
                pixels[left + column, top + row] = foreground if bits & (128 >> column) else background
    return image


def check_font(font):
    if len(font) != 512:
        raise AssertionError("ECM viewports require 64 eight-byte glyphs.")
    glyphs = [font[index * 8:(index + 1) * 8] for index in range(64)]
    for index, glyph in enumerate(glyphs):
        if sum(row.bit_count() for row in glyph) != (index if index < 63 else 64):
            raise AssertionError("The 64-glyph font must monotonically span empty to solid.")
        if index and any(previous & current != previous
                         for previous, current in zip(glyphs[index - 1], glyph)):
            raise AssertionError("Successive dither masks must preserve previously set pixels.")
    if glyphs[32] != bytes([0xaa, 0x55] * 4):
        raise AssertionError("Glyph 32 must retain the original 50% checkerboard.")


def wave_origins(offsets, waves):
    ax, _, _, by = offsets
    rows = tuple(min(40, max(0, ax + sum(WAVE_VALUES[0][(phase + 8 * row) % 256]
                                      for phase in waves)))
                 for row in range(HEIGHT))
    columns = tuple(min(25, max(0, by + sum(WAVE_VALUES[1][(phase + 6 * column) % 256]
                                         for phase in waves)))
                    for column in range(WIDTH))
    return rows, columns


def field_for_offsets(map_a, map_b, offsets, waves):
    """Direct scalar window sampling; no retained state or native address arithmetic."""
    ax, ay, bx, by = offsets
    if not all(0 <= value <= limit for value, limit in zip(offsets, (40, 25, 40, 25))):
        raise AssertionError("A 40x25 viewport must stay within each 80x50 numeric map.")
    row_x, column_y = wave_origins(offsets, waves)
    values = []
    for y in range(HEIGHT):
        for x in range(WIDTH):
            total = (map_a[(ay + y) * MAP_WIDTH + row_x[y] + x]
                     + map_b[(column_y[x] + y) * MAP_WIDTH + bx + x])
            if not 0 <= total <= 255:
                raise AssertionError("The numeric map contract must keep every sum within one byte.")
            values.append(total)
    return bytes(values)


def state_at(frame):
    return tuple((initial + frame * step) % 65536
                 for initial, step in zip(INITIAL_PHASES, PHASE_STEPS))


def advance_state(state):
    return tuple((value + step) % 65536 for value, step in zip(state, PHASE_STEPS))


def waves_at(frame):
    return tuple((initial + frame * step) % 256 for initial, step in zip(INITIAL_WAVES, WAVE_STEPS))


def advance_waves(waves):
    return tuple((value + step) % 256 for value, step in zip(waves, WAVE_STEPS))


def offsets_for_state(state):
    values = []
    for axis, phase in enumerate(state):
        midpoint = 20 if axis % 2 == 0 else 12.5
        values.append(round(midpoint * (1 + math.sin(math.tau * (phase >> 8) / 256))))
    return tuple(values)


def numeric_map(lobes, peak):
    raw = []
    for y in range(MAP_HEIGHT):
        for x in range(MAP_WIDTH):
            raw.append(sum(weight * math.exp(-0.5 * (((x - cx) / sx) ** 2 + ((y - cy) / sy) ** 2))
                           for cx, cy, sx, sy, weight in lobes))
    maximum = max(raw)
    return bytes(round(peak * value / maximum) for value in raw)


def padded_map(logical):
    return b"".join(logical[row * MAP_WIDTH:(row + 1) * MAP_WIDTH]
                    + bytes([PADDING_BYTE]) * (SOURCE_PITCH - MAP_WIDTH)
                    for row in range(MAP_HEIGHT))


def transposed_map(logical):
    return b"".join(bytes(logical[row * MAP_WIDTH + column] for row in range(MAP_HEIGHT))
                    + bytes([PADDING_BYTE]) * (TRANSPOSED_PITCH - MAP_HEIGHT)
                    for column in range(MAP_WIDTH))


def check_assets():
    maps = tuple(numeric_map(lobes, peak) for lobes, peak in zip(LOBES, (127, 128)))
    padded = padded_map(maps[0]), transposed_map(maps[1])
    for name, logical, physical in zip(("a", "b"), maps, padded):
        if (OUTPUT / f"map-{name}.bin").read_bytes() != physical:
            raise AssertionError(f"Map {name.upper()} differs from its independent normalized Gaussian formula or padding.")
        if (OUTPUT / f"map-{name}-logical.bin").read_bytes() != logical:
            raise AssertionError(f"Map {name.upper()}'s logical review copy differs from its 80x50 values.")
    font = (OUTPUT / "font.bin").read_bytes()
    check_font(font)
    original_font = HERE / "accepted-metaball-font.bin"
    if font != original_font.read_bytes():
        raise AssertionError("The separate viewport experiment must retain the accepted metaball font exactly.")
    colors = bytes(FOREGROUNDS[value >> 6] for value in range(256))
    if (OUTPUT / "color.bin").read_bytes() != colors:
        raise AssertionError("The foreground lookup must preserve four complete 64-value color intervals.")
    if (OUTPUT / "color-stream.bin").read_bytes() != bytes(COLOR_STREAM + COLOR_STREAM[:4]):
        raise AssertionError("The automatic stream must retain the approved order and wrapped five-color windows.")
    motion = tuple(bytes(round(span / 2 + span / 2 * math.sin(math.tau * index / 256))
                         for index in range(256)) for span in (40, 25))
    for axis, expected in zip(("x", "y"), motion):
        if (OUTPUT / f"motion-{axis}.bin").read_bytes() != expected:
            raise AssertionError(f"The {axis}-axis camera table differs from the independent bounded sine formula.")
    waves = tuple(bytes(value & 255 for value in table) for table in WAVE_VALUES)
    for axis, expected in zip(("x", "y"), waves):
        if (OUTPUT / f"wave-{axis}.bin").read_bytes() != expected:
            raise AssertionError(f"The signed {axis}-wave table differs from its independent sine formula.")
    period = math.lcm(*(65536 // math.gcd(step, 65536) for step in PHASE_STEPS))
    if (period != 65536 or state_at(period) != INITIAL_PHASES or waves_at(period) != INITIAL_WAVES
            or waves_at(256) != INITIAL_WAVES or waves_at(128) == INITIAL_WAVES):
        raise AssertionError("Camera phases must repeat after 65,536 updates and the two wave cursors after 256.")
    return maps, padded, font, colors, motion, waves, period


def verify():
    subprocess.run([str(HERE / "build-viewports.sh")], cwd=HERE, check=True)
    maps, physical_maps, font, color_map, motion, wave_tables, state_period = check_assets()
    labels = {name: int(address, 16) for name, address in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", (OUTPUT / "viewports.sym").read_text())}
    required = ("initialization_done", "frame_start", "compose_start", "compose_done",
                "presentation_start", "frame_ready", "strength_field", "map_a", "map_b",
                "font", "color_map", "motion_x", "motion_y", *PHASE_LABELS,
                "wave_x", "wave_y", "row_x", "column_y", *WAVE_LABELS,
                "camera_a_x", "camera_a_y", "camera_b_x", "camera_b_y", "render_end",
                "color_stream", "palette_index", "palette_ticks", "palette_pending", "palette_cycle_done",
                "palette_lookup_ready", "palette_commit_start", "palette_commit_done",
                *(f"render_row_{row}" for row in range(HEIGHT)))
    if any(name not in labels for name in required):
        raise AssertionError("Missing native viewport labels needed for boundary verification.")
    palette_path = HERE.parents[1] / "palettes/colodore.vpl"
    palette = [tuple(int(channel, 16) for channel in line.split()[:3])
               for line in palette_path.read_text().splitlines()
               if line.strip() and not line.startswith("#")]
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    program = OUTPUT / "ecm-viewports.prg"
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
              "pal": True, "speed_percent": 100, "warp": False, "command": command,
              "numeric_maps": {"logical_size": [80, 50],
                               "physical_layouts": [{"map": "A", "major_axis": "row", "pitch": 128, "bytes": 6400},
                                                    {"map": "B", "major_axis": "column", "pitch": 64, "bytes": 5120}],
                               "padding_byte": PADDING_BYTE, "ranges": [[min(data), max(data)] for data in maps]},
              "field": "Fresh sum of horizontally warped A rows and vertically warped B columns; no retained history",
              "waves": {"initial": INITIAL_WAVES, "steps": WAVE_STEPS,
                        "component_amplitudes": [4, 3], "combined_amplitudes": [8, 6],
                        "combination": "raw sum of both phase cursors, no averaging",
                        "row_phase_step": 8, "column_phase_step": 6,
                        "origin_bounds": [[0, 40], [0, 25]], "joint_wave_period_updates": 256,
                        "native_lookup_copies": 2},
              "global_backgrounds": BACKGROUNDS, "segment_foregrounds": FOREGROUNDS,
              "palette_ramps": PALETTE_RAMPS,
              "palette_cycle": {"method": "automatic five-color sliding stream",
                                "stream": COLOR_STREAM, "hold_updates": PALETTE_HOLD_UPDATES,
                                "updates": []},
              "phase_state_period_updates": state_period, "full_phase_cycle_verified": False,
              "excerpt_frames": EXCERPT_FRAMES, "frames": [], "screenshots": [],
              "row_windows": [], "injected_cases": []}
    images = []
    process, connection, monitor = None, None, None
    with (OUTPUT / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            report["owned_pid"] = process.pid
            connection = ecm_transport.connect_monitor(process, port)
            monitor = Monitor(connection)
            monitor.run("sidefx off")
            for resource, expected in (("MachineVideoStandard", 1), ("Speed", 100),
                                       ("InitialWarpMode", 0), ("AutostartWarp", 0)):
                if f"{resource}={expected}" not in monitor.run(f'resourceget "{resource}"'):
                    raise AssertionError(f"Unexpected VICE resource {resource}.")
            active = {name: monitor.checkpoint(labels[name]) for name in
                      ("initialization_done", "frame_start", "compose_done", "presentation_start", "frame_ready")}

            def arrive(name):
                monitor.run("x")
                registers = monitor.registers()
                if registers["pc"] != labels[name]:
                    raise AssertionError(f"Expected {name}; stopped at ${registers['pc']:04x}. "
                                         "Unexpected map or guard stores also fail this boundary.")
                return registers

            def snapshot():
                monitor.run("bank ram")
                ram = monitor.dump("native-ram.bin", 0, 65535)
                monitor.run("bank io")
                io = monitor.dump("native-io.bin", 0xd000, 0xdfff)
                monitor.run("bank cpu")
                return ram, io

            def state_in(ram):
                return tuple(int.from_bytes(ram[labels[name]:labels[name] + 2], "little")
                             for name in PHASE_LABELS)

            def waves_in(ram):
                return tuple(ram[labels[name]] for name in WAVE_LABELS)

            field_address = labels["strength_field"]
            guards = ((field_address + 1000, bytes([0xc7]) * 24),
                      (field_address + 1024, bytes([0xd3]) * 256),
                      (0x07e8, bytes([0xa5]) * 24))
            field_cells_compared = 0
            projection_cells_compared = 0

            def check_native(expected_field, state, waves, projected=True, expected_maps=physical_maps,
                             palette_index=0, displayed_index=None):
                nonlocal field_cells_compared, projection_cells_compared
                ram, io = snapshot()
                if state_in(ram) != state:
                    raise AssertionError(f"Native phase counters differ from expected state {state}.")
                if waves_in(ram) != waves:
                    raise AssertionError(f"Native wave counters differ from expected state {waves}.")
                if ram[labels["palette_index"]] != palette_index:
                    raise AssertionError("Native palette window differs from the timed sliding-stream contract.")
                camera = tuple(ram[labels[name]] for name in
                               ("camera_a_x", "camera_a_y", "camera_b_x", "camera_b_y"))
                if camera != offsets_for_state(state):
                    raise AssertionError("Native camera positions differ from the independent bounded sine motion.")
                expected_rows, expected_columns = wave_origins(camera, waves)
                if (ram[labels["row_x"]:labels["row_x"] + HEIGHT] != bytes(expected_rows)
                        or ram[labels["column_y"]:labels["column_y"] + WIDTH] != bytes(expected_columns)):
                    raise AssertionError("Native warped source origins differ from independently clamped row/column waves.")
                active_colors = bytes(PALETTE_RAMPS[palette_index][1 + (value >> 6)] for value in range(256))
                for name, expected in (("font", font), ("color_map", active_colors),
                                       ("color_stream", bytes(COLOR_STREAM + COLOR_STREAM[:4])),
                                       ("motion_x", motion[0]), ("motion_y", motion[1]),
                                       ("wave_x", wave_tables[0] * 2), ("wave_y", wave_tables[1] * 2),
                                       ("map_a", expected_maps[0]), ("map_b", expected_maps[1])):
                    if ram[labels[name]:labels[name] + len(expected)] != expected:
                        raise AssertionError(f"Native {name} differs from its verified immutable asset or row padding.")
                field = ram[field_address:field_address + 1000]
                if field != expected_field:
                    different = sum(a != b for a, b in zip(field, expected_field))
                    raise AssertionError(f"Fresh numeric viewport composition differs in {different} cells.")
                field_cells_compared += 1000
                if projected:
                    screen = ram[0x0400:0x07e8]
                    colors = bytes(value & 15 for value in io[0x800:0xbe8])
                    if screen != expected_field or colors != bytes(active_colors[value] for value in expected_field):
                        raise AssertionError("Native screen/Color RAM differs from the full-range arithmetic projection.")
                    projection_cells_compared += 1000
                if (io[0x18] >> 4) * 0x400 != 0x0400 or (io[0x18] & 14) * 1024 != labels["font"]:
                    raise AssertionError("VIC must use fixed screen $0400 and the verified character memory.")
                if (io[0x11] & 0x7f) != 0x5b or (io[0x16] & 0x1f) != 8:
                    raise AssertionError("VIC must use 40x25 single-color ECM.")
                visible_palette = palette_index if displayed_index is None else displayed_index
                if (tuple(value & 15 for value in io[0x21:0x25]) != PALETTE_RAMPS[visible_palette][:-1]
                        or io[0x20] & 15 != COLOR_STREAM[0]):
                    raise AssertionError("Native backgrounds differ from the committed window or the border changed from blue.")
                if io[0xd00] & 3 != 3 or io[0xd02] & 3 != 3 or io[0x15] != 0:
                    raise AssertionError("VIC bank zero or sprite disable is incorrect.")
                for address, sentinel in guards:
                    if ram[address:address + len(sentinel)] != sentinel:
                        raise AssertionError("Viewport composition or projection wrote outside its logical buffer.")
                return field

            def screenshot(index, field, name=None, palette_index=0, state=None, waves=None, kind="baseline"):
                path = OUTPUT / (name or f"frame-{index:03d}-vice.png")
                monitor.run(f'scrsh "{path}" 2')
                comparison = ecm_transport.compare_screenshot(path, decode_ecm(field, font, palette, palette_index))
                report["screenshots"].append({"index": index, "file": path.name,
                                              "palette_index": palette_index, "state": state,
                                              "wave_state": waves, "field_sha256": sha256(field),
                                              "kind": kind, **comparison})

            def row_window(index, presenting):
                points = {name: monitor.checkpoint(labels[name]) for name in
                          (*(f"render_row_{row}" for row in range(HEIGHT)), "render_end")}
                starts = [arrive(f"render_row_{row}") for row in range(HEIGHT)]
                ended = arrive("render_end")
                origin = presenting["clock"] - presenting["raster"] * 63 - presenting["raster_cycle"]
                rows = []
                for row, start in enumerate(starts):
                    end = starts[row + 1] if row + 1 < HEIGHT else ended
                    old_fetch_end = origin + (52 + row * 8) * 63
                    next_fetch_start = origin + PAL_FRAME_CYCLES + (51 + row * 8) * 63
                    if start["clock"] < old_fetch_end or end["clock"] >= next_fetch_start:
                        raise AssertionError(f"Direct renderer overlaps row {row}'s VIC screen/color fetch window.")
                    rows.append({"row": row, "start": start, "end": end,
                                 "after_old_badline_cycles": start["clock"] - old_fetch_end,
                                 "before_next_badline_cycles": next_fetch_start - end["clock"]})
                for checkpoint in points.values():
                    monitor.run(f"delete {checkpoint}")
                report["row_windows"].append({"index": index, "rows": rows})

            next_update = 0
            active_palette = displayed_palette = 0
            cycle_pending = False
            cycle_info = None

            def global_colors(io):
                return tuple(value & 15 for value in io[0x20:0x25])

            def expected_globals(index):
                return (COLOR_STREAM[0], *PALETTE_RAMPS[index][:-1])

            def prepare_cycle():
                nonlocal next_update, active_palette, cycle_pending, cycle_info
                cycled = arrive("palette_cycle_done")
                target = (next_update // PALETTE_HOLD_UPDATES) % len(COLOR_STREAM)
                ticks = PALETTE_HOLD_UPDATES - 1 - next_update % PALETTE_HOLD_UPDATES
                cycle_pending = target != displayed_palette
                ram, io = snapshot()
                actual = tuple(ram[labels[name]] for name in
                               ("palette_index", "palette_ticks", "palette_pending"))
                if actual != (target, ticks, int(cycle_pending)):
                    raise AssertionError("Automatic palette offset/timer did not follow the five-second sliding window.")
                colors = bytes(PALETTE_RAMPS[target][1 + (value >> 6)] for value in range(256))
                if ram[labels["color_map"]:labels["color_map"] + 256] != colors:
                    raise AssertionError("The automatic cycle did not refill every foreground band before composition.")
                if global_colors(io) != expected_globals(displayed_palette):
                    raise AssertionError("The automatic cycle changed visible backgrounds before the previous frame completed.")
                active_palette = target
                cycle_info = {"update": next_update, "offset": target, "window": PALETTE_RAMPS[target],
                              "ticks": ticks, "changed": cycle_pending, "cycle_done": cycled}
                next_update += 1

            def finish_frame(expected_field, state, waves, index=None, capture=None):
                nonlocal displayed_palette
                presenting = arrive("presentation_start")
                if capture is not None:
                    if presenting["clock"] - capture["ready_clock"] < PAL_FRAME_CYCLES:
                        raise AssertionError("Screenshot capture preceded a complete VIC scan of the previous field.")
                    screenshot(capture["index"], capture["field"], capture.get("name"),
                               capture["palette_index"], capture.get("state"), capture.get("waves"),
                               capture.get("kind", "baseline"))
                if presenting["raster"] not in (55, 56):
                    raise AssertionError("Direct rendering must start in its raster55 window.")
                if index in SAMPLE_FRAMES or (isinstance(index, str) and index.startswith("window-")):
                    row_window(index, presenting)
                origin = presenting["clock"] - presenting["raster"] * 63 - presenting["raster_cycle"]
                next_top_fetch = origin + PAL_FRAME_CYCLES + 51 * 63
                if cycle_pending:
                    points = {name: monitor.checkpoint(labels[name]) for name in
                              ("palette_commit_start", "palette_commit_done")}
                    commit_start = arrive("palette_commit_start")
                    check_native(expected_field, state, waves, palette_index=active_palette,
                                 displayed_index=displayed_palette)
                    if not origin + PAL_FRAME_CYCLES <= commit_start["clock"] < next_top_fetch:
                        raise AssertionError("Palette commit must begin in the next top border after rendering.")
                    monitor.run(f"disable {palette_watch}")
                    commit_done = arrive("palette_commit_done")
                    monitor.run(f"enable {palette_watch}")
                    for checkpoint in points.values():
                        monitor.run(f"delete {checkpoint}")
                    ram, io = snapshot()
                    if (global_colors(io) != expected_globals(active_palette)
                            or ram[labels["palette_pending"]] != 0
                            or commit_done["clock"] >= next_top_fetch):
                        raise AssertionError("Palette backgrounds must commit coherently before the next top-row fetch.")
                    cycle_info["commit"] = {"start": commit_start, "done": commit_done,
                        "before_next_top_fetch_cycles": next_top_fetch - commit_done["clock"],
                        "old_globals_preserved_through_render": True}
                    displayed_palette = active_palette
                ready = arrive("frame_ready")
                if not origin + PAL_FRAME_CYCLES <= ready["clock"] < next_top_fetch:
                    raise AssertionError("Direct projection did not complete before the next top-row fetch.")
                check_native(expected_field, state, waves, palette_index=active_palette)
                cycle_info.update({"presentation_start": presenting, "frame_ready": ready,
                                   "pass": True})
                report["palette_cycle"]["updates"].append(cycle_info)
                return presenting, ready, next_top_fetch - ready["clock"]

            arrive("initialization_done")
            monitor.run(f"delete {active.pop('initialization_done')}")
            initial_ram, _ = snapshot()
            for name, expected in (("map_a", physical_maps[0]), ("map_b", physical_maps[1])):
                if initial_ram[labels[name]:labels[name] + len(expected)] != expected:
                    raise AssertionError("Native numeric map assets were not loaded intact.")
            for guard_index, (address, sentinel) in enumerate(guards):
                monitor.inject(address, sentinel, f"buffer-guard-{guard_index}.bin")
            watches = [monitor.checkpoint(labels[name], labels[name] + len(data) - 1)
                       for name, data in zip(("map_a", "map_b"), physical_maps)]
            watches.extend(monitor.checkpoint(address, address + len(sentinel) - 1) for address, sentinel in guards)
            watches.append(monitor.checkpoint(0xdbe8, 0xdbff))
            watches.append(monitor.checkpoint(0xd020, 0xd020))
            palette_watch = monitor.checkpoint(0xd021, 0xd024)
            watches.append(palette_watch)
            cycle_point = monitor.checkpoint(labels["palette_cycle_done"])
            active["palette_cycle_done"] = cycle_point
            keyboard_watch = monitor.run("watch load dc01")
            keyboard_number = re.search(r"WATCH:\s*(\d+)", keyboard_watch)
            if not keyboard_number:
                raise AssertionError("VICE did not install the no-keyboard-polling watchpoint.")
            watches.append(int(keyboard_number[1]))
            pending_capture = None
            for index in range(EXCERPT_FRAMES + 1):
                started = arrive("frame_start")
                prepare_cycle()
                state = state_at(index)
                waves = waves_at(index)
                expected = field_for_offsets(*maps, offsets_for_state(state), waves)
                composed = arrive("compose_done")
                check_native(expected, state, waves, projected=False,
                             palette_index=active_palette, displayed_index=displayed_palette)
                presenting, ready, margin = finish_frame(expected, state, waves, index, pending_capture)
                pending_capture = None
                report["frames"].append({"index": index, "state": state, "wave_state": waves,
                                         "palette_index": active_palette, "palette_changed": cycle_pending,
                                         "offsets": offsets_for_state(state),
                                         "frame_start": started, "compose_done": composed,
                                         "presentation_start": presenting, "frame_ready": ready,
                                         "compose_cycles": composed["clock"] - started["clock"],
                                         "render_cycles": ready["clock"] - presenting["clock"],
                                         "before_next_top_fetch_cycles": margin,
                                         "field_sha256": sha256(expected), "field_match": True,
                                         "projection_match": True})
                if index < EXCERPT_FRAMES:
                    images.append(decode_ecm(expected, font, palette, active_palette))
                if index in SAMPLE_FRAMES:
                    pending_capture = {"index": index, "field": expected, "ready_clock": ready["clock"],
                                       "palette_index": active_palette}
                if index % 64 == 0:
                    print(f"Verified native viewport update {index}/{EXCERPT_FRAMES}.", flush=True)

            natural_changes = [sample for sample in report["palette_cycle"]["updates"] if sample["changed"]]
            natural_intervals = [(right["commit"]["done"]["clock"] - left["commit"]["done"]["clock"]) / PAL_CLOCK
                                 for left, right in zip(natural_changes, natural_changes[1:])]
            if not natural_intervals or any(abs(seconds - 5) > PAL_FRAME_CYCLES / PAL_CLOCK
                                            for seconds in natural_intervals):
                raise AssertionError("Automatic color steps must stay within one PAL field of five seconds.")
            report["palette_cycle"].update({"natural_changes_verified": len(natural_changes),
                "natural_step_intervals_seconds": natural_intervals,
                "measured_step_seconds": statistics.mean(natural_intervals),
                "step_tolerance_seconds": PAL_FRAME_CYCLES / PAL_CLOCK,
                "forced_timer_expiries": []})

            last_state = state_at(EXCERPT_FRAMES)
            last_waves = waves_at(EXCERPT_FRAMES)
            corner_states = [(f"corners_{bits:04b}", tuple((64 if bits & (1 << axis) else 192) << 8
                                                          for axis in range(4))) for bits in range(16)]
            inner_states = []
            for name, offsets in (("inner_edges", (1, 1, 39, 24)), ("opposite_inner_edges", (39, 24, 1, 1))):
                inner_states.append((name, tuple((motion[axis % 2].index(value) << 8) | 0xff
                                                 for axis, value in enumerate(offsets))))
            phase_states = (("low_byte_carries", (0x00ff,) * 4),
                            ("all_phase_wraps", tuple((-step) & 65535 for step in PHASE_STEPS)),
                            ("high_sine_indices", (0xffff,) * 4),
                            ("negative_step_borrow", (0x1234, 0xabcd, 0x0092, 0xfeff)))
            wave_cases = tuple((name, (0,) * 4) for name in
                               ("positive_wave_reinforcement", "negative_wave_reinforcement", "opposite_wave_cancellation"))
            for case_index, (name, seed) in enumerate((*corner_states, *inner_states, *phase_states, *wave_cases)):
                arrive("frame_start")
                prepare_cycle()
                ram, _ = snapshot()
                if state_in(ram) != advance_state(last_state):
                    raise AssertionError("Native phase advancement lost a carry, borrow or16-bit wrap.")
                if waves_in(ram) != advance_waves(last_waves):
                    raise AssertionError("Native wave advancement lost a signed step or byte wrap.")
                for phase_name, value in zip(PHASE_LABELS, seed):
                    monitor.inject(labels[phase_name], value.to_bytes(2, "little"), f"{name}-{phase_name}.bin")
                wave_seed = {"low_byte_carries": (254, 253), "all_phase_wraps": (255, 255),
                             "high_sine_indices": (127, 255), "negative_step_borrow": (0, 2),
                             "positive_wave_reinforcement": (64, 64),
                             "negative_wave_reinforcement": (192, 192),
                             "opposite_wave_cancellation": (64, 192)}.get(
                                 name, (64 if case_index & 2 else 192, 64 if case_index & 4 else 192))
                for wave_name, value in zip(WAVE_LABELS, wave_seed):
                    monitor.inject(labels[wave_name], bytes([value]), f"{name}-{wave_name}.bin")
                dirty = bytes((cell * 37 + case_index * 19) & 255 for cell in range(1000))
                monitor.inject(field_address, dirty, "dirty-field.bin")
                expected = field_for_offsets(*maps, offsets_for_state(seed), wave_seed)
                arrive("compose_done")
                check_native(expected, seed, wave_seed, projected=False,
                             palette_index=active_palette, displayed_index=displayed_palette)
                finish_frame(expected, seed, wave_seed)
                rows, columns = wave_origins(offsets_for_state(seed), wave_seed)
                if name == "positive_wave_reinforcement" and (rows[0], columns[0]) != (28, 18):
                    raise AssertionError("In-phase wave peaks must add raw amplitudes 8 and 6, without averaging.")
                if name == "negative_wave_reinforcement" and (rows[0], columns[0]) != (12, 6):
                    raise AssertionError("In-phase negative wave peaks must add amplitudes -8 and -6.")
                if name == "opposite_wave_cancellation" and (set(rows), set(columns)) != ({20}, {12}):
                    raise AssertionError("Opposite wave cursors must cancel every row and column offset.")
                report["injected_cases"].append({"name": name, "phase_state": seed,
                                                  "wave_state": wave_seed,
                                                  "offsets": offsets_for_state(seed),
                                                  "warped_a_row_origins": rows, "warped_b_column_origins": columns,
                                                  "dirty_input_replaced": True, "pass": True})
                last_state = seed
                last_waves = wave_seed

            # Legal extreme source values verify the optimized once-per-row CLC.
            arrive("frame_start")
            prepare_cycle()
            ram, _ = snapshot()
            if state_in(ram) != advance_state(last_state):
                raise AssertionError("The final injected phase state did not advance across its signed borrow.")
            if waves_in(ram) != advance_waves(last_waves):
                raise AssertionError("The final injected wave state did not advance across its byte wrap.")
            seed = (0xc000,) * 4
            for phase_name, value in zip(PHASE_LABELS, seed):
                monitor.inject(labels[phase_name], value.to_bytes(2, "little"), f"max-{phase_name}.bin")
            wave_seed = (128, 128)
            for wave_name, value in zip(WAVE_LABELS, wave_seed):
                monitor.inject(labels[wave_name], bytes([value]), f"max-{wave_name}.bin")
            compose_point = monitor.checkpoint(labels["compose_start"])
            arrive("compose_start")
            monitor.run(f"delete {compose_point}")
            changed_maps = tuple(bytes([peak, 0]) + logical[2:] for peak, logical in zip((127, 128), maps))
            changed_physical = padded_map(changed_maps[0]), transposed_map(changed_maps[1])
            for name, values in zip(("map_a", "map_b"), changed_physical):
                monitor.inject(labels[name], values, f"max-{name}.bin")
            monitor.inject(field_address, bytes([0xa5]) * 1000, "max-dirty-field.bin")
            expected = field_for_offsets(*changed_maps, (0, 0, 0, 0), wave_seed)
            arrive("compose_done")
            check_native(expected, seed, wave_seed, projected=False, expected_maps=changed_physical,
                         palette_index=active_palette, displayed_index=displayed_palette)
            if expected[:2] != bytes([255, 0]):
                raise AssertionError("Max-sum regression input must exercise255 followed byzero.")
            for name, values in zip(("map_a", "map_b"), physical_maps):
                monitor.inject(labels[name], values, f"restored-{name}.bin")
            finish_frame(expected, seed, wave_seed)
            report["injected_cases"].append({"name": "maximum_sum255_then_zero", "first_cells": [255, 0],
                                              "maps_restored": True, "pass": True})

            # Natural updates above prove the five-second cadence. Explicit
            # timer expiries exercise every remaining window without waiting
            # five seconds per transition; hold frames keep the real timer.
            input_state, input_waves = seed, wave_seed
            pending_capture = None
            all_value_windows, field_windows = set(), set()
            selected_windows = []
            for step in range(len(COLOR_STREAM) * 2 + 1):
                arrive("frame_start")
                all_values = step % 2 == 0
                if all_values:
                    ram, _ = snapshot()
                    aligned_update = ((next_update + PALETTE_HOLD_UPDATES - 1)
                                      // PALETTE_HOLD_UPDATES * PALETTE_HOLD_UPDATES)
                    report["palette_cycle"]["forced_timer_expiries"].append({
                        "from_update": next_update, "observed_timer_before": ram[labels["palette_ticks"]],
                        "expired_timer": 0, "aligned_model_update": aligned_update})
                    monitor.inject(labels["palette_ticks"], b"\0", f"window-{step}-expire-timer.bin")
                    next_update = aligned_update
                prepare_cycle()
                state, waves = advance_state(input_state), advance_waves(input_waves)
                expected = field_for_offsets(*maps, offsets_for_state(state), waves)
                arrive("compose_done")
                check_native(expected, state, waves, projected=False,
                             palette_index=active_palette, displayed_index=displayed_palette)
                if all_values:
                    expected = bytes(cell & 255 for cell in range(1000))
                    monitor.inject(field_address, expected, f"window-{active_palette}-all-values.bin")
                    selected_windows.append(active_palette)
                kind = "window_all_values" if all_values else "window_field"
                _, ready, _ = finish_frame(expected, state, waves,
                    f"window-{active_palette}" if all_values else None, pending_capture)
                if pending_capture is not None:
                    windows = all_value_windows if pending_capture["kind"] == "window_all_values" else field_windows
                    windows.add(pending_capture["palette_index"])
                pending_capture = {"index": f"window-{active_palette}-{step}", "field": expected,
                    "ready_clock": ready["clock"], "palette_index": active_palette,
                    "state": state, "waves": waves, "kind": kind,
                    "name": f"window-{active_palette}-{kind}-vice.png"}
                input_state, input_waves = state, waves
            if all_value_windows != set(range(len(COLOR_STREAM))) or field_windows != all_value_windows:
                raise AssertionError("Every automatic window must pass all 256 strengths and a normal-field VIC capture.")
            if selected_windows[-1] != selected_windows[0]:
                raise AssertionError("The automatic stream must wrap to its original window after one complete traversal.")
            report["palette_cycle"].update({"pass": True, "selected_sequence": selected_windows,
                "complete_natural_cycles": EXCERPT_FRAMES // (len(COLOR_STREAM) * PALETTE_HOLD_UPDATES),
                "all256_strength_values_verified_each_window": True,
                "backgrounds_only_written_in_safe_commit": True, "keyboard_polls": 0,
                "fixed_border_color": COLOR_STREAM[0], "border_writes_after_initialization": 0})
            report["injected_cases"].append({"name": "every_byte_projection_and_VIC_each_window",
                "windows": len(all_value_windows), "values_tested": list(range(256)), "pass": True})
            for checkpoint in (*active.values(), *watches):
                monitor.run(f"delete {checkpoint}")
            samples = report["frames"]
            intervals = [b["frame_ready"]["clock"] - a["frame_ready"]["clock"]
                         for a, b in zip(samples, samples[1:])]
            durations = [round(cycles * 1000 / PAL_CLOCK) for cycles in intervals]
            images[0].resize((640, 400), Image.Resampling.NEAREST).save(
                OUTPUT / "native.gif", save_all=True,
                append_images=[image.resize((640, 400), Image.Resampling.NEAREST) for image in images[1:]],
                duration=durations, loop=0, optimize=False,
                comment=b"256-frame native viewport excerpt; fresh numeric A+B field")
            images[0].resize((960, 600), Image.Resampling.NEAREST).save(OUTPUT / "native-preview.png")
            report.update({"pass": True, "native_updates_verified": len(samples),
                           "field_cells_compared": field_cells_compared,
                           "projection_cells_compared": projection_cells_compared,
                           "fresh_field_overwrite_verified": True, "immutable_maps_verified": True,
                           "map_row_padding_bytes_preserved": MAP_HEIGHT * (SOURCE_PITCH - MAP_WIDTH),
                           "map_column_padding_bytes_preserved": MAP_WIDTH * (TRANSPOSED_PITCH - MAP_HEIGHT),
                           "wave_counter_wraps_verified": True,
                           "buffer_guards_unchanged": True,
                           "row_fetch_windows_verified": sum(len(sample["rows"]) for sample in report["row_windows"]),
                           "presentation_cycles": {"min": min(intervals), "max": max(intervals),
                                                   "mean": statistics.mean(intervals)},
                           "compose_cycles": {"min": min(s["compose_cycles"] for s in samples),
                                              "max": max(s["compose_cycles"] for s in samples),
                                              "mean": statistics.mean(s["compose_cycles"] for s in samples)},
                           "render_cycles": {"min": min(s["render_cycles"] for s in samples),
                                             "max": max(s["render_cycles"] for s in samples),
                                             "mean": statistics.mean(s["render_cycles"] for s in samples)},
                           "minimum_cycles_before_top_fetch": min(s["before_next_top_fetch_cycles"] for s in samples),
                           "measured_fps": PAL_CLOCK / statistics.mean(intervals), "native_gif": "native.gif"})
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
    print(json.dumps({"pass": report["pass"], "native_updates": report["native_updates_verified"],
                      "fps": report["measured_fps"], "verification": str(OUTPUT / "verification.json")}))


if __name__ == "__main__":
    verify()
