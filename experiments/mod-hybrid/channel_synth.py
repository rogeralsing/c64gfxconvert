"""One continuous native-SID voice driven by a complete MOD channel.

Instrument programs can come from the retained GoatTracker examples. Native
chip state is reset once per candidate, never at note boundaries. The emitted
200 Hz register frames are also the input to the standalone C64 exporter.
"""
from __future__ import annotations

import copy
import math
import os

import numpy as np
from pyresidfp._pyresidfp import ChipModel, SID, SamplingMethod

PAL = 985248
PAULA = 3546894.6
FRAME_CYCLES = 4926
CONTROL_HZ = PAL / FRAME_CYCLES


def channel_controls(ticks: list[dict], start: float, end: float, track: int = 1) -> list[dict]:
    ages = []
    age = 0.0
    for tick in ticks:
        state = tick["channels"][track]
        if state["trigger"]:
            age = 0.0
        ages.append(age)
        age += tick["duration_s"]
    controls = []
    for frame in range(round((end - start) * 200)):
        time_s = start + frame / 200
        index = min(len(ticks) - 1, int((time_s + 1e-8) / .02))
        sub = time_s - ticks[index]["time_s"]
        state = ticks[index]["channels"][track]
        controls.append({"sample": state["playing_sample"], "period": state["period"],
                         "volume": state["volume"], "age": ages[index] + max(0, sub),
                         "trigger": bool(state["trigger"] and abs(sub) < 1e-7)})
    return controls


def generic_patch(cycles: float, wave: int = 0x40, pulse: int = 1024,
                  filter_mode: int = 0) -> dict:
    return {"cycles_per_sample": cycles, "attack": 0, "decay": 5,
            "sustain": 10, "release": 4, "gate_s": .25,
            "program": [{"control": wave | 1, "pulse": pulse, "relative_semitones": 0}],
            "program_speed": 1.0, "pulse_scale": 1.0, "pulse_offset": 0.0,
            "filter_mode": filter_mode, "cutoff_start": .65, "cutoff_end": .18,
            "cutoff_tau": .09, "resonance": 3, "pitch_start": 0.0,
            "pitch_tau": .025, "level": 1.0, "filter_tracking": 0.0,
            "name": "generic"}


def example_patch(seed: dict, cycles: float, filter_mode: int = 0) -> dict:
    instrument = seed["instrument"]
    patch = generic_patch(cycles, filter_mode=filter_mode)
    patch.update(instrument["adsr"])
    patch.update(program=copy.deepcopy(instrument["frame_program"]), name=seed["seed_id"],
                 gate_s=.8, program_speed=50 / instrument.get("frame_rate_hz", 50),
                 source_gate_timer=instrument["gate_timer"],
                 source_frame_rate=instrument.get("frame_rate_hz", 50))
    return patch


def compile_frames(controls: list[dict], bank: dict[int, dict]) -> dict:
    frames = []
    previous = {}
    previous_sample = None
    hard_restart_frames = set()
    for index, state in enumerate(controls):
        incoming = bank.get(state["sample"], {})
        if state["trigger"] and incoming.get("source_gate_timer"):
            lead = round(incoming["source_gate_timer"] * 200 / incoming["source_frame_rate"])
            hard_restart_frames.update(range(max(0, index - lead), index))
    for index, state in enumerate(controls):
        sample = state["sample"]
        patch = bank.get(sample)
        trigger = state["trigger"] or index == 0 or sample != previous_sample
        writes = []

        def emit(reg: int, value: int, force: bool = False) -> None:
            value = int(value)
            if force or previous.get(reg) != value:
                writes.append([reg, value])
                previous[reg] = value

        if index == 0:
            for reg in range(25):
                emit(reg, 0, True)
            emit(24, 15, True)
        if not patch or not state["period"] or not sample:
            emit(4, 0)
            frames.append(writes)
            previous_sample = sample
            continue
        age = state["age"]
        if trigger:
            emit(4, previous.get(4, 0) & 0xFE, True)
        program_index = min(len(patch["program"]) - 1,
                            max(0, int(age * 50 / patch["program_speed"])))
        step = patch["program"][program_index]
        control = int(step["control"])
        if age >= patch["gate_s"] or not state["volume"]:
            control &= 0xFE
        hard_restart = index in hard_restart_frames
        if hard_restart:
            control &= 0xFE
        semitones = step.get("relative_semitones", 0) + patch["pitch_start"] * math.exp(-age / patch["pitch_tau"])
        hz = PAULA / state["period"] * patch["cycles_per_sample"] * 2 ** (semitones / 12)
        frequency = min(65535, max(0, round(hz * 2**24 / PAL)))
        pulse = min(4095, max(1, round(step.get("pulse", 1024) * patch["pulse_scale"] + patch["pulse_offset"] * 4095)))
        cutoff = patch["cutoff_end"] + (patch["cutoff_start"] - patch["cutoff_end"]) * math.exp(-age / patch["cutoff_tau"])
        cutoff *= (151 / state["period"]) ** patch.get("filter_tracking", 0)
        cutoff = min(2047, max(0, round(cutoff * 2047)))
        sustain = min(15, max(0, round(patch["sustain"] * state["volume"] / 64 * patch["level"])))
        emit(5, int(patch["attack"]) * 16 + int(patch["decay"]))
        emit(6, 0 if hard_restart else sustain * 16 + int(patch["release"]))
        emit(0, frequency & 255)
        emit(1, frequency >> 8)
        emit(2, pulse & 255)
        emit(3, pulse >> 8)
        if patch["filter_mode"]:
            emit(21, cutoff & 7)
            emit(22, cutoff >> 3)
        emit(23, int(patch["resonance"]) * 16 + int(bool(patch["filter_mode"])))
        emit(24, int(patch["filter_mode"]) | 15)
        emit(4, control, trigger)
        frames.append(writes)
        previous_sample = sample
    return {"frame_cycles": FRAME_CYCLES, "rate_hz": 200,
            "frames": frames, "sample_rate": 11025,
            "duration_s": len(controls) / 200, "model": "6581",
            "renderer_engine": os.environ.get("MOD_CHANNEL_ENGINE", "residfp"),
            "scope": "One continuous SID voice and its filter, no other music channels."}


def render_frames(program: dict, rate: int = 11025) -> np.ndarray:
    engine = os.environ.get("MOD_CHANNEL_ENGINE", "residfp")
    if engine == "resid":
        from channel_resid import make_sid
        chip = make_sid(rate)
    elif engine == "residfp":
        chip = SID(ChipModel.MOS6581, SamplingMethod.RESAMPLE, float(PAL), float(rate))
    else:
        raise ValueError(f"Unknown channel renderer engine {engine}")
    chip.reset()
    # A fresh chip per candidate, with a fixed quiet pre-roll. Never reset
    # between notes: envelope counters, oscillator phase and filter carry on.
    for reg in range(25):
        chip.write(reg, 0)
    chip.clock(round(PAL * .05))
    samples = []
    now = 0
    for frame, writes in enumerate(program["frames"]):
        for offset, (reg, value) in enumerate(writes):
            when = frame * FRAME_CYCLES + offset * 8
            if when > now:
                samples.extend(chip.clock(when - now))
            chip.write(reg, value)
            now = when
    end = len(program["frames"]) * FRAME_CYCLES
    if end > now:
        samples.extend(chip.clock(end - now))
    result = np.asarray(samples, dtype=np.float32) / 32768
    # Integer CIA timing differs from ideal 200Hz by <1ms over20s. Preserve
    # the score duration explicitly, padding only this known clock rounding.
    expected = round(program["duration_s"] * rate)
    return np.pad(result[:expected], (0, max(0, expected - len(result))))


def render(controls: list[dict], bank: dict[int, dict], rate: int = 11025) -> np.ndarray:
    return render_frames(compile_frames(controls, bank), rate)
