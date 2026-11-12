"""Prepare the bounded native dual-sampler score entirely from source assets.

No VICE run, historic generated music directory, recording or host audio mix
is used. The frozen twenty-second stream digests protect approved SID3 sound
and the separately verified C3 source before native assembly and capture.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
SID = HERE.parent
sys.path[:0] = [str(HERE), str(SID)]

import baseline
import c3_data
import gain_preapplied_study
import music_data
import native_support as support

APPROVED_SID3_SHA256 = "080852a5c0cf96f0e3b00ac856d594015c92a513435ccb5e08816d54cfa267a2"
VERIFIED_C3_HIGH_SHA256 = "37426b47dd1df02925b08ac4ce50d1a36bf3bee9931d71256ca32f5a4d163de0"
VERIFIED_C3_LATCHES_SHA256 = "01e2fcbf9ca20c47b10de0d83397b7884d42807225ae21388ba22efc98282ca9"


def prepare(out: Path) -> dict:
    """Generate baseline, clock-bound C3 windows and linked independent data."""
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = {"root": out, "base": out / "base", "c3_model": out / "c3-model",
             "c3_windows": out / "c3-windows", "linked": out / "linked"}
    base, _, _ = baseline.prepare(paths["base"])
    sid3 = paths["base"] / "expected-input.bin"
    if support.digest(sid3) != APPROVED_SID3_SHA256:
        raise ValueError("Prepared SID3 input differs from the frozen approved phrase")

    cuts = [0]
    for count in base["frame_sample_counts_exact"]:
        cuts.append(cuts[-1] + count)
    counts = []
    for low, high in zip(cuts, cuts[1:]):
        first = max(4, (low + 3) // 4 * 4)
        counts.append(0 if first >= high else (high - 1 - first) // 4 + 1)
    if len(counts) != 1000 or sum(counts) != 39097:
        raise ValueError("The source SID3 clock no longer yields the verified C3 event count")
    binding = {
        "source": "Freshly prepared1000 SID3 buffers, cumulative156/157sample cuts",
        "high_rate_total_values": cuts[-1], "high_rate_sample_period_cycles": 126,
        "SID2_latch_high_indices": {"startup_neutral": [0],
            "ring_values": {"first": 4, "stride": 4, "last": max(range(4, cuts[-1], 4))}},
        "source_state_assignment": "cuts[t]<=future_latch_high_index<cuts[t+1]",
        "producer_pipeline": "phase2 at highindex2 reads ring[1] for latch4; no50Hzphase reset",
        "native_timing_confirmation": "Verified SID2 latch+35, phase2read+37/release+43, W244, last_enabled249, reference105",
        "first_frame_ring_count": counts[0], "second_frame_ring_count": counts[1],
    }
    c3 = c3_data.prepare(paths["c3_model"], sample_period_cycles=504,
                         frame_counts=counts, clock_binding=binding,
                         startup_neutral_values=1, analyze_quality=False)
    windows = gain_preapplied_study.prepare(paths["c3_model"], paths["c3_windows"])
    linked = music_data.prepare(paths["linked"], c3_source=paths["c3_windows"], original=paths["base"])
    paths.update(data_asm=paths["linked"] / "data.asm",
                 sid3_expected=sid3,
                 c3_expected_high=paths["linked"] / "c3/expected-high.bin",
                 c3_expected_latches_high=paths["linked"] / "c3/expected-latches-high.bin")
    high_sha = support.digest(paths["c3_expected_high"])
    latch_sha = support.digest(paths["c3_expected_latches_high"])
    if high_sha != VERIFIED_C3_HIGH_SHA256 or latch_sha != VERIFIED_C3_LATCHES_SHA256:
        raise ValueError("Freshly prepared C3 frequency input differs from the verified native phrase")
    verification = {"passed": True, "sid3_values": base["input_codes"],
                    "sid3_input_sha256": support.digest(sid3),
                    "c3_ring_values": c3["output_values"],
                    "c3_startup_neutral_latches": c3["startup_neutral_values"],
                    "c3_high_sha256": high_sha, "c3_latches_high_sha256": latch_sha,
                    "c3_bank_roundtrip_passed": c3["packed_roundtrip_passed"],
                    "c3_window_roundtrip_passed": windows["window_roundtrip_passed"],
                    "c3_direct_roundtrip_passed": linked["c3"]["native_read_proof"]["frequency_high_stream_exact_after_declared_quantization"],
                    "resident_data_bytes": linked["resident_data_bytes"],
                    "data_end": linked["data_end"],
                    "scope": "Source preparation and exact data roundtrips only. No native runtime, audio capture or listening acceptance is claimed by this stage."}
    serialized_paths = {name: str(path) for name, path in paths.items()}
    receipt = {"paths": serialized_paths, "verification": verification,
               "clock_binding": binding,
               "method": "Baseline instrument analysis, globally bound C3 source model, reusable per-instrument gain windows and independent native linker; no cached generated score dependency."}
    support.save(out / "preparation.json", receipt)
    return {"linked": linked, "paths": serialized_paths, "verification": verification}
