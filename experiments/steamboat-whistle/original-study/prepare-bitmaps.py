#!/usr/bin/env python3
"""Grade native original RGB before crop/area scaling; export four bitmap choices.

Run after prepare-original.py. No masks, adaptive levels, dithering, character
mapping, soundtrack changes or source-frame reordering are performed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parents[1]
DEFAULT_PRESETS = [("cleaner", 15, 75), ("balance", 15, 95),
                   ("contours", 15, 115), ("detail", 45, 115)]
LUMA = np.array([.2126, .7152, .0722], np.float32)


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def save_bytes(path: Path, data: bytes) -> None:
    pending = path.with_suffix(path.suffix + ".part")
    pending.write_bytes(data)
    pending.replace(path)


def preset_argument(value: str) -> tuple[str, int, int]:
    try:
        name, black, white = value.split(":")
        black, white = int(black), int(white)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Preset must be name:black:white") from error
    if not name or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for char in name):
        raise argparse.ArgumentTypeError("Preset name must use lowercase ASCII, digits, - or _")
    if not 0 <= black < white <= 255:
        raise argparse.ArgumentTypeError("Preset needs 0 <= black < white <= 255")
    return name, black, white


def prepare(args: argparse.Namespace) -> dict:
    source_json, output = args.source_json.resolve(), args.output.resolve()
    source = json.loads(source_json.read_text())
    if not source.get("passed") or source.get("rgbFormat") != "rgb24":
        raise ValueError("A passed native RGB24 source.json from prepare-original.py is required")
    rgb_file = source_json.parent / Path(source["rgbFile"]).name
    count, width, height = source["frameCount"], source["sourceWidth"], source["sourceHeight"]
    if rgb_file.stat().st_size != count * width * height * 3:
        raise ValueError("Native RGB size does not match source.json")
    source_hash = digest(rgb_file)
    if source_hash != source["rgbSha256"]:
        raise ValueError("Native RGB hash does not match source.json")
    times = source["selectedSourcePTS"]
    if len(times) != count or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("Source timestamps must be unique and advance forward")
    x, y, crop_width, crop_height = args.crop
    if min(x, y) < 0 or min(crop_width, crop_height) <= 0 or x + crop_width > width or y + crop_height > height:
        raise ValueError("Crop must fit the native source")
    if min(args.content_width, args.content_height) <= 0 or args.canvas_width < args.content_width:
        raise ValueError("Positive content dimensions must fit the canvas")
    if (args.canvas_width - args.content_width) % 2:
        raise ValueError("Canvas minus content width must be even for centered sidebars")
    if not 1 <= args.threshold <= 255:
        raise ValueError("Threshold must be between 1 and 255")
    presets = args.preset or DEFAULT_PRESETS
    if len({name for name, _, _ in presets}) != len(presets):
        raise ValueError("Preset names must be unique")
    padding = (args.canvas_width - args.content_width) // 2
    output.mkdir(parents=True, exist_ok=True)
    report_file = output / "final-presets.json"
    report = json.loads(report_file.read_text()) if report_file.exists() else {}
    prior = {item["name"]: item for item in report.get("candidates", [])}
    results, comparisons = [], {}
    for name, black, white in presets:
        folder = output / name
        folder.mkdir(exist_ok=True)
        expression = f"clip(floor((val-{black})*255/{white-black}+0.5),0,255)"
        filters = (f"lutrgb=r='{expression}':g='{expression}':b='{expression}',"
                   f"crop={crop_width}:{crop_height}:{x}:{y},"
                   f"scale={args.content_width}:{args.content_height}:flags=area,"
                   f"pad={args.canvas_width}:{args.content_height}:{padding}:0:black")
        command = ["rtk", "proxy", "ffmpeg", "-v", "error", "-f", "rawvideo",
                   "-pixel_format", "rgb24", "-video_size", f"{width}x{height}",
                   "-framerate", str(source["fps"]), "-i", str(rgb_file),
                   "-vf", filters, "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
        decoded = subprocess.run(command, check=True, capture_output=True, timeout=180)
        expected_bytes = count * args.content_height * args.canvas_width * 3
        if len(decoded.stdout) != expected_bytes:
            raise ValueError(f"Incomplete area-scaled RGB output for {name}")
        resized = np.frombuffer(decoded.stdout, np.uint8).reshape(
            count, args.content_height, args.canvas_width, 3)
        # Preserve the exact float32 Rec709 calculation used in the calibration.
        gray = np.rint(resized.astype(np.float32) @ LUMA).clip(0, 255).astype(np.uint8)
        binary = np.where(gray < args.threshold, 0, 255).astype(np.uint8)
        save_bytes(folder / "gray.frames", gray.tobytes())
        save_bytes(folder / "binary.frames", binary.tobytes())
        hashes = {filename: digest(folder / filename) for filename in ["gray.frames", "binary.frames"]}
        old_hashes = prior.get(name, {}).get("hashes", {})
        comparisons[name] = {filename: hashes[filename] == old_hashes[filename]
                             for filename in hashes if filename in old_hashes}
        for index in sorted({0, min(12, count - 1), min(13, count - 1),
                             count // 2, count * 3 // 4, count - 1}):
            Image.fromarray(gray[index]).save(folder / f"gray{index:02d}.png")
            Image.fromarray(binary[index]).save(folder / f"frame{index:02d}.png")
        fractions = (binary[:, :, padding:padding + args.content_width] == 0).mean(axis=(1, 2))
        result = {
            "name": name, "blackPoint": black, "whitePoint": white,
            "brightnessPercent": 0,
            "nativeLumaCutoff": black + args.threshold * (white - black) / 255,
            "nativeRGBLUT": expression, "cropXYWH": list(args.crop),
            "outputContent": [args.content_width, args.content_height],
            "outputFrame": [args.canvas_width, args.content_height],
            "paddingLeftRight": padding,
            "scaling": "FFmpeg area RGB, after native RGB LUT",
            "grayscale": "Rec709 round RGB dot [.2126,.7152,.0722]",
            "threshold": args.threshold, "frameCount": count,
            "sourcePTS": {"presentationFPS": source["fps"], "originalTimesSeconds": times},
            "forwardOnly": True, "dithering": False, "retiming": False,
            "sourceRGBSha256": source_hash, "sourceMetadata": str(source_json),
            "inkFraction": {"min": float(fractions.min()), "max": float(fractions.max()),
                            "mean": float(fractions.mean()),
                            "frame13": float(fractions[min(13, count - 1)])},
            "hashes": hashes, "ffmpegCommand": command,
        }
        # Retain prior manual background-patch measurements only when the native
        # LUT and crop are identical; this utility does not invent new masks.
        old = prior.get(name, {})
        if old.get("nativeRGBLUT") == expression and old.get("cropXYWH") == list(args.crop):
            for key in ["conservativeBackgroundPatchBlackFractions", "backgroundPatchXYXY"]:
                if key in old:
                    result[key] = old[key]
        (folder / "parameters.json").write_text(json.dumps(result, indent=2) + "\n")
        results.append(result)
    updated = {item["name"]: item for item in report.get("candidates", [])}
    updated.update({item["name"]: item for item in results})
    report.update({"defaultPreset": "balance", "candidates": list(updated.values())})
    report_file.write_text(json.dumps(report, indent=2) + "\n")
    proof = {"passed": True, "sourceRGBSha256": source_hash,
             "frameCount": count, "unchangedSourcePTS": times,
             "comparisonWithPreviousOutputHashes": comparisons,
             "presets": [{key: item[key] for key in ["name", "blackPoint", "whitePoint", "hashes"]}
                         for item in results]}
    (output / "prepare-bitmaps-proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    # New four-preset contact; existing candidate/probe reports remain untouched.
    contact = Image.new("RGB", (960, len(results) * 150), "#232323")
    draw = ImageDraw.Draw(contact)
    for row, result in enumerate(results):
        name = result["name"]
        raw = np.memmap(output / name / "binary.frames", dtype=np.uint8, mode="r",
                        shape=(count, args.content_height, args.canvas_width))
        for col, index in enumerate([0, min(12, count - 1), count // 2, count * 3 // 4, count - 1]):
            draw.text((col * 192 + 3, row * 150 + 3), f"{name} {times[index]:.3f}s", fill="white")
            contact.paste(Image.fromarray(raw[index]).resize((192, 120), Image.Resampling.NEAREST),
                          (col * 192, row * 150 + 23))
    contact.save(output / "four-presets-timeline.png")
    print(json.dumps(proof, indent=2))
    return proof


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-json", type=Path, default=BASE / "work/original-calibration/source/source.json")
    parser.add_argument("--output", type=Path, default=BASE / "work/original-calibration/contrast")
    parser.add_argument("--preset", type=preset_argument, action="append", help="name:black:white; repeat to override four defaults")
    parser.add_argument("--crop", type=int, nargs=4, metavar=("X", "Y", "WIDTH", "HEIGHT"), default=(54, 166, 1224, 874))
    parser.add_argument("--content-width", type=int, default=300)
    parser.add_argument("--content-height", type=int, default=200)
    parser.add_argument("--canvas-width", type=int, default=320)
    parser.add_argument("--threshold", type=int, default=128)
    prepare(parser.parse_args())


if __name__ == "__main__":
    main()
