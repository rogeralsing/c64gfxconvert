"""Evaluate attack + periodic sustain + compiled volume envelopes for PCM4.

This is an offline optimization experiment. It writes player-compatible banks
and arrangements; the shared preparer, assembler and runtime are unchanged.
Envelope values are compiled into the existing 50 Hz volume commands, and
their actual compressed score cost is included in every RAM result.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.ndimage import uniform_filter1d
from scipy.signal import fftconvolve, find_peaks, resample_poly, stft, welch

from pcm4_build import pack
from pcm4_reference import expected_dac, pcm_level


HERE = Path(__file__).resolve().parent
RATE = 985248 / 256
OUTPUT_RATE = 22050
GROUPINGS = ("row", "order", "16", "32", "48", "64", "96", "128")
SOURCES = {
    "stardust": (HERE / "results/pcm4-clean/arrangement.json", HERE / "results/reference/original.wav"),
    "hyperbased": (HERE / "results/more-mods/hyperbased/full/arrangement.json", HERE / "results/more-mods/hyperbased/original/original.wav"),
    "madness": (HERE / "results/more-mods/4mats-madness/full/arrangement.json", HERE / "results/more-mods/4mats-madness/original/original.wav"),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rms(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(values * values)))


def spectral_metrics(reference: np.ndarray, candidate: np.ndarray, rate: float) -> dict:
    reference = reference - reference.mean()
    candidate = candidate - candidate.mean()
    if rms(reference) < 1e-12:
        return {"silent_reference": True}
    errors = []
    for width in (128, 512, 1024):
        width = min(width, max(16, len(reference) // 2))
        _, _, original = stft(reference, rate, nperseg=width, noverlap=width // 2)
        _, _, changed = stft(candidate, rate, nperseg=width, noverlap=width // 2)
        errors.append(float(np.linalg.norm(abs(original) - abs(changed)) / max(np.linalg.norm(abs(original)), 1e-12)))
    window = max(8, min(len(reference) // 4, round(rate * .02)))
    original_envelope = np.sqrt(np.maximum(0, uniform_filter1d(reference * reference, window)))
    changed_envelope = np.sqrt(np.maximum(0, uniform_filter1d(candidate * candidate, window)))
    f, original_power = welch(reference, rate, nperseg=min(4096, len(reference)))
    _, changed_power = welch(candidate, rate, nperseg=min(4096, len(candidate)))
    valid = f > max(1e-7, rate / max(len(reference), 2))
    original_peak = float(f[valid][np.argmax(original_power[valid])])
    changed_peak = float(f[valid][np.argmax(changed_power[valid])])
    return {
        "multires_spectral_error": float(np.mean(errors)),
        "spectral_errors": errors,
        "envelope_normalized_rmse": rms(original_envelope - changed_envelope) / max(rms(original_envelope), 1e-12),
        "envelope_correlation": float(np.corrcoef(original_envelope, changed_envelope)[0, 1]) if np.std(original_envelope) > 1e-12 and np.std(changed_envelope) > 1e-12 else None,
        "rms_ratio": rms(candidate) / rms(reference),
        "dominant_peak_original_hz": original_peak,
        "dominant_peak_candidate_hz": changed_peak,
        "dominant_peak_error_cents": float(1200 * np.log2(changed_peak / original_peak)),
    }


def stored_bank_bytes(entries: list[dict]) -> int:
    total = 0
    for entry in entries:
        length = int(entry["loop_length"])
        total += (int(entry["loop_start"]) + length * max(1, math.ceil(256 / length)) + 3
                  if length else int(entry["bytes"]) + 1)
    return total


def score_bytes(ticks: list) -> tuple[int, str]:
    choices = [(pack(ticks, grouping)["bytes"], grouping) for grouping in GROUPINGS]
    return min(choices)


def periodic_candidates(data: np.ndarray, entry: dict, maximum: int) -> tuple[list[int], dict]:
    start = int(entry["loop_start"])
    segment = data[start:start + int(entry["loop_length"])].copy()
    segment -= segment.mean()
    n = len(segment)
    if n < 16 or rms(segment) < .02:
        return [], {"eligible": False, "reason": "short or quiet sustain"}
    autocorrelation = fftconvolve(segment, segment[::-1], mode="full")[n - 1:]
    autocorrelation /= np.maximum(n - np.arange(n), 1)
    autocorrelation /= max(autocorrelation[0], 1e-12)
    stop = min(maximum + 1, n // 3)
    peaks = find_peaks(autocorrelation[4:stop])[0] + 4
    peaks = sorted(peaks.tolist(), key=lambda lag: autocorrelation[lag], reverse=True)
    power = abs(np.fft.rfft(segment * np.hanning(n))) ** 2 + 1e-12
    flatness = float(np.exp(np.mean(np.log(power[1:]))) / np.mean(power[1:]))
    best = float(autocorrelation[peaks[0]]) if peaks else 0.0
    eligible = best >= .45 and flatness < .35
    periods = sorted(peaks[:12]) if eligible else []
    return periods, {"eligible": eligible, "spectral_flatness": flatness, "best_periodicity": best,
                     "period_candidates": [{"period": lag, "correlation": float(autocorrelation[lag])} for lag in periods]}


def fit_bank(entry: dict, mode: str, aggressive: bool, attack_cap: int | None = None,
             period_cap: int | None = None) -> dict | None:
    codes = np.frombuffer(Path(entry["data_file"]).read_bytes(), np.uint8)
    end = int(entry["loop_start"] + entry["loop_length"])
    data = (codes[:end].astype(np.float64) - 8) / 7.5
    periods, eligibility = periodic_candidates(data, entry, period_cap or (128 if aggressive else 256))
    if not periods:
        return None
    attack = min(int(entry["loop_start"]), 128) if aggressive else int(entry["loop_start"])
    if attack_cap is not None:
        attack = min(attack, attack_cap)
    attack = max(0, min(attack, len(data) - 16))
    best = None
    for period in periods:
        if attack + period >= len(data):
            continue
        for anchor_fraction in (.15, .45, .75):
            anchor = int(entry["loop_start"] + anchor_fraction * max(0, entry["loop_length"] - period * 4))
            anchor += (attack - anchor) % period
            count = min(period * 8, len(data) - anchor)
            count -= count % period
            if count < period * 2:
                continue
            cycles = data[anchor:anchor + count].reshape(-1, period)
            if mode == "envelope":
                levels = np.sqrt(np.mean(cycles * cycles, axis=1))
                valid = levels > max(float(levels.max()) * .10, 1e-4)
                if not np.any(valid):
                    continue
                shape = np.mean(cycles[valid] / levels[valid, None], axis=0)
                shape *= .90 / max(float(np.max(abs(shape))), 1e-12)
            else:
                shape = cycles.mean(axis=0)
            shape_codes = np.clip(np.rint(shape * 7.5 + 8), 0, 15).astype(np.uint8)
            shape = (shape_codes.astype(np.float64) - 8) / 7.5
            if rms(shape) < .02:
                continue
            envelope = np.ones(len(data), dtype=np.float64)
            if mode == "envelope":
                local = np.sqrt(np.maximum(0, uniform_filter1d(data * data, max(8, period * 2))))
                envelope[attack:] = np.clip(local[attack:] / rms(shape), 0, 1)
            prediction = data.copy()
            prediction[attack:] = shape[np.arange(len(data) - attack) % period] * envelope[attack:]
            measured = spectral_metrics(data, prediction, 1)
            # Match waveform and envelope; the short-loop cost remains explicit.
            loss = measured["multires_spectral_error"] + .30 * measured["envelope_normalized_rmse"]
            if best is None or loss < best["loss"]:
                new_codes = np.r_[codes[:attack], shape_codes].astype(np.uint8)
                best = {"id": entry["id"], "attack": attack, "period": period, "anchor": anchor,
                        "mode": mode, "loss": loss, "metrics": measured, "eligibility": eligibility,
                        "codes": new_codes, "envelope": envelope,
                        "old_loop_start": int(entry["loop_start"]), "old_loop_length": int(entry["loop_length"]),
                        "old_end": end}
    return best


def compile_envelopes(arrangement: dict, fits: dict[int, dict]) -> dict:
    """Compile envelope lookup at the middle of each existing music tick."""
    changed = 0
    capped = 0
    for voice in range(4):
        position = 0
        active_id = 0
        for index, tick in enumerate(arrangement["ticks"]):
            state = tick["pcm"][voice]
            if state["trigger"]:
                active_id = int(state["sample"])
                position = 0
            count = ((30789 * (index + 1) + 200) // 400 - (30789 * index + 200) // 400)
            fit = fits.get(active_id)
            if fit is not None and fit["mode"] == "envelope":
                original_index = (position + count * int(state["step"]) // 2) >> 8
                if original_index >= fit["old_end"]:
                    original_index = fit["old_loop_start"] + (original_index - fit["old_loop_start"]) % fit["old_loop_length"]
                factor = float(fit["envelope"][original_index])
                target_level = pcm_level(int(state["volume"])) * factor
                level = min(15, max(0, round(target_level)))
                new_volume = min(64, max(0, round(level * 64 / 15)))
                capped += int(target_level > 15)
                changed += int(new_volume != state["volume"])
                state["volume"] = new_volume
            position += count * int(state["step"])
    return {"changed_volume_fields": changed, "volume_fields_capped": capped,
            "extra_runtime_envelope_bytes": 0,
            "method": "Existing 50 Hz tick volume fields; midpoint source cursor lookup, quantized to the existing 16 volume levels"}


def phrase_audio(arrangement: dict) -> tuple[np.ndarray, dict]:
    clipped = dict(arrangement)
    clipped["ticks"] = arrangement["ticks"][:2500]
    clipped["duration_s"] = len(clipped["ticks"]) * .02
    dac, receipt = expected_dac(clipped)
    audio = resample_poly((dac.astype(np.float64) - 8) / 8, 176400, 30789)
    wanted = 50 * OUTPUT_RATE
    audio = np.pad(audio[:wanted], (0, max(0, wanted - len(audio))), mode="edge")
    return audio[30 * OUTPUT_RATE:50 * OUTPUT_RATE], receipt


def active_contexts(arrangement: dict, sample_id: int) -> list[dict]:
    notes = []
    for voice in range(4):
        current = None
        for index, tick in enumerate(arrangement["ticks"]):
            state = tick["pcm"][voice]
            if state["trigger"]:
                if current is not None:
                    current["end_tick"] = index
                    notes.append(current)
                current = ({"start_tick": index, "voice": voice, "active_ticks": 0}
                           if state["sample"] == sample_id else None)
            if current is not None:
                current["active_ticks"] += int(state["volume"] > 0 and state["step"] > 0)
        if current is not None:
            current["end_tick"] = len(arrangement["ticks"])
            notes.append(current)
    notes = [note for note in notes if note["active_ticks"] > 0]
    if not notes:
        return []
    first = min(notes, key=lambda note: note["start_tick"])
    longest = max(notes, key=lambda note: note["active_ticks"])
    contexts = []
    for name, note in (("first_active_note", first), ("longest_held_note", longest)):
        start = note["start_tick"]
        end = min(note["end_tick"], start + 1000)
        contexts.append({"kind": name, "start_tick": start, "end_tick": end,
                         "start_s": start * .02, "end_s": end * .02,
                         "complete_note_duration_s": (note["end_tick"] - start) * .02,
                         "voice": note["voice"]})
    return contexts


def linear_sample_audio(arrangement: dict, sample_ids: list[int]) -> dict[int, np.ndarray]:
    """Render selected instruments before final DAC rounding, with full history."""
    ticks = arrangement["ticks"]
    cuts = (np.arange(len(ticks) + 1, dtype=np.int64) * 30789 + 200) // 400
    count = int(cuts[-1])
    output = {sample: np.zeros(count, dtype=np.float64) for sample in sample_ids}
    banks = {int(entry["id"]): {"data": np.frombuffer(Path(entry["data_file"]).read_bytes(), np.uint8),
             "start": int(entry["loop_start"]), "length": int(entry["loop_length"]),
             "end": int(entry["loop_start"] + entry["loop_length"]) if entry["loop_length"] else entry["bytes"]}
             for entry in arrangement["pcm_bank"]}
    table = np.array([[32 + round((code - 8) * level / 4) for code in range(16)] for level in range(16)])
    for voice in range(4):
        position, loaded, active = 0, 0, False
        for index, tick in enumerate(ticks):
            state = tick["pcm"][voice]
            if state["trigger"]:
                position, loaded, active = 0, state["sample"], bool(state["sample"])
            if not state["sample"]:
                active = False
            if not active or loaded not in output:
                continue
            start = 0 if index == 0 else int(cuts[index]) - 4 + voice
            end = count if index == len(ticks) - 1 else int(cuts[index + 1]) - 4 + voice
            frames = end - start
            bank = banks[loaded]
            indices = (position + np.arange(frames, dtype=np.int64) * state["step"]) >> 8
            if bank["length"]:
                wrapped = indices >= bank["end"]
                indices[wrapped] = bank["start"] + (indices[wrapped] - bank["start"]) % bank["length"]
            valid = indices < bank["end"]
            codes = np.full(frames, 8, np.uint8)
            codes[valid] = bank["data"][indices[valid]]
            output[loaded][start:end] += (table[pcm_level(state["volume"]), codes] - 32) / 128
            position += frames * state["step"]
            if position >> 8 >= bank["end"]:
                if bank["length"]:
                    position = ((bank["start"] + ((position >> 8) - bank["start"]) % bank["length"]) << 8) | (position & 255)
                else:
                    active = False
    for values in output.values():
        values[1:] = values[:-1]
        values[0] = 0
    return output


def run_song(slug: str, root: Path, maximum_samples: int,
             points: tuple[str, ...] = ("conservative", "balanced", "aggressive")) -> dict:
    input_path, original_path = SOURCES[slug]
    baseline = json.loads(input_path.read_text())
    source_path = Path(baseline["source"])
    if digest(source_path) != baseline["source_sha256"]:
        raise ValueError("Original MOD source differs from the baseline arrangement")
    out = root / slug
    out.mkdir(parents=True, exist_ok=True)
    baseline_score, baseline_grouping = score_bytes(baseline["ticks"])
    baseline_bank = stored_bank_bytes(baseline["pcm_bank"])
    baseline_audio, baseline_dac = phrase_audio(baseline)
    original, original_rate = sf.read(original_path, start=30 * OUTPUT_RATE, stop=50 * OUTPUT_RATE)
    assert original_rate == OUTPUT_RATE and original.shape == baseline_audio.shape
    # The independent MOD decoder uses a different fixed mixer gain. Remove
    # only that single level difference when measuring instrument fidelity.
    original_scale = rms(baseline_audio) / max(rms(original), 1e-12)
    original *= original_scale
    baseline_original_metrics = spectral_metrics(original, baseline_audio, OUTPUT_RATE)
    selected = []
    eligibility_records = []
    for entry in sorted(baseline["pcm_bank"], key=lambda value: value["bytes"], reverse=True):
        if entry["loop_length"] < 16 or entry["bytes"] < 256:
            continue
        data = (np.frombuffer(Path(entry["data_file"]).read_bytes(), np.uint8).astype(float) - 8) / 7.5
        periods, eligibility = periodic_candidates(data, entry, 256)
        eligibility_records.append({"id": entry["id"], "bytes": entry["bytes"], **eligibility})
        if periods and len(selected) < maximum_samples:
            selected.append(entry)
    context_map = {entry["id"]: active_contexts(baseline, entry["id"]) for entry in selected}
    baseline_linear = linear_sample_audio(baseline, [entry["id"] for entry in selected])
    # A silent or inactive target cannot approve destructive compression.
    selected = [entry for entry in selected if context_map[entry["id"]]
                and rms(baseline_linear[entry["id"]]) > 1e-7]
    variants = []
    for point in points:
        aggressive = point == "aggressive"
        attack_cap = 512 if point == "balanced" else None
        period_cap = 192 if point == "balanced" else None
        for mode in ("plain_loop", "envelope"):
            name = point + "-" + mode
            directory = out / name
            directory.mkdir(exist_ok=True)
            candidate = copy.deepcopy(baseline)
            fits = {entry["id"]: fit for entry in selected
                    if (fit := fit_bank(entry, mode, aggressive, attack_cap, period_cap)) is not None}
            fit_reports = []
            for entry in candidate["pcm_bank"]:
                fit = fits.get(entry["id"])
                if fit is None:
                    continue
                path = directory / f"sample-{entry['id']:02d}.bin"
                path.write_bytes(fit["codes"].tobytes())
                entry.update({"data_file": str(path.resolve()), "bytes": len(fit["codes"]),
                              "loop_start": fit["attack"], "loop_length": fit["period"], "sha256": digest(path),
                              "processing": "Experimental preserved attack plus short periodic sustain; envelope compiled into score" if mode == "envelope" else "Experimental preserved attack plus short periodic sustain without envelope"})
                fit_reports.append({key: value for key, value in fit.items() if key not in ("codes", "envelope")})
            envelope_receipt = compile_envelopes(candidate, fits)
            for before, after in zip(baseline["ticks"], candidate["ticks"]):
                assert {k: before[k] for k in before if k != "pcm"} == {k: after[k] for k in after if k != "pcm"}
                for old_voice, new_voice in zip(before["pcm"], after["pcm"]):
                    assert all(old_voice[key] == new_voice[key] for key in ("sample", "step", "trigger"))
                    assert 0 <= new_voice["volume"] <= 64
            candidate["optimization"] = {"method": "attack + periodic waveform + compiled amplitude envelope" if mode == "envelope" else "attack + periodic waveform only", "point": name,
                                         "baseline_arrangement_sha256": digest(input_path), "runtime_changes": False}
            arrangement_path = directory / "arrangement.json"
            arrangement_path.write_text(json.dumps(candidate, separators=(",", ":")) + "\n")
            new_score, grouping = score_bytes(candidate["ticks"])
            new_bank = stored_bank_bytes(candidate["pcm_bank"])
            audio, dac_receipt = phrase_audio(candidate)
            candidate_linear = linear_sample_audio(candidate, list(fits))
            context_reports = []
            for sample_id in fits:
                for context in context_map[sample_id]:
                    lo = (context["start_tick"] * 30789 + 200) // 400
                    hi = (context["end_tick"] * 30789 + 200) // 400
                    before = baseline_linear[sample_id][lo:hi]
                    after = candidate_linear[sample_id][lo:hi]
                    measured_context = spectral_metrics(before, after, RATE)
                    context_reports.append({"sample_id": sample_id, **context,
                                            "baseline_linear_rms": rms(before),
                                            "candidate_linear_rms": rms(after),
                                            "metrics": measured_context})
            metrics = spectral_metrics(baseline_audio, audio, OUTPUT_RATE)
            original_metrics = spectral_metrics(original, audio, OUTPUT_RATE)
            listening_gain = min(.15 / max(rms(audio), 1e-12), .9 / max(float(np.max(abs(audio))), 1e-12))
            sf.write(directory / "offline-30-50s.wav", audio * listening_gain, OUTPUT_RATE, subtype="PCM_16")
            report = {"name": name, "arrangement": str(arrangement_path.resolve()), "fit_samples": fit_reports,
                      "baseline_bank_bytes_including_loop_expansion_and_markers": baseline_bank,
                      "candidate_bank_bytes_including_loop_expansion_and_markers": new_bank,
                      "sample_ram_saved": baseline_bank - new_bank,
                      "baseline_compressed_score_bytes": baseline_score, "candidate_compressed_score_bytes": new_score,
                      "added_compressed_score_bytes": new_score - baseline_score, "score_grouping": grouping,
                      "net_ram_saved": baseline_bank + baseline_score - new_bank - new_score,
                      "metrics_against_baseline_30_50s": metrics, "metrics_against_independent_original_30_50s": original_metrics,
                      "active_sample_contexts": context_reports,
                      "envelope": envelope_receipt, "dac_clipped_output_frames_first50s": dac_receipt["clipped_output_samples"],
                      "preserved": ["sample assignment", "note triggers", "pitch steps", "tick timing", "four-track routing"],
                      "limits": "Sustain timbre is approximated; envelopes update only at 50 Hz and 16 volume levels. One fixed level calibration to original is inherited from baseline. Offline output is not VICE audio."}
            (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
            variants.append(report)
            print(json.dumps({"song": slug, "variant": name, "net_ram_saved": report["net_ram_saved"],
                              "spectral_error": metrics["multires_spectral_error"],
                              "original_spectral_error": original_metrics["multires_spectral_error"]}), flush=True)
    names = {item["name"] for item in variants}
    for point in ("conservative", "balanced", "aggressive"):
        for mode in ("plain_loop", "envelope"):
            name = point + "-" + mode
            existing = out / name / "report.json"
            if name not in names and existing.exists():
                variants.append(json.loads(existing.read_text()))
    variants.sort(key=lambda item: (("conservative", "balanced", "aggressive").index(item["name"].split("-")[0]), item["name"]))
    result = {"song": slug, "baseline_arrangement": str(input_path.resolve()), "baseline_arrangement_sha256": digest(input_path),
              "original_mod": str(source_path.resolve()), "original_mod_sha256": digest(source_path),
              "original_reference": str(original_path.resolve()), "original_reference_sha256": digest(original_path),
              "baseline_bank_bytes": baseline_bank, "baseline_score_bytes": baseline_score, "baseline_score_grouping": baseline_grouping,
              "baseline_original_30_50s": baseline_original_metrics, "selected_sample_ids": [entry["id"] for entry in selected],
              "eligibility": eligibility_records, "variants": variants,
              "score_codec": "legacy PCM4 packets; all eight existing grouping sizes compared",
              "scope": "Full-song score and bank RAM accounting; complete held musical passage30–50s plus first-active and longest-held instrument contexts evaluated with unchanged player arithmetic. No listening judgment."}
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--songs", nargs="+", choices=tuple(SOURCES), default=list(SOURCES))
    parser.add_argument("--out", type=Path, default=HERE / "results/optimization/envelopes")
    parser.add_argument("--max-samples", type=int, default=4)
    parser.add_argument("--points", nargs="+", choices=("conservative", "balanced", "aggressive"),
                        default=["conservative", "balanced", "aggressive"])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    results = [run_song(slug, args.out, args.max_samples, tuple(args.points)) for slug in args.songs]
    (args.out / "summary.json").write_text(json.dumps({"method": "Attack + periodic waveform + separately compiled envelope", "songs": results}, indent=2) + "\n")


if __name__ == "__main__":
    main()
