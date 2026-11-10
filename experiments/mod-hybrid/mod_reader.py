"""Read the four-channel, 31-instrument ProTracker MOD used by this experiment."""
from __future__ import annotations

import hashlib
from pathlib import Path


def load_mod(path: Path | str) -> dict:
    """Return samples indexed by ``id - 1`` and pattern/row/channel note dictionaries.

    Sample ``data`` is signed 8-bit PCM stored as bytes; use numpy.int8 when
    interpreting it numerically. Sample names are deliberately omitted because
    tracker instruments can also contain old personal contact information.
    """
    path = Path(path)
    data = path.read_bytes()
    if len(data) < 1084 or data[1080:1084] not in (b"M.K.", b"M!K!", b"4CHN"):
        raise ValueError("Expected a four-channel, 31-instrument ProTracker MOD")
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
    if sample_offset != len(data):
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
    return {
        "title": data[:20].split(b"\0")[0].decode("latin1"),
        "source_path": str(path.resolve()), "sha256": hashlib.sha256(data).hexdigest(),
        "channels": 4, "orders": orders, "patterns": patterns, "samples": samples,
        "bytes": len(data),
    }
