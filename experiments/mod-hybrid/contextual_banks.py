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


def _combine_extended(full_path: Path, preferred_path: Path, out: Path,
                      full: dict, preferred: dict) -> dict:
    """Select one cursor scale per triggered DMA lifetime, including its loops."""
    mod = load_mod(Path(full["source"]))
    timeline = build_timeline(mod)["ticks"]
    if len(timeline) != len(full["ticks"]):
        raise ValueError("Fallback must contain the complete original timeline")
    fallbacks = {int(entry["id"]): entry for entry in full["pcm_bank"]}

    def identity(entry):
        if "original_instrument" in entry:
            return ("first DMA", int(entry["original_instrument"]),
                    int(entry["first_segment_source_offset"]), int(entry["original_bytes"]))
        return ("instrument", int(entry["id"]))

    full_ids = {identity(entry): identifier for identifier, entry in fallbacks.items()}
    wanted = {full_ids[identity(entry)]: entry for entry in preferred["pcm_bank"]
              if identity(entry) in full_ids}
    preferred_ids = {int(entry["id"]): full_ids[identity(entry)]
                     for entry in preferred["pcm_bank"] if identity(entry) in full_ids}
    changed = {identifier for identifier, entry in wanted.items()
               if any(entry[key] != fallbacks[identifier][key]
                      for key in ("base_divisor", "loop_start", "loop_length"))
               or Path(entry["data_file"]).read_bytes()
               != Path(fallbacks[identifier]["data_file"]).read_bytes()}
    # An unchanged tiny DMA prefix still needs a distinct descriptor when its
    # next loop points at a changed bank. Never rewrite the fallback descriptor.
    while True:
        dependents = {identifier for identifier, entry in wanted.items()
                      if entry.get("loop_target_id")
                      and preferred_ids[int(entry["loop_target_id"])] in changed}
        if dependents <= changed:
            break
        changed |= dependents
    next_id = max(fallbacks) + 1
    variants = {}
    entries = copy.deepcopy(fallbacks)
    for identifier, entry in wanted.items():
        if identifier in changed:
            if next_id > 255:
                raise ValueError("Sample variants exceed the byte-sized bank ID")
            variants[identifier] = next_id
            entries[next_id] = copy.deepcopy(entry)
            next_id += 1
        else:
            variants[identifier] = identifier
    for identifier, entry in wanted.items():
        selected = variants[identifier]
        if selected != identifier:
            entries[selected]["id"] = selected
            entries[selected]["original_bank_id"] = identifier
            if entry.get("loop_target_id"):
                target = preferred_ids[int(entry["loop_target_id"])]
                entries[selected]["loop_target_id"] = variants[target]
    for identifier, entry in entries.items():
        entry["original_sample"] = int(entry.get("original_instrument",
                                               entry.get("original_bank_id", identifier)))

    result = copy.deepcopy(full)
    result["mixing"] = copy.deepcopy(preferred["mixing"])
    counts = {"preferred_notes": 0, "fallback_notes": 0}
    for voice in range(4):
        triggers = [index for index, tick in enumerate(full["ticks"])
                    if tick["pcm"][voice]["trigger"]]
        for start, stop in zip(triggers, triggers[1:] + [len(timeline)]):
            needed = {int(tick["pcm"][voice]["sample"])
                      for tick in full["ticks"][start:stop]} - {0}
            needed |= {int(tick["pcm"][voice]["loop_sample"])
                       for tick in full["ticks"][start:stop]
                       if tick["pcm"][voice].get("loop_sample")}
            pending = list(needed)
            while pending:
                entry = fallbacks[pending.pop()]
                for key in ("loop_target_id", "original_instrument"):
                    target = int(entry.get(key, 0))
                    if target and target not in needed:
                        needed.add(target)
                        pending.append(target)
            periods = [tick["channels"][voice]["period"] for tick in timeline[start:stop]
                       if tick["channels"][voice]["period"] > 0]
            scales = {wanted[i]["base_divisor"] for i in needed if i in wanted}
            safe = bool(needed) and needed <= wanted.keys() and len(scales) == 1
            if safe and periods:
                safe = round(PAULA_CLOCK / min(periods) / next(iter(scales))
                             / full["pcm_rate_hz"] * 256) <= 255
            counts["preferred_notes" if safe else "fallback_notes"] += 1
            if not safe:
                continue
            for index in range(start, stop):
                before = full["ticks"][index]["pcm"][voice]
                after = result["ticks"][index]["pcm"][voice]
                original_id = int(before["sample"])
                after["sample"] = variants[original_id] if original_id else 0
                if "loop_sample" in before:
                    target = int(before["loop_sample"])
                    after["loop_sample"] = variants[target] if target else 0
                if not original_id:
                    continue
                selected = entries[after["sample"]]
                divisor = selected["base_divisor"]
                source = timeline[index]["channels"][voice]
                period = source["period"]
                after["step"] = round(PAULA_CLOCK / period / divisor
                                      / full["pcm_rate_hz"] * 256) if period else 0
                if not 0 <= after["step"] <= 255:
                    raise ValueError("Selected bank exceeds fractional cursor range")
                if before["trigger"] and "original_instrument" in selected:
                    offset = int(source.get("offset", 0))
                    after["offset"] = 0
                    after["offset_fraction"] = ((offset * 256 + divisor // 2) // divisor) & 255
                elif before["trigger"] and source.get("offset", 0):
                    phase = (int(source["offset"]) * 256 + divisor // 2) // divisor
                    end = (selected["loop_start"] + selected["loop_length"]
                           if selected["loop_length"] else selected["bytes"])
                    phase = min(phase, end * 256)
                    after["offset"], after["offset_fraction"] = phase >> 8, phase & 255

    used = {int(state["sample"]) for tick in result["ticks"] for state in tick["pcm"]} - {0}
    used |= {int(state["loop_sample"]) for tick in result["ticks"] for state in tick["pcm"]
             if state.get("loop_sample")}
    pending = list(used)
    while pending:
        target = int(entries[pending.pop()].get("loop_target_id", 0))
        if target and target not in used:
            used.add(target)
            pending.append(target)
    out.mkdir(parents=True, exist_ok=True)
    (out / "bank").mkdir(exist_ok=True)
    result["pcm_bank"] = []
    for identifier in sorted(used):
        entry = entries[identifier]
        target_id = int(entry.get("loop_target_id", 0))
        if target_id and entry["base_divisor"] != entries[target_id]["base_divisor"]:
            raise ValueError("Initial DMA and loop target use different cursor scales")
        raw = Path(entry["data_file"]).read_bytes()
        target = out / "bank" / f"sample-{identifier:02d}.bin"
        target.write_bytes(raw)
        entry["data_file"] = str(target.resolve())
        result["pcm_bank"].append(entry)
    for before, after in zip(full["ticks"], result["ticks"]):
        for key in ("time_s", "duration_s", "order", "pattern", "row", "tick"):
            if before[key] != after[key]:
                raise ValueError("Timeline metadata changed")
        for old, new in zip(before["pcm"], after["pcm"]):
            if (old["volume"], old["trigger"]) != (new["volume"], new["trigger"]):
                raise ValueError("Original volume or trigger changed")
            target_id = int(new.get("loop_sample", 0))
            if target_id and new["sample"] and (entries[target_id]["base_divisor"]
                                                != entries[new["sample"]]["base_divisor"]):
                raise ValueError("Independent loop target uses a different cursor scale")

    # Extended scores compile with an eight-slot commit lead for their entire
    # duration. Initialize an implicit descriptor explicitly in the short
    # reference when its first loop change happens only after its EOF. This is
    # an equivalent initial DMA state, not a host-side audio alignment.
    comparison = copy.deepcopy(preferred)
    extended = any("loop_sample" in state for tick in result["ticks"] for state in tick["pcm"])
    normalized = extended and not any("loop_sample" in state for tick in comparison["ticks"]
                                      for state in tick["pcm"])
    if normalized:
        initial = comparison["ticks"][0]["pcm"][0]
        bank = next((entry for entry in comparison["pcm_bank"]
                     if int(entry["id"]) == int(initial["sample"])), None)
        initial["loop_sample"] = (int(bank.get("loop_target_id", bank["id"] if bank["loop_length"] else 0))
                                  if bank else 0)
    comparison_path = out / "preferred-reference.json"
    comparison_path.write_text(json.dumps(comparison, separators=(",", ":")) + "\n")
    result["sample_optimization"] = {
        "method": "Preferred complete DMA lifetime with linked loop banks; whole-score fallback",
        "preferred_input": str(comparison_path.resolve()),
        "preferred_source_input": str(preferred_path.resolve()),
        "fallback_input": str(full_path.resolve()), **counts,
    }
    expected, _ = expected_dac(comparison)
    actual, _ = expected_dac(result)
    excluded = 7 if extended else 4
    checked = max(0, len(expected) - excluded)
    mismatch = int((expected[:checked] != actual[:checked]).sum())
    target = out / "arrangement.json"
    target.write_text(json.dumps(result, separators=(",", ":")) + "\n")
    receipt = {
        "candidate": str(target.resolve()), "duration_s": result["duration_s"],
        "bank_entries": len(used), **counts,
        "preferred_prefix_dac_bytes_checked": checked,
        "preferred_prefix_dac_mismatches": mismatch,
        "preferred_prefix_eof_slots_excluded": excluded,
        "preferred_prefix_commit_mode": "extended eight-slot lead" if extended else "legacy four-slot lead",
        "preferred_prefix_initial_descriptor_normalized": normalized,
        "preferred_prefix_reference": str(comparison_path.resolve()),
        "preferred_prefix_scope": f"Complete preferred excerpt except {excluded} EOF staging slots; identical player commit cadence",
        "candidate_dac_samples": len(actual),
        "candidate_dac_sha256": hashlib.sha256(actual.tobytes()).hexdigest(),
        "source_sha256": mod["sha256"],
        "candidate_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "scope": "All four source note, volume, trigger and loop-pointer streams retained. Preferred banks are selected only for complete DMA lifetimes whose aliases and loop targets share a safe cursor scale. Full native DAC output requires separate verification.",
    }
    (out / "evaluation.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def combine(full_path: Path, preferred_path: Path, out: Path) -> dict:
    full = json.loads(full_path.read_text())
    preferred = json.loads(preferred_path.read_text())
    if full["source_sha256"] != preferred["source_sha256"]:
        raise ValueError("Both bank sets must belong to the same source MOD")
    if (any("loop_sample" in state for tick in full["ticks"] for state in tick["pcm"])
            or any("original_instrument" in entry for entry in full["pcm_bank"])):
        return _combine_extended(full_path, preferred_path, out, full, preferred)
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
