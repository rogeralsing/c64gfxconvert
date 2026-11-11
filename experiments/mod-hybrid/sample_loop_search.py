"""Search shorter sample sustain loops, then assess complete musical phrases.

This is an offline, lossy optimization experiment. Original banks and accepted
players remain untouched. Candidates use the existing player's prefix/loop
format and retain every note, trigger, pitch step, volume and score timestamp.
"""
from __future__ import annotations

import argparse
import copy
import ctypes as ct
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
from scipy.signal import find_peaks, resample_poly
import soundfile as sf

from pcm4_reference import expected_dac, pcm_level
from sequence_loss import SequenceLoss
from solo_original import Interactive, load_library


HERE = Path(__file__).resolve().parent
PCM_RATE = 985248 / 256
RATE = 11025
PROFILES = {
    "conservative": dict(loss=.06, carrier=.015, envelope=.08, large_pitch=.03, seam=1, rms=.15),
    "balanced": dict(loss=.14, carrier=.03, envelope=.18, large_pitch=.08, seam=2, rms=.25),
    "aggressive": dict(loss=.28, carrier=.06, envelope=.30, large_pitch=.15, seam=3, rms=.40),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def size(entry: dict) -> int:
    length = int(entry["loop_length"])
    return (int(entry["loop_start"]) + length * max(1, math.ceil(256 / length)) + 3
            if length else len(Path(entry["data_file"]).read_bytes()) + 1)


def arrangement_size(arr: dict) -> int:
    return sum(size(s) for s in arr["pcm_bank"])


def resample_dac(audio: np.ndarray) -> np.ndarray:
    divisor = math.gcd(RATE * 8, 30789)
    return resample_poly(audio, RATE * 8 // divisor, 30789 // divisor)


def phrase(audio: np.ndarray, window: tuple[int, int] = (30, 50)) -> np.ndarray:
    result = resample_dac(audio)
    return result[window[0] * RATE:window[1] * RATE].astype(np.float32)


def short(arr: dict) -> dict:
    result = dict(arr)
    result["ticks"] = arr["ticks"][:2500]
    result["duration_s"] = 50.0
    return result


def render_instrument(arr: dict, instrument: int, replacement: dict | None = None,
                      step_scale: float = 1.0, window: tuple[int, int] = (30, 50)) -> np.ndarray:
    """Fine mixer contribution at actual note times, before final DAC rounding."""
    ticks = arr["ticks"][:window[1] * 50]
    entries = {s["id"]: s for s in arr["pcm_bank"]}
    entry = replacement if replacement is not None else entries[instrument]
    data = np.frombuffer(Path(entry["data_file"]).read_bytes(), np.uint8)
    loop_start, loop_length = int(entry["loop_start"]), int(entry["loop_length"])
    bank_end = loop_start + loop_length if loop_length else len(data)
    cuts = (np.arange(len(ticks) + 1, dtype=np.int64) * 30789 + 200) // 400
    mixed = np.zeros(int(cuts[-1]), np.float64)
    table = np.array([[round((code - 8) * level / 4) / 128 for code in range(16)]
                      for level in range(16)], np.float64)
    position, loaded, active = [0.] * 4, [0] * 4, [False] * 4
    for index, tick in enumerate(ticks):
        for voice, state in enumerate(tick["pcm"]):
            start = 0 if index == 0 else int(cuts[index]) - 4 + voice
            end = len(mixed) if index == len(ticks) - 1 else int(cuts[index + 1]) - 4 + voice
            if state["trigger"]:
                loaded[voice], position[voice], active[voice] = state["sample"], 0., bool(state["sample"])
            if not state["sample"]:
                active[voice] = False
            if loaded[voice] != instrument or not active[voice]:
                continue
            count = end - start
            step = float(state["step"]) * step_scale
            sample_positions = position[voice] + np.arange(count, dtype=np.float64) * step
            indices = np.floor(sample_positions / 256).astype(np.int64)
            if loop_length:
                wrap = indices >= bank_end
                indices[wrap] = loop_start + (indices[wrap] - loop_start) % loop_length
            codes = np.full(count, 8, np.uint8)
            valid = indices < bank_end
            codes[valid] = data[indices[valid]]
            mixed[start:end] += table[pcm_level(state["volume"]), codes]
            position[voice] += count * step
            pointer = int(position[voice] // 256)
            if pointer >= bank_end:
                if loop_length:
                    position[voice] = ((loop_start + (pointer - loop_start) % loop_length) * 256
                                       + position[voice] % 256)
                else:
                    active[voice] = False
    return phrase(mixed, window)


def original_instrument(source: Path, instrument: int, out: Path,
                        window: tuple[int, int] = (30, 50)) -> np.ndarray:
    """Independent libopenmpt sample-mute render, including all trigger history."""
    # Decode at22050Hz, where a50Hz MOD tick is exactly441frames. Rendering
    # directly at11025Hz lets decoder integer tick lengths accumulate drift.
    render_rate = 22050
    path = out / f"sample-{instrument:02d}-{window[0]}-{window[1]}-render22050.wav"
    if path.exists():
        pcm, rate = sf.read(path, dtype="float32")
        if rate == RATE and len(pcm) == (window[1] - window[0]) * RATE:
            return pcm
    lib, _ = load_library()
    lib.openmpt_module_get_num_samples.argtypes = [ct.c_void_p]
    lib.openmpt_module_get_num_samples.restype = ct.c_int32
    data = source.read_bytes()
    buffer, error = ct.create_string_buffer(data), ct.c_int(0)
    extended = lib.openmpt_module_ext_create_from_memory(buffer, len(data), None, None, None, None,
                                                       ct.byref(error), None, None)
    if not extended:
        raise RuntimeError(f"Independent sample decode failed: {error.value}")
    try:
        module = lib.openmpt_module_ext_get_module(extended)
        interface = Interactive()
        if lib.openmpt_module_ext_get_interface(extended, b"interactive", ct.byref(interface), ct.sizeof(interface)) != 1:
            raise RuntimeError("Independent sample muting unavailable")
        set_mute = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, ct.c_int32, ct.c_int)(interface.set_instrument_mute_status)
        get_mute = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, ct.c_int32)(interface.get_instrument_mute_status)
        count = lib.openmpt_module_get_num_samples(module)
        expected = [int(i != instrument - 1) for i in range(count)]
        for i, mute in enumerate(expected):
            if set_mute(extended, i, mute) != 1 or get_mute(extended, i) != mute:
                raise RuntimeError("Independent sample muting was not accepted")
        lib.openmpt_module_set_repeat_count(module, 0)
        pcm = np.empty(window[1] * render_rate, np.int16)
        for start in range(0, len(pcm), 4096):
            block = pcm[start:start + 4096]
            n = lib.openmpt_module_read_mono(module, render_rate, len(block),
                                            block.ctypes.data_as(ct.POINTER(ct.c_int16)))
            if n != len(block):
                raise RuntimeError(f"Independent sample decode ended early: {source.name}, sample{instrument}, window{window}, frame{start}, got{n}of{len(block)}")
    finally:
        lib.openmpt_module_ext_destroy(extended)
    result = resample_poly(pcm[window[0] * render_rate:window[1] * render_rate].astype(np.float32) / 32768, 1, 2)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, result, RATE, subtype="PCM_16")
    return sf.read(path, dtype="float32")[0]


def candidates(entry: dict, arr: dict, limit: int) -> list[dict]:
    """Autocorrelation proposes periods; direct continuation/seam checks prune."""
    raw = np.frombuffer(Path(entry["data_file"]).read_bytes(), np.uint8)
    old_start, old_length = int(entry["loop_start"]), int(entry["loop_length"])
    if old_length <= 32:
        return []
    end = old_start + old_length
    data = raw[:end].astype(np.float64) - 8
    rates = [s["step"] * PCM_RATE / 256 for t in arr["ticks"] for s in t["pcm"]
             if s["sample"] == entry["id"] and s["volume"]]
    if not rates:
        return []
    # Preserve at least100ms at the fastest actual bank playback rate, or the
    # entire original prefix when the original sustain begins sooner.
    protected = min(old_start, max(32, math.ceil(max(rates) * .1)))
    starts = sorted({int(v) for v in [old_start, protected, *np.linspace(protected, old_start, 7).astype(int)]})
    pool = []
    for start in starts:
        tail = data[start:end]
        if len(tail) < 64 or float(np.std(tail)) < .08:
            continue
        fft_n = 1 << (2 * len(tail) - 1).bit_length()
        centred = tail - tail.mean()
        spectrum = np.fft.rfft(centred, fft_n)
        correlation = np.fft.irfft(spectrum * np.conj(spectrum), fft_n)[:len(tail)]
        correlation /= np.maximum(1, np.arange(len(tail), 0, -1))
        correlation /= max(float(correlation[0]), 1e-10)
        maximum = min(len(tail) // 2, 4096)
        peaks, _ = find_peaks(correlation[16:maximum + 1])
        peaks = peaks + 16
        ranked = sorted(peaks, key=lambda p: float(correlation[p]), reverse=True)[:18]
        periods = sorted(set([int(p) for p in ranked] + [256, 384, 512, 768, 1024]))
        for length in periods:
            if length < 16 or start + length + 1 >= end:
                continue
            stored = start + length * max(1, math.ceil(256 / length)) + 3
            saving = size(entry) - stored
            if saving < 32:
                continue
            # Compare the substituted first loop sample with the continuation
            # that would have been read without looping. This measures the
            # new seam error rather than mistaking a normal steep waveform
            # slope for a discontinuity.
            seam = abs(float(data[start] - data[start + length]))
            slope = abs(float((data[start + 1] - data[start])
                              - (data[start + length + 1] - data[start + length])))
            if seam > 3 or slope > 4:
                continue
            reconstructed = np.resize(data[start:start + length], len(tail))
            rms = float(np.sqrt(np.mean(tail * tail)))
            rmse = float(np.sqrt(np.mean((tail - reconstructed) ** 2)) / max(rms, 1e-8))
            rms_ratio = float(np.sqrt(np.mean(reconstructed * reconstructed)) / max(rms, 1e-8))
            if abs(rms_ratio - 1) > .4 or rmse > 1.45:
                continue
            pool.append(dict(start=int(start), length=int(length), stored_bytes=stored,
                             saving_bytes=saving, seam_error_codes=seam, slope_error_codes=slope,
                             autocorrelation=float(correlation[length]) if length < len(correlation) else 0.,
                             sustain_waveform_nrmse=rmse, sustain_rms_ratio=rms_ratio,
                             protected_prefix_bytes=protected))
    # Include several fidelity and size optima; avoid spending the entire
    # evaluation budget on the shortest or on near-identical windows.
    chosen = []
    orderings = [sorted(pool, key=lambda c: c["sustain_waveform_nrmse"]),
                 sorted(pool, key=lambda c: (-c["saving_bytes"], c["sustain_waveform_nrmse"])),
                 sorted(pool, key=lambda c: c["sustain_waveform_nrmse"] + .25 * c["stored_bytes"] / size(entry))]
    for index in range(limit):
        for ordering in orderings:
            if index < len(ordering) and ordering[index] not in chosen:
                chosen.append(ordering[index])
            if len(chosen) >= limit:
                return chosen
    return chosen


def pitch_guard(objective: SequenceLoss, audio: np.ndarray) -> dict:
    spectrum = objective._spectra(objective._resample(np.asarray(audio, np.float32)))[-1]
    distribution = objective._log_distribution(spectrum)
    carrier = objective.log_centres[np.argmax(distribution, axis=0)]
    difference = np.abs(carrier - objective.target_carrier)
    return {"carrier_shift_over_quarter_octave_fraction": float(np.sum((difference > .25) * objective.carrier_weights)),
            "carrier_shift_over_half_octave_fraction": float(np.sum((difference > .5) * objective.carrier_weights))}


def original_mix(path: Path) -> np.ndarray:
    audio, rate = sf.read(path, start=30 * 22050, stop=50 * 22050, dtype="float32")
    if rate != 22050 or len(audio) != 20 * 22050:
        raise ValueError("Expected independent original30–50s at22050Hz")
    return resample_poly(audio, 1, 2).astype(np.float32)


def program_end(root: Path) -> int | None:
    receipt = root / "c64/build.json"
    if receipt.exists():
        return json.loads(receipt.read_text())["program_end"]
    sym = root / "c64/pcm4.sym"
    if sym.exists():
        match = re.search(r"\.label\s+program_end\s*=\s*\$([0-9a-fA-F]+)", sym.read_text())
        if match:
            return int(match[1], 16)
    return None


def held_context(arr: dict, instrument: int) -> tuple[int, int]:
    """Select a20s context containing this instrument's longest audible note."""
    spans = []
    for voice in range(4):
        begin = None
        for index, tick in enumerate(arr["ticks"]):
            state = tick["pcm"][voice]
            audible = state["sample"] == instrument and state["volume"] > 0
            if begin is not None and (state["trigger"] or not audible):
                spans.append((begin, index))
                begin = None
            if audible and begin is None:
                begin = index
        if begin is not None:
            spans.append((begin, len(arr["ticks"])))
    if not spans:
        return 30, 50
    begin, _ = max(spans, key=lambda pair: pair[1] - pair[0])
    start = min(max(0, begin // 50), max(0, int(arr["duration_s"]) - 20))
    return start, start + 20


def study(name: str, root: Path, original: Path, out: Path, candidate_limit: int,
          original_cache: Path, output_gain: float | None = None) -> dict:
    arrangement_path = root / "arrangement.json"
    arr = json.loads(arrangement_path.read_text())
    if output_gain is not None:
        arr["mixing"]["output_gain"] = output_gain
    source = Path(arr["source"])
    current = short(arr)
    out.mkdir(parents=True, exist_ok=True)
    base_dac, _ = expected_dac(current)
    baseline_audio = phrase((base_dac.astype(np.float64) - 8) / 8)
    independent_audio = original_mix(original)
    baseline_objective = SequenceLoss(baseline_audio, RATE)
    independent_objective = SequenceLoss(independent_audio, RATE)
    baseline_original_loss = independent_objective.measure(baseline_audio)
    baseline_bytes = arrangement_size(arr)
    choices = {profile: {} for profile in PROFILES}
    searches = []
    entries = {s["id"]: s for s in arr["pcm_bank"]}
    for instrument, entry in entries.items():
        if not entry["loop_length"]:
            continue
        window = (30, 50)
        baseline_part = render_instrument(arr, instrument, window=window)
        if float(np.max(np.abs(baseline_part))) < 1e-7:
            window = held_context(arr, instrument)
            baseline_part = render_instrument(arr, instrument, window=window)
            if float(np.max(np.abs(baseline_part))) < 1e-7:
                searches.append({"id": instrument, "status": "no_audible_actual_context_untouched"})
                continue
        proposals = candidates(entry, arr, candidate_limit)
        if not proposals:
            searches.append({"id": instrument, "status": "no_smaller_seam_safe_window"})
            continue
        try:
            independent_part = original_instrument(source, instrument, original_cache / sha(source), window)
        except RuntimeError as error:
            searches.append({"id": instrument, "status": "independent_context_unassessed_untouched",
                             "quality_window_s": list(window), "reason": str(error)})
            continue
        if float(np.max(np.abs(independent_part))) < 1e-7:
            searches.append({"id": instrument, "status": "independent_instrument_silent_untouched"})
            continue
        self_objective = SequenceLoss(baseline_part, RATE)
        original_objective = SequenceLoss(independent_part, RATE)
        identity = self_objective.measure(baseline_part)
        assert identity["loss"] < 1e-6
        original_baseline = original_objective.measure(baseline_part)
        octave_control = render_instrument(arr, instrument, step_scale=2, window=window)
        controls = {"identity": identity, "silence": self_objective.measure(np.zeros_like(baseline_part)),
                    "octave_up_read_rate": self_objective.measure(octave_control),
                    "octave_up_pitch_guard": pitch_guard(self_objective, octave_control)}
        evaluated = []
        raw = Path(entry["data_file"]).read_bytes()
        for index, proposal in enumerate(proposals):
            candidate_dir = out / "search" / f"sample-{instrument:02d}" / f"candidate-{index:02d}"
            candidate_dir.mkdir(parents=True, exist_ok=True)
            start, length = proposal["start"], proposal["length"]
            data = raw[:start + length]
            assert data[:start] == raw[:start]
            bank_path = candidate_dir / "bank.bin"
            bank_path.write_bytes(data)
            replacement = dict(entry, data_file=str(bank_path.resolve()), bytes=len(data),
                               loop_start=start, loop_length=length, sha256=sha(bank_path))
            audio = render_instrument(arr, instrument, replacement, window=window)
            self_loss = self_objective.measure(audio)
            original_loss = original_objective.measure(audio)
            guard = pitch_guard(self_objective, audio)
            rms_ratio = float(np.sqrt(np.mean(audio * audio)) / max(np.sqrt(np.mean(baseline_part * baseline_part)), 1e-12))
            result = proposal | {"entry": replacement, "incremental_loss": self_loss,
                                 "independent_original_loss": original_loss, "pitch_guard": guard,
                                 "quality_window_s": list(window),
                                 "whole_phrase_rms_ratio_before_level_matching": rms_ratio}
            accepted = []
            for profile, limits in PROFILES.items():
                if (self_loss["loss"] <= limits["loss"]
                        and self_loss["carrier_pitch"] <= limits["carrier"]
                        and self_loss["envelope"] <= limits["envelope"]
                        and guard["carrier_shift_over_quarter_octave_fraction"] <= limits["large_pitch"]
                        and proposal["seam_error_codes"] <= limits["seam"]
                        and abs(rms_ratio - 1) <= limits["rms"]
                        and original_loss["carrier_pitch"] <= original_baseline["carrier_pitch"] + limits["carrier"]
                        and original_loss["absolute_register"] <= original_baseline["absolute_register"] + limits["carrier"]
                        and original_loss["loss"] <= original_baseline["loss"] + limits["loss"]):
                    accepted.append(profile)
                    prior = choices[profile].get(instrument)
                    if prior is None or (result["saving_bytes"], -self_loss["loss"]) > (prior["saving_bytes"], -prior["incremental_loss"]["loss"]):
                        choices[profile][instrument] = result
            result["profiles_passing_numeric_guards"] = accepted
            evaluated.append(result)
        searches.append({"id": instrument, "status": "searched", "original_loop_start": entry["loop_start"],
                         "quality_window_s": list(window),
                         "original_loop_length": entry["loop_length"], "original_stored_bytes_including_marker": size(entry),
                         "baseline_vs_independent_original": original_baseline, "negative_controls": controls,
                         "evaluated_candidates": evaluated})
        print(json.dumps({"case": name, "instrument": instrument, "searched": len(evaluated),
                          "saving_by_profile": {p: choices[p].get(instrument, {}).get("saving_bytes", 0) for p in PROFILES}}), flush=True)
    # A loop that survives one short phrase can still erase motion during a
    # much longer sustained note later in the song. Require an additional
    # actual-note context before advertising the full-score memory reduction.
    context_cache = {}
    rejected_contexts = []
    for profile, selected in choices.items():
        limits = PROFILES[profile]
        for instrument, chosen in list(selected.items()):
            window = held_context(arr, instrument)
            if window == tuple(chosen["quality_window_s"]):
                continue
            search = next(s for s in searches if s["id"] == instrument)
            alternatives = [c for c in search["evaluated_candidates"]
                            if profile in c["profiles_passing_numeric_guards"]]
            alternatives.sort(key=lambda c: (-c["saving_bytes"], c["incremental_loss"]["loss"]))
            del selected[instrument]
            for option in alternatives:
                key = (instrument, tuple(window), option["start"], option["length"])
                if key not in context_cache:
                    original_part = original_instrument(source, instrument, original_cache / sha(source), window)
                    baseline_part = render_instrument(arr, instrument, window=window)
                    candidate_part = render_instrument(arr, instrument, option["entry"], window=window)
                    if min(float(np.max(np.abs(original_part))), float(np.max(np.abs(baseline_part)))) < 1e-7:
                        context_cache[key] = {"window_s": list(window), "assessed": False}
                    else:
                        objective = SequenceLoss(baseline_part, RATE)
                        original_objective = SequenceLoss(original_part, RATE)
                        context_cache[key] = {"window_s": list(window), "assessed": True,
                                              "incremental_loss": objective.measure(candidate_part),
                                              "pitch_guard": pitch_guard(objective, candidate_part),
                                              "independent_original_baseline": original_objective.measure(baseline_part),
                                              "independent_original_candidate": original_objective.measure(candidate_part)}
                context = context_cache[key]
                option["longest_held_note_context"] = context
                accepted = context["assessed"]
                if accepted:
                    metric, guard = context["incremental_loss"], context["pitch_guard"]
                    old, new = context["independent_original_baseline"], context["independent_original_candidate"]
                    accepted = (metric["loss"] <= limits["loss"] and metric["carrier_pitch"] <= limits["carrier"]
                                and metric["envelope"] <= limits["envelope"]
                                and guard["carrier_shift_over_quarter_octave_fraction"] <= limits["large_pitch"]
                                and new["carrier_pitch"] <= old["carrier_pitch"] + limits["carrier"]
                                and new["absolute_register"] <= old["absolute_register"] + limits["carrier"]
                                and new["loss"] <= old["loss"] + limits["loss"])
                if accepted:
                    selected[instrument] = option
                    break
                rejected_contexts.append({"profile": profile, "instrument": instrument,
                                          "start": option["start"], "length": option["length"], "context": context})
    profiles = {}
    baseline_end = program_end(root)
    for profile, selected in choices.items():
        candidate = copy.deepcopy(arr)
        for entry in candidate["pcm_bank"]:
            if entry["id"] in selected:
                replacement = selected[entry["id"]]["entry"]
                entry.update(replacement)
                entry["loop_optimization"] = {"method": "offline_autocorrelation_window", "profile": profile,
                                              "source_bank": entries[entry["id"]]["data_file"],
                                              "listening_status": "unaccepted_lossy_candidate"}
        candidate["loop_optimization"] = {"profile": profile, "listening_status": "unaccepted_lossy_candidate",
                                          "notes_unchanged": True, "quality_passage_s": [30, 50]}
        target = out / profile
        target.mkdir(exist_ok=True)
        # Copy chosen banks into each candidate directory so a candidate does
        # not depend on temporary search ranking outputs being kept around.
        for entry in candidate["pcm_bank"]:
            if entry["id"] in selected:
                bank_path = target / f"sample-{entry['id']:02d}.bin"
                bank_path.write_bytes(Path(entry["data_file"]).read_bytes())
                entry["data_file"] = str(bank_path.resolve())
                entry["sha256"] = sha(bank_path)
        candidate_path = target / "arrangement.json"
        candidate_path.write_text(json.dumps(candidate, separators=(",", ":")) + "\n")
        candidate_dac, candidate_reference = expected_dac(short(candidate))
        audio = phrase((candidate_dac.astype(np.float64) - 8) / 8)
        incremental = baseline_objective.measure(audio)
        original_loss = independent_objective.measure(audio)
        saving = baseline_bytes - arrangement_size(candidate)
        sf.write(target / "offline-candidate-30-50.wav", audio, RATE, subtype="PCM_16")
        profiles[profile] = {"arrangement": str(candidate_path.resolve()), "arrangement_sha256": sha(candidate_path),
                             "sample_and_marker_bytes": arrangement_size(candidate), "saved_bytes": saving,
                             "saved_fraction": saving / baseline_bytes,
                             "changed_instruments": sorted(selected),
                             "incremental_whole_phrase": incremental,
                             "independent_original_whole_phrase": original_loss,
                             "original_loss_delta": original_loss["loss"] - baseline_original_loss["loss"],
                             "clipped_output_samples_first50": candidate_reference["clipped_output_samples"],
                             "program_end_estimate": baseline_end - saving if baseline_end else None,
                             "fits_resident_by_size_estimate": baseline_end - saving <= 0xd000 if baseline_end else None,
                             "listening_status": "not_accepted_offline_only"}
    report = {"case": name, "baseline_arrangement": str(arrangement_path.resolve()),
              "baseline_arrangement_sha256": sha(arrangement_path), "baseline_output_gain": arr.get("mixing", {}).get("output_gain", 1),
              "tool_sha256": sha(Path(__file__)), "model_sha256": sha(HERE / "pcm4_reference.py"),
              "objective_sha256": sha(HERE / "sequence_loss.py"), "quality_limits": PROFILES,
              "source_sha256": sha(source), "score_duration_s": arr["duration_s"],
              "baseline_sample_and_marker_bytes": baseline_bytes, "baseline_program_end": baseline_end,
              "baseline_vs_independent_original_whole_phrase": baseline_original_loss,
              "quality_passage_s": [30, 50], "profiles": profiles, "searches": searches,
              "rejected_longest_held_note_contexts": rejected_contexts,
              "scope": "Offline loop-only candidates. Existing score and IRQ unchanged; exact prefixes retained. Per-instrument and complete phrase measures use fixed times, absolute frequency, no octave folding, and one bounded global gain. Independent per-instrument targets use libopenmpt sample muting. Instruments silent in30–50s remain untouched. Numeric guards do not establish listening quality."}
    write_json(out / "report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results/optimization/loops")
    parser.add_argument("--case", choices=("all", "stardust", "hyperbased", "madness", "hyperbased-full", "madness-full"), default="all")
    parser.add_argument("--candidates", type=int, default=9)
    args = parser.parse_args()
    results = HERE / "results"
    cases = {
        "stardust": (results / "pcm4-clean", results / "reference/original.wav", None),
        "hyperbased": (results / "more-mods/hyperbased/diagnosis/gain3", results / "more-mods/hyperbased/original/original.wav", None),
        "madness": (results / "more-mods/note-banks-development/score-scope/4mats-madness", results / "more-mods/4mats-madness/original/original.wav", None),
        "hyperbased-full": (results / "more-mods/hyperbased/full", results / "more-mods/hyperbased/original/original.wav", 3.),
        "madness-full": (results / "more-mods/4mats-madness/full", results / "more-mods/4mats-madness/original/original.wav", 3.),
    }
    reports = []
    for name, (root, original, gain) in cases.items():
        if args.case not in ("all", name):
            continue
        report = study(name, root, original, args.out / name, args.candidates,
                       args.out / "independent-originals", gain)
        reports.append({k: report[k] for k in ("case", "score_duration_s", "baseline_sample_and_marker_bytes", "profiles")})
        print(json.dumps(reports[-1]), flush=True)
    write_json(args.out / (f"summary-{args.case}.json"), {"method": "loop_search", "cases": reports})


if __name__ == "__main__":
    main()
