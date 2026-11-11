#!/usr/bin/env python3
"""Prove timed V-only then H-only native mirrors against original source halves."""

import argparse
import importlib.util
import json
from pathlib import Path
import re
import socket
import subprocess

from PIL import Image

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("axis_mirror_policy", HERE / "verify-span-mirror-player.py")
mirror = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mirror)
span, native = mirror.span, mirror.native
sha, stats = span.sha, span.stats
EVENTS = ("presented", "clear_start", "clear_end", "render_start", "render_end", "commit_start", "commit_end", "field_complete")


def axis_screen(reference, source_pose, mode, horizontal, vertical):
    screen = bytearray(1000)
    if mode == 0:
        for y in range(12):
            for x in range(40):
                c = reference[source_pose * 1000 + y * 40 + x]
                screen[y * 40 + x] = c
                screen[(23 - y) * 40 + x] = vertical[c]
    elif mode == 1:
        for y in range(25):
            for x in range(20):
                c = reference[source_pose * 1000 + y * 40 + x]
                screen[y * 40 + x] = c
                screen[y * 40 + 39 - x] = horizontal[c]
    else:
        raise AssertionError("Only standalone V and H modes are valid")
    return bytes(screen)


def axis_pixels(screen, font, mode):
    return mirror.shifted_pixels(screen, font) if mode == 0 else native.pixels_from_screen(screen, font)


def symbols(path):
    labels = {name: int(value, 16) for name, value in re.findall(r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", path.read_text())}
    required = set(EVENTS) | {"mode", "next_mode", "film_frame", "next_film_frame", "film_serial", "next_serial", "field_counter",
                              "mode_started_field", "mode_fields_left", "mode_due", "front_screen_hi", "back_screen_hi", "font", "animation", "animation_end"}
    if required - labels.keys():
        raise AssertionError("Missing one-axis ABI: " + str(sorted(required - labels.keys())))
    if len({labels[name] for name in EVENTS}) != len(EVENTS):
        raise AssertionError("Axis lifecycle checkpoints must be distinct")
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
        raise AssertionError("Original font/raw source/reference or bank-one layout changed")
    accepted = HERE / "three-scene/results/flagship-star-span-mirror-texture"
    for name in ("font.bin", "rows.bin", "frame-offsets16.bin", "h-lut.bin", "v-lut.bin"):
        if (build / name).read_bytes() != (accepted / name).read_bytes():
            raise AssertionError("Axis-only renderer changed an accepted source/lookup asset: " + name)
    full_policy = mirror.lut_proof(font, horizontal, vertical, reference)
    policy = {name: full_policy[name] for name in ("method", "fontSha256", "hSha256", "vSha256", "canonicalBayerTones", "nonTemplateNearestMappingsChecked", "glyphs")}
    policy.update({"pass": True, "acceptedTextureLookupAssetsIdentical": True,
                   "scope": "Corrected canonical Bayer tone identity and all other glyphs actual-flip nearest. No old renderer byte-difference requirement applies to the new one-axis renderer."})
    (output / "independent-lookup-policy.json").write_text(json.dumps(policy, indent=2) + "\n")
    expected_screens = [[axis_screen(reference, source_pose, mode, horizontal, vertical) for source_pose in range(97)] for mode in range(2)]
    expected_pixels = [[axis_pixels(screen, font, mode) for screen in expected_screens[mode]] for mode in range(2)]
    regions = []
    for item in manifest["sourceRegions"]:
        data = (build / item["file"]).read_bytes()
        if len(data) != item["end"] - item["start"] or sha(data) != item["sha256"]:
            raise AssertionError("Immutable source/index/lookup file differs")
        regions.append({**item, "data": data})
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
              "method": "Unmodified native PAL VICE, forced refresh disabled. Every real field matches independent V-only/H-only source references. V top12×40 cells and H left25×20 cells remain original. Mode-specific YSCROLL, full hidden clears, source/font/LUT immutability and501-field mode deadlines are checked.",
              "events": [], "fields": [], "commits": [], "clears": [], "renders": [], "modeStarts": [],
              "coverage": {"originalVTopCellsChecked": 0, "originalHLeftCellsChecked": 0,
                           "VOriginalTopRightCellsDifferingFromQuadrantMirror": 0, "HOriginalBottomLeftCellsDifferingFromQuadrantMirror": 0,
                           "originalHRow24NonzeroCellsChecked": 0}}
    process = connection = monitor = None
    screens = [0x4800, 0x4c00]
    buffer_contents = {address: bytes(1024) for address in screens}
    front, back = screens
    serial = mode = started_field = transitions = 0
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
                raise AssertionError("Initial blank V-only presentation not reached")
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
                        raise AssertionError("Immutable raw/index/LUT source changed: " + region["file"])
                guard = ram[labels["animation_end"]:0xd000]
                if guard_baseline is None:
                    guard_baseline = guard
                if guard != guard_baseline:
                    raise AssertionError("Write escaped the one-axis source/output allocations")
                if registers_now["cpu_port"] != 0x35 or cia[0] & 3 != 2 or cia[2] & 3 != 3:
                    raise AssertionError("Unexpected6510 or VIC bank")
                d011 = 0x1f if mode == 0 else 0x1b
                if vic[0x11] & 0x7f != d011 or vic[0x16] & 0x1f != 8 or vic[0x15] or vic[0x18] & 0xfe != (0x20 if front == 0x4800 else 0x30):
                    raise AssertionError("VIC mode-specific YSCROLL, front or font differs")
                if vic[0x20] & 15 or vic[0x21] & 15 or any(value & 15 != 1 for value in colors):
                    raise AssertionError("Unexpected shared color RAM/background")
                if ram[labels["front_screen_hi"]] << 8 != front or ram[labels["back_screen_hi"]] << 8 != back or word(ram, "film_serial") != serial or ram[labels["film_frame"]] != span.pose(serial) or ram[labels["mode"]] != mode:
                    raise AssertionError("Published display/source metadata changed before atomic commit")
                if word(ram, "mode_started_field") != started_field:
                    raise AssertionError("Visible mode start field differs")
                for address in screens:
                    if address == back and work:
                        continue
                    if ram[address:address + 1024] != buffer_contents[address]:
                        raise AssertionError(f"One-axis output differs at serial{serial},stage{stage}")
                return ram

            def source_half_coverage(ram):
                next_serial, next_mode = pending
                source_pose = span.pose(next_serial)
                source = reference[source_pose * 1000:(source_pose + 1) * 1000]
                output_screen = ram[back:back + 1000]
                quadrants = mirror.mirrored_screen(reference, source_pose, horizontal, vertical)
                if next_mode == 0:
                    if output_screen[:480] != source[:480]:
                        raise AssertionError("V-only mode horizontally transformed the original top half")
                    report["coverage"]["originalVTopCellsChecked"] += 480
                    report["coverage"]["VOriginalTopRightCellsDifferingFromQuadrantMirror"] += sum(output_screen[y * 40 + x] != quadrants[y * 40 + x] for y in range(12) for x in range(20, 40))
                else:
                    for y in range(25):
                        if output_screen[y * 40:y * 40 + 20] != source[y * 40:y * 40 + 20]:
                            raise AssertionError("H-only mode vertically transformed/cropped the original left half")
                    report["coverage"]["originalHLeftCellsChecked"] += 500
                    report["coverage"]["HOriginalBottomLeftCellsDifferingFromQuadrantMirror"] += sum(output_screen[y * 40 + x] != quadrants[y * 40 + x] for y in range(12, 24) for x in range(20))
                    report["coverage"]["originalHRow24NonzeroCellsChecked"] += sum(value != 0 for value in source[960:980])

            first_event = True
            while True:
                if not first_event:
                    monitor.run("x")
                first_event = False
                registers_now = span.registers(monitor)
                event = next((name for name in EVENTS if labels[name] == registers_now["pc"]), None)
                if event is None:
                    raise AssertionError(f"Unexpected source/font/LUT/front write or checkpoint at${registers_now['pc']:04x}")
                stage = event
                report["events"].append({"event": event, "serial": serial, **registers_now})
                if event == "presented":
                    read_state()
                    if not report["modeStarts"]:
                        report["modeStarts"].append({"mode": 0, "field": 0, "serial": 0, "clock": registers_now["clock"]})
                    if front_watch is not None:
                        monitor.run(f"delete {front_watch}")
                    front_watch = span.store_checkpoint(monitor, front, front + 1024)
                elif event == "clear_start":
                    ram = read_state()
                    pending = (word(ram, "next_serial"), ram[labels["next_mode"]])
                    if pending[0] != serial + 1 or pending[1] not in (mode, 1 - mode) or ram[labels["next_film_frame"]] != span.pose(pending[0]):
                        raise AssertionError("One-axis source clock/mode sequence differs")
                    clear_clock, work = registers_now["clock"], "clear"
                elif event == "clear_end":
                    buffer_contents[back] = bytes(1024)
                    work = None
                    read_state()
                    report["clears"].append({"serial": pending[0], "wallCycles": registers_now["clock"] - clear_clock, "all1024BytesZero": True})
                elif event == "render_start":
                    read_state()
                    render_clock, work = registers_now["clock"], "render"
                elif event == "render_end":
                    buffer_contents[back] = expected_screens[pending[1]][span.pose(pending[0])] + bytes(24)
                    work = None
                    ram = read_state()
                    source_half_coverage(ram)
                    report["renders"].append({"serial": pending[0], "mode": pending[1], "wallCycles": registers_now["clock"] - render_clock,
                                               "onlySelectedAxisMirrored": True, "originalSourceHalfUnchanged": True})
                elif event == "field_complete":
                    ram = read_state()
                    counter = word(ram, "field_counter")
                    if counter != last_field_counter + 1 or not 256 <= registers_now["raster"] <= 258:
                        raise AssertionError("Missing actual completed one-axis field")
                    if last_field_clock is not None and abs(registers_now["clock"] - last_field_clock - native.PAL_FRAME_CYCLES) > 126:
                        raise AssertionError("One-axis field captures are not consecutive")
                    last_field_counter, last_field_clock = counter, registers_now["clock"]
                    elapsed = counter - started_field
                    if elapsed > 501 or word(ram, "mode_fields_left") != max(0, 501 - elapsed) or bool(ram[labels["mode_due"]]) != (elapsed >= 501):
                        raise AssertionError("One-axis mode missed its actual501-field deadline")
                    picture = output / f"field-{counter:04d}-mode-{mode}-serial-{serial:04d}.png"
                    monitor.run(f'scrsh "{picture}" 2')
                    comparison = span.actual_image(picture, expected_pixels[mode][span.pose(serial)])
                    if mode == 0:
                        active = Image.open(picture).convert("L").crop((32, 35, 352, 235))
                        if active.crop((0, 0, 320, 4)).getbbox() or active.crop((0, 196, 320, 200)).getbbox():
                            raise AssertionError("V-only centered canvas lost its four-pixel margins")
                    report["fields"].append({"field": counter, "mode": mode, "serial": serial, "pose": span.pose(serial), "clock": registers_now["clock"],
                                              "modeElapsedFields": elapsed, "yScroll": 7 if mode == 0 else 3,
                                              "pixelOffsetY": 4 if mode == 0 else 0, "sourceRows": 12 if mode == 0 else 25,
                                              "screenshot": picture.name, "comparison": comparison, "workInProgress": work})
                    if counter % 100 == 0:
                        print(json.dumps({"axisActualFieldsVerified": counter, "seconds": counter * native.PAL_FRAME_CYCLES / native.PAL_CLOCK,
                                          "imagesPresented": serial + 1, "mode": mode}), flush=True)
                    if transitions >= 2 and mode == 0:
                        break
                    if counter > 1100:
                        raise AssertionError("Timed V→H→V sequence did not repeat")
                elif event == "commit_start":
                    ram = read_state()
                    if work or buffer_contents[back] != expected_screens[pending[1]][span.pose(pending[0])] + bytes(24):
                        raise AssertionError("One-axis presentation attempted an unfinished hidden frame")
                    if not (registers_now["raster"] >= 256 or registers_now["raster"] < 50):
                        raise AssertionError("Mode/YSCROLL presentation began during visible scanout")
                    if pending[1] != mode and (not ram[labels["mode_due"]] or word(ram, "field_counter") - started_field != 501):
                        raise AssertionError("Mode/YSCROLL switch missed its exact501-field boundary")
                    commit_clock = registers_now["clock"]
                elif event == "commit_end":
                    old_mode = mode
                    serial, mode = pending
                    front, back = back, front
                    if mode != old_mode:
                        started_field = last_field_counter
                        transitions += 1
                    read_state()
                    if not (registers_now["raster"] >= 256 or registers_now["raster"] < 50):
                        raise AssertionError("Mode/YSCROLL presentation ended during visible scanout")
                    if mode != old_mode:
                        report["modeStarts"].append({"mode": mode, "field": started_field, "serial": serial, "clock": registers_now["clock"]})
                    report["commits"].append({"serial": serial, "mode": mode, "field": last_field_counter, "clock": registers_now["clock"],
                                               "publicationWallCycles": registers_now["clock"] - commit_clock})
            if sha(program.read_bytes()) != program_sha:
                raise AssertionError("One-axis program changed during proof")
            durations = [b["field"] - a["field"] for a, b in zip(report["modeStarts"], report["modeStarts"][1:])]
            if durations != [501, 501] or [row["mode"] for row in report["modeStarts"]] != [0, 1, 0]:
                raise AssertionError("Visible sequence was not V501→H501→V repeat")
            if not report["coverage"]["VOriginalTopRightCellsDifferingFromQuadrantMirror"] or not report["coverage"]["HOriginalBottomLeftCellsDifferingFromQuadrantMirror"]:
                raise AssertionError("Corpus did not distinguish one-axis output from simultaneous quadrant mirroring")
            residence = {}
            for row in report["fields"]:
                residence[row["serial"]] = residence.get(row["serial"], 0) + 1
            report.update({"pass": True, "actualVisibleFieldsVerified": len(report["fields"]), "imagesPresentedIncludingRepeat": serial + 1,
                           "visibleModeFields": durations, "visibleModeSeconds": [value * native.PAL_FRAME_CYCLES / native.PAL_CLOCK for value in durations],
                           "cycleFields": 1002, "cycleSeconds": 1002 * native.PAL_FRAME_CYCLES / native.PAL_CLOCK,
                           "repeatBoundaryActualScanoutVerified": True, "allActualOneAxisScanoutsMatch": True,
                           "originalVTopFullWidthUnchanged": True, "originalHLeftAll25RowsUnchanged": True,
                           "Vgeometry": {"sourceRows": 12, "outputCharacterRows": 24, "yScroll": 7, "pixelOffsetY": 4, "blackMargins": [4, 4]},
                           "Hgeometry": {"sourceRows": 25, "outputCharacterRows": 25, "yScroll": 3, "pixelOffsetY": 0, "fullHeightPixels": 200},
                           "frontWritesDuringWork": 0, "immutableFontRawSourceIndexAndLookupWrites": 0, "forcedRefresh": False,
                           "imageFieldResidenceHistogram": {str(value): sum(count == value for count in residence.values()) for value in sorted(set(residence.values()))},
                           "maximumHeldVisibleFields": max(residence.values()), "clearWallCycles": stats([row["wallCycles"] for row in report["clears"]]),
                           "renderWallCycles": stats([row["wallCycles"] for row in report["renders"]]),
                           "scope": "One actual timed V-only/H-only cycle plus first repeated-V scanout. Original raw movie/font and corrected H/V tables unchanged. Two output buffers; no simultaneous-axis quadrant rendering, music or other interrupt workload."})
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
    print(json.dumps({key: value for key, value in report.items() if key not in ("events", "fields", "commits", "renders", "clears", "modeStarts", "manifest", "command")}, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=HERE / "build/three-scene-flagship-star-span-axis")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    args = parser.parse_args()
    verify(args.build, args.vice, args.output or args.build / "pal-proof")


if __name__ == "__main__":
    main()
