"""Measured, conservative reuse of the accepted SID instrument templates.

This module does not choose channels, write libraries, synthesize audio or run
VICE. A recipe is an audition candidate, never a claim of matching the recorded
timbre. Unstable or octave-ambiguous instruments remain sample candidates.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.signal import correlate, find_peaks

HERE = Path(__file__).resolve().parent
PAULA = 3546894.6
CREAM = HERE / "instruments/cream-of-the-earth"
HYPER = HERE / "instruments/hyperbased"
ARPEGGIO = HERE / "instruments/hyperbased-full-sid/13-sid.json"


def _document(path: Path) -> dict:
    return json.loads(path.read_text())


def _provenance(path: Path) -> dict:
    return {"path": str(path.relative_to(HERE)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _approved(mod: dict, identifier: int) -> tuple[dict, Path] | None:
    for directory in (CREAM, HYPER, HERE / "instruments/hyperbased-full-sid"):
        manifest = _document(directory / "library.json")
        if manifest["source"]["sha256"] != mod.get("sha256"):
            continue
        for name in manifest["instruments"]:
            path = directory / name
            item = _document(path)
            if item["source_instrument"] == identifier:
                return item, path
    return None


def _measure(values: np.ndarray, name: str) -> dict:
    values = values.astype(np.float64)
    centered = values - values.mean()
    energy = float(centered @ centered)
    result = {"region": name, "samples": len(values),
              "rms": float(np.sqrt(np.mean(values * values))) / 128}
    if len(values) < 24 or energy < 1e-10:
        return result | {"acf": 0.0, "period_samples": None, "peaks": [],
                         "flatness": 0.0, "high_band_energy": 0.0, "half_period_acf": 0.0}
    acf = correlate(centered, centered, mode="full", method="fft")[len(values) - 1:]
    acf /= acf[0]
    candidates, _ = find_peaks(acf[4:min(1024, len(values) // 3)])
    candidates += 4
    if len(candidates):
        height = float(acf[candidates].max())
        # Prefer the first strong repetition, not a later multiple of it.
        selected = int(next(k for k in candidates if acf[k] >= max(.75, .92 * height))) \
            if height >= .75 else int(candidates[np.argmax(acf[candidates])])
        denominator = acf[selected - 1] - 2 * acf[selected] + acf[selected + 1]
        delta = .5 * (acf[selected - 1] - acf[selected + 1]) / denominator if denominator else 0.0
        period = selected + float(delta)
        confidence = float(acf[selected])
    else:
        period, confidence = None, 0.0
    size = max(16384, 1 << (len(values) - 1).bit_length())
    spectrum = np.abs(np.fft.rfft(centered * np.hanning(len(values)), size))
    power = spectrum * spectrum
    frequencies = np.fft.rfftfreq(size)
    low = max(1 / 1024, 3 / len(values))
    indices, _ = find_peaks(spectrum)
    indices = [int(k) for k in indices if low <= frequencies[k] <= .45]
    indices.sort(key=lambda k: spectrum[k], reverse=True)
    maximum = float(spectrum.max())
    peaks = [{"frequency": float(frequencies[k]),
              "amplitude": float(spectrum[k] / maximum)} for k in indices[:48]]
    valid = frequencies >= low
    half = max(4, round(period / 2)) if period is not None else 4
    result.update(period_samples=period, acf=confidence, peaks=peaks,
                  half_period_acf=float(max(acf[half - 1:half + 2])) if period is not None else 0.0,
                  flatness=float(np.exp(np.mean(np.log(power[valid] + 1e-30))) / np.mean(power[valid])),
                  high_band_energy=float(power[frequencies >= .18].sum() / power.sum()))
    return result


def _chord(region: dict) -> dict | None:
    # A chord's common repeat period is often four or six times its audible
    # root. Find independent spectral tones before interpreting the ACF peak.
    if region["acf"] < .55 or region["flatness"] > .03:
        return None
    salient = [p for p in region["peaks"] if p["amplitude"] >= .20]
    if len(salient) < 3:
        return None
    lowest = min(p["frequency"] for p in salient)
    roots = [p for p in salient if p["frequency"] <= lowest * 2 ** (45 / 1200)]
    root = sum(p["frequency"] * p["amplitude"] ** 2 for p in roots) / sum(p["amplitude"] ** 2 for p in roots)
    if root > .125:
        return None
    alternatives = []
    for semitones in ((0, 3, 7), (0, 4, 7), (0, 5, 7)):
        matches = []
        for note in semitones:
            target = root * 2 ** (note / 12)
            near = [p for p in salient if abs(1200 * math.log2(p["frequency"] / target)) <= 45]
            if not near:
                break
            matches.append(max(near, key=lambda p: p["amplitude"]))
        if len(matches) == 3:
            strength = min(p["amplitude"] for p in matches)
            alternatives.append((strength, semitones, matches))
    if not alternatives:
        return None
    _, semitones, matches = max(alternatives, key=lambda item: item[0])
    return {"period_samples": 1 / root, "semitones": list(semitones),
            "measured_semitones": [0.0] + [12 * math.log2(p["frequency"] / root) for p in matches[1:]]}


def _analysis(sample: dict, reference_period: int) -> dict:
    raw = np.frombuffer(sample["data"], np.int8).astype(np.float64)
    base = {"original_bytes": len(raw), "loop_start": sample["loop_start"],
            "loop_length": sample["loop_length"], "reference_period": reference_period,
            "reference_source_rate_hz": PAULA / reference_period,
            "sample_sha256": hashlib.sha256(sample["data"]).hexdigest()}
    if not len(raw) or np.std(raw) < 1e-8:
        return base | {"classification": "silence", "confidence": "high", "regions": [],
                       "reason": "Empty or constant source data has no measured pitched content"}
    regions = [_measure(raw[:8192], "attack")]
    if len(raw) > 1024:
        count = min(4096, len(raw) // 2)
        middle = (len(raw) - count) // 2
        regions.append(_measure(raw[middle:middle + count], "body"))
    if sample["loop_length"] > 2:
        loop = raw[sample["loop_start"]:sample["loop_start"] + sample["loop_length"]]
        if len(loop):
            loop = np.tile(loop, math.ceil(8192 / len(loop)))[:8192]
            regions.append(_measure(loop, "loop"))
    elif len(raw) > 8192:
        regions.append(_measure(raw[-4096:], "tail"))
    weights = raw * raw
    energy = np.cumsum(weights)
    q99 = int(np.searchsorted(energy, .99 * energy[-1])) + 1
    base.update(regions=regions, energy_99_source_samples=q99,
                energy_99_duration_s=q99 * reference_period / PAULA)
    measured_chords = [_chord(region) for region in regions]
    chords = [chord for chord in measured_chords if chord is not None]
    if len(chords) >= 2 and len({tuple(c["semitones"]) for c in chords}) == 1:
        periods = [c["period_samples"] for c in chords]
        spread = 1200 * math.log2(max(periods) / min(periods))
        if spread <= 45:
            return base | {"classification": "chord", "confidence": "high",
                           "root_period_samples": float(np.median(periods)),
                           "semitones": chords[0]["semitones"], "chord_regions": chords,
                           "unresolved_chord_regions": [r["region"] for r, c in zip(regions, measured_chords) if c is None],
                           "root_spread_cents": spread,
                           "reason": "Three salient spectral tones form the same measured triad in at least two source regions; ACF common repetition was not used as the root"}
    active = [r for r in regions if r["rms"] > max(v["rms"] for v in regions) * .1]
    if active and all(r["acf"] < .55 and r["flatness"] >= .065 for r in active):
        return base | {"classification": "noise", "confidence": "high",
                       "high_band_energy": float(np.mean([r["high_band_energy"] for r in active])),
                       "reason": "Broad spectrum and no strong stable repetition in the source regions"}
    tonal = [r for r in active if r["period_samples"] is not None and r["acf"] >= .75]
    if len(tonal) == len(active) and tonal:
        periods = [r["period_samples"] for r in tonal]
        spread = 1200 * math.log2(max(periods) / min(periods))
        period = float(np.median(periods))
        fundamental = 1 / period
        strengths = [max((p["amplitude"] for p in r["peaks"]
                          if abs(1200 * math.log2(p["frequency"] / fundamental)) < 70), default=0)
                     for r in tonal]
        second = [max((p["amplitude"] for p in r["peaks"]
                       if abs(1200 * math.log2(p["frequency"] / (2 * fundamental))) < 70), default=0)
                  for r in tonal]
        octave_ambiguous = any(s > 2 * f and r["half_period_acf"] >= .45
                               for r, f, s in zip(tonal, strengths, second))
        if spread <= 45 and min(strengths) >= .15 and not octave_ambiguous:
            return base | {"classification": "tonal", "confidence": "high",
                           "root_period_samples": period, "root_spread_cents": spread,
                           "reason": "Consistent strong ACF repetition with independent spectral energy at that fundamental"}
        return base | {"classification": "complex", "confidence": "low",
                       "candidate_period_samples": period, "root_spread_cents": spread,
                       "reason": "Missing/ambiguous fundamental or changing repetition; do not force an octave or flatten the recorded timbre"}
    # A falling low-frequency resonance suggests a drum, but cannot safely
    # supply an arbitrary fixed root or sweep from a broad, short spectrum.
    dominant = [max(r["peaks"], key=lambda p: p["amplitude"])["frequency"]
                for r in active if r["peaks"]]
    swept = len(dominant) > 1 and max(dominant) < .05 and max(dominant) > min(dominant) * 1.4
    return base | {"classification": "drum" if swept else "complex", "confidence": "low",
                   "suggested_template": "01-kick.json" if swept else None,
                   "reason": "Swept low body needs explicit calibration" if swept else
                             "No unambiguous monophonic root, noise class or clear triad; keep sampled until reviewed"}


def recipe_for_instrument(mod: dict, instrument_id: int, *, preserve_approved: bool = True,
                          reference_period: int = 428) -> dict:
    """Return ``{"recipe": dict | None, "analysis": dict}``, without mutation.

    Source identity selects accepted recipes before any inferred replacement.
    A ``None`` recipe deliberately asks the caller to keep this source sampled
    or review it. Pitch confidence does not establish timbral listening quality.
    ``reference_period`` declares the source-rate basis of percussion durations.
    """
    if type(instrument_id) is not int or not 1 <= instrument_id <= len(mod["samples"]):
        raise ValueError("Instrument ID is outside the source sample list")
    if type(reference_period) is not int or reference_period <= 0:
        raise ValueError("reference_period must be a positive source MOD period")
    sample = mod["samples"][instrument_id - 1]
    analysis = _analysis(sample, reference_period)
    analysis.update(source_instrument=instrument_id, source_sha256=mod.get("sha256"),
                    listening_status="unreviewed", recommendation="sample",
                    scope="Source measurements and existing-template audition proposal. Recorded envelope, filtering, polyphony and timbre are not reproduced exactly; no channel choice or audio-quality acceptance.")
    known = _approved(mod, instrument_id) if preserve_approved else None
    if known:
        recipe, path = known
        analysis.update(decision="preserved_approved", confidence="approved_recipe",
                        template=_provenance(path), overrides={},
                        recommendation=recipe.get("kind", "sid"))
        if recipe.get("program") in {"pulse", "triangle"}:
            from build_mod_hybrid import melody_pitch
            analysis["approved_pitch"] = melody_pitch(mod, recipe)
            analysis["root_period_samples"] = analysis["approved_pitch"]["source_period_samples"]
        elif recipe.get("program") == "arpeggio":
            analysis.update(root_period_samples=recipe["source_period_samples"],
                            semitones=copy.deepcopy(recipe["semitones"]))
        return {"recipe": copy.deepcopy(recipe), "analysis": analysis}
    classification = analysis["classification"]
    if analysis["confidence"] != "high" or classification == "silence":
        analysis["decision"] = "keep_sampled"
        return {"recipe": None, "analysis": analysis}
    if classification == "chord":
        path = ARPEGGIO
        recipe = _document(path)
        recipe.update(source_period_samples=analysis["root_period_samples"],
                      semitones=analysis["semitones"], kind="sid", sustain=1, pulse_width=1966)
        analysis["tradeoff"] = "A single SID voice arpeggiates the measured triad; simultaneous recorded chord tones and chorus are lost"
    elif classification == "tonal":
        path = CREAM / "10-pulse-melody.json"
        recipe = _document(path)
        period = analysis["root_period_samples"]
        recipe["pitch_analysis"] = {"sample_count": 8192, "upsample": 8,
            "period_band_samples": [max(1, math.floor(period * .92)), math.ceil(period * 1.08)],
            "minimum_autocorrelation": .75, "region": "loop_if_present"}
        from build_mod_hybrid import melody_pitch
        try:
            analysis["pitch_calibration"] = melody_pitch(mod, recipe | {"source_instrument": instrument_id})
        except ValueError as error:
            analysis.update(confidence="low", decision="keep_sampled", reason=str(error))
            return {"recipe": None, "analysis": analysis}
        analysis["root_period_samples"] = analysis["pitch_calibration"]["source_period_samples"]
        analysis["tradeoff"] = "Accepted pulse waveform and quiet fixed sustain; source envelope, filtering and harmonic balance are approximated"
    else:
        path = CREAM / ("06-hi-hat.json" if analysis["high_band_energy"] > .5 else "04-snare.json")
        recipe = _document(path)
        recipe["duration_s"] = max(.02, math.ceil(analysis["energy_99_duration_s"] / .02) * .02)
        analysis["tradeoff"] = "Accepted SID noise recipe with a source-energy duration cap; source spectral coloring and continuous decay are approximated"
    recipe.update(source_instrument=instrument_id, name=f"Instrument {instrument_id}: measured {classification} audition",
                  description=analysis["tradeoff"])
    template = _document(path)
    analysis.update(template=_provenance(path),
                    overrides={key: copy.deepcopy(value) for key, value in recipe.items() if template.get(key) != value},
                    decision="template_audition", recommendation="sid")
    return {"recipe": recipe, "analysis": analysis}
