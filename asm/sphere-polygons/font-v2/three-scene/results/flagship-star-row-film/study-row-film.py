#!/usr/bin/env python3
"""Measure exact, independently addressable trimmed character rows.

Each frame has 25 ordered records: startColumn8, length8, raw glyph bytes.
Only leading/trailing glyph0 is omitted; internal zeros remain literal data.
This builds host data and proves its bytes. It does not build a C64 player.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import struct


HERE = Path(__file__).resolve().parent
LOCKED_FONT = "1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1"
PRIMARY_REFERENCE = "5c245453149adfa4bafd433efa50b606a614ff3264eac46f0c5a0906bc9b698c"
SECONDARY_REFERENCE = "b14eaae0b1c329d4afdcbcd6d806bcdfd8a04dd907ff3485bf7e5a70c3d2f475"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(file, value):
    file.write_text(json.dumps(value, indent=2) + "\n")


def read_record(data, offset):
    x, length = data[offset:offset + 2]
    assert x <= 39 and length <= 40 and x + length <= 40
    assert length or x == 0
    end = offset + 2 + length
    assert end <= len(data)
    return bytes(x) + data[offset + 2:end] + bytes(40 - x - length), end


def frame_scan_row(data, frame_offsets, frame, row):
    offset = frame_offsets[frame]
    for _ in range(row):
        offset += 2 + data[offset + 1]
    return read_record(data, offset)[0]


def direct_row(data, row_offsets, frame, row):
    return read_record(data, row_offsets[frame * 25 + row])[0]


def measure(name, source, output, expected_reference, original_delta_bytes=None):
    source = source.resolve()
    reference = (source / "reference.frames").read_bytes()
    font = (source / "font.bin").read_bytes()
    assert sha(reference) == expected_reference
    assert sha(font) == LOCKED_FONT and len(font) == 2048
    assert len(reference) % 1000 == 0
    count = len(reference) // 1000
    output.mkdir(parents=True, exist_ok=True)
    stream = bytearray()
    frame_offsets, row_offsets, relative_offsets = [], [], []
    frame_stats, active_lengths = [], []
    blank_rows = active_rows = raw_nonzero = internal_zeros = 0
    for frame in range(count):
        frame_start = len(stream)
        frame_offsets.append(frame_start)
        frame_active = frame_raw = 0
        for row in range(25):
            row_offsets.append(len(stream))
            relative_offsets.append(len(stream) - frame_start)
            original = reference[frame * 1000 + row * 40:frame * 1000 + (row + 1) * 40]
            nonzero = [x for x, code in enumerate(original) if code]
            if nonzero:
                x, end = nonzero[0], nonzero[-1] + 1
                literal = original[x:end]
                stream.extend((x, len(literal)))
                stream.extend(literal)
                active_rows += 1
                frame_active += 1
                frame_raw += len(literal)
                active_lengths.append(len(literal))
                internal_zeros += literal.count(0)
                raw_nonzero += len(literal) - literal.count(0)
            else:
                stream.extend((0, 0))
                blank_rows += 1
        frame_stats.append(dict(frame=frame, bytes=len(stream) - frame_start,
                                rawCharacterBytes=frame_raw, headerBytes=50,
                                activeRows=frame_active, blankRows=25 - frame_active))
    stream = bytes(stream)
    assert len(stream) < 65536, "This study uses 16-bit relocatable byte offsets."
    frame_index = struct.pack("<" + "H" * len(frame_offsets), *frame_offsets)
    direct_index = struct.pack("<" + "H" * len(row_offsets), *row_offsets)
    (output / "rows.bin").write_bytes(stream)
    (output / "frame-offsets16.bin").write_bytes(frame_index)
    (output / "row-offsets16.bin").write_bytes(direct_index)
    (output / "font.bin").write_bytes(font)
    # Read actual encoded files back before independent format decoding.
    actual = (output / "rows.bin").read_bytes()
    frame_index_actual = (output / "frame-offsets16.bin").read_bytes()
    direct_index_actual = (output / "row-offsets16.bin").read_bytes()
    frames_actual = struct.unpack("<" + "H" * count, frame_index_actual)
    rows_actual = struct.unpack("<" + "H" * (count * 25), direct_index_actual)
    decoded = bytearray()
    for frame in range(count):
        cursor = frames_actual[frame]
        for row in range(25):
            assert cursor == rows_actual[frame * 25 + row]
            expanded, cursor = read_record(actual, cursor)
            assert expanded == direct_row(actual, rows_actual, frame, row)
            assert expanded == frame_scan_row(actual, frames_actual, frame, row)
            decoded.extend(expanded)
        assert cursor == (frames_actual[frame + 1] if frame + 1 < count else len(actual))
    assert bytes(decoded) == reference
    assert (output / "font.bin").read_bytes() == font
    overflow = [dict(frame=i // 25, row=i % 25, offset=value)
                for i, value in enumerate(relative_offsets) if value > 255]
    if not overflow:
        (output / "row-relative-offsets8.bin").write_bytes(bytes(relative_offsets))
    frame_sizes = [record["bytes"] for record in frame_stats]
    raw_bytes = sum(record["rawCharacterBytes"] for record in frame_stats)
    pointer_options = {
        "framePointer16": dict(valid=True, indexBytes=len(frame_index),
                               totalBytes=len(actual) + len(frame_index),
                               access="Locate frame by 16-bit offset, then parse at most25 ordered row headers."),
        "framePointer16AndRowOffset8": dict(valid=not overflow,
                                            indexBytesIfValid=count * 27,
                                            totalBytesIfValid=len(actual) + count * 27,
                                            maximumRelativeOffset=max(relative_offsets),
                                            overflowingRows=len(overflow),
                                            affectedFrames=len({r["frame"] for r in overflow}),
                                            overflowExamples=overflow[:8]),
        "directRowPointer16": dict(valid=True, indexBytes=len(direct_index),
                                   totalBytes=len(actual) + len(direct_index),
                                   access="One independent16-bit byte offset per row; no separate frame pointer needed.")
    }
    fixed_subtotals = []
    for variant in ("framePointer16", "directRowPointer16"):
        for screens in (1, 2):
            data_bytes = pointer_options[variant]["totalBytes"]
            fixed_subtotals.append(dict(index=variant, screenBuffers=screens,
                                        movieAndIndexBytes=data_bytes, fontBytes=len(font),
                                        workScreenBytes=screens * 1024,
                                        subtotalBytes=data_bytes + len(font) + screens * 1024))
    for screens in (1, 2):
        data_bytes = pointer_options["framePointer16"]["totalBytes"]
        fixed_subtotals.append(dict(index="framePointer16WithTenFrameRowCache",
                                    screenBuffers=screens, movieAndIndexBytes=data_bytes,
                                    fontBytes=len(font), workScreenBytes=screens * 1024,
                                    rowPointerCacheBytes=500,
                                    subtotalBytes=data_bytes + len(font) + screens * 1024 + 500))
    result = dict(name=name, source=str(source), sourceFrames=count,
                  uncompressedCharacterBytes=len(reference),
                  format="25 ordered rows per frame; x8,length8,rawGlyphs[length]. Empty row is0,0. Only external glyph0 is trimmed.",
                  rawCharacterBytes=raw_bytes, rawNonzeroGlyphBytes=raw_nonzero,
                  preservedInternalZeroBytes=internal_zeros, headerBytes=count * 50,
                  rowDataBytes=len(actual), activeRows=active_rows, blankRows=blank_rows,
                  activeRowHeaderBytes=active_rows * 2, blankRowHeaderBytes=blank_rows * 2,
                  meanBytesPerFrame=statistics.mean(frame_sizes),
                  minBytesPerFrame=min(frame_sizes), maxBytesPerFrame=max(frame_sizes),
                  framesExceeding255Bytes=sum(size > 255 for size in frame_sizes),
                  activeSpanMean=statistics.mean(active_lengths), activeSpanMax=max(active_lengths),
                  indexes=pointer_options, fontBytes=len(font), frameStats=frame_stats,
                  rowPointerCache=dict(historyFrames=10, rowsPerFrame=25,
                                       bytesPerPointer=2, runtimeBytes=500,
                                       storedIndexBytes=len(frame_index),
                                       update="Parse25 ordered records once per newly admitted movie frame; replace the oldest of ten pointer sets.",
                                       scope="Host-proven lookup concept. Native implementation and timing remain unbuilt."),
                  roundtrip=dict(passed=True, frames=count, characterBytes=len(reference),
                                 independentRowFetches=count * 25, fontUnchanged=True),
                  headerPacking=dict(byteAlignedBytesPerRow=2, separateFieldsBits=12,
                                     validCanonicalSpans=821, minimumInformationBits=10,
                                     oneByteCanRepresentAllSpans=False,
                                     note="x and length need6bits each if independent; byte-aligned records still need2bytes. Even exploiting x+length<=40 gives821 legal spans including blank, more than256."),
                  fixedMemorySubtotals=fixed_subtotals,
                  memoryScope="These are movie/index/font/screen subtotals only. Native code, zero page, playback, row selection tables and scratch are unbuilt/unmeasured. Color RAM is separate. No FPS or total native RAM claim.",
                  hashes=dict(reference=sha(reference), font=sha(font), rows=sha(actual),
                              frameOffsets16=sha(frame_index_actual), rowOffsets16=sha(direct_index_actual)))
    if original_delta_bytes is not None:
        baseline = original_delta_bytes + count * 2
        result["existingExactDelta"] = dict(payloadBytes=original_delta_bytes, pointerBytes=count * 2,
                                              movieAndIndexBytes=baseline,
                                              rowDataPayloadIncrease=len(actual) - original_delta_bytes)
        result["bufferReplacementEstimate"] = dict(
            oldHistoryScreenBuffers=11, oldWorkScreenBytes=11264,
            oneOutputScreen=dict(workBytes=1024, releasedBufferBytes=10240),
            twoOutputScreens=dict(workBytes=2048, releasedBufferBytes=9216),
            note="Potential allocation change only; an independent-row renderer has not been implemented. Extra row-film bytes and indexes must also fit. No native RAM savings certified.")
    write_json(output / "study.json", result)
    return result, actual, frames_actual, rows_actual, reference


def prove_wave_composites(encoded, frame_offsets, row_offsets, reference, output):
    # Intro is implicit blank0; source frames1..96 repeat. This includes the
    # closing1 after each of three full loops, and ten initially blank histories.
    def pose(serial):
        return 0 if serial <= 0 else 1 + (serial - 1) % 96

    digest = hashlib.sha256()
    records = []
    # Ten histories need only500B of row pointers, rather than ten1000-character
    # images. Initial zero pointers select the known empty record of blank0.
    assert encoded[:2] == bytes(2)
    cache = [[0] * 25 for _ in range(10)]
    pointer_updates = 0
    for serial in range(290):
        phase = serial % 96
        if serial:
            cursor = frame_offsets[pose(serial)]
            for row in range(25):
                cache[serial % 10][row] = cursor
                cursor += 2 + encoded[cursor + 1]
                pointer_updates += 1
        expected, fetched, scanned, cached = bytearray(), bytearray(), bytearray(), bytearray()
        source_poses, ages = [], []
        for row in range(25):
            age = math.floor(4.5 + 4.5 * math.sin(2 * math.pi * (row / 24 + phase / 96)) + .5)
            source_pose = pose(serial - age)
            ages.append(age)
            source_poses.append(source_pose)
            expected.extend(reference[source_pose * 1000 + row * 40:source_pose * 1000 + (row + 1) * 40])
            fetched.extend(direct_row(encoded, row_offsets, source_pose, row))
            scanned.extend(frame_scan_row(encoded, frame_offsets, source_pose, row))
            cached.extend(read_record(encoded, cache[(serial - age) % 10][row])[0])
        assert fetched == expected and scanned == expected and cached == expected
        digest.update(fetched)
        records.append(dict(serial=serial, phase=phase, latestPose=pose(serial),
                            rowAges=ages, rowSourcePoses=source_poses,
                            compositeSha256=sha(fetched)))
    result = dict(passed=True, compositesVerified=len(records),
                  completeSourceLoops=3, closingTransitionsIncluded=3,
                  independentRawRowFetches=len(records) * 25,
                  characterBytesCompared=len(records) * 1000,
                  frameScanAndDirectIndexesBothExact=True,
                  tenFrameRowPointerCacheExact=True, runtimeRowCacheBytes=500,
                  pointerCacheUpdates=pointer_updates,
                  rowHeaderScansPerNewFrame=25,
                  cacheInitialization="Clear500B so every initial pointer selects blank0's empty first row record; no stored500B seed is needed.",
                  bitmapIdentity="Identical glyph codes with the unchanged locked font imply identical pixels.",
                  formula="floor(4.5+4.5*sin(2*pi*(row/24+phase/96))+.5)",
                  phase="serial%96, initial0; missing histories are blank frame0",
                  compositeStreamSha256=digest.hexdigest(), records=records)
    write_json(output / "wave-composite-proof.json", result)
    return {key: value for key, value in result.items() if key != "records"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, default=HERE / "three-scene/results/flagship-star-ten-buffer")
    parser.add_argument("--secondary", type=Path, default=HERE / "three-scene/results/flagship-star-baked-wave/wave-raster-2")
    parser.add_argument("--output", type=Path, default=HERE / "build/row-film-study")
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    primary, encoded, frame_offsets, row_offsets, reference = measure(
        "original-pal-97", args.primary, output / "original-pal-97", PRIMARY_REFERENCE, 15272)
    primary["waveCompositeProof"] = prove_wave_composites(
        encoded, frame_offsets, row_offsets, reference, output / "original-pal-97")
    write_json(output / "original-pal-97/study.json", primary)
    studies = [primary]
    if args.secondary.exists():
        secondary, *_ = measure("baked-wave-2px-106", args.secondary,
                                output / "baked-wave-2px-106", SECONDARY_REFERENCE)
        studies.append(secondary)
    summary = dict(passed=True, nativePlayerBuilt=False, nativeFps=None,
                   scope="Exact host-side independent-row format measurement; no player or speed claims.",
                   datasets=studies, sourceScriptSha256=sha(Path(__file__).read_bytes()))
    write_json(output / "study.json", summary)
    readme = """# Independent raw-row film study

Each frame contains25 ordered row records: `startColumn8,length8,rawCharacters[length]`.
Only leading/trailing glyph0 is omitted. Internal zeros remain data; a blank row is `0,0`.
The binaries use relocatable little-endian16-bit byte offsets into `rows.bin`.

| Film | Raw glyphs | Row headers | Row data | Frame index | Direct row index |
|---|---:|---:|---:|---:|---:|
"""
    for study in studies:
        readme += (f"| {study['name']} | {study['rawCharacterBytes']} | {study['headerBytes']} | "
                   f"{study['rowDataBytes']} | {study['indexes']['framePointer16']['indexBytes']} | "
                   f"{study['indexes']['directRowPointer16']['indexBytes']} |\n")
    readme += """
The two index columns are alternatives. Frame pointers need a scan through up to25 row
headers to reach a selected row. Direct row pointers locate any row immediately.
The proposed one-byte offsets relative to a frame fail: some row starts exceed255.
Two independently stored6-bit header fields require12bits, hence two byte-aligned bytes.
Even a combined code for all legal nonempty spans plus blank has821 states, exceeding one byte.

Every encoded frame roundtrips exactly through both index methods. The original film also
passes290 sinusoidal history composites, covering three loop closures and initially blank
histories, with no image-history buffers used by the host row fetches. The proof also uses
a500-byte runtime cache: ten histories ×25 rows ×2-byte row pointer, parsing the25 row
records only once per newly admitted film frame. Font bytes remain locked.

For the original97-frame film, the frame-index variant plus that row cache has this subtotal:
23076 movie/index +2048 font +1024 output screen +500 row-pointer cache =26648 bytes.
This avoids storing the4850-byte direct-row index for every frame. The cache concept is
host-proven; its native code, synchronization and speed have not been implemented.

Eleven existing history/work screens occupy11264 bytes. A hypothetical row renderer using
one output screen would use1024 screen bytes (10240 less); two screens would use2048
(9216 less). The row film and indexes are larger than the existing delta film. These are
allocation estimates only: native code, row-selection tables, scratch and FPS are unbuilt.
`fixedMemorySubtotals` in each study separates movie/index/font/screens and excludes those
unknown costs. Color RAM remains a separate allocation.

Run from the development checkout:

```sh
rtk proxy python3 asm/sphere-polygons/font-v2/study-row-film.py
```

`study.json` contains byte counts, hashes and proof summaries. Each dataset directory contains
the actual row stream, both valid alternative indexes, unchanged font and per-frame evidence.
The original dataset additionally contains `wave-composite-proof.json`.
"""
    (output / "README.md").write_text(readme)
    if args.archive:
        archive = args.archive.resolve()
        archive.mkdir(parents=True, exist_ok=True)
        for item in output.iterdir():
            target = archive / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copyfile(item, target)
        shutil.copyfile(Path(__file__), archive / "study-row-film.py")
    print(json.dumps({"passed": True, "output": str(output), "datasets": [
        {key: study[key] for key in ("name", "sourceFrames", "rawCharacterBytes", "headerBytes",
                                    "rowDataBytes", "activeRows", "blankRows", "minBytesPerFrame",
                                    "meanBytesPerFrame", "maxBytesPerFrame")}
        for study in studies]}, indent=2))


if __name__ == "__main__":
    main()
