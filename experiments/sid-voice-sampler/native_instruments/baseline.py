"""Prepare unchanged C1/C2/C4 source components for the native instrument mixer.

This module has no player or command-line entry point. Original C3 belongs to
its independent sampled-instrument pipeline; SID2 fields are silent placeholders.
"""
from __future__ import annotations
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np
from scipy.signal import resample_poly

HERE = Path(__file__).resolve().parent
SID = HERE.parent
sys.path.insert(0, str(SID))
import native_support as support
from full_sid_score import prepare_full_sid

CLOCK, PERIOD, PAULA = 985248, 126, 3546894.6
RATE = CLOCK / PERIOD
FRAME_COUNT = 1000
DRUM_CENTER, DRUM_SCALE, BASS_CENTER = 113, 90, 15


def prepare(out: Path) -> tuple[dict, list, dict]:
    out.mkdir(parents=True, exist_ok=True)
    receipt = json.loads((SID.parent / "mod-hybrid/sources/hyperbased.source.json").read_text())
    source = dict(receipt, title_slug="hyperbased")
    mod = support.source_mod(source, out)
    ticks = support.build_timeline(mod)["ticks"][:FRAME_COUNT]
    if len(ticks) != FRAME_COUNT or any(abs(t["duration_s"] - .02) > 1e-9 for t in ticks):
        raise ValueError("Expected exactly the original first 1,000 twenty-millisecond ticks")
    synth = prepare_full_sid(mod, ticks, out / "sid")
    # The separately prepared C3 sampler replaces these unused score fields.
    # Do not generate the rejected ordinary-voice approximation here.
    voice2 = {"kind": "unused_placeholder", "musical_part": False,
              "score_fields": [0, 0, 25],
              "settings": {"sustain": 0, "pulse_width": 2048}}
    root = synth["pitch_analysis"][1]["source_period_samples"]
    rows = [row[:3] + [0, 0, 25] for row in synth["rows"]]
    cuts = [(index * CLOCK + PERIOD * 25) // (PERIOD * 50) for index in range(len(ticks) + 1)]
    counts = np.diff(cuts).astype(int).tolist()
    bass_states = [tick["channels"][0] for tick in ticks]
    drum_states = [tick["channels"][3] for tick in ticks]
    if {s["playing_sample"] for s in bass_states} != {1}:
        raise ValueError("This bounded proof requires Hyperbased's original bass instrument 1")

    # Every waveform is an instrument asset at one declared playback pitch.
    # No bass values or sums are stored in these reusable sample assets.
    prepared, assets = {}, []
    for identifier in sorted({s["playing_sample"] for s in drum_states}):
        states = [s for s in drum_states if s["playing_sample"] == identifier]
        periods = {s["period"] for s in states}
        sample = mod["samples"][identifier - 1]
        if len(periods) != 1 or sample["loop_length"] > 2:
            raise ValueError("Linus's fixed-rate sample lane requires one pitch and one-shot samples")
        period = periods.pop()
        ratio = Fraction(RATE * period / PAULA).limit_denominator(4096)
        raw = np.frombuffer(sample["data"], np.int8).astype(np.float64) / 128
        wave = resample_poly(raw, ratio.numerator, ratio.denominator)
        prepared[identifier] = wave
        assets.append({"instrument": identifier, "source_period": period,
                       "source_sample_sha256": hashlib.sha256(sample["data"]).hexdigest(),
                       "resampling_ratio": [ratio.numerator, ratio.denominator],
                       "resampled_frames": len(wave),
                       "resampling_pitch_error_cents": 1200 * math.log2(float(ratio) / (RATE * period / PAULA))})

    drum_pages, drum_ids = [], {}
    triangle_pages, triangle_ids = [], {}
    score, phases, bass_volumes, resets = [], [], [], []
    drum_position, current, last_period = 0, None, None
    original_drum = bytearray()
    for index, (tick, count, bass, drum) in enumerate(zip(ticks, counts, bass_states, drum_states)):
        if drum.get("offset", 0) or "first_segment_bytes" in drum or drum.get("loop_sample", drum["playing_sample"]) not in (0, drum["playing_sample"]):
            raise ValueError("Offsets, short DMA segments and independent sample-loop targets are outside this proof")
        if drum["trigger"]:
            drum_position, current, last_period = 0, drum["playing_sample"], drum["period"]
        if current != drum["playing_sample"] or last_period != drum["period"]:
            raise ValueError("Fixed-rate drum notes must not change sample or pitch without a retrigger")
        wave = prepared[current]
        selected = wave[drum_position:drum_position + count]
        selected = np.pad(selected, (0, count - len(selected)))
        values = np.rint(DRUM_CENTER + selected * DRUM_SCALE * drum["volume"] / 64).astype(int)
        if values.min() < 0 or values.max() + 2 * BASS_CENTER > 255:
            raise ValueError("Mix headroom would overflow; do not wrap or clip the native sum")
        original_drum.extend(values.astype(np.uint8).tobytes())
        start = 256 - count
        page = np.full(256, DRUM_CENTER, np.uint8)
        page[start:] = values
        key = page.tobytes()
        if key not in drum_ids:
            drum_ids[key] = len(drum_pages)
            drum_pages.append(key)
        drum_page = drum_ids[key]
        drum_position += count

        active = synth["rows"][index][5] == 17
        volume = bass["volume"] if active else 0
        # Sixteen equally spaced triangle levels, with the same centre at all
        # gains. A constant-centre page silences the bass without stopping drums.
        q = np.arange(256) // 8
        triangle = np.where(q < 16, q, 31 - q)
        table = np.rint(BASS_CENTER + (2 * triangle - BASS_CENTER) * volume / 64).astype(np.uint8).tobytes()
        if table not in triangle_ids:
            triangle_ids[table] = len(triangle_pages)
            triangle_pages.append(table)
        phase_step = round(PAULA / bass["period"] / root / RATE * 65536)
        if not 0 < phase_step < 65536:
            raise ValueError("Software bass step exceeds its 16-bit phase range")
        reset = int(bass["trigger"])
        phases.append(phase_step); bass_volumes.append(volume); resets.append(reset)
        score.append([phase_step & 255, phase_step >> 8, triangle_ids[table], drum_page,
                      start, reset, *rows[index]])

    # A separate integer phase model computes the intended audible input. It
    # does not execute 6502 byte/carry operations or read the generated tables.
    phase, target, bass_codes, ranges = 0, bytearray(), bytearray(), []
    drum_array = np.frombuffer(original_drum, np.uint8).astype(int)
    position = 0
    for count, step, volume, reset in zip(counts, phases, bass_volumes, resets):
        if reset:
            phase = 0
        angles = (phase - step * np.arange(1, count + 1, dtype=np.int64)) % 65536
        level = angles // 2048
        level = np.minimum(level, 31 - level)
        bass = np.rint(BASS_CENTER + (2 * level - BASS_CENTER) * volume / 64).astype(int)
        mixed = drum_array[position:position + count] + bass
        if mixed.min() < 0 or mixed.max() > 255:
            raise ValueError("Independent model detected mixed-byte overflow")
        target.extend(mixed.astype(np.uint8).tobytes())
        bass_codes.extend(bass.astype(np.uint8).tobytes())
        phase = int(angles[-1]); position += count
        ranges.append([int(mixed.min()), int(mixed.max())])
    (out / "expected-input.bin").write_bytes(target)
    (out / "drum-input.bin").write_bytes(original_drum)
    (out / "bass-input.bin").write_bytes(bass_codes)

    # Deduplicate complete sample pages across hits and silent spans. Each
    # score record selects existing pages; the C64 computes every mixed value.
    pages_base = 0x1000
    silence_triangle = bytes([BASS_CENTER] * 256)
    if silence_triangle not in triangle_ids:
        triangle_ids[silence_triangle] = len(triangle_pages); triangle_pages.append(silence_triangle)
    silence_drums = bytes([DRUM_CENTER] * 256)
    if silence_drums not in drum_ids:
        drum_ids[silence_drums] = len(drum_pages); drum_pages.append(silence_drums)
    drum_base = pages_base + len(triangle_pages) * 256
    physical_end = drum_base + len(drum_pages) * 256 + len(score) * 12
    if physical_end > 0xD000:
        raise ValueError(f"Native mix data needs ${physical_end:04x}; cannot cross SID I/O at $d000")
    lines = [f".label FRAME_COUNT = {len(score)}", ".label SID1_SUSTAIN = 2",
             f'.label SID2_SUSTAIN = {voice2["settings"]["sustain"]}',
             ".label SID3_SUSTAIN = 15",
             ".label SID_OUTPUT_MODE = 15",
             ".label SID1_PULSE = 1966",
             f'.label SID2_PULSE = {voice2["settings"]["pulse_width"]}',
             '.assert "Mixer code must not overlap instrument pages", runtime_end <= $1000, true',
             '.pc = $1000 "Reusable mixer instrument pages"']
    for kind, pages in (("triangle", triangle_pages), ("drum", drum_pages)):
        for index, data in enumerate(pages):
            name = f"{kind}-{index:03d}.bin"
            (out / name).write_bytes(data)
            lines += [f"{kind}_{index}:", f'.import binary "{(out / name).resolve()}"']
    lines += [f".label triangle_silence = triangle_{triangle_ids[silence_triangle]}",
              f".label silence_page = drum_{drum_ids[silence_drums]}", "score:"]
    for row in score:
        physical = row.copy()
        physical[2] += pages_base >> 8
        physical[3] += drum_base >> 8
        lines.append(".byte " + ",".join(map(str, physical)))
    lines += ["program_end:", '.assert "Resident mixer must remain below SID I/O", program_end <= $d000, true']
    (out / "data.asm").write_text("\n".join(lines) + "\n")

    metadata = {"source": source, "source_range_s": [0, 20], "frames": len(score),
                "frame_sample_counts_exact": counts, "input_codes": len(target),
                "duration_s": len(target) / RATE, "sample_rate_hz": RATE,
                "sample_period_cycles": PERIOD,
                "expected_input_sha256": support.digest(out / "expected-input.bin")}
    preparation = {"bass": {"source_channel": 1, "source_instrument": 1,
                     "measured_source_period_samples": root, "triangle_levels": 16,
                     "peak_amplitude_codes": BASS_CENTER, "source_volumes": sorted(set(bass_volumes)),
                     "triggers": sum(resets), "phase_bits": 16,
                     "pitch_error_cents_range": [min(1200 * math.log2(step * RATE / 65536 / (PAULA / state["period"] / root)) for step, state in zip(phases, bass_states)),
                                                  max(1200 * math.log2(step * RATE / 65536 / (PAULA / state["period"] / root)) for step, state in zip(phases, bass_states))]},
                   "drums": {"source_channel": 4, "triggers": sum(s["trigger"] for s in drum_states),
                     "assets": assets, "gain_peak_codes": DRUM_SCALE,
                     "unique_pages": len(drum_pages), "page_references": len(score),
                     "resampling": "Each source instrument is filtered and resampled once at its declared pitch, then arranged as reusable frame pages. Original source gain is applied before the native bass sum."},
                   "memory": {"triangle_bytes": len(triangle_pages) * 256,
                     "drum_bytes": len(drum_pages) * 256, "score_bytes": len(score) * 12,
                     "program_end": physical_end, "unused_before_d000_bytes": 0xD000 - physical_end},
                   "mix_range": [min(x[0] for x in ranges), max(x[1] for x in ranges)],
                   "native_mix": "C64 16-bit software phase oscillator plus ADC of independent drum data. Linear headroom prevents overflow; no compression lookup or clipping.",
                   "mapping": {"sid_voice_3": "Original C1 software triangle bass plus original C4 drums",
                     "sid_voice_1": "Existing original C2 pulse approximation",
                     "sid_voice_2": "Unused score placeholder; the production pipeline prepares original C3 sampling separately",
                     "omitted": "Original C3 is outside this baseline helper and supplied independently by the production pipeline."},
                   "voice2": voice2,
                   "scope": "Source preparation of unchanged original C1 software bass, C2 SID1 and C4 drums only. SID2 score fields are unused placeholders, not a synthesized musical part."}
    support.save(out / "input.json", metadata)
    support.save(out / "preparation.json", preparation)
    return metadata, rows, preparation
