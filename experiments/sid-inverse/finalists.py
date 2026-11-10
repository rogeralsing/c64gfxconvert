"""Re-evaluate finalists repeatedly; select by mean score instead of a lucky render."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from fit import AudioLoss
from sid_render import patch_events, render_patch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--top", type=int, default=6)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    runs = [(path, json.loads(path.read_text())) for path in sorted(args.results_dir.rglob("results.json"))]
    report = {"repeats": args.repeats, "top_per_method_seed": args.top,
              "selection": "Mean spectral loss across repeated renderings; no waveform averaging",
              "kinds": {}}
    for kind in ("kick", "snare", "guitar"):
        matching = [(path, run) for path, run in runs if run["kind"] == kind]
        if not matching:
            raise ValueError(f"No completed runs for {kind}")
        reference_path, example = matching[0]
        target, sample_rate = sf.read(reference_path.with_name("target.wav"))
        loss = AudioLoss(target, sample_rate)
        candidates = []
        global_seen = {}
        for path, run in matching:
            # Retain distinct programs; repeated samples of one vector are not
            # independent finalists. Include MSE-selected programs in cross-scoring.
            seen = set()
            count = 0
            for event in sorted(run["history"], key=lambda entry: entry["scores"][run["loss_mode"]]):
                identity = json.dumps(event["patch"], sort_keys=True)
                if identity in seen:
                    continue
                seen.add(identity)
                origin = {"run": str(path.resolve()), "stage": event["stage"],
                          "evaluation": event["evaluation"]}
                count += 1
                if identity in global_seen:
                    global_seen[identity]["origins"].append(origin)
                    if count == args.top:
                        break
                    continue
                candidate = {"run": str(path.resolve()), "search_mode": run["search_mode"],
                             "loss_mode": run["loss_mode"], "seed": run["seed"],
                             "evaluation": event["evaluation"], "patch": event["patch"],
                             "stored_scores": event["scores"], "repeat_scores": [], "origins": [origin]}
                for _ in range(args.repeats):
                    raw = render_patch(event["patch"], len(target) / sample_rate, sample_rate,
                                       run["model"], run["note_hz"], run["control_hz"])
                    score, _ = loss.measure(raw)
                    candidate["repeat_scores"].append(score)
                for metric in ("spectral", "mse", "envelope", "magnitude", "transient"):
                    values = [score[metric] for score in candidate["repeat_scores"]]
                    candidate[f"{metric}_mean"] = float(np.mean(values))
                    candidate[f"{metric}_std"] = float(np.std(values))
                candidates.append(candidate)
                global_seen[identity] = candidate
                if count == args.top:
                    break
        candidates.sort(key=lambda candidate: candidate["spectral_mean"])
        winner = candidates[0]
        stored_winner = min(candidates, key=lambda candidate: candidate["stored_scores"]["spectral"])
        directory = args.out / kind
        directory.mkdir(parents=True, exist_ok=True)
        selected_run = json.loads(Path(winner["run"]).read_text())
        raw = render_patch(winner["patch"], len(target) / sample_rate, sample_rate,
                           selected_run["model"], selected_run["note_hz"], selected_run["control_hz"])
        selected_scores, listening = loss.measure(raw)
        sf.write(directory / "target.wav", loss.target, sample_rate, subtype="PCM_16")
        sf.write(directory / "best.wav", listening, sample_rate, subtype="PCM_16")
        sf.write(directory / "raw.wav", raw, sample_rate, subtype="FLOAT")
        (directory / "patch.json").write_text(json.dumps(winner["patch"], indent=2) + "\n")
        events = patch_events(winner["patch"], len(target) / sample_rate, selected_run["note_hz"], selected_run["control_hz"])
        (directory / "events.json").write_text(json.dumps(events, indent=2) + "\n")
        selected = {key: selected_run[key] for key in ("kind", "seed", "search_mode", "loss_mode", "model", "sample_rate", "note_hz", "control_hz", "duration_s")}
        selected.update({"best_patch": winner["patch"], "best_scores": selected_scores,
                         "selection_mean_spectral": winner["spectral_mean"],
                         "selection_std_spectral": winner["spectral_std"], "selected_from": winner["run"],
                         "register_writes": len(events), "selected_by_repeated_scores": True})
        (directory / "results.json").write_text(json.dumps(selected, indent=2) + "\n")
        report["kinds"][kind] = {"winner": winner, "candidates": candidates, "selected_directory": str(directory.resolve()),
                                 "validation_evaluations": len(candidates) * args.repeats,
                                 "single_render_winner": {"run": stored_winner["run"], "patch": stored_winner["patch"]},
                                 "repeated_scoring_changed_winner": stored_winner["patch"] != winner["patch"]}
        print(json.dumps({"kind": kind, "candidates": len(candidates), "winner_method": winner["search_mode"],
                          "winner_loss": winner["loss_mode"], "mean": winner["spectral_mean"],
                          "std": winner["spectral_std"]}), flush=True)
    (args.out / "selection.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
