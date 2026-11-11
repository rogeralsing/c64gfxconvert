"""Export exact SID writes to a PAL C64 program and verify them in VICE.

The player deliberately blanks the screen and spends idle time in delay loops.
It proves executability and register timing, not graphics integration or an IRQ
player's CPU consumption. VICE's installed reSID differs from pyresidfp's core;
their audio is compared as a cross-engine check, not an expected bitwise match.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from sid_render import PAL_CLOCK_HZ as PAL_CLOCK, PRE_ROLL_CYCLES, initialization_events, patch_events, render_patch


def emit_delay(cycles: int) -> list[str]:
    """Emit exact delays. The shared DEX/BNE subroutine stays within one page."""
    if cycles < 0 or cycles == 1:
        raise ValueError(f"Cannot encode a {cycles}-cycle gap")
    lines: list[str] = []
    while cycles >= 18:
        count = min(255, (cycles - 13) // 5)
        remainder = cycles - (5 * count + 13)
        if remainder == 1:
            count -= 1
        if count == 0:
            break
        lines += [f"    ldx #{count}", "    jsr delay"]
        cycles -= 5 * count + 13
    if cycles & 1:
        lines.append("    bit $02")
        cycles -= 3
    lines.extend(["    nop"] * (cycles // 2))
    return lines


def export_program(patch: dict, out: Path, duration_s: float, note_hz: float, control_hz: int) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    patch_trace = patch_events(patch, duration_s=duration_s, note_hz=note_hz, control_hz=control_hz)
    trace = list(initialization_events()) + [
        (cycle + PRE_ROLL_CYCLES, register, value) for cycle, register, value in patch_trace
    ]
    lines = [
        "// Generated research player: PAL, one SID voice, screen off.",
        "BasicUpstart2(start)",
        "start:", "    sei", "    cld", "    ldx #$ff", "    txs",
        "    lda #$7f", "    sta $dc0d", "    sta $dd0d",
        "    lda $dc0d", "    lda $dd0d", "    lda #0", "    sta $d011",
        "    sta $d015", "    lda #$35", "    sta $01", "trace_start:",
    ]
    last_cycle = 0
    for index, (cycle, register, value) in enumerate(trace):
        if index:
            lines += emit_delay(cycle - last_cycle - 6)
        lines += [f"    lda #${value:02x}", f"    sta ${0xD400 + register:04x}"]
        last_cycle = cycle
    end_cycle = PRE_ROLL_CYCLES + round(duration_s * PAL_CLOCK)
    lines += emit_delay(max(2, end_cycle - last_cycle - 6))
    # Let the audio backend flush a complete instrument window before quitting.
    # No additional register writes occur during this trailing hold.
    lines += emit_delay(round(0.02 * PAL_CLOCK))
    lines += ["done:", "    jmp done", ".align $100", "delay:", "    dex", "    bne delay", "    rts"]
    asm = out / "candidate.asm"
    asm.write_text("\n".join(lines) + "\n")
    prg = out / "candidate.prg"
    command = [str(Path.home() / ".local/bin/kickass"), str(asm.resolve()), "-o", str(prg.resolve()), "-symbolfile"]
    build = subprocess.run(command, text=True, capture_output=True, timeout=30)
    (out / "build.log").write_text(build.stdout + build.stderr)
    if build.returncode:
        raise RuntimeError(f"KickAssembler failed: {out / 'build.log'}")
    symbols = (out / "candidate.sym").read_text()
    addresses = {key: int(value, 16) for key, value in re.findall(r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", symbols)}
    monitor = out / "commands.mon"
    monitor.write_text(
        f'load "{prg.resolve()}" 0\n'
        f'break exec ${addresses["done"]:04x}\n'
        f'g ${addresses["start"]:04x}\n'
        "quit\n"
    )
    (out / "expected-events.json").write_text(json.dumps(trace, indent=2) + "\n")
    return {"trace": trace, "patch_trace": patch_trace, "monitor": monitor, "prg": prg, "addresses": addresses}


def run_vice(export: dict, out: Path, model: str, sample_rate: int) -> tuple[np.ndarray, int, list[tuple[int, int, int]]]:
    wav = out / "vice.wav"
    dump = out / "vice-registers.txt"
    command = [
        "/opt/homebrew/bin/x64sc", "-default", "-console", "-pal", "-seed", "1",
        "-sidmodel", "0" if model == "6581" else "1", "-residsamp", "2",
        "-soundrate", str(sample_rate), "-soundoutput", "1", "-soundvolume", "100",
        "-warp", "-soundwarpmode", "1", "-initbreak", "ready",
        "-moncommands", str(export["monitor"].resolve()), "-limitcycles", "5000000",
    ]
    # The dump device bypasses PCM synthesis, so bus timing and audio need
    # separate, identically seeded runs. VICE 3.10's dummy driver also fails to
    # initialize its channel count. Use the WAV device directly for PCM.
    modes = {
        "registers": ["-sounddev", "dump", "-soundarg", str(dump.resolve())],
        "audio": ["-sounddev", "wav", "-soundarg", str(wav.resolve())],
    }
    for name, options in modes.items():
        # VICE skips primary-device PCM writes in warp, even with chip emulation
        # enabled. Real-time WAV output preserves every generated PCM fragment.
        mode_options = options + (["+warp", "-speed", "100"] if name == "audio" else [])
        completed = subprocess.run(command + mode_options, capture_output=True, text=True, timeout=30)
        log_path = out / f"vice-{name}.log"
        log_path.write_text(completed.stdout + completed.stderr)
        if completed.returncode:
            raise RuntimeError(f"VICE exited {completed.returncode}: {log_path}")
    samples, rate = sf.read(wav, dtype="float64", always_2d=True)
    if samples.shape[0] == 0 or samples.shape[1] != 1 or rate != sample_rate:
        raise ValueError("VICE WAV capture must contain nonempty mono PCM at the requested sample rate")
    samples = samples.mean(axis=1)
    trace: list[tuple[int, int, int]] = []
    cycle = 0
    for line in dump.read_text().splitlines():
        values = line.split()
        if len(values) != 3:
            continue
        delta, address, value = map(int, values)
        cycle += delta
        trace.append((cycle, address & 31, value))
    return samples, rate, trace


def check_trace(expected: list, observed: list) -> dict:
    """Allow only a common startup offset, never per-event alignment."""
    expected = [tuple(event) for event in expected]
    found = None
    for start in range(len(observed) - len(expected) + 1):
        if [(r, v) for _, r, v in observed[start:start + len(expected)]] == [(r, v) for _, r, v in expected]:
            found = observed[start:start + len(expected)]
            break
    if found is None:
        return {"register_sequence_matches": False, "expected_count": len(expected), "observed_count": len(observed)}
    offset = found[0][0] - expected[0][0]
    errors = [actual[0] - target[0] - offset for target, actual in zip(expected, found)]
    return {"register_sequence_matches": True, "expected_count": len(expected), "observed_count": len(observed),
            "startup_offset_cycles": offset, "max_timing_error_cycles": max(map(abs, errors)),
            "timing_mismatches": sum(error != 0 for error in errors)}


def compare_audio(reference: np.ndarray, recorded: np.ndarray, sample_rate: int,
                  expected_start_sample: int) -> tuple[dict, np.ndarray]:
    if not len(recorded):
        raise ValueError("VICE produced no PCM audio")
    centered = reference - reference.mean()
    recording = recorded - recorded.mean()
    correlations = signal.correlate(recording, centered, mode="full", method="fft")
    lags = signal.correlation_lags(len(recording), len(centered))
    # SID initialization and BASIC boot clicks can dominate an unbounded
    # correlation. Anchor the comparison to the actual register-dump clock.
    radius = round(0.02 * sample_rate)
    admissible = np.flatnonzero((lags >= expected_start_sample - radius)
                               & (lags <= expected_start_sample + radius))
    energies = np.convolve(recording * recording, np.ones(len(reference)), mode="valid")
    candidates = []
    for index in admissible:
        offset = int(lags[index])
        if 0 <= offset < len(energies) and energies[offset] > 1e-12:
            candidates.append((abs(correlations[index]) / np.sqrt(energies[offset]), index))
    if not candidates:
        raise ValueError("No complete, non-silent instrument window near the register timeline anchor")
    lag = int(lags[max(candidates)[1]])
    aligned = np.zeros(len(reference), dtype=np.float64)
    source_start, target_start = max(0, lag), max(0, -lag)
    count = min(len(recorded) - source_start, len(reference) - target_start)
    if count > 0:
        aligned[target_start:target_start + count] = recorded[source_start:source_start + count]
    aligned_centered = aligned - aligned.mean()
    denominator = float(np.dot(aligned_centered, aligned_centered))
    gain = float(np.dot(centered, aligned_centered) / denominator) if denominator else 0.0
    error = centered - gain * aligned_centered
    correlation = float(np.corrcoef(centered, aligned_centered)[0, 1]) if denominator else 0.0
    return {"alignment_samples": lag, "alignment_seconds": lag / sample_rate,
            "timeline_expected_start_sample": expected_start_sample,
            "alignment_delta_from_timeline_samples": lag - expected_start_sample,
            "alignment_search_radius_ms": 20,
            "linear_gain_for_comparison": gain, "waveform_correlation": correlation,
            "gain_aligned_normalized_rmse": float(np.linalg.norm(error) / max(np.linalg.norm(centered), 1e-12)),
            "vice_peak": float(np.max(np.abs(aligned))), "direct_peak": float(np.max(np.abs(reference))),
            "note": "Comparison restricted to the instrument window using the SID register timeline. Different SID cores and analog models; waveform equality is not expected."}, aligned


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("patch", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=0.6)
    parser.add_argument("--note-hz", type=float, default=110.0)
    parser.add_argument("--model", choices=["6581", "8580"], default="6581")
    parser.add_argument("--control-hz", type=int, default=200)
    parser.add_argument("--sample-rate", type=int, default=22050)
    args = parser.parse_args()
    patch = json.loads(args.patch.read_text())
    exported = export_program(patch, args.out, args.duration, args.note_hz, args.control_hz)
    recorded, rate, trace = run_vice(exported, args.out, args.model, args.sample_rate)
    trace_receipt = check_trace(exported["trace"], trace)
    if not trace_receipt.get("register_sequence_matches") or trace_receipt.get("max_timing_error_cycles"):
        raise SystemExit("C64 event trace differs from direct renderer")
    direct = render_patch(patch, args.duration, rate, args.model, args.note_hz, args.control_hz)
    expected_start = round((trace_receipt["startup_offset_cycles"] + PRE_ROLL_CYCLES) * rate / PAL_CLOCK)
    instrument = recorded[expected_start:expected_start + len(direct)]
    if len(instrument) != len(direct) or np.max(np.abs(instrument)) < 0.001:
        raise ValueError("VICE did not capture a complete non-silent instrument window")
    audio_receipt, aligned = compare_audio(direct, recorded, rate, expected_start)
    sf.write(args.out / "direct.wav", direct, rate, subtype="PCM_16")
    sf.write(args.out / "vice-aligned.wav", aligned, rate, subtype="PCM_16")
    sf.write(args.out / "vice-instrument.wav", instrument, rate, subtype="PCM_16")
    receipt = {"trace": trace_receipt, "audio": audio_receipt,
               "capture": {"device": "wav", "primary_device": True, "warp": False,
                           "sample_rate": rate, "frames": len(recorded),
                           "instrument_window_frames": len(instrument),
                           "instrument_window_start_sample": expected_start,
                           "instrument_window_peak": float(np.max(np.abs(instrument))),
                           "instrument_window_rms": float(np.sqrt(np.mean(instrument * instrument))),
                           "trailing_hold_s": 0.02,
                           "dummy_driver_bug_fix": "https://github.com/VICE-Team/svn-mirror/commit/8820daf289445253de83a220a320120f4c6f34ad",
                           "note": "VICE 3.10 dummy leaves channel count uninitialized; direct WAV output with warp disabled captures PCM."},
               "program_bytes": exported["prg"].stat().st_size,
               "register_writes": len(exported["patch_trace"]), "duration_s": args.duration,
               "direct_store_cycle_lower_bound_percent": 100 * 6 * len(exported["patch_trace"]) / (args.duration * PAL_CLOCK),
               "scope": "Screen off, interrupts disabled, busy-wait research replay. Not a shared graphics/IRQ player."}
    (args.out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
    if not receipt["trace"].get("register_sequence_matches") or receipt["trace"].get("max_timing_error_cycles"):
        raise SystemExit("C64 event trace differs from direct renderer")


if __name__ == "__main__":
    main()
