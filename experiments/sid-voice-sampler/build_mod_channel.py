"""Play one bounded real MOD channel through SID voice 3's sample-and-hold.

The published CC0-guitar prototype is read-only. This experiment selects three
complete Cream of the Earth patterns whose one-shot instruments have constant
per-instrument volume, keeping sample generation inside the measured CPU budget.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import urllib.request

import numpy as np
from scipy.signal import resample_poly, stft
import soundfile as sf

HERE = Path(__file__).resolve().parent
MOD = HERE.parent / "mod-hybrid"
sys.path.insert(0, str(MOD))
from mod_reader import load_mod
from timeline import build_timeline
from reference import render_timeline_pcm

spec = importlib.util.spec_from_file_location("voice_sampler_reference", HERE / "build.py")
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)
CLOCK, PERIOD = 985248, 126
RATE = CLOCK / PERIOD
START, END, CHANNEL = 17.92, 44.80, 1
PAULA = 3546894.6


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def reference_identity() -> dict:
    published = json.loads((HERE / "results/verification.json").read_text())
    wanted = dict(published["source_sha256"])
    wanted["results/player.prg"] = published["program"]["sha256"]
    wanted["results/voice-sampler.wav"] = published["audio"]["output_sha256"]
    for name, expected in wanted.items():
        if reference.digest(HERE / name) != expected:
            raise ValueError(f"Published reference changed: {name}")
    return wanted


def source_file(out: Path) -> tuple[Path, dict]:
    receipt = json.loads((MOD / "sources/cream-of-the-earth.source.json").read_text())
    path = MOD / "sources/cream-of-the-earth.mod"
    if not path.exists():
        path = out / "source.mod"
        if not path.exists():
            with urllib.request.urlopen(receipt["download_url"], timeout=45) as response:
                raw = response.read()
            if len(raw) != receipt["bytes"] or hashlib.sha256(raw).hexdigest() != receipt["sha256"]:
                raise ValueError("Downloaded MOD differs from its source receipt")
            path.write_bytes(raw)
    if path.stat().st_size != receipt["bytes"] or reference.digest(path) != receipt["sha256"]:
        raise ValueError("MOD differs from its source receipt")
    return path, receipt


def prepare(out: Path) -> tuple[dict, dict]:
    path, provenance = source_file(out)
    mod = load_mod(path)
    timeline = build_timeline(mod)
    ticks = [tick for tick in timeline["ticks"] if START - 1e-7 <= tick["time_s"] < END - 1e-7]
    if len(ticks) != 1344 or any(abs(t["duration_s"] - .02) > 1e-9 for t in ticks):
        raise ValueError("Expected three complete 20-ms-tick source patterns")
    states = [t["channels"][CHANNEL] for t in ticks]
    if not states[0]["trigger"]:
        raise ValueError("The phrase must begin with a real note trigger")
    instruments = sorted({s["playing_sample"] for s in states if s["playing_sample"]})
    volumes, banks, bank_meta = {}, {}, []
    for instrument in instruments:
        sample = mod["samples"][instrument - 1]
        active = [s for s in states if s["playing_sample"] == instrument]
        levels = {s["volume"] for s in active}
        if len(levels) != 1 or sample["loop_length"] > 2:
            raise ValueError("This experiment requires constant-volume one-shot banks")
        volume = levels.pop()
        volumes[instrument] = volume
        divisor = max(1, math.ceil(PAULA / min(s["period"] for s in active) / RATE * 256 / 255))
        raw = np.frombuffer(sample["data"], dtype=np.int8).astype(np.float64) / 128
        filtered = resample_poly(raw, 1, divisor)
        codes = np.clip(np.rint(128 + filtered * 127 * volume / 64), 0, 255).astype(np.uint8)
        padded = np.pad(codes, (0, (-len(codes)) % 256), constant_values=128)
        bank_path = out / f"sample-{instrument:02d}.bin"
        bank_path.write_bytes(padded.tobytes())
        banks[instrument] = padded
        bank_meta.append({"id": instrument, "volume": volume, "divisor": divisor,
                          "original_bytes": sample["length"], "resampled_bytes": len(codes),
                          "stored_bytes": len(padded), "sha256": reference.digest(bank_path)})
    by_id = {b["id"]: b for b in bank_meta}
    cuts = (np.arange(len(ticks) + 1, dtype=np.int64) * CLOCK + PERIOD * 25) // (PERIOD * 50)
    counts = np.diff(cuts)
    if set(map(int, counts)) != {156, 157}:
        raise ValueError("Unexpected source-tick to sample-clock mapping")
    score, expected, position, current, pitch_errors = [], [], 0, 0, []
    for index, (tick, state) in enumerate(zip(ticks, states)):
        instrument = state["playing_sample"]
        if not instrument or state.get("offset", 0):
            raise ValueError("Unexpected silent instrument or offset in selected channel")
        if state.get("loop_sample", instrument) not in (0, instrument):
            raise ValueError("Independent loop changes are outside this one-shot experiment")
        if state["trigger"]:
            current, position = instrument, 0
        if current != instrument or state["volume"] != volumes[instrument]:
            raise ValueError("Source changed instrument or volume without a supported note")
        divisor = by_id[instrument]["divisor"]
        step = round(PAULA / state["period"] / divisor / RATE * 256)
        if not 1 <= step <= 255:
            raise ValueError("Fractional pitch step exceeds the fast cursor range")
        pitch_errors.append(1200 * math.log2(step * RATE * divisor * state["period"] / (256 * PAULA)))
        record = [step, int(state["trigger"]), instrument, 256 - int(counts[index])]
        score.append(record)
        # Independent logical cursor model: no page-wrap or silence-page logic.
        indices = (position + np.arange(int(counts[index]), dtype=np.int64) * step) >> 8
        values = np.full(len(indices), 128, dtype=np.uint8)
        valid = indices < len(banks[current])
        values[valid] = banks[current][indices[valid]]
        expected.extend(values)
        position += int(counts[index]) * step
    (out / "expected-input.bin").write_bytes(bytes(expected))
    lines = [f".label FRAME_COUNT = {len(score)}", '.pc = $2000 "Reusable MOD instruments"']
    for bank in bank_meta:
        instrument = bank["id"]
        lines += [".align $100", f"sample_{instrument}:",
                  f'    .import binary "{(out / f"sample-{instrument:02d}.bin").resolve()}"',
                  f"sample_end_{instrument}:"]
    lines += [".align $100", "silence_page:", "    .fill 256,128", "score:"]
    for step, trigger, instrument, low in score:
        lines.append(f"    .byte {step},{trigger},>sample_{instrument},>sample_end_{instrument},{low}")
    lines += ["program_end:", '.assert "Resident program below I/O", program_end <= $d000, true']
    (out / "data.asm").write_text("\n".join(lines) + "\n")
    duration = len(expected) / RATE
    result = {"source": provenance, "source_channel": CHANNEL + 1,
              "source_range_s": [START, END], "source_duration_s": END - START,
              "duration_s": duration, "duration_error_us": (duration - (END - START)) * 1e6,
              "frames": len(score), "source_ticks_hz": 50, "sample_rate_hz": RATE,
              "sample_period_cycles": PERIOD, "frame_sample_counts": dict(Counter(map(int, counts))),
              "input_codes": len(expected), "triggers": sum(s[1] for s in score),
              "distinct_source_periods": sorted({s["period"] for s in states}),
              "fractional_pitch_error_cents": [min(pitch_errors), max(pitch_errors)],
              "banks": bank_meta, "bank_bytes": sum(b["stored_bytes"] for b in bank_meta),
              "score_bytes": len(score) * 5,
              "expected_input_sha256": reference.digest(out / "expected-input.bin"),
              "processing": "Per-instrument polyphase low-pass decimation, constant source MOD volume, unsigned eight-bit quantization; one stored reusable bank per instrument, neutral page padding. Pitch, position and retriggers execute on C64.",
              "scope": "Single real MOD channel over three complete patterns. No loops, offsets, active volume changes or channel mixing are silently discarded; this input is chosen to require none. SID voices1/2 stay silent."}
    save(out / "input.json", result)
    return result, {"mod": mod, "ticks": ticks}


def verify(build: dict, capture: dict, prepared: dict, out: Path) -> dict:
    events = reference.trace(Path(capture["media"]))
    latches = np.asarray([c for c, r, v in events if r == 18 and v == 0x11], dtype=np.int64)[1:]
    if not len(latches):
        raise ValueError("No oscillator stream")
    expected = np.frombuffer((out / "expected-input.bin").read_bytes(), dtype=np.uint8)
    inputs = np.asarray([v for c, r, v in events if r == 15 and c > latches[0]], dtype=np.uint8)
    same_length = len(inputs) == len(expected)
    mismatch = int(np.count_nonzero(inputs != expected)) if same_length else -1
    stats = bytes.fromhex(capture["stats_hex"])
    frames, underruns = int.from_bytes(stats[8:10], "little"), stats[6]
    volume_writes = [(c, v) for c, r, v in events if r == 24 and latches[0] <= c <= latches[-1]]
    synth_writes = [(c, r, v) for c, r, v in events
                    if r < 14 and latches[0] <= c <= latches[-1]]
    gap_counts = dict(Counter(map(int, np.diff(latches))))
    proof = {"profile": capture["profile"], "program_sha256": build["program_sha256"],
             "trace_sha256": capture["media_sha256"], "expected_samples": len(expected),
             "observed_latches": len(latches), "input_codes_written": len(inputs),
             "input_mismatches": mismatch, "sample_gap_counts": gap_counts,
             "first_latch_cycle": int(latches[0]), "last_latch_cycle": int(latches[-1]),
             "generated_frames": frames, "underruns": underruns,
             "d418_writes_during_music": volume_writes, "other_sid_writes_during_music": synth_writes,
             "scope": "Every actual oscillator input and latch interval over the full channel; C64 buffer completion, quiet other voices and no master-volume sampling. No analog-resolution or listening claim."}
    proof["passed"] = (len(latches) == len(expected) and same_length and mismatch == 0
                       and set(gap_counts) == {PERIOD} and frames == prepared["frames"]
                       and underruns == 0 and not volume_writes and not synth_writes)
    save(out / "player-check.json", proof)
    if not proof["passed"]:
        raise ValueError(f"MOD voice proof failed: {proof}")
    return proof


def audio(receipt: dict, proof: dict, prepared: dict, out: Path) -> dict:
    stats = bytes.fromhex(receipt["stats_hex"])
    if int.from_bytes(stats[8:10], "little") != prepared["frames"] or stats[6]:
        raise ValueError("Audio run missed a buffer")
    raw, rate = sf.read(receipt["media"], dtype="float64", always_2d=True)
    if rate != 22050 or raw.shape[1] != 1:
        raise ValueError("Expected fixed-profile mono 22050-Hz capture")
    start = round(proof["first_latch_cycle"] * rate / CLOCK)
    count = round(prepared["duration_s"] * rate)
    wave = raw[start:start + count, 0].copy()
    if len(wave) != count:
        raise ValueError("Incomplete actual VICE recording")
    wave -= wave.mean()
    peak = float(np.max(np.abs(wave)))
    if peak < .001:
        raise ValueError("Actual channel is silent")
    gain = min(8.0, .92 / peak)
    sf.write(out / "mod-channel.wav", wave * gain, rate, subtype="PCM_16")
    result = {"profile": receipt["profile"], "frames": count, "sample_rate": rate,
              "duration_s": count / rate, "raw_peak": peak,
              "raw_rms": float(np.std(wave)), "listening_gain": gain,
              "generated_frames": prepared["frames"], "underruns": 0,
              "output_sha256": reference.digest(out / "mod-channel.wav"),
              "processing": "Actual VICE WAV, clock-anchored crop, DC removal and one constant gain. No host mixing, EQ, time alignment, time stretching or dynamics."}
    save(out / "audio-check.json", result)
    return result


def analyze(out: Path, context: dict, prepared: dict) -> dict:
    codes = np.frombuffer((out / "expected-input.bin").read_bytes(), dtype=np.uint8)
    ratio = Fraction(22050 * PERIOD, CLOCK)
    ideal = resample_poly((np.r_[128, codes[:-1]].astype(float) - 128) / 128,
                          ratio.numerator, ratio.denominator)
    actual, rate = sf.read(out / "mod-channel.wav")
    count = min(len(actual), len(ideal)); a, b = actual[:count], ideal[:count]
    correlations = [float(np.corrcoef(a[441 + lag:], b[441:count - lag])[0, 1]) for lag in range(67)]
    lag = int(np.argmax(np.abs(correlations)))
    f, _, A = stft(a, rate, nperseg=1024, noverlap=768, boundary=None, padded=False)
    _, _, B = stft(b, rate, nperseg=1024, noverlap=768, boundary=None, padded=False)
    band = (f >= 50) & (f <= 3500); A, B = np.abs(A[band]).ravel(), np.abs(B[band]).ravel()
    cosine = float(A @ B / (np.linalg.norm(A) * np.linalg.norm(B)))
    # A second comparison uses original source bytes and tracker periods,
    # independently of the prepared byte banks and integer C64 cursor model.
    ticks = copy.deepcopy(context["ticks"])
    for index, tick in enumerate(ticks):
        tick["time_s"] = index * .02
        for ch, state in enumerate(tick["channels"]):
            if ch != CHANNEL:
                state["volume"] = 0
    original = render_timeline_pcm(context["mod"], {"ticks": ticks, "duration_s": END - START}, rate)[:count]
    _, _, O = stft(original, rate, nperseg=1024, noverlap=768, boundary=None, padded=False)
    O = np.abs(O[band]).ravel()
    original_cosine = float(A @ O / (np.linalg.norm(A) * np.linalg.norm(O)))
    result = {"native_audio_sha256": reference.digest(out / "mod-channel.wav"),
              "reference": "Intended C64 input, one-sample output pipeline and ideal band-limited reconstruction",
              "unshifted_waveform_correlation": correlations[0], "analysis_only_latency_frames": lag,
              "waveform_correlation_after_one_global_latency": correlations[lag],
              "native_time_spectral_cosine_50_to_3500_hz": cosine,
              "original_source_channel_spectral_cosine_50_to_3500_hz": original_cosine,
              "scope": "Complete channel. Spectra use native time; waveform analysis alone estimates one bounded global analog latency. Original-source comparison uses original sample bytes and source periods. Delivered audio is untouched; no perceived-quality or physical-chip ENOB claim."}
    result["passed"] = abs(correlations[lag]) > .9 and cosine > .95
    save(out / "waveform-check.json", result)
    if not result["passed"]:
        raise ValueError(f"Actual oscillator audio disagrees with intended input: {result}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results/mod-channel")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--budget", action="store_true", help="Non-invasive full VICE CPU profile")
    args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    preserved = reference_identity()
    prepared, context = prepare(out)
    compiled = reference.assemble("mod-channel-player", out)
    (out / "player.prg").write_bytes(Path(compiled["program"]).read_bytes())
    recording = reference.capture(compiled, out / "player", prepared["duration_s"])
    proof = verify(compiled, recording, prepared, out)
    report = {"scope": "One isolated MOD channel, three complete patterns; not full MOD integration or physical-chip validation.",
              "profile": recording["profile"], "input": prepared, "build": compiled, "native_playback": proof}
    if args.capture:
        recorded = reference.capture(compiled, out / "player", prepared["duration_s"], audio=True)
        report["audio"] = audio(recorded, proof, prepared, out)
        report["waveform"] = analyze(out, context, prepared)
    if args.budget:
        from measure_budget import measure
        report["cpu_budget"] = measure(Path(compiled["program"]), compiled["symbols"],
                                       prepared["frames"], out / "budget")
    report["memory"] = {"program_end": compiled["symbols"]["program_end"],
                        "unused_before_d000_bytes": 0xD000 - compiled["symbols"]["program_end"],
                        "prg_bytes": compiled["bytes"], "working_buffers_reserved_bytes": 512,
                        "maximum_active_buffer_bytes": 314, "bank_bytes": prepared["bank_bytes"],
                        "score_bytes": prepared["score_bytes"]}
    if reference_identity() != preserved:
        raise ValueError("Published prototype changed during this experiment")
    report["published_reference_preserved"] = preserved
    report["source_sha256"] = {name: reference.digest(HERE / name) for name in
                                ("build_mod_channel.py", "mod-channel-player.asm")}
    save(out / "verification.json", report)
    print(json.dumps({"seconds": prepared["duration_s"], "samples": prepared["input_codes"],
                      "banks": prepared["bank_bytes"], "prg_bytes": compiled["bytes"],
                      "passed": proof["passed"], "audio": report.get("audio"),
                      "cpu_budget": report.get("cpu_budget")}, indent=2))


if __name__ == "__main__":
    main()
