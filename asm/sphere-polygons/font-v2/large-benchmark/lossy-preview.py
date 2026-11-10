#!/usr/bin/env python3
"""Render labelled host comparisons of decoded lossy character frames."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


HERE = Path(__file__).resolve().parent
WIDTH, HEIGHT, CELLS = 320, 200, 1000
FONT_SHA256 = "e4071e1e3176e3ee65eeb5fc2df5bb3eccab7b733b9ea7cbb276a2f3a65a1aac"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_font():
    for name in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf"):
        if Path(name).exists():
            return ImageFont.truetype(name, 14)
    return ImageFont.load_default()


def pixels(screen, glyphs):
    return glyphs[screen.reshape(25, 40)].transpose(0, 2, 1, 3).reshape(HEIGHT, WIDTH)


def comparison(target, decoded, pose, errors, typeface, threshold, difference=False, protect_solids=False):
    panels = [target, decoded]
    if difference:
        mask = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        mask[np.not_equal(target, decoded)] = (255, 70, 70)
        panels.append(mask)
    result = Image.new("RGB", (len(panels) * 640, 458), "#111511")
    draw = ImageDraw.Draw(result)
    draw.text((16, 9), "HOST RECONSTRUCTION - fixed C64 font, not emulator scanout", fill="#e5e8dd", font=typeface)
    policy = "; keep solid updates" if protect_solids else ""
    captions = ["Lossless character frames", f"Lossy: skip changes of <={threshold} pixels{policy}", "Difference mask (red)"]
    for index, panel in enumerate(panels):
        if panel.ndim == 2:
            image = Image.fromarray(panel * 255, "L").convert("RGB")
        else:
            image = Image.fromarray(panel, "RGB")
        result.paste(image.resize((640, 400), Image.Resampling.NEAREST), (index * 640, 58))
        draw.text((index * 640 + 16, 35), captions[index], fill="#d1e891", font=typeface)
    draw.text((max(16, result.width - 390), 9), f"pose {pose:03d} - {errors} differing pixels", fill="#e5e8dd", font=typeface)
    return result


def main(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    font_data, target_data, lossy_data = args.font.read_bytes(), args.target.read_bytes(), args.lossy.read_bytes()
    if len(font_data) != 2048 or digest(font_data) != FONT_SHA256:
        raise ValueError("Expected the selected fixed 256-character font")
    if len(target_data) != len(lossy_data) or len(target_data) % CELLS:
        raise ValueError("Target and decoded lossy inputs must contain matching complete character screens")
    target_frames = np.frombuffer(target_data, dtype=np.uint8).reshape(-1, CELLS)
    lossy_frames = np.frombuffer(lossy_data, dtype=np.uint8).reshape(-1, CELLS)
    glyphs = np.unpackbits(np.frombuffer(font_data, dtype=np.uint8).reshape(256, 8, 1), axis=2)
    count = len(target_frames)
    error_counts = []
    max_cell_error = 0
    error_cell_counts = []
    solid_pixel_errors = []
    solid_error_cells = []
    longest_error_streak = np.zeros(CELLS, dtype=np.uint16)
    error_streak = np.zeros(CELLS, dtype=np.uint16)
    targets, decoded = [], []
    for pose, (target, lossy) in enumerate(zip(target_frames, lossy_frames)):
        reference, current = pixels(target, glyphs), pixels(lossy, glyphs)
        diff = np.not_equal(reference, current)
        cell_errors = diff.reshape(25, 8, 40, 8).transpose(0, 2, 1, 3).reshape(CELLS, 64).sum(axis=1)
        # This independently expands both fonts, rather than trusting the
        # encoder's distance table or its recorded per-frame error counts.
        cell_max = int(cell_errors.max())
        if cell_max > args.threshold:
            raise AssertionError(f"Pose {pose} exceeds the per-cell error bound: {cell_max}")
        max_cell_error = max(max_cell_error, cell_max)
        errors = int(diff.sum())
        error_counts.append(errors)
        error_cell_counts.append(int(np.count_nonzero(cell_errors)))
        solid_targets = np.logical_or(target == 0, target == 15)
        solid_pixels = int(cell_errors[solid_targets].sum())
        solid_cells = int(np.count_nonzero(cell_errors[solid_targets]))
        if args.protect_solids and solid_pixels:
            raise AssertionError(f"Protected solid targets differ at pose {pose}: {solid_pixels} pixels")
        solid_pixel_errors.append(solid_pixels)
        solid_error_cells.append(solid_cells)
        error_streak = np.where(cell_errors != 0, error_streak + 1, 0)
        longest_error_streak = np.maximum(longest_error_streak, error_streak)
        targets.append(reference)
        decoded.append(current)

    typeface = load_font()
    worst = int(np.argmax(error_counts))
    comparison(targets[worst], decoded[worst], worst, error_counts[worst], typeface, args.threshold,
               True, args.protect_solids).save(output / "worst-error.png")
    sample_poses = sorted(set([0, worst, *range(0, count, 64)]))
    contact = Image.new("RGB", (1920, len(sample_poses) * 458), "#111511")
    for row, pose in enumerate(sample_poses):
        contact.paste(comparison(targets[pose], decoded[pose], pose, error_counts[pose], typeface,
                                args.threshold, True, args.protect_solids), (0, row * 458))
    contact.save(output / "contact-sheet.png")
    selected = min(args.frames, count - args.start)
    if selected < 1:
        raise ValueError("Comparison segment is empty")
    images = [comparison(targets[pose], decoded[pose], pose, error_counts[pose], typeface, args.threshold,
                         protect_solids=args.protect_solids)
              for pose in range(args.start, args.start + selected)]
    gif_name = f"lossless-vs-lossy{args.threshold}.gif"
    images[0].save(output / gif_name, save_all=True, append_images=images[1:],
                   duration=40, loop=0, optimize=False)
    report = {
        "pass": True, "kind": "host reconstruction from character codes and immutable font",
        "notNativeScanout": True, "dataset": args.dataset, "threshold": args.threshold,
        "protectSolidTargets": args.protect_solids,
        "framesVerified": count, "fontSha256": digest(font_data),
        "targetFramesSha256": digest(target_data), "lossyFramesSha256": digest(lossy_data),
        "pixelErrorRelativeToLosslessFontOutput": {"min": min(error_counts),
            "mean": sum(error_counts) / count, "max": max(error_counts),
            "meanPercentOfScreen": sum(error_counts) / count / (WIDTH * HEIGHT) * 100,
            "worstPose": worst, "perFrame": error_counts},
        "maxErrorWithinOneCharacter": max_cell_error,
        "errorCellsPerFrame": {"min": min(error_cell_counts), "mean": sum(error_cell_counts) / count,
                               "max": max(error_cell_counts)},
        "pixelErrorsInEmptyOrFullTargetCells": {"min": min(solid_pixel_errors),
            "mean": sum(solid_pixel_errors) / count, "max": max(solid_pixel_errors),
            "totalOverAllFrames": sum(solid_pixel_errors)},
        "nonzeroErrorCellsWithEmptyOrFullTarget": {"min": min(solid_error_cells),
            "mean": sum(solid_error_cells) / count, "max": max(solid_error_cells),
            "totalOverAllFrames": sum(solid_error_cells)},
        "longestConsecutiveFramesWithNonzeroErrorInOneCell": int(longest_error_streak.max()),
        "gif": {"file": gif_name, "frames": selected, "startPose": args.start,
                "presentationFps": 25, "durationSeconds": selected / 25,
                "scope": "Repeated finite host-comparison segment; the jump back to its beginning is not a native full-turn animation claim."},
        "worstErrorImage": "worst-error.png", "contactSheet": "contact-sheet.png"
    }
    (output / "metadata.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items()
                      if key != "pixelErrorRelativeToLosslessFontOutput"}, indent=2))
    print(json.dumps({"pixelErrors": {key: value for key, value in report["pixelErrorRelativeToLosslessFontOutput"].items()
                                     if key != "perFrame"}}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--lossy", type=Path, required=True)
    parser.add_argument("--font", type=Path, default=HERE / "../c64-preview/build/font.bin")
    parser.add_argument("--output", type=Path, default=HERE / "build/lossy-preview/analytic")
    parser.add_argument("--dataset", default="analytic")
    parser.add_argument("--threshold", type=int, default=2)
    parser.add_argument("--protect-solids", action="store_true",
                        help="Assert and label that empty/full target updates are always preserved")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--frames", type=int, default=64)
    main(parser.parse_args())
