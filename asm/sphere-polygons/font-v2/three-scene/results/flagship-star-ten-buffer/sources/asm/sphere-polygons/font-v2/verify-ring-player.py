#!/usr/bin/env python3
"""Verify ten-screen ring playback at the actual native PAL VIC boundary.

This owns the ring lifecycle contract: copy the complete latest screen, change
only the hidden target, preserve the locked font/movie, and show every frame in
the correct VIC bank. It deliberately does not reuse the single-screen proof's
fixed $0400 screen, $2000 charset, or assumed two-field timing.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import statistics
import subprocess

from PIL import Image, ImageChops

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ring_native_monitor", HERE.parent / "verify-c64.py")
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)
LOCKED_FONT = "1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1"
EVENTS = ("presented", "frame_done", "copy_start", "copy_end", "render_start", "render_end", "held_frame_done")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def stats(values):
    return {"min": min(values), "mean": statistics.mean(values), "max": max(values)} if values else None


def symbols(path):
    labels = {name: int(address, 16) for name, address in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", path.read_text())}
    required = set(EVENTS) | {"presentation_start", "frame_index", "frame_counter", "front_index", "back_index",
                              "front_screen_hi", "back_screen_hi", "next_frame", "font", "animation", "animation_end",
                              "source_ptr", "literal_destination", "plays_left", "images_left", "script_cursor"}
    if required - labels.keys():
        raise AssertionError("Missing ring ABI labels: " + str(sorted(required - labels.keys())))
    if len({labels[event] for event in EVENTS}) != len(EVENTS):
        raise AssertionError("Ring lifecycle checkpoints must be distinct")
    return labels


def timeline_for(manifest, repetitions):
    timeline, cursor = [], 0
    for command in manifest["playback"]["commands"]:
        if command["op"] == "hold":
            break
        cursor += 5
        infinite = command["repeat"] == "forever"
        repeats = repetitions if infinite else command["repeat"]
        for iteration in range(repeats):
            for offset in range(command["frameCount"]):
                timeline.append({"pose": command["startFrame"] + offset,
                                 "plays_left": 0 if infinite else repeats - iteration,
                                 "images_left": command["frameCount"] - offset,
                                 "script_cursor": cursor})
    if [item["pose"] for item in timeline[:manifest["storedFrames"]]] != list(range(manifest["storedFrames"])):
        raise AssertionError("Native corpus must initially present every stored screen in order")
    return timeline


def checkpoint_store(monitor, start, end):
    response = monitor.run(f"break store {start:04x} {end - 1:04x}")
    match = re.search(r"(?:BREAK|WATCH):\s*(\d+)", response)
    if not match:
        raise RuntimeError("VICE did not install a memory-write checkpoint: " + response)
    return int(match[1])


def full_registers(monitor):
    response = monitor.run("r")
    match = re.search(r"^\.;([0-9a-fA-F]{4})\s+(.*)$", response, re.M)
    if not match:
        raise RuntimeError("Incomplete native register response")
    fields = match[2].split()
    return {"pc": int(match[1], 16), "a": int(fields[0], 16), "x": int(fields[1], 16),
            "y": int(fields[2], 16), "cpu_port": int(fields[5], 16), "raster": int(fields[-3]),
            "raster_cycle": int(fields[-2]), "clock": int(fields[-1])}


def actual_image(path, expected):
    active = Image.open(path).convert("RGB").crop((32, 35, 352, 235))
    target = Image.frombytes("L", (320, 200), expected).convert("RGB")
    if ImageChops.difference(active, target).getbbox():
        raise AssertionError("Actual VIC scanout differs from the reference decoded with the locked font: " + path.name)
    return {"origin": [32, 35], "comparedPixels": 64000, "differentPixels": 0}


def verify(build, vice, output, repetitions=3):
    build, output = build.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((build / "build.json").read_text())
    labels = symbols(build / "main.sym")
    font, movie = (build / "font.bin").read_bytes(), (build / "movie.bin").read_bytes()
    raw = (build / "reference.frames").read_bytes()
    if len(font) != 2048 or sha(font) != LOCKED_FONT:
        raise AssertionError("This proof requires the unchanged locked 256-character font")
    screens = manifest["addresses"]["screens"]
    if screens != list(range(0x4800, 0x7000, 1024)) or labels["font"] != 0x4000:
        raise AssertionError("Unexpected ten-buffer VIC-bank-one layout")
    if labels["animation"] != 0x8000 or labels["animation_end"] != 0x8000 + len(movie):
        raise AssertionError("Movie range does not match immutable movie.bin")
    if sha(movie) != manifest["hashes"]["movie"] or sha(raw) != manifest["hashes"]["reference"]:
        raise AssertionError("Native movie/reference hash mismatch")
    count = manifest["storedFrames"]
    if len(raw) != count * 1000:
        raise AssertionError("Expected exactly 1000 characters per stored screen")
    reference = [raw[index * 1000:(index + 1) * 1000] for index in range(count)]
    pixels = [native.pixels_from_screen(screen, font) for screen in reference]
    timeline = timeline_for(manifest, repetitions)
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
               "-VICIIsaturation", "1000", "-VICIIcontrast", "1000",
               "-VICIIbrightness", "1000", "-VICIIgamma", "1000",
               "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    report = {"pass": False, "program_sha256": program_sha, "font_sha256": sha(font), "movie_sha256": sha(movie),
              "reference_sha256": sha(raw), "manifest": manifest, "command": command,
              "method": "Owned, unmodified native PAL VICE; forced refresh disabled. Actual completed VIC scanouts, hardware bank/slot, full 1024-byte copies, hidden writes, all ring buffers, source immutability and script counters are checked. Memory write checkpoints guard front/font/movie during native execution.",
              "events": [], "frames": [], "fields": [], "copies": [], "decodes": []}
    process = connection = monitor = None
    ring = [bytes(1024) for _ in screens]
    occurrence, displayed = -1, None
    copy_clock = render_clock = None
    front_watch = None
    phase = None
    last_presented_clock = None
    last_field_clock = None
    source_start, source_end = labels["animation"], labels["animation_end"]
    guard_baseline = None

    with (output / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
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
                raise AssertionError("Initial presentation checkpoint was not reached")
            monitor.run(f"delete {initial}")
            for event in EVENTS:
                monitor.checkpoint(labels[event])
            checkpoint_store(monitor, labels["font"], labels["font"] + len(font))
            checkpoint_store(monitor, source_start, source_end)

            def read_state():
                nonlocal guard_baseline
                monitor.run("bank ram")
                ram = monitor.dump(output / "last-ram.bin", 0, 65535)
                monitor.run("bank io")
                vic = monitor.dump(output / "last-vic.bin", 0xd000, 0xd03f)
                cia = monitor.dump(output / "last-cia.bin", 0xdd00, 0xdd02)
                colors = monitor.dump(output / "last-colors.bin", 0xd800, 0xdbff)
                monitor.run("bank cpu")
                if ram[0x4000:0x4800] != font or ram[source_start:source_end] != movie:
                    raise AssertionError("Immutable font or movie changed")
                guards = ram[0x7000:0x8000] + ram[source_end:0xd000]
                if guard_baseline is None:
                    guard_baseline = guards
                if guards != guard_baseline:
                    raise AssertionError("A write escaped the screen/movie allocations")
                # Bank "ram" exposes backing bytes at $00/$01, rather than
                # the 6510 port; the register response carries the real port.
                if registers["cpu_port"] != 0x35 or cia[0] & 3 != 2 or cia[2] & 3 != 3:
                    raise AssertionError("Unexpected CPU memory mapping or VIC bank")
                if vic[0x11] & 0x7f != 0x1b or vic[0x16] & 0x1f != 8 or vic[0x15]:
                    raise AssertionError("Unexpected text mode or enabled sprites")
                if vic[0x20] & 15 or vic[0x21] & 15 or any(value & 15 != 1 for value in colors):
                    raise AssertionError("Unexpected border, background or shared color RAM")
                front, back = ram[labels["front_index"]], ram[labels["back_index"]]
                if front >= 10 or back >= 10 or ram[labels["front_screen_hi"]] != screens[front] >> 8:
                    raise AssertionError("Native front ring state is inconsistent")
                if vic[0x18] & 0xfe != 0x20 + front * 0x10:
                    raise AssertionError("D018 does not select the tracked front slot and locked font")
                for index, address in enumerate(screens):
                    if ram[address:address + 1024] != ring[index]:
                        raise AssertionError(f"Slot {index} contents differ during {phase}, occurrence {occurrence}")
                return ram, front, back

            def capture_field(registers, event, ram, front):
                nonlocal last_field_clock
                if not 256 <= registers["raster"] <= 257:
                    raise AssertionError("Completed VIC field checkpoint is outside the lower border")
                if last_field_clock is not None:
                    interval = registers["clock"] - last_field_clock
                    # This certifies every actual field only when none were
                    # skipped between the two real scanout checkpoints.
                    if abs(interval - native.PAL_FRAME_CYCLES) > 126:
                        raise AssertionError(f"An intermediate visible field needs separate certification: {interval} clocks")
                last_field_clock = registers["clock"]
                pose = timeline[occurrence]["pose"]
                path = output / f"image-{occurrence:03d}-pose-{pose:03d}-{event}.png"
                monitor.run(f'scrsh "{path}" 2')
                comparison = actual_image(path, pixels[pose])
                record = {"occurrence": occurrence, "pose": pose, "slot": front, "event": event,
                          "clock": registers["clock"], "screenshot": path.name, "comparison": comparison}
                report["fields"].append(record)
                return record

            first_event = True
            while True:
                if not first_event:
                    monitor.run("x")
                first_event = False
                registers = full_registers(monitor)
                event = next((event for event in EVENTS if labels[event] == registers["pc"]), None)
                if event is None:
                    raise AssertionError(f"Unexpected memory write or execution breakpoint at ${registers['pc']:04x}")
                phase = event
                report["events"].append({"event": event, "occurrence": occurrence, **registers})
                if event == "presented":
                    occurrence += 1
                    displayed = timeline[occurrence]["pose"]
                    ram, front, back = read_state()
                    if front != occurrence % 10 or ram[labels["frame_index"]] != displayed:
                        raise AssertionError("Displayed frame index or independent ten-slot ring order differs")
                    if ring[front] != reference[displayed] + bytes(24):
                        raise AssertionError("Presented full screen differs from reference + 24 initialized spare bytes")
                    if not 256 <= registers["raster"] <= 257:
                        raise AssertionError("VIC screen switch was outside the lower border")
                    if front_watch is not None:
                        monitor.run(f"delete {front_watch}")
                    front_watch = checkpoint_store(monitor, screens[front], screens[front] + 1024)
                    if last_presented_clock is not None:
                        report["frames"][-1]["presentationCycles"] = registers["clock"] - last_presented_clock
                    last_presented_clock = registers["clock"]
                elif event == "copy_start":
                    ram, front, back = read_state()
                    if back != (front + 1) % 10 or ram[labels["back_screen_hi"]] != screens[back] >> 8:
                        raise AssertionError("Next target is not the following independent ring slot")
                    if ram[labels["frame_index"]] != displayed:
                        raise AssertionError("Visible frame index changed before the flip")
                    copy_clock = registers["clock"]
                elif event == "copy_end":
                    # Independently expect a complete copy, including the 24
                    # spare bytes; the old target's t-10 image is irrelevant.
                    back = (occurrence + 1) % 10
                    ring[back] = ring[occurrence % 10]
                    ram, front, actual_back = read_state()
                    if actual_back != back or front == back:
                        raise AssertionError("Copy changed or selected the front buffer")
                    report["copies"].append({"occurrence": occurrence, "sourceSlot": front, "targetSlot": back,
                                              "bytes": 1024, "wallCycles": registers["clock"] - copy_clock,
                                              "all1024BytesMatchPriorFront": True})
                elif event == "render_start":
                    read_state()
                    render_clock = registers["clock"]
                elif event == "render_end":
                    target = timeline[occurrence + 1]["pose"] if occurrence + 1 < len(timeline) else manifest["loop"]["startFrame"]
                    back = (occurrence + 1) % 10
                    ring[back] = reference[target] + bytes(24)
                    ram, front, actual_back = read_state()
                    if ram[labels["frame_index"]] != displayed or ram[labels["next_frame"]] != target:
                        raise AssertionError("Outgoing delta or pending frame state differs")
                    destination = int.from_bytes(ram[labels["literal_destination"]:labels["literal_destination"] + 2], "little")
                    source = int.from_bytes(ram[labels["source_ptr"]:labels["source_ptr"] + 2], "little") + registers["y"]
                    patch = manifest["sourcePatches"][displayed]
                    if destination != screens[back] + 1000 or source != patch["address"] + patch["bytes"]:
                        raise AssertionError("Native outgoing source/destination cursors violate the literal codec ABI")
                    report["decodes"].append({"occurrence": occurrence, "fromPose": displayed, "targetPose": target,
                                               "wallCycles": registers["clock"] - render_clock, "nativeScreenMatches": True,
                                               "consumedSourceEnd": source, "destinationEnd": destination, "codecCursorsMatch": True})
                elif event == "frame_done":
                    ram, front, back = read_state()
                    counter = int.from_bytes(ram[labels["frame_counter"]:labels["frame_counter"] + 2], "little")
                    if counter != occurrence + 1 or ram[labels["frame_index"]] != displayed:
                        raise AssertionError("Presented image counter differs")
                    expected = timeline[occurrence]
                    for name in ("plays_left", "images_left", "script_cursor"):
                        width = 2 if name == "plays_left" else 1
                        if name not in labels or int.from_bytes(ram[labels[name]:labels[name] + width], "little") != expected[name]:
                            raise AssertionError("Script counter mismatch for " + name)
                    field = capture_field(registers, event, ram, front)
                    report["frames"].append({**field, "fullScreenBytes": 1024, "screenMatch": True, "scriptCountersMatch": True})
                    if (occurrence + 1) % 32 == 0:
                        print(json.dumps({"ringNativeImagesVerified": occurrence + 1, "visibleFields": len(report["fields"])}), flush=True)
                elif event == "held_frame_done":
                    ram, front, back = read_state()
                    if ram[labels["frame_index"]] != displayed:
                        raise AssertionError("Front/pose changed before the old frame's last scanout")
                    capture_field(registers, event, ram, front)
                    if occurrence + 1 == len(timeline):
                        break
            if sha(program.read_bytes()) != program_sha:
                raise AssertionError("Native program changed during verification")
            intervals = [item["presentationCycles"] for item in report["frames"] if "presentationCycles" in item]
            wraps = sum(a["pose"] == count - 1 and b["pose"] == manifest["loop"]["startFrame"] for a, b in zip(timeline, timeline[1:]))
            report.update({"pass": True, "displayedImagesVerified": len(timeline), "uniqueSourceFramesVerified": len(set(row["pose"] for row in timeline)),
                           "actualVisibleFieldsVerified": len(report["fields"]), "filmWrapsVerified": wraps,
                           "ringWrapsVerified": (len(timeline) - 1) // 10, "allTenSlotsUsed": sorted(set(row["slot"] for row in report["frames"])) == list(range(10)),
                           "allFullCopiesMatch": True, "allActualScanoutsMatch": True,
                           "frontWritesDuringCopyDecode": 0, "immutableFontMovieWrites": 0,
                           "copyWallCycles": stats([row["wallCycles"] for row in report["copies"]]),
                           "decodeWallCycles": stats([row["wallCycles"] for row in report["decodes"]]),
                           "presentationCycles": stats(intervals), "meanFps": native.PAL_CLOCK / statistics.mean(intervals),
                           "observedFieldsPerImage": sorted({round(value / native.PAL_FRAME_CYCLES) for value in intervals}),
                           "forcedRefresh": False, "sampledLoopRepetitions": repetitions,
                           "scope": "Complete native10-buffer player with no music/interrupt workload. Every completed visible field in the bounded loop sample was independently compared; no skipped intermediate fields are accepted."})
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
    print(json.dumps({key: value for key, value in report.items() if key not in ("events", "frames", "fields", "copies", "decodes", "manifest", "command")}, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=HERE / "build/three-scene-flagship-star-ring/ring-10")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    parser.add_argument("--repetitions", type=int, default=3, choices=range(1, 5))
    args = parser.parse_args()
    verify(args.build, args.vice, args.output or args.build / "pal-proof", args.repetitions)


if __name__ == "__main__":
    main()
