#!/usr/bin/env python3
"""Verify the four-line bitmap and hardware register schedule in PAL VICE."""

import argparse
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mydemo/discoball"))
sys.path.insert(0, str(ROOT / "mydemo/movieplayer"))
from vice_monitor import Monitor, connect
from vice_support import read_labels, vice_command

CORE = (32, 35, 352, 235)
PAL_CLOCKS = 19656
STORE = re.compile(
    r"#\d+ \(Trace\s+store (d011|d018)\)\s+(\d+)/\$[0-9a-f]+,\s+(\d+)/\$[0-9a-f]+"
    r"\s*\n[^\n]*\bA:([0-9a-f]{2})", re.I,
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_plane(path, length):
    data = path.read_bytes()
    require(len(data) == length, f"Expected {length} bytes in {path.name}")
    return data


def decode(bitmap, top, bottom, colors, palette, splits=None):
    double_pixels = [bytes(rgb) * 2 for rgb in palette]
    pixels = bytearray()
    for y in range(200):
        split = 4 if splits is None else splits[y // 8] or 8
        screen = bottom if y % 8 >= split else top
        for column in range(40):
            cell = (y // 8) * 40 + column
            pair = screen[cell]
            choices = (0, pair >> 4, pair & 15, colors[cell] & 15)
            bits = bitmap[cell * 8 + y % 8]
            for shift in (6, 4, 2, 0):
                pixels.extend(double_pixels[choices[(bits >> shift) & 3]])
    core = Image.frombytes("RGB", (320, 200), bytes(pixels))
    frame = Image.new("RGB", (384, 272))
    frame.paste(core, CORE[:2])
    return frame


def active_groups(bitmap, top, bottom):
    groups = []
    for group in range(25):
        for cell in range(group * 40, (group + 1) * 40):
            # Only screen colors selected by a pixel in the lower half matter.
            changes = (False, (top[cell] >> 4) != (bottom[cell] >> 4),
                       (top[cell] & 15) != (bottom[cell] & 15), False)
            lower_half = bitmap[cell * 8 + 4:cell * 8 + 8]
            if any(changes[(bits >> shift) & 3] for bits in lower_half for shift in (6, 4, 2, 0)):
                groups.append(group)
                break
    return groups


def expected_schedule(rasters):
    # VICE's store trace reports the CPU cycle after the bus write.
    schedule = []
    for raster in rasters:
        schedule.extend([
            ("d018", raster, 8, 0x18),
            ("d011", raster, 14, 0x38 | (raster & 7)),
            ("d011", raster, 60, 0x3b),
            ("d018", raster + 1, 3, 0x08),
        ])
    return schedule


def verify(args):
    assets = args.assets.resolve()
    bitmap = read_plane(assets / "bitmap.bin", 8000)
    top = read_plane(assets / "screen-top.bin", 1000)
    bottom = read_plane(assets / "screen-bottom.bin", 1000)
    colors = read_plane(assets / "color-ram.bin", 1000)
    palette_path = ROOT / "palettes/colodore.vpl"
    palette = [tuple(int(channel, 16) for channel in line.split()[:3])
               for line in palette_path.read_text().splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    require(len(palette) == 16, "Invalid Colodore palette")
    expected = decode(bitmap, top, bottom, colors, palette)
    rasters = [55 + group * 8 for group in active_groups(bitmap, top, bottom)]

    program = args.program.resolve() if args.program else assets / "lp-four-line.prg"
    checkpoint = read_labels(assets / "four-line-player.sym")["frameComplete"]
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    command = vice_command(args.vice, program, port, palette_path)
    command += ["-initbreak", "reset", "-warp", "-VICIIborders", "0"]

    schedule = expected_schedule(rasters)
    fields = []
    with TemporaryDirectory(prefix="four-line-vice-") as temp, (assets / "vice.log").open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            with connect(process, port) as connection:
                monitor = Monitor(connection)
                connection.settimeout(15)
                monitor.run("sidefx off")
                monitor.checkpoint(checkpoint)
                monitor.run("x")
                previous = monitor.registers()
                require(previous["pc"] == checkpoint and previous["raster"] == 256,
                        f"Autostart did not reach the frame checkpoint: {previous}")

                dump = Path(temp) / "memory.bin"
                monitor.run("bank ram")
                require(monitor.dump(dump, 0x4000, 0x43e7) == top, "Top screen RAM differs from the asset")
                require(monitor.dump(dump, 0x4400, 0x47e7) == bottom, "Bottom screen RAM differs from the asset")
                require(monitor.dump(dump, 0x6000, 0x7f3f) == bitmap, "Bitmap RAM differs from the asset")
                monitor.run("bank io")
                observed_colors = monitor.dump(dump, 0xd800, 0xdbe7)
                require(bytes(value & 15 for value in observed_colors) == colors,
                        "Color RAM differs from the asset")
                monitor.run("bank cpu")

                monitor.run("trace store d011")
                monitor.run("trace store d018")
                for field in range(args.fields):
                    trace = monitor.run("x")
                    registers = monitor.registers()
                    require(registers["pc"] == checkpoint and registers["raster"] == 256,
                            f"Unexpected frame checkpoint: {registers}")
                    # Foreground polling can hit a different cycle on the same raster.
                    line_start = registers["clock"] - registers["raster_cycle"]
                    previous_line_start = previous["clock"] - previous["raster_cycle"]
                    require(line_start - previous_line_start == PAL_CLOCKS,
                            f"Missed a PAL field: {registers}")
                    previous = registers
                    stores = [(address.lower(), int(line), int(cycle), int(value, 16))
                              for address, line, cycle, value in STORE.findall(trace)]
                    require(stores == schedule, f"Unexpected register schedule in field {field}: {stores}")

                    screenshot = Path(temp) / "frame.png"
                    monitor.run(f'screenshot "{screenshot}" 2')
                    with Image.open(screenshot) as image:
                        actual = image.convert("RGB")
                    require(actual.size == expected.size, f"Wrong screenshot dimensions: {actual.size}")
                    difference = ImageChops.difference(actual, expected)
                    require(difference.getbbox() is None, f"Native pixel mismatch at {difference.getbbox()}")
                    if field == 0:
                        actual.save(assets / f"{program.stem}-vice.png")
                        (assets / "raster-trace.txt").write_text(trace)
                    fields.append({"field": field, "lateBadlines": len(rasters),
                                   "lateBadlineRasters": rasters, "corePixelsMatched": 64000})
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

    (assets / "vice-proof.json").write_text(json.dumps({"passed": True, "fields": fields}, indent=2) + "\n")
    print(f"{args.fields} PAL fields verified, {len(rasters)} late badlines and 64,000 exact display pixels per field.")
    if rasters:
        print(f"Late badline rasters: {', '.join(map(str, rasters))}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assets", type=Path)
    parser.add_argument("--program", type=Path, help="PRG to verify (defaults to assets/lp-four-line.prg)")
    parser.add_argument("--vice", default="x64sc")
    parser.add_argument("--fields", type=int, default=3)
    args = parser.parse_args()
    if args.fields < 1:
        parser.error("--fields must be at least 1")
    verify(args)
