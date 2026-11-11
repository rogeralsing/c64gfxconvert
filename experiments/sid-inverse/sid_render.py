"""Render one SID voice from hardware-sized parameters and cycle-timed writes."""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np
from pyresidfp._pyresidfp import ChipModel, SID, SamplingMethod


PAL_CLOCK_HZ = 985248
PRE_ROLL_CYCLES = round(0.05 * PAL_CLOCK_HZ)
WRITE_SPACING_CYCLES = 8
NOTE_START_CYCLE = 10 * WRITE_SPACING_CYCLES
INIT_REGISTERS = tuple((register, 0) for register in range(25)) + ((4, 8), (24, 15))
WAVEFORMS = {"triangle": 0x10, "saw": 0x20, "pulse": 0x40, "noise": 0x80}
FILTER_MODES = {"off": 0, "lowpass": 0x10, "bandpass": 0x20, "highpass": 0x40}
RegisterEvent = tuple[int, int, int]


def initialization_events() -> list[RegisterEvent]:
    """Return setup writes; patch cycle zero follows PRE_ROLL_CYCLES later."""
    return [(index * WRITE_SPACING_CYCLES, register, value)
            for index, (register, value) in enumerate(INIT_REGISTERS)]


def _number(patch: dict, name: str, default: float, low: float, high: float) -> float:
    value = float(patch.get(name, default))
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return min(high, max(low, value))


def _settings(duration_s: float, sample_rate: int, model: str) -> tuple[int, int, str]:
    if not math.isfinite(duration_s) or duration_s <= 0:
        raise ValueError("duration_s must be finite and positive")
    if not isinstance(sample_rate, int) or not 8000 <= sample_rate <= 96000:
        raise ValueError("sample_rate must be an integer in 8000..96000")
    if model not in ("6581", "8580"):
        raise ValueError("model must be '6581' or '8580'")
    return round(duration_s * PAL_CLOCK_HZ), round(duration_s * sample_rate), model


def patch_events(patch: dict, duration_s: float = 0.6, note_hz: float = 110.0,
                 control_hz: int = 200) -> list[RegisterEvent]:
    """Compile a patch to (cycle, SID register offset, byte) tuples.

    Cycles are relative to the first patch write, after initialization/pre-roll.
    Every bus write is at least eight cycles after the previous bus write.
    """
    total_cycles, _, _ = _settings(duration_s, 22050, "6581")
    if not math.isfinite(note_hz) or note_hz <= 0:
        raise ValueError("note_hz must be finite and positive")
    if not isinstance(control_hz, int) or not 1 <= control_hz <= 5000:
        raise ValueError("control_hz must be an integer in 1..5000")
    waveform = WAVEFORMS[patch.get("waveform", "triangle")]
    filter_mode = FILTER_MODES[patch.get("filter_mode", "off")]
    attack = round(_number(patch, "attack", 0, 0, 15))
    decay = round(_number(patch, "decay", 6, 0, 15))
    sustain = round(_number(patch, "sustain", 0, 0, 15))
    release = round(_number(patch, "release", 3, 0, 15))
    resonance = round(_number(patch, "resonance", 0, 0, 15))
    gate_s = _number(patch, "gate_s", 0.18, 0, duration_s)
    noise_s = _number(patch, "attack_noise_s", 0, 0, duration_s)
    pitch_start = _number(patch, "pitch_start_semitones", 0, -96, 96)
    pitch_end = _number(patch, "pitch_end_semitones", 0, -96, 96)
    pitch_tau = _number(patch, "pitch_tau_s", 0.04, 0, 60)
    pulse_start = _number(patch, "pulse_start", 0.5, 0, 1)
    pulse_end = _number(patch, "pulse_end", 0.5, 0, 1)
    cutoff_start = _number(patch, "cutoff_start", 0.8, 0, 1)
    cutoff_end = _number(patch, "cutoff_end", 0.2, 0, 1)
    filter_tau = _number(patch, "filter_tau_s", 0.08, 0, 60)

    def values(t: float) -> list[tuple[int, int]]:
        pitch = pitch_end + (pitch_start - pitch_end) * math.exp(-t / pitch_tau) if pitch_tau else pitch_end
        hz = note_hz * 2 ** (pitch / 12)
        frequency = min(65535, max(0, round(hz * 2 ** 24 / PAL_CLOCK_HZ)))
        progress = min(1.0, t / gate_s) if gate_s else 1.0
        pulse = round(4095 * (pulse_start + (pulse_end - pulse_start) * progress))
        cutoff = cutoff_end + (cutoff_start - cutoff_end) * math.exp(-t / filter_tau) if filter_tau else cutoff_end
        cutoff_value = round(2047 * cutoff)
        return [(0, frequency & 255), (1, frequency >> 8),
                (2, pulse & 255), (3, pulse >> 8),
                (21, cutoff_value & 7), (22, cutoff_value >> 3)]

    def control(t: float) -> int:
        return (0x80 if t < noise_s else waveform) | int(t < gate_s)

    initial = [(5, attack << 4 | decay), (6, sustain << 4 | release)] + values(0)
    initial += [(23, resonance << 4 | int(filter_mode != 0)), (24, filter_mode | 15), (4, control(0))]
    events: list[RegisterEvent] = []
    previous: dict[int, int] = {}

    def emit(cycle: int, register: int, value: int, force: bool = False) -> None:
        if not force and previous.get(register) == value:
            return
        if events:
            cycle = max(cycle, events[-1][0] + WRITE_SPACING_CYCLES)
        if cycle < total_cycles:
            events.append((cycle, register, value))
            previous[register] = value

    for index, (register, value) in enumerate(initial):
        emit(index * WRITE_SPACING_CYCLES, register, value, force=True)
    update_cycles = {round(index * PAL_CLOCK_HZ / control_hz)
                     for index in range(1, math.ceil(duration_s * control_hz))}
    update_cycles.update((round(gate_s * PAL_CLOCK_HZ), round(noise_s * PAL_CLOCK_HZ)))
    for relative_cycle in sorted(update_cycles):
        if relative_cycle <= 0:
            continue
        cycle = NOTE_START_CYCLE + relative_cycle
        t = relative_cycle / PAL_CLOCK_HZ
        # Exact transition cycles take priority over ordinary parameter updates.
        # Comparing integer cycles avoids reopening the gate through rounding.
        control_value = (0x80 if relative_cycle < round(noise_s * PAL_CLOCK_HZ) else waveform)
        control_value |= int(relative_cycle < round(gate_s * PAL_CLOCK_HZ))
        emit(cycle, 4, control_value)
        for register, value in values(t):
            emit(cycle, register, value)
    return events


def _chip(sample_rate: int, model: str) -> SID:
    chip_model = ChipModel.MOS6581 if model == "6581" else ChipModel.MOS8580
    return SID(chip_model, SamplingMethod.RESAMPLE, float(PAL_CLOCK_HZ), float(sample_rate))


def _run_events(sid: SID, events: Iterable[RegisterEvent], until: int) -> list[int]:
    samples: list[int] = []
    current = 0
    for cycle, register, value in events:
        if not isinstance(cycle, int) or cycle < current or cycle >= until:
            raise ValueError("Event cycles must be ordered integers in 0..until-1")
        if not 0 <= register <= 24 or not 0 <= value <= 255:
            raise ValueError("SID event register or value outside writable range")
        if cycle > current:
            samples.extend(sid.clock(cycle - current))
        sid.write(register, value)
        current = cycle
    if until > current:
        samples.extend(sid.clock(until - current))
    return samples


def render_events(events: Iterable[RegisterEvent], duration_s: float = 0.6,
                  sample_rate: int = 22050, model: str = "6581") -> np.ndarray:
    """Render a patch event trace after fixed reset/pre-roll; return float64 mono.

    A fresh native SID isolates each evaluation from preceding patches. Native
    reset alone preserves oscillator, envelope and analog filter state.
    """
    total_cycles, sample_count, model = _settings(duration_s, sample_rate, model)
    sid = _chip(sample_rate, model)
    sid.reset()
    _run_events(sid, initialization_events(), PRE_ROLL_CYCLES)
    samples = np.asarray(_run_events(sid, events, total_cycles), dtype=np.float64) / 32768.0
    # Cycle-to-sample rounding can leave one fewer sample after the pre-roll.
    if len(samples) < sample_count:
        samples = np.pad(samples, (0, sample_count - len(samples)), mode="edge" if len(samples) else "constant")
    return samples[:sample_count]


def render_patch(patch: dict, duration_s: float = 0.6, sample_rate: int = 22050,
                 model: str = "6581", note_hz: float = 110.0,
                 control_hz: int = 200) -> np.ndarray:
    """Return emulated audio without per-patch gain or DC normalization."""
    return render_events(patch_events(patch, duration_s, note_hz, control_hz),
                         duration_s, sample_rate, model)
