"""Guard the accepted SID1 sound using actual, unscaled native capture samples.

The delivery path supplies a clock-cropped, DC-removed mono signal before its
shared listening gain. This module only measures it; it never changes audio.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf

REFERENCE_DIR = Path(__file__).resolve().parent / "references/hyperbased-stems"


def _metrics(signal: np.ndarray, rate: int) -> tuple[float, float]:
    centered = signal - signal.mean()
    window = np.hanning(len(signal))
    spectrum = abs(np.fft.rfft(centered * window))
    frequency = np.fft.rfftfreq(len(signal), 1 / rate)
    audible = (frequency >= 40) & (frequency <= 8000)
    return float(np.std(signal)), float(2 * spectrum[audible].max() / window.sum())


def compare(signal: np.ndarray, rate: int = 22050) -> dict:
    """Compare every approved first20s phrase; accept no alignment or gain fit.

    Input is native floating-point amplitude, without the exported WAV's gain.
    The approved WAV's fixed gain is removed arithmetically for measurement.
    """
    fixture_path = REFERENCE_DIR / "sid1-phrases.json"
    fixture_bytes = fixture_path.read_bytes()
    fixture = json.loads(fixture_bytes)
    if rate != fixture["sample_rate_hz"]:
        raise ValueError("SID1 reference comparison requires22050Hz")
    count = fixture["checked_frames"]
    observed = np.asarray(signal, dtype=np.float64)
    if observed.ndim != 1 or len(observed) < count:
        raise ValueError("SID1 reference comparison requires the complete first20s mono capture")
    observed = observed[:count]
    if not np.isfinite(observed).all():
        raise ValueError("SID1 capture contains non-finite values")
    reference_path = REFERENCE_DIR / fixture["reference_file"]
    reference_sha = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    if reference_sha != fixture["reference_sha256"]:
        raise ValueError("Protected SID1 reference WAV changed")
    reference, reference_rate = sf.read(reference_path, dtype="float64")
    if reference_rate != rate or reference.ndim != 1 or len(reference) < count:
        raise ValueError("SID1 reference has an unexpected rate, length or channel count")
    reference = reference[:count] / fixture["reference_gain"]
    phrases, failures = [], []
    for index, (start, end, instrument) in enumerate(fixture["phrases"]):
        reference_rms, reference_spectrum = _metrics(reference[start:end], rate)
        observed_rms, observed_spectrum = _metrics(observed[start:end], rate)
        rms_ratio = observed_rms / reference_rms
        spectral_ratio = observed_spectrum / reference_spectrum
        noise = instrument == 10
        low, high = fixture["rms_limits_noise" if noise else "rms_limits_tonal"]
        spectral_low, spectral_high = fixture["spectral_amplitude_limits_tonal"]
        passed = low <= rms_ratio <= high and (noise or spectral_low <= spectral_ratio <= spectral_high)
        phrases.append([rms_ratio, spectral_ratio])
        if not passed:
            failures.append(index)
    peak_ratio = float(np.max(abs(observed)) / np.max(abs(reference)))
    peak_limit = fixture["global_peak_ratio_limit"]
    return {"passed": not failures and peak_ratio <= peak_limit,
            "checked_interval_s": [0, count / rate], "phrases_checked": len(phrases),
            "failed_phrase_indices": failures, "minimum_rms_ratio": min(p[0] for p in phrases),
            "median_rms_ratio": float(np.median([p[0] for p in phrases])),
            "first_resumed_phrase_ratio": phrases[1][0],
            "global_peak_ratio": peak_ratio, "global_peak_ratio_limit": peak_limit,
            "reference_sha256": reference_sha,
            "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
            "phrase_ratio_columns": ["rms_ratio", "spectral_amplitude_ratio"], "phrase_ratios": phrases,
            "scope": "Actual first20s SID1 amplitude/spectral-envelope comparison. Fixed reference gain only; no candidate gain fitting, alignment, audio processing or WAV writing."}
