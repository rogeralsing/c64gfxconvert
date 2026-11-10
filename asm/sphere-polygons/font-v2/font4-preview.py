#!/usr/bin/env python3
"""Render and independently check the fixed 4x4 logical-font experiment."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


HERE = Path(__file__).resolve().parent
WIDTH, HEIGHT, CELLS, FRAMES = 320, 200, 1000, 384
BACKGROUND = "#111511"
FOREGROUND = "#e5e8dd"
ACCENT = "#d1e891"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def typeface(size=14):
    for name in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf"):
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


def pixels(screen, glyphs):
    return glyphs[screen.reshape(25, 40)].transpose(0, 2, 1, 3).reshape(HEIGHT, WIDTH)


def load_case(directory, count):
    font_path = directory / f"font{count}.bin"
    screen_path = directory / f"frames{count}.screen"
    font_data, screen_data = font_path.read_bytes(), screen_path.read_bytes()
    if len(font_data) != count * 8 or len(screen_data) != FRAMES * CELLS:
        raise ValueError(f"Incomplete font or frame data for {count} characters")
    glyphs = np.unpackbits(np.frombuffer(font_data, dtype=np.uint8).reshape(count, 8, 1), axis=2)
    frames = np.frombuffer(screen_data, dtype=np.uint8).reshape(FRAMES, CELLS)
    if int(frames.max()) >= count:
        raise AssertionError("Screen code exceeds the available glyph count")
    if not np.array_equal(glyphs[:, 0::2, :], glyphs[:, 1::2, :]):
        raise AssertionError("Font rows do not form 2x2 physical pixels")
    if not np.array_equal(glyphs[:, :, 0::2], glyphs[:, :, 1::2]):
        raise AssertionError("Font columns do not form 2x2 physical pixels")
    mask_path = directory / f"masks{count}.json"
    if mask_path.exists():
        masks = json.loads(mask_path.read_text())
        if isinstance(masks, dict):
            masks = masks.get("masks", masks.get("glyphs"))
        expected = np.array([[(int(mask) >> bit) & 1 for bit in range(16)] for mask in masks],
                            dtype=np.uint8).reshape(count, 4, 4)
        if not np.array_equal(glyphs[:, 0::2, 0::2], expected):
            raise AssertionError("The 16-bit masks disagree with the expanded C64 font")
    return {"count": count, "font": font_data, "screen": screen_data,
            "glyphs": glyphs, "frames": frames, "font_path": str(font_path),
            "screen_path": str(screen_path)}


def screen_image(values, size=(640, 400)):
    return Image.fromarray(np.asarray(values, dtype=np.uint8) * 255, "L").convert("RGB").resize(
        size, Image.Resampling.NEAREST)


def comparison(panels, captions, pose, font):
    result = Image.new("RGB", (640 * len(panels), 458), BACKGROUND)
    draw = ImageDraw.Draw(result)
    draw.text((16, 9), f"HOST RECONSTRUCTION - same pose {pose:03d}; fixed fonts", fill=FOREGROUND, font=font)
    for column, (panel, caption) in enumerate(zip(panels, captions)):
        result.paste(screen_image(panel), (column * 640, 58))
        draw.text((column * 640 + 16, 35), caption, fill=ACCENT, font=font)
    return result


def atlas(case, output):
    count = case["count"]
    columns = 8 if count <= 64 else 16
    cell_width, cell_height, top = 96, 104, 68
    rows = (count + columns - 1) // columns
    result = Image.new("RGB", (columns * cell_width, top + rows * cell_height + 16), BACKGROUND)
    draw, font, small = ImageDraw.Draw(result), typeface(15), typeface(12)
    draw.text((16, 9), f"{count} fixed glyphs - 4x4 logical pixels, each 2x2 physical", fill=FOREGROUND, font=font)
    draw.text((16, 34), "Code / occurrences across 384 screens; grid follows logical pixels", fill=ACCENT, font=small)
    usage = np.bincount(case["frames"].reshape(-1), minlength=count)
    for code, glyph in enumerate(case["glyphs"]):
        x, y = (code % columns) * cell_width + 16, top + (code // columns) * cell_height
        result.paste(screen_image(glyph, (64, 64)), (x, y))
        for line in range(5):
            draw.line((x + line * 16, y, x + line * 16, y + 64), fill="#555c50")
            draw.line((x, y + line * 16, x + 64, y + line * 16), fill="#555c50")
        draw.text((x, y + 72), f"{code:02d} / {int(usage[code])}", fill=FOREGROUND, font=small)
    result.save(output / f"atlas{count}.png")


def main(args):
    directory, output = args.input.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cases = [load_case(directory, count) for count in args.counts]
    case64 = next((case for case in cases if case["count"] == 64), None)
    if case64 is None:
        raise ValueError("Include the 64-glyph case for the primary comparison")
    old_font = (HERE / "c64-preview/build/font.bin").read_bytes()
    old_data = (HERE / "c64-preview/build/movie.frames").read_bytes()
    if len(old_font) != 2048 or len(old_data) != FRAMES * CELLS:
        raise ValueError("Expected the existing 256-glyph 8x8 reference")
    old_glyphs = np.unpackbits(np.frombuffer(old_font, dtype=np.uint8).reshape(256, 8, 1), axis=2)
    old_frames = np.frombuffer(old_data, dtype=np.uint8).reshape(FRAMES, CELLS)
    ideal_file = directory / "ideal.frames"
    if ideal_file.stat().st_size != FRAMES * WIDTH * HEIGHT:
        raise ValueError("Expected all 384 mathematical bitmap references")
    ideal = np.memmap(ideal_file, dtype=np.uint8, mode="r", shape=(FRAMES, HEIGHT, WIDTH))
    if int(ideal.max()) > 1:
        raise AssertionError("Mathematical references must contain binary pixels")
    errors = {case["count"]: [] for case in cases}
    outside_errors = {case["count"]: [] for case in cases}
    baseline_errors, baseline_outside, quantization_floor, difference_counts = [], [], [], []
    yy, xx = np.mgrid[:HEIGHT, :WIDTH]
    outside_circle = (xx + 0.5 - 160) ** 2 + (yy + 0.5 - 100) ** 2 > 145 ** 2
    for pose in range(FRAMES):
        wanted = ideal[pose]
        baseline = pixels(old_frames[pose], old_glyphs)
        baseline_errors.append(int(np.not_equal(baseline, wanted).sum()))
        baseline_outside.append(int(baseline[outside_circle].sum()))
        groups = wanted.reshape(100, 2, 160, 2).sum(axis=(1, 3))
        lower_bound = int(np.minimum(groups, 4 - groups).sum())
        quantization_floor.append(lower_bound)
        for case in cases:
            expanded = pixels(case["frames"][pose], case["glyphs"])
            if not np.array_equal(expanded[0::2, :], expanded[1::2, :]):
                raise AssertionError(f"Pose {pose} is not a 2x2-pixel image")
            if not np.array_equal(expanded[:, 0::2], expanded[:, 1::2]):
                raise AssertionError(f"Pose {pose} is not a 2x2-pixel image")
            error = int(np.not_equal(expanded, wanted).sum())
            if error < lower_bound:
                raise AssertionError("Expanded font beats the independent 2x2 quantization bound")
            errors[case["count"]].append(error)
            outside_errors[case["count"]].append(int(expanded[outside_circle].sum()))
            if case["count"] == 64:
                difference_counts.append(int(np.not_equal(expanded, baseline).sum()))
    font = typeface()
    worst = int(np.argmax(errors[64]))
    captions = ["Current: 8x8 font, 256 glyphs", "4x4 font, 64 glyphs; 2x2 physical pixels"]

    def pair(pose):
        return [pixels(old_frames[pose], old_glyphs), pixels(case64["frames"][pose], case64["glyphs"])]

    comparison(pair(0), captions, 0, font).save(output / "first-pose.png")
    comparison(pair(worst), captions, worst, font).save(output / "worst64-pose.png")
    selected = min(args.frames, FRAMES - args.start)
    if selected < 1:
        raise ValueError("No frames selected for the comparison")
    images = [comparison(pair(pose), captions, pose, font)
              for pose in range(args.start, args.start + selected)]
    images[0].save(output / "font8-vs-font4-64.gif", save_all=True, append_images=images[1:],
                   duration=40, loop=0, optimize=False)
    sample_poses = sorted({0, worst, *range(0, FRAMES, 64)})
    contact = Image.new("RGB", (1280, len(sample_poses) * 458), BACKGROUND)
    for row, pose in enumerate(sample_poses):
        contact.paste(comparison(pair(pose), captions, pose, font), (0, row * 458))
    contact.save(output / "contact-sheet.png")
    for case in cases:
        atlas(case, output)
    if len(cases) > 1:
        panels = [pixels(old_frames[worst], old_glyphs)] + [pixels(case["frames"][worst], case["glyphs"]) for case in cases]
        labels = ["Current 8x8 / 256 glyphs"] + [f"4x4 / {case['count']} glyphs" for case in cases]
        rows = (len(panels) + 1) // 2
        grid = Image.new("RGB", (1280, rows * 458), BACKGROUND)
        for row in range(rows):
            subset = panels[row * 2:row * 2 + 2]
            grid.paste(comparison(subset, labels[row * 2:row * 2 + 2], worst, font), (0, row * 458))
        grid.save(output / "palette-counts.png")

    # Inspect the cell with the largest 64-glyph error at the worst pose.
    error = np.not_equal(pair(worst)[1], ideal[worst])
    cell_errors = error.reshape(25, 8, 40, 8).transpose(0, 2, 1, 3).reshape(CELLS, 64).sum(axis=1)
    cell = int(np.argmax(cell_errors))
    left = min(max((cell % 40) * 8 - 28, 0), WIDTH - 64)
    top = min(max((cell // 40) * 8 - 28, 0), HEIGHT - 64)
    detail = Image.new("RGB", (1152, 438), BACKGROUND)
    draw = ImageDraw.Draw(detail)
    draw.text((16, 9), f"HOST detail - pose {worst}, cell {cell % 40},{cell // 40}; 64x64 physical-pixel region", fill=FOREGROUND, font=font)
    details = [ideal[worst], *pair(worst)]
    for column, (panel, label) in enumerate(zip(details, ["Mathematical pixel reference", "8x8 font / 256 glyphs", "4x4 font / 64 glyphs"])):
        draw.text((column * 384 + 12, 34), label, fill=ACCENT, font=font)
        detail.paste(screen_image(panel[top:top + 64, left:left + 64], (384, 384)), (column * 384, 54))
    detail.save(output / "detail.png")

    def summary(values):
        return {"min": min(values), "mean": sum(values) / len(values), "max": max(values)}

    metadata = {
        "pass": True, "kind": "host reconstruction, not native VIC scanout",
        "physicalScreen": [WIDTH, HEIGHT], "logicalDotScreen": [160, 100], "characterScreen": [40, 25],
        "framesVerified": FRAMES, "allGlyphPixelsAre2x2": True,
        "baseline": {"glyphs": 256, "fontBytes": len(old_font), "fontSha256": digest(old_font),
                     "framesSha256": digest(old_data), "pixelErrorAgainstIdeal": summary(baseline_errors),
                     "litPixelsOutsideExactCircle": summary(baseline_outside)},
        "quantization4x4MinimumPixelError": summary(quantization_floor),
        "cases": [{"glyphs": case["count"], "fontBytes": len(case["font"]),
                   "fontSha256": digest(case["font"]), "framesSha256": digest(case["screen"]),
                   "pixelErrorAgainstIdeal": summary(errors[case["count"]]),
                   "litPixelsOutsideExactCircle": summary(outside_errors[case["count"]]),
                   "meanPercentOfScreen": sum(errors[case["count"]]) / FRAMES / 640,
                   "perFrameError": errors[case["count"]]} for case in cases],
        "font64VsCurrentPixelDifferences": summary(difference_counts),
        "worst64Pose": worst, "detailCell": [cell % 40, cell // 40], "detailOrigin": [left, top],
        "gif": {"file": "font8-vs-font4-64.gif", "frames": selected, "startPose": args.start,
                "presentationFps": 25, "durationSeconds": selected / 25,
                "scope": "Repeated finite host-comparison segment; not a full-turn native movie or a measured playback rate."}
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (output / "README.md").write_text(
        "# 4x4 logical-font visual comparison\n\n"
        "These images reconstruct character screens through fixed font bytes on the host. "
        "They are not VICE screenshots. Each logical font pixel expands to a 2x2 block; "
        "the screen remains 40x25 character cells and 320x200 physical pixels.\n\n"
        "The GIF contains a finite 64-pose segment shown at 25 FPS and repeats from its beginning. "
        "It does not claim that the entire 360-degree movie fits or that native playback was measured here.\n\n"
        "`atlas64.png` shows the selected 64-glyph font, with a 4x4 logical grid and usage counts. "
        "`first-pose.png` and `worst64-pose.png` compare against the current 8x8 font. "
        "`palette-counts.png` compares the available palette sizes at the same worst pose. "
        "`detail.png` includes the independent mathematical bitmap reference. "
        "`metadata.json` records byte hashes and independently expanded pixel-error measurements.\n")
    print(json.dumps({key: value for key, value in metadata.items() if key not in ("cases",)}, indent=2))
    print(json.dumps({"cases": [{key: value for key, value in case.items() if key != "perFrameError"}
                               for case in metadata["cases"]]}, indent=2))
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=HERE / "build/font4")
    parser.add_argument("--output", type=Path, default=HERE / "build/font4-preview")
    parser.add_argument("--counts", type=int, nargs="+", default=[64, 128, 256])
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--frames", type=int, default=64)
    main(parser.parse_args())
