"""Arrange the complete MOD for SID tones and software PCM voices.

The channel assignment is fixed, so the converter never steals or drops notes.
The original arrangement uses two SID and two PCM voices. Melody-first uses
three SID voices and one PCM voice, giving the lead its own SID oscillator.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from mod_reader import load_mod
from timeline import build_timeline

PAL_CLOCK = 985248
PAULA_CLOCK = 3546894.6
PCM_RATE = PAL_CLOCK / 256
WAVES = {"triangle": 0x10, "saw": 0x20, "pulse": 0x40, "noise": 0x80}


def window_rms(sample: dict, position: float, length: float) -> float:
    """Measure the actual sample envelope, including its repeat section."""
    data = np.frombuffer(sample["data"], dtype=np.int8).astype(np.float64) / 128
    if not len(data) or length <= 0:
        return 0.0
    # At most 128 evenly spaced points per 20ms tick; include zeros past end.
    index = np.floor(position + np.arange(128) * length / 128).astype(np.int64)
    loop_start, loop_length = sample["loop_start"], sample["loop_length"]
    if loop_length > 2:
        loop_end = loop_start + loop_length
        wrap = index >= loop_end
        index[wrap] = loop_start + (index[wrap] - loop_start) % loop_length
    valid = (index >= 0) & (index < len(data))
    values = np.zeros(128)
    values[valid] = data[index[valid]]
    return float(np.sqrt(np.mean(values * values)))


def arrange(source: Path, analysis_path: Path, out: Path, divisor: int = 4,
            melody_first: bool = False, overrides: Path | None = None,
            seconds: float | None = None) -> dict:
    mod = load_mod(source)
    timeline = build_timeline(mod)
    analysis = json.loads(analysis_path.read_text())
    instruments = analysis.get("instruments", analysis.get("samples"))
    if instruments is None:
        raise ValueError("Instrument analysis has no samples/instruments list")
    if isinstance(instruments, dict):
        instruments = list(instruments.values())
    instruments = {int(item["id"]): item for item in instruments}
    if overrides:
        for item in json.loads(overrides.read_text())["samples"]:
            instruments[int(item["id"])].update(item)
    pcm_tracks = (0,) if melody_first else (0, 1)
    sid_tracks = (1, 2, 3) if melody_first else (2, 3)
    gains = {1: 2.2, 2: 0.65, 3: 0.65} if melody_first else {}
    if seconds is not None:
        timeline["ticks"] = [t for t in timeline["ticks"] if t["time_s"] < seconds - 1e-8]
        timeline["rows"] = [t for t in timeline["rows"] if t["time_s"] < seconds - 1e-8]
        timeline["duration_s"] = sum(t["duration_s"] for t in timeline["ticks"])
        timeline["termination"] = "preview_cutoff"
    out.mkdir(parents=True, exist_ok=True)
    bank_dir = out / "pcm-bank"
    bank_dir.mkdir(exist_ok=True)
    pcm_ids = sorted({tick["channels"][channel]["playing_sample"] for tick in timeline["ticks"]
                      for channel in pcm_tracks if tick["channels"][channel]["playing_sample"]})
    bank = []
    for sample_id in pcm_ids:
        sample = mod["samples"][sample_id - 1]
        values = np.frombuffer(sample["data"], dtype=np.int8).astype(np.float64) / 128
        values = resample_poly(values, 1, divisor)
        quantized = np.clip(np.rint(values * 7.5 + 8), 0, 15).astype(np.uint8)
        loop_start = round(sample["loop_start"] / divisor)
        loop_length = round(sample["loop_length"] / divisor) if sample["loop_length"] > 2 else 0
        if loop_length:
            loop_length = min(loop_length, len(quantized) - loop_start)
        path = bank_dir / f"sample-{sample_id:02d}.bin"
        path.write_bytes(quantized.tobytes())
        bank.append({"id": sample_id, "data_file": str(path.resolve()),
                     "bytes": len(quantized), "loop_start": loop_start,
                     "loop_length": loop_length, "base_divisor": divisor})
    positions = [0.0] * 4
    physical = []
    for tick in timeline["ticks"]:
        sid, pcm = [], []
        for channel, state in enumerate(tick["channels"]):
            sample_id, period = state["playing_sample"], state["period"]
            if state["trigger"]:
                positions[channel] = float(state["offset"])
            rate = PAULA_CLOCK / period if period else 0
            distance = rate * tick["duration_s"]
            if channel in pcm_tracks:
                step = round(rate / divisor / PCM_RATE * 256)
                if step > 65535:
                    raise ValueError("PCM pitch exceeds unsigned 8.8 phase step")
                pcm.append({"sample": sample_id, "step": step,
                            "volume": state["volume"], "trigger": state["trigger"]})
            else:
                instrument = instruments.get(sample_id, {})
                wave = WAVES[instrument.get("recommended_waveform", "triangle")]
                cycles = float(instrument.get("cycles_per_sample", 0))
                hz = rate * cycles
                if wave == 0x80:
                    # Noise clock frequency controls its color, not a pitched fundamental.
                    # SID advances the noise LFSR sixteen times per oscillator cycle.
                    hz = rate / 16
                frequency = min(65535, max(0, round(hz * 2**24 / PAL_CLOCK)))
                rms = window_rms(mod["samples"][sample_id - 1], positions[channel], distance) if sample_id else 0
                # RMS scaling follows the sample's envelope and original tracker volume.
                # Chip and digi balance remain an arrangement choice to assess by listening.
                envelope = min(1.0, rms / 0.30)
                volume = min(64, max(0, round(state["volume"] * envelope * gains.get(channel, 1.0))))
                sid.append({"sample": sample_id, "frequency": frequency,
                            "volume": volume, "wave": wave,
                            "pulse": int(instrument.get("pulse", 2048)),
                            "trigger": state["trigger"]})
            positions[channel] += distance
            if sample_id:
                sample = mod["samples"][sample_id - 1]
                end = sample["loop_start"] + sample["loop_length"]
                if sample["loop_length"] > 2 and positions[channel] >= end:
                    positions[channel] = sample["loop_start"] + (positions[channel] - sample["loop_start"]) % sample["loop_length"]
        physical.append({key: tick[key] for key in ("time_s", "duration_s", "order", "pattern", "row", "tick")} | {"sid": sid, "pcm": pcm})
    result = {"title": "Stardust Memories", "source": str(source.resolve()),
              "duration_s": timeline["duration_s"], "pcm_rate_hz": PCM_RATE,
              "pal_clock_hz": PAL_CLOCK, "pcm_bank": bank, "ticks": physical,
              "mapping": {"mod_tracks_1_based":
                          ({str(channel + 1): f"PCM {i + 1}" for i, channel in enumerate(pcm_tracks)} |
                           {str(channel + 1): f"SID {i + 1}" for i, channel in enumerate(sid_tracks)}),
                          "sid_track_gains": {str(k + 1): v for k, v in gains.items()},
                          "voice_steals": 0, "dropped_notes": 0},
              "scope": "PAL 6581 first arrangement. SID instruments approximate original timbres. PCM is downsampled and quantized. D418 playback modulates SID master volume.",
              "sequencer": {"ticks": len(physical), "rows": len(timeline["rows"]),
                            "termination": timeline["termination"], "effects_handled": timeline["effects_handled"]}}
    destination = out / "arrangement.json"
    destination.write_text(json.dumps(result, separators=(",", ":")) + "\n")
    summary = {"duration_s": timeline["duration_s"], "ticks": len(physical),
               "pcm_sample_ids": pcm_ids, "pcm_bytes": sum(x["bytes"] for x in bank),
               "arrangement": str(destination.resolve())}
    (out / "arrangement-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=here / "sources/stardust-memories.mod")
    parser.add_argument("--analysis", type=Path, default=here / "results/instrument-analysis.json")
    parser.add_argument("--out", type=Path, default=here / "results")
    parser.add_argument("--divisor", type=int, default=4)
    parser.add_argument("--melody-first", action="store_true")
    parser.add_argument("--overrides", type=Path)
    parser.add_argument("--seconds", type=float)
    args = parser.parse_args()
    if args.divisor < 1:
        parser.error("divisor must be positive")
    if args.seconds is not None and args.seconds <= 0:
        parser.error("seconds must be positive")
    print(json.dumps(arrange(args.source, args.analysis, args.out, args.divisor,
                            args.melody_first, args.overrides, args.seconds), indent=2))


if __name__ == "__main__":
    main()
