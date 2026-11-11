#!/usr/bin/env python3
"""Measure SID reset isolation without changing the renderer or fitting data."""

from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import soundfile as sf

from fit import AudioLoss, prepare_target
from layered_check import layered_events
import sid_render as sr


HERE = Path(__file__).resolve().parent
PREDECESSORS = {
    "quiet": {"waveform": "triangle", "filter_mode": "off", "sustain": 0,
              "gate_s": 0.01, "decay": 0, "release": 0},
    "loud_lowpass": {"waveform": "pulse", "filter_mode": "lowpass", "sustain": 15,
                     "gate_s": 0.79, "decay": 0, "release": 15, "resonance": 15,
                     "cutoff_start": 0.01, "cutoff_end": 0.01},
    "loud_highpass": {"waveform": "noise", "filter_mode": "highpass", "sustain": 15,
                      "gate_s": 0.79, "decay": 0, "release": 15, "resonance": 15,
                      "cutoff_start": 1.0, "cutoff_end": 1.0},
}


@lru_cache(maxsize=4)
def cached_native(sample_rate: int, model: str):
    """Reproduce the retired cache lifecycle even after the renderer is fixed."""
    return sr.SID(sr.ChipModel.MOS6581 if model == "6581" else sr.ChipModel.MOS8580,
                  sr.SamplingMethod.RESAMPLE, float(sr.PAL_CLOCK_HZ), float(sample_rate))


def cases() -> dict:
    captured = json.loads((HERE / "reset-cases.json").read_text())["cases"]
    result = {}
    for name, case in captured.items():
        events = (layered_events(case["patch"], case["duration_s"]) if name == "layered"
                  else sr.patch_events(case["patch"], case["duration_s"], case["note_hz"]))
        result[name] = {"events": events, "duration_s": case["duration_s"], "patch": case["patch"]}
    return result


def summary(audio: list[np.ndarray], loss: AudioLoss) -> dict:
    scores = [loss.measure(x)[0]["spectral"] for x in audio]
    return {"spectral_scores": scores, "spectral_mean": float(np.mean(scores)),
            "spectral_std": float(np.std(scores)), "spectral_range": float(np.ptp(scores)),
            "pcm_peak_differences_from_first": [float(np.max(np.abs(x - audio[0]))) for x in audio],
            "pcm_rms_differences_from_first": [float(np.sqrt(np.mean((x - audio[0]) ** 2))) for x in audio],
            "pcm_sha256": [hashlib.sha256(x.tobytes()).hexdigest() for x in audio]}


def render_case(case: dict, predecessor: str, mode: str, pre_roll_s: float) -> np.ndarray:
    original_chip = sr._chip
    original_pre_roll = sr.PRE_ROLL_CYCLES

    def chip(sample_rate: int, model: str):
        if mode == "fresh":
            native = sr.SID(sr.ChipModel.MOS6581 if model == "6581" else sr.ChipModel.MOS8580,
                            sr.SamplingMethod.RESAMPLE, float(sr.PAL_CLOCK_HZ), float(sample_rate))
        else:
            native = cached_native(sample_rate, model)
        native.enable_filter(mode != "cached_filter_disabled")
        return native

    sr._chip = chip
    sr.PRE_ROLL_CYCLES = round(pre_roll_s * sr.PAL_CLOCK_HZ)
    try:
        if predecessor != "none":
            sr.render_patch(PREDECESSORS[predecessor], 0.8, 22050, "6581", 440.0)
        return sr.render_events(case["events"], case["duration_s"], 22050, "6581")
    finally:
        sr._chip = original_chip
        sr.PRE_ROLL_CYCLES = original_pre_roll


def verify_current_renderer(case: dict, loss: AudioLoss, controls: dict,
                            repeats: int) -> tuple[dict, bool]:
    """Exercise the real current renderer without replacing its native factory."""
    started = time.perf_counter()
    all_audio = []
    conditions = {}
    for predecessor, preceding_patch in PREDECESSORS.items():
        rendered = []
        for _ in range(repeats):
            sr.render_patch(preceding_patch, 0.8, 22050, "6581", 440.0)
            rendered.append(sr.render_events(case["events"], case["duration_s"], 22050, "6581"))
        details = summary(rendered, loss)
        fresh = controls[f"layered-fresh-0.05-{predecessor}"]
        details["forced_fresh_mean"] = fresh["spectral_mean"]
        details["forced_fresh_std"] = fresh["spectral_std"]
        details["mean_difference_from_forced_fresh"] = abs(details["spectral_mean"] - fresh["spectral_mean"])
        conditions[predecessor] = details
        all_audio.extend(rendered)
    verification = summary(all_audio, loss)
    verification.update({"seconds": time.perf_counter() - started,
                         "renderer": "Actual current render_patch/render_events; native factory and pre-roll are not replaced",
                         "conditions_by_predecessor": conditions,
                         "thresholds": {"maximum_spectral_std": 0.005,
                                        "maximum_condition_mean_span": 0.005,
                                        "maximum_mean_difference_from_forced_fresh": 0.005},
                         "threshold_rationale": "Allow small native model noise while rejecting the observed cached-reset score variation of roughly 0.05 or greater."})
    means = [value["spectral_mean"] for value in conditions.values()]
    verification["condition_mean_span"] = float(np.ptp(means))
    checks = {
        "current_renderer_stable": all(value["spectral_std"] <= 0.005 for value in conditions.values()),
        "predecessor_means_stable": verification["condition_mean_span"] <= 0.005,
        "matches_forced_fresh_control": all(value["mean_difference_from_forced_fresh"] <= 0.005 for value in conditions.values()),
        "forced_fresh_control_stable": all(value["forced_fresh_std"] <= 0.005 for value in conditions.values()),
    }
    verification["checks"] = checks
    return verification, all(checks.values())


def run(out: Path, repeats: int) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    audio, rate = sf.read(HERE / "assets/snare.wav")
    loss = AudioLoss(prepare_target(audio, rate, 22050), 22050)
    all_cases = cases()
    report = {"purpose": "Diagnose reset leakage; no renderer edits and no optimizer rerun",
              "cases": all_cases, "conditions": {}, "repeats": repeats,
              "fixture_sha256": hashlib.sha256((HERE / "reset-cases.json").read_bytes()).hexdigest(),
              "source_evidence": {
                  "filter_reset": "https://github.com/pyresidfp/pyresidfp/blob/main/src/residfp/Filter.cpp",
                  "filter_state": "https://github.com/pyresidfp/pyresidfp/blob/main/src/residfp/Filter.h",
                  "integrators": "https://github.com/pyresidfp/pyresidfp/blob/main/src/residfp/Filter6581.h",
                  "waveform_reset": "https://github.com/pyresidfp/pyresidfp/blob/main/src/residfp/WaveformGenerator.cpp",
                  "envelope_reset": "https://github.com/pyresidfp/pyresidfp/blob/main/src/residfp/EnvelopeGenerator.cpp",
                  "description": "Native reset preserves oscillator accumulator and envelope counter. Filter::reset writes registers but does not clear Vhp/Vbp/Vlp or capacitor state. Initializer TESTs only voice1. Fresh construction isolates these states.",
              }}
    # The complete event list is stored separately rather than duplicated for every condition.
    (out / "cases.json").write_text(json.dumps(all_cases, indent=2) + "\n")
    report["cases"] = {name: {"patch": c["patch"], "duration_s": c["duration_s"], "events": len(c["events"])}
                       for name, c in all_cases.items()}
    for case_name, case in all_cases.items():
        for mode, pre_roll in (("cached", 0.05), ("fresh", 0.05),
                               ("cached", 0.2), ("cached", 1.0),
                               ("cached_filter_disabled", 0.05)):
            for predecessor in PREDECESSORS:
                began = time.perf_counter()
                renders = [render_case(case, predecessor, mode, pre_roll) for _ in range(repeats)]
                name = f"{case_name}-{mode}-{pre_roll}-{predecessor}"
                details = summary(renders, loss)
                details.update({"case": case_name, "mode": mode, "pre_roll_s": pre_roll,
                                "predecessor": predecessor, "seconds": time.perf_counter() - began})
                report["conditions"][name] = details
                sf.write(out / f"{name}.wav", renders[0], 22050, subtype="FLOAT")
                print(json.dumps({"condition": name, "mean": details["spectral_mean"],
                                  "std": details["spectral_std"]}), flush=True)
        # Every isolated process begins with identical model singleton/dither phase.
        isolated = []
        for index in range(3):
            destination = out / f"{case_name}-isolated-{index}.npy"
            completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker",
                                        case_name, "--worker-output", str(destination)],
                                       capture_output=True, text=True, timeout=45)
            if completed.returncode:
                raise RuntimeError(completed.stderr)
            isolated.append(np.load(destination))
        report["conditions"][f"{case_name}-isolated"] = summary(isolated, loss)
        (out / "diagnosis.json").write_text(json.dumps(report, indent=2) + "\n")
    verification, applied = verify_current_renderer(all_cases["layered"], loss,
                                                   report["conditions"], repeats)
    report["fresh_core_verification"] = verification
    report["decision"] = {
        "fix": "Construct a fresh native SID for every render_events call; remove LRU chip cache",
        "applied": applied,
        "basis": "Measured real current-renderer stability and agreement with forced-fresh controls after three different preceding sounds",
        "continuous_history": "One render_events call still preserves state between all notes in its trace",
        "old_search_results": "Retained as provisional; require fresh-instance reruns",
        "remaining_variation": "Small native model noise remains; do not assert bitwise PCM identity",
    }
    (out / "diagnosis.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results/reset-diagnosis")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--worker", choices=("one_voice", "layered"))
    parser.add_argument("--worker-output", type=Path)
    args = parser.parse_args()
    if args.repeats < 3:
        parser.error("--repeats must be at least three")
    if args.worker:
        np.save(args.worker_output, render_case(cases()[args.worker], "none", "fresh", 0.05))
        return
    report = run(args.out, args.repeats)
    print(json.dumps({"decision": report["decision"],
                      "current_renderer_checks": report["fresh_core_verification"]["checks"]}), flush=True)
    if not report["decision"]["applied"]:
        raise SystemExit("Current renderer did not pass measured fresh-state isolation")


if __name__ == "__main__":
    main()
