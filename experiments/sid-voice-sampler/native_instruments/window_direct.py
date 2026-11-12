"""Relocate verified C3 gain windows and pretranslate their SID frequency high.

The caller must supply both measured oscillator windows. This data tool does
not measure ISR timing or produce a native player or listening WAV.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _round_ratio(numerator: int, denominator: int) -> int:
    """Nearest integer, ties to even, without floating-point boundary drift."""
    quotient, remainder = divmod(numerator, denominator)
    return quotient + int(remainder * 2 > denominator or
                          (remainder * 2 == denominator and quotient & 1))


def prepare(out: Path, *, hold_cycles: int, reference_hold_cycles: int,
            arena_start: int | None = None,
            placements: dict[int, int] | None = None,
            source: Path = HERE / "gain-preapplied-504",
            timing_binding: str = "Caller-supplied window; native timing is not verified by this data tool.") -> dict:
    """Create direct frequency-high data and prove every relocated source read.

    ``arena_start`` lays all windows consecutively. Alternatively, ``placements``
    maps every active variant ID to its physical start, allowing a native linker
    to split the data across free RAM regions. Frequency low remains zero.
    """
    if type(hold_cycles) is not int or type(reference_hold_cycles) is not int:
        raise TypeError("Both transfer windows must be integer PAL cycles")
    if hold_cycles <= 0 or reference_hold_cycles <= 0:
        raise ValueError("Transfer windows must be positive")
    if (arena_start is None) == (placements is None):
        raise ValueError("Supply exactly one arena start or explicit variant-placement map")
    source = Path(source).resolve()
    meta = json.loads((source / "metadata.json").read_text())
    old = json.loads((Path(meta["source_study"]) / "metadata.json").read_text())
    raw_frames = (Path(meta["source_study"]) / "frames.bin").read_bytes()
    variants = meta["variants"]
    silent_id = meta["neutral_variant_id"]
    pcm = (source / "window-virtual-pcm.bin").read_bytes()
    expected = (source / "expected-input.bin").read_bytes()
    indices = (source / "frame-indices.bin").read_bytes()
    fields = (source / "frame-fields.bin").read_bytes()
    if _sha(expected) != meta["expected_input_sha256"]:
        raise ValueError("The verified source target changed")

    translation = [_round_ratio(code * reference_hold_cycles, hold_cycles)
                   for code in range(256)]
    if max(translation) > 255:
        raise ValueError("High-byte-only translation would clip; choose a valid transfer window")
    direct = bytes(translation[code] for code in pcm)
    expected_high = bytes(translation[code] for code in expected)
    neutral_high = translation[128]
    startup_count = meta.get("startup_neutral_values", 0)
    expected_latches_high = bytes([neutral_high] * startup_count) + expected_high
    if placements is None:
        placements = {variant["id"]: arena_start + variant["window_offset"]
                      for variant in variants}
    elif set(placements) != set(range(len(variants))):
        raise ValueError("Physical placement map must contain every active variant exactly once")

    # Sparse actual RAM image verifies split placements and modulo16-bit virtual
    # pointers. No bytes before an allocated window are implicitly materialized.
    memory, descriptors = {}, []
    lows, highs = bytearray(silent_id + 1), bytearray(silent_id + 1)
    for variant in variants:
        identifier = variant["id"]
        start = placements[identifier]
        size = variant["window_bytes"]
        if type(start) is not int or not 0 <= start <= start + size - 1 <= 65535:
            raise ValueError("Physical variant lies outside sixteen-bit RAM")
        if start < 0xE000 and start + size > 0xD000:
            raise ValueError("A native SID player needs I/O visible; gain windows cannot overlap$D000–$DFFF")
        if start + size > 0xFFFA:
            raise ValueError("Gain windows cannot overwrite the native interrupt vectors")
        offset = variant["window_offset"]
        for relative, value in enumerate(direct[offset:offset + size]):
            address = start + relative
            if address in memory:
                raise ValueError("Physical gain windows overlap")
            memory[address] = value
        virtual = (start - variant["first_read_index"]) & 65535
        lows[identifier], highs[identifier] = virtual & 255, virtual >> 8
        descriptors.append({**variant, "physical_min": start,
                            "physical_max": start + size - 1,
                            "virtual_base": virtual, "virtual_low": virtual & 255,
                            "virtual_high": virtual >> 8})
    descriptors.append({"id": silent_id, "constant_high": neutral_high,
                        "physical_min": None, "physical_max": None,
                        "virtual_base": None,
                        "contract": "Constant output; never dereference its zero pointer. Keep active source phase/end while muted."})

    phase, ended, active, output = 0, True, None, bytearray()
    reads_by_variant, reads_by_state = Counter(), Counter()
    frame_states = []
    ended_count = muted_count = trigger_count = page_cross_reads = 0
    for tick, (index, count) in enumerate(zip(indices, old["frame_sample_counts_exact"])):
        step, selection = fields[index], fields[256 + index]
        variant_id = selection & 127
        raw_step, raw_selector, raw_gain = raw_frames[tick * 3:tick * 3 + 3]
        assert raw_step == step and bool(selection & 128) == bool(raw_selector & 128)
        if selection & 128:
            if variant_id == silent_id:
                raise ValueError("A silent trigger would lose source-end metadata")
            active, phase, ended = descriptors[variant_id], 0, False
            trigger_count += 1
        phase_before, ended_before = phase, ended
        active_count = audible_count = 0
        until_end = (None if ended or active["loop_start_q8"] is not None else
                     (active["logical_end_q8"] - phase + step - 1) // step)
        for _ in range(count):
            value = neutral_high
            if ended:
                ended_count += 1
            else:
                active_count += 1
                if variant_id == silent_id:
                    if old["gain_levels"][raw_gain] != 0:
                        raise ValueError("An audible source was silently muted")
                    muted_count += 1
                else:
                    descriptor = descriptors[variant_id]
                    if descriptor["source_bank"] != active["source_bank"] or descriptor["gain_id"] != raw_gain:
                        raise ValueError("Gain variant changed the source or volume state")
                    location = phase >> 8
                    if not descriptor["first_read_index"] <= location <= descriptor["last_read_index"]:
                        raise ValueError("Native cursor escaped a retained read window")
                    address = (descriptor["virtual_base"] + location) & 65535
                    if not descriptor["physical_min"] <= address <= descriptor["physical_max"]:
                        raise ValueError("Relocated native cursor reads outside its physical window")
                    value = memory[address]
                    reads_by_variant[variant_id] += 1
                    reads_by_state[index] += 1
                    audible_count += 1
                    # For (zp),Y with the low byte of the source cursor as Y,
                    # this is the extra-cycle condition after high-page bias.
                    page_cross_reads += int((descriptor["virtual_low"] + (location & 255)) > 255)
                phase += step
                if phase >= active["logical_end_q8"]:
                    repeat = active["loop_start_q8"]
                    if repeat is None:
                        ended = True
                    else:
                        phase = repeat + (phase - active["logical_end_q8"]) % (active["logical_end_q8"] - repeat)
            output.append(value)
        frame_states.append({"tick": tick, "state_index": index,
                             "step": step, "variant_id": variant_id,
                             "trigger": bool(selection & 128), "output_count": count,
                             "phase_before_q8": phase_before, "phase_after_q8": phase,
                             "ended_before": ended_before, "ended_after": ended,
                             "source_bank": None if active is None else active["source_bank"],
                             "active_source_samples": active_count,
                             "active_read_count": audible_count,
                             "active_muted_samples": active_count - audible_count,
                             "source_samples_until_end_at_frame_start": until_end})
    if bytes(output) != expected_high:
        raise ValueError("Relocated direct frequency-high stream differs from the declared quantization")
    if set(reads_by_variant) != set(range(len(variants))) or trigger_count != meta["source_triggers"]:
        raise ValueError("Not every gain window/source trigger was exercised")
    errors = [(translation[code] * hold_cycles - code * reference_hold_cycles) / reference_hold_cycles
              for code in expected]
    all_errors = [(translation[code] * hold_cycles - code * reference_hold_cycles) / reference_hold_cycles
                  for code in range(256)]
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for name, content in (("window-direct-high.bin", direct),
                          ("expected-high.bin", expected_high),
                          ("expected-latches-high.bin", expected_latches_high),
                          ("frame-indices.bin", indices), ("frame-fields.bin", fields),
                          ("virtual-bank-low.bin", lows), ("virtual-bank-high.bin", highs)):
        (out / name).write_bytes(content)
    result = {"source": str(source), "sample_period_cycles": 504,
              "reference_hold_cycles": reference_hold_cycles, "hold_cycles": hold_cycles,
              "timing_binding": timing_binding,
              "translation": "frequency_low=0; frequency_high=round_ties_even(virtual_PCM_code×reference_hold_cycles/hold_cycles)",
              "frequency_high_table": translation, "neutral_frequency_high": neutral_high,
              "data_bytes": len(direct), "active_variants": len(variants),
              "score_bytes": len(indices) + len(fields),
              "score_unique_states": meta["score_unique_states"],
              "compact_virtual_pointer_bytes": len(lows) + len(highs),
              "output_values": len(output), "source_triggers": trigger_count,
              "startup_neutral_values": startup_count,
              "expected_latch_values": len(expected_latches_high),
              "expected_latches_high_sha256": _sha(expected_latches_high),
              "direct_data_sha256": _sha(direct), "expected_high_sha256": _sha(expected_high),
              "original_target_sha256": _sha(expected),
              "maximum_stream_equivalent_virtual_code_error": max(map(abs, errors)),
              "rms_stream_equivalent_virtual_code_error": (sum(error * error for error in errors) / len(errors)) ** .5,
              "maximum_all_256_codes_equivalent_error": max(map(abs, all_errors)),
              "native_read_proof": {"passed": True, "nonmuted_reads": sum(reads_by_variant.values()),
                                    "active_muted_constant_outputs": muted_count,
                                    "initial_or_ended_constant_outputs": ended_count,
                                    "variant_reads": dict(sorted(reads_by_variant.items())),
                                    "audible_state_reads": dict(sorted(reads_by_state.items())),
                                    "indirect_Y_page_cross_extra_cycles": page_cross_reads,
                                    "maximum_extra_cycles_per_bank_read": 1,
                                    "frequency_high_stream_exact_after_declared_quantization": True},
              "variants": descriptors,
              "frame_states": frame_states,
              "clock_binding": meta["clock_binding"],
              "scope": "Original source waveform body, filtering, all gain states and pitch cursor retained from the verified504-cycle study. Frequency-high-only transfer adds explicit quantization. This is not native timing, analog quality or listening acceptance."}
    (out / "metadata.json").write_text(json.dumps(result, indent=2) + "\n")
    (out / ".gitignore").write_text("*\n!.gitignore\n!metadata.json\n")
    return result
