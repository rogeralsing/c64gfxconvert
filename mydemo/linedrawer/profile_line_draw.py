#!/usr/bin/env python3
"""Time a full 256-pose sweep of a wireframe PRG on the PAL VICE clock."""
import argparse
from collections import Counter
import json
from pathlib import Path
import socket
from statistics import mean
import subprocess

from verify_linedrawer import PAL_CLOCK, PAL_CYCLES_PER_LINE, PAL_LINES, load_monitor, sha, symbol


def checkpoints(program):
    symbols = program.with_name("main.sym").read_text()
    code = program.read_bytes()
    origin = int.from_bytes(code[:2], "little")
    loop, edge = (symbol(symbols, name) for name in ("cubeLoop", "edgeLoop"))
    # The edge stage starts just after the bounds call, including selection
    # of the inside/clipped mesh path. This also locates it in older builds.
    bounds = b"\x20" + symbol(symbols, "rememberCubeBox").to_bytes(2, "little")
    body = code[2 + loop - origin:2 + edge - origin]
    if body.count(bounds) != 1:
        raise ValueError("Could not locate the edge stage after rememberCubeBox")
    return (loop, loop + body.index(bounds) + 3, symbol(symbols, "showFrame"),
            symbol(symbols, "presentFrame"))


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
                for pc in pcs:
                    monitor.checkpoint(pc)

                def sample(pc):
                    monitor.run("x")
                    registers = monitor.registers()
                    if registers["pc"] != pc:
                        raise RuntimeError(f"Missed profile checkpoint at ${pc:04x}")
                    return registers

                frames, fields = [], []
                for _ in range(256):
                    snapshots = [sample(pc) for pc in pcs]
                    frames.append([s["clock"] for s in snapshots])
                    flip = snapshots[-1]
                    raster = flip["raster"]
                    if 48 < raster < 252:
                        raise RuntimeError(f"Flip outside PAL border at line {raster}")
                    start = flip["clock"] - raster * PAL_CYCLES_PER_LINE - flip["raster_cycle"]
                    fields.append(start // (PAL_LINES * PAL_CYCLES_PER_LINE) + (raster >= 252))
                end = sample(pcs[0])["clock"]
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    next_starts = [row[0] for row in frames[1:]] + [end]
    totals = [after - row[0] for row, after in zip(frames, next_starts)]
    flips = [b[-1] - a[-1] for a, b in zip(frames, frames[1:])]
    return {
        "sha256": sha(program.read_bytes()), "frames": len(frames),
        "edgeCycles": round(mean(row[2] - row[1] for row in frames), 2),
        "prepareCycles": round(mean(row[2] - row[0] for row in frames), 2),
        "fullFrameCycles": round(mean(totals), 2),
        "fieldsBetweenFlips": dict(sorted(Counter(b - a for a, b in zip(fields, fields[1:])).items())),
        "fps": round(PAL_CLOCK / mean(flips), 3),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program", type=Path, help="PRG next to its matching main.sym")
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/bin/x64sc"))
    args = parser.parse_args()
    print(json.dumps(measure(args.program.resolve(), args.vice), indent=2))
