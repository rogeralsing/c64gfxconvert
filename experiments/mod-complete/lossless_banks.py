"""Copy a prepared score with unused one-shot sample tails removed.

This is score-specific storage optimization. The complete digital DAC stream
must remain byte-identical; it does not establish native timing or SID quality.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mod-hybrid"))
from pcm4_reference import expected_dac


def optimize(input_path: Path, out_path: Path) -> dict:
    """Write ``out_path/arrangement.json``, copied banks and a full DAC proof.

    Loops, offset instruments and short first-DMA aliases (including their
    targets) remain intact. IDs and every prepared voice state are preserved.
    The input arrangement and its source banks are never rewritten.
    """
    input_path, out_path = Path(input_path).resolve(), Path(out_path).resolve()
    arrangement_path, proof_path = out_path / "arrangement.json", out_path / "proof.json"
    if input_path in (arrangement_path.resolve(), proof_path.resolve()):
        raise ValueError("Lossless bank output must be separate from its input")
    source_bytes = input_path.read_bytes()
    baseline = json.loads(source_bytes)
    source_paths = {Path(entry["data_file"]).resolve() for entry in baseline["pcm_bank"]}
    destinations = {int(entry["id"]): out_path / "bank" / f"sample-{int(entry['id']):02d}.bin"
                    for entry in baseline["pcm_bank"]}
    if len(destinations) != len(baseline["pcm_bank"]):
        raise ValueError("Sample bank IDs must be unique")
    planned_outputs = {path.resolve() for path in (arrangement_path, proof_path, *destinations.values())}
    if source_paths.intersection(planned_outputs):
        raise ValueError("Lossless bank output would overwrite a source bank")
    if input_path in planned_outputs:
        raise ValueError("Lossless bank output would overwrite its input arrangement")
    original_dac, original_receipt = expected_dac(baseline)
    reach = {int(entry["id"]): int(entry["maximum_sample_index_plus_one"])
             for entry in original_receipt["bank"]}
    protected: dict[int, set[str]] = {bank_id: set() for bank_id in destinations}

    def protect(bank_id: int, reason: str) -> None:
        if bank_id in protected:
            protected[bank_id].add(reason)

    for entry in baseline["pcm_bank"]:
        bank_id = int(entry["id"])
        if int(entry["loop_length"]):
            protect(bank_id, "looped bank")
        if "loop_target_id" in entry:
            protect(bank_id, "independent loop target descriptor")
            protect(int(entry["loop_target_id"]), "referenced loop target")
        if "original_instrument" in entry or "first_segment_source_offset" in entry:
            protect(bank_id, "short first-DMA alias")
            if "original_instrument" in entry:
                protect(int(entry["original_instrument"]), "short first-DMA source")
    for tick in baseline["ticks"]:
        for state in tick["pcm"]:
            if state.get("offset", 0) or state.get("offset_fraction", 0):
                protect(int(state["sample"]), "sample offset")
            if state.get("loop_sample", 0):
                protect(int(state["loop_sample"]), "prepared loop target")

    candidate = copy.deepcopy(baseline)
    bank_proof = []
    # A stale successful receipt must not survive a failed rerun.
    out_path.mkdir(parents=True, exist_ok=True)
    proof_path.unlink(missing_ok=True)
    (out_path / "bank").mkdir(exist_ok=True)
    for entry in candidate["pcm_bank"]:
        bank_id = int(entry["id"])
        raw = Path(entry["data_file"]).read_bytes()
        used = reach[bank_id]
        if not 0 <= used <= len(raw):
            raise ValueError(f"Invalid read extent for bank {bank_id}: {used} of {len(raw)}")
        values = raw if protected[bank_id] else raw[:used] if used else bytes([8])
        destination = destinations[bank_id]
        destination.write_bytes(values)
        entry.update(data_file=str(destination), bytes=len(values),
                     sha256=hashlib.sha256(values).hexdigest())
        bank_proof.append({"id": bank_id, "original_bytes": len(raw), "bytes": len(values),
                           "saved_bytes": len(raw) - len(values),
                           "maximum_sample_index_plus_one": used,
                           "protected_reasons": sorted(protected[bank_id]),
                           "original_sha256": hashlib.sha256(raw).hexdigest(),
                           "sha256": entry["sha256"]})
    candidate_dac, candidate_receipt = expected_dac(candidate)
    if not np.array_equal(original_dac, candidate_dac):
        raise ValueError("Lossless bank candidate changed the complete digital DAC stream")
    candidate_bytes = (json.dumps(candidate, indent=2) + "\n").encode()
    arrangement_path.write_bytes(candidate_bytes)
    proof = {
        "input": str(input_path), "input_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "arrangement": str(arrangement_path),
        "arrangement_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
        "original_bank_bytes": sum(entry["original_bytes"] for entry in bank_proof),
        "bank_bytes": sum(entry["bytes"] for entry in bank_proof),
        "saved_bytes": sum(entry["saved_bytes"] for entry in bank_proof),
        "samples_compared": len(original_dac), "all_dac_bytes_match": True,
        "original_dac_sha256": hashlib.sha256(original_dac.tobytes()).hexdigest(),
        "candidate_dac_sha256": hashlib.sha256(candidate_dac.tobytes()).hexdigest(),
        "banks": bank_proof, "baseline_arithmetic": original_receipt,
        "candidate_arithmetic": candidate_receipt,
        "scope": "Lossless only for this exact prepared score: every digital DAC byte compared. All four voice states and bank IDs retained. Native timing and analog SID output require separate verification.",
    }
    proof_path.write_text(json.dumps(proof, indent=2) + "\n")
    return proof


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("out", type=Path, help="Separate output directory")
    args = parser.parse_args()
    proof = optimize(args.input, args.out)
    print(json.dumps({key: proof[key] for key in
                      ("arrangement", "saved_bytes", "samples_compared", "all_dac_bytes_match")}, indent=2))


if __name__ == "__main__":
    main()
