"""Package sequential original/C64 auditions of isolated MOD tracks.

Each pair contains the same 30–50s passage: original, a half-second pause,
then actual VICE output. Only constant gain changes are applied. No mix,
equalization, pitch correction, time stretch or additional synthesis occurs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf


def package(root: Path) -> dict:
    destination = root / "comparisons"
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for track in range(1, 5):
        original_path = root / "original" / f"track-{track}.wav"
        c64_path = root / "c64" / f"track-{track}" / "vice" / "stardust-vice.wav"
        original, rate = sf.read(original_path, dtype="float64")
        c64_full, c64_rate = sf.read(c64_path, dtype="float64")
        if rate != 22050 or c64_rate != rate or original.ndim != 1 or c64_full.ndim != 1:
            raise ValueError("Solos must be mono at 22050 Hz")
        c64 = c64_full[30 * rate:50 * rate]
        if len(original) != 20 * rate or len(c64) != len(original):
            raise ValueError("Both solos must cover exactly seconds 30–50")
        if not np.isfinite(original).all() or not np.isfinite(c64).all():
            raise ValueError("Solo contains invalid PCM")
        rms = [float(np.sqrt(np.mean(x * x))) for x in (original, c64)]
        if min(rms) < 1e-5:
            raise ValueError(f"Track {track} contains an unexpectedly silent solo")
        # Equal RMS within each pair. Lower the common target if either side's
        # crest factor requires it, preserving peaks without limiting.
        target = min(.15, *(0.90 * level / max(float(np.max(np.abs(x))), 1e-12)
                           for x, level in zip((original, c64), rms)))
        gains = [target / level for level in rms]
        sides = [original * gains[0], c64 * gains[1]]
        gap = np.zeros(rate // 2)
        joined = np.concatenate((sides[0], gap, sides[1]))
        path = destination / f"channel-{track}-original-then-c64.wav"
        sf.write(path, joined, rate, subtype="PCM_16")
        for label, pcm in zip(("original", "c64"), sides):
            sf.write(destination / f"channel-{track}-{label}.wav", pcm, rate, subtype="PCM_16")
        records.append({"track": track, "file": str(path.resolve()),
                        "original_source": str(original_path.resolve()),
                        "c64_source": str(c64_path.resolve()),
                        "original_source_sha256": hashlib.sha256(original_path.read_bytes()).hexdigest(),
                        "c64_source_sha256": hashlib.sha256(c64_path.read_bytes()).hexdigest(),
                        "pair_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "original_raw_rms": rms[0], "c64_raw_rms": rms[1],
                        "original_gain": gains[0], "c64_gain": gains[1],
                        "matched_rms": target, "frames": len(joined), "rate": rate,
                        "segments": [{"content": "original", "start_s": 0, "end_s": 20},
                                     {"content": "silence", "start_s": 20, "end_s": 20.5},
                                     {"content": "c64", "start_s": 20.5, "end_s": 40.5}]})
    receipt = {"passage_start_s": 30, "passage_duration_s": 20,
               "order": "Original for 20s, silence for 0.5s, C64 for 20s",
               "level_method": "Constant RMS matching per pair, common peak-safe target; no other processing",
               "tracks": records,
               "scope": "Channel auditions of the existing v2 arrangement; no new tone, note or mix choices."}
    (root / "comparisons.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=here / "results/channel-solos")
    args = parser.parse_args()
    print(json.dumps(package(args.root), indent=2))


if __name__ == "__main__":
    main()
