#!/usr/bin/env python3
"""Verify default C64 startup and selected animated cube frames in headless VICE.

Run the unmodified PRG through its normal autostart path. At each border flip,
prove the visible screen and charset stayed unchanged while the back pair was
drawn. Compare presented frames with the independent Python cube and line drawer. The verifier owns and cleans up only its VICE process.
"""
import argparse
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
BUFFERS = ((0x0400, 0x2000, 0x18), (0x2c00, 0x3000, 0xbc))
PAL_LINES = 312
PAL_CYCLES_PER_LINE = 63


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_monitor():
    spec = importlib.util.spec_from_file_location(
        "vice_monitor", HERE.parent / "movieplayer" / "vice_monitor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def symbol(text, name):
    match = re.search(rf"^\.label {re.escape(name)}=\$([0-9a-fA-F]+)$", text, re.M)
    if not match:
        raise ValueError(f"Missing assembly symbol: {name}")
    return int(match[1], 16)


def glyph_rows(pattern):
    rows = bytearray(8)
    for y in range(4):
        for x in range(4):
            if pattern & (1 << (y * 4 + x)):
                rows[2 * y] |= 0xc0 >> (2 * x)
                rows[2 * y + 1] |= 0xc0 >> (2 * x)
    return rows


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/bin/x64sc"))
    parser.add_argument("--build", type=Path, default=BUILD,
                        help="directory containing linedrawer.prg and matching main.sym")
    parser.add_argument("--frames", type=int, nargs="+", default=[0, 1, 2, 3, 16, 64, 196, 197],
                        help="zero-based frames to verify during normal animation (0..255)")
    parser.add_argument("--timeout", type=float, default=30,
                        help="maximum seconds waiting for each VICE monitor response")
    args = parser.parse_args()
    if any(not 0 <= frame <= 255 for frame in args.frames) or not 0 < args.timeout <= 60:
        parser.error("--frames must be 0..255 and --timeout must be greater than 0 and at most 60")

    output = args.build.resolve()
    selected = set(args.frames)
    last = max(selected)
    report = {"passed": False, "defaultLaunch": False, "doubleBuffered": False,
              "frontIntegrityChecks": 0, "presentationsChecked": 0, "frames": []}
    process = connection = log = None
    try:
        import cube_model as reference
        import linedrawer

        tile_to_code, tiles, _ = linedrawer.build_font()
        expected_font = linedrawer.charset_bytes(tiles)
        program = output / "linedrawer.prg"
        report["programSha256"] = sha(program.read_bytes())
        symbols = (output / "main.sym").read_text()
        loop = symbol(symbols, "cubeLoop")
        present = symbol(symbols, "presentFrame")
        halt = symbol(symbols, "halt")
        frame_counter = symbol(symbols, "frmcnt")
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
        monitor.run("x")
        if monitor.registers()["pc"] != loop:
            raise AssertionError("Default launch halted before the first cube frame")
        monitor.run("bank ram")
        initial = monitor.dump(output / "initial-ram.bin", 0, 0x3fff)
        initial_mode, initial_frame = initial[MODE], initial[frame_counter]
        monitor.run("bank cpu")
        report["defaultLaunch"] = initial_mode == 0 and initial_frame == 0
        if not report["defaultLaunch"]:
            raise AssertionError(f"Default launch did not start free animation: MODE={initial_mode}, frame={initial_frame}")
        front = 0
        previous_screen, previous_charset = buffer_bytes(initial, BUFFERS[front])
        previous_visible_field = None
        by_index = {}

        # The extra pre-flip boundary gives the last selected frame a full
        # physical scanout before its screenshot; it is never presented itself.
        for index in range(last + 2):
            monitor.run("x")
            registers = monitor.registers()
            if registers["pc"] != present:
                raise AssertionError(f"Animation halted before presenting cube frame {index}")
            monitor.run("bank ram")
            memory = monitor.dump(output / "last-before-present.bin", 0, 0x3fff)
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

            back = 1 - front
            screen, charset = buffer_bytes(memory, BUFFERS[back])
            static_unchanged = charset[:201 * 8] == expected_font[:201 * 8]
            if not static_unchanged:
                raise AssertionError(f"Static font changed in back buffer for frame {index}")
            monitor.run("step")             # presentFrame begins with STA $D018
            monitor.run("bank io")
            d018_after = monitor.dump(output / "last-d018.bin", 0xd018, 0xd018)[0] & 0xfe
            monitor.run("bank cpu")
            if d018_after != BUFFERS[back][2]:
                raise AssertionError(f"Screen and charset did not switch together for frame {index}")
            report["presentationsChecked"] += 1
            previous_screen, previous_charset = screen, charset
            front = back
            monitor.run("x")
            if monitor.registers()["pc"] != loop:
                raise AssertionError(f"Animation halted after presenting cube frame {index}")
            if index not in selected:
                continue

            monitor.run("bank ram")
            actual_frame = monitor.dump(output / "last-frame.bin", frame_counter, frame_counter)[0]
            monitor.run("bank io")
            colors = monitor.dump(output / "last-colors.bin", 0xd800, 0xdbe7)
            bank = monitor.dump(output / "last-bank.bin", 0xdd00, 0xdd00)[0]
            monitor.run("bank cpu")
            expected, joints = reference.frame_screen(index, tile_to_code)
            wanted_font = bytearray(expected_font)
            for slot, pattern in enumerate(joints):
                wanted_font[(201 + slot) * 8:(202 + slot) * 8] = glyph_rows(pattern)
            different = [cell for cell in range(1000) if screen[cell] != expected[cell]]
            wrong_glyphs = [code for code in sorted(set(expected))
                            if charset[code * 8:code * 8 + 8] != wanted_font[code * 8:code * 8 + 8]]
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
                     "screenBytesEqual": not different, "displayedGlyphsEqual": not wrong_glyphs,
                     "staticFontUnchanged": static_unchanged,
                     "normalHiresText": mode_ok, "vicAddressesCorrect": addresses_ok,
                     "colorsCorrect": colors_ok, "litCells": sum(code != 0 for code in screen[:1000]),
                     "firstDiffCells": [(cell % 40, cell // 40, expected[cell], screen[cell])
                                        for cell in different[:8]],
                     "wrongGlyphs": wrong_glyphs[:8], "jointSlots": len(joints),
                     "screenSha256": sha(screen[:1000])}
            frame["passed"] = (actual_frame == ((index + 1) & 255) and not different and not wrong_glyphs
                               and static_unchanged and mode_ok and addresses_ok and colors_ok
                               and frame["litCells"] > 0)
            report["frames"].append(frame)
            by_index[index] = frame
            if not frame["passed"]:
                raise AssertionError(f"Cube frame {index} differs from the Python reference")
        report["animationChanges"] = len({frame["screenSha256"] for frame in report["frames"]}) > 1
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
