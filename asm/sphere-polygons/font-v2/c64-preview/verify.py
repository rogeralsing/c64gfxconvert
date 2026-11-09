#!/usr/bin/env python3
"""Check the preview's real PAL scanout, character RAM and playback cadence."""

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
SPEC = importlib.util.spec_from_file_location("sphere_native_monitor", BASE / "verify-c64.py")
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def stats(values):
    return {"min": min(values), "mean": statistics.mean(values), "max": max(values)} if values else None


def verify(args):
    build = HERE / "build"
    output = build / "pal-proof"
    output.mkdir(parents=True, exist_ok=True)
    program = build / "player.prg"
    symbols = build / "player.sym"
    if not symbols.exists():
        symbols = build / "main.sym"
    labels = {name: int(address, 16) for name, address in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", symbols.read_text())}
    events = ("render_start", "render_end", "copy_start", "copy_end", "frame_done")
    for name in (*events, "frame_index", "frame_counter"):
        if name not in labels:
            raise ValueError("Missing native symbol " + name)
    if len({labels[name] for name in events}) != len(events):
        raise ValueError("Native event addresses must be distinct")
    font = (build / "font.bin").read_bytes()
    all_frames = (build / "movie.frames").read_bytes()
    reference = [all_frames[offset:offset + 1000] for offset in range(0, 48000, 1000)]
    by_hash = {sha(frame): index for index, frame in enumerate(reference)}
    pixels = [native.pixels_from_screen(frame, font) for frame in reference]
    report = {"pass": False, "pal_clock_hz": native.PAL_CLOCK,
              "pal_field_cycles": native.PAL_FRAME_CYCLES,
              "program_sha256": sha(program.read_bytes()), "font_sha256": sha(font),
              "reference_sha256": sha(all_frames), "frames": [], "events": [],
              "scope": "48 exact selected-font poses, reversible arc; not a full-turn animation or a live geometry renderer.",
              "monitor_forced_refresh_on_break": False, "speed_percent": 100, "warp": False}
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    palette = BASE.parents[1] / "palettes/colodore.vpl"
    command = [str(args.vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100",
               "+warp", "+autostart-warp", "+confirmonexit", "-sounddev", "dummy",
               "+refreshonbreak", "+binarymonitor", "-initbreak", "reset",
               "-autostartprgmode", "1", "-autostart", str(program),
               "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", str(palette),
               "-VICIIsaturation", "1000", "-VICIIcontrast", "1000",
               "-VICIIbrightness", "1000", "-VICIIgamma", "1000",
               "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    report["command"] = command
    process = connection = monitor = None
    last_copy_start = last_render_start = last_copy_end = None
    copy_cycles, render_cycles, copy_intervals = [], [], []
    screen_pose, origin = 0, None
    done_images = []
    scanout_count = 0
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
                    raise AssertionError("Unexpected VICE resource " + resource)
            for name in events:
                monitor.checkpoint(labels[name])

            def capture(name, pose):
                nonlocal origin, scanout_count
                path = output / f"{scanout_count:03d}-{name}-pose-{pose:02d}.png"
                monitor.run(f'scrsh "{path}" 2')
                comparison = native.screenshot_matches(path, pixels[pose])
                if origin is None:
                    origin = comparison["origin"]
                if comparison["origin"] != origin:
                    raise AssertionError("Active image origin changed")
                scanout_count += 1
                return path, comparison

            while len(report["frames"]) < args.frames:
                monitor.run("x")
                registers = monitor.registers()
                name = next((name for name in events if labels[name] == registers["pc"]), None)
                if name is None:
                    raise AssertionError(f"Unexpected breakpoint ${registers['pc']:04x}")
                record = {"name": name, **registers}
                report["events"].append(record)
                if name == "render_start":
                    last_render_start = registers["clock"]
                elif name == "render_end":
                    if last_render_start is not None:
                        render_cycles.append(registers["clock"] - last_render_start)
                elif name == "copy_start":
                    if not 256 <= registers["raster"] <= 257:
                        raise AssertionError("Screen copy did not start in lower border")
                    if last_copy_start is not None:
                        interval = registers["clock"] - last_copy_start
                        copy_intervals.append(interval)
                        if abs(interval - 2 * native.PAL_FRAME_CYCLES) > 63:
                            raise AssertionError(f"Playback cadence is not two PAL fields: {interval}")
                        capture("held-field", screen_pose)
                    last_copy_start = registers["clock"]
                elif name == "copy_end":
                    copy_cycles.append(registers["clock"] - last_copy_start)
                    last_copy_end = registers["clock"]
                    data = monitor.dump(output / "last-screen.bin", 0x400, 0x7e7)
                    digest = sha(data)
                    if digest not in by_hash:
                        raise AssertionError("Native character screen is not any expected pose")
                    screen_pose = by_hash[digest]
                    hidden = monitor.dump(output / "last-hidden.bin", 0x800, 0xbe7)
                    if hidden != data:
                        raise AssertionError("Hidden character mirror differs after visible copy")
                elif name == "frame_done":
                    if not 256 <= registers["raster"] <= 257:
                        raise AssertionError("Completed scanout checkpoint outside lower border")
                    if last_copy_start is not None and registers["clock"] - last_copy_start < native.PAL_FRAME_CYCLES - 63:
                        raise AssertionError("No complete visible scan between copy and capture")
                    path, comparison = capture("completed-field", screen_pose)
                    done_images.append(path)
                    monitor.run("bank ram")
                    ram = monitor.dump(output / "last-ram.bin", 0, 65535)
                    monitor.run("bank io")
                    vic = monitor.dump(output / "last-vic.bin", 0xd000, 0xd03f)
                    colors = monitor.dump(output / "last-colors.bin", 0xd800, 0xdbe7)
                    cia = monitor.dump(output / "last-cia.bin", 0xdd00, 0xdd00)[0]
                    monitor.run("bank cpu")
                    if ram[0x400:0x7e8] != reference[screen_pose]:
                        raise AssertionError("Displayed screen RAM changed before frame_done")
                    if ram[0x2000:0x2800] != font:
                        raise AssertionError("Immutable font changed")
                    if ram[labels["frame_index"]] != screen_pose:
                        raise AssertionError("Frame index differs from displayed pose")
                    if (vic[0x18] >> 4) != 1 or (vic[0x18] & 14) * 0x400 != 0x2000 or cia & 3 != 3:
                        raise AssertionError("VIC screen, font or bank changed")
                    if vic[0x11] & 0x7f != 0x1b or vic[0x16] & 0x1f != 8 or vic[0x15] != 0:
                        raise AssertionError("Unexpected hires text, scroll, DEN or sprite state")
                    if vic[0x20] & 15 or vic[0x21] & 15 or any(color & 15 != 1 for color in colors):
                        raise AssertionError("Unexpected border, background or glyph colors")
                    sample = {"sequence": len(report["frames"]), "pose": screen_pose,
                              "clock": registers["clock"], "screenshot": path.name,
                              "comparison": comparison, "screen_matches": True, "font_matches": True}
                    report["frames"].append(sample)
                    if len(report["frames"]) % 12 == 0:
                        print(json.dumps({"frames": len(report["frames"]), "pose": screen_pose,
                                          "scanout_matches": True}), flush=True)

            poses = [sample["pose"] for sample in report["frames"]]
            if 0 not in poses or 47 not in poses or not any(a > b for a, b in zip(poses, poses[1:])):
                raise AssertionError("Verification did not cover both arc reversals")
            if sha(program.read_bytes()) != report["program_sha256"]:
                raise AssertionError("Program changed during verification")
            first = Image.open(done_images[0]).convert("RGB")
            x, y = origin
            first.crop((x, y, x + 320, y + 200)).resize((640, 400), Image.Resampling.NEAREST).save(build / "sphere-c64.png")
            # GIF contains the actual VIC images, not reconstructions from RAM.
            images = [Image.open(path).convert("RGB").crop((x, y, x + 320, y + 200)).resize(
                (640, 400), Image.Resampling.NEAREST) for path in done_images[:94]]
            images[0].save(build / "sphere-c64.gif", save_all=True, append_images=images[1:],
                           duration=40, loop=0, optimize=False)
            report.update({"pass": True, "displayed_poses_verified": len(poses),
                           "actual_visible_fields_verified": scanout_count, "screenshot_origin": origin,
                           "copy_cycles": stats(copy_cycles), "hidden_decode_cycles": stats(render_cycles),
                           "presentation_cycles": stats(copy_intervals),
                           "measured_fps": native.PAL_CLOCK / statistics.mean(copy_intervals),
                           "exact_two_field_cadence": True, "actual_scanout_pixel_exact": True})
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
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ("frames", "events", "command")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=96)
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    verify(parser.parse_args())
