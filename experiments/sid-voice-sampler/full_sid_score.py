"""Compile full-song SID replacements, including chords and loop-target changes."""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path

import numpy as np

import build_mod_hybrid as hybrid
from mod_sample_channel import CLOCK, PAULA

HERE = Path(__file__).resolve().parent
LIBRARY = HERE / "instruments/hyperbased-full-sid"


class SourceCursor:
    """Original DMA lifetime used only for host-side gating and recipe selection."""
    def __init__(self, mod: dict):
        self.mod = mod
        self.raw = {s["id"]: np.frombuffer(s["data"], np.int8).astype(float) / 128
                    for s in mod["samples"] if s["length"]}
        self.current = self.target = 0
        self.position = self.end = 0.0
        self.ended = True

    def tick(self, state: dict, duration: float) -> tuple[int, np.ndarray]:
        target = state.get("loop_sample", state["playing_sample"])
        changed = target != self.target
        self.target = target
        if state["trigger"]:
            self.current = state["playing_sample"]
            sample = self.mod["samples"][self.current - 1]
            self.position = float(state.get("offset", 0))
            self.end = float(state.get("first_segment_bytes", (
                sample["loop_start"] + sample["loop_length"]
                if sample["loop_start"] and sample["loop_length"] > 2 else sample["length"])))
            self.ended = False
        elif self.ended and changed and target and self.mod["samples"][target - 1]["loop_length"] > 2:
            self._loop()
        if not state["period"] or not self.current:
            return 0, np.zeros(1)
        remaining = PAULA / state["period"] * duration
        chunks, weights = [], Counter()
        while remaining > 1e-8:
            if self.ended:
                chunks.append(np.zeros(max(1, round(remaining))))
                break
            if self.position >= self.end - 1e-8:
                self._loop()
                continue
            count = min(remaining, self.end - self.position)
            indices = (self.position + np.arange(max(1, math.ceil(count)))).astype(np.int64)
            indices = indices[indices < self.end]
            data = self.raw[self.current]
            block = np.zeros(len(indices)); valid = indices < len(data)
            block[valid] = data[indices[valid]]
            chunks.append(block); weights[self.current] += count
            self.position += count; remaining -= count
        effective = weights.most_common(1)[0][0] if weights else self.current
        return effective, np.concatenate(chunks) if chunks else np.zeros(1)

    def _loop(self) -> None:
        if self.target and self.mod["samples"][self.target - 1]["loop_length"] > 2:
            self.current = self.target
            sample = self.mod["samples"][self.current - 1]
            self.position = float(sample["loop_start"])
            self.end = float(sample["loop_start"] + sample["loop_length"])
            self.ended = False
        else:
            self.ended = True


def prepare_full_sid(mod: dict, ticks: list, out: Path, *, library_dir: Path = LIBRARY,
                     channels: tuple[int, int] = (1, 0),
                     separate_percussion_hits: bool = False) -> dict:
    if len(channels) != 2 or len(set(channels)) != 2 or any(c not in range(4) for c in channels):
        raise ValueError("Two distinct source channels are required for the SID voices")
    document = json.loads((library_dir / "library.json").read_text())
    if document["source"]["sha256"] != mod["sha256"]:
        raise ValueError("SID library belongs to a different MOD")
    presets, files = {}, [library_dir / "library.json"]
    for name in document["instruments"]:
        path = library_dir / name; files.append(path)
        item = json.loads(path.read_text()); presets[item["source_instrument"]] = item
    pitches = {}
    for identifier, preset in presets.items():
        if preset["program"] in {"triangle", "pulse"}:
            pitches[identifier] = hybrid.melody_pitch(mod, preset)
            # Physical pulse widths belong to the two voice settings, since
            # a source instrument can appear on both voices in this song.
            pitches[identifier].pop("pulse_width", None)
        elif preset["program"] == "arpeggio":
            pitches[identifier] = {"source_period_samples": preset["source_period_samples"],
                                   "method": "Measured spectral fundamental; equal-temperament chord arpeggio",
                                   "semitones": preset["semitones"]}
    peaks = {}
    for sample in mod["samples"]:
        if sample["id"] in presets:
            raw = np.frombuffer(sample["data"], np.int8).astype(float) / 128
            peaks[sample["id"]] = max(float(np.sqrt(np.mean(raw[j:j + 256] ** 2)))
                                      for j in range(0, len(raw), 128))
    voices, details = [], []
    for channel in channels:
        cursor = SourceCursor(mod)
        rows, active, used = [], Counter(), Counter()
        onset, trigger_index, transitions, previous = 0.0, 0, 0, 0
        for index, tick in enumerate(ticks):
            state = tick["channels"][channel]
            if state["trigger"]:
                onset, trigger_index = tick["time_s"], index
            effective, block = cursor.tick(state, tick["duration_s"])
            control, frequency = 0x19, 0.0
            if state["volume"] > 0 and effective:
                if effective not in presets:
                    raise ValueError(f"Missing SID recipe for instrument {effective}")
                preset = presets[effective]; program = preset["program"]
                used[effective] += 1
                rms = float(np.sqrt(np.mean(block * block)))
                audible = rms > peaks[effective] * preset["rms_gate_ratio"]
                age = tick["time_s"] - onset
                if program in {"noise", "triangle-sweep", "noise-then-triangle-sweep"}:
                    if separate_percussion_hits and state["trigger"]:
                        audible = True
                    audible = audible and age < preset["duration_s"] - 1e-8
                if audible:
                    rate = PAULA / state["period"]
                    if program in {"triangle", "pulse", "arpeggio"}:
                        frequency = rate / pitches[effective]["source_period_samples"]
                        if program == "arpeggio":
                            chord = preset["semitones"]
                            semitone = chord[((index - trigger_index) // preset["ticks_per_step"]) % len(chord)]
                            frequency *= 2 ** (semitone / 12)
                        control = preset["control"]
                    elif program == "noise" or (program == "noise-then-triangle-sweep"
                                                  and age < preset["noise_duration_s"] - 1e-8):
                        frequency, control = rate / preset["noise_divisor"], preset["noise_control"]
                    elif program in {"triangle-sweep", "noise-then-triangle-sweep"}:
                        body = preset["base_hz"] * preset["reference_period"] / state["period"]
                        frequency = body * (1 + preset["sweep_depth"] * math.exp(-age / preset["sweep_decay_s"]))
                        control = preset["triangle_control"]
                    else:
                        raise ValueError(f"Unsupported SID program {program}")
                    active[effective] += 1
            word = round(frequency * 2**24 / CLOCK)
            if not 0 <= word <= 65535:
                raise ValueError("Compiled frequency exceeds SID range")
            rows.append([word & 255, word >> 8, control])
            if effective != previous:
                transitions += 1; previous = effective
        if separate_percussion_hits:
            percussion = {identifier for identifier, preset in presets.items()
                          if preset["program"] in {"noise", "triangle-sweep", "noise-then-triangle-sweep"}}
            for index in range(1, len(rows)):
                now, before = ticks[index]["channels"][channel], ticks[index - 1]["channels"][channel]
                if (now["trigger"] and not before["trigger"]
                        and now["playing_sample"] in percussion
                        and before["playing_sample"] in percussion):
                    rows[index - 1] = [0, 0, 0x19]
        voices.append(rows)
        details.append({"source_channel": channel + 1, "source_triggers": sum(t["channels"][channel]["trigger"] for t in ticks),
                        "source_loop_target_change_ticks": sum("loop_sample" in t["channels"][channel] for t in ticks),
                        "effective_instrument_transitions": transitions, "used_ticks": dict(used),
                        "active_ticks": dict(active), "unique_states": len({tuple(r) for r in rows})})
    result = {"rows": [a + b for a, b in zip(*voices)], "voices": details,
              "voice_levels": document["voice_levels"], "voice_pulse_widths": document["voice_pulse_widths"],
              "pitch_analysis": pitches,
              "source_sha256": {str(path.relative_to(HERE)): hybrid.base.reference.digest(path) for path in files},
              "scope": document["scope"]}
    out.mkdir(parents=True, exist_ok=True)
    hybrid.base.save(out / "full-synth.json", result)
    return result
