#!/usr/bin/env python3
"""Fit compact, one-voice SID instruments to isolated reference sounds."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Callable

import cma
import numpy as np
import soundfile as sf
from scipy.ndimage import uniform_filter1d
from scipy.signal import resample_poly, stft


def _normalize(audio: np.ndarray) -> tuple[np.ndarray, float]:
    audio = np.asarray(audio, dtype=np.float64)
    audio = audio - np.mean(audio)
    peak = float(np.max(np.abs(audio)))
    return audio * (0.8 / peak) if peak >= 1e-6 else audio, peak


def prepare_target(audio: np.ndarray, source_sr: int, sample_rate: int) -> np.ndarray:
    """Downmix, resample, trim leading silence and normalize one reference."""
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim == 2:
        audio = np.mean(audio, axis=1)
    if audio.ndim != 1 or not len(audio) or not np.all(np.isfinite(audio)):
        raise ValueError("Reference must contain finite mono or stereo audio")
    if source_sr != sample_rate:
        divisor = int(np.gcd(source_sr, sample_rate))
        audio = resample_poly(audio, sample_rate // divisor, source_sr // divisor)
    audio, peak = _normalize(audio)
    if peak < 1e-6:
        raise ValueError("Reference is silent")
    active = np.flatnonzero(np.abs(audio) >= 0.008)
    # Keep one millisecond before onset. Preserve the reference's full tail.
    start = max(0, int(active[0]) - round(sample_rate * 0.001))
    return audio[start:]


class AudioLoss:
    """Compare equally peak-normalized sounds without aligning each candidate."""

    def __init__(self, target: np.ndarray, sample_rate: int):
        self.target, self.target_peak = _normalize(target)
        self.sample_rate = sample_rate
        self.fft_sizes = (128, 512, 2048)
        self.target_spectra = self._spectra(self.target)
        self.target_envelope = self._envelope(self.target)
        self.target_transient = np.diff(self.target_envelope)

    def _spectra(self, audio: np.ndarray) -> list[np.ndarray]:
        spectra = []
        for size in self.fft_sizes:
            padded = np.pad(audio, (0, max(0, size - len(audio))))
            spectra.append(np.abs(stft(
                padded, fs=self.sample_rate, nperseg=size,
                noverlap=size * 3 // 4, boundary="zeros", padded=True,
            )[2]))
        return spectra

    def _envelope(self, audio: np.ndarray) -> np.ndarray:
        energy = uniform_filter1d(
            audio * audio, max(1, round(self.sample_rate * 0.004)), mode="constant",
        )
        hop = max(1, round(self.sample_rate * 0.002))
        return np.sqrt(np.maximum(energy[::hop], 0.0))

    def measure(self, raw_audio: np.ndarray) -> tuple[dict, np.ndarray]:
        raw_audio = np.asarray(raw_audio, dtype=np.float64)
        if raw_audio.ndim != 1 or not np.all(np.isfinite(raw_audio)):
            raise ValueError("Renderer must return finite mono audio")
        raw_audio = np.pad(raw_audio[:len(self.target)], (0, max(0, len(self.target) - len(raw_audio))))
        audio, peak = _normalize(raw_audio)
        spectra = self._spectra(audio)
        magnitude, log_magnitude = [], []
        for target, candidate in zip(self.target_spectra, spectra):
            magnitude.append(float(np.mean(np.abs(target - candidate)) / (np.mean(target) + 1e-8)))
            log_magnitude.append(float(np.mean(np.abs(np.log(target + 1e-4) - np.log(candidate + 1e-4)))))
        envelope = self._envelope(audio)
        envelope_error = float(np.mean(np.abs(envelope - self.target_envelope)) / (np.mean(self.target_envelope) + 1e-8))
        transient_error = float(np.mean(np.abs(np.diff(envelope) - self.target_transient)) / (np.mean(np.abs(self.target_transient)) + 1e-6))
        magnitude_error = float(np.mean(magnitude))
        log_error = float(np.mean(log_magnitude))
        spectral = 0.60 * magnitude_error + 0.20 * log_error + 0.15 * envelope_error + 0.05 * transient_error
        mse = float(np.mean((audio - self.target) ** 2))
        # Never reward a silent render through normalization or a mostly silent reference.
        silence_penalty = 10.0 if peak < 1e-6 else 0.0
        return {
            "spectral": spectral + silence_penalty,
            "mse": mse + silence_penalty,
            "magnitude": magnitude_error,
            "log_magnitude": log_error,
            "envelope": envelope_error,
            "transient": transient_error,
            "silence_penalty": silence_penalty,
            "raw_peak": peak,
            "normalization_gain": 0.8 / peak if peak >= 1e-6 else 1.0,
        }, audio


def _space(kind: str, duration: float) -> list[tuple]:
    # Bound time constants logarithmically; search pitch in semitones.
    shared = [
        ("decay", 0, 13, "int"), ("release", 0, 11, "int"),
        ("gate_s", 0.008, max(0.009, min(duration, 0.8)), "log"),
        ("cutoff_start", 0.03, 1.0, "linear"),
        ("cutoff_end", 0.01, 1.0, "linear"),
        ("filter_tau_s", 0.003, 0.5, "log"),
        ("resonance", 0, 12, "int"),
    ]
    if kind == "kick":
        return shared + [
            ("pitch_start_semitones", -4, 36, "linear"),
            ("pitch_end_semitones", -30, 0, "linear"),
            ("pitch_tau_s", 0.003, 0.2, "log"),
            ("attack_noise_s", 0, 0.025, "linear"),
        ]
    if kind == "snare":
        return shared + [
            ("pitch_start_semitones", 12, 60, "linear"),
            ("pitch_end_semitones", 0, 48, "linear"),
            ("pitch_tau_s", 0.003, 0.35, "log"),
            ("attack_noise_s", 0.005, 0.08, "linear"),
        ]
    if kind == "guitar":
        return shared + [
            ("attack", 0, 5, "int"), ("sustain", 0, 12, "int"),
            ("pitch_start_semitones", -3, 3, "linear"),
            ("pitch_end_semitones", -1, 1, "linear"),
            ("pitch_tau_s", 0.003, 0.15, "log"),
            ("pulse_start", 0.05, 0.95, "linear"),
            ("pulse_end", 0.05, 0.95, "linear"),
            ("attack_noise_s", 0, 0.015, "linear"),
        ]
    raise ValueError("kind must be kick, snare or guitar")


FAMILIES = {
    "kick": [("triangle", "off"), ("triangle", "lowpass"), ("pulse", "lowpass")],
    "snare": [("noise", "bandpass"), ("noise", "highpass"), ("triangle", "lowpass")],
    "guitar": [("pulse", "lowpass"), ("saw", "lowpass"), ("triangle", "off")],
}


def _patch(vector: np.ndarray, space: list[tuple], family: tuple[str, str]) -> dict:
    patch = {"waveform": family[0], "filter_mode": family[1], "attack": 0,
             "sustain": 0, "pulse_start": 0.5, "pulse_end": 0.5}
    for position, (name, low, high, scale) in zip(vector, space):
        value = np.exp(np.log(low) + float(position) * np.log(high / low)) if scale == "log" else low + float(position) * (high - low)
        patch[name] = int(round(value)) if scale == "int" else float(value)
    return patch


def fit_target(target: np.ndarray, sr: int, kind: str, seed: int = 1,
               budget: int = 240, loss_mode: str = "spectral", *,
               model: str = "6581", note_hz: float = 110.0,
               control_hz: int = 200,
               search_mode: str = "cmaes",
               renderer: Callable | None = None) -> dict:
    """Fit an already prepared target. Budget counts every rendered candidate."""
    if loss_mode not in ("spectral", "mse"):
        raise ValueError("loss_mode must be spectral or mse")
    if search_mode not in ("cmaes", "random"):
        raise ValueError("search_mode must be cmaes or random")
    if (kind not in FAMILIES or budget < 12 or not 8000 <= sr <= 96000
            or note_hz <= 0 or not isinstance(control_hz, int) or not 1 <= control_hz <= 5000):
        raise ValueError("Invalid kind, budget (<12), sample rate, note or control rate")
    target = np.asarray(target, dtype=np.float64)
    if target.ndim != 1 or len(target) < round(sr * 0.02) or not np.all(np.isfinite(target)):
        raise ValueError("Target must contain at least 20 milliseconds of finite mono audio")
    loss = AudioLoss(target, sr)
    if loss.target_peak < 1e-6:
        raise ValueError("Target is silent")
    if renderer is None:
        from sid_render import render_patch
        renderer = render_patch
    duration = len(target) / sr
    families = FAMILIES[kind]
    all_parameters = _space(kind, duration)
    spaces = []
    for waveform, filter_mode in families:
        inactive = set()
        if filter_mode == "off":
            inactive.update(("cutoff_start", "cutoff_end", "filter_tau_s", "resonance"))
        if waveform != "pulse":
            inactive.update(("pulse_start", "pulse_end"))
        if waveform == "noise":
            inactive.add("attack_noise_s")
        spaces.append([entry for entry in all_parameters if entry[0] not in inactive])
    rng = np.random.default_rng(seed)
    history, baseline_candidates = [], []
    started = time.perf_counter()
    render_seconds = score_seconds = 0.0
    best = initial = None

    def evaluate(vector: np.ndarray, family_index: int, stage: str) -> tuple:
        nonlocal best, initial, render_seconds, score_seconds
        patch = _patch(np.clip(vector, 0, 1), spaces[family_index], families[family_index])
        began = time.perf_counter()
        rendered = renderer(patch, duration_s=duration, sample_rate=sr,
                            model=model, note_hz=note_hz, control_hz=control_hz)
        render_elapsed = time.perf_counter() - began
        render_seconds += render_elapsed
        began = time.perf_counter()
        components, audio = loss.measure(rendered)
        score_elapsed = time.perf_counter() - began
        score_seconds += score_elapsed
        candidate = (components[loss_mode], patch, audio, components, np.array(vector), family_index)
        if initial is None:
            initial = candidate
        if best is None or candidate[0] < best[0]:
            best = candidate
        history.append({"evaluation": len(history) + 1, "stage": stage,
                        "family": family_index, "patch": patch,
                        "scores": components, "objective": candidate[0],
                        "best_objective": best[0],
                        "render_seconds": render_elapsed, "score_seconds": score_elapsed})
        return candidate

    # The same first quarter of vectors and families is evaluated for both losses.
    baseline_count = max(len(families), budget // 4)
    for index in range(baseline_count):
        dimensions = len(spaces[index % len(families)])
        vector = np.full(dimensions, 0.5) if index < len(families) else rng.random(dimensions)
        baseline_candidates.append(evaluate(vector, index % len(families), "baseline"))
    remaining = budget - len(history)
    if search_mode == "random":
        for index in range(baseline_count, budget):
            family_index = index % len(families)
            baseline_candidates.append(evaluate(rng.random(len(spaces[family_index])), family_index, "random"))
    for family_index in range(len(families)) if search_mode == "cmaes" else ():
        family_budget = remaining // len(families) + int(family_index < remaining % len(families))
        candidates = [item for item in baseline_candidates if item[5] == family_index]
        start_vector = min(candidates, key=lambda item: item[0])[4]
        # Independent RNG instances make subprocess scheduling irrelevant to results.
        strategy_rng = np.random.RandomState(seed + 1009 * (family_index + 1))
        strategy = cma.CMAEvolutionStrategy(start_vector, 0.22, {
            "bounds": [0.0, 1.0], "popsize": min(8, family_budget),
            "seed": seed + 1009 * (family_index + 1),
            "randn": strategy_rng.randn, "verbose": -9,
        })
        used = 0
        while used < family_budget:
            vectors = strategy.ask()
            available = min(len(vectors), family_budget - used)
            scores = [evaluate(vector, family_index, "cmaes")[0] for vector in vectors[:available]]
            used += available
            if available == len(vectors):
                strategy.tell(vectors, scores)

    random_best = min(baseline_candidates, key=lambda item: item[0])
    return {
        "kind": kind, "seed": seed, "loss_mode": loss_mode, "search_mode": search_mode,
        "model": model, "note_hz": note_hz, "control_hz": control_hz,
        "sample_rate": sr, "duration_s": duration,
        "budget": budget, "evaluations": len(history), "baseline_evaluations": baseline_count,
        "best_patch": best[1], "best_scores": best[3], "best_audio": best[2],
        "initial_patch": initial[1], "initial_scores": initial[3], "initial_audio": initial[2],
        "random_best_patch": random_best[1], "random_best_scores": random_best[3],
        "random_best_audio": random_best[2],
        "baseline_best_spectral": min(item[3]["spectral"] for item in baseline_candidates),
        "baseline_best_mse": min(item[3]["mse"] for item in baseline_candidates),
        "history": history, "seconds": time.perf_counter() - started,
        "render_seconds": render_seconds, "score_seconds": score_seconds,
        "event_budget": {"control_hz": control_hz, "control_ticks": int(np.ceil(duration * control_hz)),
                         "writable_registers_per_tick_upper_bound": 11,
                         "register_writes_upper_bound": 11 * (int(np.ceil(duration * control_hz)) + 3),
                         "note": "Conservative schema bound; renderer/player timing determines actual writes."},
        "parameter_space": [{"name": name, "low": low, "high": high, "scale": scale}
                            for name, low, high, scale in all_parameters],
        "active_parameters_by_family": [[entry[0] for entry in space] for space in spaces],
        "normalization": "Remove DC; peak-normalize each non-silent target/render to 0.8; preserve envelope shape.",
    }


def save_result(result: dict, output: str | Path, target: np.ndarray | None = None) -> None:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    serializable = dict(result)
    for name in ("initial", "random_best", "best"):
        sf.write(output / f"{name}.wav", serializable.pop(f"{name}_audio"), result["sample_rate"], subtype="PCM_16")
    if target is not None:
        sf.write(output / "target.wav", _normalize(target)[0], result["sample_rate"], subtype="PCM_16")
    (output / "patch.json").write_text(json.dumps(result["best_patch"], indent=2) + "\n")
    (output / "history.json").write_text(json.dumps(result["history"], indent=2) + "\n")
    (output / "results.json").write_text(json.dumps(serializable, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--kind", choices=tuple(FAMILIES), required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--budget", type=int, default=240)
    parser.add_argument("--loss", choices=("spectral", "mse"), default="spectral")
    parser.add_argument("--search-mode", choices=("cmaes", "random"), default="cmaes")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-rate", type=int, default=22050)
    parser.add_argument("--model", choices=("6581", "8580"), default="6581")
    parser.add_argument("--note-hz", type=float, default=110.0)
    parser.add_argument("--control-hz", type=int, default=200)
    args = parser.parse_args()
    raw, source_sr = sf.read(args.reference)
    target = prepare_target(raw, source_sr, args.sample_rate)
    result = fit_target(target, args.sample_rate, args.kind, args.seed, args.budget,
                        args.loss, model=args.model, note_hz=args.note_hz,
                        control_hz=args.control_hz, search_mode=args.search_mode)
    result["reference"] = str(args.reference.resolve())
    save_result(result, args.output, target)
    print(json.dumps({key: result[key] for key in
                      ("kind", "seed", "loss_mode", "evaluations", "seconds", "best_scores")}))


if __name__ == "__main__":
    main()
