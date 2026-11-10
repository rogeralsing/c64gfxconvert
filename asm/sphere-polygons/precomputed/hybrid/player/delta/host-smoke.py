#!/usr/bin/env python3
"""Execute the assembled decoder; this is correctness/instruction cost, not FPS."""
import hashlib
import json
import pathlib
import re
import statistics

from py65.devices.mpu6502 import MPU


def main():
    here = pathlib.Path(__file__).resolve().parent
    build = here / "build"
    shared = here.parent / "build"
    labels = {
        name: int(value, 16)
        for name, value in re.findall(
            r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)",
            (build / "main.sym").read_text(),
        )
    }
    prg = (build / "player.prg").read_bytes()
    asset = (shared / "assets/checker-64-smooth-delta1-lag1.hd64").read_bytes()
    reference = (shared / "reference/checker-64-screen.bin").read_bytes()
    font = (shared / "assets/font.bin").read_bytes()
    assert len(reference) == 64000
    assert len(asset) == labels["animation_end"] - labels["animation"]
    memory = [0] * 65536
    load = int.from_bytes(prg[:2], "little")
    memory[load : load + len(prg) - 2] = prg[2:]
    cpu = MPU(memory=memory, pc=labels["start"])
    frames, render_cycles = [], []
    started = None
    cache = None
    previous_front = None
    for instruction in range(12000000):
        if cpu.pc == labels["invalid_movie"]:
            raise AssertionError(f"Native decoder rejected movie at frame {len(frames)}")
        if cpu.pc == labels["render_start"]:
            started = cpu.processorCycles
            front = memory[labels["front_screen_hi"]] << 8
            previous_front = bytes(memory[front : front + 1024])
            if cache is None:
                startup_cycles = cpu.processorCycles
                cache = bytes(memory[0x1400:0x1800])
                assert cache[:1000] == reference[:1000]
        if cpu.pc == labels["render_end"]:
            assert started is not None
            render_cycles.append(cpu.processorCycles - started)
            front = memory[labels["front_screen_hi"]] << 8
            assert bytes(memory[front : front + 1024]) == previous_front
        if cpu.pc == labels["wait_raster"]:
            # Plain py65 has no VIC raster. Return from the wait subroutine;
            # all render instructions above execute unmodified.
            low = memory[0x100 + ((cpu.sp + 1) & 255)]
            high = memory[0x100 + ((cpu.sp + 2) & 255)]
            cpu.sp = (cpu.sp + 2) & 255
            cpu.pc = ((low | (high << 8)) + 1) & 65535
            continue
        if cpu.pc == labels["frame_done"]:
            frame = memory[labels["frame_index"]]
            assert frame == len(frames) % 64
            front = memory[labels["front_screen_hi"]] << 8
            expected = reference[frame * 1000 : (frame + 1) * 1000]
            assert bytes(memory[front : front + 1000]) == expected, frame
            assert bytes(memory[front + 1000 : front + 1024]) == bytes(24)
            assert bytes(memory[0x1400:0x1800]) == cache
            assert bytes(memory[0x2000:0x2800]) == font
            start = labels["animation"]
            assert bytes(memory[start : start + len(asset)]) == asset
            assert memory[0xD018] == (0x18 if front == 0x0400 else 0x38)
            frames.append(frame)
            if len(frames) == 194:
                break
        cpu.step()
    else:
        raise AssertionError("Native decoder did not complete three loops")
    predictive = [cycles for frame, cycles in zip(frames, render_cycles) if frame]
    key = [cycles for frame, cycles in zip(frames, render_cycles) if not frame]
    summary = lambda values: {
        "min": min(values),
        "mean": statistics.mean(values),
        "max": max(values),
    }
    result = {
        "pass": True,
        "frames": len(frames),
        "comparedScreenBytes": len(frames) * 1000,
        "wraps": sum(frame == 0 for frame in frames) - 1,
        "measurement": "py65 instruction cycles; VIC stalls, raster wait and presentation excluded. Not FPS.",
        "startupInstructionCycles": startup_cycles,
        "renderInstructionCycles": summary(render_cycles),
        "predictiveInstructionCycles": summary(predictive),
        "cachedKeyInstructionCycles": summary(key),
        "codeBytes": labels["delta_code_end"] - labels["start"],
        "hd64Bytes": len(asset),
        "fontBytes": len(font),
        "keyCacheBytes": 1024,
        "fillScratchBytes": 60,
        "assetSha256": hashlib.sha256(asset).hexdigest(),
        "prgSha256": hashlib.sha256(prg).hexdigest(),
    }
    (build / "host-smoke.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
