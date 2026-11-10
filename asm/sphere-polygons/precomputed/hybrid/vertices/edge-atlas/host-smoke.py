#!/usr/bin/env python3
"""Execute the native PV64 plus sampled-edge atlas and exact character filler."""
import hashlib
import argparse
import json
import pathlib
import re
import statistics
from py65.devices.mpu6502 import MPU


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant', type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent)
    here = parser.parse_args().variant.resolve()
    assets = here.parent / "build/assets"
    build = here / "build"
    labels = {
        name: int(value, 16)
        for name, value in re.findall(
            r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)",
            (build / "main.sym").read_text(),
        )
    }
    prg = (build / "player.prg").read_bytes()
    movie = (build / "native-source.bin").read_bytes()
    atlas = (build / "edge-atlas.ea64").read_bytes()
    screens = (assets / "reference.bin").read_bytes()
    coverages = (assets / "coverage-reference.bin").read_bytes()
    coordinates = (assets / "xy-reference.bin").read_bytes()
    font = (assets / "font.bin").read_bytes()
    assert len(screens) == len(coverages) == 64000
    assert len(coordinates) == 64 * 124
    memory = [0] * 65536
    load = int.from_bytes(prg[:2], "little")
    memory[load:load + len(prg) - 2] = prg[2:]
    immutable = bytes(memory[labels["raster_assets_start"]:labels["animation_end"]])
    cpu = MPU(memory=memory, pc=labels["start"])
    stages = {name: [] for name in ("decode", "clear", "face_edges", "face_fill", "resolve", "render")}
    starts, faces = {}, {3: 0, 4: 0}
    frame = 0
    checked_topology = False
    previous_front = None
    for instruction in range(30000000):
        for name in stages:
            if cpu.pc == labels[name + "_start"]:
                starts[name] = cpu.processorCycles
            if cpu.pc == labels[name + "_end"]:
                assert name in starts, name
                stages[name].append(cpu.processorCycles - starts.pop(name))
        current = memory[labels["frame_index"]]
        if cpu.pc == labels["render_start"]:
            front = memory[labels["front_screen_hi"]] << 8
            previous_front = bytes(memory[front:front + 1024])
            if not checked_topology:
                offset = 12
                for face in range(36):
                    header = movie[offset]
                    offset += 1
                    count = header & 127
                    indices = movie[offset:offset + count]
                    offset += count
                    record = bytes(memory[0x1600 + 12 * face:0x1600 + 12 * (face + 1)])
                    assert record == bytes([count, header >> 7, 0, 0, 0]) + indices + bytes(7 - count)
                assert offset == 180
                checked_topology = True
        if cpu.pc == labels["decode_end"]:
            xy = bytes(value for vertex in range(62)
                       for value in (memory[0x1400 + vertex], memory[0x1440 + vertex]))
            assert xy == coordinates[current * 124:(current + 1) * 124], ("XY", current)
        if cpu.pc == labels["face_edges_start"]:
            count = memory[labels["raster_vertex_count"]]
            index = memory[labels["current_face_index"]]
            assert count in (3, 4)
            assert (memory[0x1580 + (index >> 3)] >> (index & 7)) & 1
            faces[count] += 1
        if cpu.pc == labels["resolve_start"]:
            assert bytes(memory[0x1000:0x1000 + 1000]) == coverages[current * 1000:(current + 1) * 1000], ("coverage", current)
        if cpu.pc == labels["render_end"]:
            front = memory[labels["front_screen_hi"]] << 8
            assert bytes(memory[front:front + 1024]) == previous_front
        if cpu.pc == labels["wait_raster"]:
            low = memory[0x100 + ((cpu.sp + 1) & 255)]
            high = memory[0x100 + ((cpu.sp + 2) & 255)]
            cpu.sp = (cpu.sp + 2) & 255
            cpu.pc = ((low | (high << 8)) + 1) & 65535
            continue
        if cpu.pc == labels["frame_done"]:
            assert current == frame % 64
            front = memory[labels["front_screen_hi"]] << 8
            assert bytes(memory[front:front + 1000]) == screens[current * 1000:(current + 1) * 1000], ("screen", current)
            assert bytes(memory[0x2000:0x2800]) == font
            assert bytes(memory[labels["raster_assets_start"]:labels["animation_end"]]) == immutable
            start = labels["animation"]
            assert bytes(memory[start:start + len(movie)]) == movie
            next_offset = int.from_bytes(atlas[18 + current * 2:20 + current * 2], "little") if current < 63 else int.from_bytes(atlas[10:12], "little")
            assert (memory[0x4c] | (memory[0x4d] << 8)) == labels["atlas_records"] + next_offset
            frame += 1
            if frame == 66:
                break
        cpu.step()
    else:
        raise AssertionError("Native player did not finish64+wrap frames")
    assert len(stages["face_edges"]) == len(stages["face_fill"]) == sum(faces.values())
    assert not starts
    summary = lambda values: dict(samples=len(values), min=min(values), mean=statistics.mean(values), max=max(values))
    manifest = json.loads((assets / "manifest.json").read_text())
    report = {
        "pass": True, "frames": frame, "loopWraps": 1,
        "screenBytesChecked": frame * 1000,
        "coverageBytesChecked": frame * 1000,
        "coordinateBytesChecked": frame * 124,
        "fontAndAllRasterAssetsImmutable": True,
        "visibleTriangleCalls": faces[3], "visibleQuadCalls": faces[4],
        "measurement": "py65 instruction cycles, including actual decoding/raster work; excludes VIC stalls, raster wait and presentation. Not native FPS.",
        "stages": {name: summary(values) for name, values in stages.items()},
        "codeBytes": labels["player_code_end"] - labels["start"],
        "rasterAndFontAssetBytes": 12489,
        "movieBytes": len(movie), "atlasBytes": len(atlas), "pv64Bytes": len(movie)-len(atlas), "expandedTopologyBytes": 432,
        "prgBytes": len(prg),
        "prgSha256": hashlib.sha256(prg).hexdigest(),
        "movieSha256": hashlib.sha256(movie).hexdigest(),
    }
    (build / "host-smoke.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
