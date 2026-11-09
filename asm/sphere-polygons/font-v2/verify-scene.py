#!/usr/bin/env python3
"""Prove the complete scripted scene on native PAL VICE, including held fields."""

import argparse
import importlib.util
import json
from pathlib import Path
import re
import socket
import subprocess

from PIL import Image, ImageChops

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("scene_delta_verifier", HERE / "large-benchmark/verify-delta.py")
delta = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(delta)
native = delta.native


def fixed_active_image(path, pixels):
    # An entirely black first frame cannot identify the active origin by
    # searching for matching crops. These VICE settings use32,35; use the same
    # fixed crop for every frame and let nonempty images prove its alignment.
    origin = [32, 35]
    image = Image.open(path).convert("RGB").crop((32, 35, 352, 235))
    target = Image.frombytes("L", (320, 200), pixels).convert("RGB")
    if ImageChops.difference(image, target).getbbox():
        raise AssertionError("Actual VIC active image differs from the expected character screen")
    return {"origin": origin, "mismatched_rgb_bytes": 0, "compared_pixels": 64000}


native.screenshot_matches = fixed_active_image


def verify_held_fields(build, verified):
    """Observe held fields and either the finite stop or two real loop wraps."""
    output = build / "pal-held-proof"
    output.mkdir(exist_ok=True)
    manifest = json.loads((build / "build.json").read_text())
    labels = {name: int(address, 16) for name, address in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", (build / "main.sym").read_text())}
    font = (build / "font.bin").read_bytes()
    movie = (build / "movie.bin").read_bytes()
    raw = (build / "reference.frames").read_bytes()
    count = manifest["storedFrames"]
    loop = manifest.get("loop")
    timeline = []
    cursor = 0
    for command_index, command in enumerate(manifest["playback"]["commands"]):
        if command["op"] == "hold":
            break
        cursor += 5
        repetitions = 3 if command["repeat"] == "forever" else command["repeat"]
        for iteration in range(repetitions):
            for offset in range(command["frameCount"]):
                timeline.append({"pose": command["startFrame"] + offset,
                                 "plays_left": 0 if command["repeat"] == "forever" else repetitions - iteration,
                                 "images_left": command["frameCount"] - offset,
                                 "script_cursor": cursor})
    if len(timeline) < count or [row["pose"] for row in timeline[:count]] != list(range(count)):
        raise AssertionError("This full-corpus native proof requires the script to present all stored frames in order initially")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    command = list(verified["command"])
    command[-1] = f"ip4://127.0.0.1:{port}"
    program_sha = delta.sha((build / "player.prg").read_bytes())
    if program_sha != verified["program_sha256"]:
        raise AssertionError("Both field proofs must use the same immutable native program")
    report = {"pass": False, "program_sha256": program_sha,
              "method": "Unmodified native checkpoints. Every requested finite repetition and held field, including all closing deltas, uses actual VIC screenshots with forced refresh disabled. Infinite scripts use a bounded repetition sample.",
              "frames": [], "repeated_render_cycles": []}
    process = connection = monitor = None
    with (output / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            report["owned_pid"] = process.pid
            connection = native.connect(process, port)
            monitor = native.Monitor(connection)
            monitor.run("sidefx off")
            initial = monitor.checkpoint(labels["presentation_start"])
            monitor.run("x")
            start = monitor.registers()
            monitor.run(f"delete {initial}")
            held = monitor.checkpoint(labels["held_frame_done"])

            def capture(pose, phase, occurrence, check_ram=False):
                registers = monitor.registers()
                expected_pc = labels["held_frame_done" if phase == "held" else "frame_done"]
                if registers["pc"] != expected_pc or not 256 <= registers["raster"] <= 257:
                    raise AssertionError("Capture is not at the completed image boundary")
                picture = output / f"pose-{pose:03d}-{occurrence:03d}-{phase}.png"
                monitor.run(f'scrsh "{picture}" 2')
                screen = raw[pose * 1000:(pose + 1) * 1000]
                comparison = native.screenshot_matches(picture, native.pixels_from_screen(screen, font))
                if check_ram:
                    monitor.run("bank ram")
                    ram = monitor.dump(output / "last-loop-ram.bin", 0, 65535)
                    monitor.run("bank cpu")
                    if ram[0x400:0x7e8] != screen or ram[labels["frame_index"]] != pose:
                        raise AssertionError("Native loop screen or wrapped frame index differs")
                    if ram[0x2000:0x2000 + len(font)] != font or ram[labels["animation"]:labels["animation_end"]] != movie:
                        raise AssertionError("Immutable loop font or source changed")
                    expected_state = timeline[occurrence]
                    actual_plays = int.from_bytes(ram[labels["plays_left"]:labels["plays_left"] + 2], "little")
                    if actual_plays != expected_state["plays_left"] or ram[labels["images_left"]] != expected_state["images_left"] or ram[labels["script_cursor"]] != expected_state["script_cursor"]:
                        raise AssertionError(f"Playback counter mismatch at image {occurrence}: {actual_plays}, expected {expected_state}")
                record = {"pose": pose, "phase": phase, "occurrence": occurrence,
                          "clock": registers["clock"], "scanout_match": True,
                          "screenshot": picture.name, "comparison": comparison}
                report["frames"].append(record)
                return registers

            first_pass_end = None
            for pose in range(count):
                monitor.run("x")
                first_pass_end = capture(pose, "held", pose, check_ram=True)
                if loop and pose == loop["startFrame"] - 1:
                    report["intro_presentation_seconds"] = (first_pass_end["clock"] - start["clock"]) / native.PAL_CLOCK
                if (pose + 1) % 32 == 0:
                    print(json.dumps({"held_fields_verified": pose + 1}), flush=True)
            first_pass_cycles = first_pass_end["clock"] - start["clock"]
            if round(first_pass_cycles / native.PAL_FRAME_CYCLES) != count * 2:
                raise AssertionError("The first pass did not occupy two PAL fields per image")
            report["first_pass_presentation_seconds"] = first_pass_cycles / native.PAL_CLOCK
            repeated_updates = 0
            last_capture = first_pass_end
            extra_checkpoints = []
            wraps = 0
            if len(timeline) > count:
                extra_checkpoints = [monitor.checkpoint(labels[name]) for name in ("render_start", "render_end", "frame_done")]
                for occurrence in range(len(timeline) - count):
                    pose = timeline[count + occurrence]["pose"]
                    if timeline[count + occurrence - 1]["pose"] == count - 1 and pose == loop["startFrame"]:
                        wraps += 1
                    monitor.run("x")
                    rendering = monitor.registers()
                    if rendering["pc"] != labels["render_start"] or not 256 <= rendering["raster"] <= 257:
                        raise AssertionError("Loop update did not start in the lower border")
                    monitor.run("x")
                    finished = monitor.registers()
                    cycles = finished["clock"] - rendering["clock"]
                    if finished["pc"] != labels["render_end"] or cycles >= native.PAL_FRAME_CYCLES:
                        raise AssertionError("Loop decoder exceeded one PAL field")
                    report["repeated_render_cycles"].append(cycles)
                    monitor.run("x")
                    capture(pose, "completed", count + occurrence, check_ram=True)
                    monitor.run("x")
                    last_capture = capture(pose, "held", count + occurrence, check_ram=True)
                    repeated_updates += 1
                repeated_cycles = last_capture["clock"] - first_pass_end["clock"]
                if abs(repeated_cycles - repeated_updates * 2 * native.PAL_FRAME_CYCLES) > 63:
                    raise AssertionError("Repeated suffix cadence changed across a real wrap")
                report.update({"loop_wraps_verified": wraps, "loop_repeated_images_verified": repeated_updates,
                               "loop_period_seconds": repeated_cycles / (repeated_updates / loop["frameCount"]) / native.PAL_CLOCK})
            if manifest["finiteClip"]:
                monitor.run(f"delete {held}")
                for checkpoint in extra_checkpoints:
                    monitor.run(f"delete {checkpoint}")
                monitor.checkpoint(labels["stopped"])
                monitor.run("x")
                stopped = monitor.registers()
                if stopped["pc"] != labels["stopped"]:
                    raise AssertionError("Finite scene failed to stop")
                stop_cycles = stopped["clock"] - start["clock"]
                if round(stop_cycles / native.PAL_FRAME_CYCLES) != len(timeline) * 2:
                    raise AssertionError("Script stopped before its final image completed both fields")
                monitor.run("x")
                if monitor.registers()["pc"] != labels["stopped"]:
                    raise AssertionError("Final HOLD did not remain at the stop loop")
                report["finite_stop_verified"] = True
            else:
                report["finite_stop_verified"] = False
            elapsed = last_capture["clock"] - start["clock"]
            report.update({"pass": True, "checked_held_fields": count + repeated_updates,
                           "checked_repeated_update_fields": repeated_updates,
                           "total_presentation_fields": round(elapsed / native.PAL_FRAME_CYCLES),
                           "total_presentation_cycles": elapsed,
                           "total_presentation_seconds": elapsed / native.PAL_CLOCK,
                           "all_held_scanouts_match": True})
            report["displayed_images_verified"] = len(timeline)
            report["all_playback_counters_match"] = True
        except BaseException as error:
            report["error"] = repr(error)
            raise
        finally:
            if monitor:
                (output / "monitor.log").write_text("\n".join(monitor.transcript))
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
            (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=HERE / "build/scene-native/spiral")
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    args = parser.parse_args()
    root = args.root.resolve()
    build = root / "sparse-front"
    report = delta.verify("sparse-front", args.vice, root=root)
    count = report["manifest"]["storedFrames"]
    loop = report["manifest"].get("loop")
    if not report["pass"] or report["checked_frames"] != count or report["observed_fields_per_image"] != [2]:
        raise AssertionError("The complete scripted scene must pass exact native playback at two PAL fields per image")
    held = verify_held_fields(build, report)
    report.update({"scope": "Complete embedded PLAY/HOLD program, including every requested repetition and final HOLD for finite scripts. No music or interrupt workload.",
                   "safe_scanout_scope": f"All {held['displayed_images_verified']} displayed images were compared in both PAL fields using actual VIC screenshots. Playback counters and all real wrap transitions were checked.",
                   "heldFieldProof": {key: value for key, value in held.items() if key != "frames"},
                   "actual_visible_fields_verified": report["actual_visible_fields_verified"] + held["checked_held_fields"] + held["checked_repeated_update_fields"]})
    renders = [event["clock"] - report["events"][index - 1]["clock"] for index, event in enumerate(report["events"]) if event["event"] == "render_end"]
    report["render_cycles"] = delta.stats(renders + held["repeated_render_cycles"])
    report["manifest"]["nativeFps"] = report["mean_fps"]
    report["manifest"]["nativeVisibleFieldsVerified"] = report["actual_visible_fields_verified"]
    (build / "build.json").write_text(json.dumps(report["manifest"], indent=2) + "\n")
    (build / "pal-proof/verification.json").write_text(json.dumps(report, indent=2) + "\n")
    summary = {key: report[key] for key in ("pass", "checked_frames", "actual_visible_fields_verified", "mean_fps", "render_cycles", "presentation_cycles", "observed_fields_per_image", "safe_scanout_scope")}
    summary["firstPassSeconds"] = held["first_pass_presentation_seconds"]
    summary["finiteStopVerified"] = held["finite_stop_verified"]
    summary["loopWrapsVerified"] = held.get("loop_wraps_verified", 0)
    summary["loopPeriodSeconds"] = held.get("loop_period_seconds")
    summary["introSeconds"] = held.get("intro_presentation_seconds")
    summary["displayedImagesVerified"] = held["displayed_images_verified"]
    summary["allPlaybackCountersMatch"] = held["all_playback_counters_match"]
    summary["completeScriptSeconds"] = held["total_presentation_seconds"]
    summary["memory"] = report["manifest"]
    (root / "verification-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
