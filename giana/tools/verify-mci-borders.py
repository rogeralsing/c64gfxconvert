#!/usr/bin/env python3
"""Verify standalone MCI pixels and open-border checker sprites in native PAL VICE.

The reference decodes the retained True Paint source independently. Screenshots
come from completed real VIC-II fields; the monitor never writes guest memory.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "giana/build"
sys.path.insert(0, str(ROOT / "mydemo/discoball"))
from vice_support import Monitor, connect_monitor, read_labels, vice_command

PAL_CYCLES = 19656
ACTIVE_BOX = (32, 35, 352, 235)
EXTENDED_BOX = (8, 0, 376, 272)
FULL_ROW_X = (48, 96, 144, 0, 336, 192, 240, 288)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def breakpoint(monitor, address):
    response = monitor.run(f"break ${address:04x}")
    match = re.search(r"BREAK:\s*(\d+)", response)
    assert match, response
    return int(match[1])


def registers(monitor):
    response = monitor.run("r")
    match = re.search(r"^\.;([0-9a-fA-F]{4})\s+(.*)$", response, re.M)
    assert match, response
    fields = match[2].split()
    return int(match[1], 16), int(fields[-3]), int(fields[-2]), int(fields[-1])


class Reference:
    """Original two-field bitmap plus physical hardware-sprite geometry."""

    def __init__(self):
        self.path = ROOT / "giana/assets/giana-man.mci"
        self.source = self.path.read_bytes()
        assert len(self.source) == 19434 and self.source[:2] == b"\x00\x9c"
        self.screens = (self.source[2:1002], self.source[17410:18410])
        self.bitmaps = (self.source[1026:9026], self.source[9218:17218])
        self.colors = self.source[18434:19434]
        self.background = self.source[1002]
        assert self.background < 16 and all(color < 16 for color in self.colors)
        self.palette = [tuple(int(value, 16) for value in line.split()[:3])
                        for line in (ROOT / "palettes/peptoette-a.vpl").read_text().splitlines()
                        if line.strip() and not line.lstrip().startswith("#")]
        assert len(self.palette) == 16
        self.rows = []
        self.images = []
        self.extended = []
        for phase in (0, 1):
            rows = []
            for y in range(200):
                row = []
                for x in range(160):
                    cell = y // 8 * 40 + x // 4
                    value = self.bitmaps[phase][cell * 8 + y % 8]
                    code = value >> (6 - 2 * (x % 4)) & 3
                    screen = self.screens[phase][cell]
                    color = (self.background, screen >> 4, screen & 15, self.colors[cell])[code]
                    row.extend((color, color))
                rows.append(row)
            self.rows.append(rows)
            # Field B has one physical-pixel horizontal fine-scroll offset.
            image = Image.new("RGB", (320, 200))
            image.putdata([self.palette[color]
                           for row in rows
                           for color in ([self.background] + row[:-1] if phase else row)])
            self.images.append(image)
            self.extended.append(self.extended_image(phase))
        self.checker = bytes((0xaa if line % 2 == 0 else 0x55)
                             for line in range(21) for _ in range(3)) + bytes(1)
        # The spare pair starts ten lines early behind the preceding side band.
        self.last_checker = bytes(30) + self.checker[30:]

    @staticmethod
    def checker_pixel(x, source_y):
        if source_y >= 21:
            return False
        return bool((0xaa if source_y % 2 == 0 else 0x55) & (0x80 >> (x % 8)))

    def extended_image(self, phase):
        pixels = [[self.background] * 384 for _ in range(272)]
        # Preserve the rightmost one-pixel fine-scroll spill in the open border.
        for y, row in enumerate(self.rows[phase]):
            for x, color in enumerate(row):
                pixels[y + 35][x + 32 + phase] = color
        for y in range(272):
            if y < 35 or y >= 235:
                source_y = (y + 7) // 2 if y < 35 else (y - 235) // 2
                for left in FULL_ROW_X:
                    left += 8
                    for x in range(max(0, left), min(384, left + 48)):
                        if self.checker_pixel((x - left) // 2, source_y):
                            pixels[y][x] = 3
            else:
                offset = y - 35
                # Nine complete 21-line bands are followed by the spare pair's
                # final eleven rows. Its first ten rows stay transparent.
                source_y = offset % 21 if offset < 189 else offset - 179
                for left in (8, 352):
                    for x in range(left, left + 24):
                        # The right sprite keeps X expansion for the first side
                        # row, preserving the preceding full-width top row.
                        source_x = (x - left) // 2 if left == 352 and y == 35 else x - left
                        if self.checker_pixel(source_x, source_y):
                            pixels[y][x] = 3
        result = Image.new("RGB", (384, 272))
        result.putdata([self.palette[color] for row in pixels for color in row])
        return result

    def check_memory(self, phase, ram, vic, colors, cia):
        assert phase in (0, 1)
        pins = (cia[0] | (~cia[2] & 0xff)) & 3
        bank = (~pins) & 3
        assert bank == (1, 2)[phase], ("MCI bank", phase, bank)
        assert vic[0x18] & 0xfe == 0x08, ("MCI screen/bitmap selection", vic[0x18])
        assert vic[0x16] & 0x3f == 0x18 + phase, ("Restored MCI fine scroll", phase, vic[0x16])
        assert vic[0x11] & 0x37 == 0x33, ("Bitmap mode, display enable and Y scroll", vic[0x11])
        assert vic[0x15] == 255 and vic[0x1c] == 0 and vic[0x1b] == 0
        assert all(color & 15 == 3 for color in vic[0x27:0x2f]), "Checker sprites must use cyan"
        assert vic[0x20] & 15 == 0 and vic[0x21] & 15 == self.background
        assert colors == self.colors, "Shared Color RAM differs from the original MCI"
        for index, (screen, bitmap, checker) in enumerate(((0x4000, 0x6000, 0x4400),
                                                          (0x8000, 0xa000, 0x8400))):
            assert ram[screen:screen + 1000] == self.screens[index], (index, "Original screen changed")
            assert ram[bitmap:bitmap + 8000] == self.bitmaps[index], (index, "Original bitmap changed")
            assert ram[screen + 0x3f8:screen + 0x400] == bytes([0x10]) * 8
            assert ram[checker:checker + 64] == self.checker, (index, "Checker frame changed")
            assert ram[checker + 64:checker + 128] == self.last_checker, (index, "Final side frame changed")
        assert ram[0x7fff] == ram[0xbfff] == 0, "Idle-state bitmap bytes must remain zero"
        return {"phase": phase, "vic_bank": bank,
                "screen": (0x4000, 0x8000)[phase], "bitmap": (0x6000, 0xa000)[phase]}


def differences(actual, expected, box):
    left, top, right, bottom = box
    result = []
    a, e = actual.load(), expected.load()
    for y in range(top, bottom):
        for x in range(left, right):
            if a[x, y] != e[x, y]:
                result.append((x, y, a[x, y], e[x, y]))
    return result


def empty_side_rows(image, cyan):
    """Visible horizontal seams must not interrupt either checker column."""
    pixels = image.load()
    return {name: [y for y in range(image.height)
                   if not any(pixels[x, y] == cyan for x in range(left, right))]
            for name, left, right in (("left", 8, 32), ("right", 352, 376))}


def side_row_changes(image):
    """Report visible vertical detail over the bitmap's 200 side-border rows."""
    pixels = image.load()
    return {name: sum(any(pixels[x, y] != pixels[x, y - 1] for x in range(left, right))
                      for y in range(36, 235))
            for name, left, right in (("left", 8, 32), ("right", 352, 376))}


def verify(args):
    program = args.program.resolve()
    labels = read_labels(program.with_suffix(".sym"))
    assert all(name in labels for name in ("start", "phase", "frameComplete", "fieldCounter"))
    reference = Reference()
    output = BUILD / "mci-borders-check"
    output.mkdir(parents=True, exist_ok=True)
    receipt_path = BUILD / "mci-borders-verification.json"
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    command = vice_command(args.vice, program, port, ROOT / "palettes/peptoette-a.vpl")
    command += ["-initbreak", "reset", "-warp", "-VICIIborders", "0", "-seed", "1"]
    result = {"passed": False, "program": str(program), "program_sha256": digest(program.read_bytes()),
              "source_mci_sha256": digest(reference.source), "requested_fields": args.frames,
              "warmup_fields": args.warmup, "native_pal_fps": "13684/273",
              "active_box": ACTIVE_BOX, "extended_box": EXTENDED_BOX, "command": command}
    process = connection = monitor = None
    fields, images = [], []
    began = time.monotonic()
    try:
        with (output / "vice.log").open("w") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            connection = connect_monitor(process, port)
            monitor = Monitor(connection)
            monitor.run("r")
            monitor.run("sidefx off")
            startup = breakpoint(monitor, labels["start"])
            monitor.run("x")
            assert monitor.registers()[0] == labels["start"]
            monitor.run(f"disable {startup}")
            complete = breakpoint(monitor, labels["frameComplete"])
            previous = None
            for index in range(args.warmup + args.frames):
                monitor.run("x")
                pc, raster, line_cycle, cycles = registers(monitor)
                assert pc == labels["frameComplete"], ("Unexpected execution checkpoint", pc)
                monitor.run("bank ram")
                ram = monitor.memory(output / "ram.bin", 0, 0xffff)
                phase, count = ram[labels["phase"]], ram[labels["fieldCounter"]]
                monitor.run("bank io")
                vic = monitor.memory(output / "vic.bin", 0xd000, 0xd03f)
                colors = bytes(value & 15 for value in monitor.memory(output / "colors.bin", 0xd800, 0xdbe7))
                cia = monitor.memory(output / "cia.bin", 0xdd00, 0xdd03)
                monitor.run("bank cpu")
                if index < args.warmup:
                    continue
                assert raster == 302, ("Stable frame boundary", index, raster)
                assert line_cycle == 3, ("Stable frame-entry cycle", index, line_cycle)
                layout = reference.check_memory(phase, ram, vic, colors, cia)
                if previous:
                    assert phase == previous["phase"] ^ 1, ("Field phase skipped/repeated", index)
                    assert count == (previous["counter"] + 1) & 255, ("Field counter skipped/repeated", index)
                    assert abs(cycles - previous["cycles"] - PAL_CYCLES) <= 1, ("PAL field cadence", index, cycles - previous["cycles"])
                screenshot = output / f"field-{len(fields):03d}.png"
                monitor.run(f'screenshot "{screenshot}" 2')
                with Image.open(screenshot) as image:
                    actual = image.convert("RGB")
                assert actual.size == (384, 272), ("Expected uncropped PAL VICE frame", actual.size)
                expected = reference.extended[phase]
                central = differences(actual, expected, ACTIVE_BOX)
                extended = differences(actual, expected, EXTENDED_BOX)
                cyan = reference.palette[3]
                zones = {"top": (8, 0, 376, 33), "bottom": (8, 235, 376, 272),
                         "left": (8, 35, 32, 234), "right": (352, 35, 376, 234)}
                pixels = actual.load()
                counts = {name: sum(pixels[x, y] == cyan
                                    for y in range(box[1], box[3]) for x in range(box[0], box[2]))
                          for name, box in zones.items()}
                gaps = empty_side_rows(actual, cyan)
                row = {"field": len(fields), "counter": count, "raster": raster, "line_cycle": line_cycle,
                       "cycles": cycles, **layout, "central_pixel_differences": len(central),
                       "extended_pixel_differences": len(extended), "checker_pixels_by_border": counts,
                       "empty_side_rows": gaps, "side_row_changes": side_row_changes(actual),
                       "first_central_differences": central[:12], "first_extended_differences": extended[:12],
                       "actual_rgb_sha256": digest(actual.tobytes())}
                if len(fields) < 2:
                    expected.save(output / f"expected-phase-{phase}.png")
                    actual.save(output / f"actual-phase-{phase}.png")
                fields.append(row)
                images.append(actual)
                previous = row
                if len(fields) % 8 == 0:
                    print(f"Native open-border MCI: {len(fields)}/{args.frames} completed PAL fields", flush=True)
            monitor.run(f"disable {complete}")
        assert len(fields) == args.frames and {field["phase"] for field in fields} == {0, 1}
        result.update({"fields": fields, "central_pixel_differences": sum(field["central_pixel_differences"] for field in fields),
                       "extended_pixel_differences": sum(field["extended_pixel_differences"] for field in fields)})
        assert result["central_pixel_differences"] == 0, ("Native MCI image changed", result["central_pixel_differences"])
        assert all(all(count > 0 for count in field["checker_pixels_by_border"].values()) for field in fields), "Checker sprites are missing from at least one border"
        assert all(not rows for field in fields for rows in field["empty_side_rows"].values()), "Horizontal gaps interrupt the side checker sprites"
        assert result["extended_pixel_differences"] == 0, ("Native border sprites/idle pixels differ", result["extended_pixel_differences"])
        points = [(x, y) for y in range(272) for x in range(384)
                  if images[0].getpixel((x, y)) == reference.palette[3]
                  and not (32 <= x < 352 and 35 <= y < 235)]
        result["observed_border_checker_bounds"] = [min(x for x, _ in points), min(y for _, y in points),
                                                     max(x for x, _ in points) + 1, max(y for _, y in points) + 1]
        images[0].save(BUILD / "mci-borders-native.gif", save_all=True, append_images=images[1:],
                       duration=20, loop=0, disposal=1, optimize=False)
        result["passed"] = True
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
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
        if process:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        result["elapsed_host_seconds"] = round(time.monotonic() - began, 3)
        result.setdefault("fields", fields)
        receipt_path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key not in ("command", "fields")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, default=BUILD / "giana-mci-borders.prg")
    parser.add_argument("--frames", type=int, default=32)
    parser.add_argument("--warmup", type=int, default=8)
    parser.add_argument("--vice", default=os.environ.get("VICE") or shutil.which("x64sc"))
    options = parser.parse_args()
    if not options.vice:
        parser.error("x64sc was not found; set VICE or pass --vice")
    if options.frames < 2 or options.warmup < 6:
        parser.error("At least two captured fields and six warmup fields are required")
    verify(options)
