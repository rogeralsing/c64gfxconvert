#!/usr/bin/env python3
"""Check a separate ECM plasma against its numeric and PAL VIC-II contracts."""

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
BACKGROUNDS = (4, 10, 7, 1)
FOREGROUND = 6
PAL_CLOCK = 985248
PAL_FRAME_CYCLES = 19656
EXCERPT_FRAMES = 256
SAMPLE_FRAMES = (0, 64, 128, 192, 255)
INITIAL_PHASES = (0x0000, 0x4000, 0x8000, 0xC000, 0x0000)
PHASE_STEPS = (0x013D, 0x00B5, 0xFF6D, 0x0067, 0x0071)
PHASE_LABELS = ("phase_a", "phase_b", "phase_c", "phase_d", "phase_e")
SINE_VALUES = tuple(round(39 * math.sin(math.tau * index / 256)) for index in range(256))

# Reuse only the existing read-only monitor protocol and screenshot comparator.
# Its build entry point and output directory are never invoked or modified.
_spec = importlib.util.spec_from_file_location("ecm_transport", HERE.parent / "ecm-dither/verify.py")
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


def decode_ecm(screen, font, palette):
    image = Image.new("RGB", (320, 200))
    pixels = image.load()
    for cell, code in enumerate(screen):
        foreground = palette[FOREGROUND]
        background = palette[BACKGROUNDS[code >> 6]]
        left, top = cell % 40 * 8, cell // 40 * 8
        for row in range(8):
            bits = font[(code & 63) * 8 + row]
            for column in range(8):
                pixels[left + column, top + row] = foreground if bits & (128 >> column) else background
    return image


def check_font(font):
    if len(font) != 512:
        raise AssertionError("ECM plasma must contain exactly 64 eight-byte glyphs.")
    glyphs = [font[glyph * 8:(glyph + 1) * 8] for glyph in range(64)]
    for glyph, mask in enumerate(glyphs):
        if sum(row.bit_count() for row in mask) != abs(64 - 2 * glyph):
            raise AssertionError(f"Glyph {glyph} violates the full-coverage triangular density ramp.")
        if 0 < glyph <= 32 and any(current & previous != current for current, previous
                                   in zip(mask, glyphs[glyph - 1])):
            raise AssertionError("Descending coverage must remove pixels without relocating them.")
        if glyph > 32 and mask != glyphs[64 - glyph]:
            raise AssertionError("Ascending coverage must retrace the descending nested masks.")
    checkerboards = (bytes([0xaa, 0x55] * 4), bytes([0x55, 0xaa] * 4))
    if glyphs[16] not in checkerboards or glyphs[48] != glyphs[16]:
        raise AssertionError("Both half-coverage phases must use the same one-pixel checkerboard.")
    return {"glyphs": 64, "foreground_set_pixels": [abs(64 - 2 * glyph) for glyph in range(64)],
            "nested_masks": True, "solid_blue_glyph": 0, "pure_background_glyph": 32,
            "checkerboard_glyphs": [16, 48]}


def state_at(frame):
    return tuple((initial + frame * step) % 65536
                 for initial, step in zip(INITIAL_PHASES, PHASE_STEPS))


def advance_state(state):
    return tuple((value + step) % 65536 for value, step in zip(state, PHASE_STEPS))


def phase_field(state):
    """Direct scalar formula, independent of the native row-difference renderer."""
    a, b, c, d, e = (value // 256 for value in state)
    return bytes(
        (SINE_VALUES[(5 * x + a) % 256] + SINE_VALUES[(13 * x + b) % 256]
         + SINE_VALUES[(7 * y + c) % 256] + SINE_VALUES[(17 * y + d) % 256] + e) % 256
        for y in range(25) for x in range(40)
    )


def check_assets():
    font = (OUTPUT / "font.bin").read_bytes()
    font_contract = check_font(font)
    sine = bytes(value & 255 for value in SINE_VALUES)
    if (OUTPUT / "sine.bin").read_bytes() != sine:
        raise AssertionError("Sine asset differs from the independent signed round(39*sin) contract.")
    period = math.lcm(*(65536 // math.gcd(step, 65536) for step in PHASE_STEPS))
    if period != 65536 or state_at(period) != INITIAL_PHASES or state_at(period // 2) == INITIAL_PHASES:
        raise AssertionError("Five phase accumulators must repeat after exactly 65536 updates.")
    return font, sine, font_contract, period


def verify():
    subprocess.run([str(HERE / "build-plasma.sh")], cwd=HERE, check=True)
    font, sine, font_contract, state_period = check_assets()
    labels = {name: int(address, 16) for name, address in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", (OUTPUT / "plasma.sym").read_text())}
    required = ("initialization_done", "frame_start", "frame_presented", "frame_ready",
                "components_ready", "column_values", "row_values", "font", "sine", "front_index",
                *PHASE_LABELS)
    if any(name not in labels for name in required):
        raise AssertionError("Missing native plasma labels required for its boundary proof.")
    palette_path = HERE.parents[1] / "palettes/colodore.vpl"
    palette = [tuple(int(channel, 16) for channel in line.split()[:3])
               for line in palette_path.read_text().splitlines()
               if line.strip() and not line.startswith("#")]
    if len(palette) != 16:
        raise AssertionError("Expected a sixteen-color VIC palette.")
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    program = OUTPUT / "ecm-plasma.prg"
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
              "global_backgrounds": BACKGROUNDS, "static_foreground": FOREGROUND,
              "font_contract": font_contract, "phase_state_period_updates": state_period,
              "full_phase_cycle_verified": False, "excerpt_frames": EXCERPT_FRAMES,
              "frames": [], "screenshots": [], "injected_cases": []}
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
                    raise AssertionError(f"Unexpected native VICE resource {resource}.")
            checkpoints = {name: monitor.checkpoint(labels[name]) for name in
                           ("initialization_done", "frame_start", "frame_presented", "frame_ready")}

            def arrive(name):
                monitor.run("x")
                registers = monitor.registers()
                if registers["pc"] != labels[name]:
                    raise AssertionError(f"Expected {name}; stopped at ${registers['pc']:04x}. "
                                         "An unexpected screen/Color RAM write also fails this boundary.")
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

            guards = ((0x07e8, bytes([0xa5]) * 24), (0x0be8, bytes([0xc7]) * 24))
            screen_cells_compared = 0

            def check_native(state, expected_front, expected_back, expected_front_address=None):
                nonlocal screen_cells_compared
                ram, io = snapshot()
                if state_in(ram) != state:
                    raise AssertionError(f"Native 16-bit phase state differs from {state}.")
                front = ((io[0x18] >> 4) & 15) * 0x400
                if front not in (0x0400, 0x0800) or front != 0x0400 * (1 + ram[labels["front_index"]]):
                    raise AssertionError("Native front index and VIC screen selection disagree.")
                if expected_front_address is not None and front != expected_front_address:
                    raise AssertionError("Double buffering did not alternate screen addresses.")
                back = 0x0c00 - front
                if ram[front:front + 1000] != expected_front:
                    raise AssertionError("Visible screen differs from the independent four-sine phase field.")
                if ram[back:back + 1000] != expected_back:
                    raise AssertionError("Hidden screen differs from the independent four-sine phase field.")
                screen_cells_compared += 2000
                for name, expected in (("font", font), ("sine", sine)):
                    if ram[labels[name]:labels[name] + len(expected)] != expected:
                        raise AssertionError(f"Native {name} changed or loaded incorrectly.")
                if bytes(value & 15 for value in io[0x800:0xc00]) != bytes([FOREGROUND]) * 1024:
                    raise AssertionError("All 1024 Color RAM nibbles must remain fixed blue.")
                if (io[0x11] & 0x7f) != 0x5b or (io[0x16] & 0x1f) != 8:
                    raise AssertionError("Native VIC is not in 40x25 single-color ECM.")
                if (io[0x18] & 14) * 1024 != labels["font"]:
                    raise AssertionError("VIC character memory differs from the verified font.")
                if tuple(value & 15 for value in io[0x21:0x25]) != BACKGROUNDS:
                    raise AssertionError("Native ECM backgrounds differ from purple/pink/yellow/white.")
                if io[0xd00] & 3 != 3 or io[0xd02] & 3 != 3 or io[0x15] != 0:
                    raise AssertionError("VIC bank zero or sprite disable is incorrect.")
                for address, sentinel in guards:
                    if ram[address:address + len(sentinel)] != sentinel:
                        raise AssertionError("Plasma wrote outside a screen's 1000 logical cells.")
                return front, back

            def screenshot(index, screen, name=None):
                path = OUTPUT / (name or f"frame-{index:03d}-vice.png")
                monitor.run(f'scrsh "{path}" 2')
                comparison = ecm_transport.compare_screenshot(path, decode_ecm(screen, font, palette))
                report["screenshots"].append({"index": index, "file": path.name, **comparison})

            initialized = arrive("initialization_done")
            monitor.run(f"delete {checkpoints.pop('initialization_done')}")
            for guard_index, (address, sentinel) in enumerate(guards):
                monitor.inject(address, sentinel, f"screen-guard-{guard_index}.bin")
            color_watch = monitor.checkpoint(0xd800, 0xdbff)
            front_watch = monitor.checkpoint(0x0400, 0x07e7)
            check_native(INITIAL_PHASES, bytes(1000), phase_field(INITIAL_PHASES), 0x0400)
            report["initialization_done"] = initialized
            previous_front = bytes(1000)
            prepared = phase_field(INITIAL_PHASES)
            previous_front_address = 0x0400
            previous_ready = None
            seen_codes = set()
            for index in range(EXCERPT_FRAMES):
                started = arrive("frame_start")
                if previous_ready is not None and started["clock"] <= previous_ready["clock"]:
                    raise AssertionError("The next swap began before the hidden screen was complete.")
                if index - 1 in SAMPLE_FRAMES:
                    screenshot(index - 1, previous_front)
                monitor.run(f"delete {front_watch}")
                presented = arrive("frame_presented")
                if presented["raster"] != 251:
                    raise AssertionError("Screen flip must occur at raster 251 after the visible area.")
                state = state_at(index)
                expected_front_address = 0x0c00 - previous_front_address
                front, back = check_native(state, prepared, previous_front, expected_front_address)
                front_watch = monitor.checkpoint(front, front + 999)
                ready = arrive("frame_ready")
                next_state = state_at(index + 1)
                next_prepared = phase_field(next_state)
                check_native(next_state, prepared, next_prepared, front)
                seen_codes.update(prepared)
                image = decode_ecm(prepared, font, palette)
                images.append(image)
                report["frames"].append({"index": index, "state": state,
                                         "next_state": next_state, "front": front, "back": back,
                                         "screen_sha256": sha256(prepared),
                                         "next_screen_sha256": sha256(next_prepared),
                                         "frame_start": started, "frame_presented": presented,
                                         "frame_ready": ready,
                                         "render_cycles": ready["clock"] - presented["clock"]})
                previous_front, prepared = prepared, next_prepared
                previous_front_address, previous_ready = front, ready
                if (index + 1) % 64 == 0:
                    print(f"Verified {index + 1}/{EXCERPT_FRAMES} native ECM frames.", flush=True)
            final_start = arrive("frame_start")
            screenshot(EXCERPT_FRAMES - 1, previous_front)
            monitor.run(f"delete {front_watch}")

            # Inject independent 16-bit states at the real pre-advance boundary.
            # This reaches carries/borrows/wraps without claiming a 65536-frame run.
            boundary_states = (
                ("low_byte_carries", (0x00ff,) * 5),
                ("all_accumulator_wraps", tuple((-step) & 65535 for step in PHASE_STEPS)),
                ("high_sine_indices", (0xffff,) * 5),
                ("negative_step_borrow", (0x1234, 0xabcd, 0x0092, 0xfeff, 0xff00)),
            )
            current_state = state_at(EXCERPT_FRAMES)
            for case_index, (name, seed) in enumerate(boundary_states):
                if case_index:
                    arrive("frame_start")
                    monitor.run(f"delete {front_watch}")
                arrive("frame_presented")
                current_front = prepared
                front, back = check_native(current_state, current_front, previous_front,
                                           0x0c00 - previous_front_address)
                for phase_name, value in zip(PHASE_LABELS, seed):
                    monitor.inject(labels[phase_name], value.to_bytes(2, "little"), f"{name}-{phase_name}.bin")
                front_watch = monitor.checkpoint(front, front + 999)
                arrive("frame_ready")
                current_state = advance_state(seed)
                prepared = phase_field(current_state)
                check_native(current_state, current_front, prepared, front)
                report["injected_cases"].append({"name": name, "seed_state": seed,
                                                  "advanced_state": current_state,
                                                  "screen_cells_compared": 1000, "pass": True})
                previous_front, previous_front_address = current_front, front

            # A separable ramp reaches every byte code through the actual plotter.
            arrive("frame_start")
            monitor.run(f"delete {front_watch}")
            arrive("frame_presented")
            current_front = prepared
            front, back = check_native(current_state, current_front, previous_front,
                                       0x0c00 - previous_front_address)
            front_watch = monitor.checkpoint(front, front + 999)
            component_checkpoint = monitor.checkpoint(labels["components_ready"])
            arrive("components_ready")
            monitor.run(f"delete {component_checkpoint}")
            monitor.inject(labels["column_values"], bytes(range(40)), "all-codes-columns.bin")
            monitor.inject(labels["row_values"], bytes((40 * row) & 255 for row in range(25)), "all-codes-rows.bin")
            arrive("frame_ready")
            current_state = advance_state(current_state)
            all_codes = bytes(cell & 255 for cell in range(1000))
            check_native(current_state, current_front, all_codes, front)
            arrive("frame_start")
            monitor.run(f"delete {front_watch}")
            arrive("frame_presented")
            front, back = check_native(current_state, all_codes, current_front, back)
            front_watch = monitor.checkpoint(front, front + 999)
            arrive("frame_ready")
            current_state = advance_state(current_state)
            check_native(current_state, all_codes, phase_field(current_state), front)
            arrive("frame_start")
            screenshot("all-256-codes", all_codes, "all-codes-vice.png")
            monitor.run(f"delete {front_watch}")
            report["injected_cases"].append({"name": "every_screen_byte_through_native_plotter_and_VIC",
                                              "values_tested": list(range(256)),
                                              "glyph_background_combinations": 256, "pass": True})
            monitor.run(f"delete {color_watch}")
            for checkpoint in checkpoints.values():
                monitor.run(f"delete {checkpoint}")
            samples = report["frames"]
            intervals = [b["frame_presented"]["clock"] - a["frame_presented"]["clock"]
                         for a, b in zip(samples, samples[1:])]
            origins = [sample["frame_presented"]["clock"]
                       - sample["frame_presented"]["raster"] * 63
                       - sample["frame_presented"]["raster_cycle"] for sample in samples]
            if any(b - a != PAL_FRAME_CYCLES for a, b in zip(origins, origins[1:])):
                raise AssertionError("Native plasma skipped a PAL frame or presented more than once per frame.")
            margins = [b["frame_start"]["clock"] - a["frame_ready"]["clock"]
                       for a, b in zip(samples, samples[1:])]
            margins.append(final_start["clock"] - samples[-1]["frame_ready"]["clock"])
            if min(margins) <= 0:
                raise AssertionError("A hidden-buffer calculation overran its next screen flip.")
            durations = [round(cycles * 1000 / PAL_CLOCK) for cycles in intervals]
            durations.append(durations[-1])
            images[0].resize((640, 400), Image.Resampling.NEAREST).save(
                OUTPUT / "native.gif", save_all=True,
                append_images=[image.resize((640, 400), Image.Resampling.NEAREST) for image in images[1:]],
                duration=durations, loop=0, optimize=False,
                comment=b"256-frame native excerpt; five 16-bit phase accumulators, fixed Color RAM")
            images[0].resize((960, 600), Image.Resampling.NEAREST).save(OUTPUT / "native-preview.png")
            render_cycles = [sample["render_cycles"] for sample in samples]
            report.update({"pass": True, "native_presentations_verified": len(samples),
                           "screen_cells_compared": screen_cells_compared,
                           "natural_screen_codes_seen": sorted(seen_codes),
                           "color_ram_bytes_unchanged": 1024,
                           "color_ram_store_watchpoint": "No CPU stores after initialization",
                           "visible_screen_store_watchpoints": "No CPU stores from presentation to the next swap",
                           "screen_padding_guards_unchanged": True,
                           "presentation_cycles": {"min": min(intervals), "max": max(intervals),
                                                   "mean": statistics.mean(intervals)},
                           "render_cycles": {"min": min(render_cycles), "max": max(render_cycles),
                                             "mean": statistics.mean(render_cycles)},
                           "minimum_cycles_before_next_swap": min(margins),
                           "measured_fps": PAL_CLOCK / statistics.mean(intervals),
                           "every_pal_frame_presented": True, "native_gif": "native.gif"})
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
    print(json.dumps({"pass": report["pass"], "native_frames": report["native_presentations_verified"],
                      "fps": report["measured_fps"], "verification": str(OUTPUT / "verification.json")}))


if __name__ == "__main__":
    verify()
