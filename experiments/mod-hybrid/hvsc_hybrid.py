"""Audition extracted HVSC instruments on one complete Guitar Slinger phrase.

Two real SID voices replace the pulse melody and its echo. Guitar chords and
bass remain independent, reusable MOD samples. Final audio comes only from the
C64 program in VICE, using the project's single digiboost profile.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from scipy.signal import stft

from build_c64 import build, verify_raw_sid_trace
from channel_resid import make_digiboost_sid
from mod_reader import load_mod
from pcm4_prepare import prepare
from reference import render_timeline_pcm
from run_vice import capture
from timeline import build_timeline
from vice_profile import PAL_CLOCK, PROFILE, RATE


HERE = Path(__file__).resolve().parent
OUT = HERE / "results/rebuild/hvsc-hybrid"
SOURCE_START, SOURCE_END = 5.50, 14.46
SID_TRACKS, PCM_TRACKS = (0, 2), (1, 3)
HYBRID_SID_SUSTAIN = 0.4


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def target() -> tuple[dict, list[dict], float, dict]:
    source = HERE / "sources/guitar-slinger.mod"
    mod = load_mod(source)
    timeline = build_timeline(mod)
    ticks = [t for t in timeline["ticks"]
             if SOURCE_START - 1e-7 <= t["time_s"] < SOURCE_END - 1e-7]
    if len(ticks) != 448 or any(abs(t["duration_s"] - .02) > 1e-8 for t in ticks):
        raise ValueError("Expected the complete 448-tick first melody pattern")
    sample = mod["samples"][8]
    raw = np.frombuffer(sample["data"], dtype=np.int8).astype(np.float64) / 128
    loop = raw[sample["loop_start"]:sample["loop_start"] + sample["loop_length"]]
    # A long repeating loop supports an interpolated autocorrelation estimate.
    # Restrict to the first strong period, avoiding octave/subharmonic guesses.
    acf = np.correlate(loop - loop.mean(), loop - loop.mean(), mode="full")[len(loop) - 1:]
    acf /= np.arange(len(loop), 0, -1)
    candidates = [i for i in range(8, min(128, len(acf) - 1))
                  if acf[i] > acf[i - 1] and acf[i] >= acf[i + 1]]
    peak = next(i for i in candidates if acf[i] >= .85 * max(acf[j] for j in candidates))
    correction = .5 * (acf[peak - 1] - acf[peak + 1]) / (
        acf[peak - 1] - 2 * acf[peak] + acf[peak + 1])
    period = peak + correction
    cycles = 1 / period
    if not 31 < period < 32:
        raise ValueError(f"Unexpected pulse sample fundamental: {period}")
    for tick in ticks:
        for ch in SID_TRACKS:
            s = tick["channels"][ch]
            if s["volume"] and s["playing_sample"] != 9:
                raise ValueError("This phrase contains another audible SID-track instrument")
    return mod, ticks, cycles, {"instrument": 9, "period_source_samples": period,
                              "cycles_per_sample": cycles, "method": "First strong autocorrelation peak of the original sample loop, parabolic interpolation"}


def macro_frame(patch: dict, age: float) -> dict:
    frames = []
    for frame in patch["frames"]:
        if not frame["control"] & 1 or frame["control"] & 8:
            break
        frames.append(frame)
    if not frames:
        raise ValueError("A reusable tonal macro must begin with its oscillator gated on")
    return next((f for f in reversed(frames) if f["time_s"] <= age + 1e-8), frames[0])


def sid_program(patch: dict, ticks: list[dict], track: int, cycles: float,
                sustain_scale: float = 1.0) -> list[list[list[int]]]:
    """Adapt observed waveform/pulse/ADSR state to the MOD's pitch and gate times.

    Source note lengths and source melody are not replayed. Control is sampled
    at the MOD's 50-Hz ticks, holding the last gated donor state. Sustain follows
    MOD volume; SID attack peaks cannot be independently volume-scaled.
    """
    result, registers, onset = [], [0] * 7, 0
    for index, tick in enumerate(ticks):
        state = tick["channels"][track]
        writes = []
        if state["trigger"]:
            onset = index
            writes.append([4, 8])
            registers[4] = 8
        frame = macro_frame(patch, (index - onset) / 50)
        frequency_hz = 3546894.6 / state["period"] * cycles if state["period"] else 0
        word = round(frequency_hz * frame["frequency_ratio"] * 2**24 / PAL_CLOCK)
        if not 0 <= word <= 65535:
            raise ValueError("Transposed SID frequency exceeds the oscillator register")
        control = frame["control"] if state["volume"] else frame["control"] & ~1
        sustain = min(15, round((frame["sr"] >> 4) * state["volume"] / 24 * sustain_scale))
        values = [word & 255, word >> 8, frame["pulse"] & 255,
                  frame["pulse"] >> 8, control, frame["ad"], sustain * 16 + (frame["sr"] & 15)]
        # Load pitch, pulse and envelope before the gate. Keep unchanged writes
        # out of the score, while retaining the deliberate gate-off/on edges.
        for register in (0, 1, 2, 3, 5, 6, 4):
            if index == 0 or state["trigger"] or values[register] != registers[register]:
                writes.append([register, values[register]])
                registers[register] = values[register]
        if index + 1 < len(ticks) and ticks[index + 1]["channels"][track]["trigger"]:
            # A full tick of release avoids the SID ADSR delay bug between
            # consecutive notes. This is an explicit reusable-player adaptation.
            for register, value in ((4, 8), (5, 0), (6, 0)):
                writes.append([register, value])
                registers[register] = value
        result.append(writes)
    return result


def render_program(program: list[list[list[int]]]) -> np.ndarray:
    sid = make_digiboost_sid(RATE)
    sid.write(24, 8)
    sid.clock(round(.1 * PAL_CLOCK))
    chunks, previous = [], 0
    for index, writes in enumerate(program):
        for register, value in writes:
            sid.write(register, value)
        cut = round((index + 1) * PAL_CLOCK / 50)
        chunks.append(np.asarray(sid.clock(cut - previous), dtype=np.float64) / 32768)
        previous = cut
    return np.concatenate(chunks)


def score_patch(patch: dict, ticks: list[dict], cycles: float, reference: np.ndarray) -> dict:
    # Rank a complete first note, including attack and tail, instead of a
    # single steady waveform. Final selected patches are checked over all notes.
    short_ticks = ticks[:84]
    candidate = render_program(sid_program(patch, short_ticks, SID_TRACKS[0], cycles))
    count = min(len(candidate), len(reference))
    a, b = reference[:count].copy(), candidate[:count].copy()
    a -= a.mean(); b -= b.mean()
    _, _, A = stft(a, RATE, nperseg=1024, noverlap=768)
    _, _, B = stft(b, RATE, nperseg=1024, noverlap=768)
    A, B = np.abs(A), np.abs(B)
    denominator = float(np.sum(B * B))
    gain = float(np.sum(A * B) / denominator) if denominator else 0
    loss = float(np.linalg.norm(A - gain * B) / np.linalg.norm(A))
    return {"patch_id": patch["id"], "author": patch["source"]["author"],
            "title": patch["source"]["title"], "spectral_error": loss,
            "analysis_gain": gain, "scope": "First complete 1.68-second melody note; gain-fitted native reSID magnitude spectrum, no phase alignment. Ranking is diagnostic, not listening approval."}


def arrangement(patch: dict, ticks: list[dict], cycles: float, pcm: dict, solo: bool) -> dict:
    selected = [t for t in pcm["ticks"]
                if SOURCE_START - 1e-7 <= t["time_s"] < SOURCE_END - 1e-7]
    if len(selected) != len(ticks):
        raise ValueError("Sample and tracker timelines disagree")
    sustain_scale = 1.0 if solo else HYBRID_SID_SUSTAIN
    programs = [sid_program(patch, ticks, track, cycles, sustain_scale) for track in SID_TRACKS]
    arranged = []
    used = set()
    banks = {b["id"]: copy.deepcopy(b) for b in pcm["pcm_bank"]}
    aliases = {}
    for index, (tick, prepared) in enumerate(zip(ticks, selected)):
        states = []
        for channel in PCM_TRACKS:
            state = copy.deepcopy(prepared["pcm"][channel])
            if state.get("loop_sample", state["sample"]) not in (0, state["sample"]):
                raise ValueError("This phrase requires an independent PCM loop-pointer update")
            if state.get("offset", 0) or state.get("offset_fraction", 0):
                bank = banks[state["sample"]]
                if state.get("offset_fraction", 0) or bank["loop_length"]:
                    raise ValueError("The first experiment supports only integer one-shot sample offsets")
                # The chord at source12.50 uses 9xx. Keep its remaining sample
                # as a reusable suffix; do not silently restart the full chord.
                key = state["sample"], state["offset"]
                if key not in aliases:
                    alias_id = max(banks) + 1
                    path = Path(bank["data_file"]).parent / f"offset-{key[0]}-{key[1]}.bin"
                    path.write_bytes(Path(bank["data_file"]).read_bytes()[state["offset"]:])
                    if not path.stat().st_size or alias_id > 31:
                        raise ValueError("Sample offset cannot fit the hybrid descriptor format")
                    banks[alias_id] = dict(bank, id=alias_id, data_file=str(path.resolve()),
                                          bytes=path.stat().st_size, sha256=sha(path),
                                          offset_source_instrument=key[0], offset_source_bank_index=key[1])
                    aliases[key] = alias_id
                state["sample"] = aliases[key]
            if solo:
                state["volume"] = 0
            used.add(state["sample"])
            states.append(state)
        sid = [{"writes": programs[voice][index] if not solo or voice == 0 else []}
               for voice in range(2)]
        arranged.append({"time_s": index / 50, "duration_s": .02,
                         "order": tick["order"], "row": tick["row"], "tick": tick["tick"],
                         "sid": sid, "pcm": states})
    return {"title": "Guitar Slinger / " + patch["source"]["author"],
            "raw_sid": True, "pcm_rate_hz": PAL_CLOCK / 256,
            "duration_s": len(arranged) / 50, "ticks": arranged,
            "mixing": {"output_gain": 3.0, "sid_sustain_scale": sustain_scale},
            "pcm_bank": [b for key, b in banks.items() if key in used],
            "source_range_s": [SOURCE_START, SOURCE_END], "donor_patch": patch,
            "adaptation": "Original donor waveform, pulse and AD; relative source macro pitch retuned to MOD sample fundamental. Sustain follows MOD volume relative to24. The combined hybrid attenuates SID sustain to leave room for the samples; solo/ranking programs retain the donor level. Original source note length replaced by MOD note timing; one-tick hard restart before triggers. Donor filter/sync/ring dependencies excluded. Attack peaks remain native SID behavior."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=OUT / "source-traces/catalog.json")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--capture", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    mod, ticks, cycles, pitch = target()
    # Recreate reusable sample banks through the current converter, without
    # changing any accepted sampled-only programs or recordings.
    prepare(HERE / "sources/guitar-slinger.mod", args.out / "pcm", seconds=50,
            bank_scope="score", protracker_loops=True)
    pcm = json.loads((args.out / "pcm/arrangement.json").read_text())
    reference_ticks = copy.deepcopy(ticks[:84])
    for index, tick in enumerate(reference_ticks):
        tick["time_s"] = index / 50
        for channel, state in enumerate(tick["channels"]):
            if channel != SID_TRACKS[0]:
                state["volume"] = 0
    reference = render_timeline_pcm(mod, {"ticks": reference_ticks, "duration_s": 1.68}, RATE)
    catalog = json.loads(args.catalog.read_text())
    if catalog.get("strict_note_boundaries") is not True:
        raise ValueError("Re-extract the HVSC catalog with strict donor-note boundaries")
    candidates = []
    for patch in catalog["patches"]:
        if patch.get("strict_note_boundaries") is not True:
            raise ValueError("A donor patch has not passed strict note-boundary extraction")
        if all(not value for value in patch["dependencies"].values()):
            candidates.append((score_patch(patch, ticks, cycles, reference), patch))
    candidates.sort(key=lambda item: item[0]["spectral_error"])
    selected = {}
    wanted = {"Jeroen Tel": "tel", "Chris Hülsbeck": "huelsbeck", "Martin Galway": "galway"}
    for score, patch in candidates:
        author = patch["source"]["author"]
        if author in wanted and wanted[author] not in selected:
            selected[wanted[author]] = (score, patch)
    if not all(name in selected for name in wanted.values()):
        raise ValueError(f"Need independent patches from Tel, Hülsbeck and Galway; found {list(selected)}")
    ranking = {"profile": dict(PROFILE), "target_pitch": pitch,
               "scores": [score for score, _ in candidates],
               "selected": {name: score for name, (score, _) in selected.items()}}
    (args.out / "ranking.json").write_text(json.dumps(ranking, indent=2) + "\n")
    records = []
    sustained = [name for name in selected if selected[name][1]["source_sustain"] > 0]
    if not sustained:
        raise ValueError("Hybrid lead and quieter echo require a donor with controllable sustain")
    winner = min(sustained, key=lambda name: selected[name][0]["spectral_error"])
    for name, (score, patch) in selected.items():
        modes = (True, False) if name == winner else (True,)
        for solo in modes:
            label = name + "-sid-melody" if solo else "hybrid"
            folder = args.out / label
            folder.mkdir(parents=True, exist_ok=True)
            source = folder / "arrangement.json"
            source.write_text(json.dumps(arrangement(patch, ticks, cycles, pcm, solo), separators=(",", ":")) + "\n")
            compiled = build(source, folder / "c64")
            record = {"name": label, "patch_id": patch["id"], "author": patch["source"]["author"],
                      "source_title": patch["source"]["title"], "source_subtune": patch["source_subtune"],
                      "source_voice": patch["source_voice"], "source_url": patch["source"]["source_url"],
                      "source_sid_sha256": patch["source"]["sha256"],
                      "source_onset_cycle": patch["source_onset_cycle"],
                      "program": str((folder / "c64/stardust.prg").resolve()),
                      "program_sha256": compiled["prg_sha256"], "seconds": len(ticks) / 50}
            if args.capture:
                receipt = capture(folder / "c64/stardust.prg", folder / "c64/stardust.sym", folder / "vice", len(ticks) / 50, "both")
                record["raw_sid_check"] = verify_raw_sid_trace(source, folder / "vice/capture.json")
                record["runtime"] = receipt["runtime"]
                audio = args.out / (label + ".wav")
                shutil.copyfile(folder / "vice/stardust-listening.wav", audio)
                record.update(audio=str(audio.resolve()), audio_sha256=sha(audio))
            records.append(record)
            print(f"{label}: built" + (" and captured" if args.capture else ""), flush=True)
    manifest = {"profile": dict(PROFILE), "source": "Guitar Slinger, Jogeir Liljedahl",
                "source_mod_sha256": mod["sha256"], "catalog_sha256": sha(args.catalog),
                "source_sha256": {name: sha(HERE / name) for name in
                    ("hvsc_hybrid.py", "hvsc_extract.py", "build_c64.py", "c64_player.asm",
                     "channel_resid.py", "channel_resid.cpp", "vice_profile.py")},
                "source_range_s": [SOURCE_START, SOURCE_END], "duration_s": len(ticks) / 50,
                "sid_tracks": [1, 3], "sample_tracks": [2, 4], "winner": winner,
                "records": records, "scope": "One complete pattern. SID instruments are adapted register programs, not sampled SID audio. Final listening WAVs are actual C64/VICE output; no host mixing."}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"winner": winner, "records": len(records)}, indent=2))


if __name__ == "__main__":
    main()
