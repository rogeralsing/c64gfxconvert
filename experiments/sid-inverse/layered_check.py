"""Exploratory two-voice snare: filtered SID noise plus an unfiltered body.

Both searches spend the same render budget and share the first quarter's
programs. This single-seed experiment measures a richer program's fit, not
general optimizer superiority or an assembled C64 player's feasibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import cma
import numpy as np
import soundfile as sf

from fit import AudioLoss, prepare_target
from sid_render import PAL_CLOCK_HZ, patch_events, render_events


HERE = Path(__file__).resolve().parent
FILTERS = ("lowpass", "bandpass", "highpass")
SPACE = (
    ("noise_hz", 300.0, 3800.0, "log"),
    ("noise_decay", 3, 12, "int"),
    ("noise_release", 2, 9, "int"),
    ("noise_gate_s", 0.005, 0.4, "log"),
    ("cutoff_start", 0.04, 1.0, "linear"),
    ("cutoff_end", 0.02, 1.0, "linear"),
    ("filter_tau_s", 0.004, 0.3, "log"),
    ("resonance", 0, 8, "int"),
    ("body_hz", 80.0, 450.0, "log"),
    ("body_pitch_start_semitones", 0.0, 24.0, "linear"),
    ("body_pitch_tau_s", 0.003, 0.1, "log"),
    ("body_gate_s", 0.002, 0.15, "log"),
    ("body_decay", 0, 10, "int"),
    ("body_release", 0, 7, "int"),
    ("body_attack", 0, 4, "int"),
)


def decode(vector: np.ndarray, filter_mode: str) -> dict:
    patch = {"filter_mode": filter_mode}
    for position, (name, low, high, scale) in zip(np.clip(vector, 0, 1), SPACE):
        value = low * (high / low) ** float(position) if scale == "log" else low + float(position) * (high - low)
        patch[name] = int(round(value)) if scale == "int" else value
    return patch


def layered_events(patch: dict, duration_s: float, control_hz: int = 200) -> list[tuple[int, int, int]]:
    noise = {
        "waveform": "noise", "filter_mode": patch["filter_mode"],
        "attack": 0, "decay": patch["noise_decay"], "sustain": 0,
        "release": patch["noise_release"], "gate_s": patch["noise_gate_s"],
        "pitch_start_semitones": 0, "pitch_end_semitones": 0,
        "attack_noise_s": 0,
        "cutoff_start": patch["cutoff_start"], "cutoff_end": patch["cutoff_end"],
        "filter_tau_s": patch["filter_tau_s"], "resonance": patch["resonance"],
    }
    body = {
        "waveform": "triangle", "filter_mode": "off",
        "attack": patch["body_attack"], "decay": patch["body_decay"], "sustain": 0,
        "release": patch["body_release"], "gate_s": patch["body_gate_s"],
        "pitch_start_semitones": patch["body_pitch_start_semitones"],
        "pitch_end_semitones": 0, "pitch_tau_s": patch["body_pitch_tau_s"],
        "attack_noise_s": 0,
    }
    noise_events = patch_events(noise, duration_s, patch["noise_hz"], control_hz)
    body_events = [(cycle, register + 7, value)
                   for cycle, register, value in patch_events(body, duration_s, patch["body_hz"], control_hz)
                   if register < 7]
    # Keep the primary voice's global filter/volume program. Voice 2 is not
    # routed through it: primary $D417's routing mask is exactly voice 1.
    merged = sorted(noise_events + body_events, key=lambda event: event[0])
    until = round(duration_s * PAL_CLOCK_HZ)
    serialized = []
    for cycle, register, value in merged:
        if serialized:
            cycle = max(cycle, serialized[-1][0] + 8)
        if cycle < until:
            serialized.append((cycle, register, value))
    return serialized


def render(patch: dict, duration_s: float, sample_rate: int) -> np.ndarray:
    return render_events(layered_events(patch, duration_s), duration_s, sample_rate, "6581")


def run_search(target: np.ndarray, sample_rate: int, method: str, budget: int, seed: int, out: Path) -> dict:
    loss = AudioLoss(target, sample_rate)
    duration = len(target) / sample_rate
    rng = np.random.default_rng(seed)
    started = time.perf_counter()
    history = []
    best = None
    baseline = []
    render_seconds = score_seconds = 0.0

    def evaluate(vector: np.ndarray, family: int, stage: str) -> float:
        nonlocal best, render_seconds, score_seconds
        patch = decode(vector, FILTERS[family])
        began = time.perf_counter()
        raw = render(patch, duration, sample_rate)
        render_seconds += time.perf_counter() - began
        began = time.perf_counter()
        scores, listening = loss.measure(raw)
        score_seconds += time.perf_counter() - began
        entry = {"evaluation": len(history) + 1, "family": family,
                 "stage": stage, "patch": patch, "scores": scores}
        history.append(entry)
        if best is None or scores["spectral"] < best[0]["scores"]["spectral"]:
            best = (entry, raw, listening)
        if len(history) % 100 == 0:
            print(json.dumps({"method": method, "evaluations": len(history),
                              "best_spectral": best[0]["scores"]["spectral"]}), flush=True)
        return scores["spectral"]

    baseline_count = budget // 4
    for index in range(baseline_count):
        vector = np.full(len(SPACE), 0.5) if index < len(FILTERS) else rng.random(len(SPACE))
        family = index % len(FILTERS)
        score = evaluate(vector, family, "baseline")
        baseline.append((family, score, vector))
    if method == "random":
        for index in range(baseline_count, budget):
            evaluate(rng.random(len(SPACE)), index % len(FILTERS), "random")
    else:
        remaining = budget - baseline_count
        for family in range(len(FILTERS)):
            allowance = remaining // len(FILTERS) + int(family < remaining % len(FILTERS))
            initial = min((entry for entry in baseline if entry[0] == family), key=lambda entry: entry[1])[2]
            strategy_seed = seed + 1009 * (family + 1)
            strategy_rng = np.random.RandomState(strategy_seed)
            strategy = cma.CMAEvolutionStrategy(initial, 0.22, {
                "bounds": [0.0, 1.0], "popsize": 10, "verbose": -9,
                "seed": strategy_seed, "randn": strategy_rng.randn,
            })
            used = 0
            while used < allowance:
                vectors = strategy.ask()
                selected = vectors[:min(len(vectors), allowance - used)]
                scores = [evaluate(vector, family, "cmaes") for vector in selected]
                used += len(selected)
                if len(selected) == len(vectors):
                    strategy.tell(vectors, scores)

    elapsed = time.perf_counter() - started
    assert len(history) == budget
    entry, raw, listening = best
    patch = entry["patch"]
    events = layered_events(patch, duration)
    repeated_scores = []
    for _ in range(5):
        scores, _ = loss.measure(render(patch, duration, sample_rate))
        repeated_scores.append(scores)
    out.mkdir(parents=True, exist_ok=True)
    for name, audio, subtype in (("target", loss.target, "PCM_16"), ("best", listening, "PCM_16"), ("raw", raw, "FLOAT")):
        sf.write(out / f"{name}.wav", audio, sample_rate, subtype=subtype)
    for filename, content in (("patch.json", patch), ("events.json", events), ("history.json", history)):
        (out / filename).write_text(json.dumps(content, indent=2) + "\n")
    result = {
        "experiment": "layered-snare", "method": method, "seed": seed,
        "budget": budget, "evaluations": len(history), "baseline_evaluations": baseline_count,
        "model": "6581", "sample_rate": sample_rate, "duration_s": duration,
        "control_hz": 200,
        "control_rate_note": "Gate transitions use additional exact-cycle events, as in the one-voice renderer",
        "best_patch": patch, "best_scores": entry["scores"],
        "best_evaluation": entry["evaluation"],
        "seconds": elapsed, "render_seconds": render_seconds, "score_seconds": score_seconds,
        "repeated_score_evaluations_after_search": len(repeated_scores),
        "repeat_scores": repeated_scores,
        "repeat_mean_spectral": float(np.mean([item["spectral"] for item in repeated_scores])),
        "repeat_std_spectral": float(np.std([item["spectral"] for item in repeated_scores])),
        "resources": {
            "sid_voices": 2, "noise_voice": 1, "triangle_body_voice": 2,
            "shared_filter_used": True, "filter_routing_mask": 1,
            "body_filtered": False, "master_volume": 15,
            "register_writes": len(events),
            "minimum_write_spacing_cycles": min(b[0] - a[0] for a, b in zip(events, events[1:])),
            "bus_write_only_lower_bound_percent": 100 * 6 * len(events) / (duration * PAL_CLOCK_HZ),
            "pcm_data_at_playback": False, "assembled_c64_player_verified": False,
        },
        "parameter_space": [{"name": name, "low": low, "high": high, "scale": scale}
                            for name, low, high, scale in SPACE],
        "family_filters": FILTERS,
        "normalization": "Same AudioLoss as main matrix: remove DC and peak-normalize to 0.8; absolute loudness is not fitted",
        "limitation": "One exploratory seed; 15 parameters and two SID voices versus the main one-voice macro. No inference of general optimizer superiority or real-chip fidelity.",
    }
    (out / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results/layered-snare")
    parser.add_argument("--budget", type=int, default=600)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    if args.budget < 24 or args.budget % 12:
        parser.error("Use a budget >=24 divisible by 12 for equal family allocation")
    source = HERE / "assets/snare.wav"
    audio, rate = sf.read(source)
    target = prepare_target(audio, rate, rate)
    args.out.mkdir(parents=True, exist_ok=True)
    results = {method: run_search(target, rate, method, args.budget, args.seed, args.out / method)
               for method in ("cmaes", "random")}
    histories = {method: json.loads((args.out / method / "history.json").read_text()) for method in results}
    shared = args.budget // 4
    assert all(a["patch"] == b["patch"] for a, b in zip(histories["cmaes"][:shared], histories["random"][:shared]))
    summary = {
        "experiment": "Two-voice true SID synthesis of a recorded snare",
        "reference": str(source.resolve()), "reference_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "prepared_target_frames": len(target), "shared_initial_programs_verified": shared,
        "same_render_budget_per_method": args.budget, "seed": args.seed,
        "runs": results,
        "interpretation": "Exploratory expressiveness check only. Compare each method with its matching one-voice method; the second voice and different program space are additional resources.",
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({method: {"spectral": result["best_scores"]["spectral"],
                               "repeated_mean": result["repeat_mean_spectral"],
                               "seconds": result["seconds"],
                               "register_writes": result["resources"]["register_writes"]}
                      for method, result in results.items()}), flush=True)


if __name__ == "__main__":
    main()
