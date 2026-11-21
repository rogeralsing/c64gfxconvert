#!/usr/bin/env python3
"""Verify one full message cycle of the native line scroller in PAL VICE."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory

from motion import LEFT_LIMIT, SCROLL_STEP, SPACING, START_X, segments, state_at

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "megaplot"))
from verify_megaplot import (BUFFERS, FIRST_PATCH, PAL_CLOCK, PAL_CYCLES_PER_LINE, PAL_LINES,
                             PATCH_SLOTS, buffer_bytes, capture_pixels, displayed_pixels,
                             pixel_errors, reference_pixels, symbol, vice_monitor)


def raster_strokes(strokes):
    pixels = reference_pixels(())
    for x0, y0, x1, y1 in strokes:
        pixels = reference_pixels(((x0, y0), (x1, y1)), pixels)
    return pixels


def sampled_frames(strokes, wrap):
    selected = {i * wrap // 15 for i in range(16)} | {wrap + 10}
    for edge in (0, 159):
        first = next((i for i, lines in enumerate(strokes)
                      if any(a == edge or c == edge for a, _, c, _ in lines)), None)
        if first is not None:
            selected.add(first)
    return selected


def scroll_state(memory, addresses):
    x = memory[addresses["scFirstLo"]] + 256 * memory[addresses["scFirstHi"]]
    return (x - 65536 if x >= 32768 else x), memory[addresses["scFirstGlyph"]]


def check_color_and_bank(monitor, scratch):
    monitor.run("bank io")
    bank = monitor.dump(scratch / "bank.bin", 0xdd00, 0xdd00)[0]
    colors = monitor.dump(scratch / "color.bin", 0xd800, 0xdbe7)
    monitor.run("bank ram")
    if bank & 3 != 3 or any(color & 15 != 1 for color in colors):
        raise AssertionError("Expected VIC bank 0 and white character ink")


def check_scroller(monitor, output, scratch, labels, message, report):
    length = len(message) - 1
    wrap = (START_X - LEFT_LIMIT + (length - 1) * SPACING) // SCROLL_STEP + 1
    last = wrap + 10
    strokes = [segments(frame, message) for frame in range(last + 2)]
    selected = sampled_frames(strokes, wrap)
    fixed_font = (output / "charset.bin").read_bytes()[:FIRST_PATCH * 8]

    boot = monitor.checkpoint(labels["waveLoop"])
    monitor.checkpoint(labels["presentFrame"])
    monitor.run("x")
    if monitor.registers()["pc"] != labels["waveLoop"]:
        raise AssertionError("Default launch missed the scroll loop")
    monitor.run(f"delete {boot}")
    last_byte = max(0x3fff, *[labels[name] for name in ("scFirstLo", "scFirstHi", "scFirstGlyph",
                                                       "frameIndex", "JCOUNT", "jointOverflow")])
    monitor.run("bank ram")
    initial = monitor.dump(scratch / "memory.bin", 0, last_byte)
    if initial[labels["frameIndex"]] != 0 or scroll_state(initial, labels) != state_at(0, length):
        raise AssertionError("Incorrect scroll state at startup")
    check_color_and_bank(monitor, scratch)
    screen_tails = [buffer_bytes(initial, pair)[0][1000:] for pair in BUFFERS]
    front = 0
    previous_buffer = buffer_bytes(initial, BUFFERS[front])
    fields = []
    seen_glyphs = {0}
    edge_frames = {0: 0, 159: 0}
    sample = None
    report["defaultLaunch"] = True

    # The next flip follows the complete scanout of the previous picture.
    for frame in range(last + 2):
        monitor.run("x")
        registers = monitor.registers()
        raster = registers["raster"]
        if registers["pc"] != labels["presentFrame"] or 49 <= raster < 252:
            raise AssertionError(f"Frame {frame} missed its border flip at raster {raster}")
        field = ((registers["clock"] - raster * PAL_CYCLES_PER_LINE - registers["raster_cycle"])
                 // (PAL_LINES * PAL_CYCLES_PER_LINE) + (raster >= 252))
        if fields and field <= fields[-1]:
            raise AssertionError(f"Frame {frame} interrupted the previous PAL scanout")
        fields.append(field)

        memory = monitor.dump(scratch / "memory.bin", 0, last_byte)
        state = scroll_state(memory, labels)
        if memory[labels["frameIndex"]] != frame % 256 or state != state_at(frame + 1, length):
            raise AssertionError(f"Frame {frame} next scroll state {state} differs from the model")
        if state[1] == 0 and len(seen_glyphs) == length and "messageWrapFrame" not in report:
            if length > 1 or frame + 1 == wrap:
                report["messageWrapFrame"] = frame + 1
        seen_glyphs.add(state[1])

        monitor.run("bank io")
        vic = monitor.dump(scratch / "vic.bin", 0xd011, 0xd021)
        monitor.run("bank ram")
        if vic[7] & 0xfe != BUFFERS[front][2] or vic[0] & 0x60 or vic[5] & 0x10 or vic[16] & 15:
            raise AssertionError(f"Frame {frame} changed the front VIC configuration")
        if buffer_bytes(memory, BUFFERS[front]) != previous_buffer:
            raise AssertionError(f"Frame {frame} changed the displayed screen or charset")
        report["frontIntegrityChecks"] += 1

        if sample is not None:
            physical = capture_pixels(monitor, output / sample["screenshot"])
            errors = pixel_errors(displayed_pixels(*previous_buffer), physical)
            sample["scanoutVsRamErrors"] = errors
            sample["palFields"] = fields[-1] - fields[-2]
            report["scanoutVsRamErrors"] += errors

        back = 1 - front
        screen, charset = buffer_bytes(memory, BUFFERS[back])
        if screen[1000:] != screen_tails[back] or charset[:len(fixed_font)] != fixed_font:
            raise AssertionError(f"Frame {frame} overwrote the screen guard or static font")
        allocated, overflow = memory[labels["JCOUNT"]], memory[labels["jointOverflow"]]
        if allocated > PATCH_SLOTS or any(code >= FIRST_PATCH + allocated for code in screen[:1000]):
            raise AssertionError(f"Frame {frame} used an unallocated patch glyph")
        if frame == last + 1:
            break
        report["peakAllocatedPatches"] = max(report["peakAllocatedPatches"], allocated)
        if overflow:
            report["overflowFrames"].append(frame)
            report["overflowAttempts"] += overflow

        actual = displayed_pixels(screen, charset)
        expected = raster_strokes(strokes[frame])
        errors = pixel_errors(expected, actual)
        report["characterPixelErrors"] += errors
        if errors and not overflow:
            report["unexplainedErrorFrames"].append(frame)
        if any(bits & 0xc0 for bits in actual[0::40]):
            edge_frames[0] += 1
        if any(bits & 0x03 for bits in actual[39::40]):
            edge_frames[159] += 1
        sample = None
        if frame in selected:
            sample = {"frame": frame, "strokes": len(strokes[frame]), "allocatedPatches": allocated,
                      "characterPixelErrors": errors, "screenshot": f"frame-{frame}-vice.png"}
            report["samples"].append(sample)
        previous_buffer = screen, charset
        front = back

    check_color_and_bank(monitor, scratch)
    if report.get("messageWrapFrame") != wrap or seen_glyphs != set(range(length)):
        raise AssertionError("Did not traverse and wrap the full message")
    if not all(edge_frames.values()):
        raise AssertionError("Expected the scroller to reach both screen edges")
    intervals = [b - a for a, b in zip(fields, fields[1:])]
    pal_fps = PAL_CLOCK / (PAL_LINES * PAL_CYCLES_PER_LINE)
    report.update(presentationsChecked=len(intervals), leftEdgeFrames=edge_frames[0], rightEdgeFrames=edge_frames[159],
                  measuredFPS=round(pal_fps * len(intervals) / sum(intervals), 3),
                  minimumFrameFPS=round(pal_fps / max(intervals), 3),
                  palFieldCadence=dict(sorted(Counter(intervals).items())), doubleBuffered=True)


def verify(vice, output, report):
    program = output / "line-scroller.prg"
    manifest = json.loads((output / "scroller.json").read_text())
    report["programSha256"] = hashlib.sha256(program.read_bytes()).hexdigest()
    report["text"] = manifest["text"]
    if report["programSha256"] != manifest["programSha256"]:
        raise ValueError("Program differs from its build manifest")
    message = (output / "letter-message.bin").read_bytes()
    if len(message) < 2 or len(message) != manifest["messageLength"] + 1 or message[-1] != 255 or max(message[:-1]) > 26:
        raise ValueError("Message asset differs from its build manifest")
    symbols = (output / "main.sym").read_text()
    names = ("waveLoop", "presentFrame", "frameIndex", "scFirstLo", "scFirstHi", "scFirstGlyph",
             "JCOUNT", "jointOverflow")
    labels = {name: symbol(symbols, name) for name in names}
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    argv = [str(vice), "-default", "+saveres", "-minimized", "-pal", "-warp", "+autostart-warp",
            "+confirmonexit", "-sounddev", "dummy", "+refreshonbreak", "-initbreak", "reset",
            "-autostartprgmode", "1", "-autostart", str(program), "-remotemonitor", "-remotemonitoraddress",
            f"ip4://127.0.0.1:{port}"]
    with TemporaryDirectory(dir=output) as scratch, (output / "vice.log").open("w") as log:
        process = subprocess.Popen(argv, cwd=output, stdout=log, stderr=log)
        try:
            with vice_monitor.connect(process, port) as connection:
                check_scroller(vice_monitor.Monitor(connection), output, Path(scratch), labels, message, report)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/bin/x64sc"))
    parser.add_argument("--build", type=Path, default=HERE / "build")
    args = parser.parse_args()
    output = args.build.resolve()
    if not output.is_dir():
        parser.error(f"Build directory does not exist: {output}")
    report = {"passed": False, "frontIntegrityChecks": 0, "characterPixelErrors": 0,
              "scanoutVsRamErrors": 0, "unexplainedErrorFrames": [], "peakAllocatedPatches": 0,
              "overflowFrames": [], "overflowAttempts": 0, "samples": []}
    try:
        verify(args.vice, output, report)
        report["passed"] = not (report["characterPixelErrors"] or report["scanoutVsRamErrors"]
                                or report["overflowFrames"])
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    (output / "verify.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "samples"}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
