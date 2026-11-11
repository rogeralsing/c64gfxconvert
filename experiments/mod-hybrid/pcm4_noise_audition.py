"""Compare actual C64 captures before/after removing residual feedback.

The fixed30–40s passage is presented old, silence0.5s, new. Both sides get
one constant peak-safe RMS gain. Source banks, whole-song notes, volume LUT,
native runtime and PRG identity are checked before the pair is written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.signal import welch
import soundfile as sf

from fit_audition import digest, load_crop


HERE = Path(__file__).resolve().parent
RATE = 22050


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def image_bytes(build: dict, label: str, count: int) -> bytes:
    data = Path(build["program"]).read_bytes()
    start = build["labels"][label] - int.from_bytes(data[:2], "little") + 2
    result = data[start:start + count]
    if start < 2 or len(result) != count:
        raise ValueError(f"Program table outside PRG: {label}")
    return result


def verify_capture(root: Path, duration: int, audio: bool) -> tuple[dict, dict]:
    capture = read_json(root / "vice/capture.json")
    build = read_json(root / "c64/build.json")
    if audio and capture.get("audio", {}).get("duration_s") != duration:
        raise ValueError(f"Wait for completed{duration}s audio receipt: {root}")
    if not digest(Path(capture["program"])) == capture["program_sha256"] == build["program_sha256"]:
        raise ValueError(f"Capture, build and actual PRG hashes differ: {root}")
    if build["duration_s"] != duration or build["pcm_channels"] != 4 or build["sid_voices"] != 0:
        raise ValueError(f"Expected complete four-PCM score: {root}")
    for mode in (("registers", "audio") if audio else ("registers",)):
        state = capture.get("runtime", {}).get(mode, {})
        if state.get("played_tick_count") != duration * 50 or state.get("underrun_counter") != 0:
            raise ValueError(f"Incomplete/late C64 playback: {root}:{mode}:{state}")
    trace = capture["trace"]
    if (abs(trace["sample_count_error"]) > 1 or trace["gaps_over_384_cycles"]
            or abs(trace["score_clock_end_error_cycles"]) >= 256
            or trace["score_clock_phase_range_cycles"] >= 256):
        raise ValueError(f"Physical DAC clock checks failed: {root}")
    return capture, build


def input_audit(old: Path, new: Path, old_build: dict, new_build: dict) -> dict:
    before, after = read_json(old / "arrangement.json"), read_json(new / "arrangement.json")
    short = read_json(new / "short/arrangement.json")
    if before["ticks"] != after["ticks"] or short["ticks"] != after["ticks"][:2500]:
        raise ValueError("Notes, triggers, periods/steps or volumes changed")
    if before["source_sha256"] != after["source_sha256"] or before["pcm_rate_hz"] != after["pcm_rate_hz"]:
        raise ValueError("Source MOD or DAC rate changed")
    banks = []
    old_banks = {b["id"]: b for b in before["pcm_bank"]}
    new_banks = {b["id"]: b for b in after["pcm_bank"]}
    if old_banks.keys() != new_banks.keys():
        raise ValueError("Full-song sample IDs changed")
    for ident, bank in old_banks.items():
        other = new_banks[ident]
        fields = ("bytes", "loop_start", "loop_length", "base_divisor", "original_bytes")
        if any(bank[k] != other[k] for k in fields):
            raise ValueError(f"Sample layout/divisor changed: {ident}")
        a, b = Path(bank["data_file"]), Path(other["data_file"])
        stored_a, stored_b = old / f"c64/sample-{ident:02d}.bin", new / f"c64/sample-{ident:02d}.bin"
        if a.read_bytes() != b.read_bytes() or stored_a.read_bytes() != stored_b.read_bytes():
            raise ValueError(f"Sample bytes changed: {ident}")
        source_hash = digest(a)
        if source_hash != bank["sha256"] or source_hash != other["sha256"]:
            raise ValueError(f"Source bank hash disagrees: {ident}")
        banks.append({"id": ident, "source_sha256": source_hash,
                      "stored_sha256": digest(stored_a), "stored_bytes": stored_a.stat().st_size})
    for bank in short["pcm_bank"]:
        if Path(bank["data_file"]).read_bytes() != Path(new_banks[bank["id"]]["data_file"]).read_bytes():
            raise ValueError("Short capture bank differs from whole-song bank")
    volume = image_bytes(old_build, "volume_table", 256)
    if volume != image_bytes(new_build, "volume_table", 256):
        raise ValueError("Pre-quantizer mixing gain table changed")
    nearest = image_bytes(new_build, "quantize_table", 256)
    if nearest != bytes(min(15, max(0, round(value / 16))) for value in range(256)):
        raise ValueError("New DAC table is not the declared nearest quantizer")
    lo, hi = 4 * min(volume), 4 * max(volume)
    if any(nearest[value] != round(value / 16) for value in range(lo, hi + 1)):
        raise ValueError("New quantizer clips reachable mixer sums")
    mixing = new_build["mixing"]
    if mixing["mode"] != "nearest" or mixing["residual_feedback"]:
        raise ValueError("Expected residual feedback disabled, nearest quantization")
    return {"whole_song_ticks_equal": len(after["ticks"]), "short_ticks_equal_to_prefix": len(short["ticks"]),
            "source_banks_and_expanded_loops_identical": banks,
            "compiled_volume_table_identical_sha256": hashlib.sha256(volume).hexdigest(),
            "nearest_table_sha256": hashlib.sha256(nearest).hexdigest(),
            "reachable_mixer_sum_bounds": [lo, hi], "nearest_table_no_clipping_in_reachable_range": True,
            "musical_gain_unchanged": True, "new_mixing": mixing,
            "scope": "Whole-song note/step/volume/trigger arrays and bank bytes unchanged. Same compiled fine-mixing gain table; final conversion changes from residual feedback to nearest rounding."}


def power_bands(audio: np.ndarray, gain: float) -> dict:
    matched = (audio - audio.mean()) * gain
    frequency, power = welch(matched, RATE, nperseg=8192, noverlap=4096)
    total = float(np.trapezoid(power, frequency))
    bands = []
    for label, low, high in (("0_500", 0, 500), ("500_1500", 500, 1500),
                             ("1500_1924", 1500, 1924.3125),
                             ("1924_2000_transition", 1924.3125, 2000),
                             ("2000_plus", 2000, RATE / 2 + 1)):
        mask = (frequency >= low) & (frequency < high)
        energy = float(np.trapezoid(power[mask], frequency[mask]))
        bands.append({"label": label, "hz": [low, min(high, RATE / 2)],
                      "matched_rms": energy ** .5, "power_fraction": energy / total})
    return {"total_welch_power": total, "matched_ac_rms": float(np.sqrt(np.mean(matched * matched))), "bands": bands}


def package(out: Path) -> dict:
    old, new = HERE / "results/pcm4", HERE / "results/pcm4-clean"
    # Do not open a pending WAV, even if VICE has already created its header.
    new_capture, short_build = verify_capture(new / "short", 50, True)
    old_capture, old_build = verify_capture(old, 240, True)
    full_capture, full_build = verify_capture(new, 240, False)
    inputs = input_audit(old, new, old_build, full_build)
    if image_bytes(short_build, "volume_table", 256) != image_bytes(full_build, "volume_table", 256) or image_bytes(short_build, "quantize_table", 256) != image_bytes(full_build, "quantize_table", 256):
        raise ValueError("Short/full mixing tables differ")
    dac_path = new / "reference/actual-trace-check.json"
    dac = read_json(dac_path)
    if (not dac["all_dac_bytes_match"] or dac["mismatched_bytes"] != 0
            or dac["bytes_compared"] != 923670 or dac["capture_program_sha256"] != full_capture["program_sha256"]
            or digest(Path(dac["trace_file"])) != dac["trace_sha256"]):
        raise ValueError("New whole-song native DAC verification is incomplete")
    before, old_rate, old_source = load_crop(old / "vice/stardust-vice.wav", 30, 40)
    after, new_rate, new_source = load_crop(new / "short/vice/stardust-vice.wav", 30, 40)
    if (old_rate != RATE or new_rate != RATE or old_source["source_frames"] != 240 * RATE
            or new_source["source_frames"] != 50 * RATE
            or new_capture["audio"]["frames"] != new_source["source_frames"]):
        raise ValueError("Expected native22050Hz actual240s-old/50s-new captures")
    values = (before, after)
    rms = [float(np.sqrt(np.mean(a * a))) for a in values]
    if min(rms) <= 1e-6:
        raise ValueError("Unexpected silent before/after crop")
    target = min(.15, *(.90 * level / max(float(np.max(np.abs(a))), 1e-12) for a, level in zip(values, rms)))
    gains = [target / level for level in rms]
    sides = [a * gain for a, gain in zip(values, gains)]
    count, gap = 10 * RATE, np.zeros(RATE // 2)
    joined = np.concatenate((sides[0], gap, sides[1]))
    out.mkdir(parents=True, exist_ok=True)
    pair_path = out / "c64-before-then-after.wav"
    sf.write(pair_path, joined, RATE, subtype="PCM_16")
    stored, rate = sf.read(pair_path, dtype="float64")
    offset = count + len(gap)
    errors = [float(np.max(np.abs(stored[:count] - sides[0])) * 32768), float(np.max(np.abs(stored[offset:] - sides[1])) * 32768)]
    checks = {"mono_finite22050": stored.ndim == 1 and rate == RATE and bool(np.isfinite(stored).all()),
              "duration20_5s": len(stored) == round(20.5 * RATE),
              "old_first_segment_matches_gain": errors[0] <= 1.00001,
              "new_second_segment_matches_gain": errors[1] <= 1.00001,
              "pause_exact_zero": bool(np.all(stored[count:offset] == 0)),
              "peak_below_full_scale": float(np.max(np.abs(stored))) < 1}
    if not all(checks.values()):
        raise ValueError(f"Audition audit failed: {checks}")
    old_power, new_power = power_bands(before, gains[0]), power_bands(after, gains[1])
    reductions = [{"label": a["label"], "old_fraction": a["power_fraction"], "new_fraction": b["power_fraction"],
                   "matched_band_power_change_db": float(20 * np.log10(max(b["matched_rms"], 1e-15) / max(a["matched_rms"], 1e-15)))}
                  for a, b in zip(old_power["bands"], new_power["bands"])]
    record = {"file": str(pair_path.resolve()), "sha256": digest(pair_path), "rate": rate,
              "frames": len(stored), "duration_s": len(stored) / RATE, "song_passage_s": [30, 40],
              "before_source": old_source, "after_source": new_source,
              "after_audio_capture_duration_s": 50, "after_whole_song_register_verification_duration_s": 240,
              "segments": [{"content": "old_actual_C64_residual_feedback", "start_s": 0, "end_s": 10},
                           {"content": "silence", "start_s": 10, "end_s": 10.5},
                           {"content": "new_actual_C64_nearest_rounding", "start_s": 10.5, "end_s": 20.5}],
              "before_raw_rms": rms[0], "after_raw_rms": rms[1], "before_gain": gains[0], "after_gain": gains[1],
              "matched_rms": target, "peak": float(np.max(np.abs(stored))),
              "processing": "Separate constant RMS gains, common peak-safe target0.15/peak0.90. Native22050Hz fixed crops only; no resampling, EQ, pitch shifting, alignment search, time warp, dynamic gain or limiting.",
              "input_audit": inputs,
              "power_analysis": {"before": old_power, "after": new_power, "changes": reductions,
                                 "method": "DC removed for analysis only; apply declared presentation gains; Welch8192/4096 at22050Hz. Fractions use each side total Welch power.",
                                 "interpretation": "Band energy contains both music and artifacts. A reduction does not establish noise-free reproduction."},
              "runtime": {"before_full": old_capture["runtime"], "after_short": new_capture["runtime"], "after_full_registers": full_capture["runtime"]},
              "program_sha256": {"before_full": old_capture["program_sha256"], "after_short": new_capture["program_sha256"], "after_full": full_capture["program_sha256"]},
              "dac_verification": {"file": str(dac_path.resolve()), "sha256": digest(dac_path), "bytes_compared": dac["bytes_compared"], "mismatched_bytes": dac["mismatched_bytes"]},
              "audit_status": "pass"}
    audit = {"status": "pass", "checks": checks, "maximum_segment_error_pcm16_steps": errors,
             "pair_file": str(pair_path.resolve()), "pair_sha256": digest(pair_path),
             "source_hashes": {"before": old_source["sha256"], "after": new_source["sha256"]},
             "scope": "Actual C64 before/after order, native rates, gain/peak, silence, identical score/banks, short audio runtime and whole-song native DAC proof."}
    (out / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    (out / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results/pcm4-clean/audition")
    args = parser.parse_args()
    record = package(args.out)
    print(json.dumps({"file": record["file"], "matched_rms": record["matched_rms"], "peak": record["peak"],
                      "bands": record["power_analysis"]["changes"], "audit_status": record["audit_status"]}, indent=2))


if __name__ == "__main__":
    main()
