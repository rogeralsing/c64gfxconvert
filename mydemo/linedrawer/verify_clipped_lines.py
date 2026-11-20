#!/usr/bin/env python3
"""Verify the assembled signed line entry against an exact viewport reference."""

import argparse
import json
from itertools import product
from math import gcd
from pathlib import Path
import random
import socket
import subprocess
from tempfile import TemporaryDirectory

from clip_reference import HEIGHT, WIDTH, visible_segment
from cube_model import normalized_cells
from verify_linedrawer import (BUFFERS, BUILD, add_junction_renderers, assembly_symbols,
                              glyph_rows, load_monitor, sha, symbol, trace_execution)


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


def crossing_segments():
    yield from test_segments()

    def starts(delta, extent):
        low, high = max(0, -delta), min(extent - 1, extent - 1 - delta)
        if low > high:
            # A segment longer than this axis crosses the viewport boundary.
            base = 4 if delta > 0 else (extent - 9) & ~3
            yield from range(base, base + 4)
            return
        middle = (low + high) // 2
        for phase in range(4):
            positions = range(low + (phase - low) % 4, high + 1, 4)
            if positions:
                yield min(positions, key=lambda p: abs(p - middle))

    for span in (3, 55, 56, 57, 99, 158, 159):
        for minor in (max(1, span // 3), span - 1):
            for major, secondary in ((span, minor), (minor, span)):
                for dx, dy in product((-major, major), (-secondary, secondary)):
                    for x, y in product(starts(dx, WIDTH), starts(dy, HEIGHT)):
                        yield f"span {span} delta {dx},{dy}", (x, y, x + dx, y + dy)
    for x, y in product(range(40, 44), repeat=2):
        for dx, dy in product((-15, 0, 15), repeat=2):
            yield f"axis/diagonal {dx},{dy}", (x, y, x + dx, y + dy)


def motif_segments():
    yield from test_segments()
    yield "long shallow motif", (0, 3, 156, 42)
    yield "long shallow motif reversed", (159, 42, 3, 3)
    yield "long steep motif", (3, 0, 27, 96)
    for major, minor in ((38, 11), (36, 9)):
        for dx, dy in ((major, minor), (minor, major)):
            for sx, sy in product((-1, 1), repeat=2):
                for x, y in product(range(40, 44), repeat=2):
                    yield "motif alignment", (x, y, x + sx * dx, y + sy * dy)


def repeat_segments():
    yield from motif_segments()
    yield "quarter-slope shorter line", (0, 3, 92, 26)
    yield "three-quarter-slope fallback", (8, 9, 80, 63)
    yield "quarter-slope clipped to exact repeat", (-12, 0, 100, 28)
    for span in (32, 33):
        yield f"clipped horizontal span {span}", (-5, 20, span, 35)
        yield f"clipped horizontal span {span} reversed", (span, 35, -5, 20)
        yield f"clipped vertical span {span}", (20, -5, 35, span)
        yield f"clipped vertical span {span} reversed", (35, span, 20, -5)
    for dx, dy in ((44, 22), (22, 44)):
        for sx, sy in product((-1, 1), repeat=2):
            for x, y in product(range(48, 52), repeat=2):
                yield "half-slope repeat alignment", (x, y, x + sx * dx, y + sy * dy)


def expected_repetitions(clipped):
    if clipped is None:
        return 0
    x0, y0, x1, y1 = clipped
    dx, dy = x1 - x0, y1 - y0
    major_start, major_delta = (x0, dx) if abs(dx) >= abs(dy) else (y0, dy)
    major, minor = max(abs(dx), abs(dy)), min(abs(dx), abs(dy))
    if major == 0:
        return 0
    rate = (512 * minor + major) // (2 * major)
    if rate not in (0, 64, 128, 256):
        return 0
    normalized_start = (major_start & 3) ^ (3 if major_delta < 0 else 0)
    head = (-normalized_start) & 3
    samples_per_period = 1024 // gcd(rate, 256)
    repetitions = (major + 1 - head) // samples_per_period
    return repetitions if repetitions >= 2 else 0


def check_walker_operands(addresses, before, after, clipped):
    """Permit only the code bytes selected by this particular clipped line."""
    if clipped is None:
        return
    x0, y0, x1, y1 = clipped
    dx, dy = x1 - x0, y1 - y0
    steep = abs(dy) > abs(dx)
    octant = int(dx < 0) + 2 * (dy < 0) + 4 * steep
    start, delta = (y0, dy) if steep else (x0, dx)
    local = (start & 3) ^ (3 if delta < 0 else 0)
    count = 1 + abs(delta)
    prefix = min(4 - local, count) if local else 0
    full, tail = divmod(count - prefix, 4)

    def operand(name, opcode, target, operand_bytes):
        pc = addresses[name] - GUARD_START
        instruction = bytes((opcode, target & 255, target >> 8))
        if before[pc] != opcode or after[pc:pc + 3] != instruction:
            raise AssertionError(f"{clipped}: wrong instruction/operand at {name}, expected {instruction.hex()}")
        before[pc + 1:pc + 1 + operand_bytes] = instruction[1:1 + operand_bytes]

    if full and "firstEmpty" in addresses:
        for name, opcode, table in (("firstEmpty", 0xbd, "holeFullFirst"),
                                    ("firstBusy", 0xdd, "holeFullFirst"),
                                    ("secondGlyph", 0xbd, "holeFullSecond")):
            operand(name, opcode, addresses[table] + 64 * octant, 2)
    if "holePartialDispatch" in addresses:
        # A trailing single point has its own path in builds with holeTailDot.
        slot = local * 32 + (prefix - 1) * 8 + octant if prefix else None
        if tail >= (2 if "holeTailDot" in addresses else 1):
            slot = (tail - 1) * 8 + octant
        if slot is not None:
            operand("holePartialDispatch", 0x6c, addresses["holePartialJumps"] + 2 * slot, 1)


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


def verify_case(monitor, addresses, dump_file, pair, label, segment, window_walker=False, guard_end=GUARD_END):
    screen, charset, _ = pair
    screen_end = screen + 1000
    monitor.run(f"fill {screen:04x} {screen_end - 1:04x} 00")
    stub = entry_stub(addresses, segment, screen, charset)
    monitor.run(f"> {CALL_STUB:04x} {stub.hex(' ')}")
    before = bytearray(monitor.dump(dump_file, GUARD_START, guard_end))
    monitor.run(f"g {CALL_STUB:04x}")
    entry = monitor.registers()
    if entry["pc"] != addresses["drawClippedLine"]:
        raise AssertionError(f"{label}: did not enter native clip routine")
    execution = monitor.run("x")
    done = monitor.registers()
    if done["pc"] != addresses["halt"]:
        raise AssertionError(f"{label}: native clip routine did not return")
    after = monitor.dump(dump_file, GUARD_START, guard_end)
    clipped = visible_segment(segment)
    if window_walker:
        check_walker_operands(addresses, before, after, clipped)
    repeat_proof = {}
    if "globeRepeatRun" in addresses:
        hits = trace_execution(execution)
        select, run = addresses["globeRepeatSelect"], addresses["globeRepeatRun"]
        repeats = expected_repetitions(clipped)
        if (hits[select], hits[run]) != (bool(repeats), repeats):
            raise AssertionError(f"{label}: expected one selection and {repeats} runs when eligible, "
                                 f"observed {hits[select]} selections and {hits[run]} runs")
        repeat_proof = {"repeatSelections": hits[select], "repeatCalls": hits[run]}
        if repeats:
            operand = run + 1 - GUARD_START
            target = int.from_bytes(after[operand:operand + 2], "little")
            if not 0xe000 <= target < 0xfffa:
                raise AssertionError(f"{label}: repeat target outside the literal code bank")
            repeat_proof["repeatKernel"] = target
            before[operand:operand + 2] = after[operand:operand + 2]

    lower, upper = screen - GUARD_START, screen_end - GUARD_START
    if before[:lower] != after[:lower] or before[upper:] != after[upper:]:
        bad = next(GUARD_START + i for i, (old, new) in enumerate(zip(before, after))
                   if not lower <= i < upper and old != new)
        raise AssertionError(f"{label} {segment}: write outside screen at ${bad:04x}")

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
            "screen": screen, "nativeCycles": done["clock"] - entry["clock"] - 3,
            **repeat_proof}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/bin/x64sc"))
    renderer = parser.add_mutually_exclusive_group()
    renderer.add_argument("--crossing-holes", action="store_true",
                          help="check the globe's fixed-glyph drawer on both buffers and all eight octants")
    renderer.add_argument("--globe-motifs", action="store_true",
                          help="check generated globe fragments in all octants and starting alignments")
    renderer.add_argument("--globe-repeat", action="store_true",
                          help="verify fixed repeat dispatch and signed endpoints")
    add_junction_renderers(renderer)
    parser.add_argument("--build", type=Path, help="directory containing the PRG and its matching main.sym")
    args = parser.parse_args()
    window_walker = args.crossing_holes or bool(args.junction)
    variant = f"globe-{args.junction}" if args.junction else "globe-holes"
    if args.globe_motifs:
        variant = "globe-motifs"
    elif args.globe_repeat:
        variant = "globe-repeat"
    variant_build = window_walker or args.globe_motifs or args.globe_repeat
    default = BUILD / variant if variant_build else BUILD
    build = (args.build or default).resolve()
    program = build / (f"{variant}.prg" if variant_build else "linedrawer.prg")
    report = {"passed": False, "programSha256": sha(program.read_bytes()), "cases": []}
    process = connection = None
    try:
        text = assembly_symbols(build)
        addresses = {name: symbol(text, name) for name in (*LOW_BYTES, *HIGH_BYTES, "baseLo",
                    "baseHi", "drawCharsetHi", "cubeLoop", "drawClippedLine", "halt")}
        if window_walker:
            for name in ("firstEmpty", "firstBusy", "secondGlyph", "holeFullFirst", "holeFullSecond",
                         "holePartialDispatch", "holePartialJumps", "holeTailDot"):
                try:
                    addresses[name] = symbol(text, name)
                except ValueError:
                    pass
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
            segments = crossing_segments() if window_walker else (
                motif_segments() if args.globe_motifs else test_segments())
            guard_end = GUARD_END
            if window_walker:
                guard_end = 0xffff if args.junction else 0xcfff
            elif args.globe_repeat:
                segments = repeat_segments()
                guard_end = 0xffff
                for name in ("globeRepeatSelect", "globeRepeatRun"):
                    addresses[name] = symbol(text, name)
                    monitor.run(f"trace exec {addresses[name]:04x}")
            for index, (label, segment) in enumerate(segments):
                pairs = BUFFERS if window_walker else (BUFFERS[index % len(BUFFERS)],)
                for pair in pairs:
                    report["cases"].append(verify_case(monitor, addresses, scratch / "ram.bin",
                                                       pair, label, segment, window_walker, guard_end))
        if args.globe_repeat:
            by_name = {case["case"]: case for case in report["cases"]}
            longer = by_name["long shallow motif"]
            shorter = by_name["quarter-slope shorter line"]
            if (longer["repeatKernel"] != shorter["repeatKernel"] or
                    longer["repeatCalls"] == shorter["repeatCalls"]):
                raise AssertionError("Expected the same quarter-slope code at two different line lengths")
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
