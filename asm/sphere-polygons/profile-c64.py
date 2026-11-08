#!/usr/bin/env python3
"""Profile exclusive native instruction costs for polygon character plotting."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import statistics
import subprocess
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("polygon_vice_verifier", HERE / "verify-c64.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def source_map(path):
    root = ET.parse(path).getroot()
    sources = {}
    for line in root.find("Sources").text.splitlines():
        if "," in line:
            index, filename = line.strip().split(",", 1)
            sources[int(index)] = Path(filename)
    mapping = {}
    for block in root.findall(".//Block"):
        for line in (block.text or "").splitlines():
            if not line.strip().startswith("$"):
                continue
            fields = line.strip().split(",")
            mapping[int(fields[0][1:], 16)] = (sources[int(fields[2])], int(fields[3]))
    return mapping


def classifier(mapping, labels):
    lines = (HERE / "raster.asm").read_text().splitlines()
    line_of = lambda text: next(index + 1 for index, line in enumerate(lines) if line.strip() == text)
    face_init = line_of("lda faces_base")
    bounds_clear_first = line_of("!clear_bounds:")
    bounds_clear_last = line_of("bcc !clear_bounds-")
    edge_first = line_of("raster_edge:")
    fill_first = line_of("raster_fill_span:")
    resolve_first = line_of("resolve_screen:")
    clip_first = line_of("!resolved:")

    def category(pc):
        if labels["face_front"] <= pc < labels["vertex_count"]:
            return "face_traversal_cull_bounds"
        info = mapping.get(pc)
        if info is None:
            return "uncategorized"
        source, number = info
        if source.name == "geometry.asm":
            return "geometry_projection_matrix"
        if source.name == "main.asm":
            return "render_driver"
        if source.name != "raster.asm":
            return "uncategorized"
        text = lines[number - 1].strip()
        if number < face_init:
            return "coverage_clear"
        if bounds_clear_first <= number <= bounds_clear_last:
            return "crossing_arrays_clear"
        if number < edge_first:
            return "face_traversal_cull_bounds"
        if number < fill_first:
            return "edge_dda"
        if number < resolve_first:
            return "span_mask_fill"
        if number < clip_first:
            if text.startswith("lda glyph_lut"):
                return "glyph_lut_read"
            if text.startswith("lda coverage") or text == "tay":
                return "glyph_index_prepare"
            if re.match(r"sta \$0[4567]00,x", text):
                return "screen_store"
            return "resolve_setup_loop"
        return "circle_safe_clip"
    return category


def parse_flat(text, labels):
    functions = []
    for line in text.splitlines():
        match = re.match(r"\s*(\d+)\s+[\d.]+%\s+(\d+)\s+[\d.]+%\s+(\S+)", line)
        if not match or int(match[2]) == 0:
            continue
        name = match[3].lstrip(".")
        address = labels.get(name)
        if address is None and re.fullmatch(r"[0-9a-fA-F]{4}", name):
            address = int(name, 16)
        if address is None:
            raise ValueError(f"Cannot resolve profiled function {name}")
        functions.append({"name": name, "address": address, "self_cycles": int(match[2])})
    return functions


def parse_instructions(text):
    rows = []
    for line in text.splitlines():
        match = re.match(r"\s*(\d+)\s+\S+%\s+(\d+)\s+.*?\.C:([0-9a-fA-F]{4})\s+(.*)", line)
        if match:
            rows.append({"cycles": int(match[1]), "executions": int(match[2]),
                         "pc": int(match[3], 16), "disassembly": match[4].strip()})
    stolen = re.search(r"Stolen self\s+(\d+)\s+cycles", text)
    return rows, int(stolen[1]) if stolen else None


def profile(args):
    labels = verifier.labels_from(args.symbols)
    category_of = classifier(source_map(args.debug), labels)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    program = args.program.resolve()
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    command = [str(args.vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100",
               "+warp", "+autostart-warp", "+confirmonexit", "-sounddev", "dummy",
               "+refreshonbreak", "+binarymonitor", "-initbreak", "reset",
               "-autostartprgmode", "1", "-autostart", str(program),
               "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    report = {"pass": False, "program": str(program), "program_sha256": sha256(program.read_bytes()),
              "symbols_sha256": sha256(args.symbols.read_bytes()), "debug_sha256": sha256(args.debug.read_bytes()),
              "source_sha256": {name: sha256((HERE / name).read_bytes()) for name in ("main.asm", "geometry.asm", "raster.asm")},
              "pal": True, "speed_percent": 100, "warp": False, "command": command,
              "scope": "render_start to render_end, excluding presentation wait; profiler instruction cycles exclude VIC stolen cycles, reported separately",
              "categories": {}, "samples": [], "models": {}}
    process = connection = monitor = None
    poses = [(0, 24, 0), (32, 40, 16), (64, 64, 64), (113, 91, 39)][:args.poses]
    with (output / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            report["pid"] = process.pid
            connection = verifier.connect(process, port)
            monitor = verifier.Monitor(connection)
            monitor.run("sidefx off")
            monitor.run(f'load_labels "{args.vice_symbols.resolve()}"')
            (output / "profile-help.txt").write_text(monitor.run("help profile"))
            for resource, expected in (("MachineVideoStandard", 1), ("Speed", 100), ("InitialWarpMode", 0), ("AutostartWarp", 0)):
                if f"{resource}={expected}" not in monitor.run(f'resourceget "{resource}"'):
                    raise AssertionError(f"Unexpected VICE resource {resource}")
            for name in ("render_start", "render_end", "frame_done"):
                monitor.checkpoint(labels[name])

            def arrive(name):
                monitor.run("x")
                registers = monitor.registers()
                if registers["pc"] != labels[name]:
                    raise AssertionError(f"Expected {name}, observed ${registers['pc']:04x}")
                return registers

            arrive("render_start")
            arrive("render_end")
            arrive("frame_done")
            for model in (0, 1):
                for index, (yaw, pitch, roll) in enumerate(poses):
                    name = f"{verifier.MODELS[model]}-{index}"
                    for key, value in (("paused", 1), ("model", model), ("angle_yaw", yaw), ("angle_pitch", pitch), ("angle_roll", roll)):
                        monitor.run(f"> {labels[key]:04x} {value:02x}")
                    started = arrive("render_start")
                    monitor.run("profile on")
                    ended = arrive("render_end")
                    monitor.run("profile off")
                    flat = monitor.run("profile flat 100")
                    (output / f"{name}-flat.txt").write_text(flat)
                    functions = parse_flat(flat, labels)
                    categories, instructions, stolen_self = {}, [], 0
                    for function in functions:
                        text = monitor.run(f"profile disass {function['address']:04x}")
                        filename = f"{name}-{function['name']}.txt"
                        (output / filename).write_text(text)
                        rows, stolen = parse_instructions(text)
                        actual = sum(row["cycles"] for row in rows)
                        if actual != function["self_cycles"]:
                            raise AssertionError(f"Instruction accounting differs from flat self cycles: {function['name']} {actual}/{function['self_cycles']}")
                        function.update({"export": filename, "stolen_self": stolen})
                        if stolen is not None:
                            stolen_self += stolen
                        for row in rows:
                            category = category_of(row["pc"])
                            totals = categories.setdefault(category, {"cycles": 0, "instruction_executions": 0})
                            totals["cycles"] += row["cycles"]
                            totals["instruction_executions"] += row["executions"]
                            instructions.append({**row, "function": function["name"], "category": category})
                    cpu_cycles = sum(category["cycles"] for category in categories.values())
                    render_cycles = ended["clock"] - started["clock"]
                    stolen = render_cycles - cpu_cycles
                    if stolen < 0 or stolen != stolen_self:
                        raise AssertionError(f"CPU/VIC accounting mismatch: render {render_cycles}, instruction {cpu_cycles}, stolen exports {stolen_self}")
                    sample = {"model": model, "name": name, "yaw": yaw, "pitch": pitch, "roll": roll,
                              "render_start": started, "render_end": ended, "render_cycles": render_cycles,
                              "cpu_instruction_cycles": cpu_cycles, "vic_stolen_cycles": stolen,
                              "categories": categories, "functions": functions}
                    (output / f"{name}-instructions.json").write_text(json.dumps(instructions, indent=2) + "\n")
                    report["samples"].append(sample)
                    print(json.dumps({"name": name, "render_cycles": render_cycles, "cpu_instruction_cycles": cpu_cycles,
                                      "vic_stolen_cycles": stolen, "categories": categories}), flush=True)
                    arrive("frame_done")
            for model, name in enumerate(verifier.MODELS):
                samples = [row for row in report["samples"] if row["model"] == model]
                keys = set().union(*(row["categories"] for row in samples))
                means = {key: statistics.mean(row["categories"].get(key, {}).get("cycles", 0) for row in samples) for key in sorted(keys)}
                total = statistics.mean(row["cpu_instruction_cycles"] for row in samples)
                report["models"][name] = {"poses": len(samples), "mean_render_cycles": statistics.mean(row["render_cycles"] for row in samples),
                    "mean_cpu_instruction_cycles": total, "mean_vic_stolen_cycles": statistics.mean(row["vic_stolen_cycles"] for row in samples),
                    "mean_category_cycles": means, "category_cpu_percent": {key: value * 100 / total for key, value in means.items()}}
            if sha256(program.read_bytes()) != report["program_sha256"]:
                raise AssertionError("PRG changed during profiling.")
            for name, digest in report["source_sha256"].items():
                if sha256((HERE / name).read_bytes()) != digest:
                    raise AssertionError(f"Source changed during profiling: {name}")
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
    print(json.dumps({"pass": report["pass"], "profile": str(output / "profile.json"), "models": report["models"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, default=HERE / "build/polygon-spheres.prg")
    parser.add_argument("--symbols", type=Path, default=HERE / "build/main.sym")
    parser.add_argument("--vice-symbols", type=Path, default=HERE / "build/main.vs")
    parser.add_argument("--debug", type=Path, default=HERE / "build/polygon-spheres.dbg")
    parser.add_argument("--output", type=Path, default=HERE / "build/char-cpu-profile")
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    parser.add_argument("--poses", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.poses <= 4:
        parser.error("--poses must be 1..4")
    profile(args)
