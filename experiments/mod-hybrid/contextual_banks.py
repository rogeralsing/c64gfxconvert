"""Reuse a preferred sample bank when a complete note fits its pitch range.

The fallback banks cover the whole score. A bank changes only on retrigger,
so its pointer and fractional step never switch scale during a held note.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from mod_reader import load_mod
from pcm4_prepare import PAULA_CLOCK
from pcm4_reference import expected_dac
from timeline import build_timeline


def combine(full_path: Path, preferred_path: Path, out: Path) -> dict:
    full = json.loads(full_path.read_text())
    preferred = json.loads(preferred_path.read_text())
    if full["source_sha256"] != preferred["source_sha256"]:
        raise ValueError("Both bank sets must belong to the same source MOD")
    mod = load_mod(Path(full["source"]))
    timeline = build_timeline(mod)["ticks"]
    if len(timeline) != len(full["ticks"]):
        raise ValueError("Fallback must contain the complete original timeline")
    result = copy.deepcopy(full)
    result["mixing"] = copy.deepcopy(preferred["mixing"])
    fallbacks = {int(item["id"]): item for item in full["pcm_bank"]}
    wanted = {int(item["id"]): item for item in preferred["pcm_bank"]}
    entries = {i: copy.deepcopy(item) for i, item in fallbacks.items()}
    variants = {}
    next_id = max(entries) + 1
    for instrument, item in wanted.items():
        original = fallbacks[instrument]
        same = all(item[key] == original[key] for key in ("base_divisor", "loop_start", "loop_length"))
        same = same and Path(item["data_file"]).read_bytes() == Path(original["data_file"]).read_bytes()
        if same:
            variants[instrument] = instrument
        else:
            if next_id > 255:
                raise ValueError("Sample variants exceed the byte-sized bank ID")
            variants[instrument] = next_id
            entries[next_id] = copy.deepcopy(item) | {"id": next_id, "original_sample": instrument}
            next_id += 1
    counts = {"preferred_notes": 0, "fallback_notes": 0}
    for voice in range(4):
        triggers = [i for i, tick in enumerate(timeline) if tick["channels"][voice]["trigger"]]
        for start, stop in zip(triggers, triggers[1:] + [len(timeline)]):
            instrument = timeline[start]["channels"][voice]["playing_sample"]
            if not instrument:
                continue
            segment = timeline[start:stop]
            target = wanted.get(instrument)
            periods = [tick["channels"][voice]["period"] for tick in segment if tick["channels"][voice]["period"] > 0]
            safe = target is not None and (not periods or round(PAULA_CLOCK / min(periods) / target["base_divisor"] / full["pcm_rate_hz"] * 256) <= 255)
            selected = variants[instrument] if safe else instrument
            counts["preferred_notes" if safe else "fallback_notes"] += 1
            divisor = entries[selected]["base_divisor"]
            for index in range(start, stop):
                state = timeline[index]["channels"][voice]
                if state["playing_sample"] != instrument:
                    raise ValueError("A playing instrument changed without a trigger")
                period = state["period"]
                step = round(PAULA_CLOCK / period / divisor / full["pcm_rate_hz"] * 256) if period else 0
                if not 0 <= step <= 255:
                    raise ValueError("Selected bank exceeds fractional cursor range")
                result["ticks"][index]["pcm"][voice]["sample"] = selected
                result["ticks"][index]["pcm"][voice]["step"] = step
    used = {state["sample"] for tick in result["ticks"] for state in tick["pcm"]} - {0}
    out.mkdir(parents=True, exist_ok=True)
    (out / "bank").mkdir(exist_ok=True)
    result["pcm_bank"] = []
    for identifier in sorted(used):
        entry = entries[identifier]
        raw = Path(entry["data_file"]).read_bytes()
        target = out / "bank" / f"sample-{identifier:02d}.bin"
        target.write_bytes(raw)
        entry["data_file"] = str(target.resolve())
        entry.setdefault("original_sample", identifier)
        result["pcm_bank"].append(entry)
    result["sample_optimization"] = {"method": "preferred pitch-range bank per complete triggered note; whole-score fallback",
                                     "preferred_input": str(preferred_path.resolve()),
                                     "fallback_input": str(full_path.resolve()), **counts}
    # No original volume, trigger, ordering or tick duration may change.
    for before, after in zip(full["ticks"], result["ticks"]):
        for key in ("time_s", "duration_s", "order", "pattern", "row", "tick"):
            if before[key] != after[key]:
                raise ValueError("Timeline metadata changed")
        for old, new in zip(before["pcm"], after["pcm"]):
            if (old["volume"], old["trigger"]) != (new["volume"], new["trigger"]):
                raise ValueError("Original volume or trigger changed")
    expected, _ = expected_dac(preferred)
    actual, _ = expected_dac(result)
    # A short score suppresses staging its missing next tick at EOF. Exclude
    # only those final four output slots when comparing a full continuation.
    checked = len(expected) - 4
    mismatch = int((expected[:checked] != actual[:checked]).sum())
    target = out / "arrangement.json"
    target.write_text(json.dumps(result, separators=(",", ":")) + "\n")
    receipt = {"candidate": str(target.resolve()), "duration_s": result["duration_s"],
               "bank_entries": len(used), **counts,
               "preferred_prefix_dac_bytes_checked": checked,
               "preferred_prefix_dac_mismatches": mismatch,
               "preferred_prefix_scope": "Complete preferred excerpt except four EOF staging slots",
               "source_sha256": mod["sha256"],
               "candidate_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
               "scope": "Exact original note, volume and trigger timeline. Changed bank variants must be evaluated across their full pitch ranges."}
    (out / "evaluation.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", type=Path, required=True)
    parser.add_argument("--preferred", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(combine(args.full, args.preferred, args.out), indent=2))


if __name__ == "__main__":
    main()
