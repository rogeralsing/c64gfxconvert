#!/usr/bin/env python3
"""Check fitted SID patches without fitting or touching the held-out recording."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from fit import AudioLoss, prepare_target
from sid_render import PAL_CLOCK_HZ, patch_events, render_events, render_patch


ROOT = Path(__file__).resolve().parent


def _winners(results_dir: Path) -> dict[str, tuple[Path, dict]]:
    winners: dict[str, tuple[Path, dict]] = {}
    for path in sorted(results_dir.rglob("results.json")):
        result = json.loads(path.read_text())
        final_selection = result.get("selected_by_repeated_scores", False)
        if (result.get("kind") not in ("kick", "snare", "guitar")
                or (not final_selection and (result.get("search_mode", "cmaes") != "cmaes"
                                             or result.get("loss_mode") != "spectral"))):
            continue
        if result.get("control_hz") != 200:
            continue
        kind = result["kind"]
        if kind not in winners or result["best_scores"]["spectral"] < winners[kind][1]["best_scores"]["spectral"]:
            winners[kind] = (path, result)
    missing = {"kick", "snare", "guitar"} - winners.keys()
    if missing:
        raise ValueError(f"Missing completed 200 Hz fitted/finalist results: {', '.join(sorted(missing))}")
    return winners


def _save_audio(directory: Path, name: str, raw: np.ndarray,
                listening: np.ndarray, sample_rate: int) -> dict:
    raw_name, listening_name = f"{name}-raw.wav", f"{name}.wav"
    sf.write(directory / raw_name, raw, sample_rate, subtype="FLOAT")
    sf.write(directory / listening_name, listening, sample_rate, subtype="PCM_16")
    return {"raw_audio": raw_name, "listening_audio": listening_name,
            "raw_subtype": "FLOAT", "listening_subtype": "PCM_16"}


def _measure(loss: AudioLoss, raw: np.ndarray) -> tuple[dict, np.ndarray]:
    scores, listening = loss.measure(raw)
    return scores, listening


def _history_render(current: dict, preceding: dict, duration: float,
                    preceding_duration: float, sample_rate: int) -> tuple[np.ndarray, np.ndarray, dict]:
    prefix_cycles = round(preceding_duration * PAL_CLOCK_HZ)
    first = patch_events(preceding["best_patch"], preceding_duration,
                         preceding["note_hz"], preceding["control_hz"])
    second = [(cycle + prefix_cycles, register, value)
              for cycle, register, value in patch_events(
                  current["best_patch"], duration, current["note_hz"], current["control_hz"])]
    combined = first + second
    spacing = min(b[0] - a[0] for a, b in zip(combined, combined[1:]))
    if spacing < 8:
        raise ValueError("History event concatenation violates the eight-cycle write spacing")
    total_duration = prefix_cycles / PAL_CLOCK_HZ + duration
    full = render_events(combined, total_duration, sample_rate, current["model"])
    offset = round(prefix_cycles * sample_rate / PAL_CLOCK_HZ)
    count = round(duration * sample_rate)
    second_audio = full[offset:offset + count]
    second_audio = np.pad(second_audio, (0, max(0, count - len(second_audio))))
    return second_audio, full, {
        "preceding_kind": preceding["kind"], "preceding_patch": preceding["best_patch"],
        "preceding_note_hz": preceding["note_hz"], "preceding_duration_s": preceding_duration,
        "second_note_start_cycle": prefix_cycles, "second_note_start_sample": offset,
        "minimum_write_spacing_cycles": spacing, "events": len(combined),
        "reset_between_notes": False,
        "note": "Both notes use their existing patch setup writes; no TEST, zeroing or pre-roll occurs between notes.",
    }


def run(results_dir: Path, output: Path, repeats: int = 10) -> dict:
    winners = _winners(results_dir)
    output.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "schema_version": 1, "results_dir": str(results_dir.resolve()),
        "selection": "Completed 200 Hz repeated-score finalists, or lowest stored spectral score among 200 Hz spectral CMA runs",
        "no_retraining": True,
        "normalization": "Same AudioLoss as fitting: remove DC and peak-normalize each non-silent sound to 0.8",
        "rate_comparison": "Patches learned at 200 Hz; replay rates vary without any optimization",
        "history_comparison": "One reset/pre-roll before first note; preserve complete chip state into second note",
        "sample_rounding": "Second-note sample boundary rounds its exact PAL cycle timestamp",
        "repeats": repeats, "kinds": {},
    }
    prepared = {}
    for kind, (path, result) in winners.items():
        target, sample_rate = sf.read(path.with_name("target.wav"), dtype="float64")
        if target.ndim != 1 or sample_rate != result["sample_rate"]:
            raise ValueError(f"Target WAV shape/rate differs from result at {path}")
        prepared[kind] = (target, sample_rate, len(target) / sample_rate)

    kinds = ("kick", "snare", "guitar")
    for index, kind in enumerate(kinds):
        path, result = winners[kind]
        target, sample_rate, duration = prepared[kind]
        directory = output / kind
        directory.mkdir(parents=True, exist_ok=True)
        loss = AudioLoss(target, sample_rate)
        args = {"duration_s": duration, "sample_rate": sample_rate,
                "model": result["model"], "note_hz": result["note_hz"], "control_hz": 200}
        repeat_scores = []
        fresh_raw = fresh_listening = None
        for repeat in range(repeats):
            raw = render_patch(result["best_patch"], **args)
            scores, listening = _measure(loss, raw)
            repeat_scores.append(scores)
            if repeat == 0:
                fresh_raw, fresh_listening = raw, listening
        spectral = np.array([scores["spectral"] for scores in repeat_scores])
        kind_report = {
            "selected_result": str(path.resolve()), "seed": result["seed"],
            "artifact_directory": str(directory.resolve()),
            "patch": result["best_patch"], "trained_model": result["model"],
            "trained_control_hz": 200, "note_hz": result["note_hz"],
            "sample_rate": sample_rate, "duration_s": duration,
            "stored_training_spectral": result["best_scores"]["spectral"],
            "fresh_render": _save_audio(directory, "fresh", fresh_raw, fresh_listening, sample_rate),
            "repeatability": {
                "spectral_mean": float(np.mean(spectral)),
                "spectral_std_population": float(np.std(spectral)),
                "spectral_min": float(np.min(spectral)), "spectral_max": float(np.max(spectral)),
                "spectral_range": float(np.ptp(spectral)), "scores": repeat_scores,
            }, "control_rates": {}, "models": {}, "histories": {},
        }
        baseline = float(np.mean(spectral))
        for rate in (50, 100, 200, 400):
            raw = render_patch(result["best_patch"], **{**args, "control_hz": rate})
            scores, listening = _measure(loss, raw)
            kind_report["control_rates"][str(rate)] = {
                "scores": scores, "spectral_delta_from_repeat_mean": scores["spectral"] - baseline,
                "retrained": False, **_save_audio(directory, f"control-{rate}", raw, listening, sample_rate),
            }
        for model in ("6581", "8580"):
            raw = render_patch(result["best_patch"], **{**args, "model": model})
            scores, listening = _measure(loss, raw)
            kind_report["models"][model] = {
                "scores": scores, "spectral_delta_from_repeat_mean": scores["spectral"] - baseline,
                "retrained": False, **_save_audio(directory, f"model-{model}", raw, listening, sample_rate),
            }
        for history, preceding_kind in (("same", kind), ("different", kinds[(index + 1) % len(kinds)])):
            preceding = winners[preceding_kind][1]
            raw, full, detail = _history_render(result, preceding, duration,
                                               prepared[preceding_kind][2], sample_rate)
            scores, listening = _measure(loss, raw)
            files = _save_audio(directory, f"history-{history}-second", raw, listening, sample_rate)
            full_name = f"history-{history}-sequence-raw.wav"
            sf.write(directory / full_name, full, sample_rate, subtype="FLOAT")
            kind_report["histories"][history] = {
                **detail, "scores": scores,
                "spectral_delta_from_repeat_mean": scores["spectral"] - baseline,
                **files, "full_sequence_raw_audio": full_name,
            }
        report["kinds"][kind] = kind_report
        print(json.dumps({"kind": kind, "repeat_spectral_mean": baseline,
                          "repeat_spectral_std": float(np.std(spectral))}), flush=True)

    manifest = json.loads((ROOT / "assets/manifest.json").read_text())
    holdout = next(sample for sample in manifest["samples"] if sample["id"] == "guitar-holdout")
    if holdout.get("role") != "holdout" or not holdout.get("root_hz"):
        raise ValueError("Guitar holdout requires an independent recording and measured root_hz")
    training_sample = next(sample for sample in manifest["samples"] if sample["id"] == "guitar")
    if holdout["original_sha256"] == training_sample["original_sha256"]:
        raise ValueError("Holdout must use a different original recording from the training target")
    path = ROOT / "assets" / holdout["file"]
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if content_hash != holdout["sha256"]:
        raise ValueError("Holdout recording differs from the source manifest")
    guitar = winners["guitar"][1]
    raw_target, source_rate = sf.read(path, dtype="float64")
    target = prepare_target(raw_target, source_rate, guitar["sample_rate"])
    raw = render_patch(guitar["best_patch"], len(target) / guitar["sample_rate"],
                       guitar["sample_rate"], guitar["model"], holdout["root_hz"], 200)
    scores, listening = _measure(AudioLoss(target, guitar["sample_rate"]), raw)
    directory = output / "guitar-holdout"
    directory.mkdir(parents=True, exist_ok=True)
    target_name = "target.wav"
    normalized_target = AudioLoss(target, guitar["sample_rate"]).target
    sf.write(directory / target_name, normalized_target, guitar["sample_rate"], subtype="PCM_16")
    report["guitar_holdout"] = {
        "trained_result": str(winners["guitar"][0].resolve()),
        "artifact_directory": str(directory.resolve()),
        "same_patch_as_training": True, "no_retraining": True,
        "reference": str(path.resolve()), "reference_sha256": content_hash,
        "reference_is_independent_recording": True, "reference_was_pitch_shifted": False,
        "training_root_hz": guitar["note_hz"], "holdout_root_hz": holdout["root_hz"],
        "duration_s": len(target) / guitar["sample_rate"], "scores": scores,
        "target_audio": target_name, "model": guitar["model"], "control_hz": 200,
        **_save_audio(directory, "same-patch-transposed", raw, listening, guitar["sample_rate"]),
    }
    (output / "robustness.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str((output / "robustness.json").resolve()),
                      "holdout_spectral": scores["spectral"]}), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results/sweep")
    parser.add_argument("--out", type=Path, default=ROOT / "results/robustness")
    parser.add_argument("--repeats", type=int, default=10)
    args = parser.parse_args()
    if args.repeats < 2:
        parser.error("--repeats must be at least two")
    run(args.results_dir, args.out, args.repeats)


if __name__ == "__main__":
    main()
