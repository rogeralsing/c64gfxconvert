"""Fit instrument programs, then evaluate one complete original MOD channel.

Training concatenates several real notes/pitches per instrument and keeps SID
state through every retrigger. Selection and comparison use the complete
30–50s isolated sequence. Later original passages remain validation-only.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import time

import cma
import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

from channel_synth import channel_controls, compile_frames, example_patch, generic_patch, render
from mod_reader import load_mod
from timeline import build_timeline
from sequence_loss import SequenceLoss
from sequence_targets import load_targets

HERE = Path(__file__).resolve().parent
RATE = 11025
SPACE = [("attack", 0, 4, "int"), ("decay", 0, 12, "int"),
         ("sustain", 0, 15, "int"), ("release", 0, 12, "int"),
         ("gate_s", .015, 1.4, "log"), ("program_speed", .25, 2.5, "log"),
         ("pulse_scale", .25, 4, "log"), ("pulse_offset", -.15, .5, "linear"),
         ("cutoff_start", .005, .4, "log"), ("cutoff_end", .003, .4, "log"),
         ("cutoff_tau", .008, .6, "log"), ("resonance", 0, 15, "int"),
         ("filter_tracking", 0, 2, "linear"), ("pitch_start", -3, 3, "linear"),
         ("pitch_tau", .008, .2, "log"), ("level", .01, 8, "log")]


def unpack(base: dict, vector: np.ndarray) -> dict:
    patch = copy.deepcopy(base)
    for (name, lo, hi, scale), value in zip(SPACE, np.clip(vector, 0, 1)):
        value = float(np.exp(np.log(lo) + value * np.log(hi / lo))) if scale == "log" else float(lo + value * (hi - lo))
        patch[name] = round(value) if scale == "int" else value
    return patch


def pack(patch: dict) -> np.ndarray:
    return np.asarray([np.clip(np.log(max(lo, patch[name]) / lo) / np.log(hi / lo)
                               if scale == "log" else (patch[name] - lo) / (hi - lo), .001, .999)
                       for name, lo, hi, scale in SPACE])


def families(sample: int, cycles: float, seeds: list[dict]) -> list[dict]:
    candidates = []
    if sample in (1, 7):
        waves = [(0x80, 1024), (0x20, 1024), (0x10, 1024)]
        factors = (.5, 1, 2)
    else:
        waves = [(0x10, 2048), (0x20, 2048), (0x40, 205), (0x40, 614), (0x40, 2048), (0x50, 410)]
        factors = (.5, 1, 2, 4) if sample == 14 else (.5, 1, 2)
    for factor in factors:
        for mode in (0, 0x10, 0x20):
            for wave, pulse in waves:
                patch = generic_patch(cycles * factor, wave, pulse, mode)
                patch.update(cutoff_start=.08, cutoff_end=.035, resonance=10,
                             filter_tracking=1.0, gate_s=.25)
                if sample in (1, 7) and wave != 0x80:
                    patch["program"] = [{"control": 0x81, "pulse": pulse},
                                        {"control": wave | 1, "pulse": pulse},
                                        {"control": wave, "pulse": pulse}]
                patch["name"] = f"generic-{wave:02x}-{pulse}-filter{mode:02x}-x{factor}"
                candidates.append(patch)
    if sample not in (1, 7):
        for seed in seeds:
            for factor in (1, 2, 4) if sample == 14 else (1, 2):
                for mode in (0, 0x20):
                    patch = example_patch(seed, cycles * factor, mode)
                    patch.update(cutoff_start=.08, cutoff_end=.035, resonance=10,
                                 filter_tracking=1.0)
                    candidates.append(patch)
    return candidates


def note_training(data: dict, sample: int, ticks: list[dict]) -> tuple[np.ndarray, list[dict], list[int]]:
    contexts = [c for c in data["contexts_by_sample"][sample] if c["end_s"] <= 50 + 1e-8]
    controls, audio, selected = [], [], []
    for context in contexts[:4]:
        duration = min(context["duration_s"], .30)
        count = max(1, round(duration * 200))
        segment = channel_controls(ticks, context["start_s"], context["start_s"] + count / 200)
        segment[0]["trigger"] = True
        for frame, item in enumerate(segment):
            item["age"] = frame / 200
        controls.extend(segment)
        raw = context["audio"][:round(count / 200 * 22050)]
        audio.append(resample_poly(raw, 1, 2).astype(np.float32))
        selected.append(context["note_index"])
    target = np.concatenate(audio)
    if len(target) < 4096:
        raise ValueError("Training notes need at least4096 frames for the longest spectrum")
    expected = round(len(controls) / 200 * RATE)
    target = np.pad(target[:expected], (0, max(0, expected - len(target))))
    return target, controls, selected


def fit_one(sample: int, data: dict, ticks: list[dict], cycles: float,
            seeds: list[dict], out: Path, refinements: int) -> list[dict]:
    target, controls, notes = note_training(data, sample, ticks)
    objective = SequenceLoss(target, RATE)
    history = []
    began = time.perf_counter()

    def evaluate(patch: dict, stage: str) -> dict:
        audio = render(controls, {sample: patch}, RATE)
        scores = objective.measure(audio)
        result = {"patch": patch, "scores": scores, "stage": stage}
        history.append(result)
        return result

    screened = [evaluate(patch, "source-screen") for patch in families(sample, cycles, seeds)]
    ordered = sorted(screened, key=lambda x: x["scores"]["loss"])
    # Preserve a filtered contender even if an untuned resonant cutoff makes
    # its initial score worse. The source has weak roots with strong partials.
    starts = [ordered[0]]
    # A strong fourth partial must not eliminate root-frequency candidates
    # before their resonant filter has been tuned. Refine separate registers.
    for factor in ((.5, 1, 2, 4) if sample == 14 else (.5, 1, 2)):
        option = next((x for x in ordered if x["patch"]["filter_mode"]
                       and abs(x["patch"]["cycles_per_sample"] / cycles - factor) < .001), None)
        if option is not None and option not in starts:
            starts.append(option)
    source_option = next((x for x in ordered if not x["patch"]["name"].startswith("generic")), None)
    if source_option is not None and source_option not in starts:
        starts.append(source_option)
    for family_index, initial in enumerate(starts):
        base = initial["patch"]
        strategy = cma.CMAEvolutionStrategy(pack(base), .19,
                    {"bounds": [0, 1], "seed": 418 + sample * 11 + family_index,
                     "popsize": 8, "verbose": -9, "maxfevals": refinements // len(starts)})
        remaining = refinements // len(starts)
        while remaining >= 8 and not strategy.stop():
            vectors = strategy.ask()
            results = [evaluate(unpack(base, vector), "cma-sequence") for vector in vectors]
            strategy.tell(vectors, [x["scores"]["loss"] for x in results])
            remaining -= len(vectors)
    ordered = sorted(history, key=lambda x: x["scores"]["loss"])
    selected_candidates = []
    for candidate in ordered:
        signature = json.dumps(candidate["patch"], sort_keys=True)
        if all(signature != json.dumps(q["patch"], sort_keys=True) for q in selected_candidates):
            selected_candidates.append(candidate)
        if len(selected_candidates) == 8:
            break
    receipt = {"sample": sample, "training_note_indices": notes,
               "training_seconds": len(target) / RATE, "evaluations": len(history),
               "elapsed_s": time.perf_counter() - began,
               "best": selected_candidates[0], "finalists": selected_candidates,
               "history": history}
    (out / f"sample-{sample:02d}.json").write_text(json.dumps(receipt, indent=2) + "\n")
    sf.write(out / f"sample-{sample:02d}-target.wav", target, RATE, subtype="PCM_16")
    sf.write(out / f"sample-{sample:02d}-best.wav", render(controls, {sample: selected_candidates[0]["patch"]}), RATE, subtype="PCM_16")
    print(json.dumps({"sample": sample, "evaluations": len(history),
                      "best_loss": receipt["best"]["scores"]["loss"],
                      "seed": receipt["best"]["patch"]["name"],
                      "seconds": receipt["elapsed_s"]}), flush=True)
    return selected_candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results/channel-fit-2/search")
    parser.add_argument("--refinements", type=int, default=160)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    data = load_targets(HERE / "results/channel-fit-2/targets")
    mod = load_mod(HERE / "sources/stardust-memories.mod")
    ticks = build_timeline(mod)["ticks"]
    info = {s["id"]: s for s in json.loads((HERE / "results/instrument-analysis.json").read_text())["samples"]}
    examples = json.loads((HERE / "results/channel-fit-2/sid-examples.json").read_text())
    bank, finalists = {}, {}
    for sample in (14, 13, 15, 1, 7):
        path = args.out / f"sample-{sample:02d}.json"
        if path.exists():
            selected = json.loads(path.read_text())["finalists"]
        else:
            cycles = info[sample]["cycles_per_sample"] or 1 / 16
            selected = fit_one(sample, data, ticks, cycles, examples["seeds"], args.out, args.refinements)
        bank[sample] = selected[0]["patch"]
        finalists[sample] = selected
    controls = channel_controls(ticks, 29.5, 50)
    target = resample_poly(data["windows"]["train"]["audio"], 1, 2).astype(np.float32)
    objective = SequenceLoss(target, RATE)

    def score_bank(patches: dict) -> tuple[dict, np.ndarray]:
        audio = render(controls, patches, RATE)[round(.5 * RATE):round(20.5 * RATE)]
        return objective.measure(audio), audio

    scores, audio = score_bank(bank)
    history = [{"stage": "assembled-instrument-winners", "scores": scores}]
    print(json.dumps({"whole_sequence_initial": scores}), flush=True)
    # Candidate decisions use the complete sequence, including other programs
    # and their prior-note/filter history, rather than isolated tone score.
    for sample in (14, 13, 15, 1, 7):
        for candidate in finalists[sample][1:4]:
            trial = dict(bank) | {sample: candidate["patch"]}
            trial_scores, trial_audio = score_bank(trial)
            history.append({"sample": sample, "scores": trial_scores})
            if trial_scores["loss"] < scores["loss"]:
                bank, scores, audio = trial, trial_scores, trial_audio
    record = {"channel": 2, "passage_s": [30, 50], "warmup_s": .5,
              "bank": bank, "scores": scores, "whole_sequence_selection": history,
              "source_seed_archive_sha256": examples["archive_sha256"],
              "scope": "Fitted single-channel SID programs. Objective improvement does not establish listener recognition."}
    (args.out / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    sf.write(args.out / "native-best.wav", audio, RATE, subtype="PCM_16")
    sf.write(args.out / "original.wav", target, RATE, subtype="PCM_16")
    (args.out / "frameevents.json").write_text(json.dumps(compile_frames(controls, bank), separators=(",", ":")) + "\n")
    print(json.dumps({"whole_sequence_best": scores, "result": str(args.out / 'result.json')}), flush=True)


if __name__ == "__main__":
    main()
