"""Compile reused triangle run programs from score phase and instrument tables.

The source is the accepted software oscillator's note score, never a recording.
Each distinct run program is reused across equal pitch/volume/phase frames.
The native program still reads the independent drum asset and adds its current
triangle level for every output value.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import numpy as np


def _rows(data: str) -> list[list[int]]:
    body = data.split("score:\n", 1)[1].split("program_end:", 1)[0]
    return [[int(value) for value in line[6:].split(",")]
            for line in body.splitlines() if line.startswith(".byte ")]


def prepare(original: Path, out: Path, *, frames: int = 1000,
            stem: str = "all", compact_drums: dict | None = None) -> tuple[dict, list[list[int]], dict]:
    """Write compatible twelve-byte score with two run-pointer fields.

    Field 2 is retained as an unused placeholder. Field 3 selects the same
    drum bytes at relocated addresses, field 4 keeps the 156/157 buffer count,
    and field 5 remains the original trigger as provenance. No run list may
    cross a page; an absolute-X instruction therefore costs four cycles.
    """
    base = original if stem == "all" else original / "stems" / stem
    data = (base / "data.asm").read_text()
    records = _rows(data)[:frames]
    metadata = json.loads((original / "input.json").read_text())
    counts = metadata["frame_sample_counts_exact"][:frames]
    if len(records) != frames:
        raise ValueError("The RLE proof must cover the requested complete frame range")
    triangle_files = re.findall(r'triangle_(\d+):\n.import binary "([^"]+)"', data)
    tables = {0x10 + int(index): np.frombuffer(Path(path).read_bytes(), np.uint8)
              for index, path in triangle_files}
    triangle_count = len(tables)
    if triangle_count != 6:
        raise ValueError("Expected the six frozen triangle-volume pages")
    phase = 0
    programs: dict[bytes, int] = {}
    selected, proof_bass, runs, keys = [], bytearray(), [], Counter()
    for row, count in zip(records, counts):
        step = row[0] + row[1] * 256
        if row[5]:
            phase = 0
        before = phase
        locations = (phase - step * np.arange(1, count + 1, dtype=np.int64)) % 65536
        values = tables[row[2]][locations >> 8]
        phase = int(locations[-1])
        changes = np.r_[np.flatnonzero(values[:-1] != values[1:]) + 1, count]
        program, position = bytearray(), 0
        for end in changes:
            program.extend((int(end), int(values[position])))
            position = int(end)
        if len(program) > 256:
            raise ValueError("A triangle run program exceeds its one-page native index")
        key = bytes(program)
        if key not in programs:
            programs[key] = len(programs)
        selected.append(programs[key])
        runs.append(len(program) // 2)
        keys[step, row[2], before, count] += 1
        proof_bass.extend(values.tobytes())

    # Best-fit decreasing packs short reusable programs without crossing a page.
    # Programs contained inside a longer one can reuse that exact byte slice.
    pages: list[bytearray] = []
    locations: dict[int, tuple[int, int]] = {}
    for program, identifier in sorted(programs.items(), key=lambda item: -len(item[0])):
        embedded = next(((page, bytes(content).find(program)) for page, content in enumerate(pages)
                         if bytes(content).find(program) >= 0), None)
        if embedded is not None:
            locations[identifier] = embedded
            continue
        fits = [page for page, content in enumerate(pages) if len(content) + len(program) <= 256]
        if fits:
            page = max(fits, key=lambda index: len(pages[index]))
        else:
            page = len(pages); pages.append(bytearray())
        offset = len(pages[page]); pages[page].extend(program)
        locations[identifier] = page, offset

    # Removing the no-longer-read triangle pages frees seven pages below the
    # hardware dispatch area. Remaining RLE pages follow the relocated score.
    addresses = list(range(0x6900, 0x7000, 256)) + list(range(0xA800, 0xD000, 256))
    if len(pages) > len(addresses):
        raise ValueError(f"RLE programs need {len(pages)} pages, only {len(addresses)} fit below I/O")
    pointers = []
    for identifier in selected:
        page, offset = locations[identifier]
        pointers.append(addresses[page] + offset)
    replay = bytearray()
    for identifier, count in zip(selected, counts):
        page, offset = locations[identifier]
        content = pages[page]
        y = 0
        while y < count:
            end, value = content[offset:offset + 2]
            if not y < end <= count:
                raise ValueError("Packed triangle run program has an invalid endpoint")
            replay.extend(bytes([value]) * (end - y))
            y = end; offset += 2
    if replay != proof_bass:
        raise ValueError("Packed run programs differ from the independent phase oscillator")
    if stem in ("all", "sid-3"):
        previous = (original / "bass-input.bin").read_bytes()[:sum(counts)]
        if replay != previous:
            raise ValueError("RLE bass differs from the accepted phase-model output")

    # Existing drum assets remain byte-identical. Only their address moves down
    # six pages, replacing the unused triangle tables. Data is not host-mixed.
    header = data.split('.pc = $1000 "Reusable mixer instrument pages"', 1)[0]
    header = header.replace(".label FRAME_COUNT = 1000", f".label FRAME_COUNT = {frames}")
    output = [header.rstrip(), '.pc = $1000 "Unchanged reusable drum pages"']
    drum_files = re.findall(r'drum_(\d+):\n.import binary "([^"]+)"', data)
    drum_pages = {0x10 + triangle_count + int(index): np.frombuffer(Path(path).read_bytes(), np.uint8)
                  for index, path in drum_files}
    mixed_min, mixed_max, offset = 255, 0, 0
    for row, count in zip(records, counts):
        bass = np.frombuffer(proof_bass[offset:offset + count], np.uint8).astype(np.uint16)
        mixed = bass + drum_pages[row[3]][row[4]:].astype(np.uint16)
        mixed_min, mixed_max = min(mixed_min, int(mixed.min())), max(mixed_max, int(mixed.max()))
        offset += count
    if mixed_max > 255:
        raise ValueError("The unrolled ADC kernel requires no unsigned addition overflow")
    if compact_drums is None:
        for index, path in drum_files:
            output += [f"drum_{index}:", f'.import binary "{path}"']
        silence = re.search(r"\.label silence_page = drum_(\d+)", data)[1]
        output += [".label triangle_silence = $0000", f".label silence_page = drum_{silence}"]
    else:
        for asset in compact_drums["assets"]:
            output += [f'.pc = ${asset["physical_min"]:04x} "Unchanged compact drum window"',
                       f'.import binary "{asset["file"]}"']
        output += [".label triangle_silence = $0000",
                   f'.label silence_page = ${compact_drums["assets"][0]["physical_min"]:04x}']
    for page, content in enumerate(pages):
        path = out / f"rle-{page:02d}.bin"
        path.write_bytes(bytes(content).ljust(256, b"\0"))
        output += [f'.pc = ${addresses[page]:04x} "Reusable triangle run programs"',
                   f'.import binary "{path.resolve()}"']
    output += ['.pc = $7900 "Triangle run score"', "score:"]
    for tick, (row, pointer) in enumerate(zip(records, pointers)):
        record = row.copy()
        record[:2] = [pointer & 255, pointer >> 8]
        if compact_drums is None:
            record[3] -= triangle_count
        else:
            drum_pointer = (compact_drums["assets"][0]["physical_min"] if stem == "sid-1" else
                            compact_drums["pointer_low"][tick] + 256 * compact_drums["pointer_high"][tick])
            record[2:4] = [drum_pointer & 255, drum_pointer >> 8]
        output.append(".byte " + ",".join(map(str, record)))
    end = max(0x7900 + 12 * frames, max(addresses[:len(pages)]) + 256)
    output += [f".label program_end = ${end:04x}",
               '.assert "RLE proof must remain below I/O", program_end <= $d000, true']
    (out / "data.asm").write_text("\n".join(output) + "\n")
    expected = (base / "expected-input.bin").read_bytes()[:sum(counts)]
    (out / "expected-input.bin").write_bytes(expected)
    (out / "rle-bass.bin").write_bytes(replay)
    metadata.update(frames=frames, input_codes=sum(counts), duration_s=sum(counts) * 126 / 985248,
                    frame_sample_counts_exact=counts)
    result = {"unique_run_programs": len(programs), "raw_command_bytes": sum(map(len, programs)),
              "packed_pages": len(pages), "packed_bytes": len(pages) * 256,
              "total_runs": sum(runs), "maximum_runs_per_frame": max(runs),
              "mean_runs_per_frame": sum(runs) / frames,
              "estimated_regular_cycles_per_sample": 18,
              "estimated_mean_cycles_per_sample_including_run_loads": 18 + 20 * sum(runs) / sum(counts),
              "note_phase_volume_states": len(keys), "reused_frame_references": frames,
              "constant_frames": sum(run == 1 for run in runs),
              "frame_run_pointers": pointers,
              "run_pages": [{"address": addresses[page], "file": str((out / f"rle-{page:02d}.bin").resolve()),
                             "used_bytes": len(content)} for page, content in enumerate(pages)],
              "program_end": end, "accepted_bass_sha256": hashlib.sha256(replay).hexdigest(),
              "packed_program_replay_exact": True,
              "independent_mixed_code_range": [mixed_min, mixed_max],
              "adc_carry_overflow_impossible": True,
              "compact_drums": compact_drums is not None,
              "method": "Reusable triangle run command lists derived from pitch, volume, phase and buffer length. The native C64 emits triangle levels and mixes each with the unchanged independent drum asset. No mixed PCM or recording is stored."}
    (out / "rle-data-check.json").write_text(json.dumps(result, indent=2) + "\n")
    return metadata, [row[6:] for row in records], result
