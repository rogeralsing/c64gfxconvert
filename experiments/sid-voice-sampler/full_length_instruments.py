"""Reusable instruments and an explicit, approximate full Hyperbased arrangement.

This is data preparation for the native player, not an audio renderer.  Four
independent tracker channels are considered before allocating two SID programs,
one software triangle and one integer-cursor sample lane.  The immutable twenty
second proof remains a separate listening reference.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
from scipy.signal import resample_poly

import native_support as support
from full_sid_score import SourceCursor, prepare_full_sid
from sid_pitch import melody_pitch
import full_length_sid

HERE = Path(__file__).resolve().parent
CLOCK, PERIOD, PAULA = support.CLOCK, support.PERIOD, support.PAULA
RATE = CLOCK / PERIOD
CENTER, SCALE, BASS_CENTER = 113, 90, 15
DRUMS = {2, 3, 4, 5, 6, 9, 10}
CHORDS = {12: (0, 4, 7), 13: (0, 3, 7), 15: (0, 5, 9), 16: (0, 3, 8)}
LEADS = {7, 14, 23, 24}
BASSES = {1, 8}
SPECIAL = {17, 18, 19, 20, 21, 22}
NAMES = {1: "longbase", 2: "bassdrum", 3: "snare", 4: "hihat", 5: "wood",
         6: "lightwood", 7: "lead", 8: "base", 9: "snare2", 10: "clap",
         11: "orch-hit", 12: "accdur", 13: "accmol", 14: "lead2", 15: "acc3",
         16: "acc4", 17: "munjiga1", 18: "munjiga2", 19: "munjiga3",
         20: "munjiga4", 21: "wilde thing", 22: "another drop", 23: "lead3", 24: "lead4"}


def _instrument_metadata() -> dict[int, dict]:
    result = {}
    for path in sorted((HERE / "native_instruments/hyperbased_full").glob("*.asm")):
        fields = {key: int(value) for key, value in re.findall(
            r"\.label\s+(\w+)\s*=\s*(\d+)", path.read_text())}
        result[fields["sourceInstrument"]] = fields
    if set(result) != set(range(1, 25)):
        raise ValueError("Expected one explicit reusable declaration for every Hyperbased instrument")
    return result


PROGRAMS = _instrument_metadata()


def _roots(mod: dict) -> dict[int, float]:
    result = {}
    for identifier in (1, 7):
        preset = json.loads((HERE / f"instruments/hyperbased-mix/{identifier:02d}-sid.json").read_text())
        result[identifier] = melody_pitch(mod, preset)["source_period_samples"]
    for identifier, band in {8: (130, 155), 14: (27, 37), 23: (28, 36), 24: (28, 36)}.items():
        result[identifier] = melody_pitch(mod, {
            "source_instrument": identifier, "program": "pulse",
            "pitch_analysis": {"sample_count": 8192, "upsample": 8,
                               "period_band_samples": band, "minimum_autocorrelation": .1}})["source_period_samples"]
    result.update({12: 63.12183017342965, 13: 63.27907454135963,
                   15: 63.1, 16: 63.1})
    # These short effect samples have no claimed stable monophonic root.  A
    # measured strongest attack partial drives a deliberately approximate sweep.
    for identifier in SPECIAL:
        raw = np.frombuffer(mod["samples"][identifier - 1]["data"], np.int8).astype(float)
        count = min(len(raw), 4096)
        spectrum = abs(np.fft.rfft((raw[:count] - raw[:count].mean()) * np.hanning(count), 8192))
        low, high = math.ceil(8192 / 300), math.floor(8192 / 8)
        peak = low + int(np.argmax(spectrum[low:high]))
        result[identifier] = 8192 / peak
    return result


def prepare(out: Path, *, compact_drums: bool = True,
            orch_gain_families: bool = True,
            use_native_pcm_gain: bool = True) -> dict:
    """Return semantic 24-byte records, reusable PCM banks and triangle pages.

    Row14 is a triangle page index. Row16 is a PCM asset ID;17..21 are
    placeholders for linked exclusive-end and loop pointers. Reset flags15/22
    are explicit on every tick. All other fields persist in the native decoder.
    """
    out = Path(out).resolve(); out.mkdir(parents=True, exist_ok=True)
    source = json.loads((HERE.parent / "mod-hybrid/sources/hyperbased.source.json").read_text())
    source = dict(source, title_slug="hyperbased")
    mod = support.source_mod(source, out)
    ticks = support.build_timeline(mod)["ticks"]
    if len(ticks) != 16692 or any(abs(t["duration_s"] - .02) > 1e-9 for t in ticks):
        raise ValueError("Expected the pinned complete 50Hz Hyperbased traversal")
    original_source_ticks = len(ticks)
    # The chosen performance ends at3:00. Select it before compiling reusable
    # instruments and note data; the pinned original traversal is still checked.
    ticks = ticks[:9000]
    roots = _roots(mod)
    sid_compiler = full_length_sid.Compiler(roots, PROGRAMS)
    accepted = prepare_full_sid(mod, ticks[:1000], out / "accepted-prefix")["rows"]
    cuts = [(i * CLOCK + PERIOD * 25) // (PERIOD * 50) for i in range(len(ticks) + 1)]
    counts = np.diff(cuts).astype(int).tolist()
    cursors = [SourceCursor(mod) for _ in range(4)]
    onset = [0.0] * 4; trigger_index = [0] * 4
    trigger_gain = [0] * 4
    effective, levels, ages, note_ages, onset_gains = [], [], [], [], []
    for index, tick in enumerate(ticks):
        ids, rms, age, note_age = [], [], [], []
        for channel, cursor in enumerate(cursors):
            state = tick["channels"][channel]
            if state["trigger"]:
                onset[channel] = tick["time_s"]; trigger_index[channel] = index
                trigger_gain[channel] = state["volume"]
            identifier, block = cursor.tick(state, tick["duration_s"])
            ids.append(identifier); rms.append(float(np.sqrt(np.mean(block * block))))
            age.append(tick["time_s"] - onset[channel]); note_age.append(index - trigger_index[channel])
        effective.append(ids); levels.append(rms); ages.append(age); note_ages.append(note_age)
        onset_gains.append(trigger_gain.copy())

    # Keep each early accepted bass gain exactly; later source gains map to this
    # small declared set rather than allocating 65 pages.
    early_volumes = sorted({ticks[i]["channels"][0]["volume"] for i in range(1000)})
    volumes = sorted(set(early_volumes + [0, 16, 32, 48, 64]))
    triangle_pages = []
    q = np.arange(256) // 8; triangle = np.where(q < 16, q, 31 - q)
    for volume in volumes:
        triangle_pages.append(np.rint(15 + (2 * triangle - 15) * volume / 64).astype(np.uint8).tobytes())
    triangle_index = {volume: i for i, volume in enumerate(volumes)}

    assets = [{"id": 0, "instrument": 0, "period": 0, "gain": 0,
               "data": bytes([CENTER] * 313), "logical_bytes": 157, "loop_offset": 0}]
    asset_map = {}
    periodic_cycle = None
    routes, omissions, represented = [], [], Counter()
    semantic, score_semantic, pcm_previous, triangle_previous = [], [], None, None
    sid_previous = [None, None]

    def bank(identifier: int, period: int, gain: int = 64) -> int:
        nonlocal periodic_cycle
        key = identifier, period, gain
        if key in asset_map:
            return asset_map[key]
        sample = mod["samples"][identifier - 1]
        if identifier == 23:
            # A reusable short actual-waveform sustain is appropriate for this
            # exceptionally stable source. One complete source loop averages
            # away its detuning/attack: this is an explicit timbre approximation.
            if periodic_cycle is None:
                raw = np.frombuffer(sample["data"], np.int8).astype(float) / 128
                raw = raw[sample["loop_start"]:sample["loop_start"] + sample["loop_length"]]
                root = roots[23]
                phase = np.arange(256) * root / 256
                cycles = max(1, int(len(raw) / root) - 1)
                periodic_cycle = np.mean([np.interp(j * root + phase, np.arange(len(raw)), raw)
                                          for j in range(cycles)], axis=0)
                periodic_cycle -= periodic_cycle.mean()
            target = PAULA / period / roots[23]
            choices = []
            for length in range(157, 261):
                cycles = max(1, round(target * length / RATE))
                actual = RATE * cycles / length
                error = 1200 * math.log2(actual / target)
                choices.append((abs(error), length, cycles, error, actual))
            acceptable = [choice for choice in choices if choice[0] <= 3]
            error_abs, length, cycles, error, actual = min(acceptable, key=lambda c: c[1]) if acceptable else min(choices)
            phases = (np.arange(length) * cycles / length % 1) * 256
            wave = np.interp(phases, np.arange(257), np.r_[periodic_cycle, periodic_cycle[0]])
            values = np.rint(CENTER + wave * 60).astype(np.uint8).tobytes()
            content = values[:1] + values
            identifier_out = len(assets)
            assets.append({"id": identifier_out, "instrument": identifier, "period": period,
                           "gain": 64, "data": content + (values * 2)[:156],
                           "logical_bytes": len(content), "loop_offset": 1,
                           "source_sha256": hashlib.sha256(sample["data"]).hexdigest(),
                           "kind": "actual-waveform averaged periodic sustain",
                           "loop_bytes": length, "cycles_per_loop": cycles,
                           "pitch_error_cents": error, "frequency_hz": actual,
                           "source_gain_policy": "native-shift16/32/64"})
            asset_map[key] = identifier_out
            return identifier_out
        ratio = Fraction(RATE * period / PAULA).limit_denominator(4096)
        raw = np.frombuffer(sample["data"], np.int8).astype(float) / 128
        wave = resample_poly(raw, ratio.numerator, ratio.denominator)
        duration = len(wave) / RATE
        if identifier == 11 and orch_gain_families and not use_native_pcm_gain and gain < 64:
            duration = .16 if gain == 32 else .10
            wave = wave[:round(duration * RATE)].copy()
            if len(wave):
                fade = min(len(wave), round(.005 * RATE))
                wave[-fade:] *= np.linspace(1, 0, fade)
        scale = 60 if identifier == 11 else SCALE
        values = np.rint(CENTER + wave * scale * gain / 64).astype(int)
        if values.min(initial=CENTER) < 0 or values.max(initial=CENTER) + 30 > 255:
            raise ValueError("PCM attack exceeds native linear mix headroom")
        data = values.astype(np.uint8).tobytes()
        identifier_out = len(assets)
        assets.append({"id": identifier_out, "instrument": identifier, "period": period,
                       "gain": gain, "data": data + bytes([CENTER] * 156),
                       "logical_bytes": len(data), "loop_offset": 0,
                       "source_sha256": hashlib.sha256(sample["data"]).hexdigest(),
                       "maximum_duration_s": duration,
                       "source_gain_policy": ("native-shift16/32/64" if use_native_pcm_gain else
                                              "onset16/32/64" if identifier == 11 and orch_gain_families else "fixed64"),
                       "resampling_ratio": [ratio.numerator, ratio.denominator]})
        asset_map[key] = identifier_out
        return identifier_out

    for index, tick in enumerate(ticks):
        states = tick["channels"]; ids = effective[index]
        active = {c for c in range(4) if states[c]["volume"] > 0 and levels[index][c] > .002}
        assigned, route = set(), {"tick": index, "time_s": tick["time_s"]}
        bass = (0 if index < 1000 else
                next((c for c in (0, 2, 3, 1) if c in active and ids[c] in BASSES), None))
        if bass is None:
            tri = [0, 0, triangle_index[0], 0]
        else:
            state, identifier = states[bass], ids[bass]
            source_volume = state["volume"]
            if index < 1000 and accepted[index][5] != 17:
                source_volume = 0
            volume = min(volumes, key=lambda v: abs(v - source_volume))
            step = round(PAULA / state["period"] / roots[identifier] / RATE * 65536)
            if not 0 < step < 65536:
                raise ValueError("Software triangle phase step out of range")
            negative_step = (-step) & 65535
            tri = [negative_step & 255, negative_step >> 8, triangle_index[volume],
                   int(state["trigger"] or triangle_previous != (bass, identifier))]
            triangle_previous = bass, identifier
            assigned.add(bass); route["triangle"] = bass + 1
        tonal = [c for c in (1, 0, 2, 3) if c in active - assigned and ids[c] != 11
                 and ids[c] not in DRUMS]
        sid_channels = ([1] + [c for c in tonal if c != 1])[:2] if index < 1000 else tonal[:2]
        # Actual orchestral hits always get the sample lane. Remaining PCM
        # candidates are ordinary percussion at their original pitch; rare slow
        # drums use a SID envelope rather than a long upsampled bank.
        pcm_candidates = [c for c in (2, 3, 1, 0) if c in active - assigned
                          and (ids[c] == 11 or (ids[c] in DRUMS and states[c]["period"] < 400))]
        if compact_drums:
            later = {(3, 214), (3, 226), (9, 269), (10, 143), (10, 160)}
            pcm_candidates = [c for c in pcm_candidates if (ids[c], states[c]["period"]) not in later]
        if orch_gain_families and not use_native_pcm_gain:
            pcm_candidates = [c for c in pcm_candidates if ids[c] != 11 or onset_gains[index][c] >= 8]
        pcm_channel = next((c for c in pcm_candidates if ids[c] == 11), None)
        if pcm_channel is None:
            pcm_channel = next((c for c in (3, 1, 2, 0) if c in pcm_candidates), None)
        if pcm_channel is None and 2 in tonal[2:] and ids[2] == 23:
            pcm_channel = 2
        if pcm_channel is not None:
            assigned.add(pcm_channel); route["pcm"] = pcm_channel + 1
        for c in (3, 1, 2, 0):
            if len(sid_channels) >= 2:
                break
            if c in active - assigned and c not in sid_channels and ids[c] in DRUMS:
                sid_channels.append(c)
        sid_rows, sid_descriptors, gate_flags = [], [], 0
        for physical in range(2):
            c = sid_channels[physical] if physical < len(sid_channels) else None
            if c is None:
                sid_rows += [0, 0, 0x19, 0, 8, 0]
                sid_descriptors += sid_compiler.descriptor(0, None)
                sid_previous[physical] = None
            else:
                assigned.add(c); route[f"sid{physical + 1}"] = c + 1
                exact = accepted[index][:3] if index < 1000 and physical == 0 and c == 1 else None
                sid_rows += [0] * 6
                sid_descriptors += sid_compiler.descriptor(
                    ids[c], states[c], active=(exact[2] != 25 if exact is not None else levels[index][c] > .002),
                    accepted_level=2 if exact is not None else None)
                identity = c, ids[c]
                if states[c]["trigger"] or sid_previous[physical] != identity:
                    gate_flags |= 1 << physical
                sid_previous[physical] = identity
        if pcm_channel is None:
            asset_id, reset = 0, int(pcm_previous is not None)
            pcm_previous = None
        else:
            c = pcm_channel; state = states[c]
            gain = 64
            if ids[c] == 11 and orch_gain_families and not use_native_pcm_gain:
                gain = min((16, 32, 64), key=lambda v: abs(v - onset_gains[index][c]))
            asset_id = bank(ids[c], state["period"], gain)
            identity = (c, ids[c], state["period"], trigger_index[c])
            reset = int(state["trigger"] or pcm_previous != identity)
            pcm_previous = identity
        shift = 0
        if use_native_pcm_gain and pcm_channel is not None:
            volume = states[pcm_channel]["volume"]
            shift = 3 if volume < 8 else {64: 0, 32: 1, 16: 2}[
                min((16, 32, 64), key=lambda v: abs(v - volume))]
        semantic.append(sid_rows + tri + [asset_id, 0, 0, 0, 0, 0, reset, gate_flags | (shift << 2)])
        score_semantic.append(sid_descriptors + semantic[-1][12:])
        for c in assigned:
            represented[(c + 1, ids[c])] += 1
        missed = active - assigned
        if missed:
            omissions.append({"tick": index, "channels": [c + 1 for c in sorted(missed)],
                              "instruments": [ids[c] for c in sorted(missed)]})
        routes.append(route)

    original_gate_flags = [row[23] & 3 for row in score_semantic]
    semantic = sid_compiler.physical(score_semantic, fix_retriggers=True)
    added_gate_flags = [row[23] & 3 ^ old for row, old in zip(score_semantic, original_gate_flags)]
    # Remove only a never-read suffix of an independently reused one-shot bank.
    # This is not a phrase/frame window: every hit still selects one common
    # instrument/pitch prefix and the native cursor reads it normally.
    max_read, position, active = Counter(), 0, False
    for row, count in zip(semantic, counts):
        asset = assets[row[16]]
        if row[22]:
            position, active = 0, True
        if not active:
            continue
        max_read[asset["id"]] = max(max_read[asset["id"]], min(asset["logical_bytes"], position + count))
        position += count
        if position >= asset["logical_bytes"]:
            if asset["loop_offset"]:
                position = asset["loop_offset"] + (position - asset["logical_bytes"]) % (asset["logical_bytes"] - asset["loop_offset"])
            else:
                active = False
    trim = []
    model = {"rows": semantic, "assets": assets, "triangle_pages": triangle_pages,
             "frame_sample_counts_exact": counts}
    before_trim = expected_input(model)
    for asset in assets:
        end = max_read[asset["id"]]
        if asset["id"] and not asset["loop_offset"] and 0 < end < asset["logical_bytes"]:
            trim.append({"asset": asset["id"], "instrument": asset["instrument"],
                         "period": asset["period"], "old_logical_bytes": asset["logical_bytes"],
                         "new_logical_bytes": end, "saved_bytes": asset["logical_bytes"] - end})
            asset["data"] = asset["data"][:end] + bytes([CENTER] * 156)
            asset["logical_bytes"] = end
    after_trim = expected_input(model)
    if before_trim != after_trim:
        raise ValueError("Unused-tail elimination changed the complete native sample model")
    bank_bytes = sum(len(asset["data"]) for asset in assets)
    report = {"source_sha256": mod["sha256"], "ticks": len(ticks), "duration_s": len(ticks) / 50,
              "original_source_ticks": original_source_ticks, "selected_ticks": len(ticks),
              "user_chosen_ending_s": 180,
              "native_rate_hz": RATE, "frame_sample_counts": dict(Counter(counts)),
              "envelope_gain_rise_retriggers": {"sid1": sum(bool(v & 1) for v in added_gate_flags),
                                                 "sid2": sum(bool(v & 2) for v in added_gate_flags),
                                                 "accepted_sid1_first1000_exempt": True},
              "pcm_bank_bytes_including_guards": bank_bytes,
              "unused_tail_elimination": {"saved_bytes": sum(t["saved_bytes"] for t in trim),
                                           "assets": trim, "complete_sample_stream_unchanged": True,
                                           "expected_input_sha256": hashlib.sha256(after_trim).hexdigest()},
              "triangle_bytes": len(triangle_pages) * 256, "triangle_source_volumes": volumes,
              "policy": {"compact_drums": compact_drums, "orch_gain_families": orch_gain_families,
                         "use_native_pcm_gain": use_native_pcm_gain},
              "measured_period_samples": roots, "omitted_active_channel_ticks": len(omissions),
              "omissions_by_channel": dict(Counter(c for r in omissions for c in r["channels"])),
              "represented_channel_instrument_ticks": {f"{c}:{i}": n for (c, i), n in represented.items()},
              "approximations": [
                  "Two native50Hz SID instrument programs compute waveform, pulse width and envelope stages from note descriptors; source chords use native three-note arpeggios.",
                  "Native percussion uses short octave pitch stages; lead23 has four pulse-width stages, lead14 switches waveform, and special effects use noise attacks plus two envelope reductions. Source pitch/portamento sets the base frequency.",
                  "Later SID gain rises or inactive-to-active transitions retrigger the envelope and intentionally reset that native instrument age; accepted SID1 first1000ticks remain exempt.",
                  "Source1 keeps accepted triangle quantization and source2 keeps accepted pulse register fields in the first20s when routed.",
                  "Source8 bass uses a measured-root triangle, not its actual attack/filter recording.",
                  "Actual orchestral hit attacks use reused fixed-pitch samples; no rejected single-partial flute.",
                  "Every PCM waveform is stored atgain64; native-shift source-gain behavior is declared below. Original percussion/orchestral tails are retained.",
                  "Triangle gains outside early accepted values map to the nearest declared table.",
                  "More than two simultaneous tonal parts can omit the third-priority tonal source; all omissions are enumerated.",
                  "Rare percussion below original sampling rate (period>=400) uses a SID percussion program."],
              "digital_scope": "Host arrangement and independent instrument assets only; native playback and listening fidelity require separate VICE proof."}
    if use_native_pcm_gain:
        report["approximations"].append("Native PCM shifts replay per-tick source gain quantized to64/32/16; source gains below8 mute while the cursor advances. Every pitch has one full-length waveform. Shift recentering constants are0/57/85 for113-centred codes.")
    elif orch_gain_families:
        report["approximations"].append("Orch11 onset gain maps to16/32/64, onset gains below8 are omitted; quiet and medium reusable hits retain100/160ms with5ms asset fades. Held source-volume automation is not replayed.")
    if compact_drums:
        report["approximations"].append("Later snare3 periods214/226, snare9 period269 and clap10 periods143/160 use SID percussion to preserve memory for actual orchestral attacks.")
    periodic = [a for a in assets if a["instrument"] == 23]
    report["periodic_c3_lead"] = {"assets": len(periodic),
                                   "bytes_including_guards": sum(len(a["data"]) for a in periodic),
                                   "maximum_pitch_error_cents": max((abs(a["pitch_error_cents"]) for a in periodic), default=0)}
    if periodic:
        report["approximations"].append("Otherwise-unassigned C3lead23 uses averaged original-waveform periodic sustains, not a complete source attack. Pitch changes retrigger the short bank; loops contain an integer number of cycles and are at least157bytes.")
    for asset in assets:
        filename = f"pcm-{asset['id']:03d}.bin"
        (out / filename).write_bytes(asset["data"])
        asset["file"] = str(out / filename)
    for i, page in enumerate(triangle_pages):
        (out / f"triangle-{i:02d}.bin").write_bytes(page)
    (out / "semantic-rows.bin").write_bytes(bytes(value for row in semantic for value in row))
    (out / "score-rows.bin").write_bytes(bytes(value for row in score_semantic for value in row))
    support.save(out / "report.json", report)
    support.save(out / "routing.json", {"routes": routes, "omissions": omissions})
    support.save(out / "assets.json", {"assets": [{k: v for k, v in a.items() if k != "data"} for a in assets],
                                               "triangle_volumes": volumes})
    # The native program source is emitted after descriptor data so the score
    # compressor can inspect it while assembly work is being validated.
    sid_programs_asm = sid_compiler.emit(out)
    return {"rows": semantic, "score_rows": score_semantic,
            "sid_programs_asm": sid_programs_asm,
            "assets": assets, "triangle_pages": triangle_pages,
            "triangle_silence_index": triangle_index[0], "ticks": ticks,
            "frame_sample_counts_exact": counts, "source": source, "report": report}


def expected_input(prepared: dict) -> bytes:
    """Independent integer phase/cursor model of every intended SID3 input."""
    phase, position, previous_id = 0, 0, None
    output = bytearray()
    for row, count in zip(prepared["rows"], prepared["frame_sample_counts_exact"]):
        step = row[12] | row[13] << 8
        if row[15]:
            phase = 0
        asset = prepared["assets"][row[16]]
        if row[22]:
            position = 0
        elif previous_id != asset["id"] and previous_id is None:
            position = 0
        page = prepared["triangle_pages"][row[14]]
        for _ in range(count):
            phase = (phase + step) & 65535
            pcm = asset["data"][position] if position < len(asset["data"]) else CENTER
            shift = row[23] >> 2 & 3
            if shift == 3:
                pcm = CENTER
            elif shift == 1:
                pcm = (pcm >> 1) + (pcm & 1) + 56
            elif shift == 2:
                pcm = (pcm >> 2) + ((pcm >> 1) & 1) + 85
            value = page[phase >> 8] + pcm
            if value > 255:
                raise ValueError("Independent phase model found mix overflow")
            output.append(value); position += 1
        if position >= asset["logical_bytes"]:
            if asset["loop_offset"]:
                position = asset["loop_offset"] + (position - asset["logical_bytes"]) % (asset["logical_bytes"] - asset["loop_offset"])
            else:
                position = asset["logical_bytes"]
        previous_id = asset["id"]
    return bytes(output)
