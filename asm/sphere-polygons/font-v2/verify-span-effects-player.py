#!/usr/bin/env python3
"""Verify timed C64 effects rendered directly from X,length,raw row spans.

The expected images come from the original 97 complete character screens. The
serialized-byte oracle expands raw spans directly, including their empty prefix
and tail. No previous screen, key, delta, hold-codec or reconstruction is used
to calculate expected source images.
"""

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import socket
import statistics
import subprocess

from PIL import Image, ImageChops

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("span_native_monitor", HERE.parent / "verify-c64.py")
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)
LOCKED_FONT = "1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1"
REFERENCE = "5c245453149adfa4bafd433efa50b606a614ff3264eac46f0c5a0906bc9b698c"
EVENTS = ("presented", "clear_start", "clear_end", "cache_start", "cache_end", "render_start", "render_end", "commit_start", "commit_end", "field_complete")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def stats(values):
    return {"min": min(values), "mean": statistics.mean(values), "max": max(values)} if values else None


def registers(monitor):
    response = monitor.run("r")
    match = re.search(r"^\.;([0-9a-fA-F]{4})\s+(.*)$", response, re.M)
    if not match:
        raise RuntimeError("Incomplete native register response")
    fields = match[2].split()
    return {"pc": int(match[1], 16), "a": int(fields[0], 16), "x": int(fields[1], 16), "y": int(fields[2], 16),
            "cpu_port": int(fields[5], 16), "raster": int(fields[-3]), "raster_cycle": int(fields[-2]), "clock": int(fields[-1])}


def store_checkpoint(monitor, start, end):
    response = monitor.run(f"break store {start:04x} {end - 1:04x}")
    match = re.search(r"(?:BREAK|WATCH):\s*(\d+)", response)
    if not match:
        raise RuntimeError("Native memory-write checkpoint was not installed")
    return int(match[1])


def actual_image(path, pixels):
    actual = Image.open(path).convert("RGB").crop((32, 35, 352, 235))
    expected = Image.frombytes("L", (320, 200), pixels).convert("RGB")
    if ImageChops.difference(actual, expected).getbbox():
        raise AssertionError("Actual completed VIC field differs from independent reference composite: " + path.name)
    return {"origin": [32, 35], "comparedPixels": 64000, "differentPixels": 0}


def pose(serial):
    return 0 if serial <= 0 else 1 + (serial - 1) % 96


class SpanOracle:
    def __init__(self, payload, frame_offsets, reference):
        if len(payload) != 22882 or len(frame_offsets) != 194 or len(reference) != 97000:
            raise AssertionError("Expected the frozen 22882-byte raw-row film and194-byte frame table")
        self.payload = payload
        self.offsets = [int.from_bytes(frame_offsets[index:index + 2], "little") for index in range(0, 194, 2)]
        self.pointers, self.spans = [], []
        cursor = 0
        for frame, offset in enumerate(self.offsets):
            pointers, spans = [], []
            screen = bytearray(1000)
            if offset == 0xffff:
                if frame != 0:
                    raise AssertionError("Only startup frame0 may be implicit blank")
                pointers, spans = [None] * 25, [(0, 0, b"")] * 25
            else:
                if offset != cursor:
                    raise AssertionError("Frame pointer skips bytes or enters the middle of a raw row")
                for row in range(25):
                    pointers.append(cursor)
                    x, length = payload[cursor:cursor + 2]
                    cursor += 2
                    if x > 40 or length > 40 - x or cursor + length > len(payload):
                        raise AssertionError("Raw X/length row exceeds40 cells or source bytes")
                    raw = payload[cursor:cursor + length]
                    cursor += length
                    screen[row * 40 + x:row * 40 + x + length] = raw
                    spans.append((x, length, raw))
            if bytes(screen) != reference[frame * 1000:(frame + 1) * 1000]:
                raise AssertionError(f"Independent direct-span expansion differs from original frame{frame}")
            self.pointers.append(pointers)
            self.spans.append(spans)
        if cursor != len(payload):
            raise AssertionError("Raw span stream has unindexed trailing bytes")


def validate_ages(ages):
    if len(ages) != 2400:
        raise AssertionError("Expected25×96 wave ages")
    for row in range(25):
        for phase in range(96):
            ideal = 4.5 + 4.5 * math.sin(2 * math.pi * (row / 24 + phase / 96))
            age = ages[row * 96 + phase]
            if not 0 <= age <= 9 or abs(age - ideal) > .500000000001:
                raise AssertionError("Wave ages differ from the independent sinusoid")


def composite(reference, ages, serial, mode):
    output = bytearray(1000)
    for row in range(25):
        a = pose(max(0, serial - ages[row * 96 + serial % 96])) if mode == 1 else pose(serial)
        b = pose(max(0, serial - 48))
        for x in range(40):
            selected = b if mode == 2 and ((x >> 2) ^ (row >> 2)) & 1 else a
            output[row * 40 + x] = reference[selected * 1000 + row * 40 + x]
    return bytes(output)


def symbols(path):
    labels = {name: int(value, 16) for name, value in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", path.read_text())}
    required = set(EVENTS) | {"mode", "next_mode", "film_frame", "next_film_frame", "film_serial", "next_serial", "phase", "next_phase",
                              "field_counter", "mode_started_field", "mode_fields_left", "mode_due", "front_screen_hi", "back_screen_hi",
                              "font", "animation", "animation_end", "wave_ages", "cache_frame_ids", "cache_table_count", "row_cache"}
    if required - labels.keys():
        raise AssertionError("Missing direct-span ABI: " + str(sorted(required - labels.keys())))
    if len({labels[name] for name in EVENTS}) != len(EVENTS):
        raise AssertionError("Native lifecycle checkpoints must be distinct")
    return labels


def verify(build, vice, output):
    build, output = build.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((build / "build.json").read_text())
    labels = symbols(build / "main.sym")
    font, payload = (build / "font.bin").read_bytes(), (build / "rows.bin").read_bytes()
    reference = (build / "reference.frames").read_bytes()
    frame_offsets = (build / "frame-offsets16.bin").read_bytes()
    oracle = SpanOracle(payload, frame_offsets, reference)
    if len(font) != 2048 or sha(font) != LOCKED_FONT or sha(reference) != REFERENCE:
        raise AssertionError("Original locked font/reference changed")
    if labels["font"] != 0x4000 or labels["animation"] != 0x5000 or labels["animation_end"] != 0x5000 + len(payload):
        raise AssertionError("Unexpected direct raw-span source/font addresses")
    regions = []
    for item in manifest["sourceRegions"]:
        data = (build / item["file"]).read_bytes()
        if len(data) != item["end"] - item["start"] or sha(data) != item["sha256"]:
            raise AssertionError("Loaded immutable source region file/hash differs")
        regions.append({**item, "data": data})
    if not any(item["start"] == 0x5000 and item["data"] == payload for item in regions):
        raise AssertionError("Direct raw-row payload is missing from loaded source regions")
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
    report = {"pass": False, "program_sha256": program_sha, "font_sha256": sha(font), "rows_sha256": sha(payload),
              "frameOffsets_sha256": sha(frame_offsets), "reference_sha256": sha(reference), "manifest": manifest, "command": command,
              "method": "Unmodified native PAL VICE, forced refresh disabled. Every actual field is compared with the original97-screen reference. X,length,raw spans and row-pointer caches are independently checked; every hidden frame begins with1024 cleared bytes.",
              "events": [], "fields": [], "commits": [], "renders": [], "clears": [], "caches": [], "modeStarts": [],
              "coverage": {"cacheRowPointersChecked": 0, "staleNonzeroCellsCleared": 0, "staleCellsOutsideNewImageCleared": 0,
                           "checkerFramesWhereUnclippedACorruptsPixels": 0, "checkerFramesWhereUnclippedBCorruptsPixels": 0,
                           "checkerRawSpansCrossingMaskBoundary": 0}}
    process = connection = monitor = None
    screens = [0x4800, 0x4c00]
    screen_cache = {screen: bytes(1024) for screen in screens}
    active_serial = active_mode = active_started_field = transitions = 0
    front, back = screens
    ages = active_pixels = None
    work, stage = None, "startup"
    front_watch = None
    guard_baseline = None
    last_field_counter = 0
    last_field_clock = None
    clear_clock = cache_clock = render_clock = commit_clock = None
    pending = None

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
                raise AssertionError("Initial blank presentation not reached")
            monitor.run(f"delete {initial}")
            for event in EVENTS:
                monitor.checkpoint(labels[event])
            store_checkpoint(monitor, 0x4000, 0x4800)
            for region in regions:
                store_checkpoint(monitor, region["start"], region["end"])

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
                        raise AssertionError("Immutable raw source region changed: " + region["file"])
                guard = ram[labels["animation_end"]:0xd000]
                if guard_baseline is None:
                    guard_baseline = guard
                if guard != guard_baseline:
                    raise AssertionError("Unexpected write beyond raw source allocation")
                if registers_now["cpu_port"] != 0x35 or cia[0] & 3 != 2 or cia[2] & 3 != 3:
                    raise AssertionError("Unexpected6510 or VIC bank")
                if vic[0x11] & 0x7f != 0x1b or vic[0x16] & 0x1f != 8 or vic[0x15] or vic[0x18] & 0xfe != (0x20 if front == 0x4800 else 0x30):
                    raise AssertionError("Unexpected VIC mode/front screen/font")
                if vic[0x20] & 15 or vic[0x21] & 15 or any(value & 15 != 1 for value in colors):
                    raise AssertionError("Unexpected shared color RAM/background")
                if ram[labels["front_screen_hi"]] << 8 != front or ram[labels["back_screen_hi"]] << 8 != back:
                    raise AssertionError("Native front/back pointers differ")
                if word(ram, "film_serial") != active_serial or ram[labels["mode"]] != active_mode or ram[labels["film_frame"]] != pose(active_serial) or ram[labels["phase"]] != active_serial % 96:
                    raise AssertionError("Active mode/source metadata changed before atomic commit")
                if word(ram, "mode_started_field") != active_started_field:
                    raise AssertionError("Visible mode start field differs")
                if ages is not None and ram[labels["wave_ages"]:labels["wave_ages"] + 2400] != ages:
                    raise AssertionError("Wave LUT changed")
                for screen in screens:
                    if screen == back and work == "render":
                        if ram[screen + 1000:screen + 1024] != bytes(24):
                            raise AssertionError("A raw-span store overran1000 character cells")
                        continue
                    if screen == back and work == "clear":
                        continue
                    if ram[screen:screen + 1024] != screen_cache[screen]:
                        raise AssertionError(f"Screen${screen:04x} differs at serial{active_serial},stage{stage}")
                return ram

            def validate_cache(ram):
                cached = []
                count = ram[labels["cache_table_count"]]
                if count not in (1, 2, 10) or count * 50 > 500:
                    raise AssertionError("Row-pointer cache exceeds its500-byte pool")
                for slot in range(count):
                    source_pose = ram[labels["cache_frame_ids"] + slot]
                    if source_pose > 96:
                        raise AssertionError("Row-pointer cache refers to an invalid source pose")
                    cached.append(source_pose)
                    for row in range(25):
                        index = labels["row_cache"] + slot * 50 + row * 2
                        pointer = int.from_bytes(ram[index:index + 2], "little")
                        expected = oracle.pointers[source_pose][row]
                        if expected is None:
                            if pointer + 1 >= 65536 or ram[pointer + 1] != 0 or ram[pointer] > 40:
                                raise AssertionError("Implicit blank cache row is not an empty raw span")
                        elif pointer != 0x5000 + expected:
                            raise AssertionError("Cached row pointer skips its X/length header or selects another source row")
                        report["coverage"]["cacheRowPointersChecked"] += 1
                needed = {pose(pending[0])}
                if pending[1] == 1:
                    needed = {pose(max(0, pending[0] - ages[row * 96 + pending[0] % 96])) for row in range(25)}
                elif pending[1] == 2:
                    needed.add(pose(max(0, pending[0] - 48)))
                if not needed.issubset(set(cached)):
                    raise AssertionError("Direct cache omits a source selected by the pending composite")

            def clipping_coverage(serial):
                a, b = pose(serial), pose(max(0, serial - 48))
                bad_a = bad_b = crosses = 0
                for row in range(25):
                    ax, alen, araw = oracle.spans[a][row]
                    bx, blen, braw = oracle.spans[b][row]
                    for x in range(40):
                        parity = ((x >> 2) ^ (row >> 2)) & 1
                        acell = reference[a * 1000 + row * 40 + x]
                        bcell = reference[b * 1000 + row * 40 + x]
                        if parity == 1 and ax <= x < ax + alen and not bx <= x < bx + blen and acell != 0:
                            bad_a += 1
                        if parity == 0 and bx <= x < bx + blen and bcell != acell:
                            bad_b += 1
                    for x, length, raw in ((ax, alen, araw), (bx, blen, braw)):
                        if length and (x >> 2) != ((x + length - 1) >> 2):
                            crosses += 1
                report["coverage"]["checkerFramesWhereUnclippedACorruptsPixels"] += int(bad_a > 0)
                report["coverage"]["checkerFramesWhereUnclippedBCorruptsPixels"] += int(bad_b > 0)
                report["coverage"]["checkerRawSpansCrossingMaskBoundary"] += crosses

            first_event = True
            while True:
                if not first_event:
                    monitor.run("x")
                first_event = False
                registers_now = registers(monitor)
                event = next((name for name in EVENTS if labels[name] == registers_now["pc"]), None)
                if event is None:
                    raise AssertionError(f"Unexpected raw source/front write or breakpoint at${registers_now['pc']:04x}")
                stage = event
                report["events"].append({"event": event, "serial": active_serial, **registers_now})
                if event == "presented":
                    ram = read_state()
                    if ages is None:
                        ages = ram[labels["wave_ages"]:labels["wave_ages"] + 2400]
                        validate_ages(ages)
                        if any(ram[screen:screen + 1024] != bytes(1024) for screen in screens):
                            raise AssertionError("Startup screens are not completely blank")
                        active_pixels = native.pixels_from_screen(composite(reference, ages, 0, 0), font)
                        report["modeStarts"].append({"mode": 0, "field": 0, "serial": 0, "clock": registers_now["clock"]})
                    if front_watch is not None:
                        monitor.run(f"delete {front_watch}")
                    front_watch = store_checkpoint(monitor, front, front + 1024)
                elif event in ("clear_start", "cache_start"):
                    ram = read_state()
                    next_state = (word(ram, "next_serial"), ram[labels["next_mode"]])
                    if next_state[0] != active_serial + 1 or next_state[1] not in (active_mode, (active_mode + 1) % 3):
                        raise AssertionError("Pending direct source serial/mode differs")
                    if ram[labels["next_film_frame"]] != pose(next_state[0]) or ram[labels["next_phase"]] != next_state[0] % 96:
                        raise AssertionError("Pending direct source pose/phase differs")
                    pending = next_state
                    if event == "clear_start":
                        expected = composite(reference, ages, pending[0], pending[1])
                        report["coverage"]["staleNonzeroCellsCleared"] += sum(value != 0 for value in screen_cache[back][:1000])
                        report["coverage"]["staleCellsOutsideNewImageCleared"] += sum(old != 0 and new == 0 for old, new in zip(screen_cache[back], expected))
                        clear_clock, work = registers_now["clock"], "clear"
                    else:
                        cache_clock = registers_now["clock"]
                elif event == "clear_end":
                    screen_cache[back] = bytes(1024)
                    work = None
                    read_state()
                    report["clears"].append({"serial": pending[0], "wallCycles": registers_now["clock"] - clear_clock, "all1024BytesZero": True})
                elif event == "cache_end":
                    ram = read_state()
                    validate_cache(ram)
                    report["caches"].append({"serial": pending[0], "mode": pending[1], "wallCycles": registers_now["clock"] - cache_clock,
                                              "allPointersMatchDirectSpanHeaders": True})
                elif event == "render_start":
                    read_state()
                    render_clock, work = registers_now["clock"], "render"
                elif event == "render_end":
                    screen_cache[back] = composite(reference, ages, pending[0], pending[1]) + bytes(24)
                    work = None
                    read_state()
                    if pending[1] == 2:
                        clipping_coverage(pending[0])
                    report["renders"].append({"serial": pending[0], "mode": pending[1], "wallCycles": registers_now["clock"] - render_clock,
                                               "modeTransition": pending[1] != active_mode, "fullIndependentScreenMatch": True})
                elif event == "field_complete":
                    ram = read_state()
                    counter = word(ram, "field_counter")
                    if counter != last_field_counter + 1 or not 256 <= registers_now["raster"] <= 258:
                        raise AssertionError("Missing actual completed PAL field")
                    if last_field_clock is not None and abs(registers_now["clock"] - last_field_clock - native.PAL_FRAME_CYCLES) > 126:
                        raise AssertionError("Actual field scanouts are not consecutive")
                    last_field_counter, last_field_clock = counter, registers_now["clock"]
                    elapsed = counter - active_started_field
                    if elapsed > 501:
                        raise AssertionError(f"Visible mode{active_mode} exceeded its501-field deadline: {elapsed}")
                    if word(ram, "mode_fields_left") != max(0, 501 - elapsed) or bool(ram[labels["mode_due"]]) != (elapsed >= 501):
                        raise AssertionError("Mode timer is not counting actual PAL fields")
                    picture = output / f"field-{counter:04d}-mode-{active_mode}-serial-{active_serial:04d}.png"
                    monitor.run(f'scrsh "{picture}" 2')
                    comparison = actual_image(picture, active_pixels)
                    report["fields"].append({"field": counter, "mode": active_mode, "serial": active_serial, "filmPose": pose(active_serial),
                                              "phase": active_serial % 96, "modeElapsedFields": elapsed, "clock": registers_now["clock"],
                                              "workInProgress": work, "screenshot": picture.name, "comparison": comparison})
                    if counter % 100 == 0:
                        print(json.dumps({"spanEffectsFieldsVerified": counter, "seconds": counter * native.PAL_FRAME_CYCLES / native.PAL_CLOCK,
                                          "imagesCommitted": active_serial + 1, "mode": active_mode}), flush=True)
                    if transitions >= 3 and active_mode == 0:
                        break
                    if counter > 1600:
                        raise AssertionError("Timed three-mode cycle did not repeat")
                elif event == "commit_start":
                    ram = read_state()
                    if work or screen_cache[back] != composite(reference, ages, pending[0], pending[1]) + bytes(24):
                        raise AssertionError("Attempted to publish an incomplete direct-span screen")
                    if not (registers_now["raster"] >= 256 or registers_now["raster"] < 50):
                        raise AssertionError("Presentation began during visible scanout")
                    if pending[1] != active_mode and (not ram[labels["mode_due"]] or word(ram, "field_counter") - active_started_field != 501):
                        raise AssertionError("Mode transition missed its501-field visible deadline")
                    commit_clock = registers_now["clock"]
                elif event == "commit_end":
                    old_mode = active_mode
                    active_serial, active_mode = pending
                    front, back = back, front
                    if active_mode != old_mode:
                        active_started_field = last_field_counter
                        transitions += 1
                    read_state()
                    active_pixels = native.pixels_from_screen(screen_cache[front][:1000], font)
                    if not (registers_now["raster"] >= 256 or registers_now["raster"] < 50):
                        raise AssertionError("Presentation finished during visible scanout")
                    if active_mode != old_mode:
                        report["modeStarts"].append({"mode": active_mode, "field": active_started_field, "serial": active_serial, "clock": registers_now["clock"]})
                    report["commits"].append({"serial": active_serial, "mode": active_mode, "field": last_field_counter,
                                               "clock": registers_now["clock"], "publicationWallCycles": registers_now["clock"] - commit_clock})
            if sha(program.read_bytes()) != program_sha:
                raise AssertionError("Program changed during native proof")
            durations = [b["field"] - a["field"] for a, b in zip(report["modeStarts"], report["modeStarts"][1:])]
            if durations != [501, 501, 501] or [row["mode"] for row in report["modeStarts"]] != [0, 1, 2, 0]:
                raise AssertionError("Mode cycle was not normal→wave→checker→normal, each501 actual fields")
            if not all(value > 0 for value in report["coverage"].values()):
                raise AssertionError("Raw span corpus did not exercise stale clearing and both sides of checker clipping")
            residence = {}
            for field in report["fields"]:
                residence[field["serial"]] = residence.get(field["serial"], 0) + 1
            report.update({"pass": True, "actualVisibleFieldsVerified": len(report["fields"]), "imagesCommitted": active_serial + 1,
                           "visibleModeFields": durations, "visibleModeSeconds": [value * native.PAL_FRAME_CYCLES / native.PAL_CLOCK for value in durations],
                           "threeModeCycleFields": sum(durations), "threeModeCycleSeconds": sum(durations) * native.PAL_FRAME_CYCLES / native.PAL_CLOCK,
                           "repeatBoundaryActualScanoutVerified": True, "allActualScanoutsMatch": True, "allDirectSpansAndCachePointersMatch": True,
                           "serializedFilmBytes": len(payload) + len(frame_offsets), "rowPointerPoolBytes": 500,
                           "frontWritesDuringWork": 0, "immutableFontRawFilmIndexWrites": 0, "forcedRefresh": False,
                           "fieldResidenceHistogram": {str(value): sum(count == value for count in residence.values()) for value in sorted(set(residence.values()))},
                           "maximumHeldVisibleFields": max(residence.values()),
                           "meanCommittedImagesPerCycleSecond": active_serial / (1503 * native.PAL_FRAME_CYCLES / native.PAL_CLOCK),
                           "clearWallCycles": stats([row["wallCycles"] for row in report["clears"]]),
                           "cacheWallCycles": stats([row["wallCycles"] for row in report["caches"]]),
                           "renderWallCycles": stats([row["wallCycles"] for row in report["renders"]]),
                           "scope": "One real timed three-mode cycle plus first repeated-normal scanout. Direct independent X,length,raw rows; two output buffers;500-byte row-pointer pool. No precomputed30-second output movie, image history buffers, music or other interrupt workload."})
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
    parser.add_argument("--build", type=Path, default=HERE / "build/three-scene-flagship-star-span-effects")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    args = parser.parse_args()
    verify(args.build, args.vice, args.output or args.build / "pal-proof")


if __name__ == "__main__":
    main()
