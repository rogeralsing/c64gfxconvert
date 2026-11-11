#!/usr/bin/env python3
"""Measure anonymous MOD instruments and four-channel hybrid resource demands."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.signal import correlate, find_peaks, resample_poly


HERE = Path(__file__).resolve().parent
PAULA_CLOCK = 3546894.6
REFERENCE_PERIOD = 428


def parse(path: Path) -> tuple[bytes, list[int], list[dict], np.ndarray]:
    data = path.read_bytes()
    if data[1080:1084] != b"M.K.":
        raise ValueError("Expected four-channel, 31-instrument M.K. MOD")
    orders = list(data[952:952 + data[950]])
    pattern_count = max(orders) + 1
    patterns = np.frombuffer(data[1084:1084 + pattern_count * 1024], dtype=np.uint8).reshape(pattern_count, 64, 4, 4)
    position = 1084 + pattern_count * 1024
    instruments = []
    for sample_id in range(1, 32):
        header = data[20 + (sample_id - 1) * 30:50 + (sample_id - 1) * 30]
        length = int.from_bytes(header[22:24], "big") * 2
        loop_start = int.from_bytes(header[26:28], "big") * 2
        loop_length = int.from_bytes(header[28:30], "big") * 2
        fine = header[24] & 15
        instruments.append({"id": sample_id, "length_bytes": length,
                            "loop_start": loop_start, "loop_length": loop_length,
                            "looped": loop_length > 2, "volume": header[25],
                            "finetune": fine - 16 if fine > 7 else fine,
                            "pcm": np.frombuffer(data[position:position + length], dtype=np.int8).astype(np.float64) / 128})
        position += length
    if position != len(data):
        raise ValueError("Parsed MOD payload does not exactly cover source bytes")
    return data, orders, instruments, patterns


def features(sample: dict) -> dict:
    pcm = sample["pcm"]
    if not len(pcm):
        return {"classification": "empty", "cycles_per_sample": 0.0, "recommended_waveform": "noise"}
    loop = pcm[sample["loop_start"]:sample["loop_start"] + sample["loop_length"]]
    segment = (np.tile(loop, max(1, int(np.ceil(4096 / len(loop)))))[:4096]
               if sample["looped"] else pcm[:8192])
    segment = segment - np.mean(segment)
    up = resample_poly(segment, 8, 1)
    acf = correlate(up, up, method="fft")[len(up) - 1:]
    acf /= max(float(acf[0]), 1e-12)
    maximum_lag = min(8192, len(up) // 3)
    candidates, _ = find_peaks(acf[32:maximum_lag], prominence=0.015)
    candidates = candidates + 32
    best = max((float(acf[lag]) for lag in candidates), default=0.0)
    selected = next((int(lag) for lag in candidates if acf[lag] >= max(0.30, 0.88 * best)), None)
    periodicity = float(acf[selected]) if selected is not None else 0.0
    lag = selected / 8 if selected is not None else None
    # Short high-frequency correlation in broadband percussion is not a tonal root.
    tonal = lag is not None and periodicity >= 0.38 and lag >= 20
    cycles = 1 / lag if tonal else 0.0
    spectrum = np.abs(np.fft.rfft(segment * np.hanning(len(segment)), n=32768))
    power = spectrum ** 2
    frequencies = np.fft.rfftfreq(32768)
    total = max(float(np.sum(power)), 1e-15)
    centroid = float(np.sum(frequencies * power) / total)
    flatness = float(np.exp(np.mean(np.log(power[1:] + 1e-12))) / max(np.mean(power[1:]), 1e-12))
    peaks, _ = find_peaks(spectrum, distance=8, prominence=max(spectrum) * 0.03)
    strongest = sorted(peaks, key=lambda index: spectrum[index], reverse=True)[:10]
    reference_rate = PAULA_CLOCK / REFERENCE_PERIOD
    chunk = min(len(pcm), max(16, round(reference_rate * 0.02)))
    rms = lambda x: float(np.sqrt(np.mean(x * x)))
    classification = ("complex_tonal_loop" if sample["looped"] and tonal and periodicity < 0.85
                      else "tonal_loop" if sample["looped"] and tonal
                      else "noise_loop" if sample["looped"]
                      else "tonal_transient" if tonal else "broadband_transient")
    waveform = "triangle" if tonal and centroid < 0.012 else "saw" if tonal else "noise"
    pulse = 2048
    harmonic_fit = None
    if tonal:
        fit_segment = (np.tile(loop, max(1, int(np.ceil(8192 / len(loop)))))[:8192]
                       if sample["looped"] else pcm[:8192])
        fit_segment = fit_segment - np.mean(fit_segment)
        fit_spectrum = np.abs(np.fft.rfft(fit_segment * np.hanning(len(fit_segment)), n=65536))
        harmonic_count = min(24, int(0.49 / cycles))
        harmonics = np.arange(1, harmonic_count + 1, dtype=np.float64)
        radius = max(1, int(np.ceil(65536 / len(fit_segment))))
        amplitudes = []
        for harmonic in harmonics:
            center = round(cycles * harmonic * 65536)
            amplitudes.append(float(np.max(fit_spectrum[max(1, center - radius):min(len(fit_spectrum), center + radius + 1)])))
        target = np.array(amplitudes)
        target /= max(float(np.linalg.norm(target)), 1e-12)
        options = [("saw", None, 1 / harmonics),
                   ("triangle", None, np.where(harmonics % 2, 1 / harmonics ** 2, 0))]
        options += [("pulse", float(duty), np.abs(np.sin(np.pi * harmonics * duty)) / harmonics)
                    for duty in np.linspace(0.05, 0.5, 46)]
        scored = []
        baseline = {}
        for name, duty, candidate in options:
            candidate = candidate / np.linalg.norm(candidate)
            error = float(np.linalg.norm(target - candidate))
            scored.append((error, name, duty))
            if name != "pulse":
                baseline[name] = error
        error, waveform, duty = min(scored, key=lambda item: item[0])
        pulse = round(duty * 4096) if duty is not None else 2048
        harmonic_fit = {"method": "48 ideal waveform candidates: triangle, saw and pulse duty 5..50% in 1% steps; L2 distance between up to24 normalized harmonic amplitudes below Nyquist, at the unchanged measured fundamental",
                        "candidate_count": len(options), "best_error_l2": error,
                        "harmonic_count": harmonic_count,
                        "baseline_errors_l2": baseline, "pulse_duty": duty,
                        "target_normalized_harmonics": target.tolist(),
                        "limitation": "Ideal steady waveform magnitude only; not native SID emulation, envelope fitting, pitch search or proof of perceived similarity"}
    return {
        "classification": classification, "cycles_per_sample": cycles,
        "recommended_waveform": waveform, "pulse": pulse,
        "harmonic_fit": harmonic_fit,
        "pitch_period_source_samples": lag if tonal else None,
        "autocorrelation_at_pitch_period": periodicity,
        "root_hz_at_period_428": reference_rate * cycles,
        "root_hz_at_period_180": PAULA_CLOCK / 180 * cycles,
        "loop_cycles_at_estimated_root": sample["loop_length"] * cycles if sample["looped"] and tonal else None,
        "reference_sample_rate_hz": reference_rate,
        "duration_s_at_period_428": len(pcm) / reference_rate,
        "rms": rms(pcm), "peak": float(np.max(np.abs(pcm))),
        "first_20ms_rms": rms(pcm[:chunk]), "last_20ms_rms": rms(pcm[-chunk:]),
        "spectral_centroid_cycles_per_sample": centroid,
        "spectral_flatness": flatness,
        "strong_spectral_peaks": [{"cycles_per_sample": float(index / 32768),
                                    "hz_at_period_428": float(index / 32768 * reference_rate),
                                    "relative_amplitude": float(spectrum[index] / max(spectrum))}
                                   for index in strongest],
        "measurement": "8x band-limited interpolation, autocorrelation of first 4096 loop samples (repeated when shorter) or first 8192 unlooped samples; choose first peak >=88% of strongest and >=0.30, require lag>=20 and correlation>=0.38 for tonal root",
        "pitch_caveat": "An estimated waveform repetition rate, not a stored MOD root-note label. Strong even harmonics or multiple tones can make perceived pitch differ by an octave.",
    }


def schedule(orders: list[int], instruments: list[dict], patterns: np.ndarray) -> dict:
    states = [{"selected": 0, "playing": 0, "period": 428, "target": 428,
               "position": 0.0, "volume": 0, "porta": 0} for _ in range(4)]
    triggers = [Counter() for _ in range(4)]
    periods = {sample["id"]: Counter() for sample in instruments}
    usage_seconds = [Counter() for _ in range(4)]
    histogram = Counter()
    tonal_histogram = Counter()
    examples = []
    fx = Counter()
    speed, bpm, elapsed = 6, 125, 0.0
    row_count = 0
    for order_index, pattern in enumerate(orders):
        for row in range(64):
            row_count += 1
            events = []
            next_order = False
            for channel, raw in enumerate(patterns[pattern, row]):
                a, b, c, d = map(int, raw)
                sample_id, period, effect, argument = (a & 0xF0) | (c >> 4), (a & 15) << 8 | b, c & 15, d
                fx[f"{effect:X}{argument:02X}"] += 1
                state = states[channel]
                if sample_id:
                    state["selected"] = sample_id
                    state["volume"] = instruments[sample_id - 1]["volume"]
                if period:
                    if effect == 3 and state["playing"]:
                        state["target"] = period
                    else:
                        state.update(playing=state["selected"], period=period, target=period, position=0.0)
                        triggers[channel][state["playing"]] += 1
                        periods[state["playing"]][period] += 1
                if effect == 3 and argument:
                    state["porta"] = argument
                if effect == 12:
                    state["volume"] = min(64, argument)
                if effect == 15 and argument:
                    if argument <= 31:
                        speed = argument
                    else:
                        bpm = argument
                if effect == 13:
                    next_order = True
                events.append((effect, argument))
            for tick in range(speed):
                tick_duration = 2.5 / bpm
                sounding = []
                tonal = []
                looped_tonal = []
                for channel, state in enumerate(states):
                    effect, argument = events[channel]
                    if tick:
                        if effect == 3:
                            distance = state["target"] - state["period"]
                            state["period"] += max(-state["porta"], min(state["porta"], distance))
                        if effect == 10:
                            state["volume"] = max(0, min(64, state["volume"] + ((argument >> 4) or -(argument & 15))))
                    sample_id = state["playing"]
                    if not sample_id:
                        continue
                    sample = instruments[sample_id - 1]
                    if state["volume"] > 0:
                        sounding.append((channel, sample_id))
                        usage_seconds[channel][sample_id] += tick_duration
                        if sample["cycles_per_sample"]:
                            tonal.append((channel, sample_id))
                            if sample["looped"]:
                                looped_tonal.append((channel, sample_id))
                    state["position"] += PAULA_CLOCK / max(1, state["period"]) * tick_duration
                    if state["position"] >= sample["length_bytes"]:
                        if sample["looped"]:
                            state["position"] = sample["loop_start"] + ((state["position"] - sample["loop_start"]) % sample["loop_length"])
                        else:
                            state["playing"] = 0
                histogram[len(sounding)] += tick_duration
                tonal_histogram[len(tonal)] += tick_duration
                if len(looped_tonal) >= 3 and len(sounding) == 4 and len(examples) < 8:
                    if not examples or (examples[-1]["order"], examples[-1]["row"]) != (order_index, row):
                        examples.append({"seconds": elapsed, "order": order_index, "pattern": pattern,
                                         "row": row, "tick": tick, "audible_channel_sample_pairs": sounding,
                                         "tonal_channel_sample_pairs": looped_tonal,
                                         "note": "At least three simultaneous looped tonal samples plus a fourth active track; this is a resource lower bound independent of pitched percussion classification"})
                elapsed += tick_duration
            if next_order:
                break
    pcm_ids = sorted(set(triggers[0]) | set(triggers[1]))
    sid_only_ids = sorted((set(triggers[2]) | set(triggers[3])) - set(pcm_ids))
    pcm_bytes = sum(instruments[sample_id - 1]["length_bytes"] for sample_id in pcm_ids)
    return {
        "duration_s_first_order_pass": elapsed, "rows": row_count,
        "sample_note_triggers_per_channel": [{str(k): v for k, v in sorted(count.items())} for count in triggers],
        "audible_sample_seconds_per_channel": [{str(k): v for k, v in sorted(count.items())} for count in usage_seconds],
        "sample_trigger_periods": {str(k): {str(p): v for p, v in sorted(count.items())} for k, count in periods.items() if count},
        "concurrent_audible_logical_channels_seconds": {str(k): v for k, v in sorted(histogram.items())},
        "concurrent_tonal_channels_seconds": {str(k): v for k, v in sorted(tonal_histogram.items())},
        "three_tonal_plus_percussion_examples": examples,
        "fixed_mapping": {"pcm_mod_channels": [0, 1], "sid_mod_channels": [2, 3],
                          "pcm_sample_ids": pcm_ids, "sid_only_sample_ids": sid_only_ids,
                          "pcm_original_8bit_bytes": pcm_bytes, "pcm_packed_4bit_bytes": pcm_bytes // 2,
                          "sample_bytes_saved_by_dropping_sid_only_pcm": sum(instruments[i - 1]["length_bytes"] for i in sid_only_ids),
                          "recommendation": "Use two logical PCM mixers for MOD channels0/1 and one SID oscillator each for channels2/3. This preserves four simultaneous logical tracks without SID voice stealing. The two PCM tracks share the D418 output and require software mixing."},
        "dynamic_mapping_caveat": "Three simultaneous tonal logical tracks occur alongside percussion. A two-SID mapping by sample class must demote a tonal track to PCM or steal a voice. Fixed channel routing avoids allocator ambiguity.",
        "timing_model": "Tick durations, speed/tempo, volume changes/slides, portamento, finite sample ends and loops; instantaneous vibrato pitch modulation is omitted from lifetime estimation. Tick-level occupancy can overcount a finite sample by less than one tick. First listed order pass only.",
        "effects": dict(sorted(fx.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=HERE / "sources/stardust-memories.mod")
    parser.add_argument("--out", type=Path, default=HERE / "results/instrument-analysis.json")
    args = parser.parse_args()
    data, orders, samples, patterns = parse(args.source)
    for sample in samples:
        sample.update(features(sample))
    scheduling = schedule(orders, samples, patterns)
    used = set().union(*(set(map(int, counts)) for counts in scheduling["sample_note_triggers_per_channel"]))
    report_samples = []
    for sample in samples:
        if sample["id"] not in used:
            continue
        sample["initial_mapping"] = "SID on fixed MOD channels2/3; PCM when played on channels0/1" if sample["cycles_per_sample"] else "PCM preferred; use SID noise approximation only on a fixed SID track"
        report_samples.append({key: value for key, value in sample.items() if key != "pcm"})
    report = {"schema_version": 1, "source_bytes": len(data),
              "source_sha256": hashlib.sha256(data).hexdigest(), "format": "M.K. four-channel MOD",
              "privacy": "Sample names and embedded contact strings are not read or exported",
              "paula_clock_hz": PAULA_CLOCK, "reference_period": REFERENCE_PERIOD,
              "pitch_formula": "sid_note_hz = paula_clock_hz / MOD_period * cycles_per_sample",
              "noise_pitch_rule": "cycles_per_sample=0 means no reliable tonal root; a SID noise approximation still needs a positive oscillator frequency to clock its LFSR",
              "samples": report_samples, "scheduling": scheduling,
              "evidence_limit": "Feature measurements and pattern simulation only; no claim of listening assessment or learned perceptual fidelity"}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(args.out)
    print(json.dumps({"out": str(args.out), "sample_ids": sorted(used), "fixed_mapping": scheduling["fixed_mapping"],
                      "three_tonal_plus_percussion_examples": scheduling["three_tonal_plus_percussion_examples"][:1]}, indent=2))


if __name__ == "__main__":
    main()
