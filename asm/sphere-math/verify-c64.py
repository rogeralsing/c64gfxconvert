#!/usr/bin/env python3
"""Verify live 6510 tile rendering in an owned PAL VICE session."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import statistics
import subprocess
import time

from PIL import Image


HERE = Path(__file__).resolve().parent
PAL_CLOCK = 985248
PAL_FRAME_CYCLES = 19656
PROMPT = re.compile(rb"\((?:C|8|9|10|11):\$[0-9a-fA-F]{4}\) $")
REQUIRED_LABELS = {
    "render_start", "render_end", "frame_done", "spin", "mode", "paused",
    "frame_counter", "front_screen_hi",
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_labels(path):
    labels = {name: int(address, 16) for name, address in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", path.read_text())}
    missing = REQUIRED_LABELS - labels.keys()
    if missing:
        raise ValueError(f"Missing native debug labels: {sorted(missing)}")
    return labels


class Monitor:
    def __init__(self, connection):
        self.connection = connection
        self.transcript = []
        # Synchronize on a real registers response. An unsolicited greeting
        # prompt must not satisfy the first command by itself.
        connection.settimeout(60)
        self.run("r")

    def run(self, command):
        self.connection.sendall((command + "\n").encode())
        response = bytearray()
        needs_registers = command.strip().lower() in ("r", "registers")
        while not PROMPT.search(response) or (
                needs_registers and not re.search(rb"^\.;", response, re.M)):
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
            raise RuntimeError(f"VICE registers response is incomplete:\n{response}")
        fields = match[2].split()
        return {
            "pc": int(match[1], 16), "raster": int(fields[-3]),
            "raster_cycle": int(fields[-2]), "clock": int(fields[-1]),
        }

    def dump(self, path, first, last):
        self.run(f'bsave "{path.resolve()}" 0 {first:04x} {last:04x}')
        data = path.read_bytes()
        if len(data) != last - first + 1:
            raise RuntimeError(f"VICE wrote an incomplete dump: {path}")
        return data

    def checkpoint(self, address):
        response = self.run(f"break {address:04x}")
        match = re.search(r"BREAK:\s*(\d+)", response)
        if not match:
            raise RuntimeError(f"VICE did not set breakpoint ${address:04x}.")
        return int(match[1])


def connect_monitor(process, port):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Owned VICE exited during startup; inspect vice.log.")
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=1)
        except OSError:
            time.sleep(0.1)
    raise TimeoutError("Owned VICE did not open its monitor within 15 seconds.")


def pixels_from_screen(screen, font):
    pixels = bytearray(64000)
    for cell, code in enumerate(screen):
        x, y = cell % 40 * 8, cell // 40 * 8
        for row in range(8):
            bits = font[code * 8 + row]
            for bit in range(8):
                pixels[(y + row) * 320 + x + bit] = 255 if bits & (128 >> bit) else 0
    return bytes(pixels)


def compare_screenshot(path, expected):
    image = Image.open(path).convert("RGB")
    expected_image = Image.frombytes("L", (320, 200), expected).convert("RGB")
    target = expected_image.tobytes()
    candidates = []
    for top in range(28, 42):
        for left in range(28, 38):
            crop = image.crop((left, top, left + 320, top + 200)).tobytes()
            different_bytes = sum(a != b for a, b in zip(crop, target))
            candidates.append((different_bytes, left, top))
    different_bytes, left, top = min(candidates)
    if different_bytes:
        raise AssertionError(f"Native screenshot differs from displayed font RAM: {different_bytes} RGB bytes")
    return {"origin": [left, top], "mismatched_rgb_bytes": 0, "compared_pixels": 64000}


def summary(values):
    return {"min": min(values), "mean": statistics.mean(values), "max": max(values)}


def verify(args):
    program, symbols, output = args.program.resolve(), args.symbols.resolve(), args.output.resolve()
    labels = read_labels(symbols)
    expected_font = (HERE / "assets/font.bin").read_bytes()
    if len(expected_font) != 2048:
        raise ValueError("Expected a complete 2,048-byte fixed font.")
    if not program.is_file() or not args.model.is_file():
        raise FileNotFoundError("Build sphere.prg and native-model.cjs before verification.")
    output.mkdir(parents=True, exist_ok=True)
    (output / "verification.json").unlink(missing_ok=True)
    palette = HERE.parents[1] / "palettes/colodore.vpl"
    if not palette.is_file():
        raise FileNotFoundError(palette)
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    command = [
        str(args.vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100",
        "+warp", "+autostart-warp", "+confirmonexit", "-sounddev", "dummy",
        "+refreshonbreak", "+binarymonitor", "-initbreak", "reset",
        "-autostartprgmode", "1", "-autostart", str(program),
        "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", str(palette),
        "-VICIIsaturation", "1000", "-VICIIcontrast", "1000",
        "-VICIIbrightness", "1000", "-VICIIgamma", "1000",
        "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}",
    ]
    monitor, connection, process = None, None, None
    report = {
        "pass": False, "program": str(program), "program_sha256": sha256(program.read_bytes()),
        "symbols": str(symbols), "expected_font_sha256": sha256(expected_font),
        "pal": True, "pal_clock_hz": PAL_CLOCK, "pal_frame_cycles": PAL_FRAME_CYCLES,
        "speed_percent": 100, "warp": False, "command": command, "port": port,
        "measurement": "Live 6510 execution; render clocks include VIC bus stalls. Presentation FPS includes raster-boundary waits.",
        "samples": [], "modes": {},
    }
    images = {0: [], 1: []}
    with (output / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            report["pid"] = process.pid
            connection = connect_monitor(process, port)
            monitor = Monitor(connection)
            monitor.run("sidefx off")
            for resource, expected in [("MachineVideoStandard", 1), ("Speed", 100),
                                       ("InitialWarpMode", 0), ("AutostartWarp", 0)]:
                text = monitor.run(f'resourceget "{resource}"')
                if f"{resource}={expected}" not in text:
                    raise AssertionError(f"Unexpected emulator resource {resource}: {text}")
            for address in sorted({labels[name] for name in ("render_start", "render_end", "frame_done")}):
                monitor.checkpoint(address)

            def arrive(name, allow_current=False):
                if not allow_current or monitor.registers()["pc"] != labels[name]:
                    monitor.run("x")
                registers = monitor.registers()
                if registers["pc"] != labels[name]:
                    raise AssertionError(f"Expected {name} at ${labels[name]:04x}, stopped at ${registers['pc']:04x}")
                return registers

            pending_capture = None

            def capture_previous_front(ended):
                nonlocal pending_capture
                if pending_capture is None:
                    return
                sample, pixels = pending_capture
                # frame_done flips D018 at raster zero. VICE's framebuffer
                # still holds the previous screen there. Wait until the next
                # render has run, while the verified front screen remains
                # selected and has been scanned for at least two PAL fields.
                if ended["clock"] - sample["frame_done"]["clock"] < 2 * PAL_FRAME_CYCLES:
                    raise AssertionError("Render is too short for deferred full-frame screenshot capture.")
                screenshot = output / f"mode-{sample['mode']}-frame-{sample['index']:02d}-vice.png"
                monitor.run(f'scrsh "{screenshot}" 2')
                if not screenshot.is_file():
                    raise RuntimeError("VICE did not write its native screenshot.")
                sample["screenshot"] = screenshot.name
                sample["screenshot_sha256"] = sha256(screenshot.read_bytes())
                sample["screenshot_comparison"] = compare_screenshot(screenshot, pixels)
                sample["screenshot_capture_clock"] = ended["clock"]
                pending_capture = None

            for mode, count in ((0, args.frames), (1, args.sparse_frames)):
                previous_done = None
                for index in range(count):
                    if report["samples"]:
                        monitor.run(f"> {labels['mode']:04x} {mode:02x}")
                    started = arrive("render_start")
                    ended = arrive("render_end")
                    capture_previous_front(ended)
                    shown = arrive("frame_done", allow_current=labels["render_end"] == labels["frame_done"])
                    name = f"mode-{mode}-frame-{index:02d}"
                    monitor.run("bank ram")
                    ram = monitor.dump(output / f"{name}-ram.bin", 0, 65535)
                    monitor.run("bank io")
                    vic = monitor.dump(output / f"{name}-vic.bin", 0xd000, 0xd03f)
                    colors = monitor.dump(output / f"{name}-colors.bin", 0xd800, 0xdbe7)
                    cia2 = monitor.dump(output / f"{name}-cia2.bin", 0xdd00, 0xdd00)[0]
                    monitor.run("bank cpu")
                    if ram[labels["mode"]] != mode:
                        raise AssertionError("Emulator mode does not match the requested algorithm.")
                    if ram[labels["paused"]]:
                        raise AssertionError("Native renderer unexpectedly paused.")
                    spin = ram[labels["spin"]]
                    front = ram[labels["front_screen_hi"]] << 8
                    if front not in (0x0400, 0x0c00):
                        raise AssertionError(f"Invalid front screen ${front:04x}.")
                    if (vic[0x18] >> 4) * 0x400 != front:
                        raise AssertionError("VIC front buffer differs from front_screen_hi.")
                    if (cia2 & 3) != 3:
                        raise AssertionError("VIC is not using bank zero.")
                    if (vic[0x18] & 14) * 0x400 != 0x2000 or vic[0x11] & 0x60 or vic[0x16] & 0x10:
                        raise AssertionError("VIC is not using the fixed hires character font at $2000.")
                    if (vic[0x11] & 0x18) != 0x18 or not (vic[0x16] & 8):
                        raise AssertionError("VIC is not displaying a 40-column, 25-row screen.")
                    if any((color & 15) != 1 for color in colors):
                        raise AssertionError("Color RAM is not fixed white.")
                    actual_font = ram[0x2000:0x2800]
                    if actual_font != expected_font:
                        raise AssertionError("C64 font differs from the immutable mathematical font.")
                    screen = ram[front:front + 1000]
                    (output / f"{name}-screen.bin").write_bytes(screen)
                    expected_file = output / f"{name}-expected.bin"
                    subprocess.run([args.node, str(args.model.resolve()), str(spin), str(mode), str(expected_file)],
                                   cwd=HERE, check=True, capture_output=True, text=True)
                    expected = expected_file.read_bytes()
                    if len(expected) != 1000 or screen != expected:
                        mismatch = sum(a != b for a, b in zip(screen, expected))
                        raise AssertionError(f"Native screen differs from mathematical model: mode {mode}, spin {spin}, {mismatch} cells")
                    pixels = pixels_from_screen(screen, actual_font)
                    # Check actual screen RAM against the geometric silhouette,
                    # independently of whether the host model shares a defect.
                    for y in range(200):
                        for x in range(320):
                            if pixels[y * 320 + x] and (x + 0.5 - 160) ** 2 + (y + 0.5 - 100) ** 2 > 94 ** 2:
                                raise AssertionError(f"Native sphere spills outside its circle at ({x},{y}), mode {mode}, spin {spin}")
                    images[mode].append(Image.frombytes("L", (320, 200), pixels).convert("RGB"))
                    render_cycles = ended["clock"] - started["clock"]
                    if render_cycles <= 0:
                        raise AssertionError("Render cycle count must advance.")
                    sample = {
                        "mode": mode, "index": index, "spin": spin,
                        "frame_counter": int.from_bytes(ram[labels["frame_counter"]:labels["frame_counter"] + 2], "little"),
                        "front_screen": f"${front:04x}", "render_start": started,
                        "render_end": ended, "frame_done": shown,
                        "render_cycles": render_cycles,
                        "presentation_cycles": None if previous_done is None else shown["clock"] - previous_done,
                        "screen_bytes_compared": 1000, "screen_match": True, "font_match": True,
                        "screen_sha256": sha256(screen), "font_sha256": sha256(actual_font),
                        "ram": f"{name}-ram.bin", "screen": f"{name}-screen.bin",
                        "expected": expected_file.name,
                        "vic_d011": vic[0x11], "vic_d016": vic[0x16], "vic_d018": vic[0x18],
                        "cia2_dd00": cia2, "color_ram_white": True, "silhouette_spill_pixels": 0,
                    }
                    if index in {0, count // 2, count - 1}:
                        pending_capture = (sample, pixels)
                    report["samples"].append(sample)
                    previous_done = shown["clock"]
                    print(json.dumps({"mode": mode, "frame": index, "spin": spin, "render_cycles": render_cycles,
                                      "screen_match": True}), flush=True)

                samples = [sample for sample in report["samples"] if sample["mode"] == mode]
                elapsed = [sample["presentation_cycles"] for sample in samples if sample["presentation_cycles"] is not None]
                if any(value <= 0 for value in elapsed):
                    raise AssertionError("Presentation clock did not advance.")
                counters = [sample["frame_counter"] for sample in samples]
                if any(((b - a) & 65535) != 1 for a, b in zip(counters, counters[1:])):
                    raise AssertionError("Native frame counter does not advance once per rendered frame.")
                spins = [sample["spin"] for sample in samples]
                if any(((b - a) & 127) != 4 for a, b in zip(spins, spins[1:])):
                    raise AssertionError("Native spin did not advance four phase units per frame.")
                period_verified = False
                if count >= 33:
                    if spins[32] != spins[0] or samples[32]["screen_sha256"] != samples[0]["screen_sha256"]:
                        raise AssertionError("The 124-to-zero phase wrap does not reproduce the original screen.")
                    period_verified = True
                cadence = statistics.mean(elapsed)
                median_cadence = statistics.median(elapsed)
                gif = output / f"mode-{mode}-native.gif"
                durations = [max(10, round((sample["presentation_cycles"] or cadence) * 1000 / PAL_CLOCK)) for sample in samples]
                gif_images = images[mode]
                # The repeated closing pose proves the native phase wrap but
                # must not add a double-duration pause at the GIF loop seam.
                if period_verified and count == 33:
                    gif_images = gif_images[:-1]
                    durations = durations[:-1]
                gif_images[0].resize((640, 400), Image.Resampling.NEAREST).save(
                    gif, save_all=True,
                    append_images=[image.resize((640, 400), Image.Resampling.NEAREST) for image in gif_images[1:]],
                    duration=durations, loop=0, optimize=False)
                report["modes"][str(mode)] = {
                    "name": "analytic tangent" if mode == 0 else "nine probes", "frames": count,
                    "render_cycles": summary([sample["render_cycles"] for sample in samples]),
                    "presentation_cycles": summary(elapsed),
                    "measured_fps": PAL_CLOCK / median_cadence,
                    "mean_cadence_fps": PAL_CLOCK / cadence,
                    "pal_frames_per_presentation": cadence / PAL_FRAME_CYCLES,
                    "gif": gif.name, "gif_frames": len(gif_images), "phase_period_verified": period_verified,
                    "screen_bytes_compared": count * 1000,
                    "font_bytes_compared": count * 2048,
                }
            if pending_capture is not None:
                arrive("render_start")
                capture_previous_front(arrive("render_end"))
            report["font_unchanged"] = True
            report["all_screens_match_mathematical_model"] = True
            report["all_lit_pixels_inside_sphere"] = True
            report["pass"] = True
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
                      "modes": report["modes"]}), flush=True)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, default=HERE / "build/sphere.prg")
    parser.add_argument("--symbols", type=Path, default=HERE / "build/sphere.sym")
    parser.add_argument("--model", type=Path, default=HERE / "native-model.cjs")
    parser.add_argument("--output", type=Path, default=HERE / "build/verification")
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    parser.add_argument("--node", default="node")
    parser.add_argument("--frames", type=int, default=33)
    parser.add_argument("--sparse-frames", type=int, default=4)
    args = parser.parse_args()
    if args.frames < 2 or args.sparse_frames < 2:
        parser.error("Each mode requires at least two frames to measure presentation cadence.")
    return args


if __name__ == "__main__":
    verify(parse_args())
