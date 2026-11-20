#!/usr/bin/env python3
"""Time a full 256-pose sweep of a wireframe PRG on the PAL VICE clock."""
import argparse
from collections import Counter
import json
from pathlib import Path
import socket
from statistics import mean
import subprocess

from verify_linedrawer import (PAL_CLOCK, PAL_CYCLES_PER_LINE, PAL_LINES, assembly_symbols,
                              load_monitor, sha, symbol)


def checkpoints(program):
    symbols = assembly_symbols(program.parent)
    code = program.read_bytes()
    origin = int.from_bytes(code[:2], "little")
    loop, edge = (symbol(symbols, name) for name in ("cubeLoop", "edgeLoop"))
    # The edge stage starts just after the bounds call, including selection
    # of the inside/clipped mesh path. This also locates it in older builds.
    bounds = b"\x20" + symbol(symbols, "rememberCubeBox").to_bytes(2, "little")
    body = code[2 + loop - origin:2 + edge - origin]
    if body.count(bounds) != 1:
        raise ValueError("Could not locate the edge stage after rememberCubeBox")
    return {
        "frame": loop,
        "clear": symbol(symbols, "clearScreenJoints"),
        "position": symbol(symbols, "updateCubePosition"),
        "transform": symbol(symbols, "transformVerts"),
        "cull": symbol(symbols, "findVisibleFaces"),
        "bounds": symbol(symbols, "rememberCubeBox"),
        "edges": loop + body.index(bounds) + 3,
        "show": symbol(symbols, "showFrame"),
        "flip": symbol(symbols, "presentFrame"),
    }


def measure(program, vice):
    pcs = checkpoints(program)
    vm = load_monitor()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    command = [str(vice), "-default", "+saveres", "-minimized", "-pal", "-warp",
               "+autostart-warp", "+confirmonexit", "-sounddev", "dummy", "+refreshonbreak",
               "-initbreak", "reset", "-autostartprgmode", "1", "-autostart", str(program),
               "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    with program.with_suffix(".profile.log").open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=log)
        try:
            with vm.connect(process, port) as connection:
                monitor = vm.Monitor(connection)

                def sample(pc):
                    monitor.run("x")
                    registers = monitor.registers()
                    if registers["pc"] != pc:
                        raise RuntimeError(
                            f"Expected profile checkpoint ${pc:04x}, got ${registers['pc']:04x}")
                    return registers

                monitor.checkpoint(pcs["frame"])
                start = sample(pcs["frame"])
                stages_in_order = [(name, pc) for name, pc in pcs.items() if name != "frame"]
                for _, pc in stages_in_order:
                    monitor.checkpoint(pc)
                frames, fields = [], []
                for index in range(256):
                    frame = start if index == 0 else sample(pcs["frame"])
                    snapshots = {"frame": frame, **{name: sample(pc) for name, pc in stages_in_order}}
                    frames.append({name: point["clock"] for name, point in snapshots.items()})
                    flip = snapshots["flip"]
                    raster = flip["raster"]
                    if 48 < raster < 252:
                        raise RuntimeError(f"Flip outside PAL border at line {raster}")
                    start = flip["clock"] - raster * PAL_CYCLES_PER_LINE - flip["raster_cycle"]
                    fields.append(start // (PAL_LINES * PAL_CYCLES_PER_LINE) + (raster >= 252))
                end = sample(pcs["frame"])["clock"]
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    next_starts = [row["frame"] for row in frames[1:]] + [end]
    totals = [after - row["frame"] for row, after in zip(frames, next_starts)]
    flips = [b["flip"] - a["flip"] for a, b in zip(frames, frames[1:])]
    stages = {
        name: round(mean(row[after] - row[before] for row in frames), 2)
        for name, before, after in (
            ("bufferSetup", "frame", "clear"),
            ("clear", "clear", "position"),
            ("position", "position", "transform"),
            ("rotationAndProjection", "transform", "cull"),
            ("faceCulling", "cull", "bounds"),
            ("bounds", "bounds", "edges"),
            ("edges", "edges", "show"),
        )
    }
    prepare = mean(row["show"] - row["frame"] for row in frames)
    stages["presentAndFrameAdvance"] = round(mean(totals) - prepare, 2)
    return {
        "sha256": sha(program.read_bytes()), "frames": len(frames),
        "edgeCycles": stages["edges"],
        "stageCycles": stages,
        "prepareCycles": round(prepare, 2),
        "fullFrameCycles": round(mean(totals), 2),
        "fieldsBetweenFlips": dict(sorted(Counter(b - a for a, b in zip(fields, fields[1:])).items())),
        "fps": round(PAL_CLOCK / mean(flips), 3),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program", type=Path, help="PRG next to its matching main.sym or main.vs")
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/bin/x64sc"))
    args = parser.parse_args()
    print(json.dumps(measure(args.program.resolve(), args.vice), indent=2))
