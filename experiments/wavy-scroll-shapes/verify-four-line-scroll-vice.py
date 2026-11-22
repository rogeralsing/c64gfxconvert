#!/usr/bin/env python3
"""Verify the four-line scroller's motion and raster timing in PAL VICE."""

import argparse
from dataclasses import dataclass
from importlib import import_module
import json
from pathlib import Path
import socket
import struct
import subprocess
from tempfile import TemporaryDirectory

from PIL import Image, ImageChops

support = import_module("verify-four-line-vice")
from vice_monitor import Monitor, connect
from vice_support import read_labels, vice_command

ROW_BYTES = 1000
DEFAULT_FIELDS_PER_ADVANCE = 4
OWNER_RECORD = struct.Struct("<5H")
BANK_BASES = (0x4000, 0x8000)
LOGICAL_SIZE = (160, 200)
LOGICAL_PIXELS = LOGICAL_SIZE[0] * LOGICAL_SIZE[1]
SOURCE_ERROR_KEYS = ("mismatchedPixels", "backgroundSpill", "missingForeground", "wrongForegroundColor")


def valid_reference(reference, lookup_size):
    return reference < lookup_size or 0xff00 <= reference <= 0xff0f


def color_for_reference(reference, lookup):
    return reference & 15 if reference >= 0xff00 else lookup[reference]


def read_source_targets(directory, lookup_size):
    data = support.read_plane(directory / "target-tiles.bin", LOGICAL_PIXELS * 2)
    references = struct.unpack(f"<{LOGICAL_PIXELS}H", data)
    for pixel, reference in enumerate(references):
        support.require(valid_reference(reference, lookup_size),
                        f"{directory.name}: invalid source reference ${reference:04x} at logical pixel {pixel}")
    return references


def measure_source_errors(actual, targets, lookup, palette):
    # Native verification has already checked both display pixels in each pair.
    # Sample one per pair so a mismatch counts as one logical multicolor pixel.
    logical = actual.crop(support.CORE).resize(LOGICAL_SIZE, Image.Resampling.NEAREST)
    black = palette[0]
    spill = missing = wrong_color = 0
    for reference, observed in zip(targets, struct.iter_unpack("3B", logical.tobytes()), strict=True):
        wanted = palette[color_for_reference(reference, lookup)]
        if wanted != observed:
            if wanted == black:
                spill += 1
            elif observed == black:
                missing += 1
            else:
                wrong_color += 1
    return {"mismatchedPixels": spill + missing + wrong_color, "backgroundSpill": spill,
            "missingForeground": missing, "wrongForegroundColor": wrong_color}


def summarize_source_errors(fields):
    totals = {key: sum(field["sourceErrors"][key] for field in fields) for key in SOURCE_ERROR_KEYS}
    summary = {"fieldsCompared": len(fields), "totals": totals}
    if fields:
        worst = max(fields, key=lambda field: field["sourceErrors"]["mismatchedPixels"])
        summary["worstField"] = {key: worst[key] for key in ("field", "phase", "offset", "sourceErrors", "screenshot")
                                 if key in worst}
    return summary


@dataclass(frozen=True)
class Phase:
    bitmap: bytes
    owners: tuple
    late_rasters: tuple
    visible_color_cells: tuple

    @classmethod
    def read(cls, directory, lookup_size):
        bitmap = support.read_plane(directory / "bitmap.bin", 8000)
        raw_owners = support.read_plane(directory / "owners.bin", 1000 * OWNER_RECORD.size)
        owners = tuple(OWNER_RECORD.iter_unpack(raw_owners))
        late_groups = set()
        visible_colors = []
        for cell, (top_high, top_low, bottom_high, bottom_low, shared) in enumerate(owners):
            lower = {packed >> shift & 3 for packed in bitmap[cell * 8 + 4:cell * 8 + 8]
                     for shift in (6, 4, 2, 0)}
            if (1 in lower and top_high != bottom_high) or (2 in lower and top_low != bottom_low):
                late_groups.add(cell // 40)
            if any((packed >> shift & 3) == 3 for packed in bitmap[cell * 8:cell * 8 + 8]
                   for shift in (6, 4, 2, 0)):
                visible_colors.append(cell)
            for owner in (top_high, top_low, bottom_high, bottom_low, shared):
                support.require(valid_reference(owner, lookup_size),
                                f"{directory.name}: invalid owner ${owner:04x} at cell {cell}")
        return cls(bitmap, owners, tuple(55 + group * 8 for group in sorted(late_groups)),
                   tuple(visible_colors))

    def color_planes(self, lookup):
        top, bottom, shared = bytearray(), bytearray(), bytearray()
        for top_high, top_low, bottom_high, bottom_low, color in self.owners:
            top.append(color_for_reference(top_high, lookup) << 4 | color_for_reference(top_low, lookup))
            bottom.append(color_for_reference(bottom_high, lookup) << 4 | color_for_reference(bottom_low, lookup))
            shared.append(color_for_reference(color, lookup))
        return bytes(top), bytes(bottom), bytes(shared)


def seed_offset(monitor, symbols, offset):
    breakpoint = monitor.checkpoint(symbols["start"])
    monitor.run("x")
    support.require(monitor.registers()["pc"] == symbols["start"], "Did not reach the normal player entry point")
    monitor.run("bank ram")
    monitor.run(f"> {symbols['nextOffset']:04x} {offset & 255:02x} {offset >> 8:02x}")
    monitor.run("bank cpu")
    monitor.run(f"delete {breakpoint}")


def verify(args, report):
    assets = args.assets.resolve()
    try:
        raster_plan = json.loads((assets / "raster-plan.json").read_text())
    except FileNotFoundError:
        raster_plan = {}
    support.require(isinstance(raster_plan, dict), "Expected an object in raster-plan.json")
    step_half_columns = raster_plan.get("stepHalfColumns", 1)
    support.require(type(step_half_columns) is int and step_half_columns > 0,
                    "stepHalfColumns must be a positive integer")
    fields_per_advance = raster_plan.get("fieldsPerAdvance", DEFAULT_FIELDS_PER_ADVANCE)
    support.require(type(fields_per_advance) is int and fields_per_advance in (3, 4),
                    "fieldsPerAdvance must be 3 or 4")
    report["stepHalfColumns"] = step_half_columns
    report["fieldsPerAdvance"] = fields_per_advance
    phase_paths = (assets / "phase-a", assets / "phase-b")
    fit = json.loads((phase_paths[0] / "fit.json").read_text())
    columns, rows = fit["columns"], fit["radialRows"]
    support.require(isinstance(columns, int) and 1 <= columns <= 80, "Invalid wave column count")
    support.require(isinstance(rows, int) and 1 <= rows <= 32, "Invalid wave row count")
    stride, period = columns + 1, ROW_BYTES - columns + 1
    support.require(0 <= args.start_offset < period, f"Start offset must be between 0 and {period - 1}")
    phases = tuple(Phase.read(path, rows * stride) for path in phase_paths)
    source_targets = None
    if args.compare_source or args.target_assets is not None:
        target_assets = (args.target_assets or assets).resolve()
        source_targets = tuple(read_source_targets(target_assets / path.name, rows * stride) for path in phase_paths)
    colors = support.read_plane(assets / "row-colors.bin", rows * ROW_BYTES)
    support.require(all(color < 16 for color in colors), "Row color data includes an invalid C64 color")
    for row in range(rows):
        start = row * ROW_BYTES
        support.require(colors[start + period:start + ROW_BYTES] == colors[start:start + columns - 1],
                        f"Row {row} does not contain the wrap suffix")

    palette_path = support.ROOT / "palettes/colodore.vpl"
    palette = [tuple(int(channel, 16) for channel in line.split()[:3])
               for line in palette_path.read_text().splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    support.require(len(palette) == 16, "Invalid Colodore palette")
    symbols = read_labels(args.symbols or assets / "four-line-scroll-player.sym")
    checkpoint = symbols["frameComplete"]
    phase_addr, offset_addr = symbols["currentPhase"], symbols["currentOffset"]

    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    command = vice_command(args.vice, args.program, port, palette_path)
    command += ["-initbreak", "reset", "-warp", "-VICIIborders", "0"]

    with TemporaryDirectory(prefix="four-line-scroll-vice-") as temp, (args.out / "vice.log").open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            with connect(process, port) as connection:
                monitor = Monitor(connection)
                connection.settimeout(15)
                monitor.run("sidefx off")
                if args.start_offset:
                    seed_offset(monitor, symbols, args.start_offset)
                monitor.checkpoint(checkpoint)
                last_line_clock = None
                checked_bitmaps = set()
                source_errors = {}
                scratch = Path(temp) / "memory.bin"
                trace_path = args.out / "raster-trace.txt"
                with trace_path.open("w") as traces:
                    for field in range(args.fields):
                        trace = monitor.run("x")
                        registers = monitor.registers()
                        support.require(registers["pc"] == checkpoint and registers["raster"] == 256,
                                        f"Field {field}: unexpected VICE checkpoint {registers}")
                        line_clock = registers["clock"] - registers["raster_cycle"]
                        elapsed = None if last_line_clock is None else line_clock - last_line_clock
                        support.require(elapsed in (None, support.PAL_CLOCKS),
                                        f"Field {field}: expected one PAL field, measured {elapsed} cycles")
                        last_line_clock = line_clock

                        monitor.run("bank ram")
                        phase = monitor.dump(scratch, phase_addr, phase_addr)[0]
                        offset = int.from_bytes(monitor.dump(scratch, offset_addr, offset_addr + 1), "little")
                        advance = field // fields_per_advance
                        expected_offset, expected_phase = divmod(2 * args.start_offset + advance * step_half_columns, 2)
                        expected_offset %= period
                        support.require((phase, offset) == (expected_phase, expected_offset),
                                        f"Field {field}: expected phase {expected_phase}, offset {expected_offset}; "
                                        f"got phase {phase}, offset {offset}")
                        image = phases[phase]
                        if phase not in checked_bitmaps:
                            bitmap_address = BANK_BASES[phase] + 0x2000
                            support.require(monitor.dump(scratch, bitmap_address, bitmap_address + 7999) == image.bitmap,
                                            f"Phase {phase}: bitmap RAM differs from the asset")
                            checked_bitmaps.add(phase)

                        lookup = bytes(colors[row * ROW_BYTES + (offset + column) % period]
                                       for row in range(rows) for column in range(stride))
                        top, bottom, shared = image.color_planes(lookup)
                        monitor.run("bank io")
                        bank = monitor.dump(scratch, 0xdd00, 0xdd00)[0] & 3
                        support.require(bank == 2 - phase,
                                        f"Field {field}: CIA2 selected VIC bank {3 - bank}; expected {1 + phase}")
                        actual_colors = monitor.dump(scratch, 0xd800, 0xdbe7)
                        wrong_color = next((cell for cell in image.visible_color_cells
                                            if actual_colors[cell] & 15 != shared[cell]), None)
                        support.require(wrong_color is None,
                                        f"Field {field}: visible Color RAM differs at cell {wrong_color}")
                        monitor.run("bank cpu")

                        if field == 0:
                            monitor.run("trace store d011")
                            monitor.run("trace store d018")
                        else:
                            traces.write(trace)
                            # The $BB write only sets the high raster-IRQ compare bit for R256.
                            stores = [(register.lower(), int(line), int(cycle), int(value, 16))
                                      for register, line, cycle, value in support.STORE.findall(trace)
                                      if ((51 <= int(line) <= 250 and (register.lower(), value.lower()) != ("d011", "bb"))
                                          or (register.lower(), value.lower()) == ("d011", "3f"))]
                            expected_stores = support.expected_schedule(image.late_rasters)
                            support.require(stores == expected_stores,
                                            f"Field {field}: unexpected register schedule {stores}")

                        screenshot = Path(temp) / "frame.png"
                        monitor.run(f'screenshot "{screenshot}" 2')
                        with Image.open(screenshot) as frame:
                            actual = frame.convert("RGB")
                        expected = support.decode(image.bitmap, top, bottom, shared, palette)
                        support.require(actual.size == expected.size, f"Field {field}: wrong screenshot size {actual.size}")
                        difference = ImageChops.difference(actual, expected).getbbox()
                        support.require(difference is None, f"Field {field}: native pixel mismatch at {difference}")
                        frame_record = {"field": field, "phase": "AB"[phase], "offset": offset,
                                        "cyclesFromPreviousField": elapsed, "lateBadlineRasters": image.late_rasters,
                                        "timingTraced": field != 0, "corePixelsMatched": 64000}
                        if field % fields_per_advance == 0:
                            name = f"step-{advance:04d}.png"
                            actual.save(args.out / name)
                            frame_record["screenshot"] = name
                        if source_targets is not None:
                            step = (phase, offset)
                            if step not in source_errors:
                                source_errors[step] = measure_source_errors(actual, source_targets[phase], lookup, palette)
                            frame_record["sourceErrors"] = source_errors[step]
                        report["fields"].append(frame_record)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assets", type=Path)
    parser.add_argument("--program", type=Path, help="defaults to assets/wave-four-line-scroll.prg")
    parser.add_argument("--symbols", type=Path, help="defaults to assets/four-line-scroll-player.sym")
    parser.add_argument("--out", type=Path, help="defaults to assets/vice-proof")
    parser.add_argument("--fields", type=int, default=8)
    parser.add_argument("--start-offset", type=int, default=0)
    parser.add_argument("--vice", default="x64sc")
    parser.add_argument("--compare-source", action="store_true", help="measure errors against the phase target tiles")
    parser.add_argument("--target-assets", type=Path, help="compare with target tiles in another asset directory")
    args = parser.parse_args()
    if args.fields < 1:
        parser.error("--fields must be at least 1")
    args.program = (args.program or args.assets / "wave-four-line-scroll.prg").resolve()
    args.out = (args.out or args.assets / "vice-proof").resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "program": str(args.program), "startOffset": args.start_offset, "fields": []}
    try:
        verify(args, report)
        report["passed"] = True
        step = report["stepHalfColumns"]
        cadence = report["fieldsPerAdvance"]
        units = "half-column" if step == 1 else "half-columns"
        print(f"Verified {args.fields} PAL fields, advancing {step} {units} every {cadence} fields "
              "with 64,000 exact display pixels per field.")
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        report["error"] = str(error)
        print(error)
    finally:
        fields = [field for field in report["fields"] if "sourceErrors" in field]
        if fields:
            comparison = summarize_source_errors(fields)
            comparison["logicalPixelsPerField"] = LOGICAL_PIXELS
            comparison["phases"] = {phase: summarize_source_errors([field for field in fields if field["phase"] == phase])
                                    for phase in "AB"}
            report["sourceComparison"] = comparison
        (args.out / "vice-proof.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
