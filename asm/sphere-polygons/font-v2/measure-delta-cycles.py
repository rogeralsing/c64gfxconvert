#!/usr/bin/env python3
"""Execute the existing grouped decoder on the latest smaller-sphere corpus."""

import hashlib
import json
from pathlib import Path
import re
import statistics

from py65.devices.mpu6502 import MPU


HERE = Path(__file__).resolve().parent
PLAYER = HERE / "large-benchmark/build/grouped-native/analytic/hybrid-front"
SOURCE = HERE / "build/settings-164-html25"
OUTPUT = HERE / "build/huffman-study"


def main():
    program = (PLAYER / "player.prg").read_bytes()
    labels = {name: int(value, 16) for name, value in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", (PLAYER / "main.sym").read_text())}
    payload = (SOURCE / "hybrid.bin").read_bytes()
    index = json.loads((SOURCE / "hybrid-index.json").read_text())
    frames = (SOURCE / "reference.frames").read_bytes()
    cpu = MPU()
    address = int.from_bytes(program[:2], "little")
    cpu.memory[address:address + len(program) - 2] = program[2:]
    measurements = []
    for pose, record in enumerate(index):
        previous = frames[pose * 1000:(pose + 1) * 1000]
        target_pose = (pose + 1) % len(index)
        target = frames[target_pose * 1000:(target_pose + 1) * 1000]
        data = payload[record["offset"]:record["offset"] + record["bytes"]]
        cpu.memory[0x400:0x7e8] = previous
        cpu.memory[0x3000:0x3000 + len(data)] = data
        cpu.memory[2:4] = [0, 0x30]
        cpu.memory[0x1fe:0x200] = [0xff, 0x0f]
        cpu.pc, cpu.sp = labels["decode_grouped"], 0xfd
        cpu.a, cpu.x, cpu.y = 0x73, 0x28, 0x95
        before, steps = cpu.processorCycles, 0
        while cpu.pc != 0x1000:
            cpu.step()
            steps += 1
            if steps > 100000:
                raise AssertionError("Grouped decoder did not return")
        if bytes(cpu.memory[0x400:0x7e8]) != target:
            raise AssertionError(f"Decoded character screen differs at pose {pose}")
        measurements.append({"pose": pose, "sourceBytes": len(data),
                             "instructionCycles": cpu.processorCycles - before})
    cycles = [sample["instructionCycles"] for sample in measurements]
    result = {"pass": True, "frames": len(measurements),
              "programSha256": hashlib.sha256(program).hexdigest(),
              "sourceSha256": hashlib.sha256(payload).hexdigest(),
              "instructionCycles": {"min": min(cycles), "mean": statistics.mean(cycles), "max": max(cycles)},
              "scope": "Existing assembled 6502 grouped decoder, exact screen comparison. CPU instruction clocks only: no VIC stalls, driver, disk loader or presentation. Not an FPS measurement.",
              "samples": measurements}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "delta-apply-cycles.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "samples"}, indent=2))
    return result


if __name__ == "__main__":
    main()
