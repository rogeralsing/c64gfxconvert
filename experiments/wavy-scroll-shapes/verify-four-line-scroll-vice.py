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
    splits: tuple
    late_rasters: tuple
    visible_color_cells: tuple

    @classmethod
    def read(cls, directory, lookup_size):
        bitmap = support.read_plane(directory / "bitmap.bin", 8000)
        raw_owners = support.read_plane(directory / "owners.bin", 1000 * OWNER_RECORD.size)
        owners = tuple(OWNER_RECORD.iter_unpack(raw_owners))
        fit = json.loads((directory / "fit.json").read_text())
        splits = fit.get("splits", [4] * 25)
        support.require(isinstance(splits, list) and len(splits) == 25
                        and all(type(split) is int and 0 <= split <= 7 for split in splits)
                        and splits[-1] <= 4, f"{directory.name}: invalid VIC row splits")
        late_groups = set()
        visible_colors = []
        for cell, (top_high, top_low, bottom_high, bottom_low, shared) in enumerate(owners):
            row = cell // 40
            split = splits[row] or 8
            lower = {packed >> shift & 3 for packed in bitmap[cell * 8 + split:cell * 8 + 8]
                     for shift in (6, 4, 2, 0)}
            if (1 in lower and top_high != bottom_high) or (2 in lower and top_low != bottom_low):
                late_groups.add(row)
            if any((packed >> shift & 3) == 3 for packed in bitmap[cell * 8:cell * 8 + 8]
                   for shift in (6, 4, 2, 0)):
                visible_colors.append(cell)
            for owner in (top_high, top_low, bottom_high, bottom_low, shared):
                support.require(valid_reference(owner, lookup_size),
                                f"{directory.name}: invalid owner ${owner:04x} at cell {cell}")
        return cls(bitmap, owners, tuple(splits),
                   tuple(51 + group * 8 + splits[group] for group in sorted(late_groups)),
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


def read_y_sine(raster_plan, max_window_start):
    if "ySine" not in raster_plan:
        return None
    sine = raster_plan["ySine"]
    support.require(isinstance(sine, dict) and max_window_start > 0,
                    "Y sine requires a moving active window")
    base, positions = sine.get("base"), sine.get("positions")
    support.require(type(base) is int and 0 <= base <= 7, "Invalid Y sine register base")
    support.require(isinstance(positions, list) and positions and
                    all(type(value) is int and 0 <= value <= 4 * max_window_start
                        and base + (value & 3) <= 7 for value in positions),
                    "Y sine positions must be valid quarter-row values")
    support.require(isinstance(sine.get("stateLabel"), str), "Missing Y sine state label")
    return sine


def shift_frame(frame, y_delta):
    if y_delta == 0:
        return frame
    shifted = Image.new("RGB", frame.size)
    shifted.paste(frame, (0, y_delta))
    return shifted


def traced_schedule(trace, y_sine, y_scroll):
    stores = [(register.lower(), int(line), int(cycle), int(value, 16))
              for register, line, cycle, value in support.STORE.findall(trace)]
    if y_sine is not None:
        # Include the display range at every fine scroll setting and skip the
        # D011 value that arms the high raster IRQ for vblank.
        vblank_control = 0xb8 | y_scroll
        return [(register, line, cycle, value) for register, line, cycle, value in stores
                if 48 <= line <= 254 and (register, value) != ("d011", vblank_control)]
    return [(register, line, cycle, value) for register, line, cycle, value in stores
            if (51 <= line <= 250 and (register, value) != ("d011", 0xbb))
            or (register == "d011" and 0x38 <= value <= 0x3f and value != 0x3b)]


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
    support.require(type(fields_per_advance) is int and fields_per_advance in (2, 3, 4),
                    "fieldsPerAdvance must be 2, 3 or 4")
    vblank_raster = raster_plan.get("vblankRaster", 256)
    support.require(type(vblank_raster) is int and 256 <= vblank_raster < 312, "Invalid vblank raster")
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
    active_rows = raster_plan.get("activeRows", rows)
    window_pairs = raster_plan.get("windowPairsToHold", 1)
    support.require(type(active_rows) is int and 1 <= active_rows <= rows and
                    type(window_pairs) is int and window_pairs >= 1, "Invalid active wave window")
    max_window_start = rows - active_rows
    y_sine = read_y_sine(raster_plan, max_window_start)
    if y_sine is not None:
        report["ySine"] = y_sine
    colors = support.read_plane(assets / "row-colors.bin", active_rows * ROW_BYTES)
    support.require(all(color < 16 for color in colors), "Row color data includes an invalid C64 color")
    for row in range(active_rows):
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
    window_addr = symbols["displayWindowStart"] if max_window_start else None
    y_addr = symbols[y_sine["stateLabel"]] if y_sine is not None else None
    missed_addr = symbols.get("missedDeadline")

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
                        support.require(registers["pc"] == checkpoint and registers["raster"] == vblank_raster,
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
                        y_scroll = 3
                        window_start = 0
                        if window_addr is not None:
                            if y_sine is None:
                                position = (advance // 2 // window_pairs) % (2 * max_window_start)
                                expected_window = min(position, 2 * max_window_start - position)
                            else:
                                positions = y_sine["positions"]
                                expected_window, fine_scroll = divmod(positions[(advance // 2) % len(positions)], 4)
                                y_scroll = y_sine["base"] + fine_scroll
                            window_start = monitor.dump(scratch, window_addr, window_addr)[0]
                            support.require(window_start == expected_window,
                                            f"Field {field}: expected window {expected_window}, got {window_start}")
                        if y_addr is not None:
                            actual_y = monitor.dump(scratch, y_addr, y_addr)[0]
                            support.require(actual_y == y_scroll,
                                            f"Field {field}: expected Y scroll {y_scroll}, got {actual_y}")
                        if missed_addr is not None:
                            support.require(monitor.dump(scratch, missed_addr, missed_addr)[0] == 0,
                                            f"Field {field}: player missed a display deadline")
                        expected_offset, expected_phase = divmod(2 * args.start_offset + advance * step_half_columns, 2)
                        expected_offset %= period
                        support.require((phase, offset) == (expected_phase, expected_offset),
                                        f"Field {field}: expected phase {expected_phase}, offset {expected_offset}; "
                                        f"got phase {phase}, offset {offset}")
                        image = phases[phase]
                        y_delta = y_scroll - 3
                        late_rasters = tuple(raster + y_delta for raster in image.late_rasters)
                        if phase not in checked_bitmaps:
                            bitmap_address = BANK_BASES[phase] + 0x2000
                            phase_name = "AB"[phase]
                            first = symbols.get(f"bitmapBodyStart{phase_name}", bitmap_address)
                            last = symbols.get(f"bitmapBodyEnd{phase_name}", bitmap_address + 8000)
                            support.require(bitmap_address <= first < last <= bitmap_address + 8000,
                                            f"Phase {phase}: invalid bitmap RAM bounds")
                            start, end = first - bitmap_address, last - bitmap_address
                            support.require(not any(image.bitmap[:start]) and not any(image.bitmap[end:]),
                                            f"Phase {phase}: runtime overlaps the visible bitmap")
                            support.require(monitor.dump(scratch, first, last - 1) == image.bitmap[start:end],
                                            f"Phase {phase}: bitmap RAM differs from the asset")
                            checked_bitmaps.add(phase)

                        lookup = bytes(colors[(row - window_start) * ROW_BYTES + (offset + column) % period]
                                       if window_start <= row < window_start + active_rows else 0
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
                            expected_stores = [(register, line, cycle,
                                                (0x38 | y_scroll) if register == "d011" and cycle == 60 else value)
                                               for register, line, cycle, value in support.expected_schedule(late_rasters)]
                            stores = traced_schedule(trace, y_sine, y_scroll)
                            support.require(stores == expected_stores, f"Field {field}: unexpected register schedule {stores}")

                        screenshot = Path(temp) / "frame.png"
                        monitor.run(f'screenshot "{screenshot}" 2')
                        with Image.open(screenshot) as frame:
                            actual = frame.convert("RGB")
                        expected = support.decode(image.bitmap, top, bottom, shared, palette, image.splits)
                        support.require(actual.size == expected.size, f"Field {field}: wrong screenshot size {actual.size}")
                        difference = ImageChops.difference(actual, shift_frame(expected, y_delta)).getbbox()
                        support.require(difference is None, f"Field {field}: native pixel mismatch at {difference}")
                        frame_record = {"field": field, "phase": "AB"[phase], "offset": offset,
                                        "cyclesFromPreviousField": elapsed, "lateBadlineRasters": late_rasters,
                                        "timingTraced": field != 0, "corePixelsMatched": 64000}
                        if window_addr is not None:
                            frame_record["windowStart"] = window_start
                        if y_sine is not None:
                            frame_record["yOffset"] = y_delta
                        if field % fields_per_advance == 0:
                            name = f"step-{advance:04d}.png"
                            actual.save(args.out / name)
                            frame_record["screenshot"] = name
                        if source_targets is not None:
                            step = (phase, offset, window_start, y_delta)
                            if step not in source_errors:
                                aligned = shift_frame(actual, -y_delta)
                                source_errors[step] = measure_source_errors(aligned, source_targets[phase], lookup, palette)
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
