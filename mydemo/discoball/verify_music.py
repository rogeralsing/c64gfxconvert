#!/usr/bin/env python3
"""Verify native PAL music cadence, presentation deadlines, SID writes and audio."""

import argparse
import array
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import wave


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location("native_verification", HERE / "vice_support.py")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
PAL_CLOCK = 985248
PAL_FRAME_CYCLES = 312 * 63
# Independent py65 execution of the original $1000 SID: song zero, sixteen calls.
ORIGINAL_SID_TRACE_SHA256 = "9aaccd20768c2bb5d8bee0d891a4544bddd7ee3f6fb287e01749457fbfeec731"
EVENT = re.compile(
    r"#(\d+) \((Trace|Stop on)\s+(exec|store) ([0-9a-fA-F]{4})\)"
    r"\s+(\d+)/\$[0-9a-fA-F]+,\s+(\d+)/\$[0-9a-fA-F]+\s*\n"
    r"(\.C:[^\n]*?\s(\d+))(?=\n|$)"
)


def checkpoint(monitor, command):
    response = monitor.run(command)
    match = re.search(r"(?:BREAK|TRACE|WATCH): (\d+)", response)
    if not match:
        raise RuntimeError(f"VICE did not create checkpoint: {response}")
    return int(match[1])


def events(response):
    return [{"checkpoint": int(m[1]), "kind": m[2], "access": m[3],
             "address": int(m[4], 16), "raster": int(m[5]),
             "raster_cycle": int(m[6]), "instruction": m[7], "cycles": int(m[8])}
            for m in EVENT.finditer(response)]


def run_native(args, output, ticks, record=False):
    labels = common.read_labels(HERE / "build" / "hexagon" / "main.sym")
    required = {"musicTick", "musicTickEnd", "rasterIRQ", "missedDeadlines"}
    if required - labels.keys():
        raise ValueError(f"Missing native symbols: {sorted(required - labels.keys())}")
    program = HERE / "build" / "hexagon" / "sprite-ball.prg"
    program_data = program.read_bytes()
    name = "audio" if record else "timing"
    snapshot = output / f"{name}-sprite-ball.prg"
    snapshot.write_bytes(program_data)
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    command = common.vice_command(args.vice, snapshot, port, ROOT / "palettes" / "colodore.vpl")
    command += ["-sound", "-sidmodel", "1", "-soundwarpmode", "1", "-initbreak", "reset"]
    audio = output / "sid-output.wav"
    if record:
        audio.unlink(missing_ok=True)
        command[command.index("-sounddev") + 1] = "coreaudio"
        command += ["-soundrecdev", "wav", "-soundrecarg", str(audio)]
    else:
        command += ["-warp"]
    monitor = connection = None
    collected = []
    with (output / f"{name}-vice.log").open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            connection = common.connect_monitor(process, port)
            monitor = common.Monitor(connection)
            monitor.run("r")
            monitor.run("sidefx off")
            checkpoint(monitor, f"break {labels['musicTick']:04x}")
            monitor.run("x")
            pc, raster, first_cycles = monitor.registers()
            if pc != labels["musicTick"]:
                raise AssertionError(f"Stopped before music at unexpected PC ${pc:04x}")
            initial = monitor.memory(output / f"{name}-initial-zero-page.bin", 0, 255)
            if initial[labels["missedDeadlines"]]:
                raise AssertionError("Presentation deadline missed before first music call")
            if not record:
                monitor.run("warp on")
            monitor.run("delete")
            checkpoint(monitor, f"trace exec {labels['musicTick']:04x}")
            checkpoint(monitor, f"trace exec {labels['musicTickEnd']:04x}")
            checkpoint(monitor, f"trace exec {labels['rasterIRQ']:04x}")
            finished = checkpoint(monitor, f"break {labels['musicTickEnd']:04x}")
            deadline = checkpoint(monitor, f"watch store {labels['missedDeadlines']:04x}")
            sid = checkpoint(monitor, "trace store d400 d418")
            # Stop immediately on every missed deadline, including counter wraps.
            # SID tracing is needed only for the first sixteen complete calls.
            first_batch = min(ticks, 16)
            for count in (first_batch, ticks - first_batch):
                if not count:
                    continue
                monitor.run(f"ignore {finished} ${count - 1:x}")
                response = monitor.run("x")
                batch = events(response)
                collected.extend(batch)
                if any(e["checkpoint"] == deadline for e in batch):
                    raise AssertionError("Native music caused a presentation deadline miss")
                pc, _, _ = monitor.registers()
                if pc != labels["musicTickEnd"]:
                    raise AssertionError(f"Unexpected native stop at ${pc:04x}")
                monitor.run(f"disable {sid}")
            final = monitor.memory(output / f"{name}-final-zero-page.bin", 0, 255)
            if final[labels["missedDeadlines"]]:
                raise AssertionError("Native presentation deadline counter is nonzero")
            # The current first instruction is suppressed when a breakpoint resumes.
            # Preserve its directly observed stopwatch as the first call boundary.
            starts = [first_cycles] + [e["cycles"] for e in collected if e["kind"] == "Trace"
                                      and e["access"] == "exec" and e["address"] == labels["musicTick"]]
            ends = [e["cycles"] for e in collected if e["kind"] == "Trace"
                    and e["access"] == "exec" and e["address"] == labels["musicTickEnd"]]
            irqs = [e["cycles"] for e in collected if e["kind"] == "Trace"
                    and e["access"] == "exec" and e["address"] == labels["rasterIRQ"]]
            if len(starts) != ticks or len(ends) != ticks or len(irqs) != ticks - 1:
                raise AssertionError(f"Music is not called once per IRQ: {len(starts)=}, {len(ends)=}, {len(irqs)=}")
            durations = [end - start for start, end in zip(starts, ends)]
            if not all(0 < duration < PAL_FRAME_CYCLES for duration in durations):
                raise AssertionError("Music routine exceeded one PAL frame")
            intervals = [b - a for a, b in zip(irqs, irqs[1:])]
            if any(abs(interval - PAL_FRAME_CYCLES) > 8 for interval in intervals):
                raise AssertionError("Music IRQ does not occur once per PAL frame")
            # Each IRQ must contain exactly one whole music invocation.
            for index, irq in enumerate(irqs, 1):
                next_irq = irqs[index] if index < len(irqs) else ends[-1] + 1
                if not irq <= starts[index] < ends[index] < next_irq:
                    raise AssertionError("Music call escaped its raster IRQ")
            stores = [e for e in collected if e["kind"] == "Trace" and e["access"] == "store"
                      and 0xd400 <= e["address"] <= 0xd418]
            voices = {0xd404, 0xd40b, 0xd412}
            if not voices <= {e["address"] for e in stores}:
                raise AssertionError("Native SID writes did not reach all three voices")
            values = []
            for event in stores:
                line = event["instruction"]
                mnemonic = re.search(r"\s(STA|STX|STY)\s", line)
                if not mnemonic:
                    raise AssertionError(f"Unsupported SID store trace: {line}")
                register = {"STA": "A", "STX": "X", "STY": "Y"}[mnemonic[1]]
                value = re.search(rf"\b{register}:([0-9a-fA-F]{{2}})", line)
                values.append((event["address"], int(value[1], 16)))
            if len(stores) < first_batch * 8 or len(set(values)) < 8 or not any(v for _, v in values):
                raise AssertionError("Native SID output did not change meaningfully")
            trace_sha256 = hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()
            if first_batch == 16 and trace_sha256 != ORIGINAL_SID_TRACE_SHA256:
                raise AssertionError("Native SID writes differ from independent original-tune execution")
            report = {
                "ticks": ticks, "pal_clock_hz": PAL_CLOCK, "cycles_per_video_frame": PAL_FRAME_CYCLES,
                "music_hz": PAL_CLOCK / PAL_FRAME_CYCLES,
                "emulated_seconds": ticks * PAL_FRAME_CYCLES / PAL_CLOCK,
                "irq_interval_cycles": [min(intervals), max(intervals)] if intervals else [],
                "music_call_elapsed_cycles_including_jsr_and_vic_stalls": [min(durations), max(durations)],
                "music_call_mean_elapsed_cycles": sum(durations) / len(durations),
                "missed_deadlines": 0, "deadline_write_watch_active": True,
                "sid_calls_traced": first_batch, "actual_sid_stores": len(stores),
                "distinct_sid_register_values": len(set(values)),
                "sid_trace_sha256": trace_sha256,
                "independent_original_sid_trace_matched": first_batch == 16,
                "prg_sha256": hashlib.sha256(program_data).hexdigest(),
                "sid_model": "8580", "sound_emulated_during_warp": True,
            }
            (output / f"{name}-sid-stores.json").write_text(json.dumps(values) + "\n")
            return report
        finally:
            if monitor:
                (output / f"{name}-monitor.txt").write_text("\n".join(monitor.transcript))
            if connection:
                try:
                    connection.sendall(b"quit\n")
                except OSError:
                    pass
                connection.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)


def check_audio(path):
    with wave.open(str(path)) as recording:
        if recording.getsampwidth() != 2 or recording.getnchannels() not in (1, 2):
            raise AssertionError("VICE did not record 16-bit mono/stereo audio")
        samples = array.array("h", recording.readframes(recording.getnframes()))
        if sys.byteorder != "little":
            samples.byteswap()
        seconds = recording.getnframes() / recording.getframerate()
        rate = recording.getframerate()
    if not samples:
        raise AssertionError("VICE audio recording is empty")
    peak = max(abs(value) for value in samples) / 32768
    rms = math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768
    if seconds < 4 or peak < 0.01 or rms < 0.002:
        raise AssertionError(f"VICE audio is silent or too short: {seconds=}, {peak=}, {rms=}")
    return {"path": str(path), "seconds": seconds, "sample_rate": rate, "peak": peak, "rms": rms}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticks", type=int, default=20000,
                        help="Consecutive native PAL music calls; default covers about 399 seconds")
    parser.add_argument("--record", action="store_true",
                        help="Also record and check six seconds of native 8580 audio through CoreAudio")
    parser.add_argument("--vice", default=shutil.which("x64sc"))
    args = parser.parse_args()
    if args.ticks < 4 or not args.vice:
        parser.error("At least four ticks and an x64sc executable are required")
    output = HERE / "build" / "hexagon" / "music-verification"
    output.mkdir(parents=True, exist_ok=True)
    report = {"timing": run_native(args, output, args.ticks)}
    if args.record:
        report["audio_native"] = run_native(args, output, 300, record=True)
        report["audio"] = check_audio(output / "sid-output.wav")
        (output / "audio-report.json").write_text(json.dumps(
            {"audio_native": report["audio_native"], "audio": report["audio"]}, indent=2) + "\n")
    (output / "timing-report.json").write_text(json.dumps(report["timing"], indent=2) + "\n")
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
