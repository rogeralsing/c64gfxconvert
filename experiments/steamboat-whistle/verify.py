#!/usr/bin/env python3
"""Verify native SID sample writes and record the actual C64 audio output.

The primary contract is the externally observed SID register sequence, not
the Python encoder or assembly layout. The final latch is checked separately:
writing a frequency byte does not yet emit that sample.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import subprocess

import numpy as np
import soundfile as sf


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CLOCK, PERIOD, RECORDING_RATE = 985248, 126, 22050


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def profile():
    path = REPO / "experiments/mod-hybrid/vice_profile.py"
    spec = importlib.util.spec_from_file_location("whistle_vice_profile", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def read_events(path: Path) -> list[tuple[int, int, int]]:
    """Convert the VICE SID dump's delta clock to absolute PAL cycles."""
    events, clock = [], 0
    with path.open() as stream:
        for line in stream:
            fields = line.split()
            if len(fields) != 3:
                continue
            try:
                delta, address, value = map(int, fields)
            except ValueError:
                continue
            if delta < 0 or not 0 <= value <= 255:
                raise ValueError("Invalid SID dump event")
            clock += delta
            events.append((clock, address & 31, value))
    return events


def verify_sid_trace(path: Path, expected: bytes) -> dict:
    """Check every sample preparation and its following hardware latch."""
    if not expected:
        raise ValueError("The complete expected sample sequence is required")
    events = read_events(path)
    sid3 = [(cycle, register, value) for cycle, register, value in events
            if register in (15, 18)]
    pattern = [(18, 17), (18, 1), (18, 9), (15, expected[0]), (18, 1)]
    offsets = [0, 6, 12, 20, 26]
    starts = []
    for index, event in enumerate(sid3[:-4]):
        if [(r, v) for _, r, v in sid3[index:index + 5]] != pattern:
            continue
        if [c - event[0] for c, _, _ in sid3[index:index + 5]] == offsets:
            starts.append(index)
    if not starts:
        raise ValueError("No native SID3 sample prefix matches the first input")
    # Startup's neutral latch does not contain the complete five-write prefix.
    start = starts[0]
    first = sid3[start][0]
    wanted = []
    guarded = expected + bytes((128, 128))
    for index, value in enumerate(guarded):
        base = first + index * PERIOD
        wanted.extend(((base, 18, 17), (base + 6, 18, 1),
                       (base + 12, 18, 9), (base + 20, 15, value),
                       (base + 26, 18, 1)))
    observed = sid3[start:start + len(wanted)]
    mismatches = [(index, a, b) for index, (a, b) in
                  enumerate(zip(observed, wanted)) if a != b]
    missing = max(0, len(wanted) - len(observed))
    last_preparation = first + (len(expected) - 1) * PERIOD
    final_latch = first + len(expected) * PERIOD
    remaining = sid3[start + len(wanted):]
    final_emitted = ((final_latch, 18, 17) in observed)
    final_end = final_latch + PERIOD
    shutdown = [(c, r, v) for c, r, v in remaining if r == 18 and v in (0, 9)]
    hold_complete = bool(shutdown and shutdown[0][0] >= final_end)
    master_before = [(c, v) for c, r, v in events if r == 24 and c < first]
    master_during = [(c, v) for c, r, v in events
                     if r == 24 and first <= c <= final_end]
    initial = {register: value for cycle, register, value in events if cycle < first}
    quiet_voices = initial.get(4) == 0 and initial.get(11) == 0 and not any(
        register in (4, 11) and value != 0
        for cycle, register, value in events if first <= cycle <= final_end)
    envelope = initial.get(19) == 0 and initial.get(20) == 240
    controls = [(c, v) for c, r, v in observed if r == 18 and v == 17]
    gaps = Counter(b[0] - a[0] for a, b in zip(controls, controls[1:]))
    result = {
        "passed": not mismatches and not missing and final_emitted and hold_complete
                  and bool(master_before) and master_before[-1][1] == 15
                  and not master_during and quiet_voices and envelope,
        "traceSha256": sha(path), "samples": len(expected),
        "expectedInputSha256": hashlib.sha256(expected).hexdigest(),
        "sampleInputsChecked": min(len(expected), len(observed) // 5),
        "neutralGuardInputsChecked": max(0, len(observed) // 5 - len(expected)),
        "orderedRegisterEventsChecked": len(observed),
        "eventMismatches": len(mismatches) + missing,
        "firstMismatches": mismatches[:8], "missingEvents": missing,
        "firstPreparationLatchCycle": first,
        "firstAudibleSampleCycle": first + PERIOD,
        "lastPreparationLatchCycle": last_preparation,
        "finalAudibleSampleCycle": final_latch,
        "fullSampleHoldEndCycle": final_end,
        "finalSampleWasEmitted": final_emitted,
        "finalSampleHeldForFullPeriod": hold_complete,
        "samplePeriodCounts": dict(gaps),
        "masterVolumeBeforeSamples": master_before[-1][1] if master_before else None,
        "masterWritesDuringSamples": master_during,
        "ordinaryVoicesStayMuted": quiet_voices,
        "sampleEnvelopeAD0SRF0": envelope,
        "durationSeconds": len(expected) * PERIOD / CLOCK,
        "scope": "All ordered SID3 frequency/control writes, exact PAL periods, "
                 "final emitted sample and hold, and constant SID master volume. "
                 "This does not prove physical SID fidelity or listening approval.",
    }
    return result


def capture(build: dict, out: Path, duration: float, *, audio: bool = False,
            points: dict[str, int] | None = None) -> dict:
    """Run one owned VICE process to its native completion breakpoint."""
    out.mkdir(parents=True, exist_ok=True)
    settings = profile()
    labels = build["symbols"]
    stats, monitor = out / "state.bin", out / "capture.mon"
    media = out / ("raw.wav" if audio else "registers.txt")
    log = out / "monitor.log"
    for path in (stats, media, log):
        path.unlink(missing_ok=True)
    commands = [f'logname "{log.resolve()}"', "log on",
                f'load "{build["program"]}" 0']
    packed_metadata = Path(build["program"]).parent / "packaging.json"
    packaged = json.loads(packed_metadata.read_text()) if packed_metadata.exists() else None
    if packaged and packaged["programSha256"] == sha(Path(build["program"])):
        commands += [f'break exec ${packaged["symbols"]["restore_done"]:04x}',
                     f'g ${packaged["symbols"]["unpack_start"]:04x}']
        done_checkpoint, next_checkpoint = 2, 3
        run_command = "g"
    else:
        done_checkpoint, next_checkpoint = 1, 2
        run_command = f'g ${labels["start"]:04x}'
    commands += [f'break exec ${labels["done"]:04x}']
    if done_checkpoint == 2:
        commands += ["delete 1"]
    for checkpoint, address in enumerate((points or {}).values(), next_checkpoint):
        commands += [f'trace exec ${address:04x}',
                     f'command {checkpoint} "stopwatch"']
    commands += [run_command,
                 f'bsave "{stats.resolve()}" 0 $0000 $0fff',
                 f"delete {done_checkpoint}"]
    commands += [f"delete {checkpoint}" for checkpoint in
                 range(next_checkpoint, next_checkpoint + len(points or {}))]
    commands += ["step 20000", "log off", "quit"]
    monitor.write_text("\n".join(commands) + "\n")
    command = ["rtk", "proxy", *settings.vice_command(), "-console", "-seed", "1",
               "-initbreak", "ready", "-moncommands", str(monitor.resolve()),
               "-limitcycles", str(round((duration + 15) * CLOCK)),
               "-sounddev", "wav" if audio else "dump",
               "-soundarg", str(media.resolve())]
    command += ["+warp", "-speed", "100"] if audio else ["-warp"]
    completed = subprocess.run(command, capture_output=True, text=True,
                               timeout=duration + 60)
    (out / "vice.log").write_text(completed.stdout + completed.stderr)
    if completed.returncode or not stats.exists() or not media.exists():
        raise RuntimeError(f"Native capture did not complete; inspect {out}")
    result = {"program": build["program"], "programSha256": sha(Path(build["program"])),
              "command": command, "profile": settings.PROFILE,
              "media": str(media.resolve()), "mediaSha256": sha(media),
              "state": str(stats.resolve()), "stateSha256": sha(stats),
              "monitorLog": str(log.resolve())}
    save(out / "receipt.json", result)
    return result


def verify_ring(receipt: dict, build: dict, samples: int, *, traced: bool) -> dict:
    """Require each produced page to precede its matching native activation."""
    labels = build["symbols"]
    state = Path(receipt["state"]).read_bytes()
    pages = (samples + 255) // 256
    counters = {name: state[labels[name]] for name in
                ("boundary_count", "generated_pages", "underruns", "finished")}
    counter_ok = (counters["boundary_count"] == pages - 1
                  and counters["generated_pages"] == pages
                  and counters["underruns"] == 0 and counters["finished"] == 1)
    result = {"passed": counter_ok, "pages": pages, "counters": counters,
              "partialFinalPageSamples": samples % 256 or 256}
    if traced:
        addresses = {labels["producer_done"]: "produced",
                     labels["consumer_activate"]: "activated"}
        events = {name: [] for name in addresses.values()}
        pattern = re.compile(r"^\.C:([0-9a-fA-F]{4})\s+.*\s(\d+)$")
        for line in Path(receipt["monitorLog"]).read_text().splitlines():
            match = pattern.match(line)
            if match and int(match[1], 16) in addresses:
                events[addresses[int(match[1], 16)]].append(int(match[2]))
        produced, activated = events["produced"], events["activated"]
        margins = [activation - finish for activation, finish in
                   zip(activated, produced[1:])]
        causal = (len(produced) == pages and len(activated) == pages - 1
                  and len(margins) == pages - 1 and min(margins) > 0)
        result.update(passed=counter_ok and causal, completedPages=len(produced),
                      consumingActivations=len(activated),
                      minimumPublicationMarginCycles=min(margins) if margins else None,
                      everyGenerationWrittenBeforeActivation=causal,
                      traceSha256=sha(Path(receipt["monitorLog"])))
    return result


def spectral_check(signal: np.ndarray, expected: bytes, rate: int) -> dict:
    """Compare fixed-clock spectral windows without searching for an offset."""
    indices = np.minimum(np.arange(len(signal)) * CLOCK // (rate * PERIOD),
                         len(expected) - 1).astype(np.int64)
    model = np.frombuffer(expected, dtype=np.uint8).astype(float)[indices] - 128
    length = round(rate * .2)
    window = np.hanning(length)
    low, high = max(1, round(length * 50 / rate)), round(length * 3500 / rate)

    def scores(actual):
        values = []
        for start in range(0, len(signal) - length + 1, length):
            a = actual[start:start + length]
            b = model[start:start + length]
            spectrum_a = np.abs(np.fft.rfft((a - a.mean()) * window))[low:high]
            spectrum_b = np.abs(np.fft.rfft((b - b.mean()) * window))[low:high]
            denominator = np.linalg.norm(spectrum_a) * np.linalg.norm(spectrum_b)
            values.append(float(np.dot(spectrum_a, spectrum_b) / denominator)
                          if denominator else 0.)
        return values

    actual = scores(signal)
    noise = scores(np.random.default_rng(0).normal(size=len(signal)))
    silence = scores(np.zeros_like(signal))
    passed = bool(actual) and float(np.median(actual)) > .8 and min(actual) > .5
    guard = float(np.median(noise)) <= .8 and max(silence) == 0.
    return {"passed": passed and guard, "windows": len(actual),
            "windowSeconds": .2, "bandHz": [50, 3500],
            "medianCosine": float(np.median(actual)), "minimumCosine": min(actual),
            "noiseMedianCosine": float(np.median(noise)),
            "silenceMaximumCosine": max(silence), "negativeControlsRejected": guard,
            "timeOffsetFitted": False, "gainFitted": False,
            "scope": "Magnitude spectra of fixed200ms native-clock windows "
                     "against the prepared sample values. This guards missing "
                     "or unrelated audio and does not establish listening approval."}


def write_audio(receipt: dict, proof: dict, expected: bytes, out: Path) -> dict:
    """Produce listening audio without fitting its time axis to the source."""
    raw, rate = sf.read(receipt["media"], dtype="float64", always_2d=True)
    if rate != RECORDING_RATE or raw.shape[1] != 1:
        raise ValueError("Expected mono 22050-Hz native VICE recording")
    begin = round(proof["firstAudibleSampleCycle"] * rate / CLOCK)
    count = round(proof["durationSeconds"] * rate)
    signal = raw[begin:begin + count, 0].copy()
    if len(signal) != count:
        raise ValueError("VICE recording does not cover the complete sample")
    signal -= signal.mean()
    peak = float(np.max(np.abs(signal)))
    rms = float(np.std(signal))
    if peak < .001 or rms < .0001:
        raise ValueError("Native sample recording is silent")
    spectral = spectral_check(signal, expected, rate)
    if not spectral["passed"]:
        save(out / "audio-spectrum-check.json", spectral)
        raise ValueError(f"Native audio differs from prepared samples: {spectral}")
    gain = min(8., .92 / peak)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "all.wav"
    sf.write(target, signal * gain, rate, subtype="PCM_16")
    result = {"passed": True, "file": str(target.resolve()), "sha256": sha(target),
              "sampleRate": rate, "samples": count, "durationSeconds": count / rate,
              "clockAnchoredFirstSample": begin, "rawPeak": peak,
              "rawRMS": rms, "constantListeningGain": gain,
              "spectralCheck": spectral,
              "processing": "Actual VICE audio; clock-anchored crop, DC removal "
                            "and one constant gain. No host mixing, EQ, timing "
                            "fit, time stretching, limiting or denoising."}
    save(out / "audio-check.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    args = parser.parse_args()
    folder = args.build.resolve()
    metadata = json.loads((folder / "build.json").read_text())
    build = metadata.get("build", metadata)
    if "symbols" not in build:
        build["symbols"] = json.loads((folder / "labels.json").read_text())
    if "program" not in build:
        build["program"] = str(folder / "player.prg")
    expected = (folder / "expected-input.bin").read_bytes()
    duration = len(expected) * PERIOD / CLOCK
    out = folder / "verification"
    points = {name: build["symbols"][name] for name in
              ("producer_done", "consumer_activate")}
    registers = capture(build, out / "registers", duration, points=points)
    proof = verify_sid_trace(Path(registers["media"]), expected)
    ring = verify_ring(registers, build, len(expected), traced=True)
    save(out / "register-check.json", proof)
    save(out / "ring-check.json", ring)
    if not proof["passed"] or not ring["passed"]:
        raise ValueError(f"Native SID sample proof failed: {proof}; {ring}")
    audio = capture(build, out / "capture", duration, audio=True)
    audio_ring = verify_ring(audio, build, len(expected), traced=False)
    if not audio_ring["passed"]:
        raise ValueError(f"Native audio run missed a page: {audio_ring}")
    listening = write_audio(audio, proof, expected, out)
    result = {"passed": True, "programSha256": sha(Path(build["program"])),
              "digital": proof, "ring": ring, "audioRunRing": audio_ring,
              "audio": listening}
    save(out / "verification.json", result)
    print(json.dumps({"passed": True, "samples": len(expected),
                      "audio": listening["file"]}, indent=2))


if __name__ == "__main__":
    main()
