#!/usr/bin/env python3
"""Profile frozen projected-vertex playback stages with actual PAL VICE clocks."""

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
BASE = HERE.parents[2]
spec = importlib.util.spec_from_file_location("vertex_profile_monitor", BASE / "verify-c64.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)

STAGE_PAIRS = {
    "decode": ("decode_start", "decode_end"),
    "clear": ("clear_start", "clear_end"),
    "face_edges": ("face_edges_start", "face_edges_end"),
    "face_fill": ("face_fill_start", "face_fill_end"),
    "resolve": ("resolve_start", "resolve_end"),
}
BOUNDARIES = ("render_start", "render_end", "frame_done") + tuple(
    label for pair in STAGE_PAIRS.values() for label in pair)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def stats(values):
    if not values:
        return {"samples": 0, "total": 0, "min": None, "median": None, "mean": None, "max": None}
    return {"samples": len(values), "total": sum(values), "min": min(values),
            "median": statistics.median(values), "mean": statistics.mean(values), "max": max(values)}


def load_symbols(path, vertex_count_label):
    labels = {name: int(value, 16) for name, value in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", path.read_text())}
    required = set(BOUNDARIES) | {"frame_index", vertex_count_label}
    missing = required - labels.keys()
    if missing:
        raise ValueError("Missing profiling labels: " + ", ".join(sorted(missing)))
    for name, pair in STAGE_PAIRS.items():
        if labels[pair[0]] == labels[pair[1]]:
            raise ValueError(f"Stage {name} has identical start/end PCs")
    return labels


def profile(args):
    variant = args.variant.resolve()
    program, symbol_file = variant / "build/player.prg", variant / "build/main.sym"
    labels = load_symbols(symbol_file, args.vertex_count_label)
    image = program.read_bytes()
    digest = sha(image)
    if args.expected_program_sha256 and digest != args.expected_program_sha256.lower():
        raise ValueError("PRG SHA-256 differs from the frozen expected program")
    output = (args.output or variant / "build/pal-profile").resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_paths = sorted(path for path in variant.rglob("*.asm") if "build" not in path.relative_to(variant).parts)
    source_hashes = {str(path): sha(path.read_bytes()) for path in source_paths}
    load = int.from_bytes(image[:2], "little")
    embedded = image[2 + labels["animation"] - load:2 + labels["animation_end"] - load]
    candidates = [args.asset.resolve()] if args.asset else [
        variant / "build/native-source.bin",
        variant / "build/assets/spans.sa64",
        HERE / "build/assets/white-delta.pv64",
    ]
    matches = [path for path in candidates if path.is_file() and path.read_bytes() == embedded]
    if not matches:
        raise ValueError("No movie asset matches the animation bytes embedded in this PRG")
    asset = matches[0]
    report = {
        "pass": False, "variant": str(variant), "program": str(program), "program_sha256": digest,
        "symbols_sha256": sha(symbol_file.read_bytes()), "source_sha256": source_hashes,
        "pal_clock_hz": native.PAL_CLOCK, "pal_frame_cycles": native.PAL_FRAME_CYCLES,
        "speed_percent": 100, "warp": False, "requested_frames": args.frames,
        "measurement": "Emulated PAL VICE clocks between instruction-PC boundaries, including VIC bus stalls. No music/IRQ workload. Startup and presentation waiting excluded from render stages.",
        "correctness_scope": "Profiling only; the separate full native verifier owns screen/font/movie and screenshot validation.",
        "stage_labels": {name: list(pair) for name, pair in STAGE_PAIRS.items()},
        "stage_addresses": {name: labels[name] for name in BOUNDARIES}, "samples": [],
    }
    if asset.is_file():
        report.update({"asset": str(asset), "asset_bytes": asset.stat().st_size, "asset_sha256": sha(asset.read_bytes()), "asset_matches_program": True})
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    command = [str(args.vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100",
               "+warp", "+autostart-warp", "+confirmonexit", "-sounddev", "dummy",
               "+refreshonbreak", "+binarymonitor", "-initbreak", "reset",
               "-autostartprgmode", "1", "-autostart", str(program), "-remotemonitor",
               "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    report["command"] = command
    by_pc = {}
    for name in BOUNDARIES:
        by_pc.setdefault(labels[name], []).append(name)
    starts = {pair[0]: name for name, pair in STAGE_PAIRS.items()}
    ends = {pair[1]: name for name, pair in STAGE_PAIRS.items()}

    def boundary_order(name):
        if name == "render_start":
            return 0
        if name == "render_end":
            return 3
        if name == "frame_done":
            return 4
        return 1 if name in ends else 2

    process = connection = monitor = None
    current = face = None
    open_stages = {}
    prior_presentation = None
    events = 0
    with (output / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            report["owned_pid"] = process.pid
            connection = native.connect(process, port)
            monitor = native.Monitor(connection)
            monitor.run("sidefx off")
            monitor.run("bank cpu")
            for resource, expected in (("MachineVideoStandard", 1), ("Speed", 100),
                                       ("InitialWarpMode", 0), ("AutostartWarp", 0)):
                if f"{resource}={expected}" not in monitor.run(f'resourceget "{resource}"'):
                    raise AssertionError(f"Unexpected VICE resource: {resource}")
            for pc in by_pc:
                monitor.checkpoint(pc)

            def read_state(names):
                addresses = [labels[name] for name in names]
                first, last = min(addresses), max(addresses)
                if last - first < 256:
                    data = monitor.dump(output / "last-state.bin", first, last)
                    return {name: data[labels[name] - first] for name in names}
                return {name: monitor.dump(output / f"last-{name}.bin", labels[name], labels[name])[0] for name in names}

            while len(report["samples"]) < args.frames:
                monitor.run("x")
                registers = monitor.registers()
                names = by_pc.get(registers["pc"])
                if names is None:
                    raise AssertionError(f"Unexpected VICE stop at ${registers['pc']:04x}")
                events += 1
                if events > args.frames * 200 + 1000:
                    raise RuntimeError("Profiling boundary budget exceeded")
                for name in sorted(names, key=boundary_order):
                    clock = registers["clock"]
                    if name == "render_start":
                        if current is not None or open_stages or face is not None:
                            raise AssertionError("Unclosed frame/stage at render_start")
                        frame = read_state(["frame_index"])["frame_index"]
                        if frame != len(report["samples"]) % 64:
                            raise AssertionError(f"Unexpected frame order: {frame}")
                        current = {"sequence": len(report["samples"]), "frame": frame,
                                   "render_start": registers, "stages": {}, "stage_calls": {}, "faces": []}
                    elif current is None:
                        # A startup key decode can enter shared routines before
                        # the first timed render. Startup is a separate cost.
                        continue
                    elif name in starts:
                        stage = starts[name]
                        if stage in open_stages:
                            raise AssertionError("Stage started twice: " + stage)
                        if stage == "face_edges":
                            if face is not None:
                                raise AssertionError("Previous face has no completed fill")
                            fields = [args.vertex_count_label]
                            if args.face_index_label in labels:
                                fields.append(args.face_index_label)
                            state = read_state(fields)
                            vertices = state[args.vertex_count_label]
                            if vertices not in (3, 4):
                                raise AssertionError(f"Unexpected checker face size: {vertices}")
                            face = {"order": len(current["faces"]), "vertices": vertices,
                                    "kind": "quad" if vertices == 4 else "triangle"}
                            if args.face_index_label in state:
                                face["topology_index"] = state[args.face_index_label]
                        if stage == "face_fill" and face is None:
                            raise AssertionError("Fill has no associated face")
                        open_stages[stage] = registers
                    elif name in ends:
                        stage = ends[name]
                        start = open_stages.pop(stage, None)
                        if start is None:
                            raise AssertionError("Stage ended without start: " + stage)
                        elapsed = clock - start["clock"]
                        if elapsed < 0:
                            raise AssertionError("VICE clock moved backward")
                        current["stages"][stage] = current["stages"].get(stage, 0) + elapsed
                        current["stage_calls"][stage] = current["stage_calls"].get(stage, 0) + 1
                        if stage.startswith("face_"):
                            face[stage.removeprefix("face_") + "_cycles"] = elapsed
                            if stage == "face_fill":
                                current["faces"].append(face)
                                face = None
                    elif name == "render_end":
                        if open_stages or face is not None:
                            raise AssertionError("Render ended with an open stage/face")
                        for stage in ("decode", "clear", "resolve"):
                            if current["stage_calls"].get(stage) != 1:
                                raise AssertionError(f"Expected one {stage} stage per frame")
                        if current["stage_calls"].get("face_edges", 0) != current["stage_calls"].get("face_fill", 0):
                            raise AssertionError("Edge and fill face counts differ")
                        current["render_end"] = registers
                        current["render_cycles"] = clock - current["render_start"]["clock"]
                        accounted = sum(current["stages"].values())
                        current["driver_unattributed_cycles"] = current["render_cycles"] - accounted
                        if current["driver_unattributed_cycles"] < 0:
                            raise AssertionError("Stage intervals overlap")
                    elif name == "frame_done":
                        if "render_end" not in current:
                            raise AssertionError("Presentation preceded render_end")
                        current["frame_done"] = registers
                        current["post_render_wait_and_flip_cycles"] = clock - current["render_end"]["clock"]
                        if prior_presentation is not None:
                            current["observed_presentation_cycles"] = clock - prior_presentation
                        prior_presentation = clock
                        report["samples"].append(current)
                        print(json.dumps({"frame": current["frame"], "render_cycles": current["render_cycles"],
                                          "stages": current["stages"], "faces": len(current["faces"])}), flush=True)
                        current = None

            rows = report["samples"]
            all_faces = [face for row in rows for face in row["faces"]]
            total_render = sum(row["render_cycles"] for row in rows)
            stage_summary = {name: stats([row["stages"].get(name, 0) for row in rows]) for name in STAGE_PAIRS}
            for summary in stage_summary.values():
                summary["percent_render_clock"] = summary["total"] * 100 / total_render
            report.update({
                "frames_profiled": len(rows), "events": events, "render_cycles": stats([row["render_cycles"] for row in rows]),
                "stage_cycles_per_frame": stage_summary,
                "driver_unattributed_cycles_per_frame": stats([row["driver_unattributed_cycles"] for row in rows]),
                "fill_cycles_per_face": stats([face["fill_cycles"] for face in all_faces]),
                "quad_fill_cycles_per_face": stats([face["fill_cycles"] for face in all_faces if face["vertices"] == 4]),
                "triangle_fill_cycles_per_face": stats([face["fill_cycles"] for face in all_faces if face["vertices"] == 3]),
                "quad_fill_cycles_per_frame": stats([sum(face["fill_cycles"] for face in row["faces"] if face["vertices"] == 4) for row in rows]),
                "triangle_fill_cycles_per_frame": stats([sum(face["fill_cycles"] for face in row["faces"] if face["vertices"] == 3) for row in rows]),
                "edge_cycles_per_face": stats([face["edges_cycles"] for face in all_faces]),
                "observed_presentation_cycles": stats([row["observed_presentation_cycles"] for row in rows if "observed_presentation_cycles" in row]),
                "cadence_scope": "Observed during profiling, not a replacement for the independent all-frame screen/screenshot/FPS verification.",
            })
            if sha(program.read_bytes()) != digest or sha(symbol_file.read_bytes()) != report["symbols_sha256"]:
                raise AssertionError("Program or symbol file changed while profiling")
            for filename, source_digest in source_hashes.items():
                if sha(Path(filename).read_bytes()) != source_digest:
                    raise AssertionError("Source changed while profiling: " + filename)
            if "asset_sha256" in report and sha(asset.read_bytes()) != report["asset_sha256"]:
                raise AssertionError("Asset changed while profiling")
            report["pass"] = True
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
            (output / "profile.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key in (
        "pass", "program_sha256", "frames_profiled", "render_cycles", "stage_cycles_per_frame",
        "quad_fill_cycles_per_face", "quad_fill_cycles_per_frame", "triangle_fill_cycles_per_face")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", type=Path, default=HERE / "player")
    parser.add_argument("--asset", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--frames", type=int, default=64)
    parser.add_argument("--vertex-count-label", default="raster_vertex_count")
    parser.add_argument("--face-index-label", default="current_face_index")
    parser.add_argument("--expected-program-sha256")
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    arguments = parser.parse_args()
    if not 1 <= arguments.frames <= 256:
        parser.error("--frames must be 1..256")
    profile(arguments)
