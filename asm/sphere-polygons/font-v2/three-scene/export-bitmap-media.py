#!/usr/bin/env python3
"""Preview packed bitmap frames directly, before any character conversion."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw


def verify_gif(file, expected, frame_ms):
    """Check decoded pixels and timing, including coalesced identical frames."""
    elapsed = 0
    with Image.open(file) as gif:
        assert "loop" not in gif.info
        blocks = gif.n_frames
        for index in range(blocks):
            gif.seek(index)
            duration, actual = gif.info["duration"], gif.convert("RGB").tobytes()
            assert duration > 0 and duration % frame_ms == 0
            for instant in range(elapsed, elapsed + duration, frame_ms):
                assert actual == expected[instant // frame_ms].convert("RGB").tobytes(), f"GIF differs at frame {instant // frame_ms}"
            elapsed += duration
    assert elapsed == len(expected) * frame_ms
    return elapsed, blocks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args()
    source, output = options.input.resolve(), options.output.resolve()
    metadata = json.loads((source / "metadata.json").read_text())
    width, height, count, fps = (metadata[key] for key in ("width", "height", "frameCount", "fps"))
    frame_bytes, frame_ms = width * height // 8, round(1000 / fps)
    assert width % 8 == 0 and frame_ms * fps == 1000 and frame_ms % 10 == 0
    packed = (source / metadata["framesFile"]).read_bytes()
    rgba = (source / metadata["rgbaFile"]).read_bytes()
    assert len(packed) == count * frame_bytes and len(rgba) == count * width * height * 4
    assert hashlib.sha256(packed).hexdigest() == metadata["hashes"]["frames"]
    assert hashlib.sha256(rgba).hexdigest() == metadata["hashes"]["rgba"]
    output.mkdir(parents=True, exist_ok=True)
    bitmaps = []
    def color_frame(index):
        color = Image.frombytes("RGBA", (width, height), rgba[index * width * height * 4:(index + 1) * width * height * 4])
        return color.convert("RGB").resize((width * 4, height * 4), Image.Resampling.NEAREST)

    for index in range(count):
        image = Image.frombytes("1", (width, height), packed[index * frame_bytes:(index + 1) * frame_bytes])
        bitmaps.append(image.resize((width * 4, height * 4), Image.Resampling.NEAREST))
    gif_path = output / "bitmap.gif"
    bitmaps[0].save(gif_path, save_all=True, append_images=bitmaps[1:], duration=frame_ms, optimize=False, disposal=1)
    comparisons = []
    for index, bitmap in enumerate(bitmaps):
        pair = Image.new("RGB", (width * 8, height * 4 + 28), (0, 0, 0))
        draw = ImageDraw.Draw(pair)
        draw.text((10, 7), "Three.js / RGBA", fill=(255, 255, 255))
        draw.text((width * 4 + 10, 7), "1 bit / ordered dithering", fill=(255, 255, 255))
        pair.paste(color_frame(index), (0, 28)); pair.paste(bitmap, (width * 4, 28))
        palette = pair.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
        assert palette.convert("RGB").tobytes() == pair.tobytes(), "Comparison palette changed source gray levels"
        comparisons.append(palette)
    comparisons[0].save(output / "comparison.gif", save_all=True, append_images=comparisons[1:], duration=frame_ms, optimize=False, disposal=1)

    elapsed, blocks = verify_gif(gif_path, bitmaps, frame_ms)
    verify_gif(output / "comparison.gif", comparisons, frame_ms)
    samples = {min(count - 1, round(second * fps)) for second in (3, 4.96, 5.5, 6, 7, 7.96)}
    samples.add(count - 1)
    phases = metadata.get("frames", [])
    samples.update(index for index in range(1, len(phases))
                   if phases[index].get("phase") != phases[index - 1].get("phase") and index >= 5 * fps)
    samples = sorted(samples)
    contact = Image.new("RGB", (width * 8, (height * 4 + 28) * len(samples)), (20, 22, 19))
    draw = ImageDraw.Draw(contact)
    for row, index in enumerate(samples):
        y = row * (height * 4 + 28)
        contact.paste(comparisons[index], (0, y))
        draw.text((width * 4 - 125, y + 7), f"{index / fps:.2f}s / {index}", fill=(217, 241, 138))
    contact.save(output / "bitmap-contact.png")
    detail = None
    if metadata.get("objectMaskFile"):
        masks = (source / metadata["objectMaskFile"]).read_bytes()
        assert len(masks) == len(packed)
        tail_start = max(0, count - round(2 * fps))
        bounds = [Image.frombytes("1", (width, height), masks[index * frame_bytes:(index + 1) * frame_bytes]).getbbox()
                  for index in range(tail_start, count)]
        bounds = [box for box in bounds if box]
        if bounds:
            crop = (max(0, min(box[0] for box in bounds) - 3), max(0, min(box[1] for box in bounds) - 3),
                    min(width, max(box[2] for box in bounds) + 3), min(height, max(box[3] for box in bounds) + 3))
            size = ((crop[2] - crop[0]) * 8, (crop[3] - crop[1]) * 8)
            frames = [Image.frombytes("1", (width, height), packed[index * frame_bytes:(index + 1) * frame_bytes]).crop(crop).resize(size, Image.Resampling.NEAREST)
                      for index in range(tail_start, count)]
            detail_file = output / "bitmap-detail.gif"
            frames[0].save(detail_file, save_all=True, append_images=frames[1:], duration=frame_ms, optimize=False, disposal=1)
            detail_duration, detail_blocks = verify_gif(detail_file, frames, frame_ms)
            frames[-1].save(output / "bitmap-detail.png")
            detail = {"gif": str(detail_file), "startFrame": tail_start, "cropLogicalPixels": crop,
                      "nearestScale": 8, "durationMs": detail_duration, "gifBlocks": detail_blocks}
    result = {"pass": True, "frames": count, "gifBlocks": blocks, "durationMs": elapsed,
              "decodedGifPixelsMatchPackedMovie": True, "characterConversionRun": False,
              "bitmapSha256": metadata["hashes"]["frames"], "gif": str(gif_path),
              "comparison": str(output / "comparison.gif"), "contact": str(output / "bitmap-contact.png"), "detail": detail}
    (output / "media.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
