"""Prepare bounded reusable eight-bit banks for the accepted SID-voice player.

The runtime remains unchanged. A bank may include a finite repetition of its
original source loop, sufficient for every selected note; pitch and cursor
advance remain native C64 work. Audible gain changes during a held note and
independent loop-target changes are rejected rather than silently discarded.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

CLOCK, PERIOD, PAULA = 985248, 126, 3546894.6
RATE = CLOCK / PERIOD


def frame_ticks(ticks: list[dict]) -> tuple[list[dict], list[int]]:
    """Split long tracker ticks into held buffers of at most 256 DAC values."""
    frames, counts = [], []
    cumulative, previous = Fraction(0), 0
    for tick in ticks:
        duration = Fraction(str(tick["duration_s"])).limit_denominator(1000000)
        if duration <= 0 or abs(float(duration) - tick["duration_s"]) > 1e-8:
            raise ValueError("Source tick duration and BPM disagree")
        cumulative += duration * Fraction(CLOCK, PERIOD)
        cut = (2 * cumulative.numerator + cumulative.denominator) // (2 * cumulative.denominator)
        samples = cut - previous
        previous = cut
        if samples < 32:
            raise ValueError("Source tick is too short for this verified buffer renderer")
        pieces = math.ceil(samples / 256)
        for index in range(pieces):
            count = samples * (index + 1) // pieces - samples * index // pieces
            frame = dict(tick)
            frame["channels"] = [dict(state) for state in tick["channels"]]
            if index:
                for state in frame["channels"]:
                    state["trigger"] = False
                    state.pop("offset", None)
                    state.pop("first_segment_bytes", None)
            frame["duration_s"] = count / RATE
            frame["time_s"] = tick["time_s"] + (samples * index // pieces) / RATE
            frame["source_tick_time_s"] = tick["time_s"]
            frames.append(frame); counts.append(count)
    return frames, counts


def prepare(mod: dict, ticks: list[dict], channel: int, out: Path) -> dict:
    if not ticks or not 0 <= channel < 4:
        raise ValueError("Select a nonempty source passage and one PCM channel")
    frames, counts = frame_ticks(ticks)
    states = [frame["channels"][channel] for frame in frames]
    if not states[0]["trigger"] or not states[0]["playing_sample"]:
        raise ValueError("The PCM passage must start at a real source note trigger")
    identifiers = sorted({state["playing_sample"] for state in states})
    if 0 in identifiers:
        raise ValueError("A selected PCM instrument became zero after playback started")
    divisors = {}
    for identifier in identifiers:
        active = [state for state in states if state["playing_sample"] == identifier]
        if any(state["period"] <= 0 for state in active):
            raise ValueError("A sampled source note has no positive period")
        divisors[identifier] = max(1, math.ceil(
            PAULA / min(state["period"] for state in active) / RATE * 256 / 255))
    neutral_loop_updates = 0
    for state in states:
        identifier = state["playing_sample"]
        target = state.get("loop_sample", identifier)
        if target not in (0, identifier):
            original, replacement = mod["samples"][identifier - 1], mod["samples"][target - 1]
            if (original["loop_length"] > 2 or replacement["loop_length"] > 2
                    or replacement["loop_start"] != 0 or replacement["data"][:2] != bytes(2)):
                raise ValueError("Independent loop-target changes need a different PCM passage")
            neutral_loop_updates += 1
        if "first_segment_bytes" in state:
            raise ValueError("A short first-DMA segment needs a different PCM passage")

    starts = [index for index, state in enumerate(states) if state["trigger"]]
    notes, definitions, ignored_tail_updates = [], {}, 0
    pitch_errors = []
    for start, stop in zip(starts, starts[1:] + [len(states)]):
        first = states[start]
        identifier, gain = first["playing_sample"], first["volume"]
        source = mod["samples"][identifier - 1]
        if not source["length"]:
            raise ValueError("A selected PCM instrument is empty")
        divisor = divisors[identifier]
        offset = int(first.get("offset", 0))
        if not 0 <= offset < source["length"]:
            raise ValueError("Sample offset lies outside the original instrument")
        looped = source["loop_length"] > 2
        if looped and offset >= (source["loop_start"] + source["loop_length"]
                                  if source["loop_start"] else source["length"]):
            raise ValueError("Offset is beyond the initial DMA segment")
        key = (identifier, gain, offset)
        position, steps, maximum = 0, [], 0
        signal_end = math.ceil((source["length"] - offset) / divisor)
        for frame_index in range(start, stop):
            state, count = states[frame_index], counts[frame_index]
            if state["playing_sample"] != identifier:
                raise ValueError("A source instrument changed without a trigger")
            if state["volume"] != gain:
                if looped or position >> 8 < signal_end:
                    raise ValueError("Audible gain changed during a held PCM note")
                ignored_tail_updates += 1
            step = round(PAULA / state["period"] / divisor / RATE * 256)
            if not 1 <= step <= 255:
                raise ValueError("Source pitch exceeds the fractional cursor")
            pitch_errors.append(1200 * math.log2(
                step * RATE * divisor * state["period"] / (256 * PAULA)))
            maximum = max(maximum, (position + (count - 1) * step) >> 8)
            steps.append(step); position += count * step
        definition = definitions.setdefault(key, {"maximum_read": -1})
        definition["maximum_read"] = max(definition["maximum_read"], maximum)
        notes.append({"start": start, "stop": stop, "key": key, "steps": steps})

    out.mkdir(parents=True, exist_ok=True)
    library = out / "instruments"; library.mkdir(exist_ok=True)
    banks = {}
    for bank_index, (key, definition) in enumerate(sorted(definitions.items())):
        identifier, gain, offset = key
        sample, divisor = mod["samples"][identifier - 1], divisors[identifier]
        raw = np.frombuffer(sample["data"], np.int8).astype(np.float64) / 128
        needed = definition["maximum_read"] + 1
        if sample["loop_length"] > 2:
            start, length = sample["loop_start"], sample["loop_length"]
            first_end = start + length if start else len(raw)
            attack = raw[offset:first_end]
            loop = raw[start:start + length]
            extra = max(0, (needed + 32) * divisor - len(attack))
            wave = np.r_[attack, np.tile(loop, math.ceil(extra / length))]
            loop_copies = math.ceil(extra / length)
        else:
            wave, loop_copies = raw[offset:], 0
        # A sliced offset bank retains the source's preceding filter context.
        # At source zero, ordinary zero padding reproduces the accepted bank.
        guard = 32 * divisor
        if offset:
            before = raw[max(0, offset - guard):offset]
            before = np.pad(before, (guard - len(before), 0))
            filtered = resample_poly(np.r_[before, wave], 1, divisor)[32:]
        else:
            filtered = resample_poly(wave, 1, divisor)
        codes = np.clip(np.rint(128 + filtered * 127 * gain / 64), 0, 255).astype(np.uint8)
        valid = len(codes)
        stored = min(len(codes), needed) if not loop_copies else needed
        stored = max(256, (stored + 255) // 256 * 256)
        values = np.full(stored, 128, np.uint8)
        prefix = min(stored, valid); values[:prefix] = codes[:prefix]
        name = f"{identifier:02d}-gain-{gain:02d}-offset-{offset:05d}"
        binary = values.tobytes()
        (library / f"{name}.bin").write_bytes(binary)
        (library / f"{name}.asm").write_text(
            "// Reusable unsigned eight-bit instrument bank; player supplies labels and page alignment.\n"
            + "\n".join(".byte " + ",".join(f"${value:02x}" for value in binary[i:i + 16])
                        for i in range(0, len(binary), 16)) + "\n")
        metadata = {"id": bank_index, "source_instrument": identifier, "source_gain": gain,
                    "source_offset": offset, "divisor": divisor, "bytes": stored,
                    "original_bytes": sample["length"], "source_loop_start": sample["loop_start"],
                    "source_loop_length": sample["loop_length"], "unrolled_loop_copies": loop_copies,
                    "maximum_read_index": definition["maximum_read"],
                    "sha256": hashlib.sha256(binary).hexdigest(),
                    "processing": "Unsigned eight-bit reusable instrument bank; source gain, polyphase decimation, bounded original loop repeats and neutral page padding. Pitch and position remain C64 work."}
        (library / f"{name}.json").write_text(json.dumps(metadata, indent=2) + "\n")
        banks[key] = dict(metadata, data=values, label=f"audition_bank_{bank_index}",
                          path=(library / f"{name}.bin").resolve())
    expected, score = bytearray(), []
    for note in notes:
        bank, position = banks[note["key"]], 0
        for frame_index, step in zip(range(note["start"], note["stop"]), note["steps"]):
            count = counts[frame_index]
            indices = (position + np.arange(count, dtype=np.int64) * step) >> 8
            values = np.full(count, 128, np.uint8)
            valid = indices < len(bank["data"])
            values[valid] = bank["data"][indices[valid]]
            expected.extend(values.tobytes()); position += count * step
            score.append({"step": step, "trigger": int(frame_index == note["start"]),
                          "bank": bank["id"], "start_low": (256 - count) & 255})
    (out / "expected-input.bin").write_bytes(expected)
    metadata = {"frames": len(frames), "source_channel": channel + 1,
                "source_range_s": [ticks[0]["time_s"], ticks[-1]["time_s"] + ticks[-1]["duration_s"]],
                "duration_s": len(expected) / RATE, "input_codes": len(expected),
                "sample_rate_hz": RATE, "sample_period_cycles": PERIOD,
                "frame_sample_counts_exact": counts,
                "frame_sample_counts": dict(Counter(counts)),
                "triggers": len(notes), "bank_bytes": sum(bank["bytes"] for bank in banks.values()),
                "fractional_pitch_error_cents": [min(pitch_errors), max(pitch_errors)],
                "inaudible_ended_volume_updates": ignored_tail_updates,
                "neutral_two_byte_loop_updates": neutral_loop_updates,
                "expected_input_sha256": hashlib.sha256(expected).hexdigest(),
                "banks": [{k: v for k, v in bank.items() if k not in {"data", "path", "label"}}
                          for bank in banks.values()],
                "scope": "One original source channel over a declared passage. No audible gain changes, independent loop changes or short DMA segments discarded. Bounded loop materialization stores reusable waveforms, not a recording of the passage."}
    (out / "input.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return {"metadata": metadata, "banks": list(banks.values()), "score": score,
            "frames": frames, "counts": counts}
