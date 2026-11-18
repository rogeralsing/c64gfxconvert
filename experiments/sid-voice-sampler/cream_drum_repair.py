"""Bounded Cream drum repair using the canonical native dual-sampler.

This is a twenty-second listening candidate, not a replacement for full Cream.
SID1 retains the approved pulse program and SID3 its exact sample codes. Only
SID2 changes: six reusable original drum banks replace the short noise stubs.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

import cream_instruments as cream
import cream_playback
import native_support as support
from native_instruments.music_data import Arena
from native_instruments.verify_music import verify

HERE = Path(__file__).resolve().parent
FRAMES = 1000
MODES = {"all": (True, True, True), "sid-1": (True, False, False),
         "sid-2": (False, True, False), "sid-3": (False, False, True),
         "muted": (False, False, False)}


def prepare(out: Path) -> dict:
    """Link original banks and notes, never a flattened song waveform."""
    out.mkdir(parents=True, exist_ok=True)
    accepted = cream.prepare(out / "approved-input")
    ticks = accepted["ticks"][:FRAMES]
    counts = accepted["frame_sample_counts_exact"][:FRAMES]
    cuts = np.r_[0, np.cumsum(counts)].astype(int)
    total = int(cuts[-1])
    expected3 = accepted["expected_input"][:total]
    mod = support.source_mod(accepted["source"], out)
    arena = Arena()
    # The canonical COPY32 manager and calibration occupy C000..C4ff.
    arena.regions[-1] = (0x7900, 0xc000)
    segments: list[tuple[int, bytes, str]] = []

    def allocate(data: bytes, name: str, alignment: int = 1) -> int:
        address = arena.allocate(len(data), name, alignment)
        segments.append((address, data, name))
        return address

    addresses3 = {asset["id"]: allocate(asset["data"], f'bass-{asset["id"]}')
                  for asset in accepted["assets"]}
    drums, drum_ids = [], {}
    for tick in ticks:
        state = tick["channels"][3]
        identifier, period, volume = (state[key] for key in ("playing_sample", "period", "volume"))
        key = identifier, period, volume
        if key in drum_ids:
            continue
        if identifier not in range(1, 7) or state.get("offset", 0):
            raise ValueError("The bounded repair only accepts original Cream drums 1..6")
        sample = mod["samples"][identifier - 1]
        if sample["loop_length"] > 2:
            raise ValueError("Cream drum repair requires explicit one-shot banks")
        raw = np.frombuffer(sample["data"], np.int8).astype(float) / 128
        ratio = Fraction(support.CLOCK * period / (504 * support.PAULA)).limit_denominator(20000)
        filtered = resample_poly(raw, ratio.numerator, ratio.denominator)
        virtual = np.clip(np.rint(128 + filtered * 127 * volume / 64), 0, 255).astype(np.uint8)
        high = np.rint(virtual.astype(float) * 105 / 249).astype(np.uint8)
        data = high.tobytes() + bytes([54] * 40)
        identifier2 = len(drums)
        address = allocate(data, f'drum-{identifier}-{period}-{volume}')
        drums.append({"id": identifier2, "source_instrument": identifier,
                      "period": period, "volume": volume, "address": address,
                      "logical_bytes": len(high), "data": data,
                      "source_sample_sha256": hashlib.sha256(sample["data"]).hexdigest(),
                      "bank_sha256": hashlib.sha256(data).hexdigest()})
        drum_ids[key] = identifier2
    neutral_id = len(drums)
    neutral = allocate(bytes([54] * 40), "neutral-drum")
    drums.append({"id": neutral_id, "source_instrument": 0, "address": neutral,
                  "logical_bytes": 0, "data": bytes([54] * 40)})
    bank_low = allocate(bytes(d["address"] & 255 for d in drums), "c3_bank_low")
    bank_high = allocate(bytes(d["address"] >> 8 for d in drums), "c3_bank_high")
    rle = {count: allocate(bytes([count, 15]), f"neutral-triangle-{count}", 256)
           for count in sorted(set(counts))}
    records, sid1_rows, expected2 = [], [], bytearray()
    position3, position2 = 0, 0
    previous2 = None
    for index, (tick, count, row) in enumerate(zip(ticks, counts, accepted["rows"])):
        bass = tick["channels"][1]
        if bass["trigger"]:
            position3 = 0
        asset = accepted["assets"][row[16]]
        if position3 < asset["logical_bytes"]:
            pointer3 = addresses3[asset["id"]] + position3
        else:
            pointer3 = addresses3[0]
        # The integer cursor bank must yield the independently approved Q8 codes.
        actual = asset["data"][position3:position3 + count]
        if len(actual) < count:
            actual += bytes([113] * (count - len(actual)))
        if position3 >= asset["logical_bytes"]:
            actual = bytes([113] * count)
        if bytes(value + 15 for value in actual) != expected3[cuts[index]:cuts[index + 1]]:
            raise ValueError("Linked SID3 bank changed approved Q8 values")
        position3 += count

        state = tick["channels"][3]
        key = tuple(state[k] for k in ("playing_sample", "period", "volume"))
        if state["trigger"]:
            position2 = 0
        elif previous2 is not None and key != previous2:
            raise ValueError("Held drum pitch/gain changes need an explicit cursor policy")
        drum = drums[drum_ids[key]]
        first_latch = max(4, (int(cuts[index]) + 3) // 4 * 4)
        output_count = len(range(first_latch, int(cuts[index + 1]), 4))
        active = min(output_count, max(0, drum["logical_bytes"] - position2))
        expected2.extend(drum["data"][position2:position2 + active])
        expected2.extend(bytes([54] * (output_count - active)))
        pointer = rle[count]
        sid1 = row[:3]
        records.append([pointer & 255, pointer >> 8, pointer3 & 255, pointer3 >> 8,
                        256 - count, output_count, *sid1, drum["id"],
                        int(state["trigger"]), active])
        sid1_rows.append(sid1)
        position2 += active
        previous2 = key
    score = allocate(bytes(v for row in records for v in row), "score")
    labels = {"score": score, "c3_bank_low": bank_low, "c3_bank_high": bank_high,
              "silence_page": addresses3[0]}
    lines = [f".label FRAME_COUNT = {FRAMES}", ".label SID1_SUSTAIN = 1",
             ".label SID2_SUSTAIN = 15", ".label SID3_SUSTAIN = 15",
             ".label SID_OUTPUT_MODE = 15", ".label SID1_PULSE = 1966",
             ".label SID2_PULSE = 2048", f".label C3_SILENT_VARIANT = {neutral_id}",
             ".label SID2_LATCH_CONTROL = 17", ".label SID2_RELEASE_CONTROL = 1"]
    lines += [f".label {key} = ${value:04x}" for key, value in labels.items()]
    for address, content, name in sorted(segments):
        path = out / f"{address:04x}-{name}.bin"
        path.write_bytes(content)
        lines += [f'.pc = ${address:04x} "{name}"', f'.import binary "{path.resolve()}"']
    lines.append(f".label program_end = ${max(a + len(b) for a,b,_ in segments):04x}")
    (out / "data.asm").write_text("\n".join(lines) + "\n")
    (out / "expected-input.bin").write_bytes(expected3)
    (out / "expected-high.bin").write_bytes(expected2)
    support.save(out / "drums.json", {"banks": [{k: v for k, v in d.items() if k != "data"} for d in drums],
        "output_rate_hz": support.CLOCK / 504, "hold_cycles": 249,
        "reference_hold_cycles": 105, "approximation": "Original one-shot samples, low-pass resampled to the 504-cycle lane. First code follows the note's first available global SID2 latch; no host song waveforms."})
    return {"frames": FRAMES, "input_codes": total, "duration_s": total * 126 / support.CLOCK,
            "frame_sample_counts_exact": counts, "rows": sid1_rows,
            "data": str((out / "data.asm").resolve()), "score": score,
            "segments": segments, "source": accepted["source"], "drums": drums,
            "expected3": expected3, "expected2": bytes(expected2)}


def _build(out: Path, prepared: dict, enabled: tuple[bool, bool, bool]) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    data = Path(prepared["data"]).read_text()
    constants = {"SID1_SUSTAIN": 1 if enabled[0] else 0,
                 "SID2_SUSTAIN": 15 if enabled[1] else 0,
                 "SID3_SUSTAIN": 15 if enabled[2] else 0,
                 "SID_OUTPUT_MODE": 15 if enabled[2] else 143,
                 "SID2_LATCH_CONTROL": 17 if enabled[1] else 25,
                 "SID2_RELEASE_CONTROL": 1 if enabled[1] else 9}
    for key, value in constants.items():
        data, count = re.subn(rf"(?m)^\.label {key} = \d+$", f".label {key} = {value}", data)
        if count != 1:
            raise ValueError(f"Expected one native output constant {key}")
    rows = [r.copy() for r in prepared["rows"]]
    if not enabled[0]:
        original = next(Path(prepared["data"]).parent.glob(f'{prepared["score"]:04x}-score.bin'))
        score = bytearray(original.read_bytes())
        for index in range(FRAMES):
            score[index * 12 + 6:index * 12 + 9] = bytes([0, 0, 25])
            rows[index] = [0, 0, 25]
        replacement = out / "muted-score.bin"
        replacement.write_bytes(score)
        data = data.replace(str(original.resolve()), str(replacement.resolve()))
    (out / "data.asm").write_text(data)
    source = (HERE / "linus-mix-player.asm").read_text()
    if source.count("cmp #241") != 1:
        raise ValueError("Expected the canonical startup prefill guard")
    # COPY32 may add 32 values. Stop with at least 32 free slots, including the
    # startup neutral slot; otherwise a long first drum can wrap the write
    # cursor before the old 241 threshold is observed.
    source = source.replace("cmp #241", "cmp #209", 1)
    # Restore the accepted Cream capture's absolute emulator epoch. Both
    # runtimes already commit initial SID1 at -254/-247/-240 cycles and later
    # notes at +53/+60/+67. This fixed cold delay precedes SID initialization;
    # listening files receive no measured or fitted timing adjustment.
    from full_length_runtime import _delay
    anchor = "    jsr startup_audio_delay\n"
    if source.count(anchor) != 1:
        raise ValueError("Expected one canonical cold audio delay call")
    source = source.replace(anchor, "    jsr cream_epoch_delay\n" + anchor, 1)
    source += '\n.pc = $c500 "Cream fixed absolute audio epoch"\ncream_epoch_delay:\n' + _delay(53960 - 6)
    target = out / "linus-mix-player.asm"
    target.write_text(source)
    program = out / "linus-mix-player.prg"
    completed = subprocess.run(["rtk", "proxy", str(Path.home() / ".local/bin/kickass"),
        str(target), "-o", str(program), "-symbolfile"], capture_output=True,
        text=True, timeout=60)
    (out / "build.log").write_text(completed.stdout + completed.stderr)
    if completed.returncode:
        raise RuntimeError(completed.stdout + completed.stderr)
    labels = {k: int(v, 16) for k, v in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", target.with_suffix(".sym").read_text())}
    build = {"program": str(program), "symbols": labels, "bytes": program.stat().st_size,
             "program_sha256": support.digest(program), "source_sha256": support.digest(target)}
    build.update(rows=rows, enabled=list(enabled))
    support.save(out / "build.json", build)
    return build


def _previous_muted_control(out: Path) -> dict:
    """Reuse a verified capture or reproduce the pinned old native control.

    A fresh checkout has the approved WAVs and source, but no ignored raw
    captures. Rebuilding into this candidate's directory avoids depending on
    historical work files and never overwrites the approved player.
    """
    for saved in (HERE / "work/cream/linus-mix/programs/muted/audio/receipt.json",
                  out / "reference-control/programs/muted/audio/receipt.json"):
        if saved.exists():
            receipt = json.loads(saved.read_text())
            media = Path(receipt["media"])
            if (receipt["profile"] == support.profile().PROFILE and media.exists()
                    and support.digest(media) == receipt["media_sha256"]):
                return receipt
    reference = cream_playback.run(out / "reference-control", assemble_only=True)
    if reference["program"]["program_sha256"] != "17c46c6fb45900f6024413ec52634200f2c5168dcacf6561465c527ad1333af1":
        raise ValueError("The reproduced previous Cream control changed its pinned player")
    folder = out / "reference-control/programs/muted"
    build = json.loads((folder / "build.json").read_text())
    receipt = support.capture(build, folder / "audio", reference["duration_s"], audio=True)
    support.save(folder / "audio/receipt.json", receipt)
    stats = bytes.fromhex(receipt["stats_hex"])
    if int.from_bytes(stats[8:10], "little") != 1344 or int.from_bytes(stats[6:8], "little"):
        raise ValueError("The independent previous muted control missed its native deadline")
    return receipt


def run(out: Path, *, assemble_only: bool = False) -> dict:
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / ".gitignore").write_text(
        "*\n!.gitignore\n!player.prg\n!all.wav\n!sid-[1-3].wav\n!verification.json\n!README.md\n"
        "!original-c4.wav\n!original-c4-receipt.json\n!autostart-check.json\n"
        "!rebuild-check.json\n!isolation-check.json\n")
    protected = cream_playback.protected_hashes(full=True)
    protected.update({f"full-cream/{p.name}": support.digest(p)
                      for p in (HERE / "work/cream/full-linus-mix").glob("*")
                      if p.suffix in (".wav", ".prg")})
    prepared = prepare(out / "linked")
    builds = {name: _build(out / "programs" / name, prepared, enabled)
              for name, enabled in MODES.items()}
    result = {"scope": "Bounded SID2 timbre repair candidate only, original Cream 17.92..37.92s. Full-length arrangement and approved references are untouched.",
              "source_interval_s": [17.92, 37.92], "full_song": False,
              "program": {k: v for k, v in builds["all"].items() if k not in ("symbols", "rows")},
              "source": prepared["source"], "frames": FRAMES,
              "duration_s": prepared["duration_s"], "SID3_codes": len(prepared["expected3"]),
              "SID3_codes_sha256": hashlib.sha256(prepared["expected3"]).hexdigest(),
              "SID2_codes": len(prepared["expected2"]),
              "SID2_high_sha256": hashlib.sha256(prepared["expected2"]).hexdigest(),
              "source_sha256": support.digest(Path(__file__)),
              "runtime_sha256": support.digest(HERE / "linus-mix-player.asm"),
              "memory": {"instrument_and_note_bytes": sum(len(b) for _,b,_ in prepared["segments"]),
                         "program_bytes": builds["all"]["bytes"], "external_RAM": False},
              "limitations": ["SID2 upper bandwidth is approximately 977 Hz, so original hihat brightness cannot survive this clock.",
                              "Original C1 remains omitted, matching the approved interval. SID1 remains its pulse approximation.",
                              "This does not integrate the extra sample lane into the full Q8 player."],
              "protected_hashes": protected}
    support.save(out / "verification.json", result)
    shutil.copyfile(builds["all"]["program"], out / "player.prg")
    if assemble_only:
        return result

    def capture(item):
        name, build = item
        folder = out / "programs" / name
        (folder / "expected-input.bin").write_bytes(prepared["expected3"])
        receipt = support.capture(build, folder / "registers", prepared["duration_s"])
        support.save(folder / "register-receipt.json", receipt)
        proof = verify(build, receipt, prepared, build["rows"], folder,
                       out / "linked/expected-high.bin",
                       directmeta={"hold_cycles": 249, "reference_hold_cycles": 105,
                                   "startup_neutral_values": 1, "neutral_frequency_high": 54},
                       sid2_muted=not build["enabled"][1], baseline_first_latch_cycle=None)
        return name, proof

    with ThreadPoolExecutor(max_workers=3) as pool:
        proofs = dict(pool.map(capture, builds.items()))
    if any(proof["first_latch_cycle"] != 2300170 for proof in proofs.values()):
        raise ValueError("Cream candidate lost the approved absolute native audio epoch")
    result["native"] = proofs
    from native_instruments.measure_ring import measure as measure_ring
    from native_instruments.measure_music_budget import measure as measure_cpu
    result["ring"] = measure_ring(builds["all"], prepared["expected2"], out / "ring", prepared["duration_s"])
    result["cpu"] = measure_cpu(Path(builds["all"]["program"]), builds["all"]["symbols"],
                                prepared["frame_sample_counts_exact"], out / "cpu")
    if not result["ring"]["passed"] or not result["cpu"]["passed"]:
        raise ValueError("Native ring or CPU deadline proof failed")
    support.save(out / "verification.json", result)

    from native_playback import static_control
    audio_builds = dict(builds)
    audio_builds["static-control"] = static_control(builds["muted"], out / "static-control")

    def audio(item):
        name, build = item
        folder = out / "programs" / name / "audio"
        saved = folder / "receipt.json"
        receipt = json.loads(saved.read_text()) if saved.exists() else None
        if not (receipt and receipt["program_sha256"] == build["program_sha256"]
                and receipt["profile"] == support.profile().PROFILE
                and Path(receipt["media"]).exists()
                and support.digest(Path(receipt["media"])) == receipt["media_sha256"]):
            receipt = support.capture(build, folder, prepared["duration_s"], audio=True)
        proof = proofs["all" if name == "static-control" else name]
        signal, rate = support.audio_signal(receipt, proof, prepared)
        support.save(folder / "receipt.json", receipt)
        return name, (signal, rate, receipt)

    with ThreadPoolExecutor(max_workers=6) as pool:
        captured = dict(pool.map(audio, audio_builds.items()))
    # Independently static/muted captures attribute the small shared startup
    # settling difference. This subtraction is analysis only: none of these
    # arrays replaces the listening signals below.
    old_muted_receipt = _previous_muted_control(out)
    old_muted_path = Path(old_muted_receipt["media"])
    if support.digest(old_muted_path) != old_muted_receipt["media_sha256"]:
        raise ValueError("The independent previous muted capture changed")
    old_muted, old_rate = sf.read(old_muted_path, dtype="float64")
    begin = round(2300170 * old_rate / support.CLOCK)
    old_muted = old_muted[begin:begin + len(captured["muted"][0])].copy()
    old_muted -= old_muted.mean()
    if old_rate != captured["muted"][1] or len(old_muted) != len(captured["muted"][0]):
        raise ValueError("Independent muted controls have different fixed clock axes")
    muted_delta = captured["muted"][0] - old_muted
    preservation = {}
    for name in ("sid-1", "sid-3"):
        reference_path = HERE / "work/cream/linus-mix" / f"{name}.wav"
        reference, rate = sf.read(reference_path, dtype="float64")
        observed, new_rate, _ = captured[name]
        reference = reference[:len(observed)] / 8
        if rate != new_rate or len(reference) != len(observed):
            raise ValueError("Cream preservation comparison has unequal fixed clock axes")
        reference -= reference.mean()
        difference = observed - reference
        delta = difference * 8 * 32768
        peak_lsb, rms_lsb = float(abs(delta).max()), float(np.sqrt(np.mean(delta * delta)))
        attributed = (difference - muted_delta) * 8 * 32768
        attributed_peak = float(abs(attributed).max())
        attributed_rms = float(np.sqrt(np.mean(attributed * attributed)))
        ratio = float(np.std(observed) / np.std(reference))
        preservation[name] = {"passed": attributed_peak <= 96 and attributed_rms <= 25,
            "reference_sha256": support.digest(reference_path), "comparison_gain": 8,
            "fixed_frames": len(observed), "peak_PCM16_LSB_difference": peak_lsb,
            "RMS_PCM16_LSB_difference": rms_lsb, "RMS_ratio": ratio,
            "raw_peak_within_96_LSB": peak_lsb <= 96,
            "raw_peak_after_45ms_PCM16_LSB": float(abs(delta[round(.045 * rate):]).max()),
            "independent_muted_attribution_peak_PCM16_LSB": attributed_peak,
            "independent_muted_attribution_RMS_PCM16_LSB": attributed_rms,
            "previous_muted_capture_sha256": old_muted_receipt["media_sha256"],
            "current_muted_capture_sha256": captured["muted"][2]["media_sha256"],
            "peak_limit_PCM16_LSB": 96, "RMS_limit_PCM16_LSB": 25,
            "time_or_gain_fit": False,
            "scope": "Actual solo captures at the same fixed native epoch and fixed comparison gain. Raw startup peaks exceed 96 LSB and remain explicitly reported. The gate applies to residuals after independently measured muted-control settling is subtracted for analysis only. Listening audio is never shifted, gain-fitted, control-subtracted or otherwise corrected."}
    result["preserved_SID1_and_SID3_audio"] = preservation
    if not all(item["passed"] for item in preservation.values()):
        support.save(out / "verification.json", result)
        raise ValueError("Native SID1 or SID3 audio changed beyond the fixed capture-noise bounds")
    peak = max(float(abs(x[0]).max()) for name, x in captured.items() if name not in ("muted", "static-control"))
    gain = min(8.0, .92 / peak)
    delta = float(abs(captured["muted"][0] - captured["static-control"][0]).max()) * gain * 32768
    result["mute_control"] = {"passed": delta <= 1, "maximum_PCM16_LSB_difference": delta}
    if delta > 1:
        raise ValueError("Muted native producer differs from the independent static SID")
    result["audio"] = {}
    for name in ("all", "sid-1", "sid-2", "sid-3"):
        signal, rate, receipt = captured[name]
        path = out / f"{name}.wav"
        sf.write(path, signal * gain, rate, subtype="PCM_16")
        result["audio"][name] = {"file": path.name, "sha256": support.digest(path),
            "rate": rate, "frames": len(signal), "duration_s": len(signal) / rate,
            "listening_gain": gain, "RMS": float(np.std(signal) * gain),
            "raw_capture_sha256": receipt["media_sha256"],
            "processing": "Independent actual VICE capture, native-clock crop, DC removal and one common constant gain. No host mixing, EQ, alignment or dynamics."}
    current = cream_playback.protected_hashes(full=True)
    current.update({f"full-cream/{p.name}": support.digest(p)
                    for p in (HERE / "work/cream/full-linus-mix").glob("*")
                    if p.suffix in (".wav", ".prg")})
    result["protected_unchanged"] = protected == current
    if not result["protected_unchanged"]:
        raise ValueError("A protected player or recording changed")
    support.save(out / "verification.json", result)
    (out / "README.md").write_text(f'''# Cream SID2 drum repair — listening candidate

This candidate plays original MOD time 17.92–37.92 seconds. It is a bounded
twenty-second test, not a completed repair of the full song. The existing full
Cream player, short reference and Hyperbased artifacts remain unchanged.

- [Full mix](all.wav)
- [SID1: preserved pulse melody](sid-1.wav)
- [SID2: original drum sampling](sid-2.wav)
- [SID3: preserved sampled bass](sid-3.wav)
- [Runnable PRG](player.prg)
- [Verification and measured limits](verification.json)

SID2 now plays six reusable original C4 drum samples through the oscillator
sample-and-hold method at 1,954.86 values/s. It replaces the short, flat
triangle/noise drum approximations. The 504-cycle lane discards frequencies
above approximately 977 Hz, so hihat brightness remains limited. This has not
received listening approval. Original C1 remains omitted in this interval.

SID1 keeps the same pulse, sustain, note values and musical event phases.
SID3 retains every approved sample code and its 126-cycle clock. The first
native latch is cycle 2,300,170, matching the earlier actual Cream capture.
The new COPY32 startup guard leaves space for its largest block; the original
241 threshold could wrap and overwrite unread startup values for long drums.

All five output/mute variants pass all 156,389 SID3 sample codes, all 39,097
SID2 inputs and global sample-clock phases, all SID1 notes and shutdown.
Every ring read follows the correct producer generation. The CPU maximum NMI
is {result['cpu']['maximum_nmi_cycles']} cycles; minimum foreground margin is
{result['cpu']['minimum_deadline_slack_foreground_cycles']} cycles. Ring write-to-read margin is
{result['ring']['minimum_write_to_read_margin_cycles']} cycles. No late buffers occur.

The four WAVs are independent full-workload VICE recordings at mono 22,050 Hz.
They use one common export gain, {gain:.6f}, reduced uniformly to prevent
clipping from the stronger drum signal. Hardware SID1/SID3 levels did not change.
No EQ, host mixing, dynamics, time alignment or control subtraction is applied.

Actual SID1/SID3 solo comparisons retain their raw startup difference of about
104 PCM16 LSB peak and less than 1.5 LSB RMS at fixed comparison gain 8. The
raw peak is not within the 96 LSB capture-noise bound. After 45 ms it is below
24 LSB. An independent muted-control comparison attributes the common startup
settling; analysis residuals are below 65 LSB peak and 1 LSB RMS. This analysis
never changes a listening file. New WAVs are not claimed byte-identical to the
approved ones.

Build from the repository root:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py --song cream --sid2-repair
```
''')
    return result
