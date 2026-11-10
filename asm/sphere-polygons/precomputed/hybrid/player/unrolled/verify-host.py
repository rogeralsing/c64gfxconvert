#!/usr/bin/env python3
"""Execute the assembled decoder; PAL/VIC timing remains a separate VICE gate."""
import hashlib
import json
from pathlib import Path
import re
import statistics

from py65.devices.mpu6502 import MPU

HERE = Path(__file__).resolve().parent
image = (HERE / "build/player.prg").read_bytes()
symbols = {name: int(value, 16) for name, value in re.findall(
    r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", (HERE / "build/main.sym").read_text())}
reference = (HERE.parent / "build/reference/checker-64-screen.bin").read_bytes()
memory = [0xa5] * 65536
first = int.from_bytes(image[:2], "little")
memory[first:first + len(image) - 2] = image[2:]
cpu = MPU(memory=memory)
cpu.pc = symbols["start"]


def until(address):
    cycles = cpu.processorCycles
    for _ in range(200000):
        if cpu.pc == address:
            return cpu.processorCycles - cycles
        cpu.step()
    raise RuntimeError(f"No boundary at ${address:04x}; PC=${cpu.pc:04x}")


until(symbols["render_start"])
font = bytes(memory[0x2000:0x2800])
asset = bytes(memory[symbols["animation"]:symbols["animation_end"]])
rows = []
for sequence in range(65):
    frame = sequence % 64
    assert memory[symbols["frame_index"]] == frame
    cycles = until(symbols["render_end"])
    back = memory[symbols["back_screen_hi"]] << 8
    expected = reference[frame * 1000:(frame + 1) * 1000]
    actual = bytes(memory[back:back + 1000])
    if actual != expected:
        cell = next(i for i, (a, b) in enumerate(zip(actual, expected)) if a != b)
        raise AssertionError(f"Frame {frame} cell {cell}: {actual[cell]}/{expected[cell]}")
    assert bytes(memory[0x2000:0x2800]) == font
    assert bytes(memory[symbols["animation"]:symbols["animation_end"]]) == asset
    # Skip only the raster wait call, then execute the real flip/index/wrap code.
    cpu.pc = symbols["render_end"] + 3
    until(symbols["frame_done"])
    assert memory[symbols["frame_index"]] == frame
    assert memory[symbols["front_screen_hi"]] << 8 == back
    counter = memory[symbols["frame_counter"]] | memory[symbols["frame_counter"] + 1] << 8
    assert counter == sequence + 1
    rows.append({"sequence": sequence, "frame": frame, "render_cpu_cycles": cycles})
    until(symbols["render_start"])

report = {"pass": True, "program_sha256": hashlib.sha256(image).hexdigest(),
          "frames_checked": len(rows), "screen_bytes_checked": len(rows) * 1000,
          "loop_63_to_0_checked": True, "font_immutable": True, "asset_immutable": True,
          "measurement": "Assembled NMOS 6502 py65 replay; excludes VIC stalls and raster waiting. Not native FPS.",
          "render_cpu_cycles": {"min": min(row["render_cpu_cycles"] for row in rows),
                                "median": statistics.median(row["render_cpu_cycles"] for row in rows),
                                "mean": statistics.mean(row["render_cpu_cycles"] for row in rows),
                                "max": max(row["render_cpu_cycles"] for row in rows)}, "rows": rows}
(HERE / "build/host-verification.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))
