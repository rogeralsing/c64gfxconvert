#!/usr/bin/env python3
"""Prove native24-row glyph mirroring, nearest-glyph LUTs and C64 centering."""

import argparse
import importlib.util
import json
from pathlib import Path
import re
import socket
import statistics
import subprocess

from PIL import Image, ImageChops

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("mirror_raw_span_helpers", HERE / "verify-span-effects-player.py")
span = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(span)
native, sha, stats = span.native, span.sha, span.stats
EVENTS = ("presented", "clear_start", "clear_end", "render_start", "render_end", "commit_start", "commit_end", "field_complete")


def shifted_pixels(screen, font):
    # YSCROLL7 moves the normal character rows down four active pixels.
    # Row24 is blank, so only its first four black lines appear at the bottom.
    return bytes(320 * 4) + native.pixels_from_screen(screen, font)[:320 * 196]


def mirrored_screen(reference, source_pose, horizontal, vertical):
    screen = bytearray(1000)
    for y in range(12):
        for x in range(20):
            c = reference[source_pose * 1000 + y * 40 + x]
            h = horizontal[c]
            screen[y * 40 + x] = c
            screen[y * 40 + 39 - x] = h
            screen[(23 - y) * 40 + x] = vertical[c]
            screen[(23 - y) * 40 + 39 - x] = vertical[h]
    return bytes(screen)


def ideal_pixels(reference, source_pose, font):
    source = Image.frombytes("L", (320, 200), native.pixels_from_screen(reference[source_pose * 1000:(source_pose + 1) * 1000], font))
    tl = source.crop((0, 0, 160, 96))
    top = Image.new("L", (320, 96))
    top.paste(tl, (0, 0))
    top.paste(tl.transpose(Image.Transpose.FLIP_LEFT_RIGHT), (160, 0))
    result = Image.new("L", (320, 200))
    result.paste(top, (0, 4))
    result.paste(top.transpose(Image.Transpose.FLIP_TOP_BOTTOM), (0, 100))
    return result.tobytes()


def lut_proof(font, horizontal, vertical, reference):
    if len(horizontal) != 256 or len(vertical) != 256:
        raise AssertionError("Both glyph mirror lookup tables must contain256 entries")
    glyphs = [font[index * 8:(index + 1) * 8] for index in range(256)]
    reverse = [int(f"{value:08b}"[::-1], 2) for value in range(256)]
    entries = []
    for code, glyph in enumerate(glyphs):
        targets = [bytes(reverse[value] for value in glyph), glyph[::-1]]
        errors = []
        for mapping, target in zip((horizontal, vertical), targets):
            distance = [sum((a ^ b).bit_count() for a, b in zip(target, candidate)) for candidate in glyphs]
            selected = min(range(256), key=lambda index: (distance[index], index))
            if mapping[code] != selected:
                raise AssertionError(f"Glyph{code} does not choose minimum Hamming error and lowest-code tie")
            errors.append(distance[selected])
        entries.append({"sourceCode": code, "horizontalCode": horizontal[code], "verticalCode": vertical[code],
                        "horizontalErrorPixels": errors[0], "verticalErrorPixels": errors[1]})
    poses, weighted = [], [0, 0, 0]
    used = set()
    for source_pose in range(97):
        screen = mirrored_screen(reference, source_pose, horizontal, vertical)
        actual = shifted_pixels(screen, font)
        ideal = ideal_pixels(reference, source_pose, font)
        quadrants = []
        for left, top in ((160, 4), (0, 100), (160, 100)):
            error = sum(actual[y * 320 + x] != ideal[y * 320 + x] for y in range(top, top + 96) for x in range(left, left + 160))
            quadrants.append(error)
        for index, error in enumerate(quadrants):
            weighted[index] += error
        for y in range(12):
            used.update(reference[source_pose * 1000 + y * 40:source_pose * 1000 + y * 40 + 20])
        poses.append({"pose": source_pose, "TRerrorPixels": quadrants[0], "BLerrorPixels": quadrants[1],
                      "BRerrorPixels": quadrants[2], "totalErrorPixels": sum(quadrants)})
    total = sum(weighted)
    return {"pass": True, "method": "Independent bit reversal and glyph-row reversal; exhaustive256-candidate Hamming search, lowest-code tie. Ideal bitmap uses pixel transforms independent of glyph lookup tables.",
            "fontSha256": sha(font), "hSha256": sha(horizontal), "vSha256": sha(vertical), "usedTLGlyphs": len(used),
            "weightedTRerrorPixels": weighted[0], "weightedBLerrorPixels": weighted[1], "weightedBRerrorPixels": weighted[2],
            "weightedTotalErrorPixels": total, "full200PixelErrorFraction": total / (97 * 320 * 200),
            "canvas192PixelErrorFraction": total / (97 * 320 * 192), "meanErrorPixelsPerFrame": total / 97,
            "maximumErrorPixelsPerFrame": max(row["totalErrorPixels"] for row in poses),
            "bottomRightRule": "V[H[sourceCode]], vertical mapping of the actual top-right glyph", "glyphs": entries, "poses": poses}


def symbols(path):
    labels = {name: int(value, 16) for name, value in re.findall(r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", path.read_text())}
    required = set(EVENTS) | {"film_frame", "next_film_frame", "film_serial", "next_serial", "field_counter", "front_screen_hi", "back_screen_hi", "font", "animation", "animation_end"}
    if required - labels.keys():
        raise AssertionError("Missing standalone mirror ABI: " + str(sorted(required - labels.keys())))
    if len({labels[name] for name in EVENTS}) != len(EVENTS):
        raise AssertionError("Mirror lifecycle checkpoints must be distinct")
    return labels


def verify(build, vice, output):
    build, output = build.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((build / "build.json").read_text())
    labels = symbols(build / "main.sym")
    font, rows = (build / "font.bin").read_bytes(), (build / "rows.bin").read_bytes()
    offsets, reference = (build / "frame-offsets16.bin").read_bytes(), (build / "reference.frames").read_bytes()
    horizontal, vertical = (build / "h-lut.bin").read_bytes(), (build / "v-lut.bin").read_bytes()
    span.SpanOracle(rows, offsets, reference)
    if sha(font) != span.LOCKED_FONT or sha(reference) != span.REFERENCE or labels["font"] != 0x4000 or labels["animation"] != 0x5000 or labels["animation_end"] != 0x5000 + len(rows):
        raise AssertionError("Original raw film/font/reference or proven bank-one layout changed")
    metrics = lut_proof(font, horizontal, vertical, reference)
    (output / "independent-lut-proof.json").write_text(json.dumps(metrics, indent=2) + "\n")
    expected_screens = [mirrored_screen(reference, pose, horizontal, vertical) for pose in range(97)]
    expected_pixels = [shifted_pixels(screen, font) for screen in expected_screens]
    regions = []
    for item in manifest["sourceRegions"]:
        data = (build / item["file"]).read_bytes()
        if len(data) != item["end"] - item["start"] or sha(data) != item["sha256"]:
            raise AssertionError("Immutable raw/index/LUT file differs")
        regions.append({**item, "data": data})
    if sum(len(item["data"]) for item in regions if item["file"] in ("h-lut.bin", "v-lut.bin")) != 512:
        raise AssertionError("The two256-byte H/V lookup regions were not both declared")
    program = build / "player.prg"
    program_sha = sha(program.read_bytes())
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    palette = HERE.parent.parent.parent / "palettes/colodore.vpl"
    command = [str(vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100", "+warp", "+autostart-warp", "+confirmonexit",
               "-sounddev", "dummy", "+refreshonbreak", "+binarymonitor", "-initbreak", "reset", "-autostartprgmode", "1", "-autostart", str(program),
               "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", str(palette), "-VICIIsaturation", "1000", "-VICIIcontrast", "1000",
               "-VICIIbrightness", "1000", "-VICIIgamma", "1000", "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    report = {"pass": False, "program_sha256": program_sha, "font_sha256": sha(font), "rows_sha256": sha(rows),
              "h_sha256": sha(horizontal), "v_sha256": sha(vertical), "manifest": manifest, "command": command,
              "method": "Unmodified native PAL VICE, forced refresh disabled. Actual200-line scanouts are matched to the24-row character mirror shifted down4pixels. Independent raw referenceTL, nearest-Hamming LUTs, V[H] bottom-right composition, both black margins and all hidden clears are checked.",
              "events": [], "fields": [], "commits": [], "clears": [], "renders": []}
    process = connection = monitor = None
    screens = [0x4800, 0x4c00]
    buffer_contents = {address: bytes(1024) for address in screens}
    front, back = screens
    serial = 0
    pending = None
    work, stage = None, "startup"
    front_watch = None
    guard_baseline = None
    last_field_counter = 0
    last_field_clock = None
    clear_clock = render_clock = commit_clock = None

    def word(ram, name):
        return int.from_bytes(ram[labels[name]:labels[name] + 2], "little")

    with (output / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            report["owned_pid"] = process.pid
            connection = native.connect(process, port)
            monitor = native.Monitor(connection)
            monitor.run("sidefx off")
            for resource, value in (("MachineVideoStandard", 1), ("Speed", 100), ("InitialWarpMode", 0), ("AutostartWarp", 0), ("RefreshOnBreak", 0)):
                if f"{resource}={value}" not in monitor.run(f'resourceget "{resource}"'):
                    raise AssertionError("Unexpected VICE resource " + resource)
            initial = monitor.checkpoint(labels["presented"])
            monitor.run("x")
            if monitor.registers()["pc"] != labels["presented"]:
                raise AssertionError("Initial mirror presentation not reached")
            monitor.run(f"delete {initial}")
            for event in EVENTS:
                monitor.checkpoint(labels[event])
            span.store_checkpoint(monitor, 0x4000, 0x4800)
            for region in regions:
                span.store_checkpoint(monitor, region["start"], region["end"])

            def read_state():
                nonlocal guard_baseline
                monitor.run("bank ram")
                ram = monitor.dump(output / "last-ram.bin", 0, 65535)
                monitor.run("bank io")
                vic = monitor.dump(output / "last-vic.bin", 0xd000, 0xd03f)
                cia = monitor.dump(output / "last-cia.bin", 0xdd00, 0xdd02)
                colors = monitor.dump(output / "last-colors.bin", 0xd800, 0xdbff)
                monitor.run("bank cpu")
                if ram[0x4000:0x4800] != font:
                    raise AssertionError("Locked font changed")
                for region in regions:
                    if ram[region["start"]:region["end"]] != region["data"]:
                        raise AssertionError("Immutable raw/index/H/V lookup region changed: " + region["file"])
                guard = ram[labels["animation_end"]:0xd000]
                if guard_baseline is None:
                    guard_baseline = guard
                if guard != guard_baseline:
                    raise AssertionError("Write escaped the standalone source/output allocations")
                if registers_now["cpu_port"] != 0x35 or cia[0] & 3 != 2 or cia[2] & 3 != 3:
                    raise AssertionError("Unexpected6510 or VIC bank")
                if vic[0x11] & 0x7f != 0x1f or vic[0x16] & 0x1f != 8 or vic[0x15] or vic[0x18] & 0xfe != (0x20 if front == 0x4800 else 0x30):
                    raise AssertionError("VIC does not select YSCROLL7 and the expected screen/font")
                if vic[0x20] & 15 or vic[0x21] & 15 or any(value & 15 != 1 for value in colors):
                    raise AssertionError("Unexpected shared color RAM/background")
                if ram[labels["front_screen_hi"]] << 8 != front or ram[labels["back_screen_hi"]] << 8 != back or word(ram, "film_serial") != serial or ram[labels["film_frame"]] != span.pose(serial):
                    raise AssertionError("Active display/source metadata changed before commit")
                for address in screens:
                    if address == back and work:
                        continue
                    if ram[address:address + 1024] != buffer_contents[address]:
                        raise AssertionError(f"Character mirror RAM differs at serial{serial},stage{stage}")
                return ram

            first_event = True
            while True:
                if not first_event:
                    monitor.run("x")
                first_event = False
                registers_now = span.registers(monitor)
                event = next((name for name in EVENTS if labels[name] == registers_now["pc"]), None)
                if event is None:
                    raise AssertionError(f"Unexpected front/source/font/LUT write or checkpoint at${registers_now['pc']:04x}")
                stage = event
                report["events"].append({"event": event, "serial": serial, **registers_now})
                if event == "presented":
                    read_state()
                    if front_watch is not None:
                        monitor.run(f"delete {front_watch}")
                    front_watch = span.store_checkpoint(monitor, front, front + 1024)
                elif event == "clear_start":
                    ram = read_state()
                    pending = word(ram, "next_serial")
                    if pending != serial + 1 or ram[labels["next_film_frame"]] != span.pose(pending):
                        raise AssertionError("Standalone movie sequence skipped or repeated startup blank")
                    clear_clock, work = registers_now["clock"], "clear"
                elif event == "clear_end":
                    buffer_contents[back] = bytes(1024)
                    work = None
                    read_state()
                    report["clears"].append({"serial": pending, "wallCycles": registers_now["clock"] - clear_clock, "all1024BytesZero": True})
                elif event == "render_start":
                    read_state()
                    render_clock, work = registers_now["clock"], "render"
                elif event == "render_end":
                    buffer_contents[back] = expected_screens[span.pose(pending)] + bytes(24)
                    work = None
                    read_state()
                    report["renders"].append({"serial": pending, "pose": span.pose(pending), "wallCycles": registers_now["clock"] - render_clock,
                                               "TLandHandVandVHIndicesMatch": True, "row24And24SpareBytesBlank": True})
                elif event == "field_complete":
                    ram = read_state()
                    counter = word(ram, "field_counter")
                    if counter != last_field_counter + 1 or not 256 <= registers_now["raster"] <= 258:
                        raise AssertionError("Missing actual completed mirror field")
                    if last_field_clock is not None and abs(registers_now["clock"] - last_field_clock - native.PAL_FRAME_CYCLES) > 126:
                        raise AssertionError("Mirror field captures are not consecutive")
                    last_field_counter, last_field_clock = counter, registers_now["clock"]
                    picture = output / f"field-{counter:04d}-serial-{serial:03d}-pose-{span.pose(serial):03d}.png"
                    monitor.run(f'scrsh "{picture}" 2')
                    comparison = span.actual_image(picture, expected_pixels[span.pose(serial)])
                    active = Image.open(picture).convert("L").crop((32, 35, 352, 235))
                    if active.crop((0, 0, 320, 4)).getbbox() or active.crop((0, 196, 320, 200)).getbbox():
                        raise AssertionError("Actual C64 top/bottom4-pixel margins are not black")
                    report["fields"].append({"field": counter, "serial": serial, "pose": span.pose(serial), "clock": registers_now["clock"],
                                              "screenshot": picture.name, "comparison": comparison, "bothFourPixelMarginsBlack": True,
                                              "workInProgress": work})
                    if counter % 64 == 0:
                        print(json.dumps({"mirrorActualFieldsVerified": counter, "imagesPresented": serial + 1}), flush=True)
                elif event == "commit_start":
                    read_state()
                    if work or buffer_contents[back] != expected_screens[span.pose(pending)] + bytes(24):
                        raise AssertionError("Mirror presentation attempted an unfinished output")
                    if not (registers_now["raster"] >= 256 or registers_now["raster"] < 50):
                        raise AssertionError("Mirror presentation began during visible scanout")
                    if serial == 288:
                        break
                    commit_clock = registers_now["clock"]
                elif event == "commit_end":
                    serial = pending
                    front, back = back, front
                    read_state()
                    if not (registers_now["raster"] >= 256 or registers_now["raster"] < 50):
                        raise AssertionError("Mirror presentation ended during visible scanout")
                    report["commits"].append({"serial": serial, "pose": span.pose(serial), "field": last_field_counter,
                                               "clock": registers_now["clock"], "publicationWallCycles": registers_now["clock"] - commit_clock})
            if sha(program.read_bytes()) != program_sha:
                raise AssertionError("Mirror program changed during native proof")
            residence = {}
            for row in report["fields"]:
                residence[row["serial"]] = residence.get(row["serial"], 0) + 1
            if sorted(residence) != list(range(289)):
                raise AssertionError("The bounded proof did not capture every image in all three periods")
            intervals = [b["clock"] - a["clock"] for a, b in zip(report["commits"], report["commits"][1:])]
            report.update({"pass": True, "displayedImagesVerified": 289, "uniqueSourceFramesVerified": len(set(row["pose"] for row in report["fields"])),
                           "actualVisibleFieldsVerified": len(report["fields"]), "filmWrapsVerified": 2,
                           "allNativeMirrorsMatchLookupReference": True, "allFourPixelMarginsBlack": True,
                           "allNativeCharacterRows24AndSparesBlank": True, "verticalMirrorCanvasTop": 4, "verticalMirrorCanvasBottom": 195,
                           "verticalAxisPixel": 100, "horizontalAxisPixel": 160,
                           "observedFieldsPerImage": sorted(set(residence.values())), "imageFieldCounts": residence,
                           "meanFps": native.PAL_CLOCK / statistics.mean(intervals) if intervals else None,
                           "presentationCycles": stats(intervals), "clearWallCycles": stats([row["wallCycles"] for row in report["clears"]]),
                           "renderWallCycles": stats([row["wallCycles"] for row in report["renders"]]),
                           "frontWritesDuringWork": 0, "immutableFontRawSourceIndexAndLookupWrites": 0, "forcedRefresh": False,
                           "glyphApproximationIsExpected": True,
                           "approximation": {key: metrics[key] for key in ("weightedTotalErrorPixels", "full200PixelErrorFraction", "meanErrorPixelsPerFrame", "maximumErrorPixelsPerFrame")},
                           "scope": "Standalone original raw-span source with H/V nearest glyph lookup tables. Actual centered24-row mirror,289 images including two real film wraps. No music or other interrupt workload."})
        except BaseException as error:
            report["error"] = repr(error)
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
            if process and process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key not in ("events", "fields", "commits", "renders", "clears", "manifest", "command", "imageFieldCounts")}, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=HERE / "build/three-scene-flagship-star-span-mirror")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    args = parser.parse_args()
    verify(args.build, args.vice, args.output or args.build / "pal-proof")


if __name__ == "__main__":
    main()
