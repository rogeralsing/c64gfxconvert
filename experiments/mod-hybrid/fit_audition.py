"""Package and audit the fitted single-channel SID attempt and C64 PCM control.

Scores use one fixed20-second original at11025Hz. Presentation keeps original
audio at22050Hz; only the11025Hz SID capture is upsampled for the paired file.
The gain changes below are constant per side, with no equalization or alignment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

from sequence_loss import SequenceLoss


HERE = Path(__file__).resolve().parent
PRESENTATION_RATE = 22050
ANALYSIS_RATE = 11025


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_crop(path: Path, start_s: float, end_s: float) -> tuple[np.ndarray, int, dict]:
    info = sf.info(path)
    start, stop = round(start_s * info.samplerate), round(end_s * info.samplerate)
    if info.channels != 1 or info.frames < stop:
        raise ValueError(f"Incomplete or non-mono source: {path}")
    audio, rate = sf.read(path, dtype="float64", start=start, stop=stop)
    if len(audio) != stop - start or not np.isfinite(audio).all():
        raise ValueError(f"Invalid source crop: {path}")
    return audio, rate, {"file": str(path.resolve()), "sha256": digest(path),
                         "source_rate": rate, "source_frames": info.frames,
                         "crop_start_frame": start, "crop_end_frame": stop,
                         "crop_duration_s": len(audio) / rate}


def convert(audio: np.ndarray, source_rate: int, target_rate: int) -> tuple[np.ndarray, dict]:
    if source_rate == target_rate:
        return audio, {"operation": "none", "source_rate": source_rate, "target_rate": target_rate}
    divisor = math.gcd(source_rate, target_rate)
    up, down = target_rate // divisor, source_rate // divisor
    result = resample_poly(audio, up, down)
    return result, {"operation": "scipy.signal.resample_poly", "up": up, "down": down,
                    "source_rate": source_rate, "target_rate": target_rate,
                    "note": "Fixed sample-rate conversion only; no pitch or duration adjustment"}


def pair(out: Path, label: str, original: np.ndarray, candidate: np.ndarray,
         source_original: dict, source_candidate: dict, conversion: dict) -> dict:
    count = 20 * PRESENTATION_RATE
    if len(original) != count or len(candidate) != count:
        raise ValueError("Presentation sides must both contain20s at22050Hz")
    values = (original, candidate)
    rms = [float(np.sqrt(np.mean(audio * audio))) for audio in values]
    if min(rms) < 1e-6:
        raise ValueError("Unexpected silent audition side")
    target_rms = min(0.15, *(0.90 * level / max(float(np.max(np.abs(audio))), 1e-12)
                             for audio, level in zip(values, rms)))
    gains = [target_rms / level for level in rms]
    sides = [audio * gain for audio, gain in zip(values, gains)]
    gap = np.zeros(PRESENTATION_RATE // 2)
    joined = np.concatenate((sides[0], gap, sides[1]))
    destination = out / f"channel-2-original-then-{label}.wav"
    sf.write(destination, joined, PRESENTATION_RATE, subtype="PCM_16")
    stored, rate = sf.read(destination, dtype="float64")
    offset = count + len(gap)
    errors = [float(np.max(np.abs(stored[:count] - sides[0])) * 32768),
              float(np.max(np.abs(stored[offset:] - sides[1])) * 32768)]
    checks = {
        "mono_finite": stored.ndim == 1 and bool(np.isfinite(stored).all()),
        "length40_5s": len(stored) == round(40.5 * PRESENTATION_RATE),
        "rate22050": rate == PRESENTATION_RATE,
        "first_segment_matches_original_with_declared_gain": errors[0] <= 1.00001,
        "second_segment_matches_candidate_with_declared_gain": errors[1] <= 1.00001,
        "half_second_gap_is_exactly_zero": bool(np.all(stored[count:offset] == 0)),
        "peak_below_full_scale": float(np.max(np.abs(stored))) < 1,
    }
    if not all(checks.values()):
        raise ValueError(f"Audition PCM audit failed: {label}: {checks}")
    return {"label": label, "file": str(destination.resolve()), "sha256": digest(destination),
            "rate": rate, "frames": len(stored), "duration_s": len(stored) / rate,
            "original_source": source_original, "candidate_source": source_candidate,
            "candidate_presentation_conversion": conversion,
            "original_gain": gains[0], "candidate_gain": gains[1],
            "original_raw_rms": rms[0], "candidate_presentation_raw_rms": rms[1],
            "matched_rms": target_rms, "peak": float(np.max(np.abs(stored))),
            "segments": [{"content": "original", "start_s": 0, "end_s": 20},
                         {"content": "silence", "start_s": 20, "end_s": 20.5},
                         {"content": label, "start_s": 20.5, "end_s": 40.5}],
            "audit": {"checks": checks, "maximum_segment_error_pcm16_steps": errors,
                      "status": "pass"}}


def package(out: Path) -> dict:
    capture_path = HERE / "results/channel-fit-2/final-vice/vice/capture.json"
    capture = json.loads(capture_path.read_text())
    if "audio" not in capture or capture["audio"]["duration_s"] != 50:
        raise ValueError("Final capture is not complete; wait for its50s audio receipt")
    if not capture["trace"]["passed"] or any(item["underruns"] for item in capture["runtime"].values()):
        raise ValueError("Final C64 capture did not pass runtime/register verification")
    out.mkdir(parents=True, exist_ok=True)
    original_path = HERE / "results/channel-fit-2/targets/train.wav"
    fitted_path = HERE / "results/channel-fit-2/final-vice/vice/phrase-vice.wav"
    baseline_path = HERE / "results/channel-solos/c64/track-2/vice/stardust-vice.wav"
    pcm_path = HERE / "results/channel-fit-2/pcm-control/phrase-vice.wav"
    original, original_rate, original_source = load_crop(original_path, 0, 20)
    fitted, fitted_rate, fitted_source = load_crop(fitted_path, 30, 50)
    baseline, baseline_rate, baseline_source = load_crop(baseline_path, 30, 50)
    pcm, pcm_rate, pcm_source = load_crop(pcm_path, 0, 20)
    if original_rate != 22050 or fitted_rate != 11025 or pcm_rate != 22050 or baseline_rate != 22050:
        raise ValueError("Source rates differ from their declared native capture rates")
    if fitted_source["source_frames"] != capture["audio"]["frames"] or fitted_rate != capture["audio"]["sample_rate"]:
        raise ValueError("Final WAV does not match completed capture receipt")
    analysis_target, target_conversion = convert(original, original_rate, ANALYSIS_RATE)
    objective = SequenceLoss(analysis_target, ANALYSIS_RATE)
    scores, analysis = {}, {}
    for name, audio, rate, record in (("baseline_v2_sid", baseline, baseline_rate, baseline_source),
                                       ("fitted_sid", fitted, fitted_rate, fitted_source),
                                       ("c64_pcm_control", pcm, pcm_rate, pcm_source)):
        analyzed, conversion = convert(audio, rate, ANALYSIS_RATE)
        if len(analyzed) != 20 * ANALYSIS_RATE:
            raise ValueError(f"Analysis source does not have exactly20s: {name}")
        scores[name] = objective.measure(analyzed)
        analysis[name] = {"source": record, "conversion": conversion, "frames": len(analyzed), "rate": ANALYSIS_RATE}
    fitted_presentation, fitted_conversion = convert(fitted, fitted_rate, PRESENTATION_RATE)
    pcm_presentation, pcm_conversion = convert(pcm, pcm_rate, PRESENTATION_RATE)
    pairs = [pair(out, "fitted-sid", original, fitted_presentation, original_source, fitted_source, fitted_conversion),
             pair(out, "c64-pcm", original, pcm_presentation, original_source, pcm_source, pcm_conversion)]
    record = {"mod_track_1_based": 2, "song_passage_s": [30, 50],
              "order": "Original20s, silence0.5s, actual C64 candidate20s",
              "level_method": "Constant RMS match to0.15 per pair, reduced equally when either side would exceed0.90 peak; no limiting or dynamic gain",
              "presentation": "Original22050Hz remains at its native rate. Fitted SID11025Hz is upsampled once by2 for paired playback. PCM control remains22050Hz. No EQ, pitch shifting, time warp or candidate-specific alignment.",
              "pairs": pairs,
              "objective": {"target": original_source, "target_conversion": target_conversion,
                            "analysis_rate": ANALYSIS_RATE, "target_frames": len(analysis_target),
                            "candidate_inputs": analysis, "scores": scores,
                            "alignment": "Fixed song30–50s, with final SID and baseline cropped from complete50s captures. PCM control is already the recorded20s passage. No content-based alignment.",
                            "gain": "SequenceLoss applies one bounded global level adjustment; presentation gain matching does not alter objective inputs."},
              "final_capture": {"file": str(capture_path.resolve()), "sha256": digest(capture_path),
                                "program_sha256": capture["program_sha256"], "source_renderer_engine": capture["source_renderer_engine"],
                                "frames_checked": capture["trace"]["frames_checked"], "runtime": capture["runtime"]},
              "audit_status": "pass", "scope": "One original MOD channel only. Actual VICE SID attempt and original-sample C64 PCM control; no edits to musical programs or other tracks."}
    (out / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    audit = {"status": "pass", "pairs": [{"file": item["file"], **item["audit"]} for item in pairs],
             "objective_analysis_lengths": {name: item["frames"] for name, item in analysis.items()},
             "fitted_sid_analysis_resampling": analysis["fitted_sid"]["conversion"],
             "scope": "Native-rate crop, gain, segment-order, silence, finite-PCM, frame-count and peak audit"}
    (out / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results/channel-fit-2/audition")
    args = parser.parse_args()
    record = package(args.out)
    print(json.dumps({"manifest": str((args.out / 'manifest.json').resolve()),
                      "scores": record["objective"]["scores"],
                      "pairs": [{"file": item["file"], "matched_rms": item["matched_rms"], "peak": item["peak"]} for item in record["pairs"]],
                      "audit_status": record["audit_status"]}, indent=2))


if __name__ == "__main__":
    main()
