#!/usr/bin/env python3
"""Verify every displayed PAL field of the single-visible-screen delta player."""

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
PLAYER = HERE.parent
BASE = HERE.parents[3]
spec = importlib.util.spec_from_file_location("front_delta_native_monitor", BASE / "verify-c64.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def stats(values):
    return {"samples": len(values), "min": min(values), "median": statistics.median(values),
            "mean": statistics.mean(values), "max": max(values)} if values else None


def symbols(path):
    labels = {name: int(value, 16) for name, value in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", path.read_text())}
    required = {"render_start", "render_end", "frame_done", "frame_index", "frame_counter",
                "front_screen_hi", "animation", "animation_end"}
    missing = required - labels.keys()
    if missing:
        raise ValueError("Missing front-screen verification labels: " + ", ".join(sorted(missing)))
    if len({labels[name] for name in ("render_start", "render_end", "frame_done")}) != 3:
        raise ValueError("The three verification boundary PCs must be distinct")
    return labels


def verify(args):
    variant = args.variant.resolve()
    program = variant / "build/player.prg"
    symbol_file = variant / "build/main.sym"
    labels = symbols(symbol_file)
    image = program.read_bytes()
    program_hash = sha(image)
    if args.expected_program_sha256 and program_hash != args.expected_program_sha256.lower():
        raise ValueError("Program SHA-256 differs from frozen expected PRG")
    load = int.from_bytes(image[:2], "little")
    embedded = image[2 + labels["animation"] - load:2 + labels["animation_end"] - load]
    asset_path = (args.asset or variant / "build/native-source.bin").resolve()
    asset = asset_path.read_bytes()
    if asset != embedded:
        raise ValueError("Movie asset does not match the complete PRG animation block")
    font_path, reference_path = args.font.resolve(), args.reference.resolve()
    font, reference = font_path.read_bytes(), reference_path.read_bytes()
    if len(font) != 2048 or len(reference) != 64000:
        raise ValueError("Expected the immutable 2048-byte font and 64 complete reference screens")
    pixels = [native.pixels_from_screen(reference[frame * 1000:(frame + 1) * 1000], font) for frame in range(64)]
    source_paths = sorted(path for path in variant.rglob("*.asm") if "build" not in path.relative_to(variant).parts)
    source_hashes = {str(path): sha(path.read_bytes()) for path in source_paths}
    output = (args.output or variant / "build/pal-beam-proof").resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "pass": False, "program": str(program), "program_sha256": program_hash,
        "symbols_sha256": sha(symbol_file.read_bytes()), "source_sha256": source_hashes,
        "asset": str(asset_path), "asset_bytes": len(asset), "asset_sha256": sha(asset), "asset_matches_program": True,
        "font": str(font_path), "font_sha256": sha(font), "reference": str(reference_path), "reference_sha256": sha(reference),
        "pal_clock_hz": native.PAL_CLOCK, "pal_frame_cycles": native.PAL_FRAME_CYCLES,
        "speed_percent": 100, "warp": False, "single_screen": 0x0400,
        "measurement": "Actual PAL VIC raster-buffer PNG on EVERY completed visible field, captured at frame_done in lower border before the next update. No screenshot latency fallback; no reconstructed-RAM image accepted as scanout.",
        "scope": "Fixed source/font and 64-pose loop. Screen RAM, actual scanout, one-field cadence and immutable data are checked. This is not a guarantee for arbitrary movies, music or interrupt workloads.",
        "cold_start": "Frame0 is decoded with display disabled; the first timed frame0 is a no-op followed by a complete visible field. Later frame0 updates are actual closing deltas.",
        "monitor_forced_refresh_on_break": False, "samples": [],
        "screenshot_backend_sources": [
            "https://github.com/VICE-Team/svn-mirror/blob/main/vice/src/screenshot.c",
            "https://github.com/VICE-Team/svn-mirror/blob/main/vice/src/raster/raster.c",
            "https://github.com/VICE-Team/svn-mirror/blob/main/vice/src/viciisc/vicii.c",
        ],
    }
    if args.motion_manifest and args.motion_manifest.is_file():
        manifest = json.loads(args.motion_manifest.read_text())
        report["motion"] = manifest.get("motion")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    palette = BASE.parents[1] / "palettes/colodore.vpl"
    command = [str(args.vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100",
               "+warp", "+autostart-warp", "+confirmonexit", "-sounddev", "dummy",
               "+refreshonbreak", "+binarymonitor", "-initbreak", "reset",
               "-autostartprgmode", "1", "-autostart", str(program),
               "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", str(palette),
               "-VICIIsaturation", "1000", "-VICIIcontrast", "1000", "-VICIIbrightness", "1000", "-VICIIgamma", "1000",
               "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    report["command"] = command
    process = connection = monitor = None
    crop_origin = None
    previous_done = previous_start = None
    unused_buffer = None
    with (output / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            report["owned_pid"] = process.pid
            connection = native.connect(process, port)
            monitor = native.Monitor(connection)
            monitor.run("sidefx off")
            for resource, expected in (("MachineVideoStandard", 1), ("Speed", 100),
                                       ("InitialWarpMode", 0), ("AutostartWarp", 0)):
                if f"{resource}={expected}" not in monitor.run(f'resourceget "{resource}"'):
                    raise AssertionError("Unexpected VICE resource: " + resource)
            for name in ("render_start", "render_end", "frame_done"):
                monitor.checkpoint(labels[name])

            def arrive(name):
                monitor.run("x")
                registers = monitor.registers()
                if registers["pc"] != labels[name]:
                    raise AssertionError(f"Expected {name}, observed ${registers['pc']:04x}")
                return registers

            for sequence in range(args.frames):
                frame = sequence % 64
                started = arrive("render_start")
                if not 256 <= started["raster"] <= 257:
                    raise AssertionError(f"Update begins outside lower-border boundary: {started}")
                if previous_start is not None and abs(started["clock"] - previous_start - native.PAL_FRAME_CYCLES) > 63:
                    raise AssertionError("A visible field was skipped between render starts")
                previous_start = started["clock"]
                index = monitor.dump(output / "last-index.bin", labels["frame_index"], labels["frame_index"])[0]
                if index != frame:
                    raise AssertionError(f"Wrong upcoming frame {index}, expected {frame}")
                if sequence == 0:
                    monitor.run("bank ram")
                    initial = monitor.dump(output / "initial-ram.bin", 0, 65535)
                    monitor.run("bank cpu")
                    if initial[0x0400:0x07e8] != reference[:1000]:
                        raise AssertionError("Cold frame0 was not decoded before timed scanout")
                    unused_buffer = initial[0x0c00:0x1000]
                ended = arrive("render_end")
                done = arrive("frame_done")
                if not 256 <= done["raster"] <= 257:
                    raise AssertionError(f"Scanout capture is not at the completed-field lower border: {done}")
                field_clocks = done["clock"] - started["clock"]
                if abs(field_clocks - native.PAL_FRAME_CYCLES) > 63:
                    raise AssertionError(f"Update/capture does not cover exactly one field: {field_clocks}")
                # PNG driver2 reads the emulator's already-rasterized pixel
                # buffer. Refresh-on-break is disabled to preserve scanout.
                screenshot = output / f"field-{sequence:03d}-frame-{frame:02d}.png"
                monitor.run(f'scrsh "{screenshot}" 2')
                comparison = native.screenshot_matches(screenshot, pixels[frame])
                if crop_origin is None:
                    crop_origin = comparison["origin"]
                elif comparison["origin"] != crop_origin:
                    raise AssertionError("VIC screenshot active-area origin changed between fields")
                monitor.run("bank ram")
                ram = monitor.dump(output / "last-ram.bin", 0, 65535)
                monitor.run("bank io")
                vic = monitor.dump(output / "last-vic.bin", 0xd000, 0xd03f)
                colors = monitor.dump(output / "last-colors.bin", 0xd800, 0xdbe7)
                cia = monitor.dump(output / "last-cia.bin", 0xdd00, 0xdd00)[0]
                monitor.run("bank cpu")
                expected = reference[frame * 1000:(frame + 1) * 1000]
                if ram[0x0400:0x07e8] != expected:
                    raise AssertionError(f"Final screen RAM differs at frame{frame}")
                if ram[labels["frame_index"]] != frame:
                    raise AssertionError("Frame index advanced before completed-field checkpoint")
                counter = int.from_bytes(ram[labels["frame_counter"]:labels["frame_counter"] + 2], "little")
                if counter != sequence + 1:
                    raise AssertionError("Frame counter differs from completed-field sequence")
                if ram[labels["front_screen_hi"]] != 4 or (vic[0x18] >> 4) != 1:
                    raise AssertionError("VIC changed away from the single$0400 screen")
                if (vic[0x18] & 14) * 0x400 != 0x2000 or (cia & 3) != 3:
                    raise AssertionError("VIC font or bank differs")
                if (vic[0x11] & 0x7f) != 0x1b or (vic[0x16] & 0x1f) != 8 or (vic[0x15] != 0):
                    raise AssertionError("Unexpected text mode, scroll, display-enable or sprite state")
                if (vic[0x20] & 15) or (vic[0x21] & 15) or any((color & 15) != 1 for color in colors):
                    raise AssertionError("Unexpected background/border/character colors")
                if ram[0x2000:0x2800] != font:
                    raise AssertionError("Fixed font changed")
                if ram[labels["animation"]:labels["animation_end"]] != asset:
                    raise AssertionError("Encoded HD64/closing-delta source changed")
                if ram[0x0c00:0x1000] != unused_buffer:
                    raise AssertionError("Unused second screen region changed during playback")
                sample = {"sequence": sequence, "frame": frame, "counter": counter,
                          "render_start": started, "render_end": ended, "frame_done": done,
                          "render_cycles": ended["clock"] - started["clock"], "update_to_completed_field_cycles": field_clocks,
                          "screenshot": screenshot.name, "screenshot_comparison": comparison,
                          "scanout_match": True, "screen_match": True, "cold_start_noop": sequence == 0}
                if previous_done is not None:
                    sample["presentation_cycles"] = done["clock"] - previous_done
                    if abs(sample["presentation_cycles"] - native.PAL_FRAME_CYCLES) > 63:
                        raise AssertionError("A visible field was skipped between scanout captures")
                previous_done = done["clock"]
                report["samples"].append(sample)
                print(json.dumps({"sequence": sequence, "frame": frame, "render_cycles": sample["render_cycles"],
                                  "scanout_match": True, "capture_raster": done["raster"]}), flush=True)

            intervals = [sample["presentation_cycles"] for sample in report["samples"] if "presentation_cycles" in sample]
            renders = [sample["render_cycles"] for sample in report["samples"]]
            steady_renders = [sample["render_cycles"] for sample in report["samples"] if not sample["cold_start_noop"]]
            if sha(program.read_bytes()) != program_hash or sha(symbol_file.read_bytes()) != report["symbols_sha256"]:
                raise AssertionError("PRG or symbols changed during beam proof")
            if sha(asset_path.read_bytes()) != report["asset_sha256"] or sha(font_path.read_bytes()) != report["font_sha256"] or sha(reference_path.read_bytes()) != report["reference_sha256"]:
                raise AssertionError("Movie/font/reference input changed during beam proof")
            for filename, digest in source_hashes.items():
                if sha(Path(filename).read_bytes()) != digest:
                    raise AssertionError("ASM source changed during beam proof: " + filename)
            report.update({"pass": True, "frames_verified": args.frames, "visible_fields_pixel_exact": args.frames,
                           "screen_bytes_checked": args.frames * 1000, "font_bytes_checked": args.frames * 2048,
                           "scanout_pixels_checked": args.frames * 64000, "screenshots": args.frames,
                           "one_field_per_update_verified": True, "tear_free_observed_fields": True,
                           "loop_wraps_verified": (args.frames - 1) // 64, "single_screen_verified": True,
                           "unused_second_screen_unchanged": True, "movie_immutable": True,
                           "render_cycles": stats(renders), "steady_render_cycles": stats(steady_renders),
                           "presentation_cycles": stats(intervals),
                           "mean_fps": native.PAL_CLOCK / statistics.mean(intervals) if intervals else None,
                           "median_fps": native.PAL_CLOCK / statistics.median(intervals) if intervals else None,
                           "screenshot_origin": crop_origin})
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
    print(json.dumps({key: value for key, value in report.items() if key not in ("samples", "command", "source_sha256")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", type=Path, default=HERE)
    parser.add_argument("--asset", type=Path)
    parser.add_argument("--font", type=Path, default=PLAYER / "build/assets/font.bin")
    parser.add_argument("--reference", type=Path, default=PLAYER / "build/reference/checker-64-screen.bin")
    parser.add_argument("--motion-manifest", type=Path, default=PLAYER / "build/assets/data-layout.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--frames", type=int, default=194)
    parser.add_argument("--expected-program-sha256")
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    arguments = parser.parse_args()
    if arguments.frames < 66:
        parser.error("At least66 frames are required to include a complete loop and following images")
    verify(arguments)
