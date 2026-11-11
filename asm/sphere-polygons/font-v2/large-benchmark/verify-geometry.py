#!/usr/bin/env python3
"""Measure huge-sphere native fill variants against independent host spans."""

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
SPEC = importlib.util.spec_from_file_location("huge_geometry_monitor", HERE.parents[1] / "verify-c64.py")
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)
STAGES = ("render_start", "clear_start", "clear_end", "raster_start", "raster_end",
          "resolve_start", "resolve_end", "render_end", "frame_done")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def stats(values):
    return {"min": min(values), "mean": statistics.mean(values), "max": max(values)}


def verify(args):
    variant = (HERE / "build/native-geometry/variants" / args.variant).resolve()
    output = variant / "pal-proof"
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((variant / "build.json").read_text())
    program = variant / "player.prg"
    symbol_file = variant / "geometry-player.sym"
    labels = {name: int(value, 16) for name, value in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", symbol_file.read_text())}
    missing = set(STAGES) - labels.keys()
    if missing:
        raise ValueError(f"Missing native stage symbols: {missing}")
    if len({labels[name] for name in STAGES}) != len(STAGES):
        raise ValueError("Stage checkpoints must have distinct PCs")
    assets = HERE / "build/geometry"
    font = (assets / "font.bin").read_bytes()
    expected = (assets / "frames.screen").read_bytes()
    expected_coverage = (assets / "frames.coverage").read_bytes()
    source = (variant / "frames-source.bin").read_bytes()
    xy_planes = (HERE / "build/native-xy/frames.planes").read_bytes() if manifest["sourceKind"] == 3 else None
    index = json.loads((variant / "source-index.json").read_text())
    poses = [int(value) for value in args.poses.split(",")]
    if not poses or any(pose < 0 or pose >= len(index) for pose in poses):
        raise ValueError("Pose indexes out of range")
    # One extra render allows the final requested front image to finish scanout.
    runs = poses + [poses[0]]
    report = {"pass": False, "variant": args.variant, "program_sha256": sha(program.read_bytes()),
              "font_sha256": sha(font), "reference_sha256": sha(expected),
              "source_sha256": sha(source), "pal_clock_hz": native.PAL_CLOCK,
              "pal_field_cycles": native.PAL_FRAME_CYCLES, "speed_percent": 100, "warp": False,
              "scope": "One source frame is injected before native rendering. The C64 decodes spans, fills character coverage, resolves fixed glyphs and presents normally. Source capacity is separate from this timing probe.",
              "monitor_refresh_on_break": False, "samples": []}
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    palette = HERE.parents[3] / "palettes/colodore.vpl"
    command = [str(args.vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100",
               "+warp", "+autostart-warp", "+confirmonexit", "-sounddev", "dummy",
               "+refreshonbreak", "+binarymonitor", "-initbreak", "reset",
               "-autostartprgmode", "1", "-autostart", str(program),
               "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", str(palette),
               "-VICIIsaturation", "1000", "-VICIIcontrast", "1000", "-VICIIbrightness", "1000", "-VICIIgamma", "1000",
               "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    process = connection = monitor = None
    previous_pose = previous_done = None
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
            for name in STAGES:
                monitor.checkpoint(labels[name])

            def arrive(name):
                monitor.run("x")
                registers = monitor.registers()
                if registers["pc"] != labels[name]:
                    raise AssertionError(f"Expected {name} ${labels[name]:04x}, got ${registers['pc']:04x}")
                return registers

            for run, pose in enumerate(runs):
                times = {"render_start": arrive("render_start")}
                record = index[pose]
                frame = source[record["offset"]:record["offset"] + record["length"]]
                injected = output / "injected-frame.prg"
                injected.write_bytes(manifest["movieAddress"].to_bytes(2, "little") + frame)
                if xy_planes is not None:
                    previous = 0 if pose == 0 else pose - 1
                    state = output / "injected-xy.prg"
                    state.write_bytes(bytes([0, 0x16]) + xy_planes[previous * 728:(previous + 1) * 728])
                    monitor.run(f'load "{state}" 0')
                monitor.run(f'load "{injected}" 0')
                for stage in STAGES[1:]:
                    times[stage] = arrive(stage)
                if not 256 <= times["frame_done"]["raster"] <= 257:
                    raise AssertionError("Presentation checkpoint is outside lower border")
                monitor.run("bank ram")
                ram = monitor.dump(output / "last-ram.bin", 0, 65535)
                monitor.run("bank cpu")
                back = ram[labels["back_screen_hi"]] << 8
                actual = ram[back:back + 1000]
                wanted = expected[pose * 1000:(pose + 1) * 1000]
                coverage = expected_coverage[pose * 1000:(pose + 1) * 1000]
                if ram[0x1000:0x13e8] != coverage:
                    mismatch = [(i, a, b) for i, (a, b) in enumerate(zip(ram[0x1000:0x13e8], coverage)) if a != b]
                    raise AssertionError(f"Native coverage differs at pose {pose}: {len(mismatch)}, first {mismatch[:8]}")
                if actual != wanted:
                    mismatch = [(i, a, b) for i, (a, b) in enumerate(zip(actual, wanted)) if a != b]
                    raise AssertionError(f"Native glyphs differ at pose {pose}: {len(mismatch)}, first {mismatch[:8]}")
                if ram[0x2000:0x2800] != font:
                    raise AssertionError("Immutable font changed")
                if xy_planes is not None and ram[0x1600:0x18d8] != xy_planes[pose * 728:(pose + 1) * 728]:
                    raise AssertionError(f"Decoded compact XY differs at pose {pose}")
                if ram[manifest["movieAddress"]:manifest["movieAddress"] + len(frame)] != frame:
                    raise AssertionError("Source frame changed during rendering")
                sample = {"pose": pose, "clocks": times, "screen_match": True, "coverage_match": True,
                          "render_cycles": times["render_end"]["clock"] - times["render_start"]["clock"],
                          "clear_cycles": times["clear_end"]["clock"] - times["clear_start"]["clock"],
                          "span_decode_and_fill_cycles": times["raster_end"]["clock"] - times["raster_start"]["clock"],
                          "resolve_cycles": times["resolve_end"]["clock"] - times["resolve_start"]["clock"]}
                if previous_done is not None:
                    sample["presentation_cycles"] = times["frame_done"]["clock"] - previous_done
                if previous_pose is not None:
                    screenshot = output / f"scanout-{run:03d}-pose-{previous_pose:03d}.png"
                    monitor.run(f'scrsh "{screenshot}" 2')
                    pixels = native.pixels_from_screen(expected[previous_pose * 1000:(previous_pose + 1) * 1000], font)
                    sample["completed_pose"] = previous_pose
                    sample["scanout"] = screenshot.name
                    sample["scanout_comparison"] = native.screenshot_matches(screenshot, pixels)
                report["samples"].append(sample)
                previous_pose, previous_done = pose, times["frame_done"]["clock"]
                print(json.dumps({"pose": pose, "render_cycles": sample["render_cycles"],
                                  "presentation_cycles": sample.get("presentation_cycles"), "pixel_exact": True}), flush=True)

            active = report["samples"][:-1]
            presentations = [sample["presentation_cycles"] for sample in report["samples"] if "presentation_cycles" in sample]
            report.update({"pass": True, "poses_verified": poses, "actual_scanouts_verified": len(poses),
                           "render_cycles": stats([sample["render_cycles"] for sample in active]),
                           "clear_cycles": stats([sample["clear_cycles"] for sample in active]),
                           "span_decode_and_fill_cycles": stats([sample["span_decode_and_fill_cycles"] for sample in active]),
                           "resolve_cycles": stats([sample["resolve_cycles"] for sample in active]),
                           "presentation_cycles": stats(presentations),
                           "measured_fps": native.PAL_CLOCK / statistics.mean(presentations),
                           "manifest": manifest})
            first_scanout = output / report["samples"][1]["scanout"]
            origin = report["samples"][1]["scanout_comparison"]["origin"]
            x, y = origin
            Image.open(first_scanout).crop((x, y, x + 320, y + 200)).resize(
                (640, 400), Image.Resampling.NEAREST).save(variant / "sphere-c64.png")
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
    print(json.dumps({key: value for key, value in report.items() if key not in ("samples", "command", "manifest")}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", default="packed-fast")
    parser.add_argument("--poses", default="0,24,48,72,96,120,144,168,192,216,240,264,288,312,336,360")
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    verify(parser.parse_args())
