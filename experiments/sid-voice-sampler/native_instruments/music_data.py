"""Link independent reusable instrument data for the bounded dual-sampler proof.

The original approved SID3 contribution remains exact. This linker allocates
the compact drum windows and triangle run programs separately; it never stores
their sum. Original C3 windows contain pretranslated sample amplitudes only.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
SID = HERE.parent
sys.path[:0] = [str(HERE), str(SID)]
import bass_rle
import compact_s3
import window_direct


class Arena:
    """Keep the distributed interrupt dispatch and visible SID I/O reserved."""

    def __init__(self):
        self.regions = [(0x1000, 0x7000), (0x7900, 0xD000)]
        self.address = self.regions[0][0]
        self.allocations = []

    def allocate(self, size: int, name: str, alignment: int = 1) -> int:
        while self.regions:
            low, high = self.regions[0]
            start = (max(low, self.address) + alignment - 1) // alignment * alignment
            if start + size <= high:
                self.address = start + size
                self.allocations.append({"name": name, "start": start, "end": self.address,
                                         "bytes": size})
                return start
            self.regions.pop(0)
            if self.regions:
                self.address = self.regions[0][0]
        raise ValueError(f"No safe RAM region fits {name}: {size} bytes")


def prepare(out: Path, *, c3_source: Path, frames: int = 1000,
            stem: str = "all", original: Path | None = None) -> dict:
    if frames != 1000 or stem != "all":
        raise ValueError("Link the complete 1,000-frame full-production proof; physical output muting belongs in the runtime")
    out.mkdir(parents=True, exist_ok=True)
    arena = Arena()
    old = Path(original).resolve() if original is not None else SID / "work/hyperbased/linus-mix"
    # The first pass obtains exact instrument-window sizes; the second proves
    # every actual relocated read against the approved original contribution.
    drums = compact_s3.prepare(out / "drums-layout", arena_start=0x1000, original=old)
    placements = {asset["id"]: arena.allocate(asset["bytes"], f'drum-{asset["id"]}')
                  for asset in drums["assets"]}
    drums = compact_s3.prepare(out / "drums", placements=placements, original=old)
    (out / "rle").mkdir(parents=True, exist_ok=True)
    metadata, rows, rle = bass_rle.prepare(old, out / "rle", frames=frames,
                                          stem=stem, compact_drums=drums)
    rle_relocations = {}
    segments = [(asset["physical_min"], Path(asset["file"]).read_bytes(),
                 f'drum-{asset["id"]}') for asset in drums["assets"]]
    for page in rle["run_pages"]:
        start = arena.allocate(256, "triangle-run-page", 256)
        rle_relocations[page["address"]] = start
        segments.append((start, Path(page["file"]).read_bytes(), "triangle-run-page"))

    raw = json.loads((c3_source / "metadata.json").read_text())
    c3_placements = {variant["id"]: arena.allocate(variant["window_bytes"], f'c3-{variant["id"]}')
                     for variant in raw["variants"]}
    c3 = window_direct.prepare(out / "c3", hold_cycles=249, reference_hold_cycles=105,
                              placements=c3_placements, source=c3_source,
                              timing_binding="SID2 release+43, next enable+35 after two intervening 126-cycle NMIs; final enabled oscillator cycle is release+249. First latch is startup neutral; ring values map global SID3 latch indices4,8,...")
    cut = 0
    for count, frame in zip(metadata["frame_sample_counts_exact"], c3["frame_states"]):
        next_cut = cut + count
        first = max(4, (cut + 3) // 4 * 4)
        if frame["output_count"] != len(range(first, next_cut, 4)):
            raise ValueError("C3 source states must follow the actual global SID3 clock phase")
        cut = next_cut
    direct = (out / "c3/window-direct-high.bin").read_bytes()
    for variant in c3["variants"]:
        if variant["physical_min"] is not None:
            offset, size = variant["window_offset"], variant["window_bytes"]
            segments.append((variant["physical_min"], direct[offset:offset + size], f'c3-{variant["id"]}'))

    # Keep the existing score field contract while the bounded integration is
    # measured. Field2 now supplies the independent drum pointer's low byte.
    records = bass_rle._rows((out / "rle/data.asm").read_text())
    for index, record in enumerate(records):
        old_pointer = rle["frame_run_pointers"][index]
        pointer = rle_relocations[old_pointer & 0xFF00] + (old_pointer & 255)
        record[:2] = [pointer & 255, pointer >> 8]
        frame = c3["frame_states"][index]
        record[5] = frame["output_count"]
        record[9:12] = [frame["step"], frame["variant_id"] | (128 if frame["trigger"] else 0),
                         frame["active_source_samples"]]
    score = bytes(value for record in records for value in record)
    score_start = arena.allocate(len(score), "sid3-and-sid1-score")
    segments.append((score_start, score, "score"))
    linked = {"score": score_start}
    for filename, label, alignment in (("frame-indices.bin", "c3_score", 1),
                                       ("frame-fields.bin", "c3_fields", 256),
                                       ("virtual-bank-low.bin", "c3_bank_low", 1),
                                       ("virtual-bank-high.bin", "c3_bank_high", 1)):
        content = (out / "c3" / filename).read_bytes()
        start = arena.allocate(len(content), label, alignment)
        linked[label] = start
        segments.append((start, content, label))

    out.mkdir(parents=True, exist_ok=True)
    for address, content, name in segments:
        (out / f"{address:04x}-{name}.bin").write_bytes(content)
    linked.update(silence_page=drums["assets"][0]["physical_min"], triangle_silence=0)
    memory = {address + i: value for address, content, _ in segments
              for i, value in enumerate(content)}
    assert len(memory) == sum(len(content) for _, content, _ in segments)
    assert not any(0x7000 <= address < 0x7900 or 0xD000 <= address for address in memory)
    lines = [f".label FRAME_COUNT = {frames}", ".label SID1_SUSTAIN = 2",
             ".label SID2_SUSTAIN = 15", ".label SID3_SUSTAIN = 15",
             ".label SID_OUTPUT_MODE = 15", ".label SID1_PULSE = 1966",
             ".label SID2_PULSE = 2048"]
    lines += [f".label {key} = ${value:04x}" for key, value in linked.items()]
    for address, content, name in sorted(segments):
        path = (out / f"{address:04x}-{name}.bin").resolve()
        lines += [f'.pc = ${address:04x} "{name}"', f'.import binary "{path}"']
    lines += [f".label program_end = ${max(memory) + 1:04x}"]
    (out / "data.asm").write_text("\n".join(lines) + "\n")
    result = {"input": metadata, "rows": rows, "c3": c3, "rle": rle,
              "labels": linked, "allocations": arena.allocations,
              "resident_data_bytes": len(memory), "data_end": max(memory) + 1,
              "scope": "Relocated independent instrument data and score only. Native runtime integration is separately verified."}
    (out / "linked-data.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
