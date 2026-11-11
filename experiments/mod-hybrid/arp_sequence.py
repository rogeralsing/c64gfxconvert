"""Bounded sample14 arpeggio probe ranked on the complete original channel phrase.

Only sample14 changes. Every other instrument in the completed matched-reSID
bank is preserved. Rendering uses native SID registers and one oscillator;
there is no host pitch shifting, waveform addition or objective-weight change.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import time

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

from channel_synth import channel_controls, compile_frames, render
from mod_reader import load_mod
from sequence_loss import SequenceLoss
from sequence_targets import load_targets
from timeline import build_timeline


HERE = Path(__file__).resolve().parent
RATE = 11025
PATTERN = (4, 4, 6, 4, 4, 7)


def arp_patch(base: dict, update_hz: int, waveform: int) -> dict:
    patch = copy.deepcopy(base)
    pulse = int(base["program"][0].get("pulse", 410))
    patch["program"] = [{"control": waveform | 1, "pulse": pulse,
                          "relative_semitones": 12 * math.log2(PATTERN[index % len(PATTERN)] / 4)}
                         for index in range(256)]
    patch["program_speed"] = 50 / update_hz
    patch["filter_mode"] = 0
    patch["name"] = f"whole-phrase-arp-{update_hz}Hz-wave{waveform:02x}"
    return patch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=HERE / "results/channel-fit-2/whole-refined/result.json")
    parser.add_argument("--out", type=Path, default=HERE / "results/channel-fit-2/arp-sequence")
    args = parser.parse_args()
    # No progress-file fallback: final decisions must use the completed bank.
    source_bytes = args.input.read_bytes()
    source = json.loads(source_bytes)
    if "full_history_scores" not in source or source.get("engine") != "resid":
        raise ValueError("Require the completed matched-reSID whole-refined result")
    bank = {int(key): value for key, value in source["bank"].items()}
    if abs(bank[14]["cycles_per_sample"] / 0.007952286282306162 - 4) > 1e-8:
        raise ValueError("Sample14 bank is not currently rooted at four times the measured source root")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "input-result.json").write_bytes(source_bytes)
    os.environ["MOD_CHANNEL_ENGINE"] = "resid"
    targets = load_targets(HERE / "results/channel-fit-2/targets")
    target = resample_poly(targets["windows"]["train"]["audio"], 1, 2).astype(np.float32)
    objective = SequenceLoss(target, RATE)
    ticks = build_timeline(load_mod(HERE / "sources/stardust-memories.mod"))["ticks"]
    short_controls = channel_controls(ticks, 29.5, 50)
    full_controls = channel_controls(ticks, 0, 50)
    history = []
    started = time.perf_counter()

    def score_short(candidate_bank: dict) -> tuple[dict, np.ndarray]:
        audio = render(short_controls, candidate_bank, RATE)
        audio = audio[round(0.5 * RATE):round(20.5 * RATE)]
        return objective.measure(audio), audio

    baseline_score, baseline_audio = score_short(bank)
    best_score, best_bank, best_audio = baseline_score, copy.deepcopy(bank), baseline_audio
    best_setting = None
    for update_hz in (50, 100, 200):
        for waveform in (0x10, 0x20, 0x40, 0x50):
            candidate = copy.deepcopy(bank)
            candidate[14] = arp_patch(bank[14], update_hz, waveform)
            score, audio = score_short(candidate)
            setting = {"update_hz": update_hz, "waveform": waveform, "level_factor": 1.0}
            history.append({"setting": setting, "scores": score})
            print(json.dumps({"setting": setting, "loss": score["loss"]}), flush=True)
            if score["loss"] < best_score["loss"] - 1e-5:
                best_score, best_bank, best_audio, best_setting = score, candidate, audio, setting
    if best_setting is not None:
        initial_winner = copy.deepcopy(best_bank)
        for factor in (0.5, 1.5):
            candidate = copy.deepcopy(initial_winner)
            candidate[14]["level"] = initial_winner[14]["level"] * factor
            score, audio = score_short(candidate)
            setting = dict(best_setting, level_factor=factor)
            history.append({"setting": setting, "scores": score})
            print(json.dumps({"setting": setting, "loss": score["loss"]}), flush=True)
            if score["loss"] < best_score["loss"] - 1e-5:
                best_score, best_bank, best_audio, best_setting = score, candidate, audio, setting
    baseline_full_audio = render(full_controls, bank, RATE)
    baseline_full_score = objective.measure(baseline_full_audio[30 * RATE:50 * RATE])
    if best_setting is None:
        winner_full_audio, winner_full_score = baseline_full_audio, baseline_full_score
    else:
        winner_full_audio = render(full_controls, best_bank, RATE)
        winner_full_score = objective.measure(winner_full_audio[30 * RATE:50 * RATE])
    accepted = (best_setting is not None and best_score["loss"] < baseline_score["loss"] - 1e-5
                and winner_full_score["loss"] < baseline_full_score["loss"] - 1e-5)
    selected_bank = best_bank if accepted else bank
    selected_audio = best_audio if accepted else baseline_audio
    selected_full = winner_full_audio if accepted else baseline_full_audio
    for sample_id in bank:
        if sample_id != 14 and selected_bank[sample_id] != bank[sample_id]:
            raise ValueError("Arpeggio probe altered another instrument")
    (args.out / "frameevents.json").write_text(json.dumps(compile_frames(short_controls, selected_bank), separators=(",", ":")) + "\n")
    (args.out / "frameevents-full.json").write_text(json.dumps(compile_frames(full_controls, selected_bank), separators=(",", ":")) + "\n")
    sf.write(args.out / "original.wav", target, RATE, subtype="PCM_16")
    sf.write(args.out / "native-baseline.wav", baseline_audio, RATE, subtype="FLOAT")
    sf.write(args.out / "native-best.wav", selected_audio, RATE, subtype="FLOAT")
    sf.write(args.out / "native-full.wav", selected_full, RATE, subtype="FLOAT")
    if not accepted and best_setting is not None:
        sf.write(args.out / "rejected-arp.wav", best_audio, RATE, subtype="FLOAT")
    result = {"channel": 2, "engine": "resid", "input": str(args.input.resolve()),
              "input_sha256": hashlib.sha256(source_bytes).hexdigest(),
              "input_was_completed_result": True, "passage_s": [30, 50], "warmup_s": 0.5,
              "accepted": accepted, "selected": "arpeggio" if accepted else "unchanged baseline",
              "bank": selected_bank, "scores": best_score if accepted else baseline_score,
              "full_history_scores": winner_full_score if accepted else baseline_full_score,
              "baseline_scores_remeasured": baseline_score,
              "baseline_full_history_scores_remeasured": baseline_full_score,
              "best_arp_setting": best_setting,
              "best_arp_scores": best_score if best_setting else None,
              "best_arp_full_history_scores": winner_full_score if best_setting else None,
              "relative_loss_improvement": 1 - best_score["loss"] / baseline_score["loss"],
              "arp_pattern": list(PATTERN), "table_steps": 256,
              "table_coverage_s_at_200hz": 256 / 200,
              "other_instruments_preserved": True,
              "history": history, "candidate_evaluations": len(history),
              "native_renders_including_baselines_and_full_prefix": len(history) + 2 + int(best_setting is not None),
              "elapsed_s": time.perf_counter() - started,
              "selection_rule": "Fixed whole20s objective; require improvement >0.00001 with both0.5s warmup and complete0–50s prefix before accepting",
              "scope": "Bounded one-voice arpeggio probe for sample14 only. All other completed-bank instruments remain unchanged; no objective-weight or source-audio processing changes."}
    (args.out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    if args.input.read_bytes() != source_bytes:
        raise RuntimeError("Completed input bank changed during probe; rerun against a stable final result")
    print(json.dumps({key: result[key] for key in ("accepted", "selected", "baseline_scores_remeasured", "best_arp_setting", "scores", "full_history_scores", "relative_loss_improvement", "candidate_evaluations", "elapsed_s")}, indent=2))


if __name__ == "__main__":
    main()
