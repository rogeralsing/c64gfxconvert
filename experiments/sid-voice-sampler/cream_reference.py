"""Measure the approved Cream passage against actual, unscaled C64 audio.

The passage covers original MOD time 17.92..44.80 seconds. The caller supplies a mono,
native-clock crop before listening gain. This module never writes, aligns,
rescales or otherwise changes the candidate audio. Magnitude-band comparisons
allow the documented sub-millisecond SID commit-phase difference between players.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import soundfile as sf

from native_support import CLOCK, PERIOD

REFERENCE = Path(__file__).resolve().parent / "references/cream/reference.wav"
REFERENCE_SHA256 = "d361e57e9f1eddeb34ee5436bfef93dcc9873953e8d67d637d310b0ca0934024"
REFERENCE_GAIN = 8.0
RATE, FRAMES = 22050, 592703
WINDOW_SECONDS = 0.20
RMS_RATIO_LIMITS = (0.80, 1.25)
MINIMUM_SPECTRAL_COSINE = 0.94
GLOBAL_PEAK_RATIO_LIMIT = 1.35
FREQUENCY_EDGES = np.geomspace(50.0, 8000.0, 49)


def _metrics(signal: np.ndarray, rate: int) -> tuple[float, np.ndarray]:
    centered = signal - signal.mean()
    magnitude = abs(np.fft.rfft(centered * np.hanning(len(signal))))
    frequency = np.fft.rfftfreq(len(signal), 1 / rate)
    power, _ = np.histogram(frequency, bins=FREQUENCY_EDGES,
                            weights=magnitude * magnitude)
    return float(np.std(centered)), np.sqrt(power)


def compare(signal: np.ndarray, rate: int = RATE) -> dict:
    """Check level/envelope and spectral shape without candidate gain fitting.

    Fixed reference gain is removed only for measurement. This mixed-audio
    guard complements independent per-channel register/sample verification;
    it cannot prove isolated stem identity or subjective listening approval.
    """
    observed = np.asarray(signal, dtype=np.float64)
    if rate != RATE or observed.ndim != 1 or len(observed) < FRAMES:
        raise ValueError("Cream comparison requires the complete 592,703-frame 22,050 Hz mono passage")
    if not np.isfinite(observed).all():
        raise ValueError("Cream capture contains non-finite values")
    reference_sha = hashlib.sha256(REFERENCE.read_bytes()).hexdigest()
    if reference_sha != REFERENCE_SHA256:
        raise ValueError("Protected Cream listening reference changed")
    reference, reference_rate = sf.read(REFERENCE, dtype="float64")
    if reference_rate != RATE or reference.ndim != 1 or len(reference) != FRAMES:
        raise ValueError("Cream reference has an unexpected rate, channel count or length")
    reference = reference / REFERENCE_GAIN
    observed = observed[:FRAMES]
    length = round(WINDOW_SECONDS * rate)
    ratios, cosines, failures = [], [], []
    for index, start in enumerate(range(0, FRAMES, length)):
        stop = min(start + length, FRAMES)
        reference_rms, reference_bands = _metrics(reference[start:stop], rate)
        observed_rms, observed_bands = _metrics(observed[start:stop], rate)
        if reference_rms <= 0:
            raise ValueError("Cream reference contains an unexpected silent analysis window")
        ratio = observed_rms / reference_rms
        denominator = float(np.linalg.norm(reference_bands) * np.linalg.norm(observed_bands))
        cosine = float(np.dot(reference_bands, observed_bands) / denominator) if denominator else 0.0
        cosine = float(np.clip(cosine, 0.0, 1.0))
        ratios.append(ratio)
        cosines.append(cosine)
        if not RMS_RATIO_LIMITS[0] <= ratio <= RMS_RATIO_LIMITS[1] or cosine < MINIMUM_SPECTRAL_COSINE:
            failures.append(index)
    peak_ratio = float(np.max(abs(observed)) / np.max(abs(reference)))
    return {"passed": not failures and peak_ratio <= GLOBAL_PEAK_RATIO_LIMIT,
            "source_interval_s": [17.92, 44.80], "checked_frames": FRAMES,
            "sample_rate_hz": rate, "window_seconds": WINDOW_SECONDS,
            "windows_checked": len(ratios), "failed_window_indices": failures,
            "rms_ratio_limits": list(RMS_RATIO_LIMITS),
            "minimum_rms_ratio": min(ratios), "maximum_rms_ratio": max(ratios),
            "median_rms_ratio": float(np.median(ratios)),
            "minimum_spectral_cosine_limit": MINIMUM_SPECTRAL_COSINE,
            "minimum_spectral_cosine": min(cosines),
            "median_spectral_cosine": float(np.median(cosines)),
            "global_peak_ratio": peak_ratio, "global_peak_ratio_limit": GLOBAL_PEAK_RATIO_LIMIT,
            "window_metric_columns": ["rms_ratio", "spectral_cosine"],
            "window_metrics": list(map(list, zip(ratios, cosines))),
            "frequency_band_edges_hz": FREQUENCY_EDGES.tolist(),
            "reference_sha256": reference_sha, "reference_gain": REFERENCE_GAIN,
            "scope": "Actual mixed native audio compared with the approved passage. Fixed reference gain only; no candidate gain fit, sample alignment or audio writing. Independent digital verification and listening remain required."}


def compare_full(signal: np.ndarray, rate: int = RATE) -> dict:
    """Measure the protected passage inside a complete, native-clock capture.

    The input begins at the first musical sample latch, as cropped by the
    recording path. Source-tick boundaries are rounded to native sample indices
    before conversion to recording frames. No candidate-dependent time offset
    is measured or applied. The rest of the full song is length-checked only.
    """
    if rate != RATE:
        raise ValueError("Full Cream comparison requires 22,050 Hz audio")
    source_start_tick, source_end_tick, full_ticks = 896, 2240, 12096
    boundaries = [round(tick * CLOCK / (PERIOD * 50))
                  for tick in (source_start_tick, source_end_tick, full_ticks)]
    cycles = [index * PERIOD for index in boundaries]
    frame_start, frame_end, full_frames = [round(clock * rate / CLOCK) for clock in cycles]
    observed = np.asarray(signal, dtype=np.float64)
    if observed.ndim != 1 or len(observed) != full_frames:
        raise ValueError(f"Full Cream comparison requires exactly {full_frames:,} frames of 22,050 Hz mono native audio")
    if not np.isfinite(observed).all():
        raise ValueError("Full Cream capture contains non-finite values")
    if frame_end - frame_start != FRAMES:
        raise ValueError("Source-clock passage length differs from the protected Cream reference")
    result = compare(observed[frame_start:frame_end], rate)
    result["full_capture_clock_crop"] = {
        "source_ticks_per_second": 50, "PAL_clock_hz": CLOCK,
        "native_sample_period_cycles": PERIOD,
        "source_tick_range": [source_start_tick, source_end_tick],
        "native_sample_range": boundaries[:2], "sample_clock_cycle_range": cycles[:2],
        "recording_frame_range": [frame_start, frame_end],
        "protected_sample_clock_interval_s": [clock / CLOCK for clock in cycles[:2]],
        "source_tick_to_native_sample": "round(source_tick * PAL_clock / (sample_period_cycles * 50))",
        "native_sample_to_recording_frame": "round(native_sample * sample_period_cycles * recording_rate / PAL_clock)",
        "full_source_ticks": full_ticks, "full_native_sample_values": boundaries[2],
        "full_nominal_duration_s": full_ticks / 50,
        "full_sample_clock_duration_s": cycles[2] / CLOCK,
        "full_recording_frames": full_frames, "observed_capture_frames": len(observed),
        "recording_rate_hz": rate, "candidate_time_offset_fitted": False,
        "scope": "Only the approved source passage is compared acoustically. The complete input length is checked; the remaining song audio is not compared against a listening reference."}
    return result
