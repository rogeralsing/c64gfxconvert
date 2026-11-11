#!/usr/bin/env python3
"""Prove native PAL row waves against independently reconstructed screen history.

Every real field is captured, including held fields during interrupted decoding.
Each D018 store is checked before its row's natural badline. The expected image
is assembled from reference-film rows in the ten frozen history screens, rather
than from the latest frame or a second implementation of the raster player.
"""

import argparse
import importlib.util
import json
import math
from pathlib import Path
import re
import socket
import subprocess

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("raster_ring_helpers", HERE / "verify-ring-player.py")
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)
native, sha, stats = base.native, base.sha, base.stats
EVENTS = ("presented", "frame_done", "copy_start", "copy_end", "render_start", "render_end",
          "map_publish_start", "map_publish_end", "field_complete", "irq_d018_store")


def symbols(path):
    labels = {name: int(value, 16) for name, value in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", path.read_text())}
    required = set(EVENTS) | {"frame_index", "frame_counter", "field_counter", "phase", "newest_index", "back_index",
                              "front_screen_hi", "back_screen_hi", "next_frame", "font", "animation", "animation_end",
                              "source_ptr", "literal_destination", "plays_left", "images_left", "script_cursor",
                              "row_age_table", "row_d018_active", "wave_age_lut", "irq_row_table", "irq_line_table"}
    if required - labels.keys():
        raise AssertionError("Missing raster-wave ABI: " + str(sorted(required - labels.keys())))
    if len({labels[name] for name in EVENTS}) != len(EVENTS):
        raise AssertionError("Raster-wave checkpoints must be distinct")
    return labels


def verify(build, vice, output, repetitions=3):
    build, output = build.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((build / "build.json").read_text())
    labels = symbols(build / "main.sym")
    font, movie = (build / "font.bin").read_bytes(), (build / "movie.bin").read_bytes()
    raw = (build / "reference.frames").read_bytes()
    screens = manifest["addresses"]["screens"]
    if screens != list(range(0x4800, 0x7400, 1024)) or labels["font"] != 0x4000:
        raise AssertionError("Expected eleven complete screens plus the locked font in VIC bank one")
    if len(font) != 2048 or sha(font) != base.LOCKED_FONT:
        raise AssertionError("The raster experiment must retain the locked 256-character font")
    if labels["animation"] != 0x8000 or labels["animation_end"] != 0x8000 + len(movie):
        raise AssertionError("Immutable movie range differs")
    if sha(movie) != manifest["hashes"]["movie"] or sha(raw) != manifest["hashes"]["reference"]:
        raise AssertionError("Movie/reference files differ from native inputs")
    count = manifest["storedFrames"]
    if len(raw) != count * 1000:
        raise AssertionError("Reference must contain exactly 1000 characters per image")
    reference = [raw[index * 1000:(index + 1) * 1000] for index in range(count)]
    timeline = base.timeline_for(manifest, repetitions)
    wave = manifest["rasterWave"] if "rasterWave" in manifest else manifest["wave"]
    start_row, row_count = wave["startRow"], wave["rowCount"]
    if not 0 <= start_row < 25 or not 1 <= row_count <= 25 - start_row:
        raise AssertionError("Invalid wave section")
    split_rows = sorted({0, *range(start_row, start_row + row_count), *([start_row + row_count] if start_row + row_count < 25 else [])})
    program = build / "player.prg"
    program_sha = sha(program.read_bytes())
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    palette = HERE.parent.parent.parent / "palettes/colodore.vpl"
    command = [str(vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100",
               "+warp", "+autostart-warp", "+confirmonexit", "-sounddev", "dummy",
               "+refreshonbreak", "+binarymonitor", "-initbreak", "reset",
               "-autostartprgmode", "1", "-autostart", str(program),
               "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", str(palette),
               "-VICIIsaturation", "1000", "-VICIIcontrast", "1000", "-VICIIbrightness", "1000", "-VICIIgamma", "1000",
               "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    report = {"pass": False, "program_sha256": program_sha, "font_sha256": sha(font), "movie_sha256": sha(movie),
              "reference_sha256": sha(raw), "manifest": manifest, "command": command, "sampledLoopRepetitions": repetitions,
              "method": "Unmodified PAL VICE, forced refresh disabled. Every real field and every D018 row-store deadline are checked. Expected pixels are independently reconstructed from frozen reference-film history rows. Native write checkpoints protect all ten active history screens and immutable font/movie.",
              "events": [], "fields": [], "commits": [], "copies": [], "decodes": [], "rowIrqs": [], "publications": []}
    process = connection = monitor = None
    ring = [bytes(1024) for _ in screens]
    occurrence = 0
    active_newest, active_phase = 0, 0
    active_ages, active_slots, lut = None, None, None
    work, phase = None, "startup"
    guard_baseline = None
    history_watches = []
    current_field_rows = []
    last_field_counter = 0
    last_field_clock = None
    copy_clock = render_clock = publish_clock = None
    publish_old = None
    publication_in_progress = False
    commit_clock = None
    image_field_counts = {}

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
            if native.Monitor.registers(monitor)["pc"] != labels["presented"]:
                raise AssertionError("Initial published blank history not reached")
            monitor.run(f"delete {initial}")
            for event in EVENTS:
                if event != "irq_d018_store":
                    monitor.checkpoint(labels[event])
            trace_response = monitor.run(f"trace exec {labels['irq_d018_store']:04x}")
            if not re.search(r"TRACE:\s*\d+", trace_response):
                raise RuntimeError("Native non-stopping row tracepoint was not installed: " + trace_response)
            base.checkpoint_store(monitor, 0x4000, 0x4800)
            base.checkpoint_store(monitor, labels["animation"], labels["animation_end"])

            def protect_history(newest):
                nonlocal history_watches
                for checkpoint in history_watches:
                    monitor.run(f"delete {checkpoint}")
                hidden = (newest + 1) % 11
                address = screens[hidden]
                history_watches = []
                if address > screens[0]:
                    history_watches.append(base.checkpoint_store(monitor, screens[0], address))
                if address + 1024 < 0x7400:
                    history_watches.append(base.checkpoint_store(monitor, address + 1024, 0x7400))

            def validate_lut(ram):
                nonlocal lut
                lut = ram[labels["wave_age_lut"]:labels["wave_age_lut"] + 25 * 96]
                for row in range(25):
                    for angle in range(96):
                        age = lut[row * 96 + angle]
                        if start_row <= row < start_row + row_count:
                            y = (row - start_row) / (row_count - 1) if row_count > 1 else 0
                            ideal = 4.5 + 4.5 * math.sin(2 * math.pi * (y + angle / 96))
                            # The mathematical waveform admits both neighbors
                            # at exact .5 ties; JS/Python libm may differ by ulps.
                            valid = abs(age - ideal) <= .500000000001
                        else:
                            valid = age == 0
                        if not 0 <= age <= 9 or not valid:
                            raise AssertionError(f"Age LUT violates independent sinusoid at row{row},phase{angle}: {age}")
                if list(ram[labels["irq_row_table"]:labels["irq_row_table"] + len(split_rows)]) != split_rows:
                    raise AssertionError("IRQ rows differ from the selected wave section")
                if list(ram[labels["irq_line_table"]:labels["irq_line_table"] + len(split_rows)]) != [50 + 8 * row for row in split_rows]:
                    raise AssertionError("IRQ row deadlines differ from natural character-row badlines")
                if ram[labels["irq_d018_store"]:labels["irq_d018_store"] + 3] != bytes([0x8d, 0x18, 0xd0]):
                    raise AssertionError("Native row checkpoint does not execute STA $d018")

            def read_state():
                nonlocal guard_baseline
                monitor.run("bank ram")
                ram = monitor.dump(output / "last-ram.bin", 0, 65535)
                monitor.run("bank io")
                vic = monitor.dump(output / "last-vic.bin", 0xd000, 0xd03f)
                cia = monitor.dump(output / "last-cia.bin", 0xdd00, 0xdd02)
                colors = monitor.dump(output / "last-colors.bin", 0xd800, 0xdbff)
                monitor.run("bank cpu")
                if ram[0x4000:0x4800] != font or ram[labels["animation"]:labels["animation_end"]] != movie:
                    raise AssertionError("Locked font or source movie changed")
                guards = ram[0x7400:0x8000] + ram[labels["animation_end"]:0xd000]
                if guard_baseline is None:
                    guard_baseline = guards
                if guards != guard_baseline:
                    raise AssertionError("A screen/movie write escaped its allocation")
                if registers["cpu_port"] != 0x35 or cia[0] & 3 != 2 or cia[2] & 3 != 3:
                    raise AssertionError("Unexpected 6510 or VIC bank mapping")
                if vic[0x11] & 0x7f != 0x1b or vic[0x16] & 0x1f != 8 or vic[0x15]:
                    raise AssertionError("Unexpected character mode or sprites")
                if vic[0x18] & 14 or not 2 <= vic[0x18] >> 4 <= 12:
                    raise AssertionError("D018 selected another charset or an unallocated screen")
                if vic[0x20] & 15 or vic[0x21] & 15 or any(value & 15 != 1 for value in colors):
                    raise AssertionError("Unexpected shared color RAM or background")
                hidden = (active_newest + 1) % 11
                for index, address in enumerate(screens):
                    if work in ("copy", "decode") and index == hidden:
                        continue
                    if ram[address:address + 1024] != ring[index]:
                        raise AssertionError(f"Frozen slot{index} differs at image{occurrence}, phase{phase}")
                return ram

            def expected_map(ram):
                ages = [lut[row * 96 + active_phase] for row in range(25)]
                slots = [(active_newest - age) % 11 for age in ages]
                if list(ram[labels["row_age_table"]:labels["row_age_table"] + 25]) != ages:
                    raise AssertionError("Published age map differs from independently validated waveform")
                if list(ram[labels["row_d018_active"]:labels["row_d018_active"] + 25]) != [0x20 + slot * 16 for slot in slots]:
                    raise AssertionError("Published row map selects the wrong frozen history slots")
                if (active_newest + 1) % 11 in slots:
                    raise AssertionError("Visible map selected the hidden work screen")
                return ages, slots

            def consume_row_traces(response):
                # Native VICE prints the exact raster position, CPU registers,
                # and stopwatch at a tracepoint without opening the monitor.
                pattern = re.compile(
                    r"#\d+ \([^\n]*trace[^\n]*\)\s+(\d+)/\$[0-9a-f]+,\s*(\d+)/\$[0-9a-f]+\s*\n"
                    r"\.C:([0-9a-f]{4})[^\n]*- A:([0-9a-f]{2}) X:([0-9a-f]{2})[^\n]*?\s(\d+)\s*(?:\n|$)", re.I)
                for match in pattern.finditer(response):
                    if int(match[3], 16) != labels["irq_d018_store"]:
                        continue
                    if publication_in_progress:
                        raise AssertionError("Row IRQ saw a partially published map")
                    index = int(match[5], 16)
                    if index >= len(split_rows) or index != len(current_field_rows):
                        raise AssertionError("D018 row IRQs are missing or reordered")
                    row = split_rows[index]
                    expected = 0x20 + active_slots[row] * 16
                    if int(match[4], 16) != expected:
                        raise AssertionError("Row IRQ selected a different historical screen")
                    line, cycle = int(match[1]), int(match[2])
                    if line != 50 + 8 * row or cycle + 4 > 63:
                        raise AssertionError("D018 write did not finish before the next-line badline")
                    current_field_rows.append(row)
                    report["rowIrqs"].append({"occurrence": occurrence, "phase": active_phase, "row": row, "slot": active_slots[row],
                                               "line": line, "storeStartCycle": cycle, "clocksBeforeBadline": 63 - cycle - 4,
                                               "clock": int(match[6])})

            first_event = True
            while True:
                if not first_event:
                    consume_row_traces(monitor.run("x"))
                first_event = False
                registers = base.full_registers(monitor)
                event = next((name for name in EVENTS if labels[name] == registers["pc"]), None)
                if event is None:
                    raise AssertionError(f"Unexpected history/source write or native breakpoint at${registers['pc']:04x}")
                phase = event
                report["events"].append({"event": event, "occurrence": occurrence, **registers})
                if event == "presented":
                    ram = read_state()
                    if lut is None:
                        validate_lut(ram)
                        active_ages, active_slots = expected_map(ram)
                        protect_history(active_newest)
                        report["startupAllElevenScreensBlank"] = all(ram[address:address + 1024] == bytes(1024) for address in screens)
                        if not report["startupAllElevenScreensBlank"]:
                            raise AssertionError("Startup historical screens were not all blank")
                    if ram[labels["newest_index"]] != active_newest or ram[labels["phase"]] != active_phase or ram[labels["frame_index"]] != timeline[occurrence]["pose"]:
                        raise AssertionError("Presented history/phase state differs")
                    if commit_clock is None:
                        commit_clock = registers["clock"]
                elif event == "frame_done":
                    ram = read_state()
                    counter = int.from_bytes(ram[labels["frame_counter"]:labels["frame_counter"] + 2], "little")
                    if counter != occurrence + 1:
                        raise AssertionError("Animation image counter differs")
                    expected = timeline[occurrence]
                    for name in ("plays_left", "images_left", "script_cursor"):
                        width = 2 if name == "plays_left" else 1
                        if int.from_bytes(ram[labels[name]:labels[name] + width], "little") != expected[name]:
                            raise AssertionError("Script counter mismatch for " + name)
                    if (occurrence + 1) % 32 == 0:
                        print(json.dumps({"rasterNativeImagesVerified": occurrence + 1, "visibleFields": len(report["fields"]), "rowIrqDeadlines": len(report["rowIrqs"])}), flush=True)
                elif event == "copy_start":
                    ram = read_state()
                    back = (active_newest + 1) % 11
                    if ram[labels["back_index"]] != back or ram[labels["back_screen_hi"]] != screens[back] >> 8:
                        raise AssertionError("Copy target is not the excluded eleventh screen")
                    if ram[labels["front_screen_hi"]] != screens[active_newest] >> 8:
                        raise AssertionError("Copy source is not newest")
                    copy_clock, work = registers["clock"], "copy"
                elif event == "copy_end":
                    back = (active_newest + 1) % 11
                    ring[back] = ring[active_newest]
                    work = None
                    read_state()
                    report["copies"].append({"occurrence": occurrence, "sourceSlot": active_newest, "targetSlot": back,
                                              "bytes": 1024, "wallCycles": registers["clock"] - copy_clock, "all1024BytesMatchNewest": True})
                elif event == "render_start":
                    read_state()
                    render_clock, work = registers["clock"], "decode"
                elif event == "render_end":
                    target = timeline[occurrence + 1]["pose"] if occurrence + 1 < len(timeline) else manifest["loop"]["startFrame"]
                    back = (active_newest + 1) % 11
                    ring[back] = reference[target] + bytes(24)
                    work = None
                    ram = read_state()
                    source = int.from_bytes(ram[labels["source_ptr"]:labels["source_ptr"] + 2], "little") + registers["y"]
                    destination = int.from_bytes(ram[labels["literal_destination"]:labels["literal_destination"] + 2], "little")
                    patch = manifest["sourcePatches"][timeline[occurrence]["pose"]]
                    if source != patch["address"] + patch["bytes"] or destination != screens[back] + 1000 or ram[labels["next_frame"]] != target:
                        raise AssertionError("Interrupted decoder output or outgoing codec cursors differ")
                    report["decodes"].append({"occurrence": occurrence, "targetPose": target, "wallCycles": registers["clock"] - render_clock,
                                               "sourceEnd": source, "destinationEnd": destination, "codecCursorsMatch": True})
                elif event == "field_complete":
                    if publication_in_progress or current_field_rows != split_rows:
                        raise AssertionError("Completed field saw an incomplete row sequence/publication")
                    ram = read_state()
                    if ram[labels["newest_index"]] != active_newest or ram[labels["phase"]] != active_phase or ram[labels["frame_index"]] != timeline[occurrence]["pose"]:
                        raise AssertionError("Active history state changed within the visible field")
                    ages, slots = expected_map(ram)
                    field_counter = int.from_bytes(ram[labels["field_counter"]:labels["field_counter"] + 2], "little")
                    if field_counter != (last_field_counter + 1) % 65536 or registers["raster"] != 256:
                        raise AssertionError("Missing real completed PAL field")
                    if last_field_clock is not None and abs(registers["clock"] - last_field_clock - native.PAL_FRAME_CYCLES) > 63:
                        raise AssertionError("Completed-field timestamps do not cover consecutive PAL fields")
                    last_field_counter, last_field_clock = field_counter, registers["clock"]
                    composite = b"".join(ring[slot][row * 40:(row + 1) * 40] for row, slot in enumerate(slots))
                    picture = output / f"field-{len(report['fields']):04d}-image-{occurrence:03d}-pose-{timeline[occurrence]['pose']:03d}.png"
                    monitor.run(f'scrsh "{picture}" 2')
                    comparison = base.actual_image(picture, native.pixels_from_screen(composite, font))
                    image_field_counts[occurrence] = image_field_counts.get(occurrence, 0) + 1
                    report["fields"].append({"occurrence": occurrence, "pose": timeline[occurrence]["pose"], "phase": active_phase,
                                              "newestSlot": active_newest, "ageByRow": ages, "slotByRow": slots,
                                              "fieldCounter": field_counter, "clock": registers["clock"], "screenshot": picture.name,
                                              "comparison": comparison, "workInProgress": work})
                    current_field_rows = []
                elif event == "map_publish_start":
                    ram = read_state()
                    expected_map(ram)
                    if work is not None or not (registers["raster"] >= 256 or registers["raster"] < 50):
                        raise AssertionError("Map publication began during unfinished work or visible scanout")
                    if occurrence + 1 == len(timeline):
                        break
                    publication_in_progress = True
                    publish_clock, publish_old = registers["clock"], (active_newest, active_phase)
                elif event == "map_publish_end":
                    if not publication_in_progress:
                        raise AssertionError("Unpaired map publication")
                    occurrence += 1
                    active_newest, active_phase = occurrence % 11, occurrence % 96
                    ram = read_state()
                    active_ages, active_slots = expected_map(ram)
                    if ram[labels["newest_index"]] != active_newest or ram[labels["phase"]] != active_phase or ram[labels["frame_index"]] != timeline[occurrence]["pose"]:
                        raise AssertionError("Atomic publication did not rotate newest/phase/frame together")
                    if not (registers["raster"] >= 256 or registers["raster"] < 50):
                        raise AssertionError("Map publication completed during visible scanout")
                    publication_in_progress = False
                    protect_history(active_newest)
                    report["publications"].append({"occurrence": occurrence, "oldNewest": publish_old[0], "newNewest": active_newest,
                                                    "oldPhase": publish_old[1], "newPhase": active_phase, "wallCycles": registers["clock"] - publish_clock,
                                                    "atomicBeforeNextVisibleRow": True})
                    report["commits"].append({"occurrence": occurrence, "pose": timeline[occurrence]["pose"], "clock": registers["clock"],
                                              "intervalCycles": registers["clock"] - commit_clock})
                    commit_clock = registers["clock"]
            if sha(program.read_bytes()) != program_sha:
                raise AssertionError("Program changed during native proof")
            intervals = [row["intervalCycles"] for row in report["commits"]]
            wraps = sum(a["pose"] == count - 1 and b["pose"] == manifest["loop"]["startFrame"] for a, b in zip(timeline, timeline[1:]))
            report.update({"pass": True, "displayedImagesVerified": len(timeline), "uniqueSourceFramesVerified": len(set(row["pose"] for row in timeline)),
                           "actualVisibleFieldsVerified": len(report["fields"]), "filmWrapsVerified": wraps, "ringWrapsVerified": (len(timeline) - 1) // 11,
                           "allElevenSlotsUsed": sorted(set(row["newestSlot"] for row in report["fields"])) == list(range(11)),
                           "allCompositeScanoutsMatch": True, "all1024ByteCopiesMatch": True, "allBadlineDeadlinesPassed": True,
                           "activeHistoryWritesDuringWork": 0, "immutableFontMovieWrites": 0, "forcedRefresh": False,
                           "rowIrqStoreEventsVerified": len(report["rowIrqs"]), "minimumClocksBeforeBadline": min(row["clocksBeforeBadline"] for row in report["rowIrqs"]),
                           "rowIrqTraceMethod": "Non-stopping native VICE execution tracepoint at the actual STA $d018; all raster positions and selected D018 bytes checked.",
                           "copyWallCycles": stats([row["wallCycles"] for row in report["copies"]]),
                           "decodeWallCycles": stats([row["wallCycles"] for row in report["decodes"]]),
                           "publicationWallCycles": stats([row["wallCycles"] for row in report["publications"]]),
                           "presentationCycles": stats(intervals), "meanFps": native.PAL_CLOCK / (sum(intervals) / len(intervals)),
                           "observedFieldsPerImage": sorted(set(image_field_counts.values())),
                           "imageFieldCounts": image_field_counts,
                           "scope": "Natural 8-line character-row badline splits, ten frozen histories plus one hidden work screen; no one-pixel FLI, music or other interrupt workload. All extra held fields are captured and certified."})
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
    print(json.dumps({key: value for key, value in report.items() if key not in ("events", "fields", "commits", "copies", "decodes", "rowIrqs", "publications", "manifest", "command", "imageFieldCounts")}, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=HERE / "build/three-scene-flagship-star-raster-wave/raster-wave")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    parser.add_argument("--repetitions", type=int, default=3, choices=range(1, 5))
    args = parser.parse_args()
    verify(args.build, args.vice, args.output or args.build / "pal-proof", args.repetitions)


if __name__ == "__main__":
    main()
