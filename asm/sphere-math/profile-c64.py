#!/usr/bin/env python3
"""Collect VICE's native 6510 profiler over one complete sphere phase period."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import statistics
import subprocess


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sphere_vice_verifier", HERE / "verify-c64.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def profile(args):
    program = args.program.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    labels = verifier.read_labels(args.symbols)
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    command = [
        str(args.vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100",
        "+warp", "+autostart-warp", "+confirmonexit", "-sounddev", "dummy",
        "+refreshonbreak", "+binarymonitor", "-initbreak", "reset",
        "-autostartprgmode", "1", "-autostart", str(program),
        "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}",
    ]
    report = {
        "pass": False, "program": str(program),
        "program_sha256": hashlib.sha256(program.read_bytes()).hexdigest(),
        "command": command, "frames": args.frames, "port": port,
        "scope": "Mode zero; one complete frame_done-to-frame_done phase period, including raster waits and VIC stalls.",
        "samples": [], "exports": {},
    }
    process = None
    connection = None
    monitor = None
    with (output / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            report["pid"] = process.pid
            connection = verifier.connect_monitor(process, port)
            monitor = verifier.Monitor(connection)
            monitor.run("sidefx off")
            monitor.run(f'load_labels "{args.vice_symbols.resolve()}"')
            (output / "profile-help.txt").write_text(monitor.run("help profile"))
            monitor.checkpoint(labels["frame_done"])
            monitor.run("x")
            first = monitor.registers()
            if first["pc"] != labels["frame_done"]:
                raise AssertionError("Native renderer did not reach its first presentation boundary.")
            mode = monitor.dump(output / "mode.bin", labels["mode"], labels["mode"])[0]
            initial_spin = monitor.dump(output / "initial-spin.bin", labels["spin"], labels["spin"])[0]
            if mode != 0 or initial_spin != 0:
                raise AssertionError("Expected normal analytic mode at phase zero.")
            report["start"] = first
            monitor.run("profile on")
            previous_clock = first["clock"]
            for index in range(args.frames):
                monitor.run("x")
                registers = monitor.registers()
                if registers["pc"] != labels["frame_done"]:
                    raise AssertionError("Profiler stopped outside frame_done.")
                spin = monitor.dump(output / "last-spin.bin", labels["spin"], labels["spin"])[0]
                expected_spin = ((index + 1) * 4) & 127
                if spin != expected_spin:
                    raise AssertionError(f"Expected spin {expected_spin}, observed {spin}.")
                report["samples"].append({
                    "index": index, "spin": spin, **registers,
                    "elapsed_cycles": registers["clock"] - previous_clock,
                })
                previous_clock = registers["clock"]
            monitor.run("profile off")
            report["end"] = monitor.registers()
            report["elapsed_cycles"] = report["end"]["clock"] - first["clock"]
            report["median_frame_cycles"] = statistics.median(row["elapsed_cycles"] for row in report["samples"])
            report["measured_fps"] = verifier.PAL_CLOCK / report["median_frame_cycles"]
            commands = {
                "flat": "profile flat 30",
                "graph": "profile graph depth 5",
            }
            for name in ("frame_done", "main", "analytic_glyph", "sparse_glyph", "clip_limb", "read_keyboard", "wait_raster"):
                if name in labels:
                    commands["func-" + name] = f"profile func {labels[name]:04x}"
                    commands["disass-" + name] = f"profile disass {labels[name]:04x}"
            for name, text in commands.items():
                try:
                    response = monitor.run(text)
                    path = output / (name + ".txt")
                    path.write_text(response)
                    report["exports"][name] = {"command": text, "file": path.name}
                except Exception as error:
                    report["exports"][name] = {"command": text, "error": repr(error)}
            report["pass"] = "file" in report["exports"].get("flat", {})
            if not report["pass"]:
                raise RuntimeError("VICE did not export a built-in flat profile.")
        except Exception as error:
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
            (output / "profile.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"pass": report["pass"], "output": str(output),
                      "cycles": report["elapsed_cycles"], "fps": report["measured_fps"],
                      "program_sha256": report["program_sha256"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, default=HERE / "build/sphere.prg")
    parser.add_argument("--symbols", type=Path, default=HERE / "build/sphere.sym")
    parser.add_argument("--vice-symbols", type=Path, default=HERE / "build/sphere.vs")
    parser.add_argument("--output", type=Path, default=HERE / "build/cpu-profile")
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    parser.add_argument("--frames", type=int, default=32)
    args = parser.parse_args()
    if args.frames <= 0:
        parser.error("--frames must be positive")
    profile(args)
