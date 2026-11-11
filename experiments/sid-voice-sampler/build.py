"""Build and measure a standalone oscillator-sampling experiment in PAL VICE.

Only this experiment's directory is written. The current MOD and HVSC players
are inputs/reference context and are not rebuilt or modified.
"""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

import numpy as np
from scipy.signal import resample_poly, stft
import soundfile as sf

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "results"
CLOCK = 985248
PERIOD = 126
SAMPLE_RATE = CLOCK / PERIOD
FRAME_SAMPLES = 156
FRAME_COUNT = 320


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def profile():
    path = HERE.parent / "mod-hybrid/vice_profile.py"
    spec = importlib.util.spec_from_file_location("voice_sampler_profile", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def asm_bytes(values) -> str:
    return "\n".join("    .byte " + ",".join(f"${int(x):02x}" for x in values[i:i+24])
                     for i in range(0, len(values), 24))


def prepare(out: Path) -> dict:
    source = HERE.parent / "sid-inverse/assets/guitar.wav"
    manifest = json.loads((source.parent / "manifest.json").read_text())
    provenance = next(x for x in manifest["samples"] if x["id"] == "guitar")
    if digest(source) != provenance["sha256"]:
        raise ValueError("Guitar source differs from the existing CC0 source receipt")
    wave, rate = sf.read(source, dtype="float64")
    ratio = Fraction(CLOCK, PERIOD * 2 * rate)
    bank = resample_poly(wave, ratio.numerator, ratio.denominator)
    codes = np.clip(np.rint(128 + bank * 120), 0, 255).astype(np.uint8)
    padded = np.pad(codes, (0, (-len(codes)) % 256), constant_values=128)
    (out / "guitar-bank.bin").write_bytes(padded.tobytes())
    notes = [57, 60, 64, 62] * 2
    records = []
    for frame in range(FRAME_COUNT):
        note = notes[frame // 40]
        step = round(128 * 2 ** ((note - 57) / 12))
        bass = round(110 * 2 ** ((note - 57) / 12) * 2**24 / CLOCK)
        harmony = round(330 * 2 ** ((note - 57) / 12) * 2**24 / CLOCK)
        hybrid = frame >= FRAME_COUNT // 2
        records.append([step, int(frame % 40 == 0), bass & 255, bass >> 8,
                        0x11 if hybrid else 1, harmony & 255, harmony >> 8,
                        0x41 if hybrid else 1])
    data = [f".label FRAME_COUNT = {FRAME_COUNT}", '.pc = $2000 "Reusable sample"',
            "guitar_bank:", f'    .import binary "{(out / "guitar-bank.bin").resolve()}"',
            "guitar_end:", "silence_page:", "    .fill 256,128", "score:",
            asm_bytes(bytes(x for record in records for x in record)), "program_end:",
            '.assert "Resident program must remain below I/O", program_end <= $d000, true']
    (out / "data.asm").write_text("\n".join(data) + "\n")
    expected = []
    position = 0
    for step, trigger, *_ in records:
        if trigger:
            position = 0
        for _ in range(FRAME_SAMPLES):
            index = position >> 8
            expected.append(int(padded[index]) if index < len(padded) else 128)
            position += step
    (out / "expected-input.bin").write_bytes(bytes(expected))
    expected_synth = [(register, record[field]) for record in records
                      for register, field in ((0, 2), (1, 3), (4, 4), (7, 5), (8, 6), (11, 7))]
    dump(out / "expected-synth.json", {"writes": expected_synth})
    result = {"input": str(source.relative_to(REPO)), "input_sha256": digest(source),
              "source": provenance, "source_bank_bytes": len(padded),
              "bank_sha256": digest(out / "guitar-bank.bin"), "input_codes": len(expected),
              "sample_period_cycles": PERIOD, "sample_rate_hz": SAMPLE_RATE,
              "frames": FRAME_COUNT, "samples_per_frame": FRAME_SAMPLES,
              "duration_s": len(expected) / SAMPLE_RATE,
              "notes_midi": notes, "notes": "A3 C4 E4 D4, repeated once",
              "sections": [{"start_sample": 0, "samples": len(expected)//2,
                            "voices": "One sampled guitar through SID voice 3"},
                           {"start_sample": len(expected)//2, "samples": len(expected)//2,
                            "voices": "Same sampled guitar plus two ordinary SID oscillator voices"}],
              "sampling": "One reusable 8-bit instrument bank, fractional pitch cursor computed on the C64. No complete-song PCM stream in the program.",
              "processing": "Polyphase low-pass resampling to half the output rate. Eight-bit bank quantization, input gain120/128. No dynamic processing or output-audio EQ."}
    dump(out / "input.json", result)
    return result


def assemble(name: str, out: Path) -> dict:
    source = HERE / f"{name}.asm"
    target = out / f"{name}.asm"
    shutil.copyfile(source, target)
    command = [str(Path.home() / ".local/bin/kickass"), str(target.resolve()),
               "-o", str((out / f"{name}.prg").resolve()), "-symbolfile"]
    completed = subprocess.run(command, text=True, capture_output=True, timeout=60)
    (out / f"{name}-build.log").write_text(completed.stdout + completed.stderr)
    if completed.returncode:
        raise RuntimeError(completed.stdout + completed.stderr)
    sym = out / f"{name}.sym"
    labels = {k: int(v, 16) for k, v in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", sym.read_text())}
    prg = out / f"{name}.prg"
    return {"program": str(prg.resolve()), "symbols": labels, "bytes": prg.stat().st_size,
            "program_sha256": digest(prg), "source_sha256": digest(source)}


def capture(build: dict, out: Path, duration: float, audio: bool = False, probe: bool = False) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    labels = build["symbols"]
    monitor = out / "capture.mon"
    stats = out / "stats.bin"
    stats.unlink(missing_ok=True)
    address = labels["observations"] if probe else 2
    end = address + 255 if probe else 13
    monitor.write_text(f'load "{build["program"]}" 0\n'
                       f'break exec ${labels["done"]:04x}\n'
                       f'g ${labels["start"]:04x}\n'
                       'step 20000\n'
                       f'bsave "{stats.resolve()}" 0 ${address:04x} ${end:04x}\nquit\n')
    settings = profile()
    mode = "audio" if audio else "registers"
    media = out / ("raw.wav" if audio else "registers.txt")
    media.unlink(missing_ok=True)
    command = settings.vice_command() + ["-console", "-seed", "1", "-initbreak", "ready",
        "-moncommands", str(monitor.resolve()), "-limitcycles", str(round((duration + 15) * CLOCK)),
        "-sounddev", "wav" if audio else "dump", "-soundarg", str(media.resolve())]
    command += ["+warp", "-speed", "100"] if audio else ["-warp"]
    completed = subprocess.run(command, text=True, capture_output=True, timeout=duration + 60)
    (out / f"{mode}.log").write_text(completed.stdout + completed.stderr)
    if completed.returncode or not stats.exists():
        raise RuntimeError(f"VICE {mode} did not reach the completion breakpoint; inspect {out}")
    return {"program_sha256": build["program_sha256"], "profile": settings.PROFILE,
            "command": command, "stats_hex": stats.read_bytes().hex(),
            "stats_file": str(stats.resolve()), "media": str(media.resolve()),
            "media_sha256": digest(media)}


def trace(path: Path) -> list[tuple[int, int, int]]:
    cycle = 0
    result = []
    for line in path.read_text().splitlines():
        fields = line.split()
        if len(fields) != 3:
            continue
        delta, address, value = map(int, fields)
        cycle += delta
        result.append((cycle, address & 31, value))
    return result


def verify_probe(build: dict, receipt: dict, out: Path) -> dict:
    observed = np.frombuffer(Path(receipt["stats_file"]).read_bytes(), dtype=np.uint8)
    differences = np.diff(observed.astype(int))
    result = {"input_codes": 256, "observable_levels": len(np.unique(observed)),
              "minimum": int(observed.min()), "maximum": int(observed.max()),
              "monotonic": bool(np.all(differences >= 0)), "readback": observed.tolist(),
              "profile": receipt["profile"], "program_sha256": build["program_sha256"],
              "scope": "Actual C64 OSC3 readback across all256 input codes. Eight-bit readback is a coarser observation of the internal waveform DAC; this is not a measured analog effective-bit count."}
    result["passed"] = result["observable_levels"] > 16 and result["monotonic"]
    dump(out / "probe-check.json", result)
    if not result["passed"]:
        raise ValueError(f"Oscillator transfer probe failed: {result}")
    return result


def verify_player(build: dict, receipt: dict, prepared: dict, out: Path) -> dict:
    events = trace(out / "registers.txt")
    latches = np.array([c for c, r, v in events if r == 18 and v == 0x11], dtype=np.int64)
    gaps = np.diff(latches)
    # One initialization pulse precedes the steady NMI clock.
    start = 1
    latches = latches[start:]
    gaps = np.diff(latches)
    expected = np.frombuffer((OUT / "expected-input.bin").read_bytes(), dtype=np.uint8)
    inputs = np.array([v for c, r, v in events if r == 15 and c > latches[0]], dtype=np.uint8)
    mismatch = np.flatnonzero(inputs[:len(expected)] != expected[:len(inputs)]) if len(inputs) <= len(expected) else np.array([-1])
    stats = bytes.fromhex(receipt["stats_hex"])
    generated = int.from_bytes(stats[8:10], "little")
    underruns = stats[6]
    stream = [v for c, r, v in events if r == 24 and latches[0] <= c <= latches[-1]]
    master_on = next(c for c, r, v in events if r == 24 and v == 15)
    synth = [(r, v) for c, r, v in events if master_on < c <= latches[-1]
             and r in (0, 1, 4, 7, 8, 11)]
    expected_synth = [tuple(x) for x in json.loads((OUT / "expected-synth.json").read_text())["writes"]]
    result = {"profile": receipt["profile"], "program_sha256": build["program_sha256"],
              "expected_samples": len(expected), "observed_latches": len(latches),
              "input_codes_written": len(inputs), "input_mismatches": len(mismatch),
              "sample_gap_counts": dict(sorted(Counter(map(int, gaps)).items())),
              "first_latch_cycle": int(latches[0]), "last_latch_cycle": int(latches[-1]),
              "generated_frames": generated, "underruns": underruns,
              "d418_writes_during_music": stream,
              "ordinary_sid_writes_checked": len(synth),
              "ordinary_sid_sequence_matches": synth == expected_synth,
              "scope": "Actual native SID voice3 frequency/control writes, constant sample intervals, C64 buffer generation and absence of D418 PCM writes. Not an analog fidelity or listening-quality claim."}
    result["passed"] = (len(latches) == len(expected) and len(inputs) == len(expected)
                        and not len(mismatch) and set(map(int, gaps)) == {PERIOD}
                        and generated == FRAME_COUNT and not underruns and not stream
                        and synth == expected_synth)
    dump(out / "player-check.json", result)
    if not result["passed"]:
        raise ValueError(f"Oscillator player proof failed: {result}")
    return result


def write_audio(receipt: dict, proof: dict, prepared: dict, out: Path) -> dict:
    stats = bytes.fromhex(receipt["stats_hex"])
    if int.from_bytes(stats[8:10], "little") != FRAME_COUNT or stats[6]:
        raise ValueError("The actual audio run did not generate all buffers without underruns")
    raw, rate = sf.read(receipt["media"], dtype="float64", always_2d=True)
    if rate != 22050 or raw.shape[1] != 1:
        raise ValueError("Expected fixed-profile mono22050Hz capture")
    anchor = round(proof["first_latch_cycle"] * rate / CLOCK)
    count = round(prepared["duration_s"] * rate)
    audio = raw[anchor:anchor+count, 0].copy()
    if len(audio) != count:
        raise ValueError("Native recording is incomplete")
    audio -= audio.mean()
    peak = float(np.max(np.abs(audio)))
    if peak < .001:
        raise ValueError("Native oscillator recording is silent")
    gain = min(8.0, .92 / peak)
    sf.write(out / "voice-sampler.wav", audio * gain, rate, subtype="PCM_16")
    split = round(prepared["sections"][1]["start_sample"] * rate / SAMPLE_RATE)
    sf.write(out / "guitar-voice.wav", audio[:split] * gain, rate, subtype="PCM_16")
    sf.write(out / "guitar-and-sid.wav", audio[split:] * gain, rate, subtype="PCM_16")
    result = {"profile": receipt["profile"], "frames": count, "duration_s": count / rate,
              "raw_peak": peak, "listening_gain": gain,
              "generated_frames": FRAME_COUNT, "underruns": 0,
              "output_sha256": digest(out / "voice-sampler.wav"),
              "processing": "Actual VICE WAV, clock-anchored crop, DC removal and one constant gain. Separate sections are crops of this same emulated performance; no host mixing, EQ, time stretching or dynamics."}
    dump(out / "audio-check.json", result)
    return result


def analyze_audio(out: Path) -> dict:
    """Diagnose the solo waveform without altering the delivered VICE audio."""
    codes = np.frombuffer((out / "expected-input.bin").read_bytes(), dtype=np.uint8)
    ideal = (np.r_[128, codes[:-1]].astype(np.float64) - 128) / 128
    ratio = Fraction(22050 * PERIOD, CLOCK)
    ideal = resample_poly(ideal, ratio.numerator, ratio.denominator)
    actual, rate = sf.read(out / "guitar-voice.wav", dtype="float64")
    count = min(len(actual), len(ideal))
    actual, ideal = actual[:count], ideal[:count]
    # A single bounded analog-path latency estimate for the complete solo.
    # This is diagnostic only; no source, note or listening file is realigned.
    correlations = [float(np.corrcoef(actual[441+lag:], ideal[441:count-lag])[0, 1])
                    for lag in range(67)]
    lag = int(np.argmax(np.abs(correlations)))
    a, b = actual[441+lag:], ideal[441:count-lag]
    gain = float(b @ a / (a @ a))
    error = b - gain * a
    frequencies, _, target = stft(ideal, rate, nperseg=1024, noverlap=768,
                                  boundary=None, padded=False)
    _, _, observed = stft(actual, rate, nperseg=1024, noverlap=768,
                          boundary=None, padded=False)
    selected = (frequencies >= 50) & (frequencies <= 3500)
    target, observed = np.abs(target[selected]).ravel(), np.abs(observed[selected]).ravel()
    cosine = float(target @ observed / (np.linalg.norm(target) * np.linalg.norm(observed)))
    result = {"native_audio_sha256": digest(out / "guitar-voice.wav"),
              "reference": "Exact C64 cursor input with one-sample pipeline, ideal band-limited reconstruction",
              "unshifted_waveform_correlation": correlations[0],
              "analysis_only_latency_frames": lag, "analysis_latency_bound_ms": 3,
              "waveform_correlation_after_single_global_latency": correlations[lag],
              "analysis_gain": gain,
              "waveform_signal_to_error_db": float(10 * np.log10(np.mean(b*b) / np.mean(error*error))),
              "native_time_spectral_cosine_50_to_3500_hz": cosine,
              "scope": "Whole solo. Spectra use the native time axis. Only waveform analysis estimates one global analog-path latency and scalar gain. Delivered C64 recordings are untouched. Does not establish subjective sound quality or physical-chip effective resolution."}
    result["passed"] = (abs(correlations[lag]) > .9 and cosine > .95)
    dump(out / "waveform-check.json", result)
    if not result["passed"]:
        raise ValueError(f"Native oscillator audio is not faithful to its intended input: {result}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    for name in ("voice-sampler.wav", "guitar-voice.wav", "guitar-and-sid.wav",
                 "report.json", "waveform-check.json", "audio-check.json"):
        (OUT / name).unlink(missing_ok=True)
    prepared = prepare(OUT)
    probe = assemble("probe", OUT)
    player = assemble("player", OUT)
    report = {"input": prepared, "probe_build": probe, "player_build": player}
    probe_receipt = capture(probe, OUT / "probe", .1, probe=True)
    report["probe"] = verify_probe(probe, probe_receipt, OUT)
    receipt = capture(player, OUT / "player", prepared["duration_s"])
    report["player"] = verify_player(player, receipt, prepared, OUT / "player")
    if args.capture:
        audio = capture(player, OUT / "player", prepared["duration_s"], audio=True)
        report["audio"] = write_audio(audio, report["player"], prepared, OUT)
        report["waveform"] = analyze_audio(OUT)
    dump(OUT / "report.json", report)
    print(json.dumps({"probe_levels": report["probe"]["observable_levels"],
                      "player": report["player"], "audio": report.get("audio")}, indent=2))


if __name__ == "__main__":
    main()
