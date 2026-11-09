#!/usr/bin/env python3
"""Export the generated C64 character frames as a finite GIF and contact sheet."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-dir", type=Path, default=here / "build/scenes/spiral")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--basename", default="spiral-scene")
    parser.add_argument("--expect-sha", help="Reject stale or changed character frames")
    parser.add_argument("--contact-frames", type=int, nargs="+", help="Nominal frame numbers to inspect")
    parser.add_argument("--playback-script", type=Path, default=here / "scenes/spiral.playback.json")
    parser.add_argument("--loop-repeats", type=int, help="Override the loop segment's repeat count in the JSON playback script")
    options = parser.parse_args()
    source = options.scene_dir.resolve()
    output = (options.output_dir or source).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if Path(options.basename).name != options.basename:
        raise ValueError("--basename must be a filename without directories")

    scene = json.loads((source / "scene.json").read_text())
    font = (source / "font.bin").read_bytes()
    screens = (source / "reference.frames").read_bytes()
    screens_sha = hashlib.sha256(screens).hexdigest()
    if options.expect_sha and screens_sha != options.expect_sha:
        raise ValueError(f"Character frames changed: {screens_sha}")
    count = len(scene["frames"])
    frame_ms = round(1000 / scene["fps"])
    assert frame_ms * scene["fps"] == 1000 and frame_ms % 10 == 0, "GIF needs whole centiseconds"
    assert count * frame_ms == round(scene["durationSeconds"] * 1000)
    assert (scene["width"], scene["height"]) == (320, 200)
    assert len(screens) == count * 1000 and len(font) % 8 == 0
    assert max(screens) < len(font) // 8
    playback_path = options.playback_script.resolve()
    commands = json.loads(playback_path.read_text())
    assert isinstance(commands, list) and len(commands) > 1
    loop_commands = [command for command in commands if command["op"] == "play"
                     and scene.get("loop") and command["startFrame"] == scene["loop"]["startFrame"]
                     and command["frameCount"] == scene["loop"]["frameCount"]]
    if options.loop_repeats is not None:
        assert options.loop_repeats > 0 and len(loop_commands) == 1
        loop_commands[0]["repeat"] = options.loop_repeats
    playback = []
    for index, command in enumerate(commands):
        if command["op"] == "hold":
            assert index == len(commands) - 1, "HOLD must be last"
        else:
            assert command["op"] == "play"
            assert type(command["startFrame"]) is int and command["startFrame"] >= 0
            assert type(command["frameCount"]) is int and 0 < command["frameCount"] <= 255
            assert command["startFrame"] + command["frameCount"] <= count
            assert type(command["repeat"]) is int and 0 < command["repeat"] <= 65535
            playback.extend(list(range(command["startFrame"], command["startFrame"] + command["frameCount"])) * command["repeat"])
    assert commands[-1]["op"] == "hold" and playback
    loop_repeats = sum(command["repeat"] for command in loop_commands)

    glyphs = []
    for code in range(len(font) // 8):
        glyph = Image.new("L", (8, 8))
        glyph.putdata([255 if row & (128 >> x) else 0
                       for row in font[code * 8:code * 8 + 8] for x in range(8)])
        glyphs.append(glyph)
    frames = []
    for index in range(count):
        image = Image.new("L", (320, 200))
        for cell, code in enumerate(screens[index * 1000:(index + 1) * 1000]):
            image.paste(glyphs[code], ((cell % 40) * 8, (cell // 40) * 8))
        frames.append(image)

    scaled = [frame.resize((640, 400), Image.Resampling.NEAREST) for frame in frames]
    palette = [scaled[index].convert("P") for index in playback]
    gif_file = output / f"{options.basename}.gif"
    palette[0].save(gif_file, save_all=True, append_images=palette[1:],
                    duration=frame_ms, optimize=False, disposal=1)
    # Pillow may coalesce identical frames. Check their accumulated timing and
    # decoded pixels against the actual character export, rather than GIF count.
    elapsed = 0
    with Image.open(gif_file) as gif:
        assert gif.size == (640, 400) and "loop" not in gif.info
        gif_frames = gif.n_frames
        for index in range(gif_frames):
            gif.seek(index)
            duration = gif.info["duration"]
            assert duration > 0 and duration % frame_ms == 0
            pixels = gif.convert("L").tobytes()
            for instant in range(elapsed, elapsed + duration, frame_ms):
                assert pixels == scaled[playback[instant // frame_ms]].tobytes()
            elapsed += duration
        assert elapsed == len(playback) * frame_ms

    samples = options.contact_frames or [min(count - 1, round(second * scene["fps"]))
               for second in (0, 1, 2, 3, 4, scene["durationSeconds"] - 1 / scene["fps"])]
    assert all(0 <= frame < count for frame in samples)
    contact = Image.new("RGB", (1000, ((len(samples) + 2) // 3) * 234 + 8), (20, 22, 19))
    draw = ImageDraw.Draw(contact)
    for slot, index in enumerate(samples):
        x, y = 10 + (slot % 3) * 330, 10 + (slot // 3) * 234
        contact.paste(frames[index], (x, y + 24))
        diameter = scene["frames"][index].get("diameter")
        detail = f"diameter {diameter:.0f}px" if diameter is not None else scene["frames"][index].get("phase", "bitmap")
        draw.text((x, y), f"{index / scene['fps']:.2f}s | frame {index} | {detail}",
                  fill=(217, 241, 138))
    contact_file = output / f"{options.basename}-contact.png"
    contact.save(contact_file)

    result = {"pass": True, "sourceFrames": count, "playbackFrames": len(playback), "gifFrames": gif_frames,
              "uniqueFrames": count, "introFrames": scene["loop"]["startFrame"] if scene.get("loop") else count,
              "loopFrames": scene["loop"]["frameCount"] if scene.get("loop") else 0,
              "durationMs": elapsed, "loops": False, "gif": str(gif_file),
              "playbackScript": str(playback_path), "commands": commands,
              "totalDisplayedFrames": len(playback), "nominalSeconds": elapsed / 1000,
              "loopRepetitions": loop_repeats,
              "contact": str(contact_file), "screensSha256": screens_sha,
              "contactFrames": samples,
              "fontSha256": hashlib.sha256(font).hexdigest(),
              "decodedGifPixelsMatchCharacterFrames": True}
    (output / f"{options.basename}-media.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
