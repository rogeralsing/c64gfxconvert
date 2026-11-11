"""Bounded native-6581 sample14 probe: two oscillators versus one fast arpeggio.

All candidate mixing uses one actual SID emulator and its writable registers.
No rendered voices are added or pitch-shifted in host audio code. This probes
one MOD track using multiple actual note contexts, not a replacement full mix.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

from channel_resid import make_sid
from channel_synth import compile_frames
from fit_channel import note_training
from mod_reader import load_mod
from sequence_loss import SequenceLoss
from sequence_targets import load_targets
from timeline import build_timeline


HERE = Path(__file__).resolve().parent
PAL = 985248
PAULA = 3546894.6
FRAME_CYCLES = 4926
RATE = 11025
ROOT_CYCLES = 0.007952286282306162
WAVES = ((0x10, 2048), (0x20, 2048), (0x40, 901))


def native_render(program: dict) -> np.ndarray:
    chip = make_sid(RATE)
    chip.reset()
    for register in range(25):
        chip.write(register, 0)
    chip.clock(round(PAL * 0.05))
    output = []
    current = 0
    for frame, writes in enumerate(program["frames"]):
        for offset, (register, value) in enumerate(writes):
            cycle = frame * FRAME_CYCLES + offset * 8
            if cycle > current:
                output.append(chip.clock(cycle - current))
            chip.write(register, value)
            current = cycle
    until = len(program["frames"]) * FRAME_CYCLES
    if until > current:
        output.append(chip.clock(until - current))
    audio = np.concatenate(output).astype(np.float32) / 32768 if output else np.empty(0, dtype=np.float32)
    count = round(program["duration_s"] * RATE)
    return np.pad(audio[:count], (0, max(0, count - len(audio))))


def compile_probe(controls: list[dict], candidate: dict, template: dict) -> dict:
    frames = []
    previous = {}
    voices = candidate["voices"]
    for index, state in enumerate(controls):
        writes = []

        def emit(register: int, value: int, force: bool = False) -> None:
            value = int(value)
            if force or previous.get(register) != value:
                writes.append([register, value])
                previous[register] = value

        if index == 0:
            for register in range(25):
                emit(register, 0, True)
            emit(24, 15, True)
        age = state["age"]
        trigger = state["trigger"] or index == 0
        for voice_index, voice in enumerate(voices):
            offset = voice_index * 7
            if trigger:
                emit(offset + 4, previous.get(offset + 4, 0) & 0xFE, True)
            ratio = voice["ratio"]
            if candidate.get("arp_hz"):
                pattern = candidate["arp_pattern"]
                ratio = pattern[int(age * candidate["arp_hz"] + 1e-8) % len(pattern)]
            semitones = template["pitch_start"] * np.exp(-age / template["pitch_tau"])
            frequency_hz = PAULA / state["period"] * ROOT_CYCLES * ratio * 2 ** (semitones / 12)
            frequency = max(0, min(65535, round(frequency_hz * 2**24 / PAL)))
            sustain = max(0, min(15, round(voice["sustain"] * state["volume"] / 64)))
            control = voice["wave"] | int(age < template["gate_s"] and state["volume"] > 0)
            emit(offset + 5, template["attack"] * 16 + template["decay"])
            emit(offset + 6, sustain * 16 + template["release"])
            emit(offset, frequency & 255)
            emit(offset + 1, frequency >> 8)
            emit(offset + 2, voice["pulse"] & 255)
            emit(offset + 3, voice["pulse"] >> 8)
            emit(offset + 4, control, trigger)
        mode = candidate.get("filter_mode", 0)
        if mode:
            cutoff = candidate["cutoff"] * (151 / state["period"])
            cutoff = max(0, min(2047, round(cutoff * 2047)))
            emit(21, cutoff & 7)
            emit(22, cutoff >> 3)
        emit(23, candidate.get("resonance", 0) * 16 + ((1 << len(voices)) - 1 if mode else 0))
        emit(24, mode | 15)
        frames.append(writes)
    return {"frames": frames, "frame_cycles": FRAME_CYCLES, "rate_hz": 200,
            "duration_s": len(controls) / 200, "sample_rate": RATE,
            "model": "MOS6581 matched VICE3.10 reSID", "sid_voices": len(voices),
            "scope": "Register-driven one MOD track; all oscillator mixing and filtering happen inside one physical SID model."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results/channel-fit-2/two-voice-probe")
    parser.add_argument("--single-result", type=Path, default=HERE / "results/channel-fit-2/resid-search/sample-14.json")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    targets = load_targets(HERE / "results/channel-fit-2/targets")
    ticks = build_timeline(load_mod(HERE / "sources/stardust-memories.mod"))["ticks"]
    target, controls, note_indices = note_training(targets, 14, ticks)
    periods = sorted({state["period"] for state in controls if state["trigger"]})
    if len(periods) < 3:
        raise ValueError("Probe requires at least three actual original note pitches")
    known = json.loads(args.single_result.read_text())
    if known["training_note_indices"] != note_indices:
        raise ValueError("Single-voice comparison used a different training-note fixture")
    objective = SequenceLoss(target, RATE)
    template = known["best"]["patch"]
    baseline_frames = compile_frames(controls, {14: template})
    baseline_audio = native_render(baseline_frames)
    baseline = objective.measure(baseline_audio)
    sf.write(args.out / "original-contexts.wav", target, RATE, subtype="PCM_16")
    sf.write(args.out / "single-voice-known-best.wav", baseline_audio, RATE, subtype="FLOAT")
    history = []
    best_two = best_arp = None
    started = time.perf_counter()

    def evaluate(candidate: dict, stage: str) -> dict:
        nonlocal best_two, best_arp
        frames = compile_probe(controls, candidate, template)
        audio = native_render(frames)
        scores = objective.measure(audio)
        record = {"candidate": candidate, "stage": stage, "scores": scores}
        history.append(record)
        best = best_arp if candidate.get("arp_hz") else best_two
        if best is None or scores["loss"] < best["record"]["scores"]["loss"]:
            item = {"record": record, "audio": audio, "frames": frames}
            if candidate.get("arp_hz"):
                best_arp = item
            else:
                best_two = item
        if len(history) % 30 == 0:
            print(json.dumps({"evaluations": len(history), "best_two_voice_loss": best_two["record"]["scores"]["loss"]}), flush=True)
        return record

    for companion in (0.5, 1, 2, 6, 7):
        for wave_a, pulse_a in WAVES:
            for wave_b, pulse_b in WAVES:
                for level_a, level_b in ((15, 3), (15, 7), (12, 12)):
                    evaluate({"voices": [{"ratio": 4, "wave": wave_a, "pulse": pulse_a, "sustain": level_a},
                                         {"ratio": companion, "wave": wave_b, "pulse": pulse_b, "sustain": level_b}],
                              "filter_mode": 0}, "two-voice-screen")
    top = sorted(history, key=lambda record: record["scores"]["loss"])[:10]
    for record in top:
        for mode, cutoff in ((0x10, 0.08), (0x20, 0.04), (0x20, 0.10)):
            candidate = copy.deepcopy(record["candidate"])
            candidate.update(filter_mode=mode, cutoff=cutoff, resonance=8)
            evaluate(candidate, "shared-filter-refinement")
    for update_hz in (50, 100, 200):
        for wave, pulse in WAVES:
            for pattern in ((4, 6, 7), (4, 4, 6, 4, 4, 7)):
                evaluate({"voices": [{"ratio": 4, "wave": wave, "pulse": pulse, "sustain": 15}],
                          "filter_mode": 0, "arp_hz": update_hz, "arp_pattern": list(pattern)},
                         "single-voice-arpeggio")
    if len(history) + 1 > 200:
        raise ValueError("Probe exceeded its declared render budget")
    # Each winning program is exported as physical register writes for replay.
    for name, result in (("two-voice", best_two), ("one-voice-arpeggio", best_arp)):
        sf.write(args.out / f"{name}-best.wav", result["audio"], RATE, subtype="FLOAT")
        (args.out / f"{name}-frames.json").write_text(json.dumps(result["frames"], separators=(",", ":")) + "\n")
    report = {"scope": "Sample14 assessment across four real note contexts, not a full-song optimization or proof of human recognition",
              "source_single_result": str(args.single_result.resolve()),
              "source_single_sha256": hashlib.sha256(args.single_result.read_bytes()).hexdigest(),
              "renderer": "channel_resid.make_sid: official VICE3.10 reSID, MOS6581, matching installed settings",
              "sample": 14, "note_indices": note_indices, "trigger_periods": periods,
              "training_seconds": len(target) / RATE, "root_cycles_per_sample": ROOT_CYCLES,
              "envelope_template": template, "baseline_scores_remeasured": baseline,
              "baseline_scores_stored": known["best"]["scores"],
              "best_two_voice": best_two["record"], "best_one_voice_arpeggio": best_arp["record"],
              "two_voice_relative_improvement": 1 - best_two["record"]["scores"]["loss"] / baseline["loss"],
              "arpeggio_relative_improvement": 1 - best_arp["record"]["scores"]["loss"] / baseline["loss"],
              "material_improvement_threshold": 0.10,
              "two_voice_cost": "Two of the chip's three oscillators for one MOD track; any shared filter is also a chip-wide resource",
              "native_continuity": "One fresh chip per candidate; no reset between concatenated actual notes",
              "no_host_voice_mixing": True, "no_host_pitch_shifting": True,
              "render_evaluations": len(history) + 1, "elapsed_s": time.perf_counter() - started,
              "history": history,
              "limitations": "Fixed root-ratio grid and inherited ADSR/pitch onset; only sustain balance, waveform, simple shared-filter options and arpeggio rate vary. Fewer or more expressive single-voice programs could change the comparison. No holdout or other MOD channels were fitted."}
    report["two_voice_material_in_this_probe"] = report["two_voice_relative_improvement"] >= 0.10
    (args.out / "probe.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("baseline_scores_remeasured", "best_two_voice", "best_one_voice_arpeggio", "two_voice_relative_improvement", "arpeggio_relative_improvement", "two_voice_material_in_this_probe", "render_evaluations", "elapsed_s")}, indent=2))


if __name__ == "__main__":
    main()
