#!/usr/bin/env python3
"""Execute single-screen HD64 updates and trace every timed character store."""
import hashlib
import json
from pathlib import Path
import re
import statistics
from py65.devices.mpu6502 import MPU


class Memory(list):
    tracing = False

    def __setitem__(self, address, value):
        if self.tracing and isinstance(address, int):
            assert not 0x0C00 <= address < 0x1000, "Unexpected second-screen write"
            if 0x0400 <= address < 0x07E8:
                self.pending.append((address, value))
        super().__setitem__(address, value)


def main():
    here = Path(__file__).resolve().parent
    build, shared = here / "build", here.parent / "build"
    labels = {name: int(value, 16) for name, value in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", (build / "main.sym").read_text())}
    prg = (build / "player.prg").read_bytes()
    encoded = (build / "native-source.bin").read_bytes()
    reference = (shared / "reference/checker-64-screen.bin").read_bytes()
    font = (shared / "assets/font.bin").read_bytes()
    memory = Memory([0] * 65536)
    load = int.from_bytes(prg[:2], "little")
    memory[load:load + len(prg) - 2] = prg[2:]
    memory.tracing, memory.pending = True, []
    cpu = MPU(memory=memory, pc=labels["start"])
    frames, active, writes, write_trace = [], False, [], []
    for instruction in range(12000000):
        if cpu.pc == labels["invalid_movie"]:
            raise AssertionError(("Native decoder rejected source", len(frames)))
        if cpu.pc == labels["render_start"]:
            active = True
            started, writes = cpu.processorCycles, []
            if not frames:
                startup_cycles = started
        if cpu.pc == labels["render_end"]:
            active = False
            addresses = [write["address"] for write in writes]
            assert all(a < b for a, b in zip(addresses, addresses[1:])), addresses
            assert all(write["pc"] in (labels["literal_store"], labels["repeat_store"]) for write in writes)
            render_cycles = cpu.processorCycles - started
        if cpu.pc == labels["wait_boundary"]:
            # Plain py65 has no VIC. Only bypass the raster polling subroutine.
            low = memory[0x100 + ((cpu.sp + 1) & 255)]
            high = memory[0x100 + ((cpu.sp + 2) & 255)]
            cpu.sp = (cpu.sp + 2) & 255
            cpu.pc = ((low | (high << 8)) + 1) & 65535
            continue
        if cpu.pc == labels["frame_done"]:
            frame = memory[labels["frame_index"]]
            assert frame == len(frames) % 64
            counter = memory[labels["frame_counter"]] | (memory[labels["frame_counter"] + 1] << 8)
            assert counter == len(frames) + 1
            assert bytes(memory[0x0400:0x07E8]) == reference[frame * 1000:(frame + 1) * 1000], frame
            assert bytes(memory[0x07E8:0x0800]) == bytes(24)
            assert bytes(memory[0x2000:0x2800]) == font
            start = labels["animation"]
            assert bytes(memory[start:labels["animation_end"]]) == encoded
            assert memory[labels["front_screen_hi"]] == memory[labels["back_screen_hi"]] == 4
            assert memory[0xD018] == 0x18
            if len(frames) == 0:
                assert not writes, "The cold decoded key must use no timed screen copy"
            row = dict(sequence=len(frames), frame=frame, renderCycles=render_cycles,
                       writes=len(writes), lastStoreCycle=writes[-1]["cycle"] if writes else 0)
            frames.append(row)
            write_trace.append(dict(**row, stores=writes))
            if len(frames) == 194:
                break
        pc = cpu.pc
        memory.pending = []
        cpu.step()
        if active:
            for address, value in memory.pending:
                writes.append(dict(address=address, value=value, pc=pc,
                                   cycle=cpu.processorCycles - started))
    else:
        raise AssertionError("Native playback did not finish three wraps")
    summary = lambda values: dict(min=min(values), mean=statistics.mean(values), max=max(values))
    updates = frames[1:]
    result = dict(
        pass_=True, frames=len(frames), wraps=3, screenBytesCompared=len(frames) * 1000,
        oneScreenOnly=True, timedWritesStrictlyAscending=True, fontAndSourceImmutable=True,
        startupInstructionCycles=startup_cycles,
        updateInstructionCycles=summary([row["renderCycles"] for row in updates]),
        closingInstructionCycles=summary([row["renderCycles"] for row in updates if row["frame"] == 0]),
        characterWritesPerUpdate=summary([row["writes"] for row in updates]),
        codeBytes=labels["front_delta_code_end"] - labels["start"], sourceBytes=len(encoded),
        originalHd64Bytes=labels["closing_delta"] - labels["animation"],
        closingRecordBytes=labels["animation_end"] - labels["closing_delta"],
        fontBytes=2048, fillScratchBytes=60, zeroPageBytes=30, screenBytes=1024,
        prgBytes=len(prg), prgSha256=hashlib.sha256(prg).hexdigest(),
        sourceSha256=hashlib.sha256(encoded).hexdigest(),
        measurement="Assembled6502 instruction cycles and stores; raster waits/VIC stalls bypassed. No nativeFPS or beam safety claim.",
    )
    result["pass"] = result.pop("pass_")
    (build / "host-smoke.json").write_text(json.dumps(result, indent=2) + "\n")
    (build / "write-trace.json").write_text(json.dumps(write_trace) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
