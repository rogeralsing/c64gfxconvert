#!/usr/bin/env python3
"""Check cold disk startup and every real VIC-II movie frame with SID audio.

The packed PRG must boot through an ordinary true-drive LOAD. Before native
entry, every restored RAM byte is compared with the uncompressed image. The
same owned C64 then plays all frames while its actual SID writes are recorded.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import subprocess

import numpy as np


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FIELD_CYCLES = 19656


def module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


audio = module(HERE / "verify.py", "whistle_audio_proof")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def frame_pixels(screen: bytes, font: bytes) -> bytes:
    masks = np.unpackbits(np.frombuffer(font, dtype=np.uint8)).reshape(-1, 8, 8)
    glyphs = masks[np.frombuffer(screen, dtype=np.uint8)]
    gray = np.where(glyphs, 0, 255).astype(np.uint8)
    raster = gray.reshape(25, 40, 8, 8).transpose(0, 2, 1, 3).reshape(200, 320)
    return np.repeat(raster[..., None], 3, axis=2).tobytes()


def screenshot_pixels(path: Path) -> bytes:
    return subprocess.check_output([
        "rtk", "proxy", "ffmpeg", "-v", "error", "-i", str(path),
        "-vf", "crop=320:200:32:35", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"])


def timings(folder: Path) -> dict:
    """Retain all presentation deadlines when diagnosing a failed AV bound."""
    folder = folder.resolve()
    build = json.loads((folder / "build.json").read_text())
    program = Path(build["program"])
    version = digest(program.read_bytes())[:12]
    out = folder / f"verification/timing-{version}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "player.prg").write_bytes(program.read_bytes())
    (out / "packaging.json").write_bytes((folder / "packaging.json").read_bytes())
    build["program"] = str(out / "player.prg")
    audio.save(out / "build.json", build)
    points = {name: build["symbols"][name] for name in
              ("producer_done", "consumer_activate", "presented", "prepare_start", "prepared")}
    receipt = audio.capture(build, out / "registers", 8., points=points)
    names = {address: name for name, address in points.items()}
    observed = {name: [] for name in points}
    pattern = re.compile(r"^\.C:([0-9a-fA-F]{4})\s+.*\s(\d+)$")
    for line in Path(receipt["monitorLog"]).read_text().splitlines():
        match = pattern.match(line)
        if match and int(match[1], 16) in names:
            observed[names[int(match[1], 16)]].append(int(match[2]))
    proof = audio.verify_sid_trace(Path(receipt["media"]),
                                   (folder / "expected-input.bin").read_bytes())
    records = []
    for index, cycle in enumerate(observed["presented"]):
        target = build["film"]["sampleDeadlines"][index]
        delay = cycle - proof["firstAudibleSampleCycle"] - target * audio.PERIOD
        preparation = (observed["prepared"][index - 1]
                       - observed["prepare_start"][index - 1]) if index else 0
        records.append({"frame": index, "presentClock": cycle, "targetSample": target,
                        "delaySeconds": delay / audio.CLOCK,
                        "prepareWallCycles": preparation})
    result = {"programSha256": version, "presentations": len(records),
              "maximumAVDelaySeconds": max(row["delaySeconds"] for row in records),
              "lastFrameBeforeAudioEndCycles": proof["fullSampleHoldEndCycle"]
                                               - records[-1]["presentClock"],
              "records": records}
    audio.save(out / "timing.json", result)
    print(json.dumps(result, indent=2))
    return result


def verify(folder: Path, *, direct_front: bool = False) -> dict:
    folder = folder.resolve()
    metadata = json.loads((folder / "build.json").read_text())
    packaging = json.loads((folder / "packaging.json").read_text())
    labels = metadata["symbols"]
    program = Path(metadata["program"])
    native_program = Path(metadata["native_program"])
    original = native_program.read_bytes()
    first = int.from_bytes(original[:2], "little")
    last = first + len(original) - 2
    assert digest(program.read_bytes()) == packaging["programSha256"]
    assert digest(original) == packaging["nativeSha256"]
    assert packaging["loadEndExclusive"] <= 0xd000
    screens = (folder / "expected-screen.frames").read_bytes()
    font = (folder / "font.bin").read_bytes()
    expected_audio = (folder / "expected-input.bin").read_bytes()
    film = metadata["film"]
    count = film["frameCount"]
    assert len(screens) == count * 1000 and len(font) == 2048
    expected = [frame_pixels(screens[i * 1000:(i + 1) * 1000], font) for i in range(count)]
    for pixels, wanted in zip(expected, film["expectedRGBAHashes"]):
        rgb = np.frombuffer(pixels, dtype=np.uint8).reshape(200, 320, 3)
        rgba = np.concatenate((rgb, np.full((200, 320, 1), 255, dtype=np.uint8)), axis=2)
        assert digest(rgba.tobytes()) == wanted
    out = folder / "verification/av-cold-start"
    out.mkdir(parents=True, exist_ok=True)
    native = module(REPO / "asm/sphere-polygons/verify-c64.py", "whistle_native_monitor")
    # The shared monitor module imports Pillow for its unrelated geometry tools.
    # This verifier only uses its socket monitor, not those image helpers.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    palette = REPO / "palettes/colodore.vpl"
    sid_trace = out / "registers.txt"
    (out / "autostart.d64").unlink(missing_ok=True)
    sid_trace.unlink(missing_ok=True)
    command = ["rtk", "proxy", *audio.profile().vice_command(), "+saveres", "-minimized",
               "-warp", "-speed", "100", "+confirmonexit", "+refreshonbreak", "+binarymonitor",
               "-initbreak", "reset", "-drive8truedrive", "-autostartprgmode", "2",
               "-autostartprgdiskimage", str(out / "autostart.d64"),
               "-autostart", str(program), "-sounddev", "dump", "-soundarg", str(sid_trace),
               "-limitcycles", str(608 * audio.CLOCK), "-VICIIfilter", "0",
               "-VICIIextpal", "-VICIIpalette", str(palette),
               "-VICIIsaturation", "1000", "-VICIIcontrast", "1000",
               "-VICIIbrightness", "1000", "-VICIIgamma", "1000",
               "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    report = {"passed": False, "programSha256": digest(program.read_bytes()),
              "nativeSha256": digest(original), "command": command, "frames": [],
              "scope": "True-drive disk LOAD, all restored native RAM before entry, "
                       f"then all{count} completed screen matrices and complete screen-on SID trace "
                       "in the same owned C64. No frame or source-time injection.",
              "directFrontBuffer": direct_front}
    process = connection = monitor = None
    try:
        with (out / "vice.log").open("w") as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            report["ownedPid"] = process.pid
            connection = native.connect(process, port)
            monitor = native.Monitor(connection)
            monitor.run("sidefx off")
            restore_break = monitor.checkpoint(packaging["symbols"]["restore_done"])
            monitor.run("x")
            at_restore = monitor.registers()
            assert at_restore["pc"] == packaging["symbols"]["restore_done"]
            entry_break = monitor.checkpoint(labels["start"])
            monitor.run(f"delete {restore_break}")
            monitor.run("x")
            at_entry = monitor.registers()
            assert at_entry["pc"] == labels["start"]
            monitor.run("bank ram")
            restored = monitor.dump(out / "restored-native.bin", first, last - 1)
            assert restored == original[2:], "Cold loader changed restored native RAM"
            monitor.run("bank cpu")
            port_state = monitor.dump(out / "entry-port.bin", 0, 1)
            assert port_state[1] & 7 == 5, "Native entry needs ROM out and I/O visible"
            report["startup"] = {"passed": True, "trueDrive": True, "autostartPRGMode": 2,
                                 "nativeEntry": labels["start"], "entryClock": at_entry["clock"],
                                 "comparedBytes": len(restored), "differentBytes": 0,
                                 "restoredSha256": digest(restored), "processorPort": port_state[1],
                                 "manualLoadOrSYS": False}
            monitor.run(f"delete {entry_break}")
            present_break = monitor.checkpoint(labels["presented"])
            done_break = monitor.checkpoint(labels["done"])
            if direct_front:
                response = monitor.run(f'trace exec ${labels["prepare_start"]:04x}')
                trace_id = int(re.search(r"(?:TRACE|BREAK):\s*(\d+)", response)[1])
                monitor.run(f'command {trace_id} "stopwatch"')
            monitor.run("x")
            color_watch = None
            for index in range(count):
                registers = monitor.registers()
                assert registers["pc"] == labels["presented"], (index, registers)
                monitor.run("bank ram")
                state = monitor.dump(out / "film-state.bin", labels["film_state"], labels["film_state_end"] - 1)

                def value(name):
                    return state[labels[name] - labels["film_state"]]

                assert value("film_frame") == index
                front = value("front_screen_hi") << 8
                actual_screen = monitor.dump(out / "front-screen.bin", front, front + 999)
                assert actual_screen == screens[index * 1000:(index + 1) * 1000], ("screen", index)
                assert monitor.dump(out / "font-check.bin", film["fontAddress"], film["fontAddress"] + 2047) == font
                observed_sample = value("presented_sample_low") + 256 * value("presented_sample_high")
                target_sample = film["sampleDeadlines"][index]
                completion_deadline = (film["sampleDeadlines"][index + 1]
                                       if index + 1 < count else len(expected_audio))
                maximum = completion_deadline + 160 if direct_front else target_sample + 160
                assert target_sample <= observed_sample <= maximum, (index, observed_sample, target_sample)
                monitor.run("bank io")
                video = monitor.dump(out / "video-registers.bin", 0xd011, 0xd024)
                assert video[0] & 0x70 == 0x10, "Expected screen-on normal character mode"
                assert video[5] & 0x10 == 0, "Multicolor mode must remain disabled"
                assert video[7] & 14 == 8, "Expected the $2000 character font"
                assert video[16] & 15 == 1, "Expected white global background"
                colors = monitor.dump(out / "colors.bin", 0xd800, 0xdbff)
                assert not any(v & 15 for v in colors), "Color RAM must stay black"
                monitor.run("bank cpu")
                if color_watch is None:
                    response = monitor.run("break store d800 dbff")
                    color_watch = int(re.search(r"(?:BREAK|WATCH):\s*(\d+)", response)[1])
                if not direct_front:
                    # At least24,576 CPU cycles elapse, exceeding one full PAL field.
                    # The next frame deadline is about197,064 cycles away.
                    response = monitor.run("step 3000")
                    assert not re.search(rf"#{color_watch}\s+\(Stop on ", response), "Per-frame Color RAM store"
                    refreshed = monitor.registers()
                    assert refreshed["clock"] - registers["clock"] >= FIELD_CYCLES
                    monitor.run("bank ram")
                    assert monitor.dump(out / "frame-index.bin", labels["film_frame"], labels["film_frame"])[0] == index
                    monitor.run("bank cpu")
                else:
                    refreshed = registers
                picture = out / f"frame-{index:03d}.png"
                monitor.run(f'scrsh "{picture}" 2')
                actual = screenshot_pixels(picture)
                assert len(actual) == 64000 * 3
                different = int(np.any(np.frombuffer(actual, dtype=np.uint8).reshape(-1, 3)
                                       != np.frombuffer(expected[index], dtype=np.uint8).reshape(-1, 3), axis=1).sum())
                if different and not direct_front:
                    (out / "expected.rgb").write_bytes(expected[index])
                    (out / "actual.rgb").write_bytes(actual)
                    raise AssertionError(("Native VIC-II frame differs", index, different))
                report["frames"].append({"frame": index, "presentClock": registers["clock"],
                                         "presentedSample": observed_sample, "targetSample": target_sample,
                                         "sampleDelay": observed_sample - target_sample,
                                         "completedFieldClock": refreshed["clock"],
                                         "differentCompletedMatrixPixels": 0,
                                         "differentNativeFieldPixels": different,
                                         "differentPixels": different, "screenshot": picture.name})
                monitor.run("x")
            stopped = monitor.registers()
            assert stopped["pc"] == labels["done"]
            monitor.run("bank ram")
            final_state = monitor.dump(out / "state.bin", 0, 0x1fff)
            assert final_state[labels["frame_present_count"]] == count
            assert final_state[labels["film_frame"]] == count - 1
            assert final_state[labels["underruns"]] == 0
            assert final_state[labels["finished"]] == 1
            monitor.run("bank cpu")
            report.update(passed=False, displayChecksPassed=True,
                          framesVerified=count, comparedPixels=count * 64000,
                          completedMatricesExact=True,
                          allNativeFieldsExact=not any(f["differentNativeFieldPixels"] for f in report["frames"]),
                          perFrameColorWrites=0, colorRAMStoreWatchAlwaysActive=True,
                          finalFrameCount=final_state[labels["frame_present_count"]],
                          maximumSampleDelay=max(f["sampleDelay"] for f in report["frames"]),
                          completionClock=stopped["clock"])
    except Exception as error:
        report["failure"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if monitor:
            (out / "monitor.log").write_text("\n".join(monitor.transcript))
        if connection:
            try:
                connection.sendall(b"quit\n")
            except OSError:
                pass
            connection.close()
        if process and process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        report["ownedProcessExitCode"] = process.returncode if process else None
        audio.save(out / "verification.json", report)
    sid = audio.verify_sid_trace(sid_trace, expected_audio)
    audio.save(out / "register-check.json", sid)
    if not sid["passed"]:
        raise ValueError(f"Screen-on audio failed after true-drive startup: {sid}")
    report["screenOnSID"] = sid
    if direct_front:
        pattern = re.compile(r"^\.C:([0-9a-fA-F]{4})\s+.*\s(\d+)$")
        starts = []
        for line in (out / "monitor.log").read_text().splitlines():
            match = pattern.match(line)
            if match and int(match[1], 16) == labels["prepare_start"]:
                starts.append(int(match[2]))
        assert len(starts) == count - 1, ("Draw starts", len(starts), count - 1)
        start_delays = [cycle - sid["firstAudibleSampleCycle"] - film["sampleDeadlines"][index] * audio.PERIOD
                        for index, cycle in enumerate(starts, 1)]
        assert min(start_delays) >= -2 * audio.PERIOD, start_delays
        assert max(start_delays) <= 160 * audio.PERIOD, start_delays
        for index, frame in enumerate(report["frames"]):
            if index:
                deadline = (film["sampleDeadlines"][index + 1]
                            if index + 1 < count else len(expected_audio))
                latest = sid["firstAudibleSampleCycle"] + (deadline + 160) * audio.PERIOD
                assert frame["presentClock"] <= latest, ("Late completion", index, frame)
        report["drawStartDelaysCycles"] = start_delays
        report["maximumDrawStartDelaySeconds"] = max(start_delays) / audio.CLOCK
        report["pixelProofScope"] = "All completed screen matrices and font bytes match the approved source. Native fields sampled while drawing directly can contain visible transitions."
    report["passed"] = report["displayChecksPassed"] and sid["passed"]
    assert digest(program.read_bytes()) == report["programSha256"]
    audio.save(out / "verification.json", report)
    pixel_key = "differentCompletedMatrixPixels" if direct_front else "differentPixels"
    print(json.dumps({"passed": report["passed"], "frames": count,
                      pixel_key: 0, "samples": len(expected_audio),
                      "allNativeFieldsExact": report["allNativeFieldsExact"],
                      "coldRAMBytes": len(original) - 2}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=HERE / "work/av")
    parser.add_argument("--timing-only", action="store_true")
    args = parser.parse_args()
    (timings if args.timing_only else verify)(args.build)
