"""Compile exact fixed-pitch C3 instrument windows from prepared source data.

Each bank is an instrument/step/gain waveform indexed by elapsed note output
count. The caller supplies the fresh compiler intermediate representation;
no combined channel recording, cached runtime or recording is loaded.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

EXPECTED_HIGH_SHA = "37426b47dd1df02925b08ac4ce50d1a36bf3bee9931d71256ca32f5a4d163de0"
EXPECTED_SID3_SHA = "080852a5c0cf96f0e3b00ac856d594015c92a513435ccb5e08816d54cfa267a2"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Arena:
    """Leave runtime at C000 and distributed dispatch at 7000..78ff free."""
    def __init__(self):
        self.regions = [(0x1000, 0x7000), (0x7900, 0xC000)]
        self.position = 0x1000
        self.allocations = []

    def add(self, size: int, name: str, alignment: int = 1) -> int:
        while self.regions:
            low, high = self.regions[0]
            start = (max(low, self.position) + alignment - 1) // alignment * alignment
            if start + size <= high:
                self.position = start + size
                self.allocations.append({"name": name, "start": start, "end": self.position, "bytes": size})
                return start
            self.regions.pop(0)
            if self.regions:
                self.position = self.regions[0][0]
        raise ValueError(f"Fixed C3 data does not fit below C000: {name}, {size} bytes")


def prepare(out: Path, source: dict) -> dict:
    """Emit fixed banks, two137-entry pointers and a compatible12-byte score.

    Fields9/10/11 are bankID, separate0/1 trigger and active prefix. Field5 is
    unchanged output count; fields0..8 remain byte-identical to the baseline.
    The integer elapsed-output cursor resets on trigger, advances for every
    active value including neutral gain, and holds for an ended tail.
    """
    out = Path(out).resolve(); out.mkdir(parents=True, exist_ok=True)
    if not isinstance(source, dict):
        raise TypeError("Fixed-pitch preparation requires the prepared compiler-source dictionary")
    linked, paths = source["linked"], source["paths"]
    linked_dir = Path(paths["linked"])
    c3 = linked["c3"]
    direct = (linked_dir / "c3/window-direct-high.bin").read_bytes()
    expected = (linked_dir / "c3/expected-high.bin").read_bytes()
    expected3 = (linked_dir / "rle/expected-input.bin").read_bytes()
    if sha(expected) != EXPECTED_HIGH_SHA or sha(expected3) != EXPECTED_SID3_SHA:
        raise ValueError("Prepared source inputs differ from the verified native phrase")
    neutral = c3["neutral_frequency_high"]
    source_variants = c3["variants"]
    source_banks = json.loads((Path(paths["c3_model"]) / "metadata.json").read_text())["banks"]
    groups, frames = {}, []
    elapsed, step, note = 0, 0, -1
    for frame in c3["frame_states"]:
        if frame["trigger"]:
            elapsed, step, note = 0, frame["step"], note + 1
        active = frame["active_source_samples"]
        if active and frame["step"] != step:
            raise ValueError("Fixed-pitch banks require constant step while a source is held")
        if frame["phase_before_q8"] != elapsed * step:
            raise ValueError("Original fractional source phase is not note_elapsed*step")
        key = None
        if frame["active_read_count"]:
            variant = source_variants[frame["variant_id"]]
            key = frame["variant_id"], step
            group = groups.setdefault(key, {"first": elapsed, "last": elapsed, "notes": set(), "variant": variant})
            group["first"] = min(group["first"], elapsed)
            group["last"] = max(group["last"], elapsed + active - 1)
            group["notes"].add(note)
        frames.append({**frame, "elapsed_before": elapsed, "elapsed_after": elapsed + active,
                       "source_variant_id": frame["variant_id"], "source_step": step,
                       "note_instance": note, "key": key})
        elapsed += active
        if frame["phase_after_q8"] != elapsed * step:
            raise ValueError("Active/ended prefix count changed original source lifetime")
    keys = sorted(groups)
    ids = {key: index for index, key in enumerate(keys)}
    neutral_id = len(keys)
    if neutral_id >= 256 or note + 1 != 96:
        raise ValueError("Unexpected fixed-bank ID or trigger count")
    for key, group in groups.items():
        variant, pitch_step = group["variant"], key[1]
        body = bytearray()
        for index in range(group["first"], group["last"] + 1):
            location = index * pitch_step >> 8
            if not variant["first_read_index"] <= location <= variant["last_read_index"]:
                raise ValueError("Fixed-pitch expansion escaped an original instrument window")
            body.append(direct[variant["window_offset"] + location - variant["first_read_index"]])
        group["data"] = bytes(body)
        group["constant_neutral"] = set(body) == {neutral}

    arena, segments = Arena(), []
    for allocation in linked["allocations"]:
        name, address, size = allocation["name"], allocation["start"], allocation["bytes"]
        if not (name.startswith("drum-") or name == "triangle-run-page"):
            continue
        content = (linked_dir / f"{address:04x}-{name}.bin").read_bytes()
        relocated = arena.add(size, name, 256 if name == "triangle-run-page" else 1)
        if relocated != address or len(content) != size:
            raise ValueError("SID3 asset placement changed unexpectedly")
        segments.append((address, content, name))
    pointer_low, pointer_high = bytearray(neutral_id + 1), bytearray(neutral_id + 1)
    descriptors, bodies = [], {}
    for key in keys:
        identifier, group = ids[key], groups[key]
        variant, body = group["variant"], group["data"]
        physical = None
        if not group["constant_neutral"]:
            if body not in bodies:
                physical = arena.add(len(body), f"c3-fixed-{identifier:03d}")
                bodies[body] = physical
                segments.append((physical, body, f"c3-fixed-{identifier:03d}"))
            physical = bodies[body]
            virtual = (physical - group["first"]) & 65535
            pointer_low[identifier], pointer_high[identifier] = virtual & 255, virtual >> 8
        descriptor = {"id": identifier, "source_variant_id": key[0], "source_step": key[1],
            "source_bank": variant["source_bank"], "source_instrument": variant["source_instrument"],
            "source_sample_sha256": source_banks[variant["source_bank"]]["source_sample_sha256"],
            "divisor": variant["divisor"], "gain_id": variant["gain_id"], "gain": variant["gain"],
            "first_elapsed_index": group["first"], "last_elapsed_index": group["last"],
            "logical_end_q8": variant["logical_end_q8"], "loop_start_q8": variant["loop_start_q8"],
            "raw_window_bytes": len(body), "constant_neutral": group["constant_neutral"],
            "physical_min": physical, "physical_max": None if physical is None else physical + len(body) - 1,
            "virtual_base": None if physical is None else (physical - group["first"]) & 65535,
            "note_instances": sorted(group["notes"]), "sha256": sha(body)}
        descriptors.append(descriptor)
    descriptors.append({"id": neutral_id, "constant_neutral": True, "constant_high": neutral,
                        "physical_min": None, "physical_max": None, "virtual_base": None})
    original_score = (linked_dir / f'{linked["labels"]["score"]:04x}-score.bin').read_bytes()
    score, patched_frames = bytearray(original_score), []
    for index, frame in enumerate(frames):
        key = frame.pop("key")
        logical = None if key is None else ids[key]
        selected = neutral_id if key is None or groups[key]["constant_neutral"] else logical
        frame.update(variant_id=selected, bank_id=selected, logical_variant_id=logical,
                     active_read_count=frame["active_source_samples"] if selected != neutral_id else 0)
        score[index * 12 + 9:index * 12 + 12] = bytes([selected, int(frame["trigger"]), frame["active_source_samples"]])
        if score[index * 12:index * 12 + 9] != original_score[index * 12:index * 12 + 9]:
            raise ValueError("Fixed-bank conversion changed SID3/SID1 score fields")
        patched_frames.append(frame)
    score_start = arena.add(len(score), "score")
    segments.append((score_start, bytes(score), "score"))
    labels = {"score": score_start, "silence_page": linked["labels"]["silence_page"],
              "triangle_silence": 0, "C3_SILENT_VARIANT": neutral_id}
    for content, name in ((bytes(pointer_low), "c3_bank_low"), (bytes(pointer_high), "c3_bank_high")):
        labels[name] = arena.add(len(content), name)
        segments.append((labels[name], content, name))
    memory = {address + offset: value for address, content, _ in segments for offset, value in enumerate(content)}
    if len(memory) != sum(len(content) for _, content, _ in segments):
        raise ValueError("Fixed-bank data allocations overlap")
    if any(not (0x1000 <= address < 0x7000 or 0x7900 <= address < 0xC000) for address in memory):
        raise ValueError("Fixed-bank data escaped its safe RAM regions")

    # Decode emitted score, pointer bytes and physical data, independent of the
    # old fractional replay. Neutral active spans still advance this cursor.
    replay, cursor, uses = bytearray(), 0, Counter()
    for index in range(1000):
        record = bytes(memory[score_start + index * 12 + field] for field in range(12))
        count, bank, trigger, active = record[5], record[9], record[10], record[11]
        if trigger:
            cursor = 0
        for _ in range(active):
            value = neutral
            if bank != neutral_id:
                pointer = memory[labels["c3_bank_low"] + bank] | memory[labels["c3_bank_high"] + bank] << 8
                address = (pointer + cursor) & 65535
                descriptor = descriptors[bank]
                if not descriptor["physical_min"] <= address <= descriptor["physical_max"]:
                    raise ValueError("Native linear cursor escaped its retained fixed-pitch window")
                value = memory[address]; uses[bank] += 1
            replay.append(value); cursor += 1
        replay.extend(bytes([neutral]) * (count - active))
        if cursor != patched_frames[index]["elapsed_after"]:
            raise ValueError("Patched score changed native cursor/lifetime semantics")
    if bytes(replay) != expected:
        raise ValueError("Fixed-pitch emitted-data replay changed the verified C3 input")
    resident_ids = {descriptor["id"] for descriptor in descriptors if descriptor["physical_min"] is not None}
    if set(uses) != resident_ids:
        raise ValueError("A retained fixed-pitch bank was not exercised")
    for address, content, name in segments:
        (out / f"{address:04x}-{name}.bin").write_bytes(content)
    physical_files = {address: str(out / f"{address:04x}-{name}.bin")
                      for address, _, name in segments}
    for descriptor in descriptors:
        descriptor["file"] = physical_files.get(descriptor["physical_min"])
    header = [".label FRAME_COUNT = 1000", ".label SID1_SUSTAIN = 2", ".label SID2_SUSTAIN = 15",
              ".label SID3_SUSTAIN = 15", ".label SID_OUTPUT_MODE = 15", ".label SID1_PULSE = 1966", ".label SID2_PULSE = 2048"]
    header += [f".label {name} = ${value:04x}" for name, value in labels.items()]
    for address, content, name in sorted(segments):
        header += [f'.pc = ${address:04x} "{name}"', f'.import binary "{out / f"{address:04x}-{name}.bin"}"']
    header += [f".label program_end = ${max(memory) + 1:04x}",
               '.assert "Fixed instrument data must leave C000 runtime free", program_end <= $c000, true']
    (out / "data.asm").write_text("\n".join(header) + "\n")
    for folder in (out / "rle", out / "c3"):
        folder.mkdir(exist_ok=True)
    (out / "rle/expected-input.bin").write_bytes(expected3)
    (out / "expected-input.bin").write_bytes(expected3)
    (out / "expected-high.bin").write_bytes(expected)
    (out / "c3/expected-high.bin").write_bytes(expected)
    (out / "c3/expected-latches-high.bin").write_bytes(bytes([neutral]) + expected)
    fixedmeta = {**c3, "variants": descriptors, "frame_states": patched_frames,
                 "active_variants": neutral_id, "neutral_variant_id": neutral_id,
                 "data_bytes": sum(map(len, bodies)), "compact_virtual_pointer_bytes": len(pointer_low) + len(pointer_high),
                 "score_bytes": 3000, "additional_resident_score_bytes": 0,
                 "score_contract": ["main score field9: full8-bit fixed bank ID", "field10: separate0/1 trigger", "field11: active prefix; field5: output count"],
                 "source_fractional_data_sha256": c3["direct_data_sha256"],
                 "direct_data_sha256": sha(b"".join(body for body, _ in sorted(bodies.items(), key=lambda item: item[1]))),
                 "native_read_proof": {"passed": True, "linear_cursor_physical_reads_exact": True,
                     "frequency_high_stream_exact_after_declared_quantization": True,
                     "nonconstant_reads": sum(uses.values()), "variant_reads": dict(uses),
                     "frame_cursor_snapshots_exact": len(patched_frames)},
                 "method": "Reusable fixed-pitch source-instrument/step/gain windows, indexed by elapsed note output count. No combined channel waveform stored."}
    (out / "c3/metadata.json").write_text(json.dumps(fixedmeta, indent=2) + "\n")
    proof = {"passed": True, "output_values": len(replay), "startup_neutral_values": 1,
             "expected_high_sha256": sha(expected), "roundtrip_sha256": sha(replay),
             "source_sid3_expected_sha256": sha(expected3), "source_triggers": note + 1,
             "all_lifetimes_gains_and_source_reads_exact": True, "held_pitch_changes": 0,
             "all_source_sid3_sid1_score_fields_0_to_8_exact": True,
             "logical_fixed_variants": neutral_id, "resident_nonconstant_variants": len(resident_ids),
             "neutral_variant_id": neutral_id, "raw_window_bytes": sum(len(group["data"]) for group in groups.values()),
             "resident_fixed_wave_bytes": sum(map(len, bodies)), "pointer_bytes": len(pointer_low) + len(pointer_high),
             "windows_used_by_multiple_notes": sum(len(group["notes"]) > 1 for group in groups.values()),
             "removed_unused_c3_score_fields_bytes": 1512,
             "resident_data_bytes": len(memory), "data_end": max(memory) + 1,
             "scope": "Exact data/score/physical-read roundtrip only. Native linear producer timing, full runtime deadlines and actual audio are separately verified."}
    result = {"input": linked["input"], "rows": linked["rows"], "c3": fixedmeta, "rle": linked["rle"],
              "labels": labels, "allocations": arena.allocations, "assets": descriptors,
              "resident_data_bytes": len(memory), "data_end": max(memory) + 1,
              "data_asm": str(out / "data.asm"), "linked_dir": str(out), "proof": proof,
              "paths": {"root": str(out), "data_asm": str(out / "data.asm"),
                        "source": str(Path(paths["root"])), "c3_expected_high": str(out / "c3/expected-high.bin")}}
    (out / "proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    (out / "linked-data.json").write_text(json.dumps(result, indent=2) + "\n")
    (out / ".gitignore").write_text("*\n!.gitignore\n!proof.json\n")
    return result
