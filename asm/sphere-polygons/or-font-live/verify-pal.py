#!/usr/bin/env python3
"""Verify and time the complete live checker renderer in PAL VICE."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import statistics
import subprocess

from PIL import Image


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
spec = importlib.util.spec_from_file_location("live_native", ROOT / "verify-c64.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def summary(values):
    return {"min": min(values), "mean": statistics.mean(values), "max": max(values)}


def main(args):
    program = args.program.resolve()
    labels = native.labels_from(args.symbols.resolve())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    font = (ROOT / "assets/font.bin" if args.baseline else HERE / "build/assets/font.bin").read_bytes()
    compact = circle_map = records = None
    if not args.baseline:
        compact = (HERE / "build/assets/coverage-compact.bin").read_bytes()
        circle_map = (HERE / "build/assets/circle-map.bin").read_bytes()
        records = (HERE / "build/assets/clip-records.bin").read_bytes()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    palette = ROOT.parents[1] / "palettes/colodore.vpl"
    command = [str(args.vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100",
               "+warp", "+autostart-warp", "+confirmonexit", "-sounddev", "dummy",
               "+refreshonbreak", "+binarymonitor", "-initbreak", "reset",
               "-autostartprgmode", "1", "-autostart", str(program),
               "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", str(palette),
               "-VICIIsaturation", "1000", "-VICIIcontrast", "1000",
               "-VICIIbrightness", "1000", "-VICIIgamma", "1000",
               "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    report = {"pass": False, "variant": "baseline" if args.baseline else "OR font",
              "programSha256": sha(program.read_bytes()), "fontSha256": sha(font),
              "scope": "Live rotation, projection, face culling, edge DDA, span fill, circle correction and presentation; checker only; no stored frames or spans",
              "palClockHz": native.PAL_CLOCK, "palFrameCycles": native.PAL_FRAME_CYCLES,
              "speedPercent": 100, "warp": False, "command": command, "samples": []}
    process = connection = monitor = None
    pending = None
    images = []
    immutable = None
    try:
        with (output / "vice.log").open("w") as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            report["ownedPid"] = process.pid
            connection = native.connect(process, port)
            monitor = native.Monitor(connection)
            monitor.run("sidefx off")
            for resource, expected in (("MachineVideoStandard", 1), ("Speed", 100),
                                       ("InitialWarpMode", 0), ("AutostartWarp", 0)):
                assert f"{resource}={expected}" in monitor.run(f'resourceget "{resource}"')
            for address in sorted({labels[name] for name in native.STAGES}):
                monitor.checkpoint(address)
            for index in range(args.frames + 1):
                stages = {}
                before_front = coverage = None
                for name in native.STAGES:
                    monitor.run("x")
                    registers = monitor.registers()
                    assert registers["pc"] == labels[name], (name, registers)
                    stages[name] = registers
                    if name == "render_start":
                        front = monitor.dump(output / "front-pointer.bin", labels["front_screen_hi"], labels["front_screen_hi"])[0] << 8
                        before_front = monitor.dump(output / "front-before.bin", front, front + 999)
                    if name == "raster_end":
                        pointer = monitor.dump(output / "back-pointer.bin", labels["back_screen_hi"], labels["back_screen_hi"])[0] << 8
                        start = 0x1000 if args.baseline else pointer
                        coverage = monitor.dump(output / "preclip.bin", start, start + 999)
                    if name == "resolve_end" and pending:
                        previous, pixels = pending
                        assert registers["clock"] - previous["clock"] >= native.PAL_FRAME_CYCLES
                        screenshot = output / f'frame-{previous["index"]:02d}-vice.png'
                        monitor.run(f'scrsh "{screenshot}" 2')
                        previous["screenshot"] = screenshot.name
                        previous["screenshotComparison"] = native.screenshot_matches(screenshot, pixels)
                        pending = None
                    if name == "render_end":
                        assert monitor.dump(output / "front-after.bin", front, front + 999) == before_front
                if index == args.frames:
                    break
                monitor.run("bank ram")
                ram = monitor.dump(output / "last-ram.bin", 0, 65535)
                monitor.run("bank io")
                vic = monitor.dump(output / "last-vic.bin", 0xd000, 0xd03f)
                colors = monitor.dump(output / "last-colors.bin", 0xd800, 0xdbe7)
                cia = monitor.dump(output / "last-cia.bin", 0xdd00, 0xdd00)[0]
                monitor.run("bank cpu")
                angles = tuple(ram[labels["angle_" + axis]] for axis in ("yaw", "pitch", "roll"))
                assert angles == ((2 * index) & 255, (24 + index) & 255, index & 255), (index, angles)
                assert ram[labels["model"]] == ram[labels["paused"]] == ram[labels["rotation_mode"]] == 0
                assert int.from_bytes(ram[labels["frame_counter"]:labels["frame_counter"] + 2], "little") == index + 1
                front = ram[labels["front_screen_hi"]] << 8
                assert front in (0x0400, 0x0c00)
                assert (vic[0x18] >> 4) * 0x400 == front
                assert (vic[0x18] & 14) * 0x400 == 0x2000 and (cia & 3) == 3
                assert not vic[0x11] & 0x60 and not vic[0x16] & 0x10
                assert (vic[0x11] & 0x18) == 0x18 and vic[0x16] & 8
                assert all((color & 15) == 1 for color in colors)
                assert ram[0x2000:0x2800] == font
                static = ram[0x4000:labels["assets_end"]]
                if immutable is None:
                    immutable = static
                assert static == immutable
                expected_path, state_path = output / "expected.bin", output / "state.json"
                yaw, pitch, roll = angles
                subprocess.run(["rtk", "proxy", "node", str(ROOT / "native-model.cjs"), "0", str(yaw), str(pitch),
                                str(expected_path), "--state", str(state_path), "--roll", str(roll)], check=True)
                state = json.loads(state_path.read_text())
                expected_coverage = bytes(state["coverage"][:1000])
                assert coverage == expected_coverage, ("coverage", index)
                assert ram[0x1400:0x1440] == bytes(state["projectedX"])
                assert ram[0x1440:0x1480] == bytes(state["projectedY"])
                for key, value in state["matrix"].items():
                    assert ram[labels["matrix_" + key]] == (value & 255)
                native.check_faces(ram, labels, state, 0)
                expected = expected_path.read_bytes()
                if not args.baseline:
                    expected = bytearray(expected_coverage)
                    for offset in range(0, len(records), 4):
                        cell = int.from_bytes(records[offset:offset + 2], "little")
                        base = int.from_bytes(records[offset + 2:offset + 4], "little")
                        expected[cell] = circle_map[base + compact[expected[cell]]]
                screen = ram[front:front + 1000]
                assert screen == expected, ("screen", index)
                pixels = native.pixels_from_screen(screen, font)
                assert not any(value and ((position % 320 - 160) ** 2 + (position // 320 - 100) ** 2 > 94 ** 2)
                               for position, value in enumerate(pixels))
                cycles = {name: stages[name + "_end"]["clock"] - stages[name + "_start"]["clock"]
                          for name in ("geometry", "raster", "resolve", "render")}
                sample = {"index": index, "yaw": yaw, "pitch": pitch, "roll": roll,
                          "clock": stages["frame_done"]["clock"], "cycles": cycles,
                          "screenMatch": True, "coverageMatch": True, "geometryMatch": True}
                if report["samples"]:
                    sample["presentationCycles"] = sample["clock"] - report["samples"][-1]["clock"]
                report["samples"].append(sample)
                images.append(Image.frombytes("L", (320, 200), pixels).convert("RGB"))
                if index in (0, args.frames // 2, args.frames - 1):
                    pending = (sample, pixels)
                print(json.dumps({"frame": index, "angles": angles, "cycles": cycles}), flush=True)
            assert pending is None
            cadence = [sample["presentationCycles"] for sample in report["samples"][1:]]
            report.update({"pass": True, "framesVerified": args.frames, "screenBytesChecked": args.frames * 1000,
                           "coverageBytesChecked": args.frames * 1000, "fontAndAssetsImmutable": True,
                           "frontUntouchedDuringRendering": True, "all72FacesTraversed": True,
                           "allProjectionAndMatricesMatch": True, "protrudingPixels": 0,
                           "screenshots": sum("screenshot" in sample for sample in report["samples"]),
                           "meanFps": native.PAL_CLOCK / statistics.mean(cadence),
                           "palFieldsPerPresentation": statistics.mean(cadence) / native.PAL_FRAME_CYCLES,
                           "presentationCycles": summary(cadence),
                           "stageCycles": {name: summary([sample["cycles"][name] for sample in report["samples"]])
                                           for name in ("geometry", "raster", "resolve", "render")}})
            assert sha(program.read_bytes()) == report["programSha256"]
            durations = [max(10, round(sample.get("presentationCycles", statistics.mean(cadence)) * 1000 / native.PAL_CLOCK))
                         for sample in report["samples"]]
            frames = [image.resize((640, 400), Image.Resampling.NEAREST) for image in images]
            frames[0].save(output / "live.gif", save_all=True, append_images=frames[1:], duration=durations, loop=0)
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
        report["ownedProcessExitCode"] = process.returncode if process else None
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key not in ("samples", "command")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--symbols", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=64)
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    arguments = parser.parse_args()
    if arguments.frames < 2:
        parser.error("At least two frames are required to measure cadence")
    main(arguments)
