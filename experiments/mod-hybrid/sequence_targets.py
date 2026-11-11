"""Prepare continuous original-MOD channel targets for phrase-level SID fitting.

API::

    manifest = build_targets(source_path, output_directory)
    targets = load_targets(output_directory)
    targets["windows"]["train"]["audio"]       # float64 mono, original30–50s
    targets["windows"]["train"]["ticks"]       # original tracker controls
    targets["contexts_by_sample"][14]           # multiple actual note contexts

Audio targets come from one independently decoded libopenmpt solo, continuously
rendered from song start. Per-note WAVs are crops of that decode, not isolated
sample re-triggers. MOD sample names and embedded contact strings are omitted.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.signal import correlate, find_peaks
import soundfile as sf

from mod_reader import load_mod
from solo_original import load_library, render_track
from timeline import build_timeline


HERE = Path(__file__).resolve().parent
PAULA_CLOCK = 3546894.6
WINDOWS = {"history_0_50": (0, 50), "train": (30, 50),
           "holdout_unseen": (50, 70), "holdout_seen": (150, 170)}


def pitch_features(audio: np.ndarray, rate: int) -> dict:
    """Return spectral lines and competing periodicities, without naming a root."""
    audio = np.asarray(audio, dtype=np.float64)
    audio = audio - np.mean(audio)
    if len(audio) < 64 or np.max(np.abs(audio)) < 1e-7:
        return {"silent": True, "spectral_peaks": [], "autocorrelation_candidates": []}
    spectrum = np.abs(np.fft.rfft(audio * np.hanning(len(audio)), n=32768))
    frequency = np.fft.rfftfreq(32768, 1 / rate)
    peaks, _ = find_peaks(spectrum, distance=max(1, round(8 * 32768 / rate)),
                          prominence=float(np.max(spectrum)) * 0.03)
    peaks = sorted((i for i in peaks if 40 <= frequency[i] <= 7000),
                   key=lambda i: spectrum[i], reverse=True)[:8]
    acf = correlate(audio, audio, method="fft")[len(audio) - 1:]
    acf /= max(float(acf[0]), 1e-15)
    first_lag = max(2, round(rate / 2500))
    last_lag = min(len(audio) // 2, round(rate / 45))
    lags, _ = find_peaks(acf[first_lag:last_lag], prominence=0.03)
    lags = sorted(lags + first_lag, key=lambda i: acf[i], reverse=True)[:6]
    candidates = [{"hz": float(rate / lag), "correlation": float(acf[lag])} for lag in lags]
    return {"silent": False, "frames": len(audio),
            "true_window_resolution_hz": rate / len(audio),
            "spectral_peaks": [{"hz": float(frequency[i]),
                                 "relative_amplitude": float(spectrum[i] / max(spectrum))} for i in peaks],
            "autocorrelation_candidates": candidates,
            "interpretation": "Strongest spectral line is not necessarily the repeated musical pitch; multiple candidates are retained."}


def _note_trajectory(audio: np.ndarray, rate: int) -> list[dict]:
    width = min(len(audio), 4096)
    starts = sorted({max(0, min(len(audio) - width, round(fraction * len(audio) - width / 2)))
                     for fraction in (0.2, 0.5, 0.8)})
    return [{"offset_s": start / rate, **pitch_features(audio[start:start + width], rate)}
            for start in starts]


def build_targets(source: str | Path, out: str | Path, rate: int = 22050) -> dict:
    """Write targets and return their manifest. MOD track2 is zero-based index1."""
    source, out = Path(source), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    notes_dir = out / "notes"
    notes_dir.mkdir(exist_ok=True)
    mod = load_mod(source)
    timeline = build_timeline(mod)
    end_s = max(end for _, end in WINDOWS.values())
    lib, library = load_library()
    full_pcm, mute = render_track(lib, source.read_bytes(), 1, rate, round(end_s * rate))
    full = full_pcm.astype(np.float64) / 32768
    full_name = "original-track-2-0-170.wav"
    sf.write(out / full_name, full_pcm, rate, subtype="PCM_16")
    controls, notes = [], []
    position = 0.0
    current_note = None
    for index, tick in enumerate(timeline["ticks"]):
        start_frame = round(tick["time_s"] * rate)
        if start_frame >= len(full):
            break
        end_frame = round((tick["time_s"] + tick["duration_s"]) * rate)
        state = tick["channels"][1]
        sample_id, period = state["playing_sample"], state["period"]
        if state["trigger"]:
            position = float(state["offset"])
            if current_note is not None:
                current_note["end_frame"] = start_frame
            current_note = {"note_index": len(notes), "sample_id": sample_id,
                            "start_frame": start_frame, "end_frame": len(full),
                            "start_s": start_frame / rate, "period_at_trigger": period,
                            "volume_at_trigger": state["volume"], "trigger_tick_index": index}
            notes.append(current_note)
        start_position = position
        if sample_id and period:
            position += PAULA_CLOCK / period * (end_frame - start_frame) / rate
            sample = mod["samples"][sample_id - 1]
            loop_end = sample["loop_start"] + sample["loop_length"]
            if sample["loop_length"] > 2 and position >= loop_end:
                position = sample["loop_start"] + (position - sample["loop_start"]) % sample["loop_length"]
        original_note = mod["patterns"][tick["pattern"]][tick["row"]][1]
        controls.append({"tick_index": index, "start_frame": start_frame, "end_frame": end_frame,
                         "time_s": start_frame / rate, "duration_s": (end_frame - start_frame) / rate,
                         "order": tick["order"], "pattern": tick["pattern"], "row": tick["row"],
                         "tick_in_row": tick["tick"], "playing_sample": sample_id,
                         "selected_sample": state["sample"], "period": period,
                         "volume": state["volume"], "trigger": state["trigger"], "offset": state["offset"],
                         "sample_position_start": start_position, "sample_position_end": position,
                         "effect": original_note["effect"], "effect_param": original_note["param"]})
    context_candidates = defaultdict(list)
    for note in notes:
        note["end_s"] = note["end_frame"] / rate
        note["duration_s"] = (note["end_frame"] - note["start_frame"]) / rate
        note["ticks"] = [control["tick_index"] for control in controls
                         if note["start_frame"] <= control["start_frame"] < note["end_frame"]]
        note["windows"] = [name for name, (start, end) in WINDOWS.items()
                           if note["start_frame"] < end * rate and note["end_frame"] > start * rate]
        # Every0–50s note is retained. Sample16 is absent there, so retain its
        # first later contexts as explicitly untrained diagnostic material.
        retain = note["start_frame"] < 50 * rate
        if note["sample_id"] == 16 and len(context_candidates[16]) < 8:
            retain = True
        if retain:
            filename = f"notes/note-{note['note_index']:04d}-sample-{note['sample_id']:02d}.wav"
            sf.write(out / filename, full_pcm[note["start_frame"]:note["end_frame"]], rate, subtype="PCM_16")
            note["audio_file"] = filename
            audio = full[note["start_frame"]:note["end_frame"]]
            note["pitch_trajectory"] = _note_trajectory(audio, rate)
            note["context_role"] = "training_history" if note["start_frame"] < 50 * rate else "untrained_diagnostic"
            context_candidates[note["sample_id"]].append(note)
    contexts = {}
    for sample_id, candidates in context_candidates.items():
        selected = []
        seen_periods = set()
        # Prioritize actual objective-phrase notes, then cover different pitches.
        ordered = sorted(candidates, key=lambda n: ("train" not in n["windows"], -n["duration_s"]))
        for note in ordered:
            if note["period_at_trigger"] not in seen_periods:
                selected.append(note["note_index"])
                seen_periods.add(note["period_at_trigger"])
            if len(selected) == 6:
                break
        for note in ordered:
            if len(selected) >= 6:
                break
            if note["note_index"] not in selected:
                selected.append(note["note_index"])
        contexts[str(sample_id)] = selected
    windows = {}
    for name, (start_s, stop_s) in WINDOWS.items():
        start, stop = round(start_s * rate), round(stop_s * rate)
        name_audio = f"{name}.wav"
        sf.write(out / name_audio, full_pcm[start:stop], rate, subtype="PCM_16")
        indices = [i for i, c in enumerate(controls) if start <= c["start_frame"] < stop]
        trigger_counts = Counter(c["playing_sample"] for c in controls
                                 if start <= c["start_frame"] < stop and c["trigger"])
        sample_seconds = Counter()
        for i in indices:
            sample_seconds[controls[i]["playing_sample"]] += controls[i]["duration_s"]
        windows[name] = {"start_s": start_s, "end_s": stop_s, "start_frame": start, "end_frame": stop,
                         "frames": stop - start, "audio_file": name_audio,
                         "tick_indices": indices, "trigger_counts_by_sample": dict(trigger_counts),
                         "selected_sample_seconds": dict(sample_seconds)}
    train_ids = set(windows["history_0_50"]["trigger_counts_by_sample"])
    for name in ("holdout_unseen", "holdout_seen"):
        windows[name]["instruments_absent_from_0_50"] = sorted(set(windows[name]["trigger_counts_by_sample"]) - train_ids)
    baseline_path = HERE / "results/channel-solos/c64/track-2/vice/stardust-vice.wav"
    baseline = None
    if baseline_path.exists():
        prior, prior_rate = sf.read(baseline_path, dtype="float64")
        if prior_rate != rate:
            raise ValueError("V2 comparison audio sample rate differs")
        sf.write(out / "baseline-v2-train.wav", prior[30 * rate:50 * rate], rate, subtype="PCM_16")
        baseline = {"source": str(baseline_path.resolve()), "sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
                    "audio_file": "baseline-v2-train.wav", "window_s": [30, 50]}
    manifest = {"schema_version": 1, "mod_track_1_based": 2, "sample_rate": rate,
                "source": str(source.resolve()), "source_sha256": mod["sha256"],
                "independent_decoder": "libopenmpt", "decoder_library": library,
                "mute_status": mute, "full_audio_file": full_name,
                "audio_processing": "Native independent PCM16 decode; no gain, normalization, pitch shift, truncation per sample or note retriggering outside the original score",
                "windows": windows, "ticks_file": "ticks.json", "notes_file": "notes.json",
                "contexts_by_sample": contexts, "baseline_v2": baseline,
                "pitch_measurement": "Windowed spectral lines plus competing autocorrelation peaks on actual played note contexts; neither is declared perceptual pitch truth",
                "polyphony_limit": "Several competing partials or weak autocorrelation alone do not prove recorded chords. No global one-SID impossibility claim is justified by these measurements.",
                "holdout_policy": "Do not use holdout audio or sample16 diagnostic contexts for fitting while claiming those passages are independent validation. holdout_unseen includes new instruments; holdout_seen uses instruments already present in0–50s."}
    (out / "ticks.json").write_text(json.dumps(controls, separators=(",", ":")) + "\n")
    (out / "notes.json").write_text(json.dumps(notes, indent=2) + "\n")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def load_targets(out: str | Path) -> dict:
    """Load arrays and controls. Window tick times remain absolute song times."""
    out = Path(out)
    manifest = json.loads((out / "manifest.json").read_text())
    ticks = json.loads((out / manifest["ticks_file"]).read_text())
    notes = json.loads((out / manifest["notes_file"]).read_text())
    windows = {}
    for name, record in manifest["windows"].items():
        audio, rate = sf.read(out / record["audio_file"], dtype="float64")
        if rate != manifest["sample_rate"] or len(audio) != record["frames"]:
            raise ValueError(f"Window audio does not match metadata: {name}")
        windows[name] = {**record, "audio": audio, "ticks": [ticks[i] for i in record["tick_indices"]]}
    contexts = {}
    for sample_id, indices in manifest["contexts_by_sample"].items():
        contexts[int(sample_id)] = []
        for index in indices:
            note = notes[index]
            audio, rate = sf.read(out / note["audio_file"], dtype="float64")
            contexts[int(sample_id)].append({**note, "audio": audio,
                                             "controls": [ticks[i] for i in note["ticks"]]})
    return {"manifest": manifest, "windows": windows, "ticks": ticks,
            "notes": notes, "contexts_by_sample": contexts}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=HERE / "sources/stardust-memories.mod")
    parser.add_argument("--out", type=Path, default=HERE / "results/channel-fit-2/targets")
    args = parser.parse_args()
    manifest = build_targets(args.source, args.out)
    print(json.dumps({"out": str(args.out), "contexts": {key: len(value) for key, value in manifest["contexts_by_sample"].items()},
                      "windows": {key: {"frames": value["frames"], "triggers": value["trigger_counts_by_sample"]}
                                  for key, value in manifest["windows"].items()}}, indent=2))


if __name__ == "__main__":
    main()
