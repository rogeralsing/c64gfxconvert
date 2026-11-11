#!/usr/bin/env python3
"""Small independent metric controls and an explicitly synthetic fitting check."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys

import numpy as np

from fit import AudioLoss, fit_target
from sid_render import render_patch


def metric_controls(sample_rate: int, seed: int) -> dict:
    """Use mathematical signals, not SID-generated expected waveforms."""
    count = round(sample_rate * 0.2)
    time = np.arange(count) / sample_rate
    sine = np.sin(2 * np.pi * 440 * time)
    loss = AudioLoss(sine, sample_rate)
    same = loss.measure(sine)[0]
    gain_changed = loss.measure(sine * 0.125)[0]
    inverted = loss.measure(-sine)[0]
    quarter_cycle = loss.measure(np.sin(2 * np.pi * 440 * time + np.pi / 2))[0]
    silence = loss.measure(np.zeros(count))[0]

    rng = np.random.default_rng(seed)
    noise = rng.normal(size=count)
    noise_loss = AudioLoss(noise, sample_rate)
    independent_noise = noise_loss.measure(rng.normal(size=count))[0]
    noise_replaced_by_tone = noise_loss.measure(sine)[0]
    checks = {
        "gain_invariant_spectral": abs(same["spectral"] - gain_changed["spectral"]) < 1e-10,
        "gain_invariant_mse": abs(same["mse"] - gain_changed["mse"]) < 1e-10,
        "inverted_sine_same_magnitude_spectrum": inverted["spectral"] < 1e-10,
        "inverted_sine_high_pcm_error": inverted["mse"] > 1.2,
        "quarter_cycle_spectral_below_silence": quarter_cycle["spectral"] < silence["spectral"],
        "independent_broadband_noise_beats_pure_tone_spectral": independent_noise["spectral"] < noise_replaced_by_tone["spectral"],
        "silence_penalized": silence["silence_penalty"] == 10.0,
        "silence_does_not_win_either_objective": all(silence[key] > gain_changed[key] for key in ("mse", "spectral")),
    }
    return {
        "evidence_scope": "Independent analytic sine and seeded Gaussian noise; no renderer-accuracy claim.",
        "duration_s": count / sample_rate,
        "sine_hz": 440, "gain_multiplier": 0.125, "seed": seed,
        "scores": {"same": same, "gain_changed": gain_changed,
                   "polarity_inverted": inverted, "quarter_cycle_phase_shift": quarter_cycle,
                   "silence": silence, "independent_noise": independent_noise,
                   "noise_replaced_by_tone": noise_replaced_by_tone},
        "checks": checks,
        "interpretation": "Polarity reversal preserves magnitude spectra but incurs PCM MSE. A quarter-cycle phase shift changes STFT boundary behavior. Independent noise realizations are not waveform-identical.",
    }


def averaging_controls(sample_rate: int, seed: int) -> dict:
    """Separate aligned signal averaging from averaging noisy scalar scores."""
    count = round(sample_rate * 0.08)
    rng = np.random.default_rng(seed)
    sigma = 0.05
    # Gaussian noise is an independent mathematical control, not a SID noise model.
    noise = rng.normal(0, sigma, size=(32, 16, count))
    waveform_rows = []
    for repeats in (1, 4, 16):
        means = np.mean(noise[:, :repeats, :], axis=1)
        measured = float(np.sqrt(np.mean(means * means)))
        waveform_rows.append({"averaged_waveforms": repeats, "measured_noise_rms": measured,
                              "expected_noise_rms": sigma / np.sqrt(repeats)})

    time = np.arange(count) / sample_rate
    clean = 0.5 * np.sin(2 * np.pi * 440 * time)
    loss = AudioLoss(clean, sample_rate)
    scores = np.array([loss.measure(clean + realization)[0]["spectral"]
                       for realization in noise.reshape(-1, count)]).reshape(32, 16)
    score_rows = []
    for repeats in (1, 4, 16):
        averaged_scores = np.mean(scores[:, :repeats], axis=1)
        score_rows.append({"averaged_scores": repeats,
                           "mean_score": float(np.mean(averaged_scores)),
                           "score_standard_deviation": float(np.std(averaged_scores, ddof=1))})
    return {
        "evidence_scope": "Independent additive Gaussian-noise experiment. This does not characterize native SID dither or oscillator reset behavior.",
        "seed": seed, "trials": 32, "noise_sigma": sigma,
        "waveform_averaging": waveform_rows, "score_averaging": score_rows,
        "checks": {
            "aligned_noise_rms_decreases": all(a["measured_noise_rms"] > b["measured_noise_rms"] for a, b in zip(waveform_rows, waveform_rows[1:])),
            "score_average_variance_decreases": score_rows[-1]["score_standard_deviation"] < score_rows[0]["score_standard_deviation"],
        },
        "interpretation": "Averaging aligned waveforms reduces independent noise approximately as 1/sqrt(N). Averaging scores reduces ranking uncertainty; it does not itself improve the candidate sound. Unaligned periodic signals can cancel under waveform averaging.",
    }


def synthetic_recovery(sample_rate: int, seed: int, budget: int) -> dict:
    known_patch = {
        "waveform": "triangle", "filter_mode": "lowpass",
        "attack": 0, "decay": 8, "sustain": 0, "release": 4,
        "gate_s": 0.12, "pitch_start_semitones": 24.0,
        "pitch_end_semitones": -17.0, "pitch_tau_s": 0.035,
        "pulse_start": 0.5, "pulse_end": 0.5,
        "cutoff_start": 0.65, "cutoff_end": 0.18,
        "filter_tau_s": 0.08, "resonance": 3,
        "attack_noise_s": 0.005,
    }
    settings = {"duration_s": 0.3, "sample_rate": sample_rate,
                "model": "6581", "note_hz": 110.0, "control_hz": 200}
    # The synthetic target is within the candidate macro family by construction.
    target = render_patch(known_patch, **settings)
    result = fit_target(target, sample_rate, "kick", seed=seed,
                        budget=budget, loss_mode="spectral", model=settings["model"],
                        note_hz=settings["note_hz"], control_hz=settings["control_hz"])
    loss = AudioLoss(target, sample_rate)
    repeated_scores = {}
    for name in ("initial", "random_best", "best"):
        values = [loss.measure(render_patch(result[f"{name}_patch"], **settings))[0]["spectral"]
                  for _ in range(3)]
        repeated_scores[name] = {"scores": values, "mean": float(np.mean(values)),
                                 "standard_deviation": float(np.std(values))}
    initial = repeated_scores["initial"]["mean"]
    best = repeated_scores["best"]["mean"]
    return {
        "evidence_scope": "Synthetic in-family SID target generated by the same renderer. Shows loop improvement only; not renderer accuracy, acoustic imitation or exact parameter recovery.",
        "known_patch": known_patch, "render_settings": settings,
        "seed": seed, "budget": budget, "method": "cmaes", "objective": "spectral",
        "initial_scores": result["initial_scores"], "best_scores": result["best_scores"],
        "best_patch": result["best_patch"], "random_best_patch": result["random_best_patch"],
        "random_best_scores": result["random_best_scores"],
        "repeat_score_evaluations": 9, "repeated_spectral_scores": repeated_scores,
        "mean_improvement_over_initial_fraction": (initial - best) / initial,
        "evaluation_count": result["evaluations"], "fit_seconds": result["seconds"],
        "best_objective_history": [row["best_objective"] for row in result["history"]],
        "checks": {"exact_search_budget": result["evaluations"] == budget,
                   "rerendered_best_beats_initial": best < initial},
        "limitations": "The initial-quarter random best used fewer evaluations than CMA-ES; it is not an equal-budget method comparison. Native renderer sampling can vary slightly between renders despite fixed optimizer seeds.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).parent / "results" / "search-checks.json")
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument("--budget", type=int, default=120)
    parser.add_argument("--sample-rate", type=int, default=22050)
    args = parser.parse_args()
    sources = (Path(__file__), Path(__file__).with_name("fit.py"), Path(__file__).with_name("sid_render.py"))
    result = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "command": [sys.executable, str(Path(__file__).resolve()), "--seed", str(args.seed),
                    "--budget", str(args.budget), "--sample-rate", str(args.sample_rate)],
        "python": platform.python_version(),
        "packages": {package: version(package) for package in ("numpy", "scipy", "cma", "pyresidfp")},
        "source_sha256": {source.name: hashlib.sha256(source.read_bytes()).hexdigest() for source in sources},
        "authoring_gate": {
            "contract": "Gain-normalized objective behavior, phase sensitivity, silence rejection, statistical averaging and end-to-end fitting improvement.",
            "credible_regressions": "Dropped normalization, waveform MSE substituted for spectral comparison, silence handling removed, or optimizer fails to improve a simple representable target.",
            "existing_coverage": "No existing executable checks cover these experiment contracts.",
            "production_seams": "None added; calls existing AudioLoss, fit_target and render_patch entry points.",
        },
        "metric_controls": metric_controls(args.sample_rate, args.seed),
        "averaging_controls": averaging_controls(args.sample_rate, args.seed + 1),
        "synthetic_recovery": synthetic_recovery(args.sample_rate, args.seed, args.budget),
    }
    failures = [f"{section}.{name}" for section in ("metric_controls", "averaging_controls", "synthetic_recovery")
                for name, passed in result[section]["checks"].items() if not passed]
    result["status"] = "pass" if not failures else "fail"
    result["failures"] = failures
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "failures": failures,
                      "synthetic_improvement_fraction": result["synthetic_recovery"]["mean_improvement_over_initial_fraction"],
                      "output": str(args.output.resolve())}))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
