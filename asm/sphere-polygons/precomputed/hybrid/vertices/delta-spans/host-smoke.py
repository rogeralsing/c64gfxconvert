#!/usr/bin/env python3
"""Execute dynamic old/new span comparison, retained coverage and dirty resolve."""
import hashlib
import json
from pathlib import Path
import re
import statistics
from py65.devices.mpu6502 import MPU


class Memory(list):
    active = False
    def __setitem__(self, address, value):
        if self.active and isinstance(address, int):
            if 0x1000 <= address < 0x1400:
                self.coverage_writes += 1
            if 0x0400 <= address < 0x07E8:
                self.screen_stores.append(address)
        super().__setitem__(address, value)


def main():
    here = Path(__file__).resolve().parent
    build = here / "build"
    assets = build / "assets"
    refs = here.parent / "build/assets"
    labels = {name: int(value, 16) for name, value in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", (build / "main.sym").read_text())}
    prg = (build / "player.prg").read_bytes()
    reference = (refs / "reference.bin").read_bytes()
    cov_reference = (refs / "coverage-reference.bin").read_bytes()
    font = (assets / "font.bin").read_bytes()
    movie = (assets / "spans.sa64").read_bytes()
    memory = Memory([0xA5] * 65536)
    load = int.from_bytes(prg[:2], "little")
    memory[load:load + len(prg) - 2] = prg[2:]
    immutable = bytes(memory[labels["raster_assets_start"]:labels["animation_end"]])
    cpu = MPU(memory=memory, pc=labels["start"])
    stages = {name: [] for name in ("decode", "clear", "face_edges", "face_fill", "resolve", "flush", "render")}
    starts, frames = {}, []
    primary_stage_counts = None
    counter_wrap_observed = False
    min_flush_margin, max_flush_upper = 10**9, 0
    readword = lambda name: memory[labels[name]] | (memory[labels[name] + 1] << 8)
    for instruction in range(60000000):
        for name in stages:
            if cpu.pc == labels[name + "_start"]:
                starts[name] = cpu.processorCycles
            if cpu.pc == labels[name + "_end"]:
                stages[name].append(cpu.processorCycles - starts.pop(name))
        if cpu.pc == labels["render_start"]:
            memory.active = True
            memory.coverage_writes = 0
            memory.screen_stores = []
        if cpu.pc == labels["resolve_start"]:
            if frames:
                assert memory[labels["display_initialized"]] == 1
            before_resolve = bytes(memory[0x0400:0x07E8])
            frame = memory[labels["frame_index"]]
            actual = bytes(memory[0x1000:0x13E8])
            expected = cov_reference[frame * 1000:(frame + 1) * 1000]
            if actual != expected:
                bad = [i for i in range(1000) if actual[i] != expected[i]]
                raise AssertionError(("coverage", len(frames), frame, bad[:12], [(i, actual[i], expected[i]) for i in bad[:3]]))
            assert memory.coverage_writes == readword("add_masks") + readword("remove_masks")
        if cpu.pc == labels["resolve_end"] and frames:
            assert bytes(memory[0x0400:0x07E8]) == before_resolve, "Hidden resolve changed front screen"
        if cpu.pc == labels["flush_start"]:
            queue_bytes = (memory[6] | (memory[7] << 8)) - 0x1700
            assert 0 <= queue_bytes <= 512
            assert queue_bytes == (3 * readword("screen_writes") if frames else 0)
        if cpu.pc == labels["flush_end"]:
            upper = stages["flush"][-1] + 1075 + 63
            assert upper < 19656
            max_flush_upper = max(max_flush_upper, upper)
        if cpu.pc == labels["wait_boundary"]:
            low = memory[0x100 + ((cpu.sp + 1) & 255)]
            high = memory[0x100 + ((cpu.sp + 2) & 255)]
            cpu.sp = (cpu.sp + 2) & 255
            cpu.pc = ((low | (high << 8)) + 1) & 65535
            continue
        if cpu.pc == labels["frame_done"]:
            frame = memory[labels["frame_index"]]
            assert frame == len(frames) % 64
            actual = bytes(memory[0x0400:0x07E8])
            expected = reference[frame * 1000:(frame + 1) * 1000]
            if actual != expected:
                bad = [i for i in range(1000) if actual[i] != expected[i]]
                raise AssertionError(("screen", len(frames), frame, bad[:12], [(i, actual[i], expected[i]) for i in bad[:3]]))
            assert bytes(memory[0x2000:0x2800]) == font
            assert bytes(memory[labels["raster_assets_start"]:labels["animation_end"]]) == immutable
            assert bytes(memory[labels["animation"]:labels["animation_end"]]) == movie
            assert not any(memory[0x1400:0x147D])
            assert all(a < b for a, b in zip(memory.screen_stores, memory.screen_stores[1:]))
            assert len(memory.screen_stores) == readword("screen_writes")
            frames.append(dict(sequence=len(frames), frame=frame, renderCycles=stages["render"][-1],
                               dirtyCells=readword("dirty_count"), addMasks=readword("add_masks"),
                               removeMasks=readword("remove_masks"), screenWrites=readword("screen_writes"),
                               coverageWrites=memory.coverage_writes, resolveCycles=stages["resolve"][-1],
                               queueBytes=queue_bytes, flushCycles=stages["flush"][-1]))
            if len(frames) == 66:
                # Exercise the actual native16-bit wrap without simulating
                # 65,536 complete updates. The next frame incrementsFFFF→0;
                # the following update must still enqueue every visible write.
                primary_stage_counts = {name: len(values) for name, values in stages.items()}
                memory[labels["frame_counter"]] = 255
                memory[labels["frame_counter"] + 1] = 255
            elif len(frames) == 67:
                assert readword("frame_counter") == 0
                counter_wrap_observed = True
            elif len(frames) == 68:
                assert counter_wrap_observed and readword("frame_counter") == 1
                assert memory[labels["display_initialized"]] == 1
                break
        pc, previous_stores = cpu.pc, len(memory.screen_stores) if memory.active else 0
        cpu.step()
        if memory.active and len(memory.screen_stores) > previous_stores:
            assert pc == labels["visible_store"] or (not frames and pc == labels["screen_store"])
            if pc == labels["visible_store"]:
                address = memory.screen_stores[-1]
                row = (address - 0x0400) // 40
                deadline = (312 - 256 + 51 + row * 8) * 63
                elapsed = cpu.processorCycles - starts["flush"]
                margin = deadline - elapsed - 1075 - 63
                assert margin > 0, ("Queue fetch deadline", len(frames), address, margin)
                min_flush_margin = min(min_flush_margin, margin)
    else:
        raise AssertionError("Incremental renderer did not finish66 frames")
    summarize = lambda values: dict(samples=len(values), min=min(values), mean=statistics.mean(values), max=max(values))
    steady = frames[1:66]
    certificate = json.loads((build / "certificate.json").read_text())
    result = dict(pass_=True, frames=66, totalExecutedFrames=len(frames), forcedCounterWrapFrames=2,
                  forcedCounterWrapPass=counter_wrap_observed,
                  screenBytesCompared=len(frames) * 1000,
                  coverageBytesCompared=len(frames) * 1000, sourceAndFontImmutable=True,
                  noSteadyCoverageClear=True, screenStoresStrictlyAscending=True,
                  boundedFlushWithinOnePalField=True, minConservativeFlushMargin=min_flush_margin,
                  maxFlushWith1075StallsAnd63Jitter=max_flush_upper,
                  stages={name: summarize(values[:primary_stage_counts[name]]) for name, values in stages.items()},
                  steady={name: summarize([row[name] for row in steady]) for name in (
                      "renderCycles", "dirtyCells", "addMasks", "removeMasks", "screenWrites", "coverageWrites", "resolveCycles", "queueBytes", "flushCycles")},
                  codeBytes=labels["player_code_end"] - labels["start"], tableBytes=certificate["tableBytes"],
                  movieBytes=len(movie), prgBytes=len(prg), prgSha256=hashlib.sha256(prg).hexdigest(),
                  measurement="Actual6502 instruction cycles, raster waits bypassed; no VIC stalls or nativeFPS claim.", frameRows=frames)
    result["pass"] = result.pop("pass_")
    (build / "host-smoke.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "frameRows"}, indent=2))


if __name__ == "__main__":
    main()
