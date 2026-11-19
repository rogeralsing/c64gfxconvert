#!/usr/bin/env python3
"""Verify the assembled signed line entry against an exact viewport reference."""

import argparse
import json
from pathlib import Path
import random
import socket
import subprocess
from tempfile import TemporaryDirectory

from clip_reference import HEIGHT, WIDTH, visible_segment
from cube_model import normalized_cells
from verify_linedrawer import BUFFERS, BUILD, glyph_rows, load_monitor, sha, symbol


CALL_STUB = 0xc000
GUARD_START = 0x0200
GUARD_END = 0xbfff
LOW_BYTES = ("lx0", "ly0", "lx1", "ly1")
HIGH_BYTES = ("clipX0Hi", "clipY0Hi", "clipX1Hi", "clipY1Hi")


def test_segments():
    examples = {
        "inside": (5, 6, 158, 98),
        "boundary": (0, 99, 159, 0),
        "inside dot": (159, 99, 159, 99),
        "outside dot": (160, 100, 160, 100),
        "left": (-10, 20, 30, 40),
        "right": (153, 25, 180, 35),
        "top": (8, -3, 14, 3),
        "bottom": (100, 96, 100, 104),
        "left to right": (-200, 20, 300, 30),
        "top to bottom": (159, -1000, 159, 1000),
        "left to bottom": (-40, 10, 180, 200),
        "common left": (-4, 50, -1, 90),
        "common right": (160, 40, 170, 60),
        "common top": (20, -6, 90, -1),
        "common bottom": (30, 100, 140, 117),
        "misses corner": (-10, 2, 2, -10),
        "misses corner by half": (-1, 1, 1, -2),
        "touches corner": (-1, 1, 1, -1),
        "positive half": (-1, 0, 1, 1),
        "negative half": (-1, 1, 1, 0),
        "int16 horizontal": (-32768, 50, 32767, 50),
        "int16 diagonal": (-32768, -32768, 32767, 32767),
        "int16 descending": (32767, -32669, -32669, 32767),
        "int16 miss": (32767, -32768, -32768, 32767),
        "int16 wide shallow": (-32768, -33, 32767, 114),
    }
    for label, segment in examples.items():
        x0, y0, x1, y1 = segment
        yield label, segment
        reverse = x1, y1, x0, y0
        if reverse != segment:
            yield label + " reversed", reverse

    randomizer = random.Random(6502)
    for index in range(32):
        if index < 16:
            segment = tuple(randomizer.randint(-64, edge + 64)
                            for edge in (WIDTH - 1, HEIGHT - 1) * 2)
        else:
            segment = tuple(randomizer.randint(-32768, 32767) for _ in range(4))
        yield f"seeded {index}", segment


def entry_stub(addresses, segment, screen, charset):
    """Set the public ABI and call through a real 6502 JSR, not an emulator hook."""
    code = bytearray()

    def set_byte(name, value):
        address = addresses[name]
        code.extend((0xa9, value))  # LDA #value
        if address < 0x100:
            code.extend((0x85, address))  # STA zero page
        else:
            code.extend((0x8d, address & 0xff, address >> 8))  # STA absolute

    for low, high, coordinate in zip(LOW_BYTES, HIGH_BYTES, segment):
        set_byte(low, coordinate & 0xff)
        set_byte(high, (coordinate >> 8) & 0xff)
    set_byte("baseLo", screen & 0xff)
    set_byte("baseHi", screen >> 8)
    set_byte("drawCharsetHi", charset >> 8)
    for opcode, destination in ((0x20, "drawClippedLine"), (0x4c, "halt")):
        address = addresses[destination]
        code.extend((opcode, address & 0xff, address >> 8))
    return code


def verify_case(monitor, addresses, dump_file, pair, label, segment):
    screen, charset, _ = pair
    screen_end = screen + 1000
    monitor.run(f"fill {screen:04x} {screen_end - 1:04x} 00")
    stub = entry_stub(addresses, segment, screen, charset)
    monitor.run(f"> {CALL_STUB:04x} {stub.hex(' ')}")
    before = monitor.dump(dump_file, GUARD_START, GUARD_END)
    monitor.run(f"g {CALL_STUB:04x}")
    entry = monitor.registers()
    if entry["pc"] != addresses["drawClippedLine"]:
        raise AssertionError(f"{label}: did not enter native clip routine")
    monitor.run("x")
    done = monitor.registers()
    if done["pc"] != addresses["halt"]:
        raise AssertionError(f"{label}: native clip routine did not return")
    after = monitor.dump(dump_file, GUARD_START, GUARD_END)

    lower, upper = screen - GUARD_START, screen_end - GUARD_START
    if before[:lower] != after[:lower] or before[upper:] != after[upper:]:
        bad = next(GUARD_START + i for i, (old, new) in enumerate(zip(before, after))
                   if not lower <= i < upper and old != new)
        raise AssertionError(f"{label} {segment}: write outside screen at ${bad:04x}")

    clipped = visible_segment(segment)
    expected = dict(normalized_cells(*clipped)) if clipped is not None else {}
    font = charset - GUARD_START
    for cell, code in enumerate(after[lower:upper]):
        if (cell in expected) != (code != 0):
            raise AssertionError(f"{label} {segment} -> {clipped}: unexpected occupancy at cell {cell}")
        if cell in expected:
            start = font + code * 8
            if after[start:start + 8] != glyph_rows(expected[cell]):
                raise AssertionError(f"{label} {segment} -> {clipped}: wrong glyph at cell {cell}")
    return {"case": label, "input": segment, "visible": clipped, "litCells": len(expected),
            "screen": screen, "nativeCycles": done["clock"] - entry["clock"] - 3}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/bin/x64sc"))
    parser.add_argument("--build", type=Path, default=BUILD,
                        help="directory containing linedrawer.prg and its matching main.sym")
    args = parser.parse_args()
    build = args.build.resolve()
    program = build / "linedrawer.prg"
    report = {"passed": False, "programSha256": sha(program.read_bytes()), "cases": []}
    process = connection = None
    try:
        text = (build / "main.sym").read_text()
        addresses = {name: symbol(text, name) for name in (*LOW_BYTES, *HIGH_BYTES, "baseLo",
                    "baseHi", "drawCharsetHi", "cubeLoop", "drawClippedLine", "halt")}
        vm = load_monitor()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        command = [str(args.vice), "-default", "+saveres", "-minimized", "-pal", "-warp",
                   "+autostart-warp", "+confirmonexit", "-sounddev", "dummy", "+refreshonbreak",
                   "-initbreak", "reset", "-autostartprgmode", "1", "-autostart", str(program),
                   "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
        with TemporaryDirectory(prefix="linedrawer-clipping-") as temporary:
            scratch = Path(temporary)
            with (scratch / "vice.log").open("w") as log:
                process = subprocess.Popen(command, cwd=build, stdout=log, stderr=log)
            connection = vm.connect(process, port)
            connection.settimeout(15)
            monitor = vm.Monitor(connection)
            connection.settimeout(15)
            monitor.checkpoint(addresses["cubeLoop"])
            monitor.checkpoint(addresses["drawClippedLine"])
            monitor.checkpoint(addresses["halt"])
            monitor.run("x")
            if monitor.registers()["pc"] != addresses["cubeLoop"]:
                raise AssertionError("Default launch halted before initializing the line drawer")
            monitor.run("bank ram")
            for index, (label, segment) in enumerate(test_segments()):
                receipt = verify_case(monitor, addresses, scratch / "ram.bin",
                                      BUFFERS[index % len(BUFFERS)], label, segment)
                report["cases"].append(receipt)
        report["passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if connection is not None:
            connection.close()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    (build / "verify-clipping.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({**report, "cases": len(report["cases"])}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
