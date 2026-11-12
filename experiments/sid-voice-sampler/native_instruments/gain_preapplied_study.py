"""Measure byte-exact, gain-preapplied C3 bank layouts for the bounded study.

This is data preparation, not an alternative player. It preserves the original
504-cycle study's filtering, gain tables, pitch cursor and tracker clock.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare(source: Path, out: Path, hold_cycles: int | None = None) -> dict:
    meta = json.loads((source / "metadata.json").read_text())
    if meta["sample_period_cycles"] != 504:
        raise ValueError("This comparison is bound to the existing 504-cycle study")
    frames = (source / "frames.bin").read_bytes()
    expected = (source / "expected-input.bin").read_bytes()
    gains = (source / "gain-tables.bin").read_bytes()
    banks = meta["banks"]
    waves = {bank["id"]: (source / bank["file"]).read_bytes() for bank in banks}
    intervals = {}
    phase, ended, active = 0, True, None
    reads, triggers = [], 0
    for tick, count in enumerate(meta["frame_sample_counts_exact"]):
        step, selector, gain_id = frames[tick * 3:tick * 3 + 3]
        if selector & 128:
            if meta["gain_levels"][gain_id] == 0:
                raise ValueError("A shared silent variant cannot encode a muted trigger's source bounds")
            active, phase, ended = banks[selector & 127], 0, False
            triggers += 1
        for _ in range(count):
            if ended:
                reads.append(None)
                continue
            location = phase >> 8
            key = active["id"], gain_id
            if meta["gain_levels"][gain_id]:
                bounds = intervals.setdefault(key, [location, location])
                bounds[0], bounds[1] = min(bounds[0], location), max(bounds[1], location)
                reads.append((key, location))
            else:
                # Gain zero still advances the original source phase/bounds.
                reads.append(None)
            phase += step
            if phase >= active["logical_end_q8"]:
                repeat = active["loop_start_q8"]
                if repeat is None:
                    ended = True
                else:
                    phase = repeat + (phase - active["logical_end_q8"]) % (active["logical_end_q8"] - repeat)

    out.mkdir(parents=True, exist_ok=True)
    descriptors, prefix_data, window_data = [], bytearray(), bytearray()
    key_ids = {}
    for key, (first, last) in sorted(intervals.items()):
        bank_id, gain_id = key
        values = bytes(gains[gain_id * 256 + code] for code in waves[bank_id][:last + 1])
        identifier = len(descriptors)
        key_ids[key] = identifier
        descriptors.append({"id": identifier, "source_bank": bank_id,
                            "source_instrument": banks[bank_id]["source_instrument"],
                            "divisor": banks[bank_id]["divisor"],
                            "gain_id": gain_id, "gain": meta["gain_levels"][gain_id],
                            "first_read_index": first, "last_read_index": last,
                            "prefix_offset": len(prefix_data), "prefix_bytes": len(values),
                            "window_offset": len(window_data), "window_bytes": last - first + 1,
                            "logical_end_q8": banks[bank_id]["logical_end_q8"],
                            "loop_start_q8": banks[bank_id]["loop_start_q8"],
                            "page_prefix_bytes": (last + 256) // 256 * 256,
                            "page_window_bytes": ((last + 256) // 256 - first // 256) * 256})
        prefix_data.extend(values)
        window_data.extend(values[first:])
    silent_id = len(descriptors)
    if silent_id >= 128:
        raise ValueError("Variant ID and retrigger bit no longer share one byte")

    # The silent field changes only the read target; active source phase/end
    # survive it. Every actual trigger is audible and carries its source bank.
    packed_frames = []
    for tick in range(meta["tracker_frames"]):
        step, selector, gain_id = frames[tick * 3:tick * 3 + 3]
        key = selector & 127, gain_id
        variant_id = key_ids[key] if meta["gain_levels"][gain_id] else silent_id
        packed_frames.append((step, variant_id | (selector & 128)))
    states = list(dict.fromkeys(packed_frames))
    state_ids = {state: i for i, state in enumerate(states)}
    indices = bytes(state_ids[state] for state in packed_frames)
    fields = bytearray(512)
    for i, state in enumerate(states):
        fields[i], fields[256 + i] = state
    assert [(fields[i], fields[256 + i]) for i in indices] == packed_frames

    def replay(layout: str, arena: bytes) -> bytes:
        phase, ended, active, result = 0, True, None, bytearray()
        for state_index, count in zip(indices, meta["frame_sample_counts_exact"]):
            step, selection = fields[state_index], fields[256 + state_index]
            variant = selection & 127
            if selection & 128:
                active, phase, ended = descriptors[variant], 0, False
            for _ in range(count):
                value = 128
                if not ended:
                    if variant != silent_id:
                        descriptor = descriptors[variant]
                        location = phase >> 8
                        if not descriptor["first_read_index"] <= location <= descriptor["last_read_index"]:
                            raise ValueError("Trimmed variant is read outside its proven interval")
                        origin = descriptor[f"{layout}_offset"]
                        if layout == "window":
                            origin -= descriptor["first_read_index"]
                        value = arena[origin + location]
                    phase += step
                    if phase >= active["logical_end_q8"]:
                        repeat = active["loop_start_q8"]
                        if repeat is None:
                            ended = True
                        else:
                            phase = repeat + (phase - active["logical_end_q8"]) % (active["logical_end_q8"] - repeat)
                result.append(value)
        return bytes(result)

    for layout, arena in (("prefix", prefix_data), ("window", window_data)):
        if replay(layout, arena) != expected:
            raise ValueError(f"{layout} bank replay differs from the existing sampled target")
    direct = bytes(128 if read is None else gains[read[0][1] * 256 + waves[read[0][0]][read[1]]]
                   for read in reads)
    assert direct == expected
    (out / "prefix-virtual-pcm.bin").write_bytes(prefix_data)
    (out / "window-virtual-pcm.bin").write_bytes(window_data)
    (out / "frame-indices.bin").write_bytes(indices)
    (out / "frame-fields.bin").write_bytes(fields)
    (out / "expected-input.bin").write_bytes(expected)
    startup_count = meta.get("startup_neutral_values", 0)
    latches = bytes([128] * startup_count) + expected
    (out / "expected-latches.bin").write_bytes(latches)

    # Explicit proposed descriptor layout, not a claim about an existing ASM:
    # one/two 16-bit virtual bases, 24-bit end, 24-bit loop (zero means one-shot).
    variant_count = len(descriptors) + 1
    score_bytes = len(indices) + len(fields)
    layouts = {}
    for name, size in (("packed_prefix", len(prefix_data)),
                       ("packed_window", len(window_data)),
                       ("page_prefix", sum(d["page_prefix_bytes"] for d in descriptors)),
                       ("page_window", sum(d["page_window_bytes"] for d in descriptors))):
        layouts[name] = {"wave_bytes": size,
                         "one_byte_plus_lut_and_neutral": size + 512 + 256,
                         "two_direct_planes_plus_neutral": size * 2 + 512,
                         "one_byte_total_with_declared_descriptor_and_score": size + 512 + 256 + variant_count * 8 + score_bytes,
                         "two_plane_total_with_declared_descriptor_and_score": size * 2 + 512 + variant_count * 10 + score_bytes}
    frequency = None
    if hold_cycles is not None:
        spec = importlib.util.spec_from_file_location("c3_data", HERE / "c3_data.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        table = module.frequency_table(hold_cycles)
        for layout, arena in (("prefix", prefix_data), ("window", window_data)):
            for name in ("low", "high"):
                (out / f"{layout}-frequency-{name}.bin").write_bytes(bytes(table[name][code] for code in arena))
        (out / "frequency-low.bin").write_bytes(table["low"])
        (out / "frequency-high.bin").write_bytes(table["high"])
        frequency = {key: value for key, value in table.items() if key not in ("low", "high", "words")}
        frequency["binding"] = "Caller-supplied transfer window; this data tool does not measure or validate native ISR timing."

    result = {"source_study": str(source.resolve()), "sample_period_cycles": 504,
              "output_values": len(expected), "source_triggers": triggers,
              "startup_neutral_values": startup_count,
              "expected_latch_values": len(latches),
              "expected_latches_sha256": sha(latches),
              "active_variants": len(descriptors), "neutral_variant_id": silent_id,
              "muted_trigger_count": 0, "gain_levels_unchanged": meta["gain_levels"],
              "score_unique_states": len(states), "score_bytes": score_bytes,
              "score_contract": ["step page", "variant ID bits0..6/retrigger bit7 page", "one state index per tracker tick"],
              "layouts": layouts,
              "descriptor_layout": {"one_byte_bytes_per_variant": 8, "two_plane_bytes_per_variant": 10,
                                    "fields": "16-bit virtual base per plane,24-bit source end,24-bit loop; neutral descriptor included"},
              "window_contract": "Virtual base=allocated segment address−first_read_index. Current20s accesses are proven inside each segment; no per-read subtraction or range test is needed. Unaligned indirect-indexed reads can add one6502cycle on page crossing; native CPU budget must allow it.",
              "silence_contract": "Gain0 and ended sources output128 while an active source cursor keeps advancing. A native mute path must provide constant128 without reading arbitrary memory. No trigger is muted in this phrase.",
              "clock_binding": meta["clock_binding"],
              "loop_wraps_in_phrase": meta["loop_wraps_in_this_phrase"],
              "expected_input_sha256": sha(expected), "prefix_roundtrip_passed": True,
              "window_roundtrip_passed": True, "dictionary_roundtrip_passed": True,
              "independent_existing_bank_gain_replay_passed": True,
              "frequency_translation": frequency, "variants": descriptors,
              "scope": "Byte-exact alternative layouts only. No native playback, new WAV, lower-rate listening acceptance or changed filter/gain/pitch contract."}
    (out / "metadata.json").write_text(json.dumps(result, indent=2) + "\n")
    (out / ".gitignore").write_text("*\n!.gitignore\n!metadata.json\n")
    return result
