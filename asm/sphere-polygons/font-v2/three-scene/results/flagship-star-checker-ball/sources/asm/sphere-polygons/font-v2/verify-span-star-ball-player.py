#!/usr/bin/env python3
"""Focused native PAL proof of two objects sharing one seven-effect player.

Authoring gate: independent full reference screens and per-object empirical LUTs
own the visible contract. Wrong object pointers, 48-pose phase, history reset,
I/O-gap source placement, or stale hidden output fail at real VIC scanout. The
previous single-object proof cannot exercise object publication. Only public
phase-clock variables are monitor-adjusted to bound the run; every injection is
recorded and the ball zoom alone runs all501physical fields without adjustment.
"""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import re
import socket
import subprocess

from PIL import Image

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("two_object_zoom_helpers", HERE / "verify-span-zoom-player.py")
zoom = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(zoom)
span, mirror, native = zoom.span, zoom.mirror, zoom.native
sha, stats = span.sha, span.stats
NAMES = ("normal", "wave", "checkerboard", "V only", "H only", "both quadrants", "character zoom")
EVENTS = zoom.EVENTS
ORDER = [(obj, mode) for obj in range(2) for mode in (6, 0, 1, 2, 3, 4, 5)] + [(0, 6)]


def pose(serial):
    return 0 if serial <= 0 else 1 + (serial - 1) % 48


class RawFrames:
    def __init__(self, payload, index, reference):
        if len(index) != 98 or len(reference) != 49000:
            raise AssertionError("Each object must contain blank0 and48complete source screens")
        self.offsets = [int.from_bytes(index[i:i + 2], "little") for i in range(0, 98, 2)]
        self.row_offsets = []
        cursor = 0
        for frame, offset in enumerate(self.offsets):
            if offset != cursor:
                raise AssertionError("Raw frame offset enters the middle of a row or skips data")
            screen, row_offsets = bytearray(1000), []
            for row in range(25):
                row_offsets.append(cursor - offset)
                if cursor + 2 > len(payload):
                    raise AssertionError("Truncated raw row header")
                x, count = payload[cursor:cursor + 2]
                cursor += 2
                if x > 40 or count > 40 - x or cursor + count > len(payload):
                    raise AssertionError("Raw span exceeds source row")
                screen[row * 40 + x:row * 40 + x + count] = payload[cursor:cursor + count]
                cursor += count
            if screen != reference[frame * 1000:(frame + 1) * 1000]:
                raise AssertionError("Raw span expansion differs from independent source screen")
            self.row_offsets.append(row_offsets)
        if cursor != len(payload) or reference[:1000] != bytes(1000):
            raise AssertionError("Raw payload tail or startup blank differs")


def expected_screen(obj, serial, mode, crop, ages, horizontal, vertical):
    reference, lookup = obj["reference"], obj["lookup"]
    frame = reference[pose(serial) * 1000:(pose(serial) + 1) * 1000]
    output = bytearray(1000)
    if mode <= 2:
        for y in range(25):
            a = pose(max(0, serial - ages[y * 48 + serial % 48])) if mode == 1 else pose(serial)
            b = pose(max(0, serial - 24))
            for x in range(40):
                chosen = b if mode == 2 and ((x >> 2) ^ (y >> 2)) & 1 else a
                output[y * 40 + x] = reference[chosen * 1000 + y * 40 + x]
    elif mode == 3:
        for y in range(12):
            for x in range(40):
                c = frame[y * 40 + x]
                output[y * 40 + x], output[(23 - y) * 40 + x] = c, vertical[c]
    elif mode == 4:
        for y in range(25):
            for x in range(20):
                c = frame[y * 40 + x]
                output[y * 40 + x], output[y * 40 + 39 - x] = c, horizontal[c]
    elif mode == 5:
        for y in range(12):
            for x in range(20):
                c = frame[y * 40 + x]
                h = horizontal[c]
                output[y * 40 + x], output[y * 40 + 39 - x] = c, h
                output[(23 - y) * 40 + x], output[(23 - y) * 40 + 39 - x] = vertical[c], vertical[h]
    elif mode == 6:
        cx, cy = crop
        if not 0 <= cx <= 20 or not 0 <= cy <= 13:
            raise AssertionError("Zoom crop exceeds the40x25 source")
        for y in range(12):
            for x in range(20):
                c = frame[(cy + y) * 40 + cx + x]
                quad = lookup[c * 4:c * 4 + 4]
                out = y * 80 + x * 2
                output[out:out + 2], output[out + 40:out + 42] = quad[:2], quad[2:]
    else:
        raise AssertionError("Unknown effect mode")
    return bytes(output)


def symbols(path):
    labels = {name: int(value, 16) for name, value in re.findall(r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", path.read_text())}
    required = set(EVENTS) | {"object_id", "next_object", "mode", "next_mode", "film_frame", "next_film_frame", "film_serial", "next_serial", "phase", "next_phase", "field_counter", "mode_started_field", "mode_fields_left", "mode_due", "front_screen_hi", "back_screen_hi", "font", "wave_ages", "cache_table_count", "cache_frame_ids", "row_cache", "zoom_x", "zoom_y", "latched_zoom_x", "latched_zoom_y", "active_zoom_x", "active_zoom_y"}
    if required - labels.keys() or len({labels[e] for e in EVENTS}) != len(EVENTS):
        raise AssertionError("Missing or aliased two-object lifecycle ABI: " + str(sorted(required - labels.keys())))
    return labels


def verify(build, vice, output, data_root):
    build, output, data_root = build.resolve(), output.resolve(), data_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((build / "build.json").read_text())
    lookahead = manifest["modeLookaheadFields"]
    if not 2 <= lookahead <= 25:
        raise AssertionError("Unexpected preparation lookahead for bounded phase clock injection")
    labels = symbols(build / "main.sym")
    font = (build / "font.bin").read_bytes()
    horizontal, vertical = [(build / (name + "-lut.bin")).read_bytes() for name in ("h", "v")]
    accepted = HERE / "three-scene/results/flagship-star-span-mirror-texture"
    for name in ("font.bin", "h-lut.bin", "v-lut.bin"):
        if (build / name).read_bytes() != (accepted / name).read_bytes():
            raise AssertionError("Locked font or corrected mirror maps changed")
    if sha(font) != span.LOCKED_FONT:
        raise AssertionError("Original font was regenerated")
    full_references = [(HERE / "three-scene/results/flagship-star-ten-buffer/reference.frames").read_bytes(), (data_root / "ball-full-reference.frames").read_bytes()]
    objects = []
    for index, item in enumerate(manifest["objects"]):
        obj = dict(item)
        obj["reference"] = (build / obj["referenceFile"]).read_bytes()
        obj["lookup"] = (build / obj["zoomLutFile"]).read_bytes()
        rows, offsets = (build / obj["rowsFile"]).read_bytes(), (build / obj["frameOffsetsFile"]).read_bytes()
        obj["rows"] = rows
        obj["oracle"] = RawFrames(rows, offsets, obj["reference"])
        original = full_references[index]
        wanted = bytes(1000) + b"".join(original[frame * 1000:(frame + 1) * 1000] for frame in range(1, 97, 2))
        if obj["reference"] != wanted or obj["lookup"] != (data_root / obj["name"] / "learned.lut").read_bytes():
            raise AssertionError("Object input differs from independent odd-pose reference/matched lookup")
        if len(obj["lookup"]) != 1024 or obj["lookup"][:4] != bytes(4) or len(obj["frameAddresses"]) != 49:
            raise AssertionError("Object lookup, blank or physical frame index differs")
        for quadrant, name in enumerate(("tl", "tr", "bl", "br")):
            if (build / (obj["name"] + "-zoom-" + name + ".bin")).read_bytes() != obj["lookup"][quadrant::4]:
                raise AssertionError("Runtime object/quadrant page differs from the matched empirical lookup")
        for frame, address in enumerate(obj["frameAddresses"]):
            logical_start = obj["oracle"].offsets[frame]
            logical_end = obj["oracle"].offsets[frame + 1] if frame < 48 else len(rows)
            end = address + logical_end - logical_start
            if not (0x5000 <= address < end <= 0xd000 or 0xe000 <= address < end <= 0xfffa):
                raise AssertionError("A physical source frame crosses I/O or the reserved interrupt vectors")
        objects.append(obj)
    if len(objects) != 2 or [obj["id"] for obj in objects] != [0, 1]:
        raise AssertionError("Expected star then checkerboard ball")
    regions = []
    for region in manifest["sourceRegions"]:
        content = (build / region["file"]).read_bytes()
        if len(content) != region["end"] - region["start"] or sha(content) != region["sha256"]:
            raise AssertionError("Immutable loaded region file/hash differs")
        if region["start"] < 0xe000 and region["end"] > 0xd000:
            raise AssertionError("Movie or lookup crosses the CPU I/O hole")
        regions.append({**region, "data": content})
    program = build / "player.prg"
    program_bytes = program.read_bytes()
    program_sha = sha(program_bytes)
    load_start = int.from_bytes(program_bytes[:2], "little")
    load_end = load_start + len(program_bytes) - 2
    if load_end > 0xd000:
        raise AssertionError("Hardware PRG load would enter the I/O gap; high movie must be staged below it")
    staged_regions = []
    for region in regions:
        if region["start"] >= 0xe000:
            staging = region.get("loadStart")
            if staging is None or not load_start <= staging < staging + len(region["data"]) <= load_end or program_bytes[2 + staging - load_start:2 + staging - load_start + len(region["data"])] != region["data"]:
                raise AssertionError("High movie is not present in a hardware-loadable low staging region")
            staged_regions.append({"file": region["file"], "loadStart": staging, "runtimeStart": region["start"], "bytes": len(region["data"])})
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0)); port = reservation.getsockname()[1]
    palette = HERE.parent.parent.parent / "palettes/colodore.vpl"
    command = [str(vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100", "+warp", "+autostart-warp", "+confirmonexit", "-sounddev", "dummy", "+refreshonbreak", "+binarymonitor", "-initbreak", "reset", "-autostartprgmode", "1", "-autostart", str(program), "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", str(palette), "-VICIIsaturation", "1000", "-VICIIcontrast", "1000", "-VICIIbrightness", "1000", "-VICIIgamma", "1000", "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    report = {"pass": False, "program_sha256": program_sha, "font_sha256": sha(font), "manifest": manifest, "command": command,
              "method": "Actual consecutive native PAL fields, forced refresh disabled. All48odd star poses and all48ball poses use independent references; every displayed image is checked. Explicit phase-timer injections skip waiting in previously accepted effects. The ball zoom runs its complete501physical fields; both object handoffs reset local source time to1.",
              "hardwareLoad": {"start": load_start, "endExclusive": load_end, "neverLoadsIoGap": True, "stagedHighRegions": staged_regions},
              "fields": [], "events": [], "commits": [], "modeStarts": [], "timerInjections": [], "cropPokes": [], "clears": [], "renders": [], "caches": []}
    screens, contents = [0x4800, 0x4c00], {0x4800: bytes(1024), 0x4c00: bytes(1024)}
    front, back = screens
    obj_id = serial = started_field = physical_fields = last_counter = phase_index = 0
    mode = 6
    active_crop = pending_crop = requested_crop = (10, 6)
    corners = [(0, 0), (20, 0), (0, 13), (20, 13), (10, 6)]
    corner_index = 0
    default_poses = [set(), set()]
    corner_scanouts, phase_images, injected_phases = set(), {}, set()
    ages = active_pixels = pending = work = None
    front_watch = None
    last_clock = None
    clear_clock = cache_clock = render_clock = commit_clock = None
    process = connection = monitor = None

    def word(ram, name):
        return int.from_bytes(ram[labels[name]:labels[name] + 2], "little")

    def screen(state, crop):
        o, t, m = state
        return expected_screen(objects[o], t, m, crop, ages, horizontal, vertical)

    def pixels(character_screen, selected_mode):
        return mirror.shifted_pixels(character_screen, font) if selected_mode in (3, 5, 6) else native.pixels_from_screen(character_screen, font)

    with (output / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            report["owned_pid"] = process.pid
            connection = native.connect(process, port); monitor = native.Monitor(connection)
            monitor.run("sidefx off")
            for resource, value in (("MachineVideoStandard", 1), ("Speed", 100), ("InitialWarpMode", 0), ("AutostartWarp", 0), ("RefreshOnBreak", 0)):
                if f"{resource}={value}" not in monitor.run(f'resourceget "{resource}"'):
                    raise AssertionError("Unexpected VICE resource")
            initial = monitor.checkpoint(labels["presented"]); monitor.run("x")
            if monitor.registers()["pc"] != labels["presented"]:
                raise AssertionError("Initial star zoom not reached")
            monitor.run(f"delete {initial}")
            for event in EVENTS: monitor.checkpoint(labels[event])
            span.store_checkpoint(monitor, 0x4000, 0x4800)
            for region in regions: span.store_checkpoint(monitor, region["start"], region["end"])

            def read_state():
                monitor.run("bank ram"); ram = monitor.dump(output / "last-ram.bin", 0, 65535)
                monitor.run("bank io"); vic = monitor.dump(output / "last-vic.bin", 0xd000, 0xd03f)
                cia = monitor.dump(output / "last-cia.bin", 0xdd00, 0xdd02)
                colors = monitor.dump(output / "last-colors.bin", 0xd800, 0xdbff)
                monitor.run("bank cpu")
                if ram[0x4000:0x4800] != font or any(ram[r["start"]:r["end"]] != r["data"] for r in regions):
                    raise AssertionError("Immutable font, object movie, frame index or lookup changed")
                control = 0x1f if mode in (3, 5, 6) else 0x1b
                if registers_now["cpu_port"] != 0x35 or cia[0] & 3 != 2 or cia[2] & 3 != 3 or vic[0x11] & 0x7f != control or vic[0x16] & 0x1f != 8 or vic[0x15] or vic[0x18] & 0xfe != (0x20 if front == 0x4800 else 0x30):
                    raise AssertionError("Wrong source RAM bank or mode-specific display geometry")
                if vic[0x20] & 15 or vic[0x21] & 15 or any(c & 15 != 1 for c in colors):
                    raise AssertionError("Unexpected display colors")
                if (ram[labels["object_id"]], word(ram, "film_serial"), ram[labels["mode"]]) != (obj_id, serial, mode) or ram[labels["film_frame"]] != pose(serial) or ram[labels["phase"]] != serial % 48:
                    raise AssertionError("Active object or local history changed before atomic commit")
                if word(ram, "mode_started_field") != started_field or ram[labels["front_screen_hi"]] << 8 != front or ram[labels["back_screen_hi"]] << 8 != back:
                    raise AssertionError("Published timer or output pointer changed before commit")
                if mode == 6 and (ram[labels["active_zoom_x"]], ram[labels["active_zoom_y"]]) != active_crop:
                    raise AssertionError("Published zoom offset changed before commit")
                if ages is not None and ram[labels["wave_ages"]:labels["wave_ages"] + 1200] != ages:
                    raise AssertionError("48-phase wave table changed")
                for address in screens:
                    if address == back and work: continue
                    if ram[address:address + 1024] != contents[address]:
                        raise AssertionError("Complete character output differs from independent object reference")
                return ram

            def check_pending(ram):
                candidate = (ram[labels["next_object"]], word(ram, "next_serial"), ram[labels["next_mode"]])
                new_object = obj_id ^ 1 if mode == 5 and candidate[2] == 6 else obj_id
                new_serial = 1 if new_object != obj_id else serial + 1
                if candidate != (new_object, new_serial, candidate[2]) or candidate[2] not in (mode, (mode + 1) % 7) or ram[labels["next_film_frame"]] != pose(new_serial) or ram[labels["next_phase"]] != new_serial % 48:
                    raise AssertionError("Pending object,48-pose source clock or history reset differs")
                return candidate

            def check_cache(ram):
                o, t, m = pending
                if m > 2: return
                count = ram[labels["cache_table_count"]]
                if count != {0: 1, 1: 10, 2: 2}[m]:
                    raise AssertionError("Shared row cache has wrong table count")
                cached = set()
                for slot in range(count):
                    frame = ram[labels["cache_frame_ids"] + slot]; cached.add(frame)
                    if frame > 48: raise AssertionError("Cache frame exceeds object source")
                    for row in range(25):
                        address = labels["row_cache"] + slot * 50 + row * 2
                        pointer = int.from_bytes(ram[address:address + 2], "little")
                        expected = objects[o]["frameAddresses"][frame] + objects[o]["oracle"].row_offsets[frame][row]
                        if pointer != expected: raise AssertionError("Cache points to another object or crosses physical source split")
                needed = {pose(t)}
                if m == 1: needed = {pose(max(0, t - ages[row * 48 + t % 48])) for row in range(25)}
                elif m == 2: needed.add(pose(max(0, t - 24)))
                if not needed.issubset(cached): raise AssertionError("Object cache omitted selected history frame")

            first = True
            while True:
                if not first: monitor.run("x")
                first = False; registers_now = span.registers(monitor)
                event = next((e for e in EVENTS if labels[e] == registers_now["pc"]), None)
                if event is None: raise AssertionError("Unexpected immutable/front write checkpoint")
                report["events"].append({"event": event, "object": obj_id, "mode": mode, "serial": serial, **registers_now})
                if event == "presented":
                    ram = read_state()
                    if ages is None:
                        for obj in objects:
                            for frame, address in enumerate(obj["frameAddresses"]):
                                start = obj["oracle"].offsets[frame]
                                end = obj["oracle"].offsets[frame + 1] if frame < 48 else len(obj["rows"])
                                if ram[address:address + end - start] != obj["rows"][start:end]:
                                    raise AssertionError("Boot did not install the complete low/high source frame at its physical address")
                        report["hardwareLoad"]["all98RuntimeFramesMatchAfterNativeBoot"] = True
                        ages = ram[labels["wave_ages"]:labels["wave_ages"] + 1200]
                        for row in range(25):
                            for phase in range(48):
                                ideal = 4.5 + 4.5 * math.sin(2 * math.pi * (row / 24 + phase / 48))
                                if not 0 <= ages[row * 48 + phase] <= 9 or abs(ages[row * 48 + phase] - ideal) > .500000000001:
                                    raise AssertionError("Wave does not use independent48-phase sinusoid")
                        active_pixels = pixels(screen((0, 0, 6), active_crop), 6)
                        report["modeStarts"].append({"object": 0, "mode": 6, "field": 0, "counter": 0, "serial": 0})
                    if front_watch is not None: monitor.run(f"delete {front_watch}")
                    front_watch = span.store_checkpoint(monitor, front, front + 1024)
                    if obj_id == 1 and mode == 6 and len(default_poses[1]) == 48 and corner_index < len(corners):
                        requested_crop = corners[corner_index]
                        for name, value in zip(("zoom_x", "zoom_y"), requested_crop): monitor.run(f"> ${labels[name]:04x} ${value:02x}")
                        report["cropPokes"].append({"field": physical_fields, "crop": list(requested_crop)})
                        corner_index += 1
                    ready = len(default_poses[0]) == 48 if phase_index == 0 else len(phase_images.get(phase_index, set())) >= 3
                    if phase_index < 14 and not (obj_id == 1 and mode == 6) and ready and phase_index not in injected_phases:
                        counter = word(ram, "field_counter")
                        started_field = (counter - (501 - lookahead)) & 0xffff
                        for name, value in (("mode_fields_left", lookahead), ("mode_started_field", started_field)):
                            monitor.run(f"> ${labels[name]:04x} ${value & 255:02x} ${value >> 8:02x}")
                        monitor.run(f"> ${labels['mode_due']:04x} $00")
                        injected_phases.add(phase_index)
                        report["timerInjections"].append({"phase": phase_index, "object": obj_id, "mode": mode, "actualField": physical_fields, "fieldCounter": counter, "newStartedField": started_field, "fieldsRemaining": lookahead, "sourceClockUnmodified": True})
                elif event in ("clear_start", "cache_start"):
                    ram = read_state(); pending = check_pending(ram)
                    if event == "clear_start": clear_clock, work = registers_now["clock"], "clear"
                    else: cache_clock = registers_now["clock"]
                elif event == "clear_end":
                    contents[back] = bytes(1024); work = None; read_state()
                    report["clears"].append({"wallCycles": registers_now["clock"] - clear_clock, "all1024Zero": True})
                elif event == "cache_end":
                    ram = read_state(); check_cache(ram)
                    report["caches"].append({"object": pending[0], "mode": pending[2], "wallCycles": registers_now["clock"] - cache_clock})
                elif event == "render_start": read_state(); render_clock, work = registers_now["clock"], "render"
                elif event == "zoom_render_start":
                    ram = read_state(); pending_crop = (ram[labels["latched_zoom_x"]], ram[labels["latched_zoom_y"]])
                    if pending_crop != requested_crop: raise AssertionError("Pending zoom offset differs from requested keyboard state")
                elif event == "render_end":
                    contents[back] = screen(pending, pending_crop) + bytes(24); work = None; read_state()
                    report["renders"].append({"object": pending[0], "mode": pending[2], "serial": pending[1], "wallCycles": registers_now["clock"] - render_clock})
                elif event == "field_complete":
                    ram = read_state(); counter = word(ram, "field_counter")
                    if counter != (last_counter + 1) & 0xffff or not 256 <= registers_now["raster"] <= 258:
                        raise AssertionError("Native field counter missed a completed field")
                    if last_clock is not None and abs(registers_now["clock"] - last_clock - native.PAL_FRAME_CYCLES) > 126:
                        raise AssertionError("Actual scanouts are not consecutive")
                    physical_fields += 1; last_counter, last_clock = counter, registers_now["clock"]
                    elapsed = (counter - started_field) & 0xffff
                    if elapsed > 501 or word(ram, "mode_fields_left") != max(0, 501 - elapsed) or bool(ram[labels["mode_due"]]) != (elapsed >= 501):
                        raise AssertionError("Mode missed its501-field timer after declared clock adjustment")
                    picture = output / f"field-{physical_fields:04d}-object-{obj_id}-mode-{mode}-serial-{serial:04d}.png"
                    monitor.run(f'scrsh "{picture}" 2'); comparison = span.actual_image(picture, active_pixels)
                    if mode in (3, 5, 6):
                        image = Image.open(picture).convert("L").crop((32, 35, 352, 235))
                        if image.crop((0, 0, 320, 4)).getbbox() or image.crop((0, 196, 320, 200)).getbbox(): raise AssertionError("Centered mode lost4-pixel margins")
                    report["fields"].append({"field": physical_fields, "counter": counter, "phase": phase_index, "object": obj_id, "mode": mode, "serial": serial, "pose": pose(serial), "originalPose": 0 if serial == 0 else 1 + 2 * (pose(serial) - 1), "crop": list(active_crop) if mode == 6 else None, "clock": registers_now["clock"], "screenshot": picture.name, "comparison": comparison})
                    phase_images.setdefault(phase_index, set()).add(serial)
                    if mode == 6 and active_crop == (10, 6) and serial: default_poses[obj_id].add(pose(serial))
                    if obj_id == 1 and mode == 6 and active_crop in corners[:4]: corner_scanouts.add(active_crop)
                    if physical_fields % 100 == 0: print(json.dumps({"actualFields": physical_fields, "object": obj_id, "mode": mode, "phase": phase_index, "starZoomPoses": len(default_poses[0]), "ballZoomPoses": len(default_poses[1])}), flush=True)
                    if phase_index == 14 and len(phase_images[14]) >= 3: break
                    if physical_fields > 1000: raise AssertionError("Focused two-object proof exceeded1000actual fields")
                elif event == "commit_start":
                    ram = read_state()
                    if work or contents[back] != screen(pending, pending_crop) + bytes(24): raise AssertionError("Attempted to present incomplete hidden object")
                    if registers_now["raster"] < 256 and registers_now["raster"] >= 50: raise AssertionError("Publication started during visible scanout")
                    if pending[2] != mode and ((word(ram, "field_counter") - started_field) & 0xffff) != 501: raise AssertionError("Effect/object switch missed timer deadline")
                    commit_clock = registers_now["clock"]
                elif event == "commit_end":
                    changed = pending[2] != mode
                    obj_id, serial, mode = pending; front, back = back, front
                    if mode == 6: active_crop = pending_crop
                    if changed:
                        phase_index += 1; started_field = last_counter
                        if (obj_id, mode) != ORDER[phase_index]: raise AssertionError("Object/effect order differs from14-phase script")
                    read_state(); active_pixels = pixels(contents[front][:1000], mode)
                    if registers_now["raster"] < 256 and registers_now["raster"] >= 50: raise AssertionError("Publication ended during visible scanout")
                    if changed: report["modeStarts"].append({"object": obj_id, "mode": mode, "field": physical_fields, "counter": last_counter, "serial": serial})
                    report["commits"].append({"object": obj_id, "mode": mode, "serial": serial, "field": physical_fields, "wallCycles": registers_now["clock"] - commit_clock})
            if sha(program.read_bytes()) != program_sha: raise AssertionError("PRG changed during native proof")
            starts = report["modeStarts"]
            if [(s["object"], s["mode"]) for s in starts] != ORDER or default_poses != [set(range(1, 49)), set(range(1, 49))] or corner_scanouts != set(corners[:4]): raise AssertionError("Object/pose/corner coverage incomplete")
            if starts[8]["field"] - starts[7]["field"] != 501 or 7 in injected_phases: raise AssertionError("Ball zoom did not run501actual fields without clock injection")
            required_high_frames = {(obj["id"], frame) for obj in objects for frame, address in enumerate(obj["frameAddresses"]) if address >= 0xe000}
            rendered_high_frames = {(f["object"], f["pose"]) for f in report["fields"] if objects[f["object"]]["frameAddresses"][f["pose"]] >= 0xe000}
            if not required_high_frames.issubset(rendered_high_frames): raise AssertionError("Relocated high-memory source frames were not all exercised by native scanout")
            report["hardwareLoad"]["highFramesRenderedNatively"] = [list(frame) for frame in sorted(rendered_high_frames)]
            switches = [s for i, s in enumerate(starts[1:], 1) if s["object"] != starts[i - 1]["object"]]
            if len(switches) != 2 or any(s["serial"] != 1 for s in switches): raise AssertionError("Object handoff did not reset local history to1 in both directions")
            residence = {}
            for field in report["fields"]:
                key = (field["phase"], field["serial"]); residence[key] = residence.get(key, 0) + 1
            ball_images = len(phase_images[7])
            report.update({"pass": True, "actualVisibleFieldsVerified": physical_fields, "objectHandoffsVerified": switches, "actualPhaseOrder": [list(pair) for pair in ORDER], "defaultZoomPoses": [sorted(p) for p in default_poses], "ballCornerScanouts": [list(c) for c in sorted(corner_scanouts)], "allActualScanoutsMatch": True, "frontFontSourceAndLookupWrites": 0, "forcedRefresh": False, "ballZoomFields": 501, "ballZoomSeconds": 501 * native.PAL_FRAME_CYCLES / native.PAL_CLOCK, "ballZoomImages": ball_images, "ballZoomFpsIncludingHolds": ball_images / (501 * native.PAL_FRAME_CYCLES / native.PAL_CLOCK), "sampledModeImages": {str(p): len(images) for p, images in phase_images.items()}, "imageFieldResidenceHistogram": {str(n): sum(count == n for count in residence.values()) for n in sorted(set(residence.values()))}, "maximumHeldVisibleFields": max(residence.values()), "clearWallCycles": stats([r["wallCycles"] for r in report["clears"]]), "cacheWallCycles": stats([r["wallCycles"] for r in report["caches"]]), "renderWallCycles": stats([r["wallCycles"] for r in report["renders"]]), "physicalKeyboardInjection": False, "scope": "Focused bounded proof, with explicit timer injections. All displayed fields are real; source clocks/object identifiers were never injected. Full14-phase501-field script timing belongs to host proof; only ball zoom is naturally timed in this run."})
        except BaseException as error:
            report["error"] = repr(error); raise
        finally:
            if monitor: (output / "monitor.log").write_text("\n".join(monitor.transcript))
            if connection:
                try: connection.sendall(b"quit\n")
                except OSError: pass
                connection.close()
            if process and process.poll() is None:
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
            (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("manifest", "command", "fields", "events", "commits", "clears", "renders", "caches")}, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=HERE / "build/three-scene-star-ball-player")
    parser.add_argument("--data", type=Path, default=HERE / "build/three-scene-star-ball-data")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    args = parser.parse_args(); verify(args.build, args.vice, args.output or args.build / "pal-proof", args.data)


if __name__ == "__main__": main()
