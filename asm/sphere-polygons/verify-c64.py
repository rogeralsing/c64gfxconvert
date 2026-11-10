#!/usr/bin/env python3
"""Compare live polygon-to-character 6510 rendering with the integer host model."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import statistics
import subprocess
import time

from PIL import Image, ImageChops


HERE = Path(__file__).resolve().parent
PAL_CLOCK = 985248
PAL_FRAME_CYCLES = 19656
MODELS = ("checker", "football")
PROMPT = re.compile(rb"\((?:C|8|9|10|11):\$[0-9a-fA-F]{4}\) $")
STAGES = ("render_start", "geometry_start", "geometry_end", "raster_start",
          "raster_end", "resolve_start", "resolve_end", "render_end", "frame_done")
REQUIRED = set(STAGES) | {
    "model", "angle_yaw", "angle_pitch", "angle_roll", "rotation_mode", "paused", "frame_counter",
    "front_screen_hi", "face_count", "vertex_count", "faces_base",
    "matrix_xx", "matrix_xy", "matrix_xz", "matrix_yx", "matrix_yy", "matrix_yz",
    "matrix_zx", "matrix_zy", "matrix_zz", "normal_depth",
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def labels_from(path):
    labels = {name: int(address, 16) for name, address in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", path.read_text())}
    missing = REQUIRED - labels.keys()
    if missing:
        raise ValueError(f"Missing native labels: {sorted(missing)}")
    return labels


class Monitor:
    def __init__(self, connection):
        self.connection, self.transcript = connection, []
        connection.settimeout(60)
        self.run("r")

    def run(self, command):
        self.connection.sendall((command + "\n").encode())
        response = bytearray()
        needs_registers = command.strip().lower() in ("r", "registers")
        while not PROMPT.search(response) or (needs_registers and not re.search(rb"^\.;", response, re.M)):
            chunk = self.connection.recv(65536)
            if not chunk:
                raise ConnectionError("Owned VICE monitor closed unexpectedly.")
            response.extend(chunk)
        text = response.decode(errors="replace")
        self.transcript.append(command + "\n" + text)
        if re.search(r"ERROR|Unknown command|Unknown resource|Syntax error", text):
            raise RuntimeError(f"VICE rejected {command!r}:\n{text}")
        return text

    def registers(self):
        response = self.run("r")
        match = re.search(r"^\.;([0-9a-fA-F]{4})\s+(.*)$", response, re.M)
        if not match:
            raise RuntimeError(f"Incomplete VICE registers response:\n{response}")
        fields = match[2].split()
        return {"pc": int(match[1], 16), "raster": int(fields[-3]),
                "raster_cycle": int(fields[-2]), "clock": int(fields[-1])}

    def checkpoint(self, address):
        response = self.run(f"break {address:04x}")
        match = re.search(r"BREAK:\s*(\d+)", response)
        if not match:
            raise RuntimeError(f"No breakpoint at ${address:04x}")
        return int(match[1])

    def dump(self, path, first, last):
        self.run(f'bsave "{path.resolve()}" 0 {first:04x} {last:04x}')
        data = path.read_bytes()
        if len(data) != last - first + 1:
            raise RuntimeError(f"Incomplete VICE dump: {path}")
        return data


def connect(process, port):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Owned VICE exited at startup; inspect vice.log.")
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=1)
        except OSError:
            time.sleep(.1)
    raise TimeoutError("Owned VICE monitor did not open in 15 seconds.")


def pixels_from_screen(screen, font):
    pixels = bytearray(64000)
    for cell, code in enumerate(screen):
        x, y = cell % 40 * 8, cell // 40 * 8
        for row in range(8):
            bits = font[code * 8 + row]
            for bit in range(8):
                pixels[(y + row) * 320 + x + bit] = 255 if bits & (128 >> bit) else 0
    return bytes(pixels)


def screenshot_matches(path, pixels):
    image = Image.open(path).convert("RGB")
    target = Image.frombytes("L", (320, 200), pixels).convert("RGB")
    best = None
    for top in range(28, 42):
        for left in range(28, 38):
            diff = ImageChops.difference(image.crop((left, top, left + 320, top + 200)), target)
            if not diff.getbbox():
                return {"origin": [left, top], "mismatched_rgb_bytes": 0, "compared_pixels": 64000}
            histogram = diff.histogram()
            errors = sum(histogram) - histogram[0] - histogram[256] - histogram[512]
            if best is None or errors < best[0]:
                best = (errors, left, top)
    raise AssertionError(f"Native VICE screenshot differs from verified display RAM: {best}")


def summary(values):
    return {"min": min(values), "mean": statistics.mean(values), "max": max(values)}


def state_array(state, key):
    value = state[key]
    if isinstance(value, dict):
        return [value[str(index)] for index in range(len(value))]
    return value


def assert_bytes(actual, expected, name, pose):
    expected = bytes(value & 255 for value in expected)
    if actual != expected:
        mismatches = [(i, a, b) for i, (a, b) in enumerate(zip(actual, expected)) if a != b]
        raise AssertionError(f"{name} mismatch at {pose}: lengths {len(actual)}/{len(expected)}, "
                             f"{len(mismatches)} differing bytes, first {mismatches[:8]}")


def check_faces(ram, labels, state, model):
    expected_count, expected_vertices = (72, 62) if model == 0 else (32, 60)
    face_count, vertex_count = ram[labels["face_count"]], ram[labels["vertex_count"]]
    if (face_count, vertex_count) != (expected_count, expected_vertices):
        raise AssertionError(f"Native mesh is incomplete: {face_count} faces/{vertex_count} vertices")
    base = int.from_bytes(ram[labels["faces_base"]:labels["faces_base"] + 2], "little")
    records = [ram[base + index * 12:base + (index + 1) * 12] for index in range(face_count)]
    sizes, white_count = {}, 0
    coefficients = [ram[labels[key]] for key in ("matrix_zx", "matrix_zy", "matrix_zz")]
    actual_depths = []
    last_white = None
    for index, record in enumerate(records):
        count, color = record[:2]
        if not 3 <= count <= 6 or color not in (0, 1) or any(v >= vertex_count for v in record[5:5 + count]):
            raise AssertionError(f"Invalid native face record {index}")
        sizes[count] = sizes.get(count, 0) + 1
        white_count += color
        depth = sum(ram[(record[2 + axis] << 8) + coefficients[axis]] for axis in range(3)) & 255
        actual_depths.append(depth if depth < 128 else depth - 256)
        if color:
            last_white = index
    if sizes != ({3: 24, 4: 48} if model == 0 else {5: 12, 6: 20}):
        raise AssertionError(f"Native model face kinds changed: {sizes}")
    if white_count != (36 if model == 0 else 20):
        raise AssertionError("Native face colors are incomplete.")
    expected_depths = state_array(state, "faceDepths")
    if actual_depths != expected_depths:
        raise AssertionError("Native product-page backface depths differ from host geometry.")
    if (ram[labels["normal_depth"]] & 255) != (actual_depths[last_white] & 255):
        raise AssertionError("Executed face_front depth differs from host geometry.")
    pointer_address = labels.get("face_ptr", 4)
    final_pointer = int.from_bytes(ram[pointer_address:pointer_address + 2], "little")
    if final_pointer != base + face_count * 12:
        raise AssertionError("Native raster did not traverse all retained face records.")
    return {"face_count": face_count, "vertex_count": vertex_count, "face_sizes": sizes,
            "white_faces": white_count, "front_faces": sum(d < 0 for d in actual_depths),
            "front_white_faces": sum(record[1] and d < 0 for record, d in zip(records, actual_depths)),
            "depths_match": True, "all_face_records_traversed": True,
            "backface_flags_match": True}


def verify(args):
    program, symbols, output = args.program.resolve(), args.symbols.resolve(), args.output.resolve()
    labels = labels_from(symbols)
    expected_font = (HERE / "assets/font.bin").read_bytes()
    if len(expected_font) != 2048:
        raise ValueError("Expected exactly 2,048 immutable font bytes.")
    if not program.is_file() or not args.model.is_file():
        raise FileNotFoundError("Build the PRG and native-model.cjs first.")
    output.mkdir(parents=True, exist_ok=True)
    (output / "verification.json").unlink(missing_ok=True)
    sources = {str(path.relative_to(HERE)): sha256(path.read_bytes()) for path in sorted(HERE.iterdir())
               if path.suffix in (".asm", ".cjs", ".py")}
    palette = HERE.parents[1] / "palettes/colodore.vpl"
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    command = [str(args.vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100",
               "+warp", "+autostart-warp", "+confirmonexit", "-sounddev", "dummy",
               "+refreshonbreak", "+binarymonitor", "-initbreak", "reset",
               "-autostartprgmode", "1", "-autostart", str(program),
               "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", str(palette),
               "-VICIIsaturation", "1000", "-VICIIcontrast", "1000",
               "-VICIIbrightness", "1000", "-VICIIgamma", "1000",
               "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    report = {"pass": False, "program": str(program), "program_sha256": sha256(program.read_bytes()),
              "symbols": str(symbols), "symbols_sha256": sha256(symbols.read_bytes()), "source_sha256": sources,
              "font_sha256": sha256(expected_font), "pal": True, "pal_clock_hz": PAL_CLOCK,
              "pal_frame_cycles": PAL_FRAME_CYCLES, "speed_percent": 100, "warp": False,
              "command": command, "port": port, "models": {}, "axis_probes": {}, "samples": [],
              "measurement": "Live 6510 clocks include VIC stalls; presentation includes raster-wrap wait."}
    process = connection = monitor = None
    pending = None
    with (output / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            report["pid"] = process.pid
            connection = connect(process, port)
            monitor = Monitor(connection)
            monitor.run("sidefx off")
            for resource, expected in (("MachineVideoStandard", 1), ("Speed", 100),
                                       ("InitialWarpMode", 0), ("AutostartWarp", 0)):
                if f"{resource}={expected}" not in monitor.run(f'resourceget "{resource}"'):
                    raise AssertionError(f"Unexpected VICE resource {resource}")
            for address in sorted({labels[name] for name in STAGES}):
                monitor.checkpoint(address)

            def arrive(name, allow_current=True):
                current = monitor.registers()
                if not allow_current or current["pc"] != labels[name]:
                    monitor.run("x")
                    current = monitor.registers()
                if current["pc"] != labels[name]:
                    raise AssertionError(f"Expected {name} ${labels[name]:04x}, stopped ${current['pc']:04x}")
                return current

            def capture_previous(registers):
                nonlocal pending
                if pending is None or registers["clock"] - pending[0]["frame_done"]["clock"] < PAL_FRAME_CYCLES:
                    return
                sample, pixels = pending
                screenshot = output / f"{sample['name']}-vice.png"
                monitor.run(f'scrsh "{screenshot}" 2')
                sample["screenshot"] = screenshot.name
                sample["screenshot_sha256"] = sha256(screenshot.read_bytes())
                sample["screenshot_comparison"] = screenshot_matches(screenshot, pixels)
                sample["screenshot_capture_clock"] = registers["clock"]
                pending = None

            runs = [(0, args.frames, "animation", None), (1, args.football_frames, "animation", None)]
            if not args.skip_axis_probes:
                fixed = {"mode": 0, "paused": 1, "poses": [(0, 0, 0), (0, 0, 64), (37, 61, 93), None]}
                runs.extend([(0, 4, "fixed-orientation", fixed), (1, 4, "fixed-orientation", fixed)])
                runs.extend((0, 2, name, {"mode": mode, "paused": 0, "poses": [(37, 61, 93), None]})
                            for mode, name in ((1, "yaw-only"), (2, "pitch-only"), (3, "roll-only")))
            for model, count, run_name, configuration in runs:
                previous_done = None
                images = []
                for index in range(count):
                    if report["samples"]:
                        monitor.run(f"> {labels['model']:04x} {model:02x}")
                    if configuration is not None:
                        rotation_mode, expected_paused = configuration["mode"], configuration["paused"]
                        target = configuration["poses"][index]
                        if target is not None:
                            monitor.run(f"> {labels['rotation_mode']:04x} {rotation_mode:02x}")
                            monitor.run(f"> {labels['paused']:04x} {expected_paused:02x}")
                            step = (0, 0, 0) if expected_paused else ((2, 1, 1), (2, 0, 0), (0, 1, 0), (0, 0, 1))[rotation_mode]
                            # The previous frame_done has not yet advanced the
                            # angles. Compensate so this next render gets target.
                            for axis, value, advance in zip(("yaw", "pitch", "roll"), target, step):
                                monitor.run(f"> {labels['angle_' + axis]:04x} {(value - advance) & 255:02x}")
                    else:
                        rotation_mode, expected_paused = 0, 0
                    stage = {}
                    for position, name in enumerate(STAGES):
                        stage[name] = arrive(name, allow_current=position != 0)
                        if name == "resolve_end":
                            capture_previous(stage[name])
                    # At raster zero the framebuffer can still contain the
                    # previous front screen. Deferred capture verifies it before
                    # this new front has begun a scan, if the render was short.
                    capture_previous(stage["frame_done"])
                    name = f"{MODELS[model]}-frame-{index:02d}" if run_name == "animation" else f"{MODELS[model]}-{run_name}-{index:02d}"
                    monitor.run("bank ram")
                    ram = monitor.dump(output / f"{name}-ram.bin", 0, 65535)
                    monitor.run("bank io")
                    vic = monitor.dump(output / f"{name}-vic.bin", 0xd000, 0xd03f)
                    colors = monitor.dump(output / f"{name}-colors.bin", 0xd800, 0xdbe7)
                    cia2 = monitor.dump(output / f"{name}-cia2.bin", 0xdd00, 0xdd00)[0]
                    monitor.run("bank cpu")
                    if ram[labels["model"]] != model or ram[labels["paused"]] != expected_paused or ram[labels["rotation_mode"]] != rotation_mode:
                        raise AssertionError("Native model selection or pause state changed unexpectedly.")
                    yaw, pitch, roll = (ram[labels["angle_" + axis]] for axis in ("yaw", "pitch", "roll"))
                    pose = f"{MODELS[model]} yaw{yaw} pitch{pitch} roll{roll}"
                    if configuration is not None and configuration["poses"][index] is not None and (yaw, pitch, roll) != configuration["poses"][index]:
                        raise AssertionError(f"Native fixed-pose probe did not reach its requested angles: {pose}")
                    front = ram[labels["front_screen_hi"]] << 8
                    if front not in (0x0400, 0x0c00) or (vic[0x18] >> 4) * 0x400 != front:
                        raise AssertionError("VIC front buffer differs from native front_screen_hi.")
                    if (cia2 & 3) != 3 or (vic[0x18] & 14) * 0x400 != 0x2000 or vic[0x11] & 0x60 or vic[0x16] & 0x10:
                        raise AssertionError("VIC is not using fixed hires font $2000 in bank zero.")
                    if (vic[0x11] & 0x18) != 0x18 or not vic[0x16] & 8 or any((c & 15) != 1 for c in colors):
                        raise AssertionError("Expected a white 40×25 hires character screen.")
                    font, screen = ram[0x2000:0x2800], ram[front:front + 1000]
                    assert_bytes(font, expected_font, "font", pose)
                    (output / f"{name}-screen.bin").write_bytes(screen)
                    expected_path, state_path = output / f"{name}-expected.bin", output / f"{name}-state.json"
                    host = subprocess.run([args.node, str(args.model.resolve()), str(model), str(yaw), str(pitch),
                                           str(expected_path), "--state", str(state_path), "--roll", str(roll)], cwd=HERE,
                                          capture_output=True, text=True)
                    if host.returncode:
                        raise RuntimeError(f"Host model rejected {pose}: {host.stderr or host.stdout}")
                    state = json.loads(state_path.read_text())
                    if state.get("roll") != roll:
                        raise AssertionError("Host model did not use native roll.")
                    assert_bytes(screen, expected_path.read_bytes(), "screen", pose)
                    assert_bytes(ram[0x1000:0x13e8], state_array(state, "coverage")[:1000], "coverage", pose)
                    assert_bytes(ram[0x1400:0x1440], state_array(state, "projectedX"), "projected X", pose)
                    assert_bytes(ram[0x1440:0x1480], state_array(state, "projectedY"), "projected Y", pose)
                    for key in ("xx", "xy", "xz", "yx", "yy", "yz", "zx", "zy", "zz"):
                        if ram[labels["matrix_" + key]] != (state["matrix"][key] & 255):
                            raise AssertionError(f"Native rotation matrix {key} differs from host at {pose}")
                    face_checks = check_faces(ram, labels, state, model)
                    pixels = pixels_from_screen(screen, font)
                    for y in range(200):
                        for x in range(320):
                            if pixels[y * 320 + x] and (x - 160) ** 2 + (y - 100) ** 2 > 94 ** 2:
                                raise AssertionError(f"Native polygon sphere spills outside circle at ({x},{y}), {pose}")
                    cycles = {key: stage[key + "_end"]["clock"] - stage[key + "_start"]["clock"]
                              for key in ("render", "geometry", "raster", "resolve")}
                    if any(value <= 0 for value in cycles.values()):
                        raise AssertionError(f"Native cycle region did not advance: {cycles}")
                    shown = stage["frame_done"]["clock"]
                    sample = {"name": name, "run": run_name, "model": model, "index": index, "yaw": yaw, "pitch": pitch,
                              "roll": roll, "rotation_mode": rotation_mode, "paused": expected_paused,
                              "frame_counter": int.from_bytes(ram[labels["frame_counter"]:labels["frame_counter"] + 2], "little"),
                              "front_screen": f"${front:04x}", "frame_done": stage["frame_done"], "stages": stage,
                              "cycles": cycles, "presentation_cycles": None if previous_done is None else shown - previous_done,
                              "screen_match": True, "coverage_match": True, "projection_match": True,
                              "font_match": True, "silhouette_spill_pixels": 0, "faces": face_checks,
                              "screen_sha256": sha256(screen), "font_sha256": sha256(font),
                              "ram": f"{name}-ram.bin", "screen": f"{name}-screen.bin", "expected": expected_path.name,
                              "state": state_path.name, "vic_d011": vic[0x11], "vic_d016": vic[0x16], "vic_d018": vic[0x18]}
                    images.append(Image.frombytes("L", (320, 200), pixels).convert("RGB"))
                    if pending is not None:
                        raise AssertionError("Previous screenshot was not scanned before the next front presentation.")
                    if index in {0, count // 2, count - 1}:
                        pending = (sample, pixels)
                    report["samples"].append(sample)
                    previous_done = shown
                    print(json.dumps({"model": MODELS[model], "run": run_name, "frame": index, "yaw": yaw, "pitch": pitch, "roll": roll,
                                      "cycles": cycles, "screen_match": True}), flush=True)

                samples = [sample for sample in report["samples"] if sample["model"] == model and sample["run"] == run_name]
                for before, after in zip(samples, samples[1:]):
                    if (after["frame_counter"] - before["frame_counter"]) & 65535 != 1:
                        raise AssertionError("Frame counter does not advance once per completed frame.")
                    if run_name != "fixed-orientation":
                        expected = ((2, 1, 1), (2, 0, 0), (0, 1, 0), (0, 0, 1))[rotation_mode]
                        actual = tuple((after[axis] - before[axis]) & 255 for axis in ("yaw", "pitch", "roll"))
                        if actual != expected:
                            raise AssertionError(f"Native independent-axis update failed: {run_name}, {actual} != {expected}")
                if run_name == "fixed-orientation":
                    initial = (output / samples[0]["ram"]).read_bytes()
                    quarter = (output / samples[1]["ram"]).read_bytes()
                    vertices = 62 if model == 0 else 60
                    turns = [all(quarter[0x1400 + i] == 160 + direction * (initial[0x1440 + i] - 100)
                                 and quarter[0x1440 + i] == 100 - direction * (initial[0x1400 + i] - 160)
                                 for i in range(vertices)) for direction in (1, -1)]
                    if not any(turns):
                        raise AssertionError("Pure roll64 does not independently rotate native projected vertices by 90 degrees.")
                    if samples[2]["screen_sha256"] != samples[3]["screen_sha256"] or any(samples[2][a] != samples[3][a] for a in ("yaw", "pitch", "roll")):
                        raise AssertionError("Paused arbitrary orientation did not stay fixed without rewriting its angles.")
                cadence = [sample["presentation_cycles"] for sample in samples if sample["presentation_cycles"] is not None]
                if any(value <= 0 for value in cadence):
                    raise AssertionError("Presentation clock did not advance.")
                mean_cadence = statistics.mean(cadence)
                gif = output / (f"{MODELS[model]}-native.gif" if run_name == "animation" else f"{MODELS[model]}-{run_name}.gif")
                durations = [max(10, round((sample["presentation_cycles"] or mean_cadence) * 1000 / PAL_CLOCK)) for sample in samples]
                images[0].resize((640, 400), Image.Resampling.NEAREST).save(
                    gif, save_all=True, append_images=[image.resize((640, 400), Image.Resampling.NEAREST) for image in images[1:]],
                    duration=durations, loop=0, optimize=False)
                result = {"frames": count, "cycles": {
                    region: summary([sample["cycles"][region] for sample in samples])
                    for region in ("render", "geometry", "raster", "resolve")},
                    "presentation_cycles": summary(cadence), "measured_fps": PAL_CLOCK / statistics.median(cadence),
                    "mean_cadence_fps": PAL_CLOCK / mean_cadence, "gif": gif.name,
                    "screen_bytes_compared": count * 1000, "font_bytes_compared": count * 2048,
                    "coverage_bytes_compared": count * 1000, "projection_bytes_compared": count * 128}
                if run_name == "animation":
                    report["models"][MODELS[model]] = result
                else:
                    report["axis_probes"][f"{MODELS[model]}-{run_name}"] = result
            if pending is not None:
                for name in STAGES:
                    registers = arrive(name, allow_current=name != "render_start")
                    if name in ("resolve_end", "frame_done"):
                        capture_previous(registers)
                if pending is not None:
                    raise AssertionError("Final front screen was never scanned for screenshot capture.")
            for relative, digest in sources.items():
                if sha256((HERE / relative).read_bytes()) != digest:
                    raise AssertionError(f"Source changed during native verification: {relative}")
            if sha256(program.read_bytes()) != report["program_sha256"]:
                raise AssertionError("PRG changed during native verification.")
            report.update({"pass": True, "font_unchanged": True, "all_screens_match_native_model": True,
                           "all_coverage_matches": True, "all_projected_vertices_match": True,
                           "all_lit_pixels_inside_circle": True, "all_mesh_faces_retained": True,
                           "three_axis_rotation_verified": not args.skip_axis_probes,
                           "independent_quarter_turn_verified": not args.skip_axis_probes})
        except KeyboardInterrupt:
            report["interrupted"] = True
            report["error"] = "Verification interrupted; completed sample evidence preserved."
            raise
        except Exception as error:
            report["error"] = repr(error)
            raise
        finally:
            if monitor:
                (output / "monitor.log").write_text("\n".join(monitor.transcript))
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
            (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"pass": report["pass"], "verification": str(output / "verification.json"),
                      "models": report["models"]}), flush=True)


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, default=HERE / "build/polygon-spheres.prg")
    parser.add_argument("--symbols", type=Path, default=HERE / "build/main.sym")
    parser.add_argument("--model", type=Path, default=HERE / "native-model.cjs")
    parser.add_argument("--output", type=Path, default=HERE / "build/verification")
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    parser.add_argument("--node", default="node")
    parser.add_argument("--frames", type=int, default=16)
    parser.add_argument("--football-frames", type=int)
    parser.add_argument("--skip-axis-probes", action="store_true", help="Diagnostic run without additional fixed-pose and independent-axis probes")
    args = parser.parse_args()
    if args.football_frames is None:
        args.football_frames = args.frames
    if args.frames < 2 or args.football_frames < 2:
        parser.error("Both models need at least two frames for presentation cadence.")
    return args


if __name__ == "__main__":
    verify(arguments())
