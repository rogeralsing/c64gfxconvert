"""Measure a PCM-format reference; this is not a physical SID DAC simulation."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from fit import AudioLoss, prepare_target

HERE = Path(__file__).resolve().parent


def main() -> None:
    root = HERE / "results/pcm-reference"
    root.mkdir(parents=True, exist_ok=True)
    report = {"scope": "Ideal uniform four/eight-bit levels and zero-order hold at 8 kHz. No SID DAC nonlinearity, global-volume modulation, chip drift or CPU playback is modeled.", "kinds": {}}
    for kind in ("kick", "snare", "guitar"):
        original, rate = sf.read(HERE / "assets" / f"{kind}.wav")
        target = prepare_target(original, rate, rate)
        divisor = int(np.gcd(rate, 8000))
        low_rate = resample_poly(target, 8000 // divisor, rate // divisor)
        full_scale = float(np.max(np.abs(low_rate)))
        directory = root / kind
        directory.mkdir(exist_ok=True)
        sf.write(directory / "target.wav", AudioLoss(target, rate).target, rate, subtype="PCM_16")
        report["kinds"][kind] = {}
        for bits in (4, 8):
            half = (2 ** bits - 1) / 2
            codes = np.clip(np.rint((low_rate / full_scale + 1) * half), 0, 2 ** bits - 1).astype(np.uint8)
            values = (codes.astype(float) / half - 1) * full_scale
            indexes = np.minimum((np.arange(len(target)) * 8000 // rate), len(values) - 1)
            score, listening = AudioLoss(target, rate).measure(values[indexes])
            sf.write(directory / f"pcm{bits}-8khz.wav", listening, rate, subtype="PCM_16")
            if bits == 4:
                if len(codes) & 1:
                    codes = np.pad(codes, (0, 1), constant_values=8)
                packed = codes[::2] | codes[1::2] << 4
            else:
                packed = codes
            (directory / f"pcm{bits}-packed.bin").write_bytes(packed.tobytes())
            report["kinds"][kind][str(bits)] = {"scores": score, "packed_bytes": len(packed), "rate_hz": 8000,
                                      "bits": bits, "duration_s": len(target) / rate,
                                      "audio": str((directory / f"pcm{bits}-8khz.wav").relative_to(HERE))}
    (root / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
