"""Package independently rendered MOD and actual C64 audio for a song test.

The input directory contains original/, short/c64/, short/vice/ and
short/reference/ receipts. Both clips use seconds 30–50 at native 22050 Hz.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf


RATE = 22050


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(song: Path, out: Path) -> dict:
    original = json.loads((song / "original/reference.json").read_text())
    arrangement_path = song / "short/arrangement.json"
    arrangement = json.loads(arrangement_path.read_text())
    build = json.loads((song / "short/c64/build.json").read_text())
    capture = json.loads((song / "short/vice/capture.json").read_text())
    model = json.loads((song / "short/reference/reference.json").read_text())
    verification = json.loads((song / "short/reference/trace-check.json").read_text())
    program = Path(build["program"])
    if digest(program) != build["program_sha256"] or digest(program) != capture["program_sha256"]:
        raise ValueError("Program, build and capture hashes differ")
    if digest(arrangement_path) != build["arrangement_sha256"]:
        raise ValueError("Arrangement differs from the assembled score")
    if model["arrangement_sha256"] != digest(arrangement_path) or model["trace_check"] != verification:
        raise ValueError("DAC verification belongs to another arrangement")
    if Path(verification["trace_file"]).resolve() != (song / "short/vice/registers.txt").resolve():
        raise ValueError("DAC verification belongs to another capture")
    if arrangement["source_sha256"] != original["source_sha256"]:
        raise ValueError("Original and C64 versions use different source modules")
    if original["mismatch_count"] or arrangement["mixing"]["mode"] != "nearest":
        raise ValueError("Expected validated original timing and corrected nearest quantization")
    if build["ticks"] != 2500 or build["pcm_channels"] != 4 or build["sid_voices"] != 0:
        raise ValueError("Expected four PCM tracks over the first 50 seconds")
    for mode in ("registers", "audio"):
        state = capture["runtime"][mode]
        if state["played_tick_count"] != build["ticks"] or state["underrun_counter"]:
            raise ValueError(f"Incomplete playback or underruns: {mode}")
    trace = capture["trace"]
    expected_count = (build["ticks"] * 30789 + 200) // 400
    if (verification["mismatched_bytes"] or not verification["all_dac_bytes_match"]
            or verification["bytes_compared"] != expected_count
            or verification["anchor_cycle"] != trace["first_sample_cycle"]
            or digest(Path(verification["trace_file"])) != verification["trace_sha256"]
            or abs(trace["sample_count_error"]) > 2
            or trace["gaps_over_384_cycles"]
            or trace["score_clock_phase_range_cycles"] >= 256):
        raise ValueError("Actual DAC stream does not pass exact arithmetic and clock checks")
    source_paths = [song / "original/original.wav", song / "short/vice/stardust-vice.wav"]
    if digest(source_paths[0]) != original["wav_sha256"]:
        raise ValueError("Original audio identity differs from its independent receipt")
    if capture["audio"]["duration_s"] != 50 or capture["audio"]["frames"] != 50 * RATE:
        raise ValueError("Actual audio capture is incomplete")
    # Reconstruct the processed capture from the original VICE device WAV.
    # This rejects a stale or model WAV substituted at the convenient clip path.
    raw_path = song / "short/vice/vice-raw.wav"
    raw, raw_rate = sf.read(raw_path, dtype="float64")
    anchor = capture["audio"]["crop_start_frame"]
    actual = raw[anchor:anchor + 50 * RATE].copy()
    if raw_rate != RATE or actual.ndim != 1 or len(actual) != 50 * RATE:
        raise ValueError("Raw VICE recording cannot reconstruct the complete song crop")
    actual -= actual.mean()
    if (abs(float(np.max(np.abs(actual))) - capture["audio"]["raw_peak"]) > 1e-12
            or abs(float(np.sqrt(np.mean(actual * actual))) - capture["audio"]["raw_rms"]) > 1e-12):
        raise ValueError("Raw VICE recording differs from its capture statistics")
    processed, processed_rate = sf.read(source_paths[1], dtype="float64")
    if (processed_rate != RATE or processed.shape != actual.shape
            or np.max(np.abs(processed - actual)) > 1 / 32768):
        raise ValueError("C64 audio does not match the raw VICE recording and documented crop")
    clips = []
    for path in source_paths:
        info = sf.info(path)
        if info.samplerate != RATE or info.channels != 1 or info.frames < 50 * RATE:
            raise ValueError(f"Audio must be mono 22050 Hz and cover seconds 30–50: {path}")
        clip, _ = sf.read(path, start=30 * RATE, stop=50 * RATE, dtype="float64")
        clip -= clip.mean()
        if not np.isfinite(clip).all() or np.sqrt(np.mean(clip * clip)) < 1e-6:
            raise ValueError(f"Invalid or silent passage: {path}")
        clips.append(clip)
    rms = [float(np.sqrt(np.mean(clip * clip))) for clip in clips]
    target = min(0.15, *(0.90 * level / np.max(np.abs(clip)) for clip, level in zip(clips, rms)))
    gains = [target / level for level in rms]
    segments = [clip * gain for clip, gain in zip(clips, gains)]
    joined = np.r_[segments[0], np.zeros(RATE // 2), segments[1]]
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{song.name}-original-then-c64.wav"
    sf.write(path, joined, RATE, subtype="PCM_16")
    stored, rate = sf.read(path)
    boundary = 20 * RATE
    second = boundary + RATE // 2
    if (rate != RATE or len(stored) != len(joined) or np.max(np.abs(stored)) >= 1
            or np.any(stored[boundary:second])
            or np.max(np.abs(stored[:boundary] - segments[0])) > 1 / 32768
            or np.max(np.abs(stored[second:] - segments[1])) > 1 / 32768):
        raise ValueError("Stored comparison has incorrect segments, silence or clipping")
    receipt = {"file": str(path.resolve()), "sha256": digest(path),
               "duration_s": len(stored) / RATE, "sample_rate": RATE,
               "passage_s": [30, 50], "segments": ["20s original", "0.5s silence", "20s actual C64"],
               "source_files": [str(p.resolve()) for p in source_paths],
               "source_sha256": [digest(p) for p in source_paths],
               "raw_vice_sha256": digest(raw_path), "raw_crop_verified": True,
               "program_sha256": digest(program), "source_mod_sha256": arrangement["source_sha256"],
               "constant_gains": gains, "matched_rms": float(target),
               "peak": float(np.max(np.abs(stored))), "dac_bytes_verified": expected_count,
               "status": "pass", "processing": "DC removal and separate constant RMS gains only. No EQ, limiting, pitch or timing adjustment."}
    path.with_suffix(".json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("song", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.song, args.out), indent=2))


if __name__ == "__main__":
    main()
