"""Tune relative instrument balance and parameters on the complete phrase.

No per-instrument normalization is used at this stage. Every candidate plays
all five fitted instruments in their actual note/filter/retrigger context;
only one fixed global recording gain is allowed by SequenceLoss.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path

import cma
import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

from channel_synth import channel_controls, compile_frames, render
from fit_channel import SPACE, pack, unpack
from mod_reader import load_mod
from timeline import build_timeline
from sequence_loss import SequenceLoss

HERE = Path(__file__).resolve().parent
RATE = 11025


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--evaluations", type=int, default=160)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    initial = json.loads(args.input.read_text())
    bank = {int(k): v for k, v in initial["bank"].items()}
    ticks = build_timeline(load_mod(HERE / "sources/stardust-memories.mod"))["ticks"]
    controls = channel_controls(ticks, 29.5, 50)
    target, rate = sf.read(HERE / "results/channel-fit-2/targets/train.wav", dtype="float32")
    target = resample_poly(target, 1, rate // RATE)
    objective = SequenceLoss(target, RATE)
    history = []

    def evaluate(patches: dict, label: str) -> tuple[dict, np.ndarray]:
        audio = render(controls, patches, RATE)[round(.5 * RATE):round(20.5 * RATE)]
        scores = objective.measure(audio)
        history.append({"stage": label, "scores": scores})
        return scores, audio

    scores, audio = evaluate(bank, "initial")
    # Initial local fits each used a free recording gain. Apply physically
    # realizable sustain-level trials, evaluating them in the whole bank.
    for sample in (14, 13, 15, 1, 7):
        base = copy.deepcopy(bank[sample])
        best_patch = base
        for multiplier in (.125, .25, .5, .75, 1.5, 2, 4):
            patch = copy.deepcopy(base)
            patch["level"] = max(.01, min(8, base["level"] * multiplier))
            candidate = dict(bank) | {sample: patch}
            trial, raw = evaluate(candidate, f"balance-{sample}-{multiplier}")
            if trial["loss"] < scores["loss"]:
                best_patch, scores, audio = patch, trial, raw
        bank[sample] = best_patch
    print(json.dumps({"balanced": scores}), flush=True)
    per_sample = max(8, args.evaluations // 5)
    for sample in (14, 13, 15, 1, 7):
        base = bank[sample]
        active = []
        for i, (name, *_rest) in enumerate(SPACE):
            if not base["filter_mode"] and (name.startswith("cutoff") or name in ("resonance", "filter_tracking")):
                continue
            if name.startswith("pulse") and not any(s["control"] & 0x40 for s in base["program"]):
                continue
            active.append(i)
        origin = pack(base)
        strategy = cma.CMAEvolutionStrategy(origin[active], .12,
                    {"bounds": [0, 1], "seed": 20418 + sample, "popsize": 8,
                     "verbose": -9, "maxfevals": per_sample})
        best_patch = base
        remaining = per_sample
        while remaining >= 8 and not strategy.stop():
            vectors = strategy.ask()
            losses = []
            for vector in vectors:
                full = origin.copy()
                full[active] = vector
                patch = unpack(base, full)
                trial_bank = dict(bank) | {sample: patch}
                trial, raw = evaluate(trial_bank, f"whole-cma-{sample}")
                losses.append(trial["loss"])
                if trial["loss"] < scores["loss"]:
                    best_patch, scores, audio = patch, trial, raw
            strategy.tell(vectors, losses)
            remaining -= len(vectors)
        bank[sample] = best_patch
        print(json.dumps({"sample": sample, "whole_phrase_loss": scores["loss"]}), flush=True)
        (args.out / "progress.json").write_text(json.dumps({"sample": sample, "bank": bank, "scores": scores}, indent=2) + "\n")
    # Check the selected bank with the full prefix, not only0.5s of warmup.
    full_audio = render(channel_controls(ticks, 0, 50), bank, RATE)
    full_crop = full_audio[30 * RATE:50 * RATE]
    full_scores = objective.measure(full_crop)
    result = {"channel": 2, "passage_s": [30, 50], "engine": os.environ.get("MOD_CHANNEL_ENGINE", "residfp"),
              "bank": bank, "scores": scores, "full_history_scores": full_scores,
              "history": history, "evaluations": len(history),
              "input": str(args.input.resolve()), "scope": "Whole-sequence fitting and full-prefix validation of one channel; no perceptual quality claim."}
    (args.out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    sf.write(args.out / "native-best.wav", full_crop, RATE, subtype="PCM_16")
    sf.write(args.out / "native-short-history.wav", audio, RATE, subtype="PCM_16")
    sf.write(args.out / "original.wav", target, RATE, subtype="PCM_16")
    # Full-prefix register sequence is used for the final actual C64 audition.
    (args.out / "frameevents-full.json").write_text(json.dumps(compile_frames(channel_controls(ticks, 0, 50), bank), separators=(",", ":")) + "\n")
    (args.out / "frameevents.json").write_text(json.dumps(compile_frames(controls, bank), separators=(",", ":")) + "\n")
    print(json.dumps({"best": scores, "full_prefix": full_scores, "evaluations": len(history)}), flush=True)


if __name__ == "__main__":
    main()
