"""Prepare a complete four-channel sample-only C64 rendition of the MOD.

Each original instrument is retained as a short reusable sample. Adaptive
downsampling keeps the 8-bit fractional playback step below one bank sample
per DAC update. All four original note/effect tracks remain independent.
"""
from __future__ import annotations

import argparse
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


def prepare(source: Path, out: Path, seconds: float | None = None, bank_scope: str = "song") -> dict:
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
                   if state["playing_sample"] == instrument and state["period"] > 0]
        if periods:
            divisor = max(1, math.ceil(PAULA_CLOCK / min(periods) / PCM_RATE * 256 / 255))
            divisors[instrument] = divisor
    used = sorted({s["playing_sample"] for t in ticks for s in t["channels"] if s["playing_sample"]})
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
    for tick in ticks:
        pcm = []
        for state in tick["channels"]:
            instrument, period = state["playing_sample"], state["period"]
            step = round(PAULA_CLOCK / period / divisors[instrument] / PCM_RATE * 256) if period and instrument else 0
            if not 0 <= step <= 255:
                raise ValueError(f"Sample {instrument} exceeds fractional-cursor range: {step}")
            maximum_step = max(maximum_step, step)
            pcm.append({"sample": instrument, "step": step, "volume": state["volume"],
                        "trigger": state["trigger"]})
        arranged.append({key: tick[key] for key in ("time_s", "duration_s", "order", "pattern", "row", "tick")} | {"pcm": pcm})
    duration = len(arranged) / 50
    result = {"title": f"{mod['title']}: four original PCM tracks", "source": str(source.resolve()),
              "source_sha256": mod["sha256"], "duration_s": duration,
              "pal_clock_hz": PAL_CLOCK, "pcm_rate_hz": PCM_RATE,
              "pcm_bank": bank, "ticks": arranged,
              "mapping": "Original MOD tracks1..4 map directly to independent PCM cursors1..4",
              "mixing": {"mode": "nearest",
                         "lookup": "32+round((nibble-8)*quantized_volume/4)",
                         "quantization": "Sum four fine-grained contributions, then round once to the nearest DAC code; ties to even. No residual feedback.",
                         "initial_dac": 8, "initial_residual": 0},
              "scope": "PAL6581 sample-only resident playback; no SID oscillator approximation and no full-song audio recording stored in RAM."}
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
