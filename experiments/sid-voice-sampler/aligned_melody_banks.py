"""Move loop ends to page boundaries without changing the sampled stream.

Only score-specific instrument data changes. The native player and its
126-cycle NMI remain unchanged. An independent logical replay checks every
sample before any transformed instruments are written.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

CLOCK, PERIOD = 985248, 126
RATE = CLOCK / PERIOD


def _counts(samples: dict) -> list[int]:
    frames, metadata = samples["frames"], samples["metadata"]
    if metadata["frames"] != len(frames):
        raise ValueError("Frame count differs from the prepared score")
    if metadata["sample_period_cycles"] != PERIOD or abs(metadata["sample_rate_hz"] - RATE) > 1e-8:
        raise ValueError("Loop alignment requires the existing 126-cycle sample clock")
    counts = metadata.get("frame_sample_counts_exact")
    if counts is None:
        cuts = [(n * CLOCK + PERIOD * 25) // (PERIOD * 50) for n in range(len(frames) + 1)]
        counts = [b - a for a, b in zip(cuts, cuts[1:])]
    counts = list(counts)
    if (len(counts) != len(frames) or any(type(n) is not int or not 1 <= n <= 256 for n in counts)
            or sum(counts) != metadata["input_codes"]):
        raise ValueError("Frame lengths do not cover the prepared sampled input")
    return counts


def _walk(frames: list, banks: dict, counts: list[int]):
    """Yield actual audible read indices using a logical 8-bit fractional cursor."""
    position, ended, started = 0, True, False
    for frame, count in zip(frames, counts):
        step, trigger, variant = frame
        if not 0 <= step <= 255 or trigger not in (0, 1) or not 0 <= variant <= 255:
            raise ValueError("Invalid prepared PCM state")
        bank = banks[variant & 127]
        end, loop = bank["real_end"], bank["loop_start"]
        if trigger:
            position, ended, started = 0, False, True
        if not started and (step or not variant & 128):
            raise ValueError("An inactive prefix must stay muted with zero cursor step")
        reads = []
        for _ in range(count):
            if ended or variant & 128:
                reads.append(None)
            else:
                index = position >> 8
                if not 0 <= index < end:
                    raise ValueError("A live cursor lies outside its logical bank")
                reads.append(index)
            if not ended:
                position += step
                if position >= end * 256:
                    if loop is None:
                        position, ended = end * 256, True
                    else:
                        position = loop * 256 + (position - end * 256) % ((end - loop) * 256)
        yield bank["id"], reads


def _replay(frames: list, banks: dict, counts: list[int]) -> bytes:
    result = bytearray()
    for identifier, reads in _walk(frames, banks, counts):
        data = banks[identifier]["data"]
        for index in reads:
            if index is None:
                result.append(128)
            elif index >= len(data):
                raise ValueError(f"Active read outside stored bank {identifier}: {index} >= {len(data)}")
            else:
                result.append(data[index])
    return bytes(result)


def align(samples: dict, candidate: Path) -> dict:
    """Return transformed samples and write only ``candidate/aligned-instruments``.

    For old loop [S,E), choose D=(-E)%256, append D periodic samples, and use
    [S+D,E+D). Its period and every emitted value are unchanged. Gain changes
    retain the corresponding loop phase. Trimmed banks are rebuilt only for
    their actual reads in this score; unread holes need not contain source data.
    Original bank files and preparation metadata are never overwritten.
    """
    counts = _counts(samples)
    original = {}
    for item in samples["banks"]:
        bank = dict(item, data=bytes(item["data"]))
        identifier, end, loop = bank["id"], bank["real_end"], bank["loop_start"]
        if identifier in original or not 0 <= identifier < 128:
            raise ValueError("Bank IDs must be unique and fit below the mute bit")
        if not bank["data"] or len(bank["data"]) % 256:
            raise ValueError("Stored banks must contain complete nonempty pages")
        if not 0 < end < 0xFF00 or loop is not None and not 0 <= loop < end:
            raise ValueError("Invalid logical source bank bounds")
        if hashlib.sha256(bank["data"]).hexdigest() != bank["sha256"]:
            raise ValueError("A source bank differs from its prepared hash")
        original[identifier] = bank
    if any((frame[2] & 127) not in original for frame in samples["frames"]):
        raise ValueError("The score selects a missing source bank")
    baseline = _replay(samples["frames"], original, counts)
    baseline_sha = hashlib.sha256(baseline).hexdigest()
    if baseline_sha != samples["metadata"]["expected_input_sha256"]:
        raise ValueError("Independent replay differs from the prepared sampled input")
    transformed = {identifier: dict(bank) for identifier, bank in original.items()}
    for identifier, bank in transformed.items():
        if bank["loop_start"] is not None:
            padding = (-bank["real_end"]) % 256
            bank["real_end"] += padding
            bank["loop_start"] += padding
            if bank["real_end"] >= 0xFF00:
                raise ValueError("Aligned loop endpoint exceeds the native logical range")
    required = {identifier: set() for identifier in transformed}
    for identifier, reads in _walk(samples["frames"], transformed, counts):
        required[identifier].update(index for index in reads if index is not None)
    descriptors = []
    for identifier, bank in transformed.items():
        old, reads = original[identifier], required[identifier]
        maximum = max(reads, default=-1)
        if old["loop_start"] is None or old["real_end"] == bank["real_end"]:
            data = old["data"]
        else:
            size = max(256, ((maximum + 256) // 256) * 256)
            values = bytearray([128]) * size
            for index in range(size):
                mapped = (index if index < old["real_end"] else old["loop_start"]
                          + (index - old["real_end"]) % (old["real_end"] - old["loop_start"]))
                if mapped < len(old["data"]):
                    values[index] = old["data"][mapped]
                elif index in reads:
                    raise ValueError(f"Alignment needs unavailable source data in bank {identifier}: {mapped}")
            data = bytes(values)
        bank.update(data=data, stored_bytes=len(data), max_read_index=maximum,
                    sha256=hashlib.sha256(data).hexdigest())
        descriptors.append({"id": identifier, "old_real_end": old["real_end"],
            "old_loop_start": old["loop_start"], "real_end": bank["real_end"],
            "loop_start": bank["loop_start"], "padding_samples": bank["real_end"] - old["real_end"],
            "old_stored_bytes": len(old["data"]), "stored_bytes": len(data),
            "maximum_read_index": maximum, "old_sha256": old["sha256"], "sha256": bank["sha256"]})
    aligned = _replay(samples["frames"], transformed, counts)
    if aligned != baseline:
        raise ValueError("Loop alignment changed the complete sampled stream")
    destination = Path(candidate).resolve() / "aligned-instruments"
    planned = {identifier: destination / f'{identifier:03d}-{Path(bank["asm_path"]).name}'
               for identifier, bank in original.items()}
    source_files = {Path(bank["asm_path"]).resolve() for bank in original.values()}
    if source_files.intersection(path.resolve() for path in planned.values()):
        raise ValueError("Aligned instruments would overwrite source banks")
    destination.mkdir(parents=True, exist_ok=True)
    for identifier, bank in transformed.items():
        path, data = planned[identifier], bank["data"]
        path.write_text("// Score-specific lossless page-aligned loop bank; original source bank preserved.\n"
            + "\n".join(".byte " + ",".join(f"${value:02x}" for value in data[n:n + 16])
                        for n in range(0, len(data), 16)) + "\n")
        path.with_suffix(".bin").write_bytes(data)
        bank["asm_path"] = path
    proof = {"samples_compared": len(baseline), "frames": len(samples["frames"]),
        "all_sample_inputs_identical": True, "original_input_sha256": baseline_sha,
        "aligned_input_sha256": hashlib.sha256(aligned).hexdigest(),
        "original_bank_bytes": sum(len(bank["data"]) for bank in original.values()),
        "bank_bytes": sum(len(bank["data"]) for bank in transformed.values()),
        "banks": descriptors,
        "scope": "Every prepared sample compared by an independent logical cursor, including gain changes, mute, retriggers and fractional loop phase. Exact only for this complete score. Native deadlines require separate VICE verification."}
    for descriptor in descriptors:
        planned[descriptor["id"]].with_suffix(".json").write_text(json.dumps(descriptor, indent=2) + "\n")
    (destination / "alignment-proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    result = copy.deepcopy(samples)
    result["banks"] = [transformed[bank["id"]] for bank in samples["banks"]]
    result["alignment_proof"] = proof
    result["metadata"].update(bank_bytes=proof["bank_bytes"], loop_alignment=proof,
        runtime_bank_descriptors=descriptors)
    return result
