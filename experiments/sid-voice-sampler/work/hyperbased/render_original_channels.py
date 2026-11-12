"""Render all four original Hyperbased MOD channels independently, in full."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
SAMPLER = HERE.parents[1]
MOD = SAMPLER.parent / "mod-hybrid"
sys.path.insert(0, str(MOD))
sys.path.insert(0, str(SAMPLER))

from native_support import source_mod
from solo_original import load_library, render_track


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source_receipt = json.loads((MOD / "sources/hyperbased.source.json").read_text())
    mod = source_mod(dict(source_receipt, title_slug="hyperbased"), HERE)
    source = Path(mod["source_path"])
    reference = HERE / "amiga-original.wav"
    reference_receipt = json.loads((HERE / "original-channels.json").read_text())
    source_hash, reference_hash = digest(source), digest(reference)
    if source_hash != source_receipt["sha256"] or source_hash != reference_receipt["source_sha256"]:
        raise ValueError("Original Hyperbased source differs from its recorded identity")
    if reference_hash != reference_receipt["sum_check"]["reference_sha256"]:
        raise ValueError("Original reference WAV differs from its recorded identity")
    original, rate = sf.read(reference, dtype="int16")
    if rate != 22050 or original.ndim != 1 or len(original) != 7361172:
        raise ValueError("Expected the complete 333.84-second mono original reference")

    lib, location = load_library()
    raw = source.read_bytes()
    summed = np.zeros(len(original), dtype=np.int32)
    channels = []
    for channel in range(4):
        print(f"Render original MOD channel {channel + 1}/4, full 333.84 seconds", flush=True)
        pcm, mute_proof = render_track(lib, raw, channel, rate, len(original))
        path = HERE / f"amiga-channel-{channel + 1}.wav"
        sf.write(path, pcm, rate, subtype="PCM_16")
        saved, saved_rate = sf.read(path, dtype="int16")
        if saved_rate != rate or not np.array_equal(saved, pcm):
            raise ValueError(f"WAV roundtrip changed channel {channel + 1}")
        values = pcm.astype(np.float64) / 32768
        peak = int(np.max(np.abs(pcm.astype(np.int32))))
        if not 0 < peak < 32767:
            raise ValueError(f"Channel {channel + 1} is silent or clipped")
        summed += pcm.astype(np.int32)
        channels.append({"source_channel": channel + 1, "file": path.name,
                         "frames": len(pcm), "sample_rate": rate,
                         "duration_s": len(pcm) / rate, "peak_pcm16": peak,
                         "rms": float(np.sqrt(np.mean(values ** 2))),
                         "sha256": digest(path), **mute_proof})

    error = original.astype(np.int32) - summed
    max_error = int(np.max(np.abs(error)))
    if max_error > 8:
        raise ValueError(f"Four channels do not reconstruct the original: max error {max_error} PCM16 LSB")
    if digest(source) != source_hash or digest(reference) != reference_hash:
        raise ValueError("Source MOD or original reference changed during rendering")
    proof = {
        "source": str(source), "source_sha256": source_hash,
        "decoder": "libopenmpt", "library": location,
        "library_sha256": digest(Path(location)),
        "renderer_sha256": digest(Path(__file__)),
        "shared_helper_sha256": digest(MOD / "solo_original.py"),
        "method": "Four fresh independent decoder instances, playing the unchanged original MOD from time zero. Interactive channel mutes isolate one original channel. All tracker effects continue to run.",
        "render_settings": "Same decoder defaults as the existing Hyperbased original reference. Mono 22050 Hz, native PCM16, repeat count zero, original pitch, tempo and gain.",
        "processing": "None. No normalization, gain, EQ, cropping, alignment or C64/SID synthesis. These are software-decoded Amiga MOD channels, not physical Amiga recordings.",
        "channels": channels,
        "sum_check": {"reference": str(reference), "reference_sha256": reference_hash,
                      "frames_compared": len(original), "maximum_error_pcm16_lsb": max_error,
                      "rms_error_pcm16_lsb": float(np.sqrt(np.mean(error.astype(np.float64) ** 2))),
                      "waveform_correlation": float(np.corrcoef(original, summed)[0, 1]),
                      "tolerance_pcm16_lsb": 8,
                      "note": "Independent integer-output decoder runs can differ by a few dither LSBs. The sum exists only for verification; no mixed listening file is generated.",
                      "passed": True},
        "passed": True,
    }
    (HERE / "original-channels.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps({"channels": channels, "sum_check": proof["sum_check"]}, indent=2))


if __name__ == "__main__":
    main()
