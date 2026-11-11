"""Prepare a complete four-channel sample-only C64 rendition of the MOD.

Each original instrument is retained as a short reusable sample. Adaptive
downsampling keeps the 8-bit fractional playback step below one bank sample
per DAC update. All four original note/effect tracks remain independent.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from mod_reader import load_mod
from timeline import build_timeline

HERE = Path(__file__).resolve().parent
PAL_CLOCK = 985248
PCM_RATE = PAL_CLOCK / 256
PAULA_CLOCK = 3546894.6


def prepare(source: Path, out: Path, seconds: float | None = None, bank_scope: str = "song",
            protracker_loops: bool = False) -> dict:
    if bank_scope not in ("song", "score"):
        raise ValueError("bank_scope must be song or score")
    mod = load_mod(source)
    timeline = build_timeline(mod)
    all_ticks = timeline["ticks"]
    ticks = all_ticks if seconds is None else [t for t in all_ticks if t["time_s"] < seconds - 1e-8]
    if not ticks:
        raise ValueError("Empty score")
    out.mkdir(parents=True, exist_ok=True)
    bank_dir = out / "source-bank"
    bank_dir.mkdir(exist_ok=True)
    # Derive divisors from the entire song even when preparing a preview.
    # The same instrument has the same waveform and tuning in both builds.
    # The optional score scope instead optimizes only the selected score.
    # Its bank must be prepared again before playing notes outside that score.
    divisor_ticks = all_ticks if bank_scope == "song" else ticks
    divisors = {}
    for instrument in range(1, 32):
        periods = [state["period"] for tick in divisor_ticks for state in tick["channels"]
                   if (state["playing_sample"] == instrument or
                       protracker_loops and state.get("loop_sample") == instrument)
                   and state["period"] > 0]
        if periods:
            divisor = max(1, math.ceil(PAULA_CLOCK / min(periods) / PCM_RATE * 256 / 255))
            divisors[instrument] = divisor
    if protracker_loops:
        # A Paula loop pointer can change instrument without restarting its
        # current DMA segment. Those linked banks must share a divisor because
        # the C64 fractional step continues unchanged across the transition.
        parent = {instrument: instrument for instrument in divisors}
        def component(instrument):
            while parent[instrument] != instrument:
                parent[instrument] = parent[parent[instrument]]
                instrument = parent[instrument]
            return instrument
        for tick in divisor_ticks:
            for state in tick["channels"]:
                current, target = state["playing_sample"], state.get("loop_sample", 0)
                if current in parent and target in parent and mod["samples"][target - 1]["loop_length"] > 2:
                    parent[component(target)] = component(current)
        maxima = {}
        for instrument, divisor in divisors.items():
            group = component(instrument)
            maxima[group] = max(maxima.get(group, 1), divisor)
        divisors = {instrument: maxima[component(instrument)] for instrument in divisors}
    used = sorted({s["playing_sample"] for t in ticks for s in t["channels"] if s["playing_sample"]}
                  | {s["loop_sample"] for t in ticks for s in t["channels"]
                     if protracker_loops and s.get("loop_sample") and
                     mod["samples"][s["loop_sample"] - 1]["loop_length"] > 2})
    bank = []
    for instrument in used:
        sample = mod["samples"][instrument - 1]
        divisor = divisors[instrument]
        raw = np.frombuffer(sample["data"], dtype=np.int8).astype(np.float64) / 128
        loop_copies = 1
        exact_short_loop = bank_scope == "score" and 2 < sample["loop_length"] < 256
        if exact_short_loop:
            # Keep the original repeating period exact after integer decimation.
            # One source loop need not contain an integer number of bank samples.
            loop_copies = divisor // math.gcd(sample["loop_length"], divisor)
            start, length = sample["loop_start"], sample["loop_length"]
            raw = np.r_[raw[:start], np.tile(raw[start:start + length], loop_copies)]
        filtered = resample_poly(raw, 1, divisor)
        values = np.clip(np.rint(filtered * 7.5 + 8), 0, 15).astype(np.uint8)
        loop_start = round(sample["loop_start"] / divisor)
        loop_length = round(sample["loop_length"] / divisor) if sample["loop_length"] > 2 else 0
        if exact_short_loop:
            loop_length = sample["loop_length"] * loop_copies // divisor
        if loop_length:
            loop_length = min(loop_length, len(values) - loop_start)
        path = bank_dir / f"sample-{instrument:02d}.bin"
        path.write_bytes(values.tobytes())
        bank.append({"id": instrument, "data_file": str(path.resolve()), "bytes": len(values),
                     "loop_start": loop_start, "loop_length": loop_length,
                     "base_divisor": divisor, "original_bytes": sample["length"],
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "processing": "Common gain1, polyphase downsampling, unsigned4-bit values stored one per byte"})
        if bank_scope == "score":
            bank[-1]["source_loop_copies_before_resampling"] = loop_copies
    arranged = []
    maximum_step = 0
    by_id = {entry["id"]: entry for entry in bank}
    segment_aliases = {}
    variable_ticks = any(abs(tick["duration_s"] - 0.02) > 1e-8 for tick in ticks)
    for tick in ticks:
        pcm = []
        for state in tick["channels"]:
            instrument, period = state["playing_sample"], state["period"]
            step = round(PAULA_CLOCK / period / divisors[instrument] / PCM_RATE * 256) if period and instrument else 0
            if not 0 <= step <= 255:
                raise ValueError(f"Sample {instrument} exceeds fractional-cursor range: {step}")
            maximum_step = max(maximum_step, step)
            voice = {"sample": instrument, "step": step, "volume": state["volume"],
                     "trigger": state["trigger"]}
            if protracker_loops and "loop_sample" in state:
                target = state["loop_sample"]
                voice["loop_sample"] = target if target and mod["samples"][target - 1]["loop_length"] > 2 else 0
            if instrument and state["trigger"] and state.get("offset", 0):
                entry = by_id[instrument]
                # Keep the fractional part of the source offset after bank
                # resampling. A 9xx start must not allocate a duplicate sample.
                divisor = divisors[instrument]
                phase = (int(state["offset"]) * 256 + divisor // 2) // divisor
                end = (entry["loop_start"] + entry["loop_length"]
                       if entry["loop_length"] else entry["bytes"])
                phase = min(phase, end * 256)
                voice["offset"], voice["offset_fraction"] = phase >> 8, phase & 255
            if instrument and state["trigger"] and "first_segment_bytes" in state:
                # ProTracker's out-of-range 9xx rule can play a two-byte
                # initial DMA segment before returning to the normal loop.
                # Share that loop with a tiny prefix descriptor instead of
                # cloning an entire instrument for every offset.
                source_offset = int(state.get("offset", 0))
                segment_bytes = int(state["first_segment_bytes"])
                if segment_bytes <= 0:
                    raise ValueError("Initial sample segment must contain bytes")
                key = (instrument, source_offset, segment_bytes)
                if key not in segment_aliases:
                    alias_id = max(by_id) + 1
                    if alias_id > 255:
                        raise ValueError("Sample segment aliases exceed the PCM ID range")
                    original_entry = by_id[instrument]
                    divisor = divisors[instrument]
                    data = Path(original_entry["data_file"]).read_bytes()
                    start = min(source_offset // divisor, len(data) - 1)
                    end = max(start + 1, min(math.ceil((source_offset + segment_bytes) / divisor), len(data)))
                    prefix = data[start:end]
                    alias_path = bank_dir / f"sample-{alias_id:02d}.bin"
                    alias_path.write_bytes(prefix)
                    alias = {"id": alias_id, "data_file": str(alias_path.resolve()), "bytes": len(prefix),
                             "loop_start": 0, "loop_length": 0, "base_divisor": divisor,
                             "original_bytes": segment_bytes, "original_instrument": instrument,
                             "first_segment_source_offset": source_offset,
                             "sha256": hashlib.sha256(prefix).hexdigest(),
                             "processing": "Tiny initial DMA prefix; normal instrument loop remains shared"}
                    if original_entry["loop_length"]:
                        alias["loop_target_id"] = instrument
                    bank.append(alias)
                    by_id[alias_id] = alias
                    segment_aliases[key] = alias_id
                voice["sample"] = segment_aliases[key]
                voice["offset"] = 0
                voice["offset_fraction"] = ((source_offset * 256 + divisors[instrument] // 2)
                                            // divisors[instrument]) & 255
            pcm.append(voice)
        record = {key: tick[key] for key in ("time_s", "duration_s", "order", "pattern", "row", "tick")} | {"pcm": pcm}
        if variable_ticks and "bpm" in tick:
            record["bpm"] = tick["bpm"]
        arranged.append(record)
    duration = (float(sum((Fraction(5, 2 * int(tick["bpm"])) if "bpm" in tick
                           else Fraction(str(tick["duration_s"]))) for tick in arranged))
                if variable_ticks else len(arranged) / 50)
    result = {"title": f"{mod['title']}: four original PCM tracks", "source": str(source.resolve()),
              "source_sha256": mod["sha256"], "duration_s": duration,
              "pal_clock_hz": PAL_CLOCK, "pcm_rate_hz": PCM_RATE,
              "pcm_bank": bank, "ticks": arranged,
              "mapping": "Original MOD tracks1..4 map directly to independent PCM cursors1..4",
              "mixing": {"mode": "nearest",
                         "lookup": "32+round((nibble-8)*quantized_volume/4)",
                         "quantization": "Sum four fine-grained contributions, then round once to the nearest DAC code; ties to even. No residual feedback.",
                         "initial_dac": 8, "initial_residual": 0},
              "scope": "PAL sample-only resident playback, MOS8580 + digiboost in VICE; no SID oscillator approximation and no full-song audio recording stored in RAM."}
    if bank_scope == "score":
        result["sample_bank_strategy"] = "Selected-score highest pitch only; bank and fractional steps must be prepared again for a different score"
        result["bank_scope"] = bank_scope
    path = out / "arrangement.json"
    path.write_text(json.dumps(result, separators=(",", ":")) + "\n")
    summary = {"arrangement": str(path.resolve()), "arrangement_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
               "duration_s": duration, "ticks": len(arranged), "channels": 4,
               "sample_ids": used, "divisors": {str(i): divisors[i] for i in used},
               "sample_bank_bytes_before_loop_expansion": sum(s["bytes"] for s in bank),
               "maximum_step": maximum_step,
               "triggers_per_track": [sum(t["pcm"][i]["trigger"] for t in arranged) for i in range(4)],
               "effects_handled": timeline["effects_handled"],
               "source_sha256": mod["sha256"]}
    if bank_scope == "score":
        summary["bank_scope"] = bank_scope
    (out / "prepare.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=HERE / "sources/stardust-memories.mod")
    parser.add_argument("--out", type=Path, default=HERE / "results/pcm4-clean")
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--bank-scope", choices=("song", "score"), default="song",
                        help="Derive sample-bank divisors from the whole song (default) or only the selected score; score banks must be rebuilt for a different score")
    args = parser.parse_args()
    if args.seconds is not None and args.seconds <= 0:
        parser.error("seconds must be positive")
    print(json.dumps(prepare(args.source, args.out, args.seconds, args.bank_scope), indent=2))


if __name__ == "__main__":
    main()
