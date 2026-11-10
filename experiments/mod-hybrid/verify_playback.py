"""Compare actual emulated SID register state with the original arranged score.

This checks the assembled 6502 decoder at its hardware boundary. A matching
Python bytecode decoder alone cannot catch an assembly branch/state bug.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

PAL_CLOCK = 985248


def verify(arrangement_path: Path, capture_path: Path) -> dict:
    score = json.loads(arrangement_path.read_text())
    capture = json.loads(capture_path.read_text())
    trace_path = capture_path.parent / "registers.txt"
    sid_voices = len(score["ticks"][0]["sid"])
    registers = {voice * 7 + offset: ([], []) for voice in range(sid_voices) for offset in (0, 1, 6)}
    clock = 0
    for line in trace_path.open():
        try:
            delta, register, value = map(int, line.split())
        except ValueError:
            continue
        clock += delta
        register &= 31
        if register in registers:
            registers[register][0].append(clock)
            registers[register][1].append(value)
    # Check halfway through each tick. The foreground decoder is interruptible;
    # register commits can trail the tick boundary while PCM IRQ timing remains
    # continuous. The 10ms observation point is explicit, not fitted to audio.
    times = np.asarray([capture["trace"]["first_sample_cycle"] +
                        round((tick["time_s"] + .010) * PAL_CLOCK)
                        for tick in score["ticks"]], dtype=np.int64)

    def held(register: int) -> np.ndarray:
        cycles, values = registers[register]
        indexes = np.searchsorted(cycles, times, side="right") - 1
        if np.any(indexes < 0):
            raise ValueError("Missing initial SID register state")
        return np.asarray(values, dtype=np.int64)[indexes]

    checks = []
    for voice in range(sid_voices):
        actual_frequency = held(voice * 7) | (held(voice * 7 + 1) << 8)
        actual_volume = held(voice * 7 + 6) >> 4
        expected_frequency = np.asarray([t["sid"][voice]["frequency"] for t in score["ticks"]])
        expected_volume = np.asarray([min(15, (t["sid"][voice]["volume"] * 15 + 32) // 64)
                                      for t in score["ticks"]])
        bad = np.flatnonzero((actual_frequency != expected_frequency) | (actual_volume != expected_volume))
        checks.append({"voice": voice + 1, "ticks_checked": len(times), "mismatch_count": len(bad),
                       "examples": [{"tick": int(i), "time_s": score["ticks"][int(i)]["time_s"],
                                     "expected_frequency": int(expected_frequency[i]), "actual_frequency": int(actual_frequency[i]),
                                     "expected_volume": int(expected_volume[i]), "actual_volume": int(actual_volume[i])}
                                    for i in bad[:12]]})
    receipt = {"arrangement_sha256": hashlib.sha256(arrangement_path.read_bytes()).hexdigest(),
               "program_sha256": capture["program_sha256"], "observation_ms_into_tick": 10,
               "voices": checks, "passed": all(c["mismatch_count"] == 0 for c in checks),
               "scope": "Actual C64 SID frequency and sustain-register values across every score tick. Does not assess analog envelope response, waveform timbre or PCM sample-pointer identity."}
    (capture_path.parent / "score-check.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if not receipt["passed"]:
        raise ValueError(f"Assembled C64 playback differs from arranged SID score: {checks}")
    return receipt


def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arrangement", type=Path, default=here / "results/arrangement.json")
    parser.add_argument("--capture", type=Path, default=here / "results/vice/capture.json")
    args = parser.parse_args()
    print(json.dumps(verify(args.arrangement, args.capture), indent=2))


if __name__ == "__main__":
    main()
