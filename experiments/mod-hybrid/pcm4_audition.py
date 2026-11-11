"""Package the complete four-PCM capture as one original/C64 listening pair.

Both sides use the fixed song passage30–50s at their native22050Hz rate.
Only constant level matching is applied; the complete240s capture is audited
before its crop can be used. Pending captures are never read or overwritten.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from fit_audition import digest, load_crop


HERE = Path(__file__).resolve().parent
RATE = 22050
DURATION = 240
TICKS = 12000


def package(out: Path) -> dict:
    root = HERE / "results/pcm4"
    capture_path = root / "vice/capture.json"
    capture = json.loads(capture_path.read_text())
    # The receipt is written after the WAV has been closed and checked.
    if capture.get("audio", {}).get("duration_s") != DURATION:
        raise ValueError("Wait for the completed240s audio receipt before packaging")
    build_path = root / "c64/build.json"
    build = json.loads(build_path.read_text())
    program = Path(capture["program"])
    program_hash = digest(program)
    if not program_hash == capture["program_sha256"] == build["program_sha256"]:
        raise ValueError("Capture, build receipt and actual PRG hashes differ")
    if build["duration_s"] != DURATION or build["ticks"] != TICKS or build["pcm_channels"] != 4 or build["sid_voices"] != 0:
        raise ValueError("Expected the complete four-PCM score without SID oscillators")
    for mode in ("registers", "audio"):
        state = capture.get("runtime", {}).get(mode, {})
        if state.get("played_tick_count") != TICKS or state.get("underrun_counter") != 0:
            raise ValueError(f"Incomplete or late C64 playback: {mode}: {state}")
    trace = capture["trace"]
    if (abs(trace["sample_count_error"]) > 1 or trace["gaps_over_384_cycles"]
            or abs(trace["score_clock_end_error_cycles"]) >= 256
            or trace["score_clock_phase_range_cycles"] >= 256):
        raise ValueError("The complete DAC stream did not pass physical clock checks")
    dac_path = root / "reference/actual-trace-check.json"
    dac = json.loads(dac_path.read_text())
    if (not dac["all_dac_bytes_match"] or dac["mismatched_bytes"] != 0
            or dac["bytes_compared"] != 923670
            or dac["capture_program_sha256"] != program_hash
            or digest(Path(dac["trace_file"])) != dac["trace_sha256"]):
        raise ValueError("Actual DAC byte verification does not identify this capture")

    candidate_path = root / "vice/stardust-vice.wav"
    full, rate = sf.read(candidate_path, dtype="float64")
    if rate != RATE or full.ndim != 1 or len(full) != DURATION * RATE:
        raise ValueError("Expected complete240s mono C64 audio at22050Hz")
    if capture["sample_rate"] != RATE or capture["audio"]["frames"] != len(full):
        raise ValueError("C64 WAV length or rate differs from the completed receipt")
    if not np.isfinite(full).all() or np.max(np.abs(full)) >= 1:
        raise ValueError("C64 WAV contains invalid or clipped PCM")
    block_rms = [float(np.sqrt(np.mean(block * block)))
                 for block in full.reshape(DURATION // 20, 20 * RATE)]
    if min(block_rms) <= 1e-6:
        raise ValueError("A complete20s C64 section is unexpectedly silent")

    original_path = HERE / "results/reference/original.wav"
    original, original_rate, original_source = load_crop(original_path, 30, 50)
    candidate, candidate_rate, candidate_source = load_crop(candidate_path, 30, 50)
    original_receipt_path = HERE / "results/reference/reference.json"
    original_receipt = json.loads(original_receipt_path.read_text())
    if (original_rate != RATE or candidate_rate != RATE
            or original_source["sha256"] != original_receipt["wav_sha256"]):
        raise ValueError("Original WAV identity or source sample rates differ")
    count = 20 * RATE
    values = (original, candidate)
    rms = [float(np.sqrt(np.mean(audio * audio))) for audio in values]
    if min(rms) <= 1e-6:
        raise ValueError("Unexpected silent listening segment")
    target = min(0.15, *(0.90 * level / max(float(np.max(np.abs(audio))), 1e-12)
                          for audio, level in zip(values, rms)))
    gains = [target / level for level in rms]
    sides = [audio * gain for audio, gain in zip(values, gains)]
    gap = np.zeros(RATE // 2)
    joined = np.concatenate((sides[0], gap, sides[1]))
    out.mkdir(parents=True, exist_ok=True)
    pair_path = out / "full-mix-original-then-c64.wav"
    sf.write(pair_path, joined, RATE, subtype="PCM_16")

    # Audit the stored PCM, including its segment order and PCM16 rounding.
    stored, stored_rate = sf.read(pair_path, dtype="float64")
    offset = count + len(gap)
    errors = [float(np.max(np.abs(stored[:count] - sides[0])) * 32768),
              float(np.max(np.abs(stored[offset:] - sides[1])) * 32768)]
    checks = {
        "full_capture240s_mono22050": len(full) == DURATION * RATE and full.ndim == 1 and rate == RATE,
        "full_capture_finite_and_peak_below_full_scale": bool(np.isfinite(full).all() and np.max(np.abs(full)) < 1),
        "all12_twenty_second_sections_nonzero": min(block_rms) > 1e-6,
        "both_runtime_runs12000ticks_zero_underruns": True,
        "prg_hash_matches_capture_and_build": True,
        "actual923670_dac_bytes_match": True,
        "pair40_5s_mono22050_finite": len(stored) == round(40.5 * RATE) and stored.ndim == 1 and stored_rate == RATE and bool(np.isfinite(stored).all()),
        "first_segment_matches_original_gain": errors[0] <= 1.00001,
        "second_segment_matches_actual_c64_gain": errors[1] <= 1.00001,
        "half_second_pause_exact_zero": bool(np.all(stored[count:offset] == 0)),
        "pair_peak_below_full_scale": float(np.max(np.abs(stored))) < 1,
    }
    if not all(checks.values()):
        raise ValueError(f"Stored audition audit failed: {checks}")
    record = {
        "file": str(pair_path.resolve()), "sha256": digest(pair_path),
        "rate": RATE, "frames": len(stored), "duration_s": len(stored) / RATE,
        "song_passage_s": [30, 50], "original_source": original_source,
        "candidate_source": candidate_source, "candidate_capture_duration_s": DURATION,
        "candidate_is_complete_song_capture": True,
        "segments": [{"content": "original_full_mix", "start_s": 0, "end_s": 20},
                     {"content": "silence", "start_s": 20, "end_s": 20.5},
                     {"content": "actual_c64_four_pcm_mix", "start_s": 20.5, "end_s": 40.5}],
        "level_method": "Separate constant gains match RMS0.15, with a common reduction if either side would exceed0.90 peak. No limiting or dynamic gain.",
        "original_raw_rms": rms[0], "candidate_raw_rms": rms[1],
        "original_gain": gains[0], "candidate_gain": gains[1], "matched_rms": target,
        "peak": float(np.max(np.abs(stored))),
        "processing": "Fixed native22050Hz crops only. No resampling, EQ, pitch shifting, time warp, content alignment or additional synthesis.",
        "capture": {"file": str(capture_path.resolve()), "sha256": digest(capture_path),
                    "program_sha256": program_hash, "runtime": capture["runtime"],
                    "trace": trace, "full_wav_peak": float(np.max(np.abs(full))),
                    "twenty_second_rms": block_rms},
        "build": {"file": str(build_path.resolve()), "sha256": digest(build_path),
                  "program_bytes": build["program_bytes"], "program_end": build["program_end"]},
        "dac_verification": {"file": str(dac_path.resolve()), "sha256": digest(dac_path),
                             "bytes_compared": dac["bytes_compared"], "mismatched_bytes": dac["mismatched_bytes"]},
        "audit_status": "pass",
    }
    audit = {"status": "pass", "checks": checks,
             "maximum_segment_error_pcm16_steps": errors,
             "pair_file": str(pair_path.resolve()), "pair_sha256": digest(pair_path),
             "candidate_source_sha256": candidate_source["sha256"],
             "scope": "Whole-song capture identity, physical clock, DAC reference, audio validity, constant gains, paired segment order and silence. No new musical fitting."}
    (out / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    (out / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results/pcm4/audition")
    args = parser.parse_args()
    record = package(args.out)
    print(json.dumps({key: record[key] for key in ("file", "sha256", "matched_rms", "peak", "audit_status")}, indent=2))


if __name__ == "__main__":
    main()
