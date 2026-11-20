#!/usr/bin/env python3
"""Verify default C64 startup and selected wireframe frames in headless PAL VICE.

Run the unmodified PRG through its normal autostart path. At each border flip,
prove the visible screen and charset stayed unchanged while the back pair was
drawn. Compare presented frames with the independent Python model. The verifier
owns and cleans up only its VICE process.
"""
import argparse
from collections import Counter
from functools import partial
import hashlib
import importlib.util
import json
import re
import socket
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
MODE = 0x0338
JCOUNT = 0xa770
COMPACT_PATCH_START = 234
ONE_CHAR_CODE = 201
HOLE_CODE = 201
FIRST_PRIVATE_GLYPH = 201
BUFFERS = ((0x0400, 0x2000, 0x18), (0x2c00, 0x3000, 0xbc))
PAL_LINES = 312
PAL_CYCLES_PER_LINE = 63
PAL_CLOCK = 985248


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_monitor():
    spec = importlib.util.spec_from_file_location(
        "vice_monitor", HERE.parent / "movieplayer" / "vice_monitor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def symbol(text, name):
    label = re.escape(name)
    match = re.search(rf"^\.label {label}=\$([0-9a-fA-F]+)\b", text, re.M)
    if not match:
        match = re.search(rf"^(?i:al)[ \t]+[Cc]:([0-9a-fA-F]+)[ \t]+\.{label}[ \t]*$", text, re.M)
    if not match:
        raise ValueError(f"Missing assembly symbol: {name}")
    return int(match[1], 16)


def assembly_symbols(output):
    for filename in ("main.sym", "main.vs"):
        path = output / filename
        if path.is_file():
            symbols = path.read_text()
            if symbols.strip():
                return symbols
    raise ValueError(f"No assembly symbols in {output}")


def counter_values(memory, addresses):
    return {key: int.from_bytes(memory[address:address + 2], "little")
            for key, address in addresses.items()}


def trace_execution(response):
    return Counter(int(address, 16) for address in
                   re.findall(r"\(Trace\s+exec ([0-9a-fA-F]{4})\)", response))


def verify_repeat_frame(index, response, addresses):
    """Compare per-line selection and native JMP executions with the repeat plan."""
    from ball_model import frame_segments
    from globe_repeat import line_plan

    line_address, select_address, jump_address = addresses
    trace = re.findall(r"\(Trace\s+exec ([0-9a-fA-F]{4})\)[^\n]*\n(\.C:[^\n]*)", response)
    lines = []
    for address, instruction in trace:
        pc = int(address, 16)
        if pc == line_address:
            lines.append([])
        elif lines:
            lines[-1].append((pc, instruction))
        else:
            raise AssertionError(f"Repeat trace before the first line of frame {index}")

    segments = frame_segments("globe", index)
    if len(lines) != len(segments):
        raise AssertionError(f"Line trace in frame {index}: {len(lines)}/{len(segments)} lines")

    counts = {"linesChecked": len(lines), "selectedLines": 0, "repeatCalls": 0}
    witness = None
    for line, (events, segment) in enumerate(zip(lines, segments), start=1):
        plan = line_plan(segment)
        expected = [select_address] + [jump_address] * plan.repeats if plan else []
        observed = [pc for pc, _ in events]
        if observed != expected:
            raise AssertionError(
                f"Repeat sequence in frame {index}, line {line}: expected "
                f"{int(plan is not None)} selects and {plan.repeats if plan else 0} calls in order, "
                f"observed {observed.count(select_address)} selects and {observed.count(jump_address)} calls"
            )
        if plan is None:
            continue

        targets = set()
        for _, instruction in events[1:]:
            direct_jump = re.search(r"\bJMP\s+\$([0-9a-fA-F]{4})\b", instruction)
            if not direct_jump:
                raise AssertionError(f"Missing direct kernel JMP in frame {index}, line {line}")
            targets.add(int(direct_jump[1], 16))
        if len(targets) != 1 or plan.repeats < 2:
            raise AssertionError(f"Repeat kernel changed or did not repeat in frame {index}, line {line}")

        counts["selectedLines"] += 1
        counts["repeatCalls"] += plan.repeats
        if witness is None:
            witness = {"frame": index, "line": line, "segment": segment, "kernelAddress": next(iter(targets)),
                       "selections": 1, "repeatCalls": plan.repeats}
    return counts, witness


def globe_full_group_count(index):
    """Count aligned four-sample groups independently of kernel selection."""
    from ball_model import frame_segments

    count = 0
    for x0, y0, x1, y1 in frame_segments("globe", index):
        dx, dy = x1 - x0, y1 - y0
        start, span = (x0, dx) if abs(dx) >= abs(dy) else (y0, dy)
        phase = (start & 3) ^ (3 if span < 0 else 0)
        leading = (-phase) & 3
        count += max(0, (abs(span) + 1 - leading) // 4)
    return count


def glyph_rows(pattern):
    rows = bytearray(8)
    for y in range(4):
        for x in range(4):
            if pattern & (1 << (y * 4 + x)):
                rows[2 * y] |= 0xc0 >> (2 * x)
                rows[2 * y + 1] |= 0xc0 >> (2 * x)
    return rows


def compact_font(assets):
    """Read the fixed glyphs and the hybrid mask-to-code lookup."""
    lo, hi, lengths = ((assets / f"compact-buckets-{suffix}.bin").read_bytes()
                       for suffix in ("lo", "hi", "length"))
    keys = (assets / "compact-keys.bin").read_bytes()
    codes = (assets / "compact-codes.bin").read_bytes()
    charset = (assets / "compact-charset.bin").read_bytes()
    if not (len(lo) == len(hi) == len(lengths) == 256
            and len(keys) == len(codes) == sum(lengths) and len(charset) == 2048):
        raise ValueError("Bad compact-font asset sizes")

    code_for_mask = {0: 0}
    position = 0
    for high, length in enumerate(lengths):
        if (lo[high] | (hi[high] << 8)) != position:
            raise ValueError(f"Bad compact-font bucket offset for {high:#04x}")
        end = position + length
        for low, code in zip(keys[position:end], codes[position:end]):
            mask = (high << 8) | low
            if mask in code_for_mask or not 0 < code < COMPACT_PATCH_START:
                raise ValueError(f"Bad compact-font mapping for {mask:#06x}")
            code_for_mask[mask] = code
        position = end
    return charset, code_for_mask


def compare_compact(index, screen, charset, fixed_font, code_for_mask, allocated):
    """Compare the displayed glyph masks without assuming a patch allocation order."""
    from ball_model import frame_segments
    from cube_model import normalized_cells

    masks = [0] * 1000
    for segment in frame_segments("globe", index):
        for cell, pattern in normalized_cells(*segment):
            masks[cell] |= pattern

    reserve_codes = {code for code in screen[:1000] if code >= COMPACT_PATCH_START}
    expected_patches = len(set(masks) - code_for_mask.keys())
    budget_ok = (allocated == expected_patches and allocated <= 256 - COMPACT_PATCH_START
                 and reserve_codes == set(range(COMPACT_PATCH_START, COMPACT_PATCH_START + allocated)))

    different = []
    wrong_glyphs = set()
    wrong_codes = []
    for cell, (mask, actual) in enumerate(zip(masks, screen)):
        fixed_code = code_for_mask.get(mask)
        if fixed_code is None:
            expected_rows = glyph_rows(mask)
            code_ok = actual >= COMPACT_PATCH_START
        else:
            expected_rows = fixed_font[fixed_code * 8:fixed_code * 8 + 8]
            code_ok = actual == fixed_code
        if not code_ok:
            wrong_codes.append((cell % 40, cell // 40, fixed_code, actual))
        if charset[actual * 8:actual * 8 + 8] != expected_rows:
            wrong_glyphs.add(actual)
            different.append((cell % 40, cell // 40, mask, actual))
    return not (different or wrong_codes) and budget_ok, {
        "displayedGlyphsEqual": not different,
        "staticCodesMatch": not wrong_codes,
        "firstDiffCells": different[:8],
        "firstWrongCodes": wrong_codes[:8],
        "wrongGlyphs": sorted(wrong_glyphs)[:8],
        "jointSlots": len(reserve_codes),
        "patchCount": allocated,
        "expectedPatches": expected_patches,
        "patchSlotsValid": budget_ok,
    }


def compare_normal(index, frame_screen, tile_to_code, screen, charset, fixed_font):
    expected, joints = frame_screen(index, tile_to_code)
    wanted_font = bytearray(fixed_font)
    for slot, pattern in enumerate(joints):
        wanted_font[(201 + slot) * 8:(202 + slot) * 8] = glyph_rows(pattern)
    different = [cell for cell in range(1000) if screen[cell] != expected[cell]]
    wrong_glyphs = [code for code in sorted(set(expected))
                    if charset[code * 8:code * 8 + 8] != wanted_font[code * 8:code * 8 + 8]]
    return not (different or wrong_glyphs), {
        "screenBytesEqual": not different,
        "displayedGlyphsEqual": not wrong_glyphs,
        "firstDiffCells": [(cell % 40, cell // 40, expected[cell], screen[cell])
                           for cell in different[:8]],
        "wrongGlyphs": wrong_glyphs[:8],
        "jointSlots": len(joints),
    }


def one_char_font_ok(charset):
    block = ONE_CHAR_CODE * 8
    return charset[:8] == bytes(8) and charset[block:block + 8] == b"\xff" * 8


def compare_one_char(index, screen, allocated):
    """Verify the block footprint of all Q8 line stamps."""
    from ball_model import frame_segments
    from cube_model import normalized_cells

    expected = bytearray(1000)
    for segment in frame_segments("globe", index):
        for cell, _ in normalized_cells(*segment):
            expected[cell] = ONE_CHAR_CODE
    return compare_zero_patch(expected, screen, allocated)


def compare_crossing_holes(index, screen, tile_to_code, allocated):
    """Use a blank marker once a cell receives two different line codes."""
    from ball_model import HOLES_CAMERA, HOLES_Y_SWEEP, frame_segments
    from cube_model import normalized_cells

    expected = bytearray(1000)
    for segment in frame_segments("globe", index, camera=HOLES_CAMERA, y_sweep=HOLES_Y_SWEEP):
        for cell, pattern in normalized_cells(*segment):
            code = tile_to_code[pattern] + 1
            expected[cell] = code if expected[cell] in (0, code) else HOLE_CODE
    matches, report = compare_zero_patch(expected, screen, allocated)
    report["holeCells"] = screen[:1000].count(HOLE_CODE)
    return matches, report


def compare_private_glyphs(masks, screen, charset, allocated):
    """Check the visible union and that each patch belongs to a single cell."""
    different = []
    private_codes = []
    for cell, code in enumerate(screen[:1000]):
        mask = masks.get(cell, 0)
        rows = charset[8 * code:8 * (code + 1)]
        if rows != glyph_rows(mask) or (mask == 0) != (code == 0):
            different.append((cell % 40, cell // 40, code, mask, rows.hex()))
        if code >= FIRST_PRIVATE_GLYPH:
            private_codes.append(code)
    slots_valid = sorted(private_codes) == list(range(FIRST_PRIVATE_GLYPH, FIRST_PRIVATE_GLYPH + allocated))
    return not different and slots_valid, {
        "displayedGlyphsEqual": not different, "firstDiffCells": different[:8],
        "patchCount": allocated, "jointSlots": allocated, "privateSlotsValid": slots_valid,
    }


def compare_exact_corners(index, screen, charset, tile_to_code, allocated):
    from thin_faces import expected

    masks, counts = expected(index, tile_to_code)
    matches, report = compare_private_glyphs(masks, screen, charset, allocated)
    return matches, {**report, "omittedEdges": counts["removed"]}


def compare_deferred_globe(index, screen, charset, allocated):
    from ball_model import frame_segments
    from cube_model import normalized_cells

    masks = {}
    for segment in frame_segments("globe", index):
        for cell, mask in normalized_cells(*segment):
            masks[cell] = masks.get(cell, 0) | mask
    return compare_private_glyphs(masks, screen, charset, allocated)


def compare_zero_patch(expected, screen, allocated):
    different = [(cell % 40, cell // 40, code, screen[cell])
                 for cell, code in enumerate(expected) if screen[cell] != code]
    return not different and allocated == 0, {
        "screenBytesEqual": not different,
        "firstDiffCells": different[:8],
        "jointSlots": allocated,
        "patchCount": allocated,
    }


def buffer_bytes(memory, pair):
    screen, charset, _ = pair
    return bytes(memory[screen:screen + 1024]), bytes(memory[charset:charset + 2048])


def scanout_errors(picture, screen, charset):
    """Compare the completed PAL scanout with the actual visible RAM pair."""
    from PIL import Image

    with Image.open(picture) as image:
        if image.size != (384, 272):
            raise AssertionError(f"Unexpected PAL screenshot size: {image.size}")
        pixels = image.convert("L").crop((32, 35, 352, 235)).tobytes()
    errors = 0
    for y in range(200):
        for x in range(320):
            code = screen[(y >> 3) * 40 + (x >> 3)]
            expected = (charset[code * 8 + (y & 7)] >> (7 - (x & 7))) & 1
            errors += (pixels[y * 320 + x] > 128) != bool(expected)
    return errors


def add_junction_renderers(group):
    group.add_argument("--exact-corners", dest="junction", action="store_const", const="exact-corners",
                       help="verify the globe with private glyphs at crossings")
    group.add_argument("--fixed-junction-font", dest="junction", action="store_const", const="fixed-junction-font",
                       help="verify the globe with the immutable junction font")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/bin/x64sc"))
    parser.add_argument("--shape", choices=("cube", "football", "globe"))
    renderer = parser.add_mutually_exclusive_group()
    renderer.add_argument("--compact-joins", action="store_true", help="verify the compact-font globe")
    renderer.add_argument("--one-char", action="store_true", help="verify the solid-block globe")
    renderer.add_argument("--crossing-holes", action="store_true", help="verify the globe with blank crossings")
    renderer.add_argument("--globe-replay", action="store_true", help="verify collision-aware globe motif replay")
    renderer.add_argument("--globe-motifs", action="store_true", help="verify reusable two-group globe kernels")
    renderer.add_argument("--globe-repeat", action="store_true", help="verify once-per-line globe kernel selection")
    add_junction_renderers(renderer)
    parser.add_argument("--replay-stats", action="store_true",
                        help="read hit and attempt counts from an instrumented globe replay build")
    parser.add_argument("--motif-coverage", action="store_true",
                        help="trace generated kernels and verify coverage of all globe full groups")
    parser.add_argument("--build", type=Path,
                        help="directory containing the selected PRG and matching main.sym or main.vs")
    frames = parser.add_mutually_exclusive_group()
    frames.add_argument("--frames", type=int, nargs="+", default=[0, 1, 2, 3, 16, 64, 196, 197],
                        help="zero-based frames to verify during normal animation (0..255)")
    frames.add_argument("--all-frames", action="store_true", help="verify all 256 poses and PAL scanouts")
    parser.add_argument("--timeout", type=float, default=30,
                        help="maximum seconds waiting for each VICE monitor response")
    args = parser.parse_args()
    if any(not 0 <= frame <= 255 for frame in args.frames) or not 0 < args.timeout <= 60:
        parser.error("--frames must be 0..255 and --timeout must be greater than 0 and at most 60")
    if args.replay_stats and not args.globe_replay:
        parser.error("--replay-stats requires --globe-replay")
    if args.motif_coverage and not args.globe_motifs:
        parser.error("--motif-coverage requires --globe-motifs")

    exact_corners = args.junction == "exact-corners"
    fixed_junction_font = args.junction == "fixed-junction-font"
    zero_patch = args.one_char or args.crossing_holes or fixed_junction_font
    globe_only = args.compact_joins or zero_patch or exact_corners
    experimental_globe = args.globe_replay or args.globe_motifs or args.globe_repeat
    shape = args.shape or ("globe" if globe_only or experimental_globe else "cube")
    flag = None
    variant = shape
    if args.compact_joins:
        flag, variant = "--compact-joins", "globe-compact"
    elif args.one_char:
        flag, variant = "--one-char", "globe-one-char"
    elif args.crossing_holes:
        flag, variant = "--crossing-holes", "globe-holes"
    elif args.globe_replay:
        flag, variant = "--globe-replay", "globe-replay"
    elif args.globe_motifs:
        flag, variant = "--globe-motifs", "globe-motifs"
    elif args.globe_repeat:
        flag, variant = "--globe-repeat", "globe-repeat"
    elif args.junction:
        flag, variant = f"--{args.junction}", f"globe-{args.junction}"
    if flag and shape != "globe":
        parser.error(f"{flag} requires the globe")
    default_output = BUILD if variant == "cube" else BUILD / variant
    output = (args.build or default_output).resolve()
    program = output / ("linedrawer.prg" if variant == "cube" else f"{variant}.prg")
    selected = set(range(256) if args.all_frames else args.frames)
    last = max(selected)
    report = {"shape": shape, "passed": False, "defaultLaunch": False, "doubleBuffered": False,
              "frontIntegrityChecks": 0, "presentationsChecked": 0, "frames": []}
    if args.globe_replay:
        report.update(globeReplay=True, replayPathReached=False)
    if args.globe_motifs:
        report.update(globeMotifs=True, motifPathReached=False, motifSamples=0)
    if args.motif_coverage:
        report["motifCoverage"] = {"framesChecked": 0, "fullGroups": 0, "pairCalls": 0, "singleCalls": 0}
    if args.globe_repeat:
        report.update(globeRepeat=True, repeatCoverage={"framesChecked": 0, "linesChecked": 0,
                                                        "selectedLines": 0, "repeatCalls": 0})
    if args.replay_stats:
        report.update(replayAttempts=0, replayHits=0, replayFramesWithHits=0)
    process = connection = log = None
    try:
        if args.compact_joins:
            expected_font, code_for_mask = compact_font(output.parent)
            fixed_size = COMPACT_PATCH_START * 8
            report["compactJoins"] = True
        elif args.one_char:
            report["oneChar"] = True
        elif fixed_junction_font:
            from fixed_junction_font import assets, expected_screen
            expected_font = assets()["charset"]
            report["fixedJunctionFont"] = True
        else:
            import linedrawer

            if args.crossing_holes:
                report["crossingHoles"] = True
            elif exact_corners:
                report["exactCorners"] = True
            elif shape == "cube":
                from cube_model import frame_screen
            else:
                from ball_model import frame_screen as ball_screen
                frame_screen = partial(ball_screen, shape)
            tile_to_code, tiles, _ = linedrawer.build_font()
            expected_font = linedrawer.charset_bytes(tiles)
            fixed_size = 201 * 8
        report["programSha256"] = sha(program.read_bytes())
        symbols = assembly_symbols(output)
        loop = symbol(symbols, "cubeLoop")
        present = symbol(symbols, "presentFrame")
        halt = symbol(symbols, "halt")
        frame_counter = symbol(symbols, "frmcnt")
        replay_addresses = {}
        replay_ram_end = 0x3fff
        proof_hit = replay_stats_marker = None
        if args.globe_replay:
            proof_hit = symbol(symbols, "globeReplayHit")
            replay_stats_marker = symbol(symbols, "globeReplayStatsEnabled")
        if args.globe_motifs:
            proof_hit = symbol(symbols, "globeMotifsRun")
            motif_major_span = symbol(symbols, "cwMajorDelta")
        if args.motif_coverage:
            motif_single_hit = symbol(symbols, "globeMotifsOneRun")
        deferred_overflow = None
        if args.globe_repeat:
            repeat_trace = tuple(symbol(symbols, name) for name in
                                 ("drawCharLine", "globeRepeatSelect", "globeRepeatRun"))
            try:
                symbol(symbols, "deferredFlush")
            except ValueError:
                pass  # Older and immediate builds use the shared glyph allocator.
            else:
                deferred_overflow = symbol(symbols, "deferredOverflow")
            report["deferredGlobeJoins"] = deferred_overflow is not None
        if args.replay_stats:
            replay_addresses = {
                "replayAttempts": symbol(symbols, "globeReplayAttempts"),
                "replayHits": symbol(symbols, "globeReplayHits"),
            }
            replay_ram_end = max(replay_ram_end, max(replay_addresses.values()) + 1)
        vm = load_monitor()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        command = [str(args.vice), "-default", "+saveres", "-minimized", "-pal",
                   "-speed", "100", "-warp", "+autostart-warp", "+confirmonexit",
                   "-sounddev", "dummy", "+refreshonbreak", "-initbreak", "reset",
                   "-autostartprgmode", "1", "-autostart", str(program),
                   "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
        log = (output / "vice.log").open("w")
        process = subprocess.Popen(command, cwd=output, stdout=log, stderr=log)
        connection = vm.connect(process, port)
        monitor = vm.Monitor(connection)
        connection.settimeout(args.timeout)
        monitor.checkpoint(loop)
        monitor.checkpoint(present)
        monitor.checkpoint(halt)
        if args.motif_coverage:
            monitor.run(f"trace exec {proof_hit:04x}")
            monitor.run(f"trace exec {motif_single_hit:04x}")
        if args.globe_repeat:
            for address in repeat_trace:
                monitor.run(f"trace exec {address:04x}")
        hit_checkpoint = monitor.checkpoint(proof_hit) if proof_hit is not None else None
        monitor.run("x")
        if monitor.registers()["pc"] != loop:
            raise AssertionError(f"Default launch halted before the first {shape} frame")
        monitor.run("bank ram")
        initial_end = max(replay_ram_end, replay_stats_marker or 0)
        initial = monitor.dump(output / "initial-ram.bin", 0, initial_end)
        initial_mode, initial_frame = initial[MODE], initial[frame_counter]
        if replay_stats_marker is not None:
            report["replayStatsEnabled"] = initial[replay_stats_marker] == 1
            if args.replay_stats and not report["replayStatsEnabled"]:
                raise ValueError("--replay-stats requires a PRG assembled with globeReplayStats")
        previous_counts = counter_values(initial, replay_addresses)
        if any(previous_counts.values()):
            raise AssertionError("Replay counters did not start at zero")
        monitor.run("bank cpu")
        report["defaultLaunch"] = initial_mode == 0 and initial_frame == 0
        if not report["defaultLaunch"]:
            raise AssertionError(f"Default launch did not start free animation: MODE={initial_mode}, frame={initial_frame}")
        if zero_patch or exact_corners:
            initial_fonts = [buffer_bytes(initial, pair)[1] for pair in BUFFERS]
        if args.junction:
            report["originalFontsInBothCharsets"] = all(font == expected_font for font in initial_fonts)
            if not report["originalFontsInBothCharsets"]:
                raise AssertionError("Both VIC banks must start with the expected font")
        if args.one_char:
            report["fixedBlockGlyphInBothCharsets"] = all(one_char_font_ok(font) for font in initial_fonts)
            if not report["fixedBlockGlyphInBothCharsets"]:
                raise AssertionError("Expected blank code 0 and solid block code 201 in both charsets")
        if args.crossing_holes:
            report["originalFontsInBothCharsets"] = all(font == expected_font for font in initial_fonts)
            block = HOLE_CODE * 8
            report["fixedHoleGlyphInBothCharsets"] = all(font[block:block + 8] == bytes(8) for font in initial_fonts)
            if not (report["originalFontsInBothCharsets"] and report["fixedHoleGlyphInBothCharsets"]):
                raise AssertionError("Expected the original line bank and blank marker code 201 in both charsets")
        front = 0
        previous_screen, previous_charset = buffer_bytes(initial, BUFFERS[front])
        previous_visible_field = None
        presentation_fields = []
        by_index = {}
        motif_examples = {}

        # The extra pre-flip boundary gives the last selected frame a full
        # physical scanout before its screenshot; it is never presented itself.
        for index in range(last + 2):
            response = monitor.run("x")
            trace_hits = trace_execution(response) if args.motif_coverage else None
            registers = monitor.registers()
            while hit_checkpoint is not None and registers["pc"] == proof_hit:
                if args.globe_replay:
                    report.update(replayPathReached=True, firstReplayFrame=index)
                else:
                    if not report["motifPathReached"]:
                        report.update(motifPathReached=True, firstMotifFrame=index)
                    monitor.run("bank ram")
                    # The runtime patches the direct JMP operand with the selected kernel.
                    target = monitor.dump(output / "last-motif-target.bin", proof_hit + 1, proof_hit + 2)
                    major = monitor.dump(output / "last-motif-major.bin", motif_major_span, motif_major_span)[0]
                    monitor.run("bank cpu")
                    kernel = int.from_bytes(target, "little")
                    previous_major, previous_index = motif_examples.setdefault(kernel, (major, index))
                    report["motifSamples"] += 1
                    if previous_major != major:
                        report["motifReuseWitness"] = {
                            "kernelAddress": kernel,
                            "majorSpans": [previous_major, major],
                            "frames": [previous_index, index],
                        }
                if args.globe_replay or "motifReuseWitness" in report:
                    monitor.run(f"delete {hit_checkpoint}")
                    hit_checkpoint = None
                response = monitor.run("x")
                if trace_hits is not None:
                    trace_hits.update(trace_execution(response))
                registers = monitor.registers()
            if registers["pc"] != present:
                raise AssertionError(f"Animation halted before presenting {shape} frame {index}")
            monitor.run("bank ram")
            last_byte = replay_ram_end
            if (globe_only or deferred_overflow is not None) and index in selected:
                last_byte = max(last_byte, JCOUNT + (1 if args.junction else 0))
            memory = monitor.dump(output / "last-before-present.bin", 0, last_byte)
            front_screen, front_charset = buffer_bytes(memory, BUFFERS[front])
            monitor.run("bank io")
            vic = monitor.dump(output / "last-vic.bin", 0xd011, 0xd021)
            d018_before = vic[7] & 0xfe
            monitor.run("bank cpu")
            screen_untouched = front_screen == previous_screen
            charset_untouched = front_charset == previous_charset
            raster = registers["raster"]
            safe_border = raster <= 48 or 252 <= raster < PAL_LINES
            visible_field = (
                (registers["clock"] - raster * PAL_CYCLES_PER_LINE - registers["raster_cycle"])
                // (PAL_LINES * PAL_CYCLES_PER_LINE)
                + (raster >= 252)
            )
            distinct_scanout = previous_visible_field is None or previous_visible_field < visible_field
            previous_visible_field = visible_field
            report["frontIntegrityChecks"] += 1
            if not (screen_untouched and charset_untouched
                    and d018_before == BUFFERS[front][2]
                    and memory[frame_counter] == (index & 255) and safe_border and distinct_scanout):
                report["frontIntegrityFailure"] = {
                    "index": index, "screenUnchanged": screen_untouched,
                    "charsetUnchanged": charset_untouched, "d018": d018_before,
                    "raster": raster, "frameCounter": memory[frame_counter],
                    "distinctScanout": distinct_scanout}
                raise AssertionError(f"Visible buffers or flip boundary changed while drawing frame {index}")

            if index - 1 in selected:
                picture = output / f"frame-{index - 1}-vice.png"
                monitor.run(f'scrsh "{picture}" 2')
                by_index[index - 1]["screenshot"] = picture.name
                by_index[index - 1]["completedPhysicalScanout"] = True
                pixel_errors = scanout_errors(picture, front_screen, front_charset)
                by_index[index - 1]["physicalPixelErrors"] = pixel_errors
                if pixel_errors:
                    raise AssertionError(f"Physical scanout for frame {index - 1} has {pixel_errors} wrong pixels")
            if index == last + 1:
                break

            repeat_counts = {}
            if args.globe_repeat:
                repeat_counts, witness = verify_repeat_frame(index, response, repeat_trace)
                coverage = report["repeatCoverage"]
                coverage["framesChecked"] += 1
                for key, count in repeat_counts.items():
                    coverage[key] += count
                if witness is not None:
                    report.setdefault("repeatWitness", witness)

            motif_counts = {}
            if trace_hits is not None:
                pairs, singles = trace_hits[proof_hit], trace_hits[motif_single_hit]
                full_groups = 2 * pairs + singles
                expected_groups = globe_full_group_count(index)
                if full_groups != expected_groups:
                    raise AssertionError(f"Generated coverage for frame {index}: {full_groups}/{expected_groups} full groups")
                motif_counts = {"motifPairCalls": pairs, "motifSingleCalls": singles, "fullGroupsCovered": full_groups}
                coverage = report["motifCoverage"]
                coverage["framesChecked"] += 1
                coverage["fullGroups"] += full_groups
                coverage["pairCalls"] += pairs
                coverage["singleCalls"] += singles

            replay_counts = {}
            if args.replay_stats:
                counts = counter_values(memory, replay_addresses)
                replay_counts = {key: (count - previous_counts[key]) & 0xffff
                                 for key, count in counts.items()}
                previous_counts = counts
                if replay_counts["replayHits"] > replay_counts["replayAttempts"]:
                    raise AssertionError(f"More replay hits than attempts in frame {index}")
                for key, count in replay_counts.items():
                    report[key] += count
                report["replayFramesWithHits"] += bool(replay_counts["replayHits"])

            back = 1 - front
            screen, charset = buffer_bytes(memory, BUFFERS[back])
            if zero_patch:
                static_unchanged = charset == initial_fonts[back]
            else:
                static_unchanged = charset[:fixed_size] == expected_font[:fixed_size]
            if not static_unchanged:
                raise AssertionError(f"Static font changed in back buffer for frame {index}")
            monitor.run("step")             # presentFrame begins with STA $D018
            monitor.run("bank io")
            d018_after = monitor.dump(output / "last-d018.bin", 0xd018, 0xd018)[0] & 0xfe
            monitor.run("bank cpu")
            if d018_after != BUFFERS[back][2]:
                raise AssertionError(f"Screen and charset did not switch together for frame {index}")
            report["presentationsChecked"] += 1
            presentation_fields.append(visible_field)
            previous_screen, previous_charset = screen, charset
            front = back
            monitor.run("x")
            if monitor.registers()["pc"] != loop:
                raise AssertionError(f"Animation halted after presenting {shape} frame {index}")
            if index not in selected:
                continue

            monitor.run("bank ram")
            actual_frame = monitor.dump(output / "last-frame.bin", frame_counter, frame_counter)[0]
            monitor.run("bank io")
            colors = monitor.dump(output / "last-colors.bin", 0xd800, 0xdbe7)
            bank = monitor.dump(output / "last-bank.bin", 0xdd00, 0xdd00)[0]
            monitor.run("bank cpu")
            if args.compact_joins:
                matches, glyph_report = compare_compact(index, screen, charset, expected_font,
                                                        code_for_mask, memory[JCOUNT])
            elif args.one_char:
                matches, glyph_report = compare_one_char(index, screen, memory[JCOUNT])
            elif args.crossing_holes:
                matches, glyph_report = compare_crossing_holes(index, screen, tile_to_code, memory[JCOUNT])
            elif exact_corners:
                matches, glyph_report = compare_exact_corners(index, screen, charset, tile_to_code, memory[JCOUNT])
            elif fixed_junction_font:
                matches, glyph_report = compare_zero_patch(expected_screen(index), screen, memory[JCOUNT])
            elif deferred_overflow is not None and not memory[deferred_overflow]:
                matches, glyph_report = compare_deferred_globe(index, screen, charset, memory[JCOUNT])
            else:
                matches, glyph_report = compare_normal(index, frame_screen, tile_to_code,
                                                       screen, charset, expected_font)
            if deferred_overflow is not None:
                glyph_report["deferredOverflow"] = bool(memory[deferred_overflow])
            if args.junction and memory[JCOUNT + 1]:
                raise AssertionError(f"Junction slot pool exhausted in frame {index}")
            mode_ok = (vic[0] & 0x60) == 0 and (vic[5] & 0x10) == 0
            addresses_ok = d018_after == BUFFERS[front][2] and (bank & 3) == 3
            colors_ok = (vic[16] & 15) == 0 and all((color & 15) == 1 for color in colors)
            (output / f"frame-{index}-screen.bin").write_bytes(screen[:1000])
            (output / f"frame-{index}-charset.bin").write_bytes(charset)
            frame = {"index": index, "frameCounter": actual_frame,
                     "screenAddress": BUFFERS[front][0], "charsetAddress": BUFFERS[front][1],
                     "d018Before": d018_before, "d018After": d018_after,
                     "flipRaster": registers["raster"], "flipClock": registers["clock"],
                     "firstVisibleField": visible_field, "frontScreenUnchanged": screen_untouched,
                     "frontCharsetUnchanged": charset_untouched,
                     "staticFontUnchanged": static_unchanged,
                     "normalHiresText": mode_ok, "vicAddressesCorrect": addresses_ok,
                     "colorsCorrect": colors_ok,
                     "litCells": sum(code != 0 for code in screen[:1000]) - glyph_report.get("holeCells", 0),
                     **glyph_report,
                     **replay_counts,
                     **motif_counts,
                     **repeat_counts,
                     "screenSha256": sha(screen[:1000])}
            frame["passed"] = (actual_frame == ((index + 1) & 255) and matches
                               and static_unchanged and mode_ok and addresses_ok and colors_ok
                               and frame["litCells"] > 0)
            report["frames"].append(frame)
            by_index[index] = frame
            if not frame["passed"]:
                raise AssertionError(f"{shape.title()} frame {index} differs from the Python reference")
        intervals = len(presentation_fields) - 1
        if intervals > 0:
            elapsed_fields = presentation_fields[-1] - presentation_fields[0]
            report["presentationIntervals"] = intervals
            report["palFieldCadence"] = dict(sorted(Counter(
                end - start for start, end in zip(presentation_fields, presentation_fields[1:])
            ).items()))
            report["measuredFPS"] = round(
                intervals * PAL_CLOCK / (elapsed_fields * PAL_LINES * PAL_CYCLES_PER_LINE), 3)
        report["animationChanges"] = len({frame["screenSha256"] for frame in report["frames"]}) > 1
        if args.globe_replay and args.all_frames and not report["replayPathReached"]:
            raise AssertionError("No motif was replayed in the full globe sweep")
        if args.globe_motifs and args.all_frames and "motifReuseWitness" not in report:
            raise AssertionError("No two-group kernel was observed at different line lengths")
        if args.globe_repeat and args.all_frames and "repeatWitness" not in report:
            raise AssertionError("No selected kernel repeated in the full globe sweep")
        if args.replay_stats and args.all_frames and report["replayHits"] == 0:
            raise AssertionError("Replay statistics stayed at zero")
        report["doubleBuffered"] = True
        report["passed"] = len(selected) == 1 or report["animationChanges"]
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
        if log is not None:
            log.close()
    (output / "verify.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
