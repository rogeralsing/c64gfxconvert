"""Diagnose final DAC rounding and compare one complete passage with its original.

The quantizer measurements reuse the PCM4 arithmetic model. They are not an
independent player check. The supplied original WAV is a separate source for
native-time spectral comparison; no audio is shifted, filtered or rewritten.
"""
from __future__ import annotations

import argparse
import copy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly, stft
import soundfile as sf

from pcm4_reference import PCM_RATE, expected_dac


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    left, right = left - left.mean(), right - right.mean()
    norm = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(left @ right / norm) if norm else None


def audibility(dac: np.ndarray, gain: float, window_seconds: float) -> list[dict]:
    """Show delivered DAC activity, retaining silence instead of skipping it."""
    result = []
    duration = len(dac) / PCM_RATE
    for start in np.arange(0.0, duration - 1e-5, window_seconds):
        end = min(duration, float(start) + window_seconds)
        chunk = dac[round(float(start) * PCM_RATE):round(end * PCM_RATE)]
        if not len(chunk):
            continue
        signal = (chunk.astype(np.float64) - 8) / gain
        signal -= signal.mean()
        result.append({"start_s": float(start), "duration_s": end - float(start),
                       "rms_dac_units": float(np.sqrt(np.mean(signal * signal))),
                       "neutral_fraction": float(np.mean(chunk == 8)),
                       "nonneutral_samples": int(np.count_nonzero(chunk != 8))})
    return result


def magnitude_metrics(original: np.ndarray, prepared: np.ndarray) -> dict:
    """Compare nonnegative STFT magnitudes without changing either time axis."""
    target = original.reshape(-1)
    candidate = prepared.reshape(-1)
    norm_target, norm_candidate = float(np.linalg.norm(target)), float(np.linalg.norm(candidate))
    if not norm_target or not norm_candidate:
        return {"magnitude_cosine": None, "gain_fitted_magnitude_error": None,
                "analysis_gain": None, "silent_original": not norm_target,
                "silent_prepared": not norm_candidate}
    gain = float(target @ candidate / (candidate @ candidate))
    return {"magnitude_cosine": float(target @ candidate / (norm_target * norm_candidate)),
            "gain_fitted_magnitude_error": float(np.linalg.norm(target - gain * candidate) / norm_target),
            "analysis_gain": gain, "silent_original": False, "silent_prepared": False}


def compare_original(dac: np.ndarray, gain: float, original_path: Path,
                     duration: float, window_seconds: float) -> dict:
    original, rate = sf.read(original_path, dtype="float64", always_2d=True)
    channels = original.shape[1]
    original = original.mean(axis=1)
    wanted = round(duration * rate)
    if len(original) < wanted:
        raise ValueError(f"Original has {len(original)} frames; complete passage needs {wanted}")
    ratio = Fraction(rate, 1) / Fraction(str(PCM_RATE))
    prepared = resample_poly((dac.astype(np.float64) - 8) / (8 * gain),
                             ratio.numerator, ratio.denominator)
    if abs(len(prepared) - wanted) > 2:
        raise ValueError("Modeled DAC duration does not match complete original passage")
    count = min(wanted, len(prepared))
    original, prepared = original[:count], prepared[:count]
    original -= original.mean()
    prepared -= prepared.mean()
    frequencies, times, original_stft = stft(original, rate, nperseg=1024,
                                             noverlap=768, boundary=None, padded=False)
    _, _, prepared_stft = stft(prepared, rate, nperseg=1024,
                               noverlap=768, boundary=None, padded=False)
    # The original contains frequencies the fixed C64 DAC cannot reproduce.
    # Report its full band separately; use the shared passband for diagnosis.
    passband = (frequencies >= 50) & (frequencies <= min(1700, PCM_RATE * 0.45))
    original_magnitude, prepared_magnitude = np.abs(original_stft), np.abs(prepared_stft)
    result = {**identity(original_path), "sample_rate": rate,
              "original_channels_averaged": channels, "duration_s": count / rate,
              "shared_passband_hz": [50, min(1700, PCM_RATE * 0.45)],
              "shared_passband": magnitude_metrics(original_magnitude[passband], prepared_magnitude[passband]),
              "full_band": magnitude_metrics(original_magnitude, prepared_magnitude),
              "stft": {"window_frames": 1024, "hop_frames": 256,
                       "boundary_padding": False}, "windows": []}
    envelope_frames = max(1, round(0.02 * rate))
    complete_blocks = count // envelope_frames
    envelopes = [np.sqrt(np.mean(signal[:complete_blocks * envelope_frames].reshape(
                 complete_blocks, envelope_frames) ** 2, axis=1)) for signal in (original, prepared)]
    result["twenty_ms_rms_envelope_correlation"] = correlation(*envelopes)
    for start in np.arange(0.0, duration - 1e-5, window_seconds):
        end = min(duration, float(start) + window_seconds)
        selected = (times >= start) & (times < end)
        if np.any(selected):
            result["windows"].append({"start_s": float(start), "duration_s": end - float(start),
                                      **magnitude_metrics(original_magnitude[passband][:, selected],
                                                          prepared_magnitude[passband][:, selected])})
    result["scope"] = ("Native-time STFT magnitudes against a separately supplied original WAV. "
                       "One analysis-only scalar fits magnitude levels. No shifting, warping, EQ or listening audio output. "
                       "Shared passband excludes frequencies above the fixed DAC capability. "
                       "This does not establish note, loop, SID or subjective fidelity.")
    return result


def check(arrangement_path: Path, original_path: Path, window_seconds: float = 5.0) -> dict:
    if not math.isfinite(window_seconds) or window_seconds <= 0:
        raise ValueError("Window duration must be finite and positive")
    arrangement = json.loads(arrangement_path.read_bytes())
    gain = float(arrangement.get("mixing", {}).get("output_gain", 1.0))
    dac, receipt = expected_dac(arrangement)
    report = {"arrangement": identity(arrangement_path),
              "source_sha256": arrangement.get("source_sha256"),
              "duration_s": arrangement["duration_s"], "configured_output_gain": gain,
              "sample_rate_hz": PCM_RATE,
              "mix": {"quantization": receipt["quantization"],
                      "clipped_output_samples": receipt["clipped_output_samples"],
                      "windows": audibility(dac, gain, window_seconds)},
              "channels": [],
              "original_comparison": compare_original(dac, gain, original_path,
                                                        arrangement["duration_s"], window_seconds),
              "scope": ("Complete configured passage. Quantization and isolated channels reuse expected_dac; "
                        "they are arithmetic diagnostics, not an independent replay or an actual SID recording. "
                        "Isolated channels retain the four-track mix scale and configured gain; other channels' volumes are zero. "
                        "Neutral DAC fractions include real silence. Hash/register agreement and these metrics do not prove good sound.")}
    for channel in range(4):
        isolated = copy.deepcopy(arrangement)
        for tick in isolated["ticks"]:
            for other, state in enumerate(tick["pcm"]):
                if other != channel:
                    state["volume"] = 0
        channel_dac, channel_receipt = expected_dac(isolated)
        report["channels"].append({"channel": channel + 1,
                                   "quantization": channel_receipt["quantization"],
                                   "clipped_output_samples": channel_receipt["clipped_output_samples"],
                                   "windows": audibility(channel_dac, gain, window_seconds)})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arrangement", type=Path, required=True)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Current quality.json receipt")
    parser.add_argument("--window-seconds", type=float, default=5.0)
    args = parser.parse_args()
    report = check(args.arrangement, args.original, args.window_seconds)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"quality": str(args.out.resolve()),
                      "output_gain": report["configured_output_gain"],
                      "mix_quantization": report["mix"]["quantization"],
                      "channels": [{"channel": entry["channel"], **entry["quantization"]}
                                   for entry in report["channels"]]}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
