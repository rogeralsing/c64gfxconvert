#!/usr/bin/env python3
"""Verify queued geometry updates in PAL without weakening the front50 proof."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import statistics
import subprocess

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("queued_front_helpers", HERE.parent / "player/front-delta/verify-pal.py")
front = importlib.util.module_from_spec(spec)
spec.loader.exec_module(front)
native = front.native
sha = lambda data: hashlib.sha256(data).hexdigest()


def stats(values):
    return {"samples": len(values), "min": min(values), "median": statistics.median(values),
            "mean": statistics.mean(values), "max": max(values)} if values else None


def verify(args):
    variant = args.variant.resolve()
    program, symbol_file = variant / "build/player.prg", variant / "build/main.sym"
    image = program.read_bytes()
    labels = {name: int(value, 16) for name, value in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", symbol_file.read_text())}
    required = {"render_start", "render_end", "frame_done", "flush_start", "flush_end",
                "frame_index", "frame_counter", "front_screen_hi", "animation", "animation_end"}
    if not required <= labels.keys():
        raise ValueError("Missing labels: " + ", ".join(sorted(required - labels.keys())))
    compute_start = "compute_start" if "compute_start" in labels else "render_start"
    compute_end = "compute_end" if "compute_end" in labels else "resolve_end"
    if compute_end not in labels:
        raise ValueError("Need compute_end or resolve_end before any visible flush")
    protocol = args.protocol
    if protocol == "auto":
        protocol = "pre-flush" if labels["frame_done"] == labels["flush_start"] else "post-flush"
    if protocol == "pre-flush" and labels["frame_done"] != labels["flush_start"]:
        raise ValueError("Pre-flush protocol requires frame_done==flush_start")
    if protocol == "post-flush" and labels["frame_done"] == labels["flush_start"]:
        raise ValueError("Post-flush protocol needs a distinct completed-field checkpoint")
    digest = sha(image)
    if args.expected_program_sha256 and digest != args.expected_program_sha256.lower():
        raise ValueError("Program differs from frozen expected SHA-256")
    asset_path = args.asset.resolve()
    asset = asset_path.read_bytes()
    load = int.from_bytes(image[:2], "little")
    def embedded(first, last):
        if not load <= first <= last <= load + len(image) - 2:
            raise ValueError("Static block outside the PRG load image")
        return image[2 + first - load:2 + last - load]
    if asset != embedded(labels["animation"], labels["animation_end"]):
        raise ValueError("Explicit asset does not match the complete embedded animation block")
    font = args.font.read_bytes()
    reference = args.reference.read_bytes()
    if len(font) != 2048 or len(reference) != 64000:
        raise ValueError("Need original font and64 complete reference screens")
    coverage_reference = args.coverage_reference.read_bytes() if args.coverage_reference and args.coverage_reference.is_file() else None
    if coverage_reference is not None and len(coverage_reference) != 64000:
        raise ValueError("Coverage reference must have64000 bytes")
    pixels = [native.pixels_from_screen(reference[i * 1000:(i + 1) * 1000], font) for i in range(64)]
    static_start = labels.get("raster_assets_start", labels.get("glyph_lut"))
    static_end = labels["animation"]
    static = embedded(static_start, static_end) if static_start is not None else None
    sources = {str(p): sha(p.read_bytes()) for p in variant.glob("*.asm")}
    output = (args.output or variant / "build/pal-queued-proof").resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "pass": False, "variant": str(variant), "protocol": protocol, "program_sha256": digest,
        "symbols_sha256": sha(symbol_file.read_bytes()), "source_sha256": sources,
        "asset": str(asset_path), "asset_bytes": len(asset), "asset_sha256": sha(asset), "asset_matches_program": True,
        "font_sha256": sha(font), "reference_sha256": sha(reference),
        "pal_clock_hz": native.PAL_CLOCK, "pal_frame_cycles": native.PAL_FRAME_CYCLES,
        "expected_fields": args.expected_fields, "speed_percent": 100, "warp": False,
        "measurement": "Actual VIC PNG after every completed presented UPDATE, with compute and flush clocks including VIC stalls. Positive held-field counts are allowed; held fields are not individually captured.",
        "write_scope": "Separate assembled write/deadline traces certify visible warm writes only in the bounded ascending flush. This PAL proof checks front immutability at compute boundaries, exact flush result and completed-update scanout.",
        "samples": [], "work_samples": [],
    }
    if static is not None:
        report["lookup_assets"] = {"start": static_start, "end": static_end, "bytes": len(static), "sha256": sha(static)}
    if coverage_reference is not None:
        report["coverage_reference_sha256"] = sha(coverage_reference)
    for name in ("start", "player_code_end", "delta_code_end", "coverage", "queue_count", "target_update_index"):
        if name in labels:
            report.setdefault("labels", {})[name] = labels[name]
    if args.motion_manifest and args.motion_manifest.is_file():
        report["motion"] = json.loads(args.motion_manifest.read_text()).get("motion")
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    palette = HERE.parents[4] / "palettes/colodore.vpl"
    command = [str(args.vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100", "+warp",
               "+autostart-warp", "+confirmonexit", "-sounddev", "dummy", "+refreshonbreak", "+binarymonitor",
               "-initbreak", "reset", "-autostartprgmode", "1", "-autostart", str(program),
               "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", str(palette), "-VICIIsaturation", "1000",
               "-VICIIcontrast", "1000", "-VICIIbrightness", "1000", "-VICIIgamma", "1000", "-remotemonitor",
               "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    report["command"] = command
    process = connection = monitor = None
    at = origin = previous_done = None
    with (output / "vice.log").open("w") as log:
      try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        report["owned_pid"] = process.pid
        connection = native.connect(process, port)
        monitor = native.Monitor(connection)
        monitor.run("sidefx off")
        for resource, expected in (("MachineVideoStandard", 1), ("Speed", 100), ("InitialWarpMode", 0), ("AutostartWarp", 0)):
            if f"{resource}={expected}" not in monitor.run(f'resourceget "{resource}"'):
                raise AssertionError("Wrong VICE resource: " + resource)
        watched = [compute_start, compute_end, "render_end", "flush_start", "flush_end", "frame_done"]
        for address in sorted({labels[name] for name in watched}):
            monitor.checkpoint(address)

        def arrive(name):
            nonlocal at
            if at is None or at["pc"] != labels[name]:
                monitor.run("x")
                at = monitor.registers()
            if at["pc"] != labels[name]:
                raise AssertionError(f"Expected {name}, stopped at ${at['pc']:04x}")
            return dict(at)

        def ram():
            monitor.run("bank ram")
            value = monitor.dump(output / "last-ram.bin", 0, 65535)
            monitor.run("bank cpu")
            return value

        def den():
            monitor.run("bank io")
            value = monitor.dump(output / "last-den.bin", 0xd011, 0xd011)[0]
            monitor.run("bank cpu")
            return bool(value & 16)

        def reference_screen(index):
            return reference[index * 1000:(index + 1) * 1000]

        def check_static(data):
            if data[0x2000:0x2800] != font or data[labels["animation"]:labels["animation_end"]] != asset:
                raise AssertionError("Font or encoded geometry source changed")
            if static is not None and data[static_start:static_end] != static:
                raise AssertionError("Static lookup assets changed")

        def capture(sequence, done):
            nonlocal origin, previous_done
            frame = sequence % 64
            if not 256 <= done["raster"] <= 257:
                raise AssertionError("Completed-image checkpoint is not in lower border")
            data = ram()
            if data[labels["frame_index"]] != frame:
                raise AssertionError(("Presented frame order", sequence, data[labels["frame_index"]]))
            if int.from_bytes(data[labels["frame_counter"]:labels["frame_counter"] + 2], "little") != sequence + 1:
                raise AssertionError("Completed-update counter differs")
            if data[0x0400:0x07e8] != reference_screen(frame):
                raise AssertionError("Completed visible RAM differs from reference")
            check_static(data)
            monitor.run("bank io")
            vic = monitor.dump(output / "last-vic.bin", 0xd000, 0xd03f)
            colors = monitor.dump(output / "last-colors.bin", 0xd800, 0xdbe7)
            cia = monitor.dump(output / "last-cia.bin", 0xdd00, 0xdd00)[0]
            monitor.run("bank cpu")
            if data[labels["front_screen_hi"]] != 4 or (vic[0x18] >> 4) != 1 or (vic[0x18] & 14) * 0x400 != 0x2000 or (cia & 3) != 3:
                raise AssertionError("Single0400 screen/font/bank changed")
            if (vic[0x11] & 0x7f) != 0x1b or (vic[0x16] & 31) != 8 or vic[0x15] or (vic[0x20] & 15) or (vic[0x21] & 15) or any((c & 15) != 1 for c in colors):
                raise AssertionError("VIC text mode/colors/sprites changed")
            filename = output / f"update-{sequence:03d}-frame-{frame:02d}.png"
            monitor.run(f'scrsh "{filename}" 2')
            comparison = native.screenshot_matches(filename, pixels[frame])
            if origin is None:
                origin = comparison["origin"]
            elif origin != comparison["origin"]:
                raise AssertionError("Scanout crop origin changed")
            sample = {"sequence": sequence, "frame": frame, "frame_done": done, "screenshot": filename.name,
                      "screenshot_comparison": comparison, "screen_match": True, "scanout_match": True}
            if previous_done is not None:
                elapsed = done["clock"] - previous_done
                fields = round(elapsed / native.PAL_FRAME_CYCLES)
                if fields < 1 or abs(elapsed - fields * native.PAL_FRAME_CYCLES) > 63:
                    raise AssertionError("Presentation gap is not a positive integer PAL-field count")
                if args.expected_fields is not None and fields != args.expected_fields:
                    raise AssertionError(("Unexpected held-field cadence", fields, args.expected_fields))
                sample.update({"presentation_cycles": elapsed, "pal_fields": fields})
            previous_done = done["clock"]
            report["samples"].append(sample)
            print(json.dumps({"sequence": sequence, "frame": frame, "scanout_match": True,
                              "pal_fields": sample.get("pal_fields")}), flush=True)

        for sequence in range(args.frames):
            started = arrive(compute_start)
            before = ram()
            cold = protocol == "post-flush" and sequence == 0
            target = (sequence + 1) % 64 if protocol == "pre-flush" else sequence % 64
            current = sequence % 64 if protocol == "pre-flush" else (sequence - 1) % 64
            expected_index = current if protocol == "pre-flush" else target
            if before[labels["frame_index"]] != expected_index:
                raise AssertionError("Compute frame-index semantics differ")
            if protocol == "pre-flush" and "target_update_index" in labels and before[labels["target_update_index"]] != target:
                raise AssertionError("Queued target index differs")
            if cold:
                if den():
                    raise AssertionError("Cold direct initialization must keep DEN disabled")
            elif before[0x0400:0x07e8] != reference_screen(current):
                raise AssertionError("Wrong stable image before hidden computation")
            computed = arrive(compute_end)
            after = ram()
            if cold:
                if den() or after[0x0400:0x07e8] != reference_screen(target):
                    raise AssertionError("Cold frame initialization differs or enables display early")
            elif after[0x0400:0x07e8] != before[0x0400:0x07e8]:
                raise AssertionError("Front screen changed across hidden computation")
            if coverage_reference is not None:
                coverage_base = labels.get("coverage", 0x1000)
                if after[coverage_base:coverage_base + 1000] != coverage_reference[target * 1000:(target + 1) * 1000]:
                    raise AssertionError(("Computed geometry coverage differs", target))
            check_static(after)
            work = {"sequence": sequence, "target": target, "compute_start": started, "compute_end": computed,
                    "compute_cycles": computed["clock"] - started["clock"], "cold_direct_initialization": cold,
                    "front_unchanged_at_compute_boundaries": not cold}
            if "queue_count" in labels:
                work["queued_glyphs"] = after[labels["queue_count"]]
            if protocol == "pre-flush":
                render_ended = arrive("render_end")
                done = arrive("frame_done")
                capture(sequence, done)
                if sequence == args.frames - 1:
                    work["pending_flush_not_executed_at_final_capture"] = True
                    report["work_samples"].append(work)
                    break
                flush_started = arrive("flush_start")
            else:
                flush_started = arrive("flush_start")
            if not 256 <= flush_started["raster"] <= 257:
                raise AssertionError("Visible queue flush must begin at lower-border256")
            preflush = ram()
            expected_front = reference_screen(target) if cold else before[0x0400:0x07e8]
            if preflush[0x0400:0x07e8] != expected_front:
                raise AssertionError("Front screen changed while waiting to flush")
            flushed = arrive("flush_end")
            if flushed["clock"] - flush_started["clock"] >= native.PAL_FRAME_CYCLES:
                raise AssertionError("Visible flush extends over more than one complete PAL field")
            flushed_ram = ram()
            if flushed_ram[0x0400:0x07e8] != reference_screen(target):
                raise AssertionError("Queue flush did not produce exact target screen")
            check_static(flushed_ram)
            work.update({"flush_start": flush_started, "flush_end": flushed,
                         "flush_cycles": flushed["clock"] - flush_started["clock"], "flush_screen_match": True})
            if protocol == "post-flush":
                render_ended = arrive("render_end")
                done = arrive("frame_done")
                if abs(done["clock"] - flush_started["clock"] - native.PAL_FRAME_CYCLES) > 63:
                    raise AssertionError("Completed update does not follow one full flush scanout field")
                capture(sequence, done)
            work["render_label_cycles"] = render_ended["clock"] - started["clock"]
            report["work_samples"].append(work)

        intervals = [s["presentation_cycles"] for s in report["samples"] if "presentation_cycles" in s]
        fields = [s["pal_fields"] for s in report["samples"] if "pal_fields" in s]
        if sha(program.read_bytes()) != digest or sha(symbol_file.read_bytes()) != report["symbols_sha256"] or sha(asset_path.read_bytes()) != report["asset_sha256"]:
            raise AssertionError("Frozen program/symbol/source changed during proof")
        for name, digest_source in sources.items():
            if sha(Path(name).read_bytes()) != digest_source:
                raise AssertionError("ASM source changed during proof")
        report.update({"pass": True, "frames_verified": args.frames, "presented_update_scanouts_verified": args.frames,
                       "screen_bytes_checked": args.frames * 1000, "scanout_pixels_checked": args.frames * 64000,
                       "font_bytes_checked": args.frames * 2048, "screenshots": args.frames,
                       "loop_wraps_verified": (args.frames - 1) // 64, "movie_immutable": True, "lookup_assets_immutable": static is not None,
                       "warm_front_unchanged_at_compute_boundaries": True,
                       "compute_cycles": stats([w["compute_cycles"] for w in report["work_samples"] if not w["cold_direct_initialization"]]),
                       "flush_cycles": stats([w["flush_cycles"] for w in report["work_samples"] if "flush_cycles" in w]),
                       "presentation_cycles": stats(intervals), "presentation_fields": stats(fields),
                       "mean_fps": native.PAL_CLOCK / statistics.mean(intervals), "median_fps": native.PAL_CLOCK / statistics.median(intervals),
                       "screenshot_origin": origin})
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
        report["owned_process_exit_code"] = process.returncode if process else None
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("samples", "work_samples", "command", "source_sha256")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", type=Path, required=True)
    parser.add_argument("--asset", type=Path, required=True)
    parser.add_argument("--protocol", choices=("auto", "pre-flush", "post-flush"), default="auto")
    parser.add_argument("--frames", type=int, default=66)
    parser.add_argument("--expected-fields", type=int)
    parser.add_argument("--expected-program-sha256")
    parser.add_argument("--reference", type=Path, default=HERE / "build/assets/reference.bin")
    parser.add_argument("--font", type=Path, default=HERE / "build/assets/font.bin")
    parser.add_argument("--coverage-reference", type=Path, default=HERE / "build/assets/coverage-reference.bin")
    parser.add_argument("--motion-manifest", type=Path, default=HERE / "build/assets/manifest.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    arguments = parser.parse_args()
    if arguments.frames < 66 or (arguments.expected_fields is not None and arguments.expected_fields < 1):
        parser.error("Need at least66 frames and a positive expected-field count")
    verify(arguments)
