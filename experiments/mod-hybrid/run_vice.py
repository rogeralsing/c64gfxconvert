"""Run the built PAL/6581 program and capture its actual SID output in VICE.

Register timing and PCM use separate runs. VICE's dump device bypasses PCM;
its WAV device requires warp disabled. Neither run substitutes a host mixer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

PAL_CLOCK = 985248
RATE = 22050


def symbols(path: Path) -> dict[str, int]:
    return {key: int(value, 16) for key, value in
            re.findall(r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", path.read_text())}


def trace_receipt(path: Path, duration: float, sid_voices: int = 2) -> dict:
    clock = 0
    volume_cycles = []
    voice_writes = [0] * sid_voices
    for line in path.open():
        fields = line.split()
        if len(fields) != 3:
            continue
        try:
            delta, register, value = map(int, fields)
        except ValueError:
            continue
        clock += delta
        register &= 31
        if register == 24:
            volume_cycles.append(clock)
        for voice in range(sid_voices):
            if register in (voice * 7, voice * 7 + 1, voice * 7 + 4):
                voice_writes[voice] += 1
    cycles = np.asarray(volume_cycles, dtype=np.int64)
    if len(cycles) < 100:
        raise ValueError("No sustained D418 sample stream in VICE register dump")
    gaps = np.diff(cycles)
    regular_mask = (gaps >= 160) & (gaps <= 352)
    regular = np.flatnonzero(regular_mask)
    consecutive = np.convolve(regular_mask.astype(np.int32), np.ones(32, dtype=np.int32), mode="valid")
    candidates = np.flatnonzero(consecutive == 32)
    candidates = [int(i) for i in candidates
                  if abs(int(cycles[i + 32] - cycles[i]) - 32 * 256) <= 32]
    if not candidates:
        raise ValueError("No sustained 256-cycle sample clock")
    first, last = candidates[0], int(regular[-1] + 1)
    active = cycles[first:last + 1]
    active_gaps = np.diff(active)
    span = int(active[-1] - active[0] + 256)
    expected = round(duration * PAL_CLOCK / 256)
    music = active[:expected]
    phase_error = music - music[0] - np.arange(len(music), dtype=np.int64) * 256
    receipt = {"d418_writes": len(cycles), "sample_writes": len(active),
            "expected_sample_writes": expected,
            "sample_count_error": len(active) - expected,
            "first_sample_cycle": int(active[0]), "last_sample_cycle": int(active[-1]),
            "sample_stream_duration_s": span / PAL_CLOCK,
            "sample_interval_min_cycles": int(active_gaps.min()),
            "sample_interval_max_cycles": int(active_gaps.max()),
            "sample_interval_median_cycles": float(np.median(active_gaps)),
            "gaps_over_384_cycles": int(np.sum(active_gaps > 384)),
            "score_clock_end_error_cycles": int(phase_error[-1]),
            "score_clock_phase_range_cycles": int(np.ptp(phase_error)),
            "sid_frequency_or_control_writes": voice_writes,
            "scope": "Actual emulated SID bus writes; interval jitter includes IRQ entry latency. Score-to-voice correctness is checked separately."}
    if abs(receipt["sample_count_error"]) > 2:
        raise ValueError(f"D418 stream sample count differs from score: {receipt}")
    if receipt["gaps_over_384_cycles"] or receipt["sample_interval_min_cycles"] < 128:
        raise ValueError(f"D418 stream missed or duplicated sample deadlines: {receipt}")
    if receipt["score_clock_phase_range_cycles"] >= 256:
        raise ValueError(f"D418 stream accumulated more than one sample of clock drift: {receipt}")
    if not all(voice_writes):
        raise ValueError("All SID voices must receive actual frequency/control writes")
    return receipt


def capture(prg: Path, sym: Path, out: Path, duration: float, mode: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    labels = symbols(sym)
    for key in ("start", "done", "played_tick_count", "underrun_counter"):
        if key not in labels:
            raise ValueError(f"Missing program symbol {key}")
    monitor = out / "capture.mon"
    stats = out / "runtime.bin"
    stats_start = min(labels["played_tick_count"], labels["underrun_counter"])
    stats_end = max(labels["played_tick_count"], labels["underrun_counter"]) + 1
    monitor.write_text(f'load "{prg.resolve()}" 0\n'
                       f'break exec ${labels["done"]:04x}\n'
                       f'g ${labels["start"]:04x}\n'
                       'step 20000\n'
                       f'bsave "{stats.resolve()}" 0 ${stats_start:04x} ${stats_end:04x}\n'
                       'quit\n')
    dump = out / "registers.txt"
    wav = out / "vice-raw.wav"
    command = ["/opt/homebrew/bin/x64sc", "-default", "-console", "-pal", "-seed", "1",
               "-sidmodel", "0", "-residsamp", "2", "-soundrate", str(RATE),
               "-soundoutput", "1", "-soundvolume", "100", "-initbreak", "ready",
               "-moncommands", str(monitor.resolve()),
               "-limitcycles", str(round((duration + 15) * PAL_CLOCK))]
    modes = ("registers", "audio") if mode == "both" else (mode,)
    receipt = {"program": str(prg.resolve()), "program_bytes": prg.stat().st_size,
               "program_sha256": hashlib.sha256(prg.read_bytes()).hexdigest(),
               "model": "PAL MOS6581", "sample_rate": RATE, "score_duration_s": duration}
    build_path = sym.parent / "build.json"
    if build_path.exists():
        build = json.loads(build_path.read_text())
        if build.get("prg_sha256", build.get("program_sha256")) != receipt["program_sha256"]:
            raise ValueError("Build receipt does not identify this program")
        receipt["sid_voices"] = build.get("sid_voices", 2)
    else:
        receipt["sid_voices"] = 2
    receipt_path = out / "capture.json"
    if receipt_path.exists():
        old = json.loads(receipt_path.read_text())
        if old.get("program_sha256") == receipt["program_sha256"]:
            receipt.update(old)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    for current_mode in modes:
        options = (["-sounddev", "dump", "-soundarg", str(dump.resolve()), "-warp"]
                   if current_mode == "registers" else
                   ["-sounddev", "wav", "-soundarg", str(wav.resolve()), "+warp", "-speed", "100"])
        print(f"VICE {current_mode} capture started", flush=True)
        stats.unlink(missing_ok=True)
        result = subprocess.run(command + options, text=True, capture_output=True,
                                timeout=duration + 60)
        (out / f"{current_mode}.log").write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f"VICE {current_mode} failed; inspect {out / (current_mode + '.log')}")
        raw_stats = stats.read_bytes()
        values = {key: int.from_bytes(raw_stats[labels[key] - stats_start:labels[key] - stats_start + 2], "little")
                  for key in ("played_tick_count", "underrun_counter")}
        if len(raw_stats) != stats_end - stats_start + 1:
            raise ValueError("Incomplete C64 runtime counter dump")
        receipt.setdefault("runtime", {})[current_mode] = values
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        if values["played_tick_count"] != round(duration * 50) or values["underrun_counter"]:
            raise ValueError(f"C64 sequencer did not complete all ticks without backlog: {values}")
        if current_mode == "registers":
            receipt["trace"] = trace_receipt(dump, duration, receipt["sid_voices"])
        else:
            if "trace" not in receipt:
                if not dump.exists():
                    raise ValueError("Run register capture first to anchor PCM cropping")
                receipt["trace"] = trace_receipt(dump, duration, receipt["sid_voices"])
            pcm, rate = sf.read(wav, dtype="float64", always_2d=True)
            if rate != RATE or pcm.shape[1] != 1:
                raise ValueError("Expected mono VICE output at 22050 Hz")
            anchor = round(receipt["trace"]["first_sample_cycle"] * rate / PAL_CLOCK)
            count = round(duration * rate)
            full = pcm[anchor:anchor + count, 0]
            if len(full) != count:
                raise ValueError(f"Incomplete VICE recording: {len(full)} of {count} song frames")
            full -= full.mean()
            peak = float(np.max(np.abs(full)))
            if peak < 0.001:
                raise ValueError("VICE song recording is silent")
            sf.write(out / "stardust-vice.wav", full, rate, subtype="PCM_16")
            # A common gain preserves the relative levels across full song and preview.
            gain = min(8.0, 0.92 / peak)
            listening = full * gain
            sf.write(out / "stardust-listening.wav", listening, rate, subtype="PCM_16")
            sf.write(out / "stardust-preview.wav", listening[30 * rate:50 * rate], rate, subtype="PCM_16")
            receipt["audio"] = {"frames": len(full), "duration_s": len(full) / rate,
                                "crop_start_frame": anchor, "raw_peak": peak,
                                "raw_rms": float(np.sqrt(np.mean(full * full))),
                                "listening_gain": gain, "preview_start_s": 30,
                                "preview_duration_s": 20, "warp": False,
                                "twenty_second_rms": [float(np.sqrt(np.mean(full[i:i + 20 * rate] ** 2)))
                                                      for i in range(0, len(full), 20 * rate)],
                                "note": "Audio generated by the C64 program inside VICE; DC removed and a constant listening gain applied. No host-side SID/PCM mixing."}
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        print(f"VICE {current_mode} capture complete", flush=True)
    return receipt


def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prg", type=Path, required=True)
    parser.add_argument("--symbols", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=here / "results/vice")
    parser.add_argument("--duration", type=float, default=240)
    parser.add_argument("--mode", choices=("both", "registers", "audio"), default="both")
    args = parser.parse_args()
    print(json.dumps(capture(args.prg, args.symbols, args.out, args.duration, args.mode), indent=2))


if __name__ == "__main__":
    main()
