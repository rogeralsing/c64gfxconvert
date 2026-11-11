"""Read sample-based four-channel ProTracker and Startrekker MODs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def load_mod(path: Path | str) -> dict:
    """Return samples indexed by ``id - 1`` and pattern/row/channel note dictionaries.

    Sample ``data`` is signed 8-bit PCM stored as bytes; use numpy.int8 when
    interpreting it numerically. Sample names are deliberately omitted because
    tracker instruments can also contain old personal contact information.
    """
    path = Path(path)
    data = path.read_bytes()
    if len(data) < 1084 or data[1080:1084] not in (b"M.K.", b"M!K!", b"4CHN", b"FLT4"):
        raise ValueError("Expected a four-channel, 31-instrument ProTracker MOD")
    startrekker = data[1080:1084] == b"FLT4"
    length = data[950]
    if not 1 <= length <= 128:
        raise ValueError("Invalid order count")
    orders = list(data[952:952 + length])
    # ProTracker counts stored patterns across all 128 order-table entries,
    # including entries beyond the active song length (pt2_load_mod31.c).
    pattern_count = max(data[952:1080]) + 1
    sample_offset = 1084 + pattern_count * 1024
    if sample_offset > len(data):
        raise ValueError("Truncated pattern data")
    samples = []
    for index in range(31):
        start = 20 + 30 * index
        size = int.from_bytes(data[start + 22:start + 24], "big") * 2
        finetune = data[start + 24] & 15
        if finetune >= 8:
            finetune -= 16
        volume = data[start + 25]
        loop_start = int.from_bytes(data[start + 26:start + 28], "big") * 2
        loop_length = int.from_bytes(data[start + 28:start + 30], "big") * 2
        if volume > 64 or sample_offset + size > len(data):
            raise ValueError(f"Invalid sample {index + 1}")
        if loop_length > 2 and loop_start + loop_length > size:
            raise ValueError(f"Sample {index + 1} loop exceeds its data")
        samples.append({
            "id": index + 1, "data": data[sample_offset:sample_offset + size],
            "length": size, "finetune": finetune, "volume": volume,
            "loop_start": loop_start, "loop_length": loop_length,
        })
        sample_offset += size
    padding = data[sample_offset:]
    if any(padding):
        raise ValueError("Unexpected data after samples; pattern layout needs review")
    patterns = []
    for pattern in range(pattern_count):
        rows = []
        for row in range(64):
            channels = []
            for channel in range(4):
                offset = 1084 + 1024 * pattern + 16 * row + 4 * channel
                a, b, c, d = data[offset:offset + 4]
                sample = (a & 0xF0) | (c >> 4)
                if sample > 31:
                    raise ValueError("Invalid sample number in a pattern")
                channels.append({"sample": sample, "period": ((a & 15) << 8) | b,
                                 "effect": c & 15, "param": d})
            rows.append(channels)
        patterns.append(rows)
    if startrekker:
        # FLT4 uses the same 31-sample layout, but can also reference AM/FM
        # synthesis kept in a companion file. Accept only self-contained PCM:
        # every explicitly selected instrument must have actual sample data.
        # OpenMPT's Load_mod.cpp detects missing AM data through empty samples.
        selected = {n["sample"] for p in patterns for r in p for n in r if n["sample"]}
        if any(not samples[index - 1]["length"] for index in selected):
            raise ValueError("FLT4 references an empty instrument; external AM/FM synthesis is unsupported")
    digest = hashlib.sha256(data).hexdigest()
    timing_mode = None
    receipt_path = path.with_suffix(".source.json")
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if "timing_mode" in receipt:
            if receipt["sha256"] != digest:
                raise ValueError("MOD timing receipt does not identify this source")
            timing_mode = receipt["timing_mode"]
            if timing_mode not in ("cia", "vblank"):
                raise ValueError(f"Unsupported MOD timing mode {timing_mode!r}")
            if startrekker and timing_mode != "vblank":
                raise ValueError("FLT4 requires VBlank timing")
    result = {
        "title": data[:20].split(b"\0")[0].decode("latin1"),
        "source_path": str(path.resolve()), "sha256": digest,
        "channels": 4, "orders": orders, "patterns": patterns, "samples": samples,
        "bytes": len(data),
        "format": "Startrekker FLT4" if startrekker else "ProTracker MOD",
    }
    if padding:
        result["layout"] = {"declared_payload_bytes": sample_offset,
                            "trailing_zero_padding_bytes": len(padding),
                            "trailing_zero_padding_sha256": hashlib.sha256(padding).hexdigest()}
    if timing_mode is not None:
        result["timing_mode"] = timing_mode
    return result
