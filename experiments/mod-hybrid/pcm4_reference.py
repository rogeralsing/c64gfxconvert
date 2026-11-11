"""Model four original-sample PCM cursors and verify the C64's DAC byte stream.

The model follows integer cursor, volume-table, error-feedback and one-sample
output-pipeline semantics. Its audio is an offline arithmetic reference, not
emulated analog SID output. The original full MOD reference is reused as-is.
"""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf


HERE = Path(__file__).resolve().parent
PAL_CLOCK = 985248
PCM_RATE = PAL_CLOCK / 256
OUTPUT_RATE = 22050


def pcm_level(value: int) -> int:
    if not 0 <= value <= 64:
        raise ValueError("Original track volume must be in 0..64")
    return min(15, (value * 15 + 32) // 64)


def expected_dac(arrangement: dict) -> tuple[np.ndarray, dict]:
    """Return exact four-bit DAC bytes, including the initial pipeline sample."""
    ticks = arrangement["ticks"]
    if not ticks or any(len(tick["pcm"]) != 4 for tick in ticks):
        raise ValueError("Expected exactly four PCM voices in every tick")
    if abs(arrangement["pcm_rate_hz"] - PCM_RATE) > 1e-7:
        raise ValueError("Expected PAL 256-cycle sample clock")
    mode = arrangement.get("mixing", {}).get("mode", "feedback")
    if mode not in ("feedback", "nearest"):
        raise ValueError(f"Unsupported four-PCM mixing mode: {mode}")
    try:
        output_gain = float(arrangement.get("mixing", {}).get("output_gain", 1.0))
    except (TypeError, ValueError) as error:
        raise ValueError("PCM4 output_gain must be finite and positive") from error
    if not math.isfinite(output_gain) or output_gain <= 0:
        raise ValueError("PCM4 output_gain must be finite and positive")
    if mode == "feedback" and output_gain != 1.0:
        raise ValueError("PCM4 output_gain other than1 requires nearest quantization")
    banks = {}
    bank_receipt = []
    for entry in arrangement["pcm_bank"]:
        raw = Path(entry["data_file"]).read_bytes()
        data = np.frombuffer(raw, dtype=np.uint8)
        if not len(data) or int(data.max()) > 15:
            raise ValueError("Source banks must contain one unsigned nibble per byte")
        start, length = int(entry["loop_start"]), int(entry["loop_length"])
        if length and not 0 <= start < start + length <= len(data):
            raise ValueError("Bank loop exceeds sample data")
        end = start + length if length else len(data)
        banks[int(entry["id"])] = {"data": data, "start": start, "length": length, "end": end,
                                    "loop_target": int(entry.get("loop_target_id", entry["id"] if length else 0))}
        bank_receipt.append({"id": entry["id"], "bytes": len(data), "loop_start": start,
                             "loop_length": length, "base_divisor": entry.get("base_divisor"),
                             "sha256": hashlib.sha256(raw).hexdigest()})
    # Exact midpoint Bresenham rounding, including half-sample ties. Integer
    # 30789/400 avoids floating-point and banker's-rounding differences.
    fixed_ticks = all(abs(tick["duration_s"] - 0.02) <= 1e-8 for tick in ticks)
    if fixed_ticks:
        cuts = (np.arange(len(ticks) + 1, dtype=np.int64) * 30789 + 200) // 400
    else:
        # Independent score-time integration: the model does not import the
        # packer's subdivision or timing implementation.
        elapsed, boundaries = Fraction(0), [0]
        for tick in ticks:
            seconds = (Fraction(5, 2 * int(tick["bpm"])) if "bpm" in tick
                       else Fraction(str(tick["duration_s"])))
            if seconds <= 0 or abs(float(seconds) - tick["duration_s"]) > 1e-8:
                raise ValueError("Tracker tick duration and BPM disagree")
            elapsed += seconds * Fraction(PAL_CLOCK, 256)
            boundaries.append(math.floor(elapsed + Fraction(1, 2)))
        cuts = np.asarray(boundaries, dtype=np.int64)
        if np.any(np.diff(cuts) < 5):
            raise ValueError("Tracker ticks cannot fit four staged voice commits")
    frame_count = int(cuts[-1])
    mixed = np.zeros(frame_count, dtype=np.int16)
    table = np.array([[32 + round((sample - 8) * level / 4) for sample in range(16)]
                      for level in range(16)], dtype=np.int16)
    extended_loops = any("loop_sample" in state for tick in ticks for state in tick["pcm"])
    commit_lead = [8, 6, 4, 2] if extended_loops else [4, 3, 2, 1]
    positions = [0, 0, 0, 0]
    active = [False] * 4
    loaded_ids = [0] * 4
    loop_targets = [0] * 4
    triggers = [0] * 4
    levels = [Counter() for _ in range(4)]
    reads = [0] * 4
    steps = [Counter() for _ in range(4)]
    for index, tick in enumerate(ticks):
        for voice, state in enumerate(tick["pcm"]):
            # The foreground prefetches the next tick. The IRQ commits voice0
            # with four samples left, then voices1/2/3 with three/two/one left
            # in the legacy format. Extended loop-pointer scores commit at
            # eight/six/four/two left so ordinary IRQs recover between commits.
            # The one-sample pipeline makes audible offsets -3/-2/-1/0 in the
            # legacy case and -7/-5/-3/-1 in the extended case.
            # Initial states are all committed before starting the timer;
            # the final state continues through the final output sample.
            start = 0 if index == 0 else int(cuts[index]) - commit_lead[voice]
            end = frame_count if index == len(ticks) - 1 else int(cuts[index + 1]) - commit_lead[voice]
            count = end - start
            instrument, step = int(state["sample"]), int(state["step"])
            if not 0 <= step < 256:
                raise ValueError("Four-PCM backend requires fractional steps below 256")
            level = pcm_level(int(state["volume"]))
            levels[voice][level] += count
            steps[voice][step] += count
            if state["trigger"]:
                triggers[voice] += 1
                loaded_ids[voice] = instrument
                positions[voice] = (int(state.get("offset", 0)) << 8) | int(state.get("offset_fraction", 0))
                active[voice] = bool(instrument)
                loop_targets[voice] = banks[instrument]["loop_target"] if instrument else 0
            if "loop_sample" in state:
                loop_targets[voice] = int(state["loop_sample"])
            if not active[voice] and loaded_ids[voice] and "loop_sample" in state:
                # Paula keeps repeating its silent first word after a one-shot
                # ends. A later loop-pointer update can resume that channel
                # without a new note trigger.
                target_id = loop_targets[voice]
                target = banks.get(target_id)
                if target and target["loop_target"] != target_id:
                    target_id = target["loop_target"]
                    target = banks.get(target_id)
                if target and target["length"]:
                    loaded_ids[voice] = target_id
                    positions[voice] = (target["start"] << 8) | (positions[voice] & 255)
                    active[voice] = True
            if instrument == 0:
                active[voice] = False
            if not active[voice]:
                mixed[start:end] += 32
                continue
            # Keep the current DMA segment and the next loop descriptor
            # independent. A sample-only/portamento row may replace the latter
            # while the former still plays its previous instrument.
            remaining, output_start = count, start
            while remaining:
                bank = banks[loaded_ids[voice]]
                phase = positions[voice] + np.arange(remaining, dtype=np.int64) * step
                sample_index = phase >> 8
                crossing = np.flatnonzero(sample_index >= bank["end"])
                prefix = int(crossing[0]) if len(crossing) else remaining
                if prefix:
                    codes = bank["data"][sample_index[:prefix]]
                    mixed[output_start:output_start + prefix] += table[level, codes]
                    reads[voice] += prefix
                    positions[voice] += prefix * step
                    remaining -= prefix
                    output_start += prefix
                if not remaining:
                    break
                target_id = loop_targets[voice]
                target = banks.get(target_id)
                if target and target["loop_target"] != target_id:
                    target_id = target["loop_target"]
                    target = banks.get(target_id)
                if not target or not target["length"]:
                    active[voice] = False
                    mixed[output_start:output_start + remaining] += 32
                    break
                loaded_ids[voice] = target_id
                positions[voice] = (target["start"] << 8) | (positions[voice] & 255)
    if mode == "nearest":
        with np.errstate(over="ignore"):
            rounded = np.rint(8 + (mixed.astype(np.float64) - 128) * output_gain / 16)
        clipped_output = int(np.sum((rounded < 0) | (rounded > 15)))
        quantized = np.clip(rounded, 0, 15).astype(np.int64)
        accumulator = mixed.astype(np.int64)
        final_residual = 0
        mix_description = "Sum all four lookup values; round8+(sum-128)*output_gain/16 to nearest, ties to even, then clamp0..15. No residual feedback."
    elif mode == "feedback":
        # q[n] = (mixed[n] + residual[n-1]) >> 4. Prefix sums give
        # exactly the same recurrence without a slow Python loop per sample.
        cumulative = np.cumsum(mixed, dtype=np.int64)
        quotient = cumulative >> 4
        quantized = np.diff(np.r_[np.int64(0), quotient])
        residual_before = np.r_[np.int64(0), cumulative[:-1] & 15]
        accumulator = mixed.astype(np.int64) + residual_before
        final_residual = int(cumulative[-1] & 15)
        clipped_output = 0
        mix_description = "Sum all four lookup values plus previous low-four-bit residual; output sum>>4, retain sum&15"
    else:
        raise ValueError(f"Unsupported four-PCM mixing mode: {mode}")
    clipping = int(np.sum((accumulator < 0) | (accumulator > 255)))
    if clipping or np.any((quantized < 0) | (quantized > 15)):
        raise ValueError("Four-voice mixture exceeds the eight-bit error-feedback accumulator")
    # A byte-exact player can still erase quiet music in its final rounding.
    # Measure that loss before the output pipeline and independently of any
    # listening gain applied to the recorded analog SID output.
    ideal = (mixed.astype(np.float64) - 128) / 16
    restored = (quantized.astype(np.float64) - 8) / output_gain
    centered = ideal - ideal.mean()
    error = restored - ideal
    error -= error.mean()
    signal_power = float(np.mean(centered * centered))
    error_power = float(np.mean(error * error))
    erased_power = float(np.mean(np.where(quantized == 8, centered * centered, 0)))
    quantization = {
        "snr_db": (10 * math.log10(signal_power / error_power)
                   if signal_power > 0 and error_power > 0 else None),
        "musical_energy_erased_fraction": erased_power / signal_power if signal_power else 0.0,
        "neutral_fraction": float(np.mean(quantized == 8)),
        "ideal_rms_dac_units": math.sqrt(signal_power),
        "error_rms_dac_units": math.sqrt(error_power),
        "scope": "Final DAC quantization only, against the prepared prequantized mixture. Signal and error have their means removed; constant configured output gain is undone for analysis. Does not measure sample-bank loss, SID output or perceived quality.",
    }
    dac = np.empty(frame_count, dtype=np.uint8)
    dac[0] = 8
    dac[1:] = quantized[:-1]
    receipt = {"sample_rate_hz": PCM_RATE, "sample_timer_cycles": 256,
               "samples": len(dac), "duration_s": len(dac) / PCM_RATE,
               "music_ticks": len(ticks), "triggers_per_track": triggers,
               "total_triggers": sum(triggers), "valid_sample_reads_per_track": reads,
               "volume_level_frame_counts": [dict(sorted(counter.items())) for counter in levels],
               "step_min_max_per_track": [[min(counter), max(counter)] for counter in steps],
               "tick_sample_counts": {int(count): int(occurrences) for count, occurrences
                                      in sorted(Counter(np.diff(cuts)).items())},
               "initial_dac": 8, "initial_residual": 0,
               "mixing_mode": mode, "output_gain": output_gain,
               "residual_feedback_enabled": mode == "feedback",
               "final_residual_after_last_computed_sample": final_residual,
               "last_computed_but_not_emitted_dac": int(quantized[-1]),
               "dac_min": int(dac.min()), "dac_max": int(dac.max()),
               "dac_code_counts": dict(sorted(Counter(map(int, dac)).items())),
               "clipped_accumulator_samples": clipping,
               "clipped_output_samples": clipped_output,
               "quantization": quantization,
               "lookup": "32 + round((sample_nibble - 8) * volume_level / 4), ties to even",
               "mix": mix_description,
               "quantization_tradeoff": "Nearest rounding reduces residual-driven high-frequency error but increases correlated quantization distortion and can round quiet material to silence. Neither mode is noise-free or an exact analog reconstruction.",
               "pipeline": ("Initial nextDAC8 is emitted at first IRQ. Each IRQ computes the next DAC from current cursor samples, then advances cursors. Extended states commit at8/6/4/2samples left with intervening recovery IRQs. Audible note offsets are -7/-5/-3/-1sample periods relative to the ideal tick boundary."
                            if extended_loops else "Initial nextDAC8 is emitted at first IRQ. Each IRQ computes the next DAC from current cursor samples, then advances cursors. Prefetched voice0/1/2/3 states commit before mixing with4/3/2/1samples left in the current tick. Audible note offsets are -3/-2/-1/0sample periods relative to the ideal tick boundary."),
               "tick_rounding": ("cuts[n]=(n*30789+200)//400: exact nearest-sample Bresenham with ties rounded upward"
                                 if fixed_ticks else "Nearest cumulative source tick duration at the fixed DAC clock; ties upward"),
               "bank": bank_receipt,
               "scope": "Exact digital arithmetic and cursor model. Repeated copies of a bank loop are equivalent to one original loop; no analog SID or DAC nonlinearity is modeled."}
    return dac, receipt


def verify_trace(dac: np.ndarray, trace_path: Path, first_cycle: int) -> dict:
    """Compare every DAC byte at one externally established clock anchor.

    The anchor must come from the actual capture's sample clock, not a search
    for matching audio values. No shifting, stretching or per-note alignment.
    """
    clock = 0
    cycles, values = [], []
    with trace_path.open() as stream:
        for line in stream:
            fields = line.split()
            if len(fields) != 3:
                continue
            delta, address, value = map(int, fields)
            clock += delta
            if address & 31 == 24 and clock >= first_cycle and len(values) < len(dac):
                cycles.append(clock)
                values.append(value)
    if not cycles or cycles[0] != first_cycle:
        raise ValueError("Requested clock anchor is not an observed D418 write")
    if len(values) != len(dac):
        raise ValueError(f"Incomplete DAC stream: {len(values)} of {len(dac)} bytes")
    observed = np.array(values, dtype=np.uint8)
    mismatches = np.flatnonzero(observed != dac)
    gaps = np.diff(np.asarray(cycles, dtype=np.int64))
    receipt = {"trace_file": str(trace_path.resolve()),
               "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
               "anchor_cycle": first_cycle, "bytes_compared": len(dac),
               "mismatched_bytes": len(mismatches), "all_dac_bytes_match": not len(mismatches),
               "sample_interval_min_cycles": int(gaps.min()),
               "sample_interval_max_cycles": int(gaps.max()),
               "sample_interval_median_cycles": float(np.median(gaps)),
               "examples": [{"sample_index": int(index), "cycle": cycles[index],
                              "expected": int(dac[index]), "observed": int(observed[index])}
                             for index in mismatches[:20]],
               "alignment": "Only the externally supplied first sample-clock D418 write. No DAC-value matching, local shifting, time warping or audio correlation."}
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=HERE / "results/pcm4-clean/arrangement.json")
    parser.add_argument("--out", type=Path, default=HERE / "results/pcm4-clean/reference")
    parser.add_argument("--original", type=Path, default=HERE / "results/reference/original.wav")
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--capture", type=Path, help="Capture JSON containing trace.first_sample_cycle")
    parser.add_argument("--first-cycle", type=int)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    arrangement = json.loads(raw)
    dac, receipt = expected_dac(arrangement)
    args.out.mkdir(parents=True, exist_ok=True)
    binary = args.out / "expected-DAC.bin"
    binary.write_bytes(dac.tobytes())
    common = math.gcd(OUTPUT_RATE * 8, 30789)
    audio = resample_poly((dac.astype(np.float64) - 8) / 8,
                          OUTPUT_RATE * 8 // common, 30789 // common)
    raw_resampled_frames = len(audio)
    score_frames = round(arrangement["duration_s"] * OUTPUT_RATE)
    # A short score can end between DAC sample clocks. Only the listening WAV
    # receives an endpoint hold of at most two output samples to express the
    # requested score duration; the exact DAC binary stays untouched.
    if abs(len(audio) - score_frames) > 2:
        raise ValueError("Resampled DAC duration differs from the original score")
    audio = np.pad(audio[:score_frames], (0, max(0, score_frames - len(audio))), mode="edge")
    sf.write(args.out / "expected-DAC.wav", audio, OUTPUT_RATE, subtype="PCM_16")
    start, stop = 30 * OUTPUT_RATE, 50 * OUTPUT_RATE
    original, rate = sf.read(args.original, start=start, stop=stop)
    expected = audio[start:stop].copy()
    if rate != OUTPUT_RATE or len(original) != stop - start or len(expected) != len(original):
        raise ValueError("Original or modeled preview is not the complete30–50s passage")
    original = original - original.mean()
    expected = expected - expected.mean()
    rms_original = float(np.sqrt(np.mean(original * original)))
    rms_expected = float(np.sqrt(np.mean(expected * expected)))
    if rms_expected < 1e-7:
        raise ValueError("Offline DAC model unexpectedly silent")
    original_unit, expected_unit = original / rms_original, expected / rms_expected
    common_rms = min(0.15, 0.90 / max(float(np.max(np.abs(original_unit))), float(np.max(np.abs(expected_unit)))))
    original_preview, expected_preview = original_unit * common_rms, expected_unit * common_rms
    sf.write(args.out / "original-preview.wav", original_preview, OUTPUT_RATE, subtype="PCM_16")
    sf.write(args.out / "expected-preview.wav", expected_preview, OUTPUT_RATE, subtype="PCM_16")
    sf.write(args.out / "original-then-expected.wav",
             np.r_[original_preview, np.zeros(OUTPUT_RATE // 2), expected_preview], OUTPUT_RATE, subtype="PCM_16")
    receipt.update({"arrangement_file": str(args.input.resolve()), "arrangement_sha256": hashlib.sha256(raw).hexdigest(),
                    "dac_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                    "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "original_reused": str(args.original.resolve()),
                    "original_sha256": hashlib.sha256(args.original.read_bytes()).hexdigest(),
                    "wav": {"sample_rate": OUTPUT_RATE, "frames": len(audio), "format": "PCM16",
                            "resampled_frames_before_endpoint_adjustment": raw_resampled_frames,
                            "endpoint_frames_added_or_trimmed": score_frames - raw_resampled_frames,
                            "method": "Band-limited rational resampling of (DACbyte-8)/8. No analog SID emulation."},
                    "preview": {"start_s": 30, "duration_s": 20, "matched_rms": common_rms,
                                "original_gain": common_rms / rms_original, "expected_gain": common_rms / rms_expected,
                                "method": "Separate constant level matching and DC removal for the listening preview only; exact binary bytes are unchanged."}})
    if args.trace:
        anchor = args.first_cycle
        if anchor is None and args.capture:
            anchor = json.loads(args.capture.read_text())["trace"]["first_sample_cycle"]
        if anchor is None:
            raise ValueError("Trace verification needs an externally established sample-clock anchor")
        verification = verify_trace(dac, args.trace, anchor)
        (args.out / "trace-check.json").write_text(json.dumps(verification, indent=2) + "\n")
        receipt["trace_check"] = verification
    (args.out / "reference.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({key: receipt[key] for key in ("samples", "duration_s", "music_ticks", "triggers_per_track",
                                                   "dac_min", "dac_max", "clipped_accumulator_samples")}, indent=2))
    if args.trace and not receipt["trace_check"]["all_dac_bytes_match"]:
        raise SystemExit("Actual C64 DAC bytes differ from the independent arithmetic model")


if __name__ == "__main__":
    main()
