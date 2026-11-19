#!/usr/bin/env python3
"""Verify the animated Megaplot polyline and its PAL scanout in VICE."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import sys

from PIL import Image

from wave_model import nodes

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "movieplayer"))
import vice_monitor

BUFFERS = ((0x0400, 0x2000, 0x18), (0x2c00, 0x3000, 0xbc))
PAL_LINES = 312
PAL_CYCLES_PER_LINE = 63
PAL_CLOCK = 985248
FIRST_PATCH = 201
PATCH_SLOTS = 256 - FIRST_PATCH


def symbol(text, name):
    match = re.search(rf"^\.label {re.escape(name)}=\$([0-9a-fA-F]+)\b", text, re.M)
    if not match:
        raise ValueError(f"Missing assembly symbol {name}")
    return int(match[1], 16)


def reference_pixels(points):
    """Sample each segment at its rounded Q8 rate, including both shared ends."""
    pixels = bytearray(40 * 200)
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        major, minor = max(dx, dy), min(dx, dy)
        rate = (512 * minor + major) // (2 * major) if major else 0
        sx, sy = (1 if x1 >= x0 else -1), (1 if y1 >= y0 else -1)
        for step in range(major + 1):
            offset = (128 + step * rate) >> 8
            x = x0 + sx * (step if dx >= dy else offset)
            y = y0 + sy * (offset if dx >= dy else step)
            if not (0 <= x < 160 and 0 <= y < 100):
                raise AssertionError(f"Offscreen reference point {(x, y)}")
            index = 2 * y * 40 + x // 4
            bits = 0xc0 >> (2 * (x % 4))
            pixels[index] |= bits
            pixels[index + 40] |= bits
    return bytes(pixels)


def buffer_bytes(memory, pair):
    screen, charset, _ = pair
    return memory[screen:screen + 1024], memory[charset:charset + 2048]


def displayed_pixels(screen, charset):
    return bytes(charset[8 * screen[(y // 8) * 40 + col] + y % 8]
                 for y in range(200) for col in range(40))


def capture_pixels(monitor, picture):
    monitor.run(f'scrsh "{picture}" 2')
    with Image.open(picture) as image:
        if image.size != (384, 272):
            raise AssertionError(f"Unexpected PAL screenshot size {image.size}")
        visible = image.convert("L").crop((32, 35, 352, 235))
        return visible.point(lambda v: 255 if v > 128 else 0, mode="1").tobytes()


def pixel_errors(expected, actual):
    if len(expected) != len(actual):
        raise AssertionError("Unexpected frame dimensions")
    return sum((a ^ b).bit_count() for a, b in zip(expected, actual))


def joint_is_lit(pixels, point):
    x, y = point
    top = 2 * y * 40 + x // 4
    bits = 0xc0 >> (2 * (x % 4))
    return pixels[top] & pixels[top + 40] & bits == bits


def check_animation(monitor, output, labels, segments, selected, report):
    boot = monitor.checkpoint(labels["waveLoop"])
    monitor.checkpoint(labels["presentFrame"])
    monitor.run("x")
    if monitor.registers()["pc"] != labels["waveLoop"]:
        raise AssertionError("Default launch did not reach the wave loop")
    monitor.run(f"delete {boot}")
    last_byte = max(0x3fff, labels["frameIndex"], labels["nodeX"] + segments, labels["nodeY"] + segments,
                    labels["JCOUNT"], labels["jointOverflow"])
    monitor.run("bank ram")
    initial = monitor.dump(output / "last-ram.bin", 0, last_byte)
    if initial[labels["frameIndex"]] != 0:
        raise AssertionError("The curve did not start at phase zero")
    report["defaultLaunch"] = True
    fixed_font = (output / "charset.bin").read_bytes()[:FIRST_PATCH * 8]
    monitor.run("bank io")
    bank = monitor.dump(output / "last-bank.bin", 0xdd00, 0xdd00)[0]
    colors = monitor.dump(output / "last-colors.bin", 0xd800, 0xdbe7)
    if bank & 3 != 3 or any(c & 15 != 1 for c in colors):
        raise AssertionError("Expected VIC bank 0 and white character ink")
    monitor.run("bank cpu")

    front = 0
    previous_buffer = buffer_bytes(initial, BUFFERS[front])
    previous_pixels = None
    fields = []
    by_index = {}
    last = max(selected)
    # The following flip is the earliest point where the last visible frame's
    # 200 raster lines have all reached the emulator's screenshot buffer.
    for index in range(last + 2):
        monitor.run("x")
        registers = monitor.registers()
        if registers["pc"] != labels["presentFrame"]:
            raise AssertionError(f"Missed flip for frame {index}")
        raster = registers["raster"]
        if 49 <= raster < 252:
            raise AssertionError(f"Frame {index} flipped on visible line {raster}")
        field = ((registers["clock"] - raster * PAL_CYCLES_PER_LINE - registers["raster_cycle"])
                 // (PAL_LINES * PAL_CYCLES_PER_LINE) + (raster >= 252))
        if fields and field <= fields[-1]:
            raise AssertionError(f"Frame {index} had no complete PAL scanout")
        fields.append(field)

        monitor.run("bank ram")
        memory = monitor.dump(output / "last-ram.bin", 0, last_byte)
        if memory[labels["frameIndex"]] != index % 256:
            raise AssertionError(f"Wrong animation phase before flip {index}")
        if buffer_bytes(memory, BUFFERS[front]) != previous_buffer:
            raise AssertionError(f"Drawing frame {index} changed visible screen or glyph RAM")
        monitor.run("bank io")
        vic = monitor.dump(output / "last-vic.bin", 0xd011, 0xd021)
        if vic[7] & 0xfe != BUFFERS[front][2] or vic[0] & 0x60 or vic[5] & 0x10 or vic[16] & 15:
            raise AssertionError(f"Wrong VIC bank pair, mode or background before flip {index}")
        monitor.run("bank cpu")
        report["frontIntegrityChecks"] += 1

        if index - 1 in selected:
            picture = output / f"frame-{index - 1}-vice.png"
            physical = capture_pixels(monitor, picture)
            errors = pixel_errors(previous_pixels, physical)
            scanout_errors = pixel_errors(displayed_pixels(*previous_buffer), physical)
            by_index[index - 1]["screenshot"] = picture.name
            by_index[index - 1]["scanoutVsRamErrors"] = scanout_errors
            report["scanoutVsRamErrors"] += scanout_errors
            by_index[index - 1]["physicalPixelErrors"] = errors
            report["physicalPixelErrors"] += errors
            by_index[index - 1]["durationFields"] = fields[-1] - fields[-2]

        back = 1 - front
        screen, charset = buffer_bytes(memory, BUFFERS[back])
        if charset[:len(fixed_font)] != fixed_font:
            raise AssertionError(f"Static line glyphs changed in frame {index}")
        allocated = memory[labels["JCOUNT"]]
        overflow = memory[labels["jointOverflow"]]
        visible_patches = Counter(code for code in screen[:1000] if code >= FIRST_PATCH)
        if allocated > PATCH_SLOTS or any(code - FIRST_PATCH >= allocated for code in visible_patches):
            raise AssertionError(f"Invalid patch allocation in frame {index}")
        if index <= last:
            report["peakAllocatedPatches"] = max(report["peakAllocatedPatches"], allocated)
            report["peakVisiblePatches"] = max(report["peakVisiblePatches"], len(visible_patches))
            report["peakPatchedCells"] = max(report["peakPatchedCells"], sum(visible_patches.values()))
            if overflow:
                report["overflowFrames"].append(index)
                report["overflowAttempts"] += overflow
        if index in selected or index == 256:
            expected_nodes = nodes(index % 256, segments)
            xs, ys = labels["nodeX"], labels["nodeY"]
            actual_nodes = list(zip(memory[xs:xs + segments + 1], memory[ys:ys + segments + 1]))
            if actual_nodes != expected_nodes:
                raise AssertionError(f"Frame {index} joint mismatch: expected {expected_nodes}, got {actual_nodes}")
            previous_pixels = reference_pixels(expected_nodes)
            actual_pixels = displayed_pixels(screen, charset)
            errors = pixel_errors(previous_pixels, actual_pixels)
            if index in selected:
                joins = expected_nodes[1:-1]
                lit = sum(joint_is_lit(actual_pixels, point) for point in joins)
                report["interiorJointsChecked"] += len(joins)
                report["unlitInteriorJoints"] += len(joins) - lit
                report["characterPixelErrors"] += errors
                missing = sum((expected & ~actual).bit_count()
                              for expected, actual in zip(previous_pixels, actual_pixels))
                frame = {"index": index, "jointsChecked": len(actual_nodes),
                         "litCells": sum(code != 0 for code in screen[:1000]),
                         "litLogicalPixels": sum(byte.bit_count() for byte in previous_pixels) // 4,
                         "allocatedPatches": allocated, "visiblePatches": len(visible_patches),
                         "patchedCells": sum(visible_patches.values()), "overflowAttempts": overflow,
                         "interiorJointsLit": lit, "interiorJoints": len(joins),
                         "missingHiresPixels": missing, "extraHiresPixels": errors - missing,
                         "flipRaster": raster, "firstVisibleField": field, "characterPixelErrors": errors}
                report["frames"].append(frame)
                by_index[index] = frame
            if index == 256:
                report["phaseWrapChecked"] = True
                report["phaseWrapPixelErrors"] = errors
        if index == last + 1:
            break

        monitor.run("step")    # presentFrame begins with STA $d018
        monitor.run("bank io")
        selection = monitor.dump(output / "last-d018.bin", 0xd018, 0xd018)[0]
        if selection & 0xfe != BUFFERS[back][2]:
            raise AssertionError(f"Frame {index} did not select the finished screen and glyph bank")
        monitor.run("bank cpu")
        previous_buffer = screen, charset
        front = back
        report["presentationsChecked"] += 1

    # Each interval includes the complete physical display of its frame.
    intervals = [b - a for a, b in zip(fields, fields[1:])]
    report["palFieldCadence"] = dict(sorted(Counter(intervals).items()))
    report["measuredFPS"] = round(len(intervals) * PAL_CLOCK
                                  / (sum(intervals) * PAL_LINES * PAL_CYCLES_PER_LINE), 3)
    report["doubleBuffered"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/bin/x64sc"))
    parser.add_argument("--build", type=Path, default=HERE / "build", help="verify an existing build directory")
    parser.add_argument("--rebuild", action="store_true", help="rebuild the program before verification")
    parser.add_argument("--segments", type=int, help="expected segment count, also passed to the builder with --rebuild")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--frames", type=int, nargs="+", default=[0, 1, 2, 32, 64, 128, 192, 255])
    group.add_argument("--all-frames", action="store_true", help="verify the entire 256-frame motion cycle")
    parser.add_argument("--timeout", type=float, default=30, help="timeout for each VICE monitor response in seconds")
    args = parser.parse_args()
    if any(not 0 <= n <= 255 for n in args.frames) or not 0 < args.timeout <= 60:
        parser.error("frames must be in 0..255 and timeout in (0, 60]")
    selected = set(range(256) if args.all_frames else args.frames)
    output = args.build.resolve()
    if args.rebuild:
        if output != HERE / "build":
            parser.error("--rebuild uses the local build directory")
        command = [sys.executable, str(HERE / "build_megaplot.py")]
        if args.segments is not None:
            command += ["--segments", str(args.segments)]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    program = output / "megaplot.prg"
    manifest = json.loads((output / "megaplot.json").read_text())
    segments = manifest["segments"]
    if args.segments is not None and segments != args.segments:
        parser.error(f"requested {args.segments} segments, existing PRG has {segments}")
    report = {"passed": False, "segments": segments, "presentationsChecked": 0, "frontIntegrityChecks": 0,
              "patchCapacity": PATCH_SLOTS, "peakAllocatedPatches": 0, "peakVisiblePatches": 0,
              "peakPatchedCells": 0, "overflowFrames": [], "overflowAttempts": 0,
              "interiorJointsChecked": 0, "unlitInteriorJoints": 0, "characterPixelErrors": 0,
              "physicalPixelErrors": 0, "scanoutVsRamErrors": 0, "frames": [], "programSha256": hashlib.sha256(program.read_bytes()).hexdigest()}
    try:
        if report["programSha256"] != manifest["programSha256"]:
            raise ValueError("Program differs from its build manifest")
        symbols = (output / "main.sym").read_text()
        names = ("waveLoop", "presentFrame", "frameIndex", "nodeX", "nodeY", "JCOUNT", "jointOverflow")
        labels = {name: symbol(symbols, name) for name in names}
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        command = [str(args.vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100",
                   "-warp", "+autostart-warp", "+confirmonexit", "-sounddev", "dummy", "+refreshonbreak",
                   "-initbreak", "reset", "-autostartprgmode", "1", "-autostart", str(program),
                   "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
        with (output / "vice.log").open("w") as log:
            process = subprocess.Popen(command, cwd=output, stdout=log, stderr=log)
            try:
                with vice_monitor.connect(process, port) as connection:
                    monitor = vice_monitor.Monitor(connection)
                    connection.settimeout(args.timeout)
                    check_animation(monitor, output, labels, segments, selected, report)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
        report["passed"] = not (report["overflowFrames"] or report["unlitInteriorJoints"]
                                or report["characterPixelErrors"] or report["physicalPixelErrors"]
                                or report["scanoutVsRamErrors"] or report.get("phaseWrapPixelErrors", 0))
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    (output / "verify.json").write_text(json.dumps(report, indent=2) + "\n")
    summary = {k: v for k, v in report.items() if k != "frames"}
    print(json.dumps(dict(summary, framesChecked=len(report["frames"]))))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
