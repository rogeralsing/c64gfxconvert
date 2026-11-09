#!/usr/bin/env python3
"""Measure native large-ball delta playback and verify real VIC scanout."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import statistics
import subprocess

from PIL import Image


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
SPEC = importlib.util.spec_from_file_location("large_delta_monitor", BASE / "verify-c64.py")
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def movie_source_regions(build, manifest, labels, movie):
    """Validate all immutable payload bytes and their physical RAM locations."""
    expected_hash = manifest.get("hashes", {}).get("movie")
    if expected_hash is not None and sha(movie) != expected_hash:
        raise AssertionError("Logical movie file does not match its build hash")
    declared = manifest.get("sourceRegions")
    if not declared:
        if manifest.get("pooledPayload"):
            raise AssertionError("Pooled movie is missing its source regions")
        start, end = labels["animation"], labels["animation_end"]
        if not 0 <= start < end <= 65536 or end - start != len(movie):
            raise AssertionError("Contiguous movie source range differs from movie.bin")
        return [{"start": start, "end": end, "file": "movie.bin",
                 "sha256": sha(movie), "data": movie}]

    if not expected_hash:
        raise AssertionError("Segmented source needs the complete logical movie hash")
    regions = []
    for item in declared:
        start, end = item["start"], item["end"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= 65536:
            raise AssertionError("Invalid immutable source region bounds")
        data = (build / item["file"]).read_bytes()
        if len(data) != end - start or sha(data) != item["sha256"]:
            raise AssertionError("Immutable region file/size/hash mismatch: " + item["file"])
        regions.append({"start": start, "end": end, "file": item["file"],
                        "sha256": item["sha256"], "data": data})
    regions.sort(key=lambda item: item["start"])
    for previous, current in zip(regions, regions[1:]):
        if previous["end"] > current["start"]:
            raise AssertionError("Immutable movie regions overlap in RAM")

    patches = manifest.get("sourcePatches")
    if not isinstance(patches, list) or not patches:
        raise AssertionError("Segmented source is missing its logical patch mapping")
    logical = []
    physical = [[] for _ in regions]
    reconstructed = bytearray(len(movie))
    for item in patches:
        offset, size, address = item["offset"], item["bytes"], item["address"]
        if any(type(value) is not int for value in (offset, size, address)) or size <= 0:
            raise AssertionError("Invalid source patch offset/length/address")
        if not 0 <= offset < offset + size <= len(movie):
            raise AssertionError("Source patch exceeds the logical movie")
        owners = [index for index, region in enumerate(regions)
                  if region["start"] <= address and address + size <= region["end"]]
        if len(owners) != 1:
            raise AssertionError("A source patch crosses or misses a physical region")
        owner = owners[0]
        region = regions[owner]
        local = address - region["start"]
        data = region["data"][local:local + size]
        if data != movie[offset:offset + size]:
            raise AssertionError("Relocated source patch differs from the logical movie")
        reconstructed[offset:offset + size] = data
        logical.append((offset, offset + size))
        physical[owner].append((address, address + size))

    def exact_cover(intervals, start, end, label):
        cursor = start
        for left, right in sorted(intervals):
            if left != cursor:
                raise AssertionError(label + " has omitted or overlapping bytes")
            cursor = right
        if cursor != end:
            raise AssertionError(label + " does not cover all source bytes")

    exact_cover(logical, 0, len(movie), "Logical patch mapping")
    for region, intervals in zip(regions, physical):
        exact_cover(intervals, region["start"], region["end"], "Physical pool " + region["file"])
    if bytes(reconstructed) != movie or sha(reconstructed) != expected_hash:
        raise AssertionError("All physical pools do not reconstruct the exact logical movie")
    if sum(len(region["data"]) for region in regions) != len(movie):
        raise AssertionError("Physical/logical movie byte totals differ")
    return regions


def immutable_source_report(regions):
    return [{key: value for key, value in region.items() if key != "data"} for region in regions]


def assert_movie_source(ram, regions):
    for region in regions:
        if ram[region["start"]:region["end"]] != region["data"]:
            raise AssertionError(f"Immutable movie source changed in {region['file']} "
                                 f"[${region['start']:04x},${region['end']:04x})")


def stats(values):
    return {"min": min(values), "mean": statistics.mean(values), "max": max(values)} if values else None


def probe_intermediate_field(build, command, labels, origin):
    """Stop unmodified native code at the end of its first visible update field."""
    output = build / "intermediate-field-probe"
    output.mkdir(exist_ok=True)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    command = list(command)
    command[-1] = f"ip4://127.0.0.1:{port}"
    report = {"program_sha256": sha((build / "player.prg").read_bytes()),
              "method": "Conditional monitor checkpoints on existing store/read instructions, raster lines 254-255; no extra native instructions or forced display refresh."}
    process = connection = monitor = None
    with (output / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            connection = native.connect(process, port)
            monitor = native.Monitor(connection)
            checkpoint = monitor.checkpoint(labels["render_start"])
            monitor.run("x")
            started = monitor.registers()
            monitor.run(f"delete {checkpoint}")
            for name in ("literal_store", "repeat_store", "read_source"):
                checkpoint = monitor.checkpoint(labels[name])
                monitor.run(f"condition {checkpoint} if (RL == $fe) || (RL == $ff)")
            monitor.checkpoint(labels["render_end"])
            monitor.run("x")
            captured = monitor.registers()
            report.update({"start": started, "capture": captured,
                           "elapsed_cycles": captured["clock"] - started["clock"]})
            if captured["pc"] == labels["render_end"]:
                report["probe_missed_field"] = True
            else:
                if not 254 <= captured["raster"] <= 255:
                    raise AssertionError("Conditional capture was not at completed visible field")
                screenshot = output / "first-visible-field.png"
                monitor.run(f'scrsh "{screenshot}" 2')
                x, y = origin
                actual = Image.open(screenshot).convert("RGB").crop((x, y, x + 320, y + 200)).tobytes()
                raw = (build / "reference.frames").read_bytes()
                font = (build / "font.bin").read_bytes()
                expected = [Image.frombytes("L", (320, 200), native.pixels_from_screen(
                    raw[pose * 1000:(pose + 1) * 1000], font)).convert("RGB").tobytes() for pose in (0, 1)]
                errors = [sum(actual[i:i + 3] != frame[i:i + 3] for i in range(0, len(actual), 3)) for frame in expected]
                unexplained = sum(actual[i:i + 3] != expected[0][i:i + 3] and actual[i:i + 3] != expected[1][i:i + 3]
                                  for i in range(0, len(actual), 3))
                report.update({"different_pixels_from_pose_0": errors[0], "different_pixels_from_pose_1": errors[1],
                               "unexplained_pixels": unexplained,
                               "actual_intermediate_field_is_torn": all(error > 0 for error in errors) and unexplained == 0,
                               "screenshot": str(screenshot)})
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
            (output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def verify(name, vice, root=None):
    build = (root or HERE / "build" / "delta") / name
    output = build / "pal-proof"
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((build / "build.json").read_text())
    program = build / "player.prg"
    labels = {name: int(address, 16) for name, address in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", (build / "main.sym").read_text())}
    events = ("render_start", "render_end", "copy_start", "copy_end", "frame_done")
    if len({labels[event] for event in events}) != len(events):
        raise ValueError("Timing labels alias")
    font = (build / "font.bin").read_bytes()
    movie = (build / "movie.bin").read_bytes()
    source_regions = movie_source_regions(build, manifest, labels, movie)
    reference = (build / "reference.frames").read_bytes()
    count = manifest["storedFrames"]
    expected = [reference[i * 1000:(i + 1) * 1000] for i in range(count)]
    pixels = [native.pixels_from_screen(frame, font) for frame in expected]
    report = {"pass": False, "variant": name, "manifest": manifest,
              "program_sha256": sha(program.read_bytes()), "font_sha256": sha(font),
              "reference_sha256": sha(reference), "movie_sha256": sha(movie),
              "immutable_source_regions": immutable_source_report(source_regions),
              "immutable_source_bytes": sum(len(region["data"]) for region in source_regions),
              "pal_clock_hz": native.PAL_CLOCK, "pal_field_cycles": native.PAL_FRAME_CYCLES,
              "speed_percent": 100, "warp": False,
              "monitor_forced_refresh_on_break": False,
              "scope": "Exact forward prefix of existing camera-axis motion. Static font, no music or interrupt workload.",
              "frames": [], "events": []}
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    palette = BASE.parents[1] / "palettes/colodore.vpl"
    command = [str(vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100",
               "+warp", "+autostart-warp", "+confirmonexit", "-sounddev", "dummy",
               "+refreshonbreak", "+binarymonitor", "-initbreak", "reset",
               "-autostartprgmode", "1", "-autostart", str(program),
               "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", str(palette),
               "-VICIIsaturation", "1000", "-VICIIcontrast", "1000",
               "-VICIIbrightness", "1000", "-VICIIgamma", "1000",
               "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    report["command"] = command
    process = connection = monitor = None
    last_render_start = last_render_end = last_copy_start = last_done = None
    renders, copies, intervals, screenshots = [], [], [], []
    origin = None
    image_fields = 0
    with (output / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            report["owned_pid"] = process.pid
            connection = native.connect(process, port)
            monitor = native.Monitor(connection)
            monitor.run("sidefx off")
            for resource, value in (("MachineVideoStandard", 1), ("Speed", 100),
                                    ("InitialWarpMode", 0), ("AutostartWarp", 0)):
                if f"{resource}={value}" not in monitor.run(f'resourceget "{resource}"'):
                    raise AssertionError("Unexpected VICE resource " + resource)
            for event in events:
                monitor.checkpoint(labels[event])

            def capture(pose, suffix):
                nonlocal origin, image_fields
                path = output / f"pose-{pose:03d}-{suffix}.png"
                monitor.run(f'scrsh "{path}" 2')
                comparison = native.screenshot_matches(path, pixels[pose])
                if origin is None:
                    origin = comparison["origin"]
                if comparison["origin"] != origin:
                    raise AssertionError("VIC active image origin changed")
                image_fields += 1
                return path, comparison

            while len(report["frames"]) < count:
                monitor.run("x")
                registers = monitor.registers()
                event = next((event for event in events if labels[event] == registers["pc"]), None)
                if event is None:
                    raise AssertionError(f"Unexpected breakpoint ${registers['pc']:04x}")
                report["events"].append({"event": event, **registers})
                if event == "render_start":
                    if not 256 <= registers["raster"] <= 257:
                        raise AssertionError("Update did not start in lower border")
                    last_render_start = registers["clock"]
                elif event == "render_end":
                    last_render_end = registers["clock"]
                    renders.append(last_render_end - last_render_start)
                    if not manifest["hidden"] and renders[-1] >= native.PAL_FRAME_CYCLES:
                        report["direct_update_exceeds_one_field"] = True
                elif event == "copy_start":
                    last_copy_start = registers["clock"]
                    if manifest["hidden"]:
                        if not 256 <= registers["raster"] <= 257:
                            raise AssertionError("Visible copy did not start in lower border")
                        # The completed field immediately before the copy must
                        # still show the previous front image while hidden work runs.
                        capture(len(report["frames"]) - 1, "held")
                elif event == "copy_end":
                    if manifest["hidden"]:
                        copies.append(registers["clock"] - last_copy_start)
                elif event == "frame_done":
                    pose = len(report["frames"])
                    if not 256 <= registers["raster"] <= 257:
                        raise AssertionError("Scanout checkpoint outside completed-field lower border")
                    if last_done is not None:
                        interval = registers["clock"] - last_done
                        intervals.append(interval)
                        field_count = round(interval / native.PAL_FRAME_CYCLES)
                        if abs(interval - field_count * native.PAL_FRAME_CYCLES) > 63:
                            raise AssertionError("Presentation is not aligned to PAL fields")
                    last_done = registers["clock"]
                    path, comparison = capture(pose, "completed")
                    screenshots.append(path)
                    monitor.run("bank ram")
                    ram = monitor.dump(output / "last-ram.bin", 0, 65535)
                    monitor.run("bank io")
                    vic = monitor.dump(output / "last-vic.bin", 0xd000, 0xd03f)
                    colors = monitor.dump(output / "last-colors.bin", 0xd800, 0xdbe7)
                    cia = monitor.dump(output / "last-cia.bin", 0xdd00, 0xdd00)[0]
                    monitor.run("bank cpu")
                    if ram[0x400:0x7e8] != expected[pose]:
                        raise AssertionError("Native screen mismatch at pose " + str(pose))
                    if manifest["hidden"] and ram[0x800:0xbe8] != expected[pose]:
                        raise AssertionError("Native hidden mirror mismatch")
                    if ram[labels["frame_index"]] != pose:
                        raise AssertionError("Native pose index mismatch")
                    if ram[0x2000:0x2000 + len(font)] != font:
                        raise AssertionError("Immutable font changed")
                    assert_movie_source(ram, source_regions)
                    if (vic[0x18] >> 4) != 1 or (vic[0x18] & 14) * 0x400 != 0x2000 or cia & 3 != 3:
                        raise AssertionError("VIC screen, charset or bank mismatch")
                    if vic[0x11] & 0x7f != 0x1b or vic[0x16] & 0x1f != 8 or vic[0x15] != 0:
                        raise AssertionError("Unexpected text mode or sprites")
                    if vic[0x20] & 15 or vic[0x21] & 15 or any(value & 15 != 1 for value in colors):
                        raise AssertionError("Unexpected display colors")
                    report["frames"].append({"pose": pose, "clock": registers["clock"],
                                             "screen_match": True, "scanout_match": True,
                                             "screenshot": path.name, "comparison": comparison})
                    if (pose + 1) % 16 == 0:
                        print(json.dumps({"variant": name, "verified_frames": pose + 1}), flush=True)

            if sha(program.read_bytes()) != report["program_sha256"]:
                raise AssertionError("Program changed during native proof")
            direct_safe = manifest["hidden"] or max(renders) < native.PAL_FRAME_CYCLES
            report.update({"pass": direct_safe, "all_final_screens_match": True,
                           "all_captured_scanouts_match": True, "checked_frames": count,
                           "actual_visible_fields_verified": image_fields,
                           "render_cycles": stats(renders), "copy_cycles": stats(copies),
                           "presentation_cycles": stats(intervals),
                           "mean_fps": native.PAL_CLOCK / statistics.mean(intervals),
                           "minimum_instantaneous_fps": native.PAL_CLOCK / max(intervals),
                           "maximum_instantaneous_fps": native.PAL_CLOCK / min(intervals),
                           "observed_fields_per_image": sorted({round(value / native.PAL_FRAME_CYCLES) for value in intervals}),
                           "safe_scanout_scope": "Every direct-update field if one-field updates; final and immediately pre-copy held fields for hidden variants.",
                           "secondsOfStoredPosesAtMeasuredFps": count * statistics.mean(intervals) / native.PAL_CLOCK})
            if not direct_safe:
                report["rejection"] = "Direct update takes more than one field. Intermediate visible fields are not certified; do not use this as a tear-free playback result."
            if direct_safe:
                x, y = origin
                first = Image.open(screenshots[0]).convert("RGB")
                first.crop((x, y, x + 320, y + 200)).resize((640, 400), Image.Resampling.NEAREST).save(build / "preview.png")
                images = [Image.open(path).convert("RGB").crop((x, y, x + 320, y + 200)).resize((640, 400), Image.Resampling.NEAREST) for path in screenshots]
                durations = [round(1000 * value / native.PAL_CLOCK / 10) * 10 for value in intervals]
                durations = [durations[0], *durations]
                images[0].save(build / "preview.gif", save_all=True, append_images=images[1:], duration=durations, optimize=False)
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
    print(json.dumps({key: value for key, value in report.items() if key not in ("frames", "events", "command", "manifest")}, indent=2))
    if report.get("direct_update_exceeds_one_field"):
        probe = probe_intermediate_field(build, command, labels, origin)
        report["intermediateFieldProbe"] = probe
        if probe.get("actual_intermediate_field_is_torn"):
            report["rejection"] = "Actual first visible update field mixes old and new poses. Final-image cadence is not a tear-free playback rate."
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def aggregate(root=None, storage_root=None, variants=("sparse-front", "sparse-hidden", "packets-hidden")):
    """Summarize already verified RAM-sized chunks without rerunning VICE."""
    root = root or HERE / "build" / "delta"
    builds = json.loads((root / "builds.json").read_text())
    storage = json.loads(((storage_root or root) / "study.json").read_text())
    output = {"pass": True, "settings": storage["settings"], "imageSource": storage["imageSource"], "sourceScreensSha256": storage["sourceScreensSha256"],
              "fontSha256": storage["fontSha256"], "scope": storage["motion"],
              "dataArena": storage["arena"], "variants": {}}
    for variant in variants:
        members = [row for row in builds if row["variant"] == variant]
        proofs = []
        render_cycles, copy_cycles, presentation_cycles = [], [], []
        transitions = set()
        for member in members:
            proof = json.loads((root / member["name"] / "pal-proof/verification.json").read_text())
            if not proof["pass"] or proof["program_sha256"] != member["hashes"]["program"]:
                raise AssertionError("Native proof is missing or stale for " + member["name"])
            proofs.append(proof)
            render_start = copy_start = None
            for event in proof["events"]:
                if event["event"] == "render_start":
                    render_start = event["clock"]
                elif event["event"] == "render_end":
                    render_cycles.append(event["clock"] - render_start)
                elif event["event"] == "copy_start":
                    copy_start = event["clock"]
                elif event["event"] == "copy_end" and member["hidden"]:
                    copy_cycles.append(event["clock"] - copy_start)
            presentation_cycles.extend(b["clock"] - a["clock"] for a, b in zip(proof["frames"], proof["frames"][1:]))
            transitions.update(member["sourcePoseIndices"][1:])
        if transitions != set(range(384)) or len(render_cycles) != 384:
            raise AssertionError("Native timing does not cover every full-turn transition for " + variant)
        first = next(row for row in members if row["firstSourcePose"] == 0)
        prefix = storage["formats"][first["codec"]]["maximumPrefix"]
        fps = native.PAL_CLOCK / statistics.mean(presentation_cycles)
        output["variants"][variant] = {
            "pass": True, "ramSizedNativePrograms": len(members),
            "uniquePosesAndTransitionsVerified": 384,
            "actualVisibleFieldsVerified": sum(proof["actual_visible_fields_verified"] for proof in proofs),
            "totalColdAndAnimatedFramesVerified": sum(proof["checked_frames"] for proof in proofs),
            "renderCycles": stats(render_cycles), "copyCycles": stats(copy_cycles),
            "presentationCycles": stats(presentation_cycles), "meanFps": fps,
            "palFieldsPerImage": sorted({round(value / native.PAL_FRAME_CYCLES) for value in presentation_cycles}),
            "firstPosePrefixStorage": prefix,
            "secondsOfFirstPoseStoredPrefixAtMeasuredFps": first["storedFrames"] / fps,
            "standalonePrefixProgram": str(root / first["name"] / "player.prg"),
            "prefixProgramBytes": first["programBytes"], "meaningfulLoadedBytes": first["meaningfulLoadedBytes"],
            "codeStateAndPointersBytes": first["codeStateAndPointersBytes"],
            "workScreenBytes": first["workScreenBytes"], "fontBytes": first["fontBytes"],
            "corpusNote": "All 384 transitions were measured via several separate programs. They do not fit one C64 at once. Prefix capacity is measured from source pose zero."
        }
    geometry = root / "geometry-storage/study.json"
    if geometry.exists():
        comparison = json.loads(geometry.read_text())
        output["flatGeometryStorageOnly"] = {"sourceScreensSha256": comparison["sourceScreensSha256"],
            "imageSource": comparison["imageSource"], "formats": comparison["formats"],
            "nativeFpsForThisCorpus": None}
    rejected = root / "packets-front/pal-proof/verification.json"
    if rejected.exists():
        row = json.loads(rejected.read_text())
        output["rejectedDirectPacketPath"] = {"pass": row["pass"], "observedFinalImageFps": row["mean_fps"],
            "reason": row.get("rejection"), "renderCycles": row["render_cycles"]}
        probe = root / "packets-front/intermediate-field-probe/result.json"
        if probe.exists():
            output["rejectedDirectPacketPath"]["intermediateFieldProbe"] = json.loads(probe.read_text())
            if output["rejectedDirectPacketPath"]["intermediateFieldProbe"].get("actual_intermediate_field_is_torn"):
                output["rejectedDirectPacketPath"]["reason"] = "Actual first visible update field mixes old and new poses. Final-image cadence is not a tear-free playback rate."
    (root / "summary.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variants", nargs="*", default=["sparse-front", "sparse-hidden", "packets-hidden"])
    parser.add_argument("--chunks", action="store_true", help="Verify every built RAM-sized chunk for the selected variants")
    parser.add_argument("--summary-only", action="store_true", help="Aggregate existing full-turn receipts without running VICE")
    parser.add_argument("--geometry", action="store_true", help="Use the separate flat-geometry native corpus and output tree")
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    args = parser.parse_args()
    root = HERE / "build" / "delta"
    storage_root = root
    if args.geometry:
        storage_root = root / "geometry-storage"
        root = root / "geometry-native"
    if args.summary_only:
        aggregate(root, storage_root, ("sparse-front", "sparse-hidden") if args.geometry else ("sparse-front", "sparse-hidden", "packets-hidden"))
        raise SystemExit(0)
    names = args.variants
    if args.chunks:
        builds = json.loads((root / "builds.json").read_text())
        names = [row["name"] for row in builds if row["variant"] in args.variants]
    results = [verify(name, args.vice, root) for name in names]
    summary = [{key: value for key, value in row.items() if key not in ("frames", "events", "command")} for row in results]
    filename = "native-results-" + "-".join(args.variants) + ".json"
    (root / filename).write_text(json.dumps(summary, indent=2) + "\n")
