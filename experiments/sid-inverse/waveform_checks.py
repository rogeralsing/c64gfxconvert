#!/usr/bin/env python3
"""Replay a fixed guitar patch with real SID combined waveform selections."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from fit import AudioLoss
from sid_render import PAL_CLOCK_HZ, patch_events, render_events


HERE = Path(__file__).resolve().parent
WAVEFORMS = {
    0x10: "triangle", 0x20: "saw", 0x40: "pulse",
    0x30: "triangle+saw", 0x50: "triangle+pulse",
    0x60: "saw+pulse", 0x70: "triangle+saw+pulse",
}


def waveform_events(events: list[tuple[int, int, int]], mask: int) -> list[tuple[int, int, int]]:
    """Replace selected tonal waveforms, retaining gate/TEST and noise attack."""
    return [(cycle, register, ((value & 0x0F) | mask)
             if register == 4 and not (value & 0x80) and (value & 0x70)
             else value)
            for cycle, register, value in events]


def run(results_dir: Path, output: Path, repeats: int = 5) -> dict:
    result_path = results_dir / "results.json"
    result = json.loads(result_path.read_text())
    if result["kind"] != "guitar":
        raise ValueError("Waveform ablation requires the selected guitar result")
    target_path = results_dir / "target.wav"
    target, sample_rate = sf.read(target_path, dtype="float64")
    if target.ndim != 1 or sample_rate != result["sample_rate"]:
        raise ValueError("Target WAV does not match fitted mono sample rate")
    patch = result["best_patch"]
    duration = len(target) / sample_rate
    control_hz = result["control_hz"]
    original = patch_events(patch, duration, result["note_hz"], control_hz)
    loss = AudioLoss(target, sample_rate)
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1, "experiment": "Fixed-patch actual SID waveform ablation",
        "selected_result": str(result_path.resolve()),
        "selected_result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        "target": str(target_path.resolve()),
        "target_sha256": hashlib.sha256(target_path.read_bytes()).hexdigest(),
        "fixed_patch": patch, "original_waveform": patch["waveform"],
        "trained_model": result["model"], "sample_rate": sample_rate,
        "duration_s": duration, "note_hz": result["note_hz"], "control_hz": control_hz,
        "no_retraining": True, "repeats_per_condition": repeats,
        "mechanism": "Change voice1 control-register waveform bits in the existing cycle-timed trace; preserve low control bits and all noise selections",
        "normalization": "Same AudioLoss as training: remove DC and peak-normalize non-silent audio to 0.8; report amplification separately",
        "interpretation": "Measures these waveform selections at one fixed learned patch. Combined SID waveforms are chip behavior, not sums of ordinary oscillators. No conclusion of global fit limits or retrained optimum.",
        "artifact_directory": str(output.resolve()), "conditions": {},
    }
    for model in ("6581", "8580"):
        for mask, label in WAVEFORMS.items():
            events = waveform_events(original, mask)
            name = f"model-{model}-wave-{mask:02x}"
            measured = []
            native_peaks = []
            for repeat in range(repeats):
                raw = render_events(events, duration, sample_rate, model)
                scores, listening = loss.measure(raw)
                measured.append(scores)
                native_peaks.append(float(np.max(np.abs(raw))))
                if repeat == 0:
                    sf.write(output / f"{name}-raw.wav", raw, sample_rate, subtype="FLOAT")
                    sf.write(output / f"{name}.wav", listening, sample_rate, subtype="PCM_16")
            spectral = [entry["spectral"] for entry in measured]
            peaks = [entry["raw_peak"] for entry in measured]
            gain = [entry["normalization_gain"] for entry in measured]
            condition = {
                "model": model, "mask": mask, "mask_hex": f"${mask:02x}", "waveform": label,
                "spectral_mean": float(np.mean(spectral)), "spectral_std_population": float(np.std(spectral)),
                "spectral_min": float(np.min(spectral)), "spectral_max": float(np.max(spectral)),
                "raw_peak_after_dc_mean": float(np.mean(peaks)),
                "raw_absolute_peak_mean": float(np.mean(native_peaks)),
                "normalization_gain_mean": float(np.mean(gain)),
                "normalization_gain_max": float(np.max(gain)),
                "raw_audio": f"{name}-raw.wav", "listening_audio": f"{name}.wav",
                "scores": measured,
                "resources": {
                    "sid_voices": 1, "master_volume": 15,
                    "filter_mode": patch["filter_mode"], "shared_filter": True,
                    "filter_routing_mask": int(patch["filter_mode"] != "off"),
                    "register_writes": len(events),
                    "noise_control_writes_preserved": sum(register == 4 and bool(value & 0x80)
                                                         for _, register, value in events),
                    "minimum_write_spacing_cycles": min(b[0] - a[0] for a, b in zip(events, events[1:])),
                    "bus_write_only_lower_bound_percent": 100 * 6 * len(events) / (duration * PAL_CLOCK_HZ),
                    "pcm_at_playback": False,
                },
            }
            report["conditions"][name] = condition
            print(json.dumps({"model": model, "waveform": label,
                              "mean": condition["spectral_mean"],
                              "std": condition["spectral_std_population"],
                              "normalization_gain": condition["normalization_gain_mean"]}), flush=True)
    (output / "waveform-checks.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=HERE / "results/finalists/guitar")
    parser.add_argument("--out", type=Path, default=HERE / "results/waveform-checks")
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.repeats < 2:
        parser.error("--repeats must be at least two")
    run(args.results_dir, args.out, args.repeats)


if __name__ == "__main__":
    main()
