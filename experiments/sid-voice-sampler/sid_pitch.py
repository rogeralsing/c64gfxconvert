"""Measure reusable SID instrument roots from their original sample waveforms."""
from __future__ import annotations

import math

import numpy as np
from scipy.signal import correlate, resample_poly

def melody_pitch(mod: dict, instrument: dict) -> dict:
    sample = mod["samples"][instrument["source_instrument"] - 1]
    analysis = instrument["pitch_analysis"]
    count, upsample = analysis["sample_count"], analysis["upsample"]
    low, high = analysis["period_band_samples"]
    raw = np.frombuffer(sample["data"], np.int8).astype(float) / 128
    if sample["loop_length"] > 2 and analysis.get("region", "loop_if_present") != "attack":
        loop = raw[sample["loop_start"]:sample["loop_start"] + sample["loop_length"]]
        segment = np.tile(loop, math.ceil(count / len(loop)))[:count]
    else:
        segment = raw[:count]
    interpolated = resample_poly(segment - segment.mean(), upsample, 1)
    acf = correlate(interpolated, interpolated, mode="full", method="fft")[len(interpolated) - 1:]
    acf /= acf[0]
    peak = low * upsample + int(np.argmax(acf[low * upsample:high * upsample]))
    adjustment = .5 * (acf[peak - 1] - acf[peak + 1]) / (
        acf[peak - 1] - 2 * acf[peak] + acf[peak + 1])
    period = (peak + adjustment) / upsample
    if acf[peak] < analysis["minimum_autocorrelation"]:
        raise ValueError("Melody instrument has no sufficiently stable measured root")
    return {"instrument": instrument["source_instrument"], "source_period_samples": period,
            "cycles_per_source_sample": 1 / period, "autocorrelation": float(acf[peak]),
            "pulse_width": instrument.get("pulse_width", 2048),
            "method": f"Original instrument's first {count} samples (or repeating loop), {upsample}-fold interpolation, autocorrelation peak in the configured {low}–{high} sample period band; parabolic refinement.",
            "region": analysis.get("region", "loop_if_present"),
            "scope": f'A monophonic {instrument["program"]} approximation. The recorded source has a different envelope and may have pitch drift.'}
