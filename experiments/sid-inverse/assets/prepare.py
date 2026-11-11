"""Fetch selected CC0 recordings and prepare deterministic inverse-SID targets.

Run with experiments/sid-inverse/.venv/bin/python. Only these four recordings
are retained. The downloaded guitar archive is cached in the ignored .downloads
directory; the selected lossless originals and licensing documents remain here.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

import numpy as np
import soundfile as sf
from scipy.signal import correlate, resample_poly


ROOT = Path(__file__).resolve().parent
RATE = 22050
MAX_SECONDS = 0.8
VCSL_COMMIT = "c1ea7bcc3c7309650ab0da9d15c9cd1fbc4a4c7e"
VCSL_BASE = f"https://raw.githubusercontent.com/sgossner/VCSL/{VCSL_COMMIT}/"
GUITAR_PAGE = "https://freepats.zenvoid.org/Guitar/acoustic-guitar.html"
GUITAR_ARCHIVE = (
    "https://freepats.zenvoid.org/Guitar/SpanishClassicalGuitar/"
    "SpanishClassicalGuitar-SFZ+FLAC-20190618.7z"
)
GUITAR_ARCHIVE_SHA256 = "903916921a21662d2237ade7f0e98e55de93cb7b86da219e4e10f4ad385b8f5e"
GUITAR_ARCHIVE_PREFIX = "SpanishClassicalGuitar-SFZ+FLAC-20190618/"

SOURCES = [
    {
        "id": "kick",
        "description": "Recorded acoustic bass drum; used as the kick target",
        "original": "originals/vcsl/BDrumNew_hit_v2_rr1_Sum.wav",
        "repository_path": "Membranophones/Struck Membranophones/Bass Drum 1/BDrumNew_hit_v2_rr1_Sum.wav",
        "sha256": "56827fe9b55f282a0db851e242bc24660d339a0e358b182966aea047240c1136",
        "nominal_note": None,
        "nominal_root_hz": None,
        "role": "fit",
    },
    {
        "id": "snare",
        "description": "Recorded modern acoustic snare drum, snares engaged",
        "original": "originals/vcsl/Snare3M_HitSN_v2_rr1_Mid.wav",
        "repository_path": "Membranophones/Struck Membranophones/Snare Drum, Modern 2/Snare3M_HitSN_v2_rr1_Mid.wav",
        "sha256": "db5a241f5758dc5e3d2fb953e495226f2b43b6453eefe6889014c32d82a5d15e",
        "nominal_note": None,
        "nominal_root_hz": None,
        "role": "fit",
    },
    {
        "id": "guitar",
        "description": "Recorded Spanish nylon-string guitar, nominal A3, MIDI 57",
        "original": "originals/freepats/A3.flac",
        "archive_member": "samples/A3.flac",
        "sha256": "08d2e90e80839bdb77342d7dcc8a73e0ec8849607d1a750ce433f9e7f0789e06",
        "nominal_note": "A3",
        "midi_note": 57,
        "nominal_root_hz": 220.0,
        "role": "fit",
    },
    {
        "id": "guitar-holdout",
        "description": "Independent recorded Spanish nylon-string guitar note, nominal C4, MIDI 60",
        "original": "originals/freepats/C4.flac",
        "archive_member": "samples/C4.flac",
        "sha256": "e8fcd63c262ebef3e84d1f24242918cc578f8b0db54049ad109815b01d1226f0",
        "nominal_note": "C4",
        "midi_note": 60,
        "nominal_root_hz": 261.6255653005986,
        "role": "holdout",
    },
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(url: str, destination: Path, expected_sha256: str | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        with urlopen(url, timeout=45) as response:
            destination.write_bytes(response.read())
    if expected_sha256 and sha256(destination) != expected_sha256:
        raise ValueError(f"Source checksum mismatch: {destination}")


def fetch_originals() -> None:
    for source in SOURCES:
        if "repository_path" in source:
            url = VCSL_BASE + quote(source["repository_path"])
            download(url, ROOT / source["original"], source["sha256"])

    download(VCSL_BASE + "LICENSE", ROOT / "originals/vcsl/LICENSE")
    archive = ROOT / ".downloads/SpanishClassicalGuitar-SFZ+FLAC-20190618.7z"
    guitar_sources = [source for source in SOURCES if "archive_member" in source]
    documentation = ["cc0.txt", "readme.txt", "SpanishClassicalGuitar-20190618.sfz"]
    all_present = all((ROOT / source["original"]).exists() for source in guitar_sources)
    all_present &= all((ROOT / "originals/freepats" / name).exists() for name in documentation)
    if not all_present:
        download(GUITAR_ARCHIVE, archive, GUITAR_ARCHIVE_SHA256)
        for source in guitar_sources:
            extract_member(archive, source["archive_member"], ROOT / source["original"])
        for name in documentation:
            extract_member(archive, name, ROOT / "originals/freepats" / name)
    for source in guitar_sources:
        if sha256(ROOT / source["original"]) != source["sha256"]:
            raise ValueError(f"Source checksum mismatch: {source['original']}")


def extract_member(archive: Path, member: str, destination: Path) -> None:
    result = subprocess.run(
        ["bsdtar", "-xOf", str(archive), GUITAR_ARCHIVE_PREFIX + member],
        capture_output=True,
        check=True,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(result.stdout)


def estimate_pitch(audio: np.ndarray, rate: int, nominal: float) -> dict:
    """Estimate a known isolated guitar note; avoid octave ambiguity by range.

    Four 150 ms windows, beginning 50/150/250/350 ms into the original,
    use autocorrelation near the nominal period and parabolic peak refinement.
    Report the median and every window so pitch drift remains visible.
    """
    estimates = []
    for start in (0.05, 0.15, 0.25, 0.35):
        segment = audio[round(start * rate):round((start + 0.15) * rate)]
        segment = segment - segment.mean()
        ac = correlate(segment, segment, method="fft")[len(segment) - 1:]
        low = int(rate / (nominal * 1.06))
        high = int(rate / (nominal * 0.94))
        peak = low + int(np.argmax(ac[low:high]))
        offset = 0.5 * (ac[peak - 1] - ac[peak + 1]) / (
            ac[peak - 1] - 2 * ac[peak] + ac[peak + 1]
        )
        estimates.append({
            "start_seconds": start,
            "frequency_hz": float(rate / (peak + offset)),
            "normalized_autocorrelation": float(ac[peak] / ac[0]),
        })
    return {
        "root_hz": float(np.median([item["frequency_hz"] for item in estimates])),
        "method": "Median of four 150 ms autocorrelation windows with parabolic peak interpolation; search within +/-6% of the SFZ key's nominal pitch",
        "windows": estimates,
    }


def prepare(source: dict) -> dict:
    path = ROOT / source["original"]
    original, rate = sf.read(path, dtype="float64", always_2d=True)
    mono = original.mean(axis=1)
    pitch = None
    if source["nominal_root_hz"]:
        pitch = estimate_pitch(mono, rate, source["nominal_root_hz"])

    divisor = math.gcd(rate, RATE)
    audio = resample_poly(mono, RATE // divisor, rate // divisor)
    dc = float(audio.mean())
    audio = audio - dc
    threshold = float(np.max(np.abs(audio))) * 0.02
    onset = int(np.flatnonzero(np.abs(audio) >= threshold)[0])
    start = max(0, onset - round(0.002 * RATE))
    audio = audio[start:start + round(MAX_SECONDS * RATE)].copy()
    if len(audio) < round(MAX_SECONDS * RATE):
        audio = np.pad(audio, (0, round(MAX_SECONDS * RATE) - len(audio)))
    fade_count = round(0.008 * RATE)
    audio[-fade_count:] *= np.cos(np.linspace(0, np.pi / 2, fade_count)) ** 2
    gain = 0.95 / float(np.max(np.abs(audio)))
    audio *= gain
    destination = ROOT / f"{source['id']}.wav"
    sf.write(destination, audio, RATE, subtype="PCM_16")

    source_url = GUITAR_ARCHIVE if "archive_member" in source else VCSL_BASE + quote(source["repository_path"])
    result = {
        "id": source["id"],
        "description": source["description"],
        "file": destination.name,
        "role": source["role"],
        "sample_rate": RATE,
        "channels": 1,
        "frames": len(audio),
        "duration_seconds": len(audio) / RATE,
        "root_hz": pitch["root_hz"] if pitch else None,
        "nominal_note": source["nominal_note"],
        "nominal_root_hz": source["nominal_root_hz"],
        "pitch_measurement": pitch,
        "license": "CC0-1.0",
        "source_url": source_url,
        "license_source": GUITAR_PAGE if "archive_member" in source else f"https://github.com/sgossner/VCSL/blob/{VCSL_COMMIT}/README.md",
        "original_file": source["original"],
        "original_sha256": sha256(path),
        "original_sample_rate": rate,
        "original_channels": original.shape[1],
        "original_duration_seconds": len(original) / rate,
        "sha256": sha256(destination),
        "processing": {
            "mono": "Arithmetic mean of source channels",
            "resampling": "scipy.signal.resample_poly, default polyphase low-pass filter",
            "removed_dc": dc,
            "onset_threshold_relative_to_peak": 0.02,
            "preroll_seconds": 0.002,
            "start_frame_at_22050_hz": start,
            "tail_fade_seconds": 0.008,
            "tail_fade": "Cosine squared, ending at zero",
            "peak_normalization": 0.95,
            "gain": gain,
            "max_seconds": MAX_SECONDS,
            "padding": "Zero padding when source remainder is shorter than 0.8 seconds",
            "output_subtype": "PCM_16",
            "pitch_shifted": False,
        },
    }
    if "archive_member" in source:
        result["archive_member"] = GUITAR_ARCHIVE_PREFIX + source["archive_member"]
        result["archive_sha256"] = GUITAR_ARCHIVE_SHA256
        result["midi_note"] = source["midi_note"]
    else:
        result["repository_commit"] = VCSL_COMMIT
        result["repository_path"] = source["repository_path"]
    return result


def main() -> None:
    fetch_originals()
    manifest = {
        "schema_version": 1,
        "purpose": "Real acoustic recordings for inverse-SID synthesis; no SID-generated target audio",
        "license": "CC0-1.0",
        "sample_rate": RATE,
        "samples": [prepare(source) for source in SOURCES],
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for sample in manifest["samples"]:
        print(f"{sample['id']}: {sample['duration_seconds']:.3f}s, {RATE}Hz mono, root_hz={sample['root_hz']}")


if __name__ == "__main__":
    main()
