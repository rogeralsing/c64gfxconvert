#!/usr/bin/env python3
"""Render the measured OR-font experiment and compare its displayed pixels."""
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont


HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"


def image_for(screen, font):
    image = Image.new("RGB", (320, 200))
    pixels = image.load()
    for position, code in enumerate(screen):
        left, top = position % 40 * 8, position // 40 * 8
        for y, bits in enumerate(font[code * 8:code * 8 + 8]):
            for x in range(8):
                if bits & (128 >> x):
                    pixels[left + x, top + y] = (255, 255, 255)
    return image


def main():
    old_screens = (HERE.parent / "build/assets/reference.bin").read_bytes()
    old_font = (HERE.parents[3] / "assets/font.bin").read_bytes()
    screens = (BUILD / "assets/reference.bin").read_bytes()
    font = (BUILD / "assets/font.bin").read_bytes()
    assert len(old_screens) == len(screens) == 64000
    before = [image_for(old_screens[i:i + 1000], old_font)
              for i in range(0, 64000, 1000)]
    after = [image_for(screens[i:i + 1000], font)
             for i in range(0, 64000, 1000)]
    errors = [sum(pixel != 0 for pixel in
                  ImageChops.difference(a, b).convert("L").tobytes())
              for a, b in zip(before, after)]
    frames = sorted(sorted(range(64), key=lambda i: errors[i], reverse=True)[:3])
    sheet = Image.new("RGB", (1280, len(frames) * 440), (20, 23, 24))
    draw = ImageDraw.Draw(sheet)
    text_font = ImageFont.load_default(size=20)
    for row, frame in enumerate(frames):
        top = row * 440
        draw.text((12, top + 8), f"Original / frame {frame}", fill="white", font=text_font)
        draw.text((652, top + 8), f"OR font / {errors[frame]} changed pixels", fill="white", font=text_font)
        sheet.paste(before[frame].resize((640, 400), Image.Resampling.NEAREST), (0, top + 40))
        sheet.paste(after[frame].resize((640, 400), Image.Resampling.NEAREST), (640, top + 40))
    sheet.save(BUILD / "comparison.png")
    verification = BUILD / "verification/verification.json"
    fps = json.loads(verification.read_text())["mean_fps"] if verification.exists() else 10
    animation = [image.resize((640, 400), Image.Resampling.NEAREST) for image in after]
    animation[0].save(BUILD / "or-font.gif", save_all=True, append_images=animation[1:],
                      duration=round(1000 / fps), loop=0, optimize=True)
    print(json.dumps({"frames": 64, "meanChangedPixels": sum(errors) / 64,
                      "maxChangedPixels": max(errors), "comparisonFrames": frames,
                      "gifFps": fps, "gifFrameDurationMs": round(1000 / fps)}))


if __name__ == "__main__":
    main()
