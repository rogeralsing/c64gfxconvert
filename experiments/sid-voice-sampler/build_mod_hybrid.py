"""Add two quiet native SID parts to the accepted oscillator-sampled MOD bass.

This remains a bounded three-channel arrangement. MOD channel 2 stays sampled,
channel 3 becomes a pulse melody, and channel 4 becomes synthesized percussion.
The complex chord channel 1 and the parallel HVSC work are outside this test.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
from scipy.signal import correlate, resample_poly
import soundfile as sf

from instrument_library import DEFAULT_LIBRARY, load_library, receipt as library_receipt

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("accepted_mod_channel", HERE / "build_mod_channel.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
CLOCK, PERIOD, RATE = base.CLOCK, base.PERIOD, base.RATE


def accepted_identity() -> dict:
    base.reference_identity()
    solo = json.loads((HERE / "results/mod-channel/verification.json").read_text())
    wanted = {name: digest for name, digest in solo["source_sha256"].items()}
    for name, digest in wanted.items():
        if base.reference.digest(HERE / name) != digest:
            raise ValueError(f"Accepted solo source changed: {name}")
    artifacts = {"player.prg": solo["build"]["program_sha256"],
                 "mod-channel.wav": solo["audio"]["output_sha256"],
                 "expected-input.bin": solo["input"]["expected_input_sha256"]}
    for name, digest in artifacts.items():
        if base.reference.digest(HERE / "results/mod-channel" / name) != digest:
            raise ValueError(f"Accepted solo artifact changed: {name}")
    return {"source": wanted, "artifacts": artifacts}


def melody_pitch(mod: dict, instrument: dict) -> dict:
    sample = mod["samples"][instrument["source_instrument"] - 1]
    analysis = instrument["pitch_analysis"]
    count, upsample = analysis["sample_count"], analysis["upsample"]
    low, high = analysis["period_band_samples"]
    raw = np.frombuffer(sample["data"], np.int8).astype(float) / 128
    if sample["loop_length"] > 2 and analysis.get("region", "loop_if_present") != "attack":
        loop = raw[sample["loop_start"]:sample["loop_start"] + sample["loop_length"]]
        segment = np.tile(loop, math.ceil(count / len(loop)))[:count]
    else:
        segment = raw[:count]
    interpolated = resample_poly(segment - segment.mean(), upsample, 1)
    acf = correlate(interpolated, interpolated, mode="full", method="fft")[len(interpolated) - 1:]
    acf /= acf[0]
    peak = low * upsample + int(np.argmax(acf[low * upsample:high * upsample]))
    adjustment = .5 * (acf[peak - 1] - acf[peak + 1]) / (
        acf[peak - 1] - 2 * acf[peak] + acf[peak + 1])
    period = (peak + adjustment) / upsample
    if acf[peak] < analysis["minimum_autocorrelation"]:
        raise ValueError("Melody instrument has no sufficiently stable measured root")
    return {"instrument": instrument["source_instrument"], "source_period_samples": period,
            "cycles_per_source_sample": 1 / period, "autocorrelation": float(acf[peak]),
            "pulse_width": instrument.get("pulse_width", 2048),
            "method": f"Original instrument's first {count} samples (or repeating loop), {upsample}-fold interpolation, autocorrelation peak in the configured {low}–{high} sample period band; parabolic refinement.",
            "region": analysis.get("region", "loop_if_present"),
            "scope": f'A monophonic {instrument["program"]} approximation. The recorded source has a different envelope and may have pitch drift.'}


def synth_score(context: dict, library: dict) -> tuple[list[list[int]], dict]:
    mod, ticks = context["mod"], context["ticks"]
    instruments = library["instruments"]
    pulse = instruments[10]
    rest = pulse["rest_control"]  # Known triangle-zero level, TEST and gate; no full attack on notes.
    pitch = melody_pitch(mod, pulse)
    rows, drum_triggers = [], []
    all_ticks = base.build_timeline(mod)["ticks"]
    onset, position, current = -100.0, 0.0, 0
    raw = {i: np.frombuffer(mod["samples"][i - 1]["data"], np.int8).astype(float) / 128
           for i in range(1, 7)}
    peaks = {i: max(float(np.sqrt(np.mean(data[j:j + 256] ** 2)))
                    for j in range(0, len(data), 128)) for i, data in raw.items()}
    melody_raw = np.frombuffer(mod["samples"][9]["data"], np.int8).astype(float) / 128
    melody_peak = max(float(np.sqrt(np.mean(melody_raw[j:j + 256] ** 2)))
                      for j in range(0, len(melody_raw), 128))
    melody_position, melody_current = 0.0, 0
    # These are deliberately short SID percussion envelopes, not copied drum
    # recordings. Actual source triggers and source pitch determine their timing.
    for tick in all_ticks:
        if tick["time_s"] >= base.END - 1e-7:
            break
        melody = tick["channels"][2]
        if melody["trigger"]:
            melody_current, melody_position = melody["playing_sample"], float(melody.get("offset", 0))
        melody_active = False
        if melody_current == 10 and melody["period"]:
            advance = base.PAULA / melody["period"] * tick["duration_s"]
            indices = (melody_position + np.arange(max(1, round(advance)))).astype(int)
            valid = indices < len(melody_raw)
            block = np.zeros(len(indices)); block[valid] = melody_raw[indices[valid]]
            melody_active = melody["volume"] > 0 and float(np.sqrt(np.mean(block * block))) > melody_peak * pulse["rms_gate_ratio"]
            melody_position += advance
        drum = tick["channels"][3]
        instrument = drum["playing_sample"]
        if drum["trigger"]:
            if instrument not in raw or drum.get("offset", 0):
                raise ValueError("Unexpected percussion instrument or offset")
            onset, position, current = tick["time_s"], 0.0, instrument
        drum_frequency, drum_control = 0.0, rest
        if current and drum["period"]:
            preset = instruments[current]
            source_rate = base.PAULA / drum["period"]
            advance = source_rate * tick["duration_s"]
            indices = (position + np.arange(max(1, round(advance)))).astype(int)
            valid = indices < len(raw[current])
            block = np.zeros(len(indices)); block[valid] = raw[current][indices[valid]]
            rms = float(np.sqrt(np.mean(block * block)))
            age = tick["time_s"] - onset
            active = (drum["volume"] > 0 and age < preset["duration_s"] - 1e-8
                      and (rms > peaks[current] * preset["rms_gate_ratio"] or drum["trigger"]))
            if active:
                if (preset["program"] == "triangle-sweep" or
                        (preset["program"] == "noise-then-triangle-sweep"
                         and not age < preset["noise_duration_s"] - 1e-8)):
                    body = preset["base_hz"] * preset["reference_period"] / drum["period"]
                    drum_frequency = body * (1 + preset["sweep_depth"] * math.exp(-age / preset["sweep_decay_s"]))
                    drum_control = preset["triangle_control"]
                else:
                    # Noise LFSR advances on accumulator bit19 rising: sixteen
                    # shifts per oscillator cycle. Match its clock to Paula.
                    drum_frequency = source_rate / preset["noise_divisor"]
                    drum_control = preset["noise_control"]
            position += advance
        if tick["time_s"] < base.START - 1e-7:
            continue
        if melody["volume"] and melody["playing_sample"] != 10:
            raise ValueError("The chosen melody channel changed its tonal instrument")
        melodic_hz = (base.PAULA / melody["period"] * pitch["cycles_per_source_sample"]
                      if melody["period"] and melody_active else 0)
        words = [round(hz * 2**24 / CLOCK) for hz in (melodic_hz, drum_frequency)]
        if any(not 0 <= word <= 65535 for word in words):
            raise ValueError("Synth frequency exceeds its SID register")
        rows.append([words[0] & 255, words[0] >> 8, pulse["control"] if melodic_hz else rest,
                     words[1] & 255, words[1] >> 8, drum_control])
        drum_triggers.append(bool(drum["trigger"]))
    if len(rows) != len(ticks):
        raise ValueError("Synth and sampled timelines disagree")
    # End the synthetic tail one tick before a new hit, keeping real hit onsets
    # distinct even where the original longer samples overlap the next trigger.
    for index in range(1, len(rows)):
        if drum_triggers[index] and not drum_triggers[index - 1]:
            rows[index - 1][3:] = [0, 0, rest]
    if any(rows[i][5] == rest for i, trigger in enumerate(drum_triggers) if trigger):
        raise ValueError("A source percussion trigger was lost")
    metadata = {"melody": pitch, "melody_source_channel": 3,
                "percussion_source_channel": 4, "percussion_source_triggers": sum(drum_triggers),
                "source_melody_triggers": sum(t["channels"][2]["trigger"] for t in ticks),
                "source_melody_volumes": sorted({t["channels"][2]["volume"] for t in ticks}),
                "sid_sustain_levels": [pulse["sustain"], instruments[1]["sustain"]],
                "instrument_library": library_receipt(library),
                "control_counts": [dict(Counter(row[column] for row in rows)) for column in (2, 5)],
                "scope": "Actual MOD note/hit timing. Pulse melody and handcrafted triangle/noise percussion are timbral approximations with quiet fixed sustain, not original sampled envelopes. MOD channel 1 chords are omitted."}
    return rows, metadata


def prepare(out: Path, library_directory: Path = DEFAULT_LIBRARY) -> tuple[dict, dict, list[list[int]]]:
    library = load_library(library_directory)
    instruments = library["instruments"]
    if (set(instruments) != set(range(1, 11)) or
            any(instruments[i]["kind"] != "sample" for i in (7, 8, 9)) or
            instruments[10].get("program") != "pulse" or
            any(instruments[i].get("program") not in {"triangle-sweep", "noise-then-triangle-sweep", "noise"}
                for i in range(1, 7))):
        raise ValueError("This arrangement requires Cream of the Earth's ten selected instruments")
    if len({instruments[i]["sustain"] for i in range(1, 7)}) != 1:
        raise ValueError("The percussion voice needs one shared prewarmed sustain level")
    pcm, context = base.prepare(out)
    if library["source"]["sha256"] != pcm["source"]["sha256"]:
        raise ValueError("Instrument library belongs to a different source MOD")
    expected_solo = HERE / "results/mod-channel/expected-input.bin"
    if (out / "expected-input.bin").read_bytes() != expected_solo.read_bytes():
        raise ValueError("Sampled channel differs from the accepted solo")
    rows, metadata = synth_score(context, library)
    data = (out / "data.asm").read_text()
    for bank in pcm["banks"]:
        instrument = library["instruments"][bank["id"]]
        generated_bank = out / f'sample-{bank["id"]:02d}.bin'
        if (instrument["data"] != generated_bank.read_bytes()
                or instrument["volume"] != bank["volume"] or instrument["decimation"] != bank["divisor"]):
            raise ValueError(f'Instrument {bank["id"]} differs from the accepted reusable bank')
        old = f'.import binary "{generated_bank.resolve()}"'
        if data.count(old) != 1:
            raise ValueError(f'Expected one bank include for instrument {bank["id"]}')
        # The library include contains data only. Labels and alignment stay in
        # the arrangement, preserving bank addresses and the fast C64 cursor.
        data = data.replace(old, f'.import source "{instrument["asm_path"]}"')
    before, after = data.split("score:\n", 1)
    lines, index = [], 0
    for line in after.splitlines():
        if line.strip().startswith(".byte "):
            line += "," + ",".join(map(str, rows[index])); index += 1
        lines.append(line)
    if index != pcm["frames"]:
        raise ValueError("Unexpected base score format")
    constants = (f'.label SID1_SUSTAIN = {library["instruments"][10]["sustain"]}\n'
                 f'.label SID2_SUSTAIN = {library["instruments"][1]["sustain"]}\n'
                 f'.label SID1_PULSE = {library["instruments"][10]["pulse_width"]}\n'
                 '.label SID2_PULSE = 2048\n')
    (out / "data.asm").write_text(constants + before + "score:\n" + "\n".join(lines) + "\n")
    base.save(out / "expected-synth.json", {"frames": rows, "register_order": [0, 1, 4, 7, 8, 11]})
    base.save(out / "synth-input.json", metadata)
    pcm = copy.deepcopy(pcm)
    pcm["scope"] = ("Unchanged sampled MOD channel 2 over three complete patterns. "
                    "No loops, offsets, active volume changes or channel mixing are silently discarded; "
                    "this input is chosen to require none. The separate synth_input describes SID voices 1/2.")
    base.save(out / "input.json", pcm)
    return pcm, metadata, rows


def verify(compiled: dict, receipt: dict, pcm: dict, rows: list[list[int]], out: Path) -> dict:
    events = base.reference.trace(Path(receipt["media"]))
    latches = np.asarray([c for c, r, v in events if r == 18 and v == 0x11], np.int64)[1:]
    expected = np.frombuffer((out / "expected-input.bin").read_bytes(), np.uint8)
    inputs = np.asarray([v for c, r, v in events if r == 15 and c > latches[0]], np.uint8)
    match = len(inputs) == len(expected) and np.array_equal(inputs, expected)
    gaps = dict(Counter(map(int, np.diff(latches))))
    master = next(c for c, r, v in events if r == 24 and v == 15)
    registers = (0, 1, 4, 7, 8, 11)
    synth = [(c, r, v) for c, r, v in events if master < c <= latches[-1] and r in registers]
    expected_synth = [(r, value) for row in rows for r, value in zip(registers, row)]
    same_synth = [(r, v) for _, r, v in synth] == expected_synth
    cuts = (np.arange(len(rows) + 1, dtype=np.int64) * CLOCK + PERIOD * 25) // (PERIOD * 50)
    timing_errors, offsets = [], []
    if same_synth:
        for index, (cycle, register, value) in enumerate(synth):
            frame = index // 6
            if frame == 0:
                if cycle >= latches[0]: timing_errors.append(index)
            else:
                boundary = int(latches[0] + (cuts[frame] - 1) * PERIOD)
                offset = cycle - boundary; offsets.append(offset)
                if not 0 <= offset <= 4 * PERIOD: timing_errors.append(index)
    stats = bytes.fromhex(receipt["stats_hex"])
    generated, underruns = int.from_bytes(stats[8:10], "little"), stats[6]
    master_writes = [(c, v) for c, r, v in events if r == 24 and latches[0] <= c <= latches[-1]]
    result = {"profile": receipt["profile"], "program_sha256": compiled["program_sha256"],
              "trace_sha256": receipt["media_sha256"], "expected_samples": len(expected),
              "observed_latches": len(latches), "input_codes_written": len(inputs),
              "all_sample_inputs_match_accepted_solo": match, "sample_gap_counts": gaps,
              "first_latch_cycle": int(latches[0]), "last_latch_cycle": int(latches[-1]),
              "generated_frames": generated, "underruns": underruns,
              "ordinary_sid_writes_checked": len(synth), "ordinary_sid_sequence_matches": same_synth,
              "synth_frame_timing_errors": len(timing_errors),
              "synth_commit_offset_cycles_after_boundary_latch": [min(offsets), max(offsets)] if offsets else [],
              "d418_writes_during_music": master_writes,
              "scope": "Every sampled input and latch, every ordered ordinary-voice frequency/control write and its frame, completed buffers and constant master volume. Does not prove original timbre, physical SID fidelity or perceived balance."}
    result["passed"] = (match and len(latches) == len(expected) and set(gaps) == {PERIOD}
                        and generated == pcm["frames"] and not underruns and same_synth
                        and not timing_errors and not master_writes)
    base.save(out / "player-check.json", result)
    if not result["passed"]:
        raise ValueError(f"Native hybrid verification failed: {result}")
    return result


def audio(receipt: dict, proof: dict, pcm: dict, out: Path) -> dict:
    stats = bytes.fromhex(receipt["stats_hex"])
    if int.from_bytes(stats[8:10], "little") != pcm["frames"] or stats[6]:
        raise ValueError("Hybrid audio run missed buffers")
    raw, rate = sf.read(receipt["media"], dtype="float64", always_2d=True)
    if rate != 22050 or raw.shape[1] != 1:
        raise ValueError("Expected fixed-profile mono 22050 Hz audio")
    start = round(proof["first_latch_cycle"] * rate / CLOCK)
    count = round(pcm["duration_s"] * rate)
    signal = raw[start:start + count, 0].copy()
    if len(signal) != count: raise ValueError("Incomplete hybrid recording")
    signal -= signal.mean(); peak = float(np.max(np.abs(signal)))
    if peak < .001: raise ValueError("Hybrid recording is silent")
    gain = min(8.0, .92 / peak)
    sf.write(out / "hybrid.wav", signal * gain, rate, subtype="PCM_16")
    result = {"frames": count, "duration_s": count / rate, "sample_rate": rate,
              "profile": receipt["profile"], "generated_frames": pcm["frames"], "underruns": 0,
              "raw_peak": peak, "raw_rms": float(np.std(signal)), "listening_gain": gain,
              "output_sha256": base.reference.digest(out / "hybrid.wav"),
              "processing": "Actual VICE WAV, clock-anchored crop, DC removal and one constant gain. No host mixing, EQ, alignment, time stretching or dynamics."}
    base.save(out / "audio-check.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results/mod-channel-hybrid")
    parser.add_argument("--instruments", type=Path, default=DEFAULT_LIBRARY,
                        help="Directory of instrument definitions for this arrangement")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--budget", action="store_true")
    args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    accepted = accepted_identity()
    pcm, synth, rows = prepare(out, args.instruments)
    compiled = base.reference.assemble("mod-channel-hybrid-player", out)
    (out / "player.prg").write_bytes(Path(compiled["program"]).read_bytes())
    capture = base.reference.capture(compiled, out / "player", pcm["duration_s"])
    proof = verify(compiled, capture, pcm, rows, out)
    report = {"scope": "One unchanged sampled MOD channel plus two ordinary SID approximations over the same 26.88 s. Three source channels; chord channel 1 omitted. Not full MOD or physical-chip validation.",
              "profile": capture["profile"], "pcm_input": pcm, "synth_input": synth,
              "build": compiled, "native_playback": proof}
    if args.capture:
        recorded = base.reference.capture(compiled, out / "player", pcm["duration_s"], audio=True)
        report["audio"] = audio(recorded, proof, pcm, out)
    if args.budget:
        from measure_budget import measure
        report["cpu_budget"] = measure(Path(compiled["program"]), compiled["symbols"], pcm["frames"], out / "budget")
    report["memory"] = {"program_end": compiled["symbols"]["program_end"],
                        "prg_bytes": compiled["bytes"], "bank_bytes": pcm["bank_bytes"],
                        "score_bytes": pcm["frames"] * 11,
                        "unused_before_d000_bytes": 0xD000 - compiled["symbols"]["program_end"]}
    if accepted_identity() != accepted:
        raise ValueError("Accepted reference changed during hybrid build")
    report["accepted_reference_preserved"] = accepted
    report["source_sha256"] = {name: base.reference.digest(HERE / name) for name in
                                ("build_mod_hybrid.py", "mod-channel-hybrid-player.asm", "instrument_library.py")}
    base.save(out / "verification.json", report)
    print(json.dumps({"seconds": pcm["duration_s"], "samples": pcm["input_codes"],
                      "program_bytes": compiled["bytes"], "proof": proof,
                      "audio": report.get("audio"), "cpu_budget": report.get("cpu_budget")}, indent=2))


if __name__ == "__main__":
    main()
