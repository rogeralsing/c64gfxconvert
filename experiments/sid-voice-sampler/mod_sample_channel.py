"""Compile one bounded 50-Hz MOD sample channel for the existing fast cursor.

The frozen build_mod_channel.py remains the independent accepted reference.
This production seam takes explicit source, ticks, channel and instrument files.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

CLOCK, PERIOD, PAULA = 985248, 126, 3546894.6
RATE = CLOCK / PERIOD


def prepare_sample_channel(mod: dict, ticks: list, channel: int, out: Path,
                           source: dict, start: float, end: float,
                           library: dict) -> dict:
    """Write expected PCM and a five-byte-per-tick score using library banks."""
    if not ticks or any(abs(t["duration_s"] - .02) > 1e-9 for t in ticks):
        raise ValueError("The sampled channel requires nonempty 20-ms source ticks")
    if not 0 <= channel < mod["channels"] or end <= start:
        raise ValueError("Invalid sampled channel or source range")
    if abs(ticks[0]["time_s"] - start) > 1e-7 or abs(
            ticks[-1]["time_s"] + ticks[-1]["duration_s"] - end) > 1e-7:
        raise ValueError("Source range must contain the complete selected ticks")
    if any(abs(b["time_s"] - a["time_s"] - .02) > 1e-7
           for a, b in zip(ticks, ticks[1:])):
        raise ValueError("Selected source ticks are not contiguous")
    states = [tick["channels"][channel] for tick in ticks]
    if not states[0]["trigger"]:
        raise ValueError("The sampled phrase must begin with a real note trigger")
    instruments = sorted({s["playing_sample"] for s in states if s["playing_sample"]})
    volumes, banks, bank_meta = {}, {}, []
    for identifier in instruments:
        sample = mod["samples"][identifier - 1]
        descriptor = library["instruments"][identifier]
        active = [state for state in states if state["playing_sample"] == identifier]
        levels = {state["volume"] for state in active}
        if len(levels) != 1 or sample["loop_length"] > 2 or not sample["length"]:
            raise ValueError("Sampled instruments must be constant-volume nonempty one-shots")
        volume = levels.pop()
        if any(state["period"] <= 0 for state in active):
            raise ValueError("Sampled notes require a positive source period")
        divisor = max(1, math.ceil(PAULA / min(s["period"] for s in active) / RATE * 256 / 255))
        if (descriptor["kind"] != "sample" or descriptor["volume"] != volume
                or descriptor["decimation"] != divisor):
            raise ValueError(f"Instrument {identifier} does not match its source preparation")
        raw = np.frombuffer(sample["data"], dtype=np.int8).astype(np.float64) / 128
        filtered = resample_poly(raw, 1, divisor)
        codes = np.clip(np.rint(128 + filtered * 127 * volume / 64), 0, 255).astype(np.uint8)
        padded = np.pad(codes, (0, (-len(codes)) % 256), constant_values=128)
        data = padded.tobytes()
        digest = hashlib.sha256(data).hexdigest()
        if (data != descriptor["data"] or len(data) != descriptor["bytes"]
                or digest != descriptor["sha256"]):
            raise ValueError(f"Instrument {identifier} differs from its prepared source bank")
        volumes[identifier], banks[identifier] = volume, padded
        bank_meta.append({"id": identifier, "volume": volume, "divisor": divisor,
                          "original_bytes": sample["length"], "resampled_bytes": len(codes),
                          "stored_bytes": len(padded), "sha256": digest})
    by_id = {bank["id"]: bank for bank in bank_meta}
    cuts = (np.arange(len(ticks) + 1, dtype=np.int64) * CLOCK + PERIOD * 25) // (PERIOD * 50)
    counts = np.diff(cuts)
    if not set(map(int, counts)).issubset({156, 157}):
        raise ValueError("Unexpected source-tick to sample-clock mapping")
    score, expected, position, current, pitch_errors = [], [], 0, 0, []
    for index, state in enumerate(states):
        identifier = state["playing_sample"]
        if not identifier or state.get("offset", 0):
            raise ValueError("Unexpected silent instrument or sample offset")
        if state.get("loop_sample", identifier) not in (0, identifier):
            raise ValueError("Independent loop-target changes are unsupported")
        if state["trigger"]:
            current, position = identifier, 0
        if current != identifier or state["volume"] != volumes[identifier]:
            raise ValueError("Source changed instrument or volume without a supported note")
        divisor = by_id[identifier]["divisor"]
        step = round(PAULA / state["period"] / divisor / RATE * 256)
        if not 1 <= step <= 255:
            raise ValueError("Fractional pitch step exceeds the fast cursor range")
        pitch_errors.append(1200 * math.log2(step * RATE * divisor * state["period"] / (256 * PAULA)))
        score.append([step, int(state["trigger"]), identifier, 256 - int(counts[index])])
        # Independent logical cursor model: no page-wrap or silence-page logic.
        indices = (position + np.arange(int(counts[index]), dtype=np.int64) * step) >> 8
        values = np.full(len(indices), 128, dtype=np.uint8)
        valid = indices < len(banks[current])
        values[valid] = banks[current][indices[valid]]
        expected.extend(values)
        position += int(counts[index]) * step
    out.mkdir(parents=True, exist_ok=True)
    expected_data = bytes(expected)
    (out / "expected-input.bin").write_bytes(expected_data)
    lines = [f".label FRAME_COUNT = {len(score)}", '.pc = $2000 "Reusable MOD instruments"']
    for bank in bank_meta:
        identifier = bank["id"]
        path = Path(library["instruments"][identifier]["asm_path"]).resolve()
        lines += [".align $100", f"sample_{identifier}:",
                  f'    .import source "{path}"', f"sample_end_{identifier}:"]
    lines += [".align $100", "silence_page:", "    .fill 256,128", "score:"]
    for step, trigger, identifier, low in score:
        lines.append(f"    .byte {step},{trigger},>sample_{identifier},>sample_end_{identifier},{low}")
    lines += ["program_end:", '.assert "Resident program below I/O", program_end <= $d000, true']
    (out / "data.asm").write_text("\n".join(lines) + "\n")
    duration = len(expected) / RATE
    result = {"source": source, "source_channel": channel + 1,
              "source_range_s": [start, end], "source_duration_s": end - start,
              "duration_s": duration, "duration_error_us": (duration - (end - start)) * 1e6,
              "frames": len(score), "source_ticks_hz": 50, "sample_rate_hz": RATE,
              "sample_period_cycles": PERIOD, "frame_sample_counts": dict(Counter(map(int, counts))),
              "input_codes": len(expected), "triggers": sum(row[1] for row in score),
              "distinct_source_periods": sorted({state["period"] for state in states}),
              "fractional_pitch_error_cents": [min(pitch_errors), max(pitch_errors)],
              "banks": bank_meta, "bank_bytes": sum(bank["stored_bytes"] for bank in bank_meta),
              "score_bytes": len(score) * 5,
              "expected_input_sha256": hashlib.sha256(expected_data).hexdigest(),
              "processing": "Per-instrument polyphase low-pass decimation, constant source MOD volume, unsigned eight-bit quantization and neutral page padding. Reusable ASM banks match the independent source preparation; C64 computes pitch, position and retriggers.",
              "scope": "One declared real MOD channel. Loops, offsets, variable per-instrument volumes and independent loop-target changes are rejected rather than discarded."}
    (out / "input.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result
