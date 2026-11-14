#!/usr/bin/env python3
"""Record actual VIC-II PAL fields, then mux verified native VICE audio.

No source screen matrix or font is used to create the pictures. Every image
comes from VICE's screenshot command after a completed native PAL field.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys


HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parent
REPO = EXPERIMENT.parents[1]
CLOCK, FIELD = 985248, 19656


def module(path, name):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(build_folder: Path, output: Path):
    build = json.loads((build_folder / "build.json").read_text())
    package = json.loads((build_folder / "packaging.json").read_text())
    labels = build["symbols"]
    program = Path(build["program"])
    identity = sha(program)
    assert identity == build["program_sha256"] == package["programSha256"]
    assert not build["loop"], "Capture one complete non-looping native cycle"
    audio = module(EXPERIMENT / "verify.py", "native_capture_audio")
    native = module(REPO / "asm/sphere-polygons/verify-c64.py", "native_capture_monitor")
    duration = len((build_folder / "expected-input.bin").read_bytes()) * audio.PERIOD / CLOCK
    output.mkdir(parents=True, exist_ok=True)
    fields = output / "fields"
    fields.mkdir(exist_ok=True)
    if list(fields.glob("field-*.png")):
        raise ValueError("Capture output already contains fields; choose a fresh output directory")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    trace = output / "sid-registers.txt"
    trace.unlink(missing_ok=True)
    command = ["rtk", "proxy", *audio.profile().vice_command(), "+saveres", "-seed", "1",
               "-minimized", "+warp", "-speed", "100", "+confirmonexit",
               "+refreshonbreak", "+binarymonitor", "-initbreak", "ready",
               "-sounddev", "dump", "-soundarg", str(trace.resolve()),
               "-limitcycles", str(90 * CLOCK), "-VICIIfilter", "0", "-VICIIextpal",
               "-VICIIpalette", str(REPO / "palettes/colodore.vpl"),
               "-VICIIsaturation", "1000", "-VICIIcontrast", "1000",
               "-VICIIbrightness", "1000", "-VICIIgamma", "1000",
               "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    process = connection = monitor = None
    receipt = dict(program=str(program), programSha256=identity, command=command,
                   profile=audio.profile().PROFILE, frames=[], passed=False,
                   pictureSource="Actual VICE scrsh output; no character/font reconstruction",
                   captureRefreshOnBreak=False, palClock=CLOCK, fieldCycles=FIELD,
                   frameRate=f"{CLOCK}/{FIELD}", audioDurationSeconds=duration)
    try:
        with (output / "vice.log").open("w") as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            receipt["ownedPid"] = process.pid
            connection = native.connect(process, port)
            monitor = native.Monitor(connection)
            monitor.run("sidefx off")
            monitor.run(f'load "{program}" 0')
            restore_break = monitor.checkpoint(package["symbols"]["restore_done"])
            monitor.run(f'g ${package["symbols"]["unpack_start"]:04x}')
            assert monitor.registers()["pc"] == package["symbols"]["restore_done"]
            monitor.run(f"delete {restore_break}")
            start_break = monitor.checkpoint(labels["sample_clock_start"])
            monitor.run("g")
            start = monitor.registers()
            assert start["pc"] == labels["sample_clock_start"]
            receipt["sampleClockStart"] = start
            monitor.run(f"delete {start_break}")
            response = monitor.run("break exec $0000 $ffff if RL == $000")
            raster_break = int(re.search(r"BREAK:\s*(\d+)", response)[1])
            stop_clock = start["clock"] + math.ceil(duration * CLOCK) + 2 * FIELD
            while True:
                monitor.run("x")
                registers = monitor.registers()
                assert registers["raster"] == 0
                index = len(receipt["frames"])
                picture = fields / f"field-{index:04d}.png"
                monitor.run(f'scrsh "{picture.resolve()}" 2')
                assert picture.exists()
                receipt["frames"].append(dict(index=index, **registers,
                                              file=str(picture.resolve()), sha256=sha(picture)))
                if index % 50 == 0:
                    print(json.dumps(dict(phase="actual-pal-fields", fields=index + 1,
                                          nativeSeconds=(registers["clock"]-start["clock"])/CLOCK)), flush=True)
                if registers["clock"] >= stop_clock:
                    break
                # Leave raster line zero with the checkpoint disabled. This
                # advances genuine emulated instructions, not injected time.
                monitor.run(f"disable {raster_break}")
                monitor.run("step 100")
                assert monitor.registers()["raster"] != 0
                monitor.run(f"enable {raster_break}")
            try:
                monitor.run("quit")
            except ConnectionError:
                pass
            process.wait(timeout=15)
            assert process.returncode == 0
    finally:
        if monitor:
            (output / "monitor.log").write_text("\n".join(monitor.transcript))
        if connection:
            connection.close()
        if process and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
        save(output / "capture.json", receipt)
    proof = audio.verify_sid_trace(trace, (build_folder / "expected-input.bin").read_bytes())
    save(output / "register-check.json", proof)
    assert proof["passed"]
    first = proof["firstAudibleSampleCycle"]
    selected = min(range(len(receipt["frames"])), key=lambda i: abs(receipt["frames"][i]["clock"]-first))
    gap = receipt["frames"][selected]["clock"] - first
    deltas = [b["clock"]-a["clock"] for a,b in zip(receipt["frames"],receipt["frames"][1:])]
    assert all(abs(delta-FIELD) <= 16 for delta in deltas), "A native PAL field was skipped"
    assert abs(gap) <= FIELD
    assert sha(program) == identity
    receipt.update(passed=True, firstAudibleSampleCycle=first, selectedFirstField=selected,
                   firstVideoFieldMinusFirstAudioCycles=gap,
                   firstVideoFieldMinusFirstAudioSeconds=gap/CLOCK,
                   quantization="Nearest actual PAL-field boundary; no audio offset fit or time stretch",
                   fieldCycleDeltaMin=min(deltas), fieldCycleDeltaMax=max(deltas),
                   capturedFields=len(receipt["frames"]),
                   uniqueNativePictures=len({frame["sha256"] for frame in receipt["frames"]}),
                   sidProof="register-check.json")
    save(output / "capture.json", receipt)
    return receipt


def mux(output: Path, audio_path: Path):
    receipt = json.loads((output / "capture.json").read_text())
    assert receipt["passed"]
    audio_path = audio_path.resolve()
    verification = json.loads((audio_path.parent / "verification.json").read_text())
    audio_check_path = audio_path.parent / "audio-check.json"
    audio_check = json.loads(audio_check_path.read_text())
    audio_identity = sha(audio_path)
    assert verification["passed"] and audio_check["passed"]
    assert verification["programSha256"] == receipt["programSha256"], "Audio belongs to another PRG"
    assert verification["audio"]["sha256"] == audio_check["sha256"] == audio_identity
    assert Path(verification["audio"]["file"]).resolve() == audio_path
    target = output / "c64-original.mp4"
    command = ["rtk", "proxy", "ffmpeg", "-v", "error", "-y", "-framerate", f"{CLOCK}/{FIELD}",
               "-start_number", str(receipt["selectedFirstField"]),
               "-i", str(output / "fields/field-%04d.png"), "-i", str(audio_path.resolve()),
               "-map", "0:v:0", "-map", "1:a:0", "-vf",
               "crop=320:200:32:35,scale=600:400:flags=neighbor,setsar=1",
               "-t", str(receipt["audioDurationSeconds"]), "-c:v", "libx264", "-preset", "fast",
               "-crf", "10", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
               "-movflags", "+faststart", str(target)]
    subprocess.run(command, check=True, timeout=60)
    result = dict(passed=True, programSha256=receipt["programSha256"],
                  video=str(target.resolve()), videoSha256=sha(target),
                  audio=str(audio_path), audioSha256=audio_identity, command=command,
                  audioVerificationSha256=sha(audio_path.parent / "verification.json"),
                  audioCheckSha256=sha(audio_check_path), audioProgramMatchesCapture=True,
                  pictureSource=receipt["pictureSource"], audioSource="Verified actual native VICE WAV",
                  firstFieldQuantizationSeconds=receipt["firstVideoFieldMinusFirstAudioSeconds"],
                  timeStretch=False, sourceBitmapReconstruction=False)
    save(output / "video.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=EXPERIMENT / "work/original-c64/player")
    parser.add_argument("--output", type=Path, default=EXPERIMENT / "work/original-c64/capture")
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--skip-capture", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    result = json.loads((output / "capture.json").read_text()) if args.skip_capture else capture(args.build.resolve(), output)
    if args.audio:
        result = mux(output, args.audio)
    print(json.dumps({key:value for key,value in result.items() if key not in ("frames","command")}, indent=2), flush=True)


if __name__ == "__main__":
    main()
