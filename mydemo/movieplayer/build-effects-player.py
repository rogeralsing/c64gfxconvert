#!/usr/bin/env python3
"""Build the frozen three-object ECM row-span effects program."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = HERE / "build"
FONT_SHA = "180223a47f20c13a5ca203d00d80cc49db6d3d5504589c02c0ed59d01870043f"


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    assets = json.loads((output / "assets.json").read_text())
    assert assets["passed"] and assets["fontSha256"] == FONT_SHA
    assert all(sha((output / name).read_bytes()) == digest for name, digest in assets["hashes"].items())
    assert [item["name"] for item in assets["objects"]] == ["star-lit", "cube-lit", "ball-lit"]

    # Whole frames stay on one side of I/O. The idle graphics byte at $3fff
    # is reserved, just as $7fff was in the accepted bank-one player.
    low, high, objects, pointers = bytearray(), bytearray(), [], []
    frame_locations, shared_frame_count, shared_frame_bytes = {}, 0, 0
    for source in assets["objects"]:
        raw = (output / source["rowsFile"]).read_bytes()
        offsets = source["frameOffsets"]
        addresses = []
        for frame, start in enumerate(offsets):
            blob = raw[start:offsets[frame + 1] if frame < 48 else len(raw)]
            if blob in frame_locations:
                address = frame_locations[blob]
                shared_frame_count += 1
                shared_frame_bytes += len(blob)
                addresses.append(address)
                pointers.extend(address.to_bytes(2, "little"))
                continue
            address = 0x3200 + len(low)
            if address <= 0x3fff < address + len(blob):
                low.extend(bytes(0x4000 - address))
                address = 0x4000
            if not high and address + len(blob) <= 0xd000:
                low.extend(blob)
            else:
                address = 0xe000 + len(high)
                high.extend(blob)
            assert address + len(blob) <= (0xd000 if address < 0xe000 else 0xfffa)
            frame_locations[blob] = address
            addresses.append(address)
            pointers.extend(address.to_bytes(2, "little"))
        objects.append({**source, "frameAddresses": addresses, "frameOffsetsFile": source["offsetsFile"]})
    assert low[0x3fff - 0x3200] == 0
    (output / "movie-low.bin").write_bytes(low)
    (output / "movie-high.bin").write_bytes(high)
    (output / "frame-pointers.bin").write_bytes(bytes(pointers))
    first = high[:0x7e0]
    rest = high[len(first):]
    (output / "movie-high-first.bin").write_bytes(first)
    (output / "movie-high-rest.bin").write_bytes(rest)

    step_modes, step_objects = [], []
    for obj in range(3):
        for mode in range(6):
            step_modes.extend((mode, 6))
            step_objects.extend((obj, obj))
    step_modes.extend((7, 6, 8, 6))
    step_objects.extend((0, 0, 0, 0))
    (output / "step-mode.bin").write_bytes(bytes(step_modes))
    (output / "step-object.bin").write_bytes(bytes(step_objects))
    wave = (output / "wave-ages.bin").read_bytes()
    wave_packed = wave[:48] + b"".join(wave[(row + 1) * 48 - 2:(row + 1) * 48] for row in range(1, 25))
    assert len(wave_packed) == 96
    assert all(wave_packed[row * 2:row * 2 + 48] == wave[row * 48:(row + 1) * 48] for row in range(25))
    (output / "wave-packed.bin").write_bytes(wave_packed)
    binary_vars = {
        "fontData": "font.bin", "dictionaryScreenData": "dict-screen.bin",
        "dictionaryColorData": "dict-color.bin", "waveData": "wave-packed.bin",
        "hMapData": "h-map.bin", "hSwapData": "h-swap.bin",
        "vMapData": "v-map.bin", "vSwapData": "v-swap.bin",
        "hvMapData": "hv-map.bin", "hvSwapData": "hv-swap.bin",
        "zoomMapData": "zoom-map.bin", "zoomSwapData": "zoom-swap.bin",
        "framePointerData": "frame-pointers.bin", "stepModeData": "step-mode.bin",
        "stepObjectData": "step-object.bin", "lowMovieData": "movie-low.bin",
        "highFirstData": "movie-high-first.bin", "highRestData": "movie-high-rest.bin",
    }
    prelude = [f'.var {name}=LoadBinary("{file}")' for name, file in binary_vars.items()]
    prelude.append(f".const highMovieSize={len(high)}")
    prelude.append(f'.import source "{HERE / "effects-player.asm"}"')
    (output / "main.asm").write_text("\n".join(prelude) + "\n")
    command = [str(Path.home() / ".local/bin/kickass"), "main.asm", "-odir", str(output), "-o", str(output / "player.prg"), "-symbolfile"]
    result = subprocess.run(command, cwd=output, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (output / "build.log").write_text(result.stdout)
    assert result.returncode == 0, result.stdout
    labels = {name: int(value, 16) for name, value in re.findall(r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", (output / "main.sym").read_text())}
    (output / "labels.json").write_text(json.dumps(labels, indent=2) + "\n")
    program = (output / "player.prg").read_bytes()
    load_start = int.from_bytes(program[:2], "little")
    load_end = load_start + len(program) - 2
    assert load_start == 0x0801 and load_end <= 0xd000
    assert labels["high_staging_end"] <= 0x3000
    regions = [{"file": "movie-low.bin", "start": 0x3200, "end": 0x3200 + len(low), "sha256": sha(low)},
               {"file": "movie-high.bin", "start": 0xe000, "end": 0xe000 + len(high), "sha256": sha(high)}]
    staging = [{"file": "movie-high-first.bin", "loadStart": labels["high_staging_first"], "runtimeStart": 0xe000, "bytes": len(first)},
               {"file": "movie-high-rest.bin", "loadStart": labels["high_staging_second"], "runtimeStart": 0xe000 + len(first), "bytes": len(rest)}]
    for segment in staging:
        at = segment["loadStart"] - load_start + 2
        assert program[at:at + segment["bytes"]] == (output / segment["file"]).read_bytes()
    build = {"passed": True, "format": assets["format"], "fontSha256": FONT_SHA,
             "objects": objects, "frameCount": 49, "stepMode": step_modes, "stepObject": step_objects,
             "modeFields": [25 if i & 1 else 501 for i in range(40)],
             "sourceAdvance": 1, "targetFPS": None, "paletteC64": assets["paletteC64"],
             "rowRendering": {
                 "sourceStream": "Indexed within one source row; one boundary check per encoded token",
                 "plotDispatch": "Selected once per row/cache pass; specialized plain, checker, mirrors, zoom and mixed paths",
                 "glyphZeroRuns": "Bulk screen stores without foreground work; checker clipping uses four-cell chunks",
                 "screenClear": "Full clear retained for every mode after sparse-clear inclusive cost regression",
                 "historyCache": "Ten retained physical row-pointer tables; protect all requested hits before filling misses",
                 "nonWaveCache": "Direct one/two-table fill with coherent history tags"},
             "waveTablePacking": {"sourceBytes": len(wave), "runtimeBytes": len(wave_packed),
                                  "rowStride": 2, "all1200SourceLookupsExact": True,
                                  "runtimeFile": "wave-packed.bin", "sha256": sha(wave_packed)},
             "palettePolicy": "Fixed grayscale; source foreground varies per cell and frame",
             "foregroundUpdates": {
                 "shadowStart": 0x0c00, "shadowBytes": 1024,
                 "shadowPolicy": "Retain actual foreground for invisible glyph0; compare final transformed visible foreground while plotting",
                 "skipGlyphZero": True, "queueCount": 16, "positionsPerQueue": 256,
                 "queueStart": labels["color_queue_base"], "queueEnd": labels["color_queue_pool_end"],
                 "queueCountAddress": labels["color_queue_counts"],
                 "changedCountAddress": labels["color_changed_count"],
                 "groupOrder": "Physical 256-cell page, then palette foreground color",
                 "sparseMaxChangedCells": 255, "fallbackAtChangedCells": 256,
                 "fallbackPolicy": "Previously verified top-down full shadow copy",
                 "queueConstructionIncludedInPreparation": True,
                 "queuePayloadInitializedOnDemand": True,
                 "queueStorageIsRuntimeOnly": True},
             "movieBytes": assets["totalRowsBytes"], "moviePhysicalBytes": len(low) + len(high),
             "physicalFrameSharing": {"logicalFrames": 147, "uniqueFrames": len(frame_locations),
                                      "sharedFrames": shared_frame_count, "savedBytes": shared_frame_bytes,
                                      "inputFormatAndLogicalFramesUnchanged": True},
             "sourceRegions": regions, "highStagingBytes": len(high), "stagingSegments": staging,
             "hardwareLoad": {"loadStart": load_start, "loadEnd": load_end, "neverLoadsIoGap": True},
             "memory": {"fontStart": 0x3000, "fontBytes": 512, "screenBuffers": [0x0400, 0x0800],
                        "colorWorkBuffer": 0x0c00, "codeStart": 0x1000, "codeEnd": labels["player_code_end"],
                        "codeBytes": labels["player_code_end"] - 0x1000,
                        "colorQueueStart": labels["color_queue_base"], "colorQueueBytes": 4096,
                        "unusedBelowFont": 0x3000 - labels["high_staging_end"],
                        "unusedHigh": 0xfffa - labels["color_queue_pool_end"],
                        "highMovieToQueuePadding": labels["color_queue_base"] - (0xe000 + len(high))},
             "zoom": assets["zoom"], "programSha256": sha(program),
             "assetsSha256": sha((output / "assets.json").read_bytes()), "nativePlaybackMeasured": False}
    budget_at = labels["preparation_budget"] - load_start + 2
    budget_bytes = list(program[budget_at:budget_at + 27])
    build["preparationBudgets"] = [budget_bytes[index:index + 9] for index in range(0, 27, 9)]
    build["preparationBudgetPolicy"] = "Full 48-pose preparation bound including retained FG2 and cold wave cache; add 12201 full-copy commit cycles, divide by 18456 available PAL CPU cycles, round up and add one safety field"
    build["playerSources"] = {name: sha((HERE / name).read_bytes()) for name in
                              ("effects-player.asm", "effects-row-cache.asm", "build-effects-player.py")}
    (output / "build.json").write_text(json.dumps(build, indent=2) + "\n")
    print(json.dumps({k: build[k] for k in ("passed", "programSha256", "movieBytes", "moviePhysicalBytes", "memory", "hardwareLoad")}, indent=2))


if __name__ == "__main__":
    main()
