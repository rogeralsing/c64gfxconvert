"""Remove sample tails that the complete arranged score never reads.

This analysis preserves every read, including muted voices. An independent
integer renderer must produce identical DAC bytes before a candidate is saved.
No accepted arrangements or source-bank files are modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from pcm4_reference import expected_dac


def stored_bytes(entry: dict, length: int | None = None) -> int:
    start = int(entry["loop_start"])
    loop = int(entry["loop_length"])
    if loop:
        return start + loop * max(1, math.ceil(256 / loop))
    return len(Path(entry["data_file"]).read_bytes()) if length is None else length


def reachable_reads(arrangement: dict) -> dict[int, int]:
    ticks = arrangement["ticks"]
    cuts = (np.arange(len(ticks) + 1, dtype=np.int64) * 30789 + 200) // 400
    banks = {}
    for entry in arrangement["pcm_bank"]:
        loop = int(entry["loop_length"])
        banks[int(entry["id"])] = {
            "start": int(entry["loop_start"]), "loop": loop,
            "end": int(entry["loop_start"]) + loop if loop else len(Path(entry["data_file"]).read_bytes()),
        }
    maximum = dict.fromkeys(banks, 0)
    positions, loaded, active = [0] * 4, [0] * 4, [False] * 4
    for index, tick in enumerate(ticks):
        for voice, state in enumerate(tick["pcm"]):
            start = 0 if index == 0 else int(cuts[index]) - 4 + voice
            end = int(cuts[-1]) if index == len(ticks) - 1 else int(cuts[index + 1]) - 4 + voice
            count = end - start
            instrument, step = int(state["sample"]), int(state["step"])
            if state["trigger"]:
                loaded[voice], positions[voice], active[voice] = instrument, 0, bool(instrument)
            if not instrument:
                active[voice] = False
            if not active[voice]:
                continue
            bank = banks[loaded[voice]]
            indices = (positions[voice] + np.arange(count, dtype=np.int64) * step) >> 8
            if bank["loop"]:
                wrapped = indices >= bank["end"]
                indices[wrapped] = bank["start"] + (indices[wrapped] - bank["start"]) % bank["loop"]
            valid = indices[indices < bank["end"]]
            if len(valid):
                maximum[loaded[voice]] = max(maximum[loaded[voice]], int(valid.max()) + 1)
            positions[voice] += count * step
            pointer = positions[voice] >> 8
            if pointer >= bank["end"]:
                if bank["loop"]:
                    pointer = bank["start"] + (pointer - bank["start"]) % bank["loop"]
                    positions[voice] = (pointer << 8) | (positions[voice] & 255)
                else:
                    active[voice] = False
    return maximum


def optimize(source: Path, out: Path) -> dict:
    arrangement = json.loads(source.read_text())
    baseline, _ = expected_dac(arrangement)
    maximum = reachable_reads(arrangement)
    out.mkdir(parents=True, exist_ok=True)
    bank_dir = out / "bank"
    bank_dir.mkdir(exist_ok=True)
    records = []
    before = after = 0
    for entry in arrangement["pcm_bank"]:
        original = Path(entry["data_file"]).read_bytes()
        original_stored = stored_bytes(entry)
        original_markers = 3 if entry["loop_length"] else 1
        effective_end = int(entry["loop_start"]) + int(entry["loop_length"]) if entry["loop_length"] else len(original)
        visited = maximum[int(entry["id"])]
        action = "unchanged"
        if original and all(value == 8 for value in original):
            # Silent data needs no sustaining loop: the stop marker redirects
            # the cursor to constant silence without changing its contribution.
            data = bytes([8])
            entry["loop_start"] = entry["loop_length"] = 0
            action = "constant_silence"
        elif 0 < visited < effective_end:
            data = original[:visited]
            entry["loop_start"] = entry["loop_length"] = 0
            action = "unreachable_tail"
        else:
            data = original
        target = bank_dir / f"sample-{entry['id']:02d}.bin"
        target.write_bytes(data)
        entry["data_file"] = str(target.resolve())
        entry["bytes"] = len(data)
        entry["sha256"] = hashlib.sha256(data).hexdigest()
        new_stored = stored_bytes(entry, len(data))
        new_markers = 3 if entry["loop_length"] else 1
        before += original_stored + original_markers
        after += new_stored + new_markers
        records.append({"id": entry["id"], "action": action,
                        "maximum_read_index_plus_one": visited, "original_effective_end": effective_end,
                        "before_stored_with_markers": original_stored + original_markers,
                        "after_stored_with_markers": new_stored + new_markers})
    candidate, _ = expected_dac(arrangement)
    mismatches = np.flatnonzero(candidate != baseline)
    if len(mismatches):
        raise ValueError(f"Reachability candidate changed {len(mismatches)} DAC bytes")
    arrangement["sample_optimization"] = {
        "method": "complete-score reachability plus constant-silence reduction",
        "scope": "Valid only for this exact arranged score; rebuild for another score",
    }
    target = out / "arrangement.json"
    target.write_text(json.dumps(arrangement, separators=(",", ":")) + "\n")
    receipt = {"source": str(source.resolve()),
               "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "candidate": str(target.resolve()), "duration_s": arrangement["duration_s"],
               "stored_bank_and_marker_bytes_before": before,
               "stored_bank_and_marker_bytes_after": after, "bytes_saved": before - after,
               "dac_bytes_compared": len(baseline), "dac_mismatches": len(mismatches),
               "dac_sha256": hashlib.sha256(baseline.tobytes()).hexdigest(), "samples": records,
               "scope": "Exact digital equality for the complete input score, including muted reads. Actual C64 execution is a separate verification."}
    (out / "evaluation.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = optimize(args.input, args.out)
    print(json.dumps({key: result[key] for key in ("duration_s", "bytes_saved", "dac_bytes_compared", "dac_mismatches", "candidate")}, indent=2))


if __name__ == "__main__":
    main()
