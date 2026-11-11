#!/usr/bin/env python3
"""Native PAL proof of the new 10-second character zoom and normal handoff.

Authoring gate: the independent original movie + learned LUT defines the visible
contract. Wrong quadrant order, crop clipping, front writes, YSCROLL or stale
latched offsets fail at actual native scanout. Existing suite proof cannot cover
the new zoom or keyboard-adjusted crop. No production test switch is required;
monitor pokes only the same requested crop variables used by the real keyboard.
"""

import argparse
import importlib.util
import json
from pathlib import Path
import re
import socket
import subprocess

from PIL import Image

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("suite_axis_oracle", HERE / "verify-span-axis-player.py")
axis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(axis)
mirror, span, native = axis.mirror, axis.span, axis.native
sha, stats = span.sha, span.stats
NAMES = ("normal", "wave", "checkerboard", "V only", "H only", "both quadrants", "character zoom")
LEARNED_LUT = "37efc20a89731ff3a6b745bfb5e4083947649774b2fe63b56f0c2a4340b2dc21"
EVENTS = ("presented", "cache_start", "cache_end", "clear_start", "clear_end", "render_start", "render_end", "commit_start", "commit_end", "field_complete", "zoom_render_start")



def zoom_screen(reference, serial, lookup, x, y):
    if not (0 <= x <= 20 and 0 <= y <= 13):
        raise AssertionError("Zoom crop is outside the full40x25 source")
    source = reference[span.pose(serial) * 1000:(span.pose(serial) + 1) * 1000]
    output = bytearray(1000)
    for row in range(12):
        for column in range(20):
            code = source[(y + row) * 40 + x + column]
            quad = lookup[code * 4:code * 4 + 4]
            position = row * 80 + column * 2
            output[position:position + 2] = quad[:2]
            output[position + 40:position + 42] = quad[2:]
    return bytes(output)


def suite_screen(reference, ages, serial, mode, horizontal, vertical):
    if mode <= 2:
        return span.composite(reference, ages, serial, mode)
    if mode in (3, 4):
        return axis.axis_screen(reference, span.pose(serial), mode - 3, horizontal, vertical)
    if mode == 5:
        return mirror.mirrored_screen(reference, span.pose(serial), horizontal, vertical)
    raise AssertionError("Unknown suite mode")


def suite_pixels(screen, font, mode):
    return mirror.shifted_pixels(screen, font) if mode in (3, 5, 6) else native.pixels_from_screen(screen, font)


def symbols(path):
    labels = {name: int(value, 16) for name, value in re.findall(r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", path.read_text())}
    required = set(EVENTS) | {"mode", "next_mode", "film_frame", "next_film_frame", "film_serial", "next_serial", "phase", "next_phase",
                              "field_counter", "mode_started_field", "mode_fields_left", "mode_due", "front_screen_hi", "back_screen_hi",
                              "font", "animation", "animation_end", "wave_ages", "cache_table_count", "cache_frame_ids", "row_cache", "zoom_x", "zoom_y", "latched_zoom_x", "latched_zoom_y",
                              "active_zoom_x", "active_zoom_y", "zoom_tl_lut", "zoom_tr_lut", "zoom_bl_lut", "zoom_br_lut"}
    if required - labels.keys():
        raise AssertionError("Missing unified suite ABI: " + str(sorted(required - labels.keys())))
    if len({labels[name] for name in EVENTS}) != len(EVENTS):
        raise AssertionError("Suite lifecycle checkpoints must be distinct")
    return labels


def verify(build, vice, output):
    build, output = build.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((build / "build.json").read_text())
    labels = symbols(build / "main.sym")
    font, rows = (build / "font.bin").read_bytes(), (build / "rows.bin").read_bytes()
    offsets, reference = (build / "frame-offsets16.bin").read_bytes(), (build / "reference.frames").read_bytes()
    horizontal, vertical = (build / "h-lut.bin").read_bytes(), (build / "v-lut.bin").read_bytes()
    oracle = span.SpanOracle(rows, offsets, reference)
    lookup = (build / "learned.lut").read_bytes()
    study = HERE / "three-scene/results/char-zoom-study"
    if sha(lookup) != LEARNED_LUT or lookup != (study / "learned.lut").read_bytes():
        raise AssertionError("Zoom is not using the approved learned lookup")
    if (study / "source.chars").read_bytes() != reference[1000:]:
        raise AssertionError("Empirical zoom study source differs from original raw movie")
    for quadrant, name in enumerate(("tl", "tr", "bl", "br")):
        if (build / ("zoom-" + name + ".bin")).read_bytes() != lookup[quadrant::4]:
            raise AssertionError("Deinterleaved runtime zoom LUT differs from empirical mapping")
    accepted = HERE / "three-scene/results/flagship-star-span-mirror-texture"
    for name in ("font.bin", "rows.bin", "frame-offsets16.bin", "h-lut.bin", "v-lut.bin"):
        if (build / name).read_bytes() != (accepted / name).read_bytes():
            raise AssertionError("Unified player changed an accepted source/lookup asset: " + name)
    if sha(font) != span.LOCKED_FONT or sha(reference) != span.REFERENCE or labels["font"] != 0x4000 or labels["animation"] != 0x5000 or labels["animation_end"] != 0x5000 + len(rows):
        raise AssertionError("Original source/font or bank-one layout changed")
    full_policy = mirror.lut_proof(font, horizontal, vertical, reference)
    policy = {name: full_policy[name] for name in ("method", "fontSha256", "hSha256", "vSha256", "canonicalBayerTones", "nonTemplateNearestMappingsChecked", "glyphs")}
    policy.update({"pass": True, "acceptedCorrectedLookupAssetsIdentical": True})
    (output / "independent-lookup-policy.json").write_text(json.dumps(policy, indent=2) + "\n")
    regions = []
    for item in manifest["sourceRegions"]:
        data = (build / item["file"]).read_bytes()
        if len(data) != item["end"] - item["start"] or sha(data) != item["sha256"]:
            raise AssertionError("Immutable source region file/hash differs")
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
    report = {"pass": False, "program_sha256": program_sha, "font_sha256": sha(font), "rows_sha256": sha(rows), "zoom_lut_sha256": sha(lookup),
              "h_sha256": sha(horizontal), "v_sha256": sha(vertical), "manifest": manifest, "command": command,
              "method": "Unmodified native PAL VICE, forced refresh disabled. Every actual field of initial501-field zoom plus3normal images is compared to original raw frames and independent learned-LUT expansion. At least96default-crop poses and4corner offset scanouts are required. Existing native six-mode suite proof is reused, not rerun.",
              "events": [], "fields": [], "commits": [], "caches": [], "clears": [], "renders": [], "modeStarts": [],
              "coverage": {"cacheRowPointersChecked": 0, "originalVTopCellsChecked": 0, "originalHLeftCellsChecked": 0,
                           "originalBothTLCellsChecked": 0, "originalHRow24NonzeroCellsChecked": 0,
                           "defaultZoomPoses": [], "cornerScanouts": [], "requestedCropPokes": []}}
    process = connection = monitor = None
    screens = [0x4800, 0x4c00]
    contents = {address: bytes(1024) for address in screens}
    front, back = screens
    serial = started_field = transitions = 0
    mode = 6
    active_crop = (10, 6)
    pending_crop = active_crop
    requested_crop = active_crop
    corner_requests = [(0, 0), (20, 0), (0, 13), (20, 13), (10, 6)]
    corner_request_index = 0
    default_poses, corner_scanouts, normal_images = set(), set(), set()
    ages = active_pixels = None
    pending = None
    work, stage = None, "startup"
    front_watch = None
    guard_baseline = None
    last_field_counter = 0
    last_field_clock = None
    clear_clock = cache_clock = render_clock = commit_clock = None

    def word(ram, name):
        return int.from_bytes(ram[labels[name]:labels[name] + 2], "little")

    def expected(next_serial, next_mode, crop=None):
        if next_mode == 6:
            return zoom_screen(reference, next_serial, lookup, *(crop or pending_crop))
        return suite_screen(reference, ages, next_serial, next_mode, horizontal, vertical)

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
                raise AssertionError("Initial blank normal presentation not reached")
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
                        raise AssertionError("Immutable raw/index/LUT region changed: " + region["file"])
                guard = ram[labels["animation_end"]:0xd000]
                if guard_baseline is None:
                    guard_baseline = guard
                if guard != guard_baseline:
                    raise AssertionError("Write escaped suite source/output allocations")
                if registers_now["cpu_port"] != 0x35 or cia[0] & 3 != 2 or cia[2] & 3 != 3:
                    raise AssertionError("Unexpected6510 or VIC bank")
                d011 = 0x1f if mode in (3, 5, 6) else 0x1b
                if vic[0x11] & 0x7f != d011 or vic[0x16] & 0x1f != 8 or vic[0x15] or vic[0x18] & 0xfe != (0x20 if front == 0x4800 else 0x30):
                    raise AssertionError("VIC mode-specific geometry/front/font differs")
                if vic[0x20] & 15 or vic[0x21] & 15 or any(value & 15 != 1 for value in colors):
                    raise AssertionError("Unexpected display color")
                if ram[labels["front_screen_hi"]] << 8 != front or ram[labels["back_screen_hi"]] << 8 != back or word(ram, "film_serial") != serial or ram[labels["film_frame"]] != span.pose(serial) or ram[labels["mode"]] != mode or ram[labels["phase"]] != serial % 96:
                    raise AssertionError("Published source/mode metadata changed before commit")
                if mode == 6 and (ram[labels["active_zoom_x"]], ram[labels["active_zoom_y"]]) != active_crop:
                    raise AssertionError("Published zoom crop changed before commit")
                for index, name in enumerate(("tl", "tr", "bl", "br")):
                    address = labels["zoom_" + name + "_lut"]
                    if ram[address:address + 256] != lookup[index::4]:
                        raise AssertionError("Runtime zoom LUT page changed")
                if word(ram, "mode_started_field") != started_field:
                    raise AssertionError("Visible mode start field differs")
                if ages is not None and ram[labels["wave_ages"]:labels["wave_ages"] + 2400] != ages:
                    raise AssertionError("Wave age table changed")
                for address in screens:
                    if address == back and work:
                        continue
                    if ram[address:address + 1024] != contents[address]:
                        raise AssertionError(f"Suite character output differs at serial{serial},stage{stage}")
                return ram

            def check_pending(ram):
                state = (word(ram, "next_serial"), ram[labels["next_mode"]])
                if state[0] != serial + 1 or state[1] not in (mode, (mode + 1) % 7) or ram[labels["next_film_frame"]] != span.pose(state[0]) or ram[labels["next_phase"]] != state[0] % 96:
                    raise AssertionError("Continuous source clock or seven-mode sequence differs")
                return state

            def check_cache(ram):
                if pending[1] > 2:
                    return
                count = ram[labels["cache_table_count"]]
                if count not in (1, 2, 10) or count * 50 > 500:
                    raise AssertionError("Suite row-pointer cache exceeds500 bytes")
                cached = set()
                for slot in range(count):
                    source_pose = ram[labels["cache_frame_ids"] + slot]
                    if source_pose > 96:
                        raise AssertionError("Cache source pose exceeds raw movie")
                    cached.add(source_pose)
                    for row in range(25):
                        address = labels["row_cache"] + slot * 50 + row * 2
                        pointer = int.from_bytes(ram[address:address + 2], "little")
                        if pointer != 0x5000 + oracle.pointers[source_pose][row]:
                            raise AssertionError("Shared cache selected a wrong raw source/header after mode transition")
                        report["coverage"]["cacheRowPointersChecked"] += 1
                needed = {span.pose(pending[0])}
                if pending[1] == 1:
                    needed = {span.pose(max(0, pending[0] - ages[row * 96 + pending[0] % 96])) for row in range(25)}
                elif pending[1] == 2:
                    needed.add(span.pose(max(0, pending[0] - 48)))
                if not needed.issubset(cached):
                    raise AssertionError("Shared cache omits a selected source frame")

            def check_source_halves(ram):
                next_serial, next_mode = pending
                source = reference[span.pose(next_serial) * 1000:(span.pose(next_serial) + 1) * 1000]
                screen = ram[back:back + 1000]
                if next_mode == 3:
                    if screen[:480] != source[:480]:
                        raise AssertionError("V-only mode altered original full-width top half")
                    report["coverage"]["originalVTopCellsChecked"] += 480
                elif next_mode == 4:
                    for y in range(25):
                        if screen[y * 40:y * 40 + 20] != source[y * 40:y * 40 + 20]:
                            raise AssertionError("H-only mode altered/cropped original25-row left half")
                    report["coverage"]["originalHLeftCellsChecked"] += 500
                    report["coverage"]["originalHRow24NonzeroCellsChecked"] += sum(value != 0 for value in source[960:980])
                elif next_mode == 5:
                    for y in range(12):
                        if screen[y * 40:y * 40 + 20] != source[y * 40:y * 40 + 20]:
                            raise AssertionError("Both-quadrant mode altered original TL source")
                    report["coverage"]["originalBothTLCellsChecked"] += 240

            first_event = True
            while True:
                if not first_event:
                    monitor.run("x")
                first_event = False
                registers_now = span.registers(monitor)
                event = next((name for name in EVENTS if labels[name] == registers_now["pc"]), None)
                if event is None:
                    raise AssertionError(f"Unexpected immutable/front write or native checkpoint at${registers_now['pc']:04x}")
                stage = event
                report["events"].append({"event": event, "serial": serial, **registers_now})
                if event == "presented":
                    ram = read_state()
                    if ages is None:
                        ages = ram[labels["wave_ages"]:labels["wave_ages"] + 2400]
                        span.validate_ages(ages)
                        active_pixels = suite_pixels(expected(0, 6, active_crop), font, 6)
                        report["modeStarts"].append({"mode": 6, "field": 0, "serial": 0, "clock": registers_now["clock"]})
                    if front_watch is not None:
                        monitor.run(f"delete {front_watch}")
                    front_watch = span.store_checkpoint(monitor, front, front + 1024)
                    if mode == 6 and len(default_poses) >= 96 and corner_request_index < len(corner_requests):
                        requested = corner_requests[corner_request_index]
                        requested_crop = requested
                        for name, value in zip(("zoom_x", "zoom_y"), requested):
                            monitor.run(f"> ${labels[name]:04x} ${value:02x}")
                        report["coverage"]["requestedCropPokes"].append({"serial": serial, "x": requested[0], "y": requested[1]})
                        corner_request_index += 1
                elif event in ("cache_start", "clear_start"):
                    ram = read_state()
                    pending = check_pending(ram)
                    if event == "cache_start":
                        cache_clock = registers_now["clock"]
                    else:
                        clear_clock, work = registers_now["clock"], "clear"
                elif event == "cache_end":
                    ram = read_state()
                    check_cache(ram)
                    report["caches"].append({"serial": pending[0], "mode": pending[1], "wallCycles": registers_now["clock"] - cache_clock,
                                              "allNeededRawPointersMatch": True})
                elif event == "clear_end":
                    contents[back] = bytes(1024)
                    work = None
                    read_state()
                    report["clears"].append({"serial": pending[0], "wallCycles": registers_now["clock"] - clear_clock, "all1024BytesZero": True})
                elif event == "render_start":
                    read_state()
                    render_clock, work = registers_now["clock"], "render"
                elif event == "zoom_render_start":
                    ram = read_state()
                    pending_crop = (ram[labels["latched_zoom_x"]], ram[labels["latched_zoom_y"]])
                    if pending[1] != 6 or not (0 <= pending_crop[0] <= 20 and 0 <= pending_crop[1] <= 13):
                        raise AssertionError("Zoom latched an invalid pending crop")
                    if pending_crop != requested_crop:
                        raise AssertionError("Zoom latched a crop other than the requested offsets with no native keys pressed")
                elif event == "render_end":
                    contents[back] = expected(*pending, pending_crop) + bytes(24)
                    work = None
                    ram = read_state()
                    check_source_halves(ram)
                    report["renders"].append({"serial": pending[0], "mode": pending[1], "wallCycles": registers_now["clock"] - render_clock, "independentReferenceMatches": True})
                elif event == "field_complete":
                    ram = read_state()
                    counter = word(ram, "field_counter")
                    if counter != last_field_counter + 1 or not 256 <= registers_now["raster"] <= 258:
                        raise AssertionError("Missing actual completed suite field")
                    if last_field_clock is not None and abs(registers_now["clock"] - last_field_clock - native.PAL_FRAME_CYCLES) > 126:
                        raise AssertionError("Suite field captures are not consecutive")
                    last_field_counter, last_field_clock = counter, registers_now["clock"]
                    elapsed = counter - started_field
                    if elapsed > 501 or word(ram, "mode_fields_left") != max(0, 501 - elapsed) or bool(ram[labels["mode_due"]]) != (elapsed >= 501):
                        raise AssertionError("Suite mode missed its actual501-field deadline")
                    picture = output / f"field-{counter:04d}-mode-{mode}-serial-{serial:04d}.png"
                    monitor.run(f'scrsh "{picture}" 2')
                    comparison = span.actual_image(picture, active_pixels)
                    if mode in (3, 5, 6):
                        active = Image.open(picture).convert("L").crop((32, 35, 352, 235))
                        if active.crop((0, 0, 320, 4)).getbbox() or active.crop((0, 196, 320, 200)).getbbox():
                            raise AssertionError("Centered mirror mode lost its four-pixel margins")
                    report["fields"].append({"field": counter, "mode": mode, "name": NAMES[mode], "serial": serial, "pose": span.pose(serial),
                                              "modeElapsedFields": elapsed, "clock": registers_now["clock"], "screenshot": picture.name,
                                              "yScroll": 7 if mode in (3, 5, 6) else 3, "zoomCrop": list(active_crop) if mode == 6 else None,
                                              "comparison": comparison, "workInProgress": work})
                    if mode == 6:
                        if active_crop == (10, 6) and serial:
                            default_poses.add(span.pose(serial))
                        elif active_crop in corner_requests[:4]:
                            corner_scanouts.add(active_crop)
                    elif mode == 0:
                        normal_images.add(serial)
                    if counter % 100 == 0:
                        print(json.dumps({"suiteActualFieldsVerified": counter, "seconds": counter * native.PAL_FRAME_CYCLES / native.PAL_CLOCK,
                                          "imagesPresented": serial + 1, "mode": mode, "name": NAMES[mode]}), flush=True)
                    if transitions >= 1 and mode == 0 and len(normal_images) >= 3:
                        break
                    if counter > 520:
                        raise AssertionError("Zoom did not hand off to3normal images within bounded proof")
                elif event == "commit_start":
                    ram = read_state()
                    if work or contents[back] != expected(*pending, pending_crop) + bytes(24):
                        raise AssertionError("Suite presentation attempted an unfinished hidden frame")
                    if not (registers_now["raster"] >= 256 or registers_now["raster"] < 50):
                        raise AssertionError("Suite presentation began during visible scanout")
                    if pending[1] != mode and (not ram[labels["mode_due"]] or word(ram, "field_counter") - started_field != 501):
                        raise AssertionError("Suite mode/YSCROLL transition missed its exact boundary")
                    commit_clock = registers_now["clock"]
                elif event == "commit_end":
                    old_mode = mode
                    serial, mode = pending
                    if mode == 6:
                        active_crop = pending_crop
                    front, back = back, front
                    if mode != old_mode:
                        started_field = last_field_counter
                        transitions += 1
                    read_state()
                    active_pixels = suite_pixels(contents[front][:1000], font, mode)
                    if not (registers_now["raster"] >= 256 or registers_now["raster"] < 50):
                        raise AssertionError("Suite presentation ended during visible scanout")
                    if mode != old_mode:
                        report["modeStarts"].append({"mode": mode, "field": started_field, "serial": serial, "clock": registers_now["clock"]})
                    report["commits"].append({"serial": serial, "mode": mode, "field": last_field_counter, "clock": registers_now["clock"],
                                               "publicationWallCycles": registers_now["clock"] - commit_clock})
            if sha(program.read_bytes()) != program_sha:
                raise AssertionError("Suite program changed during native proof")
            durations = [b["field"] - a["field"] for a, b in zip(report["modeStarts"], report["modeStarts"][1:])]
            if durations != [501] or [row["mode"] for row in report["modeStarts"]] != [6, 0]:
                raise AssertionError("Actual zoom501-field duration or normal handoff differs")
            if default_poses != set(range(1, 97)) or corner_scanouts != set(corner_requests[:4]):
                raise AssertionError("Native default96-pose or4corner coverage incomplete")
            report["coverage"]["defaultZoomPoses"] = sorted(default_poses)
            report["coverage"]["cornerScanouts"] = [list(crop) for crop in sorted(corner_scanouts)]
            residence = {}
            for field in report["fields"]:
                residence[field["serial"]] = residence.get(field["serial"], 0) + 1
            report.update({"pass": True, "actualVisibleFieldsVerified": len(report["fields"]), "imagesPresentedIncludingRepeat": serial + 1,
                           "visibleModeFields": durations, "visibleModeSeconds": [value * native.PAL_FRAME_CYCLES / native.PAL_CLOCK for value in durations],
                           "zoomPhaseFields": 501, "zoomPhaseSeconds": 501 * native.PAL_FRAME_CYCLES / native.PAL_CLOCK,
                           "actualModeOrder": [6, 0], "normalHandoffActualScanoutVerified": True,
                           "allActualZoomAndNormalScanoutsMatch": True, "allCacheModeRawPointersMatch": True,
                           "zoomFieldImageCount": len({row["serial"] for row in report["fields"] if row["mode"] == 6}),
                           "zoomFpsIncludingHolds": len({row["serial"] for row in report["fields"] if row["mode"] == 6}) / (501 * native.PAL_FRAME_CYCLES / native.PAL_CLOCK),
                           "frontWritesDuringWork": 0, "immutableFontRawSourceIndexAndLookupWrites": 0, "forcedRefresh": False,
                           "imageFieldResidenceHistogram": {str(value): sum(count == value for count in residence.values()) for value in sorted(set(residence.values()))},
                           "maximumHeldVisibleFields": max(residence.values()), "clearWallCycles": stats([row["wallCycles"] for row in report["clears"]]),
                           "cacheWallCycles": stats([row["wallCycles"] for row in report["caches"]]), "renderWallCycles": stats([row["wallCycles"] for row in report["renders"]]),
                           "scope": "Initial501-field zoom phase plus3normal presented images. Every actual scanout checked,96poses at defaultcrop and4pokedcorner crops. RealCIA keyboard matrix is host-verified; physicalWASD input is not claimed by this minimized native proof. Existing6mode native suite is not rerun."})
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
    print(json.dumps({key: value for key, value in report.items() if key not in ("events", "fields", "commits", "renders", "clears", "caches", "modeStarts", "manifest", "command")}, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=HERE / "build/three-scene-flagship-star-span-zoom")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    args = parser.parse_args()
    verify(args.build, args.vice, args.output or args.build / "pal-proof")


if __name__ == "__main__":
    main()
