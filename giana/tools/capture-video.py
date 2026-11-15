#!/usr/bin/env python3
"""Capture the complete true-drive demo as native PAL PNGs and same-instance PCM."""

from pathlib import Path
import argparse
import array
import hashlib
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import wave

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mydemo/discoball"))
from vice_support import Monitor, connect_monitor, read_labels, vice_command

CPU_HZ = 985248
PAL_CYCLES = 19656
PAL_FPS = "13684/273"
MCI_FIELDS = 1504  # 30.0052616194 seconds; muxing may trim the final field.


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checkpoint(monitor, expression):
    response = monitor.run(expression)
    match = re.search(r"BREAK:\s*(\d+)", response)
    assert match, response
    return int(match[1])


def capture(args):
    output = ROOT / "giana/build/video" / args.name
    output.mkdir(parents=True, exist_ok=False)
    disk = ROOT / "giana/build/giana.d64"
    runtime = ROOT / "giana/build/giana-unpacked.prg"
    labels = read_labels(ROOT / "giana/build/main.sym")
    state_address = labels["mciState"]
    assert labels["mciFieldCounter"] == state_address + 3
    assert labels["mciPhase"] == state_address + 2
    raw_audio = output / "native-all-audio.wav"
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    command = vice_command(args.emulator, disk, port, ROOT / "palettes/peptoette-a.vpl")
    # Keep the established non-warp WAV path: no host device, gain adjustment,
    # waveform fitting, or separate emulator is involved in the recording.
    command += ["-initbreak", "reset", "-drive8truedrive", "-sounddev", "wav",
                "-soundarg", str(raw_audio), "-soundrate", "44100", "-soundoutput", "1",
                "-soundvolume", "100", "-sidengine", "1", "-sidmodel", "0",
                "-residsamp", "2", "-seed", "1"]
    receipt = {
        "passed": False, "command": command, "disk_sha256": digest(disk.read_bytes()),
        "runtime_prg_sha256": digest(runtime.read_bytes()), "true_drive_demo_disk": True,
        "pal_fps": PAL_FPS, "pal_cycles": PAL_CYCLES, "cpu_hz": CPU_HZ,
        "sample_raster": 44, "requested_mci_fields": MCI_FIELDS,
        "requested_mci_seconds": 30, "limit_frames": args.limit_frames,
        "max_frames": args.max_frames,
    }
    process = connection = monitor = None
    boundaries = []
    tail = []
    phase_hashes = {}
    stage_changes = []
    previous_stage = None
    onset_index = None
    captured = 0
    started = time.monotonic()
    try:
        with (output / "vice.log").open("w") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            connection = connect_monitor(process, port)
            connection.settimeout(180)
            monitor = Monitor(connection)
            connection.settimeout(180)
            monitor.run("r")
            monitor.run("sidefx off")
            # Spindle's temporary boot code shares PCs with the later game.
            # No global checkpoint exists until job0 restores the real runtime.
            startup = checkpoint(monitor, f'break ${labels["initTerrain"]:04x}')
            monitor.run("x")
            pc, raster, cycles = monitor.registers()
            assert pc == labels["initTerrain"], ("Startup gate", pc, raster)
            receipt["startup_gate_cycle"] = cycles
            monitor.run(f"disable {startup}")
            ready = checkpoint(monitor, f'break ${labels["waitBorder"]:04x}')
            monitor.run("x")
            pc, raster, cycles = monitor.registers()
            assert pc == labels["waitBorder"], ("Music-initialized gate", pc, raster)
            receipt["music_initialized_gate_cycle"] = cycles
            monitor.run(f"disable {ready}")
            monitor.run("bank cpu")
            global_break = checkpoint(monitor, "break exec $0000 $ffff if RL == $002c")
            connection.settimeout(30)

            def sample():
                monitor.run("x")
                pc, raster, cycles = monitor.registers()
                assert raster == 44, ("Boundary raster", pc, raster, cycles)
                # All five bytes are RAM under every loader mapping. Exactly
                # one safe control read per boundary; no old game data reads.
                control = monitor.memory(output / "mci-control.bin", state_address,
                                         state_address + 4)
                return cycles, control

            def leave_boundary():
                monitor.run(f"disable {global_break}")
                monitor.run("step $40")
                _, raster, _ = monitor.registers()
                assert 44 < raster < 64, ("Failed to leave boundary before music", raster)
                monitor.run(f"enable {global_break}")

            cycles, control = sample()
            # If initialization happened unusually early, do not include a
            # still-blank interval before the initial lower-border reveal.
            den = monitor.memory(output / "startup-den.bin", 0xd011, 0xd011)[0] & 0x10
            if not den:
                leave_boundary()
                cycles, control = sample()
                den = monitor.memory(output / "startup-den.bin", 0xd011, 0xd011)[0] & 0x10
                assert den, "Initial display was not revealed within a PAL frame"
            boundaries.append(cycles)

            for image_index in range(args.max_frames):
                leave_boundary()
                cycles, control = sample()
                interval = cycles - boundaries[-1]
                assert abs(interval - PAL_CYCLES) <= 9, (image_index, "PAL cadence", interval)
                boundaries.append(cycles)
                screenshot = output / f"frame-{image_index:05d}.png"
                monitor.run(f'screenshot "{screenshot}" 2')
                captured += 1
                state, stage, live_phase = control[:3]
                complete_count = int.from_bytes(control[3:5], "little")
                if (state, stage) != previous_stage:
                    stage_changes.append({"image_index": image_index, "cycles": cycles,
                                          "state": state, "stage": stage})
                    previous_stage = state, stage
                if state == 2 and complete_count >= 1:
                    if onset_index is None:
                        assert complete_count == 1 and live_phase == 1, ("First MCI field", list(control))
                        onset_index = image_index
                        receipt["mci_onset_image_index"] = image_index
                        receipt["mci_onset_video_seconds"] = image_index * PAL_CYCLES / CPU_HZ
                        receipt["mci_onset_interval_start_cycle"] = boundaries[-2]
                        receipt["mci_first_completed_sample_cycle"] = cycles
                        print(f"{args.name}: MCI A field begins at image {image_index}", flush=True)
                    expected_count = len(tail) + 1
                    assert complete_count == expected_count, ("MCI field skipped/repeated", complete_count, expected_count)
                    completed_phase = live_phase ^ 1
                    assert completed_phase == len(tail) % 2, ("MCI phase", completed_phase, len(tail))
                    with Image.open(screenshot) as image:
                        rgb = image.convert("RGB")
                        receipt.setdefault("screenshot_size", list(rgb.size))
                        field_hash = digest(rgb.crop((32, 35, 352, 235)).tobytes())
                    phase_hashes.setdefault(str(completed_phase), field_hash)
                    assert phase_hashes[str(completed_phase)] == field_hash, ("MCI field pixels changed", image_index)
                    tail.append({"image_index": image_index, "cycles": cycles,
                                 "complete_counter": complete_count, "completed_phase": completed_phase,
                                 "live_phase": live_phase, "active_rgb_sha256": field_hash})
                if captured % 256 == 0:
                    print(f"{args.name}: {captured} native PAL intervals; MCI {len(tail)}/{MCI_FIELDS}", flush=True)
                if len(tail) == MCI_FIELDS or args.limit_frames and captured >= args.limit_frames:
                    break
            else:
                raise AssertionError(f"The complete MCI tail was not reached within {args.max_frames} frames")
            # Drain the WAV writer through a final real guest interval. This
            # last interval has no PNG and is outside the delivered AV range.
            leave_boundary()
            flush_cycle, _ = sample()
            assert abs(flush_cycle - boundaries[-1] - PAL_CYCLES) <= 9
            receipt.update({"guest_start_cycle": boundaries[0], "guest_end_cycle": boundaries[-1],
                            "guest_flush_cycle": flush_cycle, "video_frames": captured,
                            "frame_cycle_timestamps": boundaries, "mci_fields": tail,
                            "mci_phase_rgb_sha256": phase_hashes, "mci_load_stage_changes": stage_changes,
                            "complete_demo": len(tail) == MCI_FIELDS,
                            "native_seconds": captured * PAL_CYCLES / CPU_HZ,
                            "actual_guest_cycle_interval": boundaries[-1] - boundaries[0]})
    finally:
        if monitor:
            (output / "monitor.log").write_text("\n".join(monitor.transcript))
        if connection:
            try:
                connection.sendall(b"quit\n")
            except OSError:
                pass
            connection.close()
        if process:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        receipt["elapsed_host_seconds"] = round(time.monotonic() - started, 3)
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

    with wave.open(str(raw_audio), "rb") as audio:
        rate, channels, width = audio.getframerate(), audio.getnchannels(), audio.getsampwidth()
        raw_pcm = audio.readframes(audio.getnframes())
    assert (rate, channels, width) == (44100, 1, 2), (rate, channels, width)
    raw_frames = len(raw_pcm) // 2
    expected_raw = round(receipt["guest_flush_cycle"] * rate / CPU_HZ)
    raw_error = raw_frames - expected_raw
    assert abs(raw_error) <= 1024, ("WAV differs from guest clock", raw_frames, expected_raw, raw_error)
    first = round(boundaries[0] * rate / CPU_HZ)
    count = round(captured * PAL_CYCLES * rate / CPU_HZ)
    pcm = raw_pcm[first * 2:(first + count) * 2]
    assert len(pcm) == count * 2, "Native WAV does not cover the video range"
    samples = array.array("h", pcm)
    peak = max(map(abs, samples))
    assert peak > 100, ("Unexpected silent capture", peak)
    longest = run = 0
    for sample in samples:
        run = run + 1 if sample == 0 else 0
        longest = max(longest, run)
    assert longest < rate // 20, ("Unexpected >=50 ms zero PCM gap", longest)
    final_audio = output / "native-interval-audio.wav"
    with wave.open(str(final_audio), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(pcm)
    receipt.update({"passed": True, "audio_frames": count, "audio_rate": rate,
                    "audio_duration_seconds": count / rate, "raw_audio_frames": raw_frames,
                    "raw_audio_vs_guest_clock_error_samples": raw_error,
                    "audio_crop_start_sample": first, "audio_peak_pcm16": peak,
                    "audio_rms_pcm16": math.sqrt(sum(sample * sample for sample in samples) / len(samples)),
                    "longest_zero_pcm_run_samples": longest, "audio_sha256": digest(final_audio.read_bytes()),
                    "processing": "One emulator, native PAL PNGs and WAV PCM; guest-clock crop only.",
                    "phase": "PNG N is the completed image sampled at r44_(N+1), for PCM interval r44_N to r44_(N+1). MCI live phase has already advanced; completed phase is live phase xor 1."})
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({key: value for key, value in receipt.items()
                      if key not in ("command", "frame_cycle_timestamps", "mci_fields")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="Output directory below giana/build/video")
    parser.add_argument("--max-frames", type=int, default=11000)
    parser.add_argument("--limit-frames", type=int, help="Stop early for a native AV smoke capture")
    parser.add_argument("--emulator", default=os.environ.get("VICE") or shutil.which("x64sc"),
                        help="VICE x64sc executable (default: VICE or PATH)")
    options = parser.parse_args()
    if not options.emulator:
        parser.error("x64sc was not found; set VICE or pass --emulator")
    if Path(options.name).name != options.name or options.name in (".", ".."):
        parser.error("--name must be a fresh directory name below giana/build/video")
    assert options.max_frames > 0
    assert options.limit_frames is None or 0 < options.limit_frames <= options.max_frames
    capture(options)
