#!/usr/bin/env python3
"""Measure native ECM metaballs stages over a 64-update PAL window."""

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import statistics
import subprocess


HERE = Path(__file__).resolve().parent
PAL_CLOCK = 985248
PAL_FRAME_CYCLES = 19656
BASELINE_CHECKPOINTS = (
    "frame_start", "add_start", "map_start", "projection_done",
    "presentation_start", "frame_ready",
)
BASELINE_STAGES = {
    "clear": ("frame_start", "add_start"),
    "add": ("add_start", "map_start"),
    "map": ("map_start", "projection_done"),
    "raster_wait": ("projection_done", "presentation_start"),
    "copy_flip": ("presentation_start", "frame_ready"),
}
DIRECT_CHECKPOINTS = (
    "frame_start", "add_start", "map_start", "presentation_start", "frame_ready",
)
DIRECT_STAGES = {
    "clear": ("frame_start", "add_start"),
    "add": ("add_start", "map_start"),
    "raster_wait": ("map_start", "presentation_start"),
    "render": ("presentation_start", "frame_ready"),
}
spec = importlib.util.spec_from_file_location("metaballs_verifier", HERE / "verify-metaballs.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def distribution(values):
    return {"min": min(values), "mean": statistics.mean(values),
            "median": statistics.median(values), "max": max(values)}


def profile(args):
    program, symbols, output = args.program.resolve(), args.symbols.resolve(), args.output.resolve()
    if not program.is_file() or not symbols.is_file():
        raise FileNotFoundError("Build the requested PRG and symbols before profiling.")
    output.mkdir(parents=True, exist_ok=True)
    labels = {name: int(address, 16) for name, address in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", symbols.read_text())}
    drift_labels = {"drift_x_index", "drift_y_index"}
    long_motion = drift_labels <= labels.keys()
    if drift_labels & labels.keys() and not long_motion:
        raise ValueError("Motion symbols must include both drift indices.")
    primary_period, primary_step = (128, 3) if long_motion else (64, 1)
    direct = "render_field" in labels and "projection_done" not in labels
    checkpoints = DIRECT_CHECKPOINTS if direct else BASELINE_CHECKPOINTS
    preparation = "fade" if "fade_field" in labels else "clear"
    stages = {preparation if name == "clear" else name: boundaries
              for name, boundaries in (DIRECT_STAGES if direct else BASELINE_STAGES).items()}
    compute_names = (preparation, "add") if direct else (preparation, "add", "map")
    projection_names = ("render",) if direct else ("map", "copy_flip")
    missing = set(checkpoints + ("frame_index",)) - labels.keys()
    if missing:
        raise ValueError(f"Missing stage labels: {sorted(missing)}")
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
        "pass": False, "program": str(program), "symbols": str(symbols),
        "program_sha256": sha256(program.read_bytes()), "symbols_sha256": sha256(symbols.read_bytes()),
        "pal": True, "pal_clock_hz": PAL_CLOCK, "pal_frame_cycles": PAL_FRAME_CYCLES,
        "speed_percent": 100, "warp": False, "command": command,
        "scope": ("64-update finite window of long-period motion; " if long_motion
                  else "Steady 64-phase motion period; ")
                 + "elapsed machine clocks include VIC bus stalls. Monitor pauses do not advance clocks.",
        "motion_period_updates": 128 * 251 * 239 if long_motion else 64,
        "window_is_complete_period": not long_motion,
        "primary_period": primary_period, "primary_step": primary_step,
        "field_preparation": preparation,
        "pipeline": "direct" if direct else "buffered",
        "compute_stages": compute_names, "projection_stages": projection_names,
        "samples": [],
    }
    process, connection, monitor = None, None, None
    with (output / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            report["owned_pid"] = process.pid
            connection = verifier.ecm_verify.connect_monitor(process, port)
            monitor = verifier.Monitor(connection)
            monitor.run("sidefx off")
            for resource, expected in (("MachineVideoStandard", 1), ("Speed", 100),
                                       ("InitialWarpMode", 0), ("AutostartWarp", 0)):
                value = monitor.run(f'resourceget "{resource}"')
                if f"{resource}={expected}" not in value:
                    raise AssertionError(f"Unexpected VICE resource: {value}")
            for name in checkpoints:
                monitor.checkpoint(labels[name])
            previous_ready = None
            phase_file = output / "last-phase.bin"
            for index in range(65):
                points = {}
                for name in checkpoints:
                    monitor.run("x")
                    registers = monitor.registers()
                    if registers["pc"] != labels[name]:
                        raise AssertionError(f"Expected {name}, stopped at ${registers['pc']:04x}.")
                    points[name] = registers
                monitor.run(f'bsave "{phase_file}" 0 {labels["frame_index"]:04x} {labels["frame_index"]:04x}')
                phase = phase_file.read_bytes()
                expected_phase = index * primary_step % primary_period
                if phase != bytes([expected_phase]):
                    raise AssertionError(f"Expected phase {expected_phase}, observed {phase!r}.")
                elapsed = {name: points[last]["clock"] - points[first]["clock"]
                           for name, (first, last) in stages.items()}
                if any(cycles <= 0 for cycles in elapsed.values()):
                    raise AssertionError("Every stage must consume positive machine clocks.")
                # Skip startup execution. Every reported update starts after
                # a completed presentation, including finite motion windows.
                if previous_ready is not None:
                    frame_cycles = points["frame_ready"]["clock"] - previous_ready
                    overhead = points["frame_start"]["clock"] - previous_ready
                    report["samples"].append({
                        "index": index, "phase": expected_phase, "cycles": elapsed,
                        "loop_overhead_cycles": overhead, "presentation_cycles": frame_cycles,
                        "compute_cycles": sum(elapsed[name] for name in compute_names),
                        "field_compute_cycles": elapsed[preparation] + elapsed["add"],
                        "projection_cycles": sum(elapsed[name] for name in projection_names),
                        "nonwait_cycles": frame_cycles - elapsed["raster_wait"],
                        "checkpoints": points,
                    })
                previous_ready = points["frame_ready"]["clock"]
                if index % 16 == 0:
                    print(json.dumps({"phase": expected_phase, "cycles": elapsed}), flush=True)
            report["samples"].sort(key=lambda sample: sample["index"] if long_motion else sample["phase"])
            samples = report["samples"]
            expected_phases = {index * primary_step % primary_period for index in range(1, 65)}
            if len(samples) != 64 or {sample["phase"] for sample in samples} != expected_phases:
                raise AssertionError("Profiling must cover the requested 64 motion updates exactly once.")
            mean_frame = statistics.mean(sample["presentation_cycles"] for sample in samples)
            mean_compute = statistics.mean(sample["compute_cycles"] for sample in samples)
            mean_nonwait = statistics.mean(sample["nonwait_cycles"] for sample in samples)
            report["stages"] = {}
            for stage in stages:
                values = [sample["cycles"][stage] for sample in samples]
                entry = distribution(values)
                entry["share_of_presentation_percent"] = statistics.mean(values) * 100 / mean_frame
                if stage in compute_names:
                    entry["share_of_compute_percent"] = statistics.mean(values) * 100 / mean_compute
                if stage != "raster_wait":
                    entry["share_of_nonwait_percent"] = statistics.mean(values) * 100 / mean_nonwait
                report["stages"][stage] = entry
            for name in ("compute_cycles", "field_compute_cycles", "projection_cycles",
                         "presentation_cycles", "nonwait_cycles", "loop_overhead_cycles"):
                report[name] = distribution([sample[name] for sample in samples])
            report["cadence_pal_frames"] = dict(sorted(Counter(
                round(sample["presentation_cycles"] / PAL_FRAME_CYCLES) for sample in samples).items()))
            report["average_fps"] = PAL_CLOCK / mean_frame
            report["median_cadence_fps"] = PAL_CLOCK / statistics.median(
                sample["presentation_cycles"] for sample in samples)
            report["frame_budgets_cycles"] = {str(count): count * PAL_FRAME_CYCLES for count in (2, 3, 4)}
            if args.baseline_profile:
                baseline = json.loads(args.baseline_profile.resolve().read_text())
                if not baseline.get("pass"):
                    raise ValueError("Baseline profile did not finish successfully.")
                if "projection_cycles" in baseline:
                    baseline_projection = baseline["projection_cycles"]["mean"]
                else:
                    baseline_projection = sum(baseline["stages"][stage]["mean"]
                                              for stage in ("map", "copy_flip"))
                current_projection = report["projection_cycles"]["mean"]
                report["baseline_comparison"] = {
                    "baseline_profile": str(args.baseline_profile.resolve()),
                    "baseline_program_sha256": baseline["program_sha256"],
                    "baseline_combined_projection_mean_cycles": baseline_projection,
                    "current_combined_projection_mean_cycles": current_projection,
                    "projection_reduction_percent": 100 * (1 - current_projection / baseline_projection),
                    "baseline_average_fps": baseline["average_fps"],
                    "current_average_fps": report["average_fps"],
                }
            report["pass"] = True
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
    print(json.dumps({"pass": report["pass"], "average_fps": report["average_fps"],
                      "stages": report["stages"], "profile": str(output / "profile.json")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, default=HERE / "build/metaballs/metaballs.prg")
    parser.add_argument("--symbols", type=Path, default=HERE / "build/metaballs/metaballs.sym")
    parser.add_argument("--output", type=Path, default=HERE / "build/metaballs/optimization/current-profile")
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/bin/x64sc"))
    parser.add_argument("--baseline-profile", type=Path,
                        help="Compare direct rendering fairly against baseline mapping plus color copying.")
    profile(parser.parse_args())
