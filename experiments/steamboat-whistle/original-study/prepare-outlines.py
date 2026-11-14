#!/usr/bin/env python3
"""Prepare the two selected original-film outline treatments, before scaling.

outlines: fixed native levels15/95, native5x5 minimum, output threshold128.
adaptive: per-frame ink02+.28*(paper90-ink02), width80, native3x3 minimum,
          output threshold145. No masks, redraws or temporal/audio changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image
from scipy import ndimage

BASE = Path(__file__).resolve().parents[1]
CROP = (54, 166, 1224, 874)
PRESETS = [("outlines", "Tydliga konturer", 5, 128, "balance-min5"),
           ("adaptive", "Kontrast per bildruta", 3, 145, "adaptive028-min3")]


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


def prepare(source_json: Path, output: Path) -> dict:
    source_json, output = source_json.resolve(), output.resolve()
    source = json.loads(source_json.read_text())
    if not source.get("passed") or source.get("rgbFormat") != "rgb24":
        raise ValueError("A passed native RGB24 source.json is required")
    rgb_file = source_json.parent / Path(source["rgbFile"]).name
    count, width, height = source["frameCount"], source["sourceWidth"], source["sourceHeight"]
    if rgb_file.stat().st_size != count * width * height * 3:
        raise ValueError("Native RGB size does not match source metadata")
    source_hash = digest(rgb_file)
    if source_hash != source["rgbSha256"]:
        raise ValueError("Native RGB hash does not match source metadata")
    times = source["selectedSourcePTS"]
    if len(times) != count or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("Original source PTS must advance uniquely and monotonically")
    x, y, crop_width, crop_height = CROP
    if x + crop_width > width or y + crop_height > height:
        raise ValueError("Selected crop does not fit this native source")
    rgb = np.memmap(rgb_file, dtype=np.uint8, mode="r", shape=(count, height, width, 3))
    # This original is exactly monochrome RGB, so one native channel is a
    # byte-identical representation of all three native RGB channels.
    for index in range(count):
        if not (np.array_equal(rgb[index, :, :, 0], rgb[index, :, :, 1]) and
                np.array_equal(rgb[index, :, :, 1], rgb[index, :, :, 2])):
            raise ValueError("This calibrated outline treatment requires exactly monochrome RGB")
    native = rgb[:, y:y + crop_height, x:x + crop_width, 0].copy()
    percentiles = np.array([np.percentile(frame, [2, 90]) for frame in native])
    output.mkdir(parents=True, exist_ok=True)
    manifest_file = output / "final-presets.json"
    manifest = json.loads(manifest_file.read_text()) if manifest_file.exists() else {}
    existing = {item["name"]: item for item in manifest.get("candidates", [])}
    untouched = {name: {filename: digest(output / name / filename)
                       for filename in ["gray.frames", "binary.frames"]}
                 for name in existing
                 if (output / name / "gray.frames").exists()}
    comparisons, results = {}, []
    for name, label, footprint, threshold, probe_name in PRESETS:
        folder = output / name
        folder.mkdir(exist_ok=True)
        levels = []
        corrected = np.empty_like(native)
        for index, frame in enumerate(rgb[:, :, :, 0]):
            if name == "outlines":
                black, white = 15., 95.
            else:
                ink, paper = percentiles[index]
                center = ink + .28 * (paper - ink)
                black, white = center - 40, center + 40
            graded = np.clip(np.floor((frame.astype(np.float32) - black) * 255 /
                                      (white - black) + .5), 0, 255).astype(np.uint8)
            corrected[index] = ndimage.minimum_filter(
                graded[y:y + crop_height, x:x + crop_width],
                size=footprint, mode="reflect")
            levels.append({"frame": index, "originalPTS": times[index],
                           "blackPoint": float(black), "whitePoint": float(white),
                           "inkPercentile02": float(percentiles[index, 0]),
                           "paperPercentile90": float(percentiles[index, 1])})
        native_file = folder / "native-corrected.gray.part"
        corrected.tofile(native_file)
        command = ["rtk", "proxy", "ffmpeg", "-v", "error", "-f", "rawvideo",
                   "-pixel_format", "gray", "-video_size", f"{crop_width}x{crop_height}",
                   "-framerate", str(source["fps"]), "-i", str(native_file), "-vf",
                   "scale=300:200:flags=area,pad=320:200:10:0:black", "-pix_fmt",
                   "gray", "-f", "rawvideo", "pipe:1"]
        try:
            decoded = subprocess.run(command, check=True, capture_output=True, timeout=180)
        finally:
            native_file.unlink(missing_ok=True)
        if len(decoded.stdout) != count * 200 * 320:
            raise ValueError(f"Incomplete scaled frames for {name}")
        gray = np.frombuffer(decoded.stdout, np.uint8).reshape(count, 200, 320)
        binary = np.where(gray < threshold, 0, 255).astype(np.uint8)
        save_bytes(folder / "gray.frames", gray.tobytes())
        save_bytes(folder / "binary.frames", binary.tobytes())
        hashes = {filename: digest(folder / filename) for filename in ["gray.frames", "binary.frames"]}
        probe = output / "adaptive-probe" / probe_name
        comparisons[name] = {filename: hashes[filename] == digest(probe / filename)
                             for filename in hashes if (probe / filename).exists()}
        for index in sorted({0, min(12, count - 1), min(13, count - 1),
                             count // 2, count * 3 // 4, count - 1}):
            Image.fromarray(gray[index]).save(folder / f"gray{index:02d}.png")
            Image.fromarray(binary[index]).save(folder / f"frame{index:02d}.png")
        fractions = (binary[:, :, 10:310] == 0).mean(axis=(1, 2))
        parameters = {
            "name": name, "label": label, "adaptiveLevels": name == "adaptive",
            "blackPoint": 15 if name == "outlines" else None,
            "whitePoint": 95 if name == "outlines" else None,
            "brightnessPercent": 0, "perFrameNativeLevels": levels,
            "nativeLevelFormula": ("Fixed black15/white95 on every frame" if name == "outlines"
                                   else "center=inkPercentile02+.28*(paperPercentile90-inkPercentile02); black=center-40; white=center+40"),
            "nativeRGBEquivalentLUT": "clip(floor((native-black)*255/(white-black)+0.5),0,255)",
            "nativeLevelsAppliedBeforeCrop": True,
            "exposureMeasurementCropXYWH": list(CROP),
            "nativeMinimumFilter": {"width": footprint, "height": footprint, "mode": "reflect",
                                    "afterNativeLUT": True, "beforeAreaScaling": True},
            "cropXYWH": list(CROP), "outputContent": [300, 200], "outputFrame": [320, 200],
            "paddingLeftRight": 10, "scaling": "FFmpeg area on native corrected monochrome samples",
            "pipeline": "Native RGB-equivalent levels -> native crop -> native minimum filter -> area300x200 -> black10px sidebars -> threshold",
            "threshold": threshold, "frameCount": count, "fps": source["fps"],
            "sourcePTS": {"presentationFPS": source["fps"], "originalTimesSeconds": times},
            "sourceRGBSha256": source_hash, "sourceMetadataSha256": digest(source_json),
            "sourceMetadata": str(source_json), "sourceRGBIsExactlyGrayscale": True,
            "temporalLevelSmoothing": False, "sourceFrameOrderUnchanged": True,
            "forwardOnly": True, "dithering": False, "retiming": False,
            "masking": False, "redrawing": False, "audioModified": False,
            "inkFraction": {"min": float(fractions.min()), "max": float(fractions.max()),
                            "mean": float(fractions.mean())}, "hashes": hashes,
        }
        (folder / "parameters.json").write_text(json.dumps(parameters, indent=2) + "\n")
        results.append(parameters)
        existing[name] = parameters
    manifest.update({"defaultPreset": "outlines", "candidates": list(existing.values())})
    manifest_file.write_text(json.dumps(manifest, indent=2) + "\n")
    preserved = {name: {filename: digest(output / name / filename) == before
                        for filename, before in filenames.items()}
                 for name, filenames in untouched.items()}
    proof = {"passed": all(all(values.values()) for values in comparisons.values()) and
                       all(all(values.values()) for values in preserved.values()),
             "sourceRGBSha256": source_hash, "sourcePTSUnchanged": times,
             "frameCount": count, "comparisonWithSelectedProbeHashes": comparisons,
             "existingPresetsUnchanged": preserved,
             "outputs": [{key: item[key] for key in ["name", "label", "adaptiveLevels", "hashes"]}
                         for item in results]}
    (output / "prepare-outlines-proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof, indent=2))
    return proof


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-json", type=Path, default=BASE / "work/original-calibration/source/source.json")
    parser.add_argument("--output", type=Path, default=BASE / "work/original-calibration/contrast")
    args = parser.parse_args()
    proof = prepare(args.source_json, args.output)
    if not proof["passed"]:
        raise SystemExit("Selected probe reproduction or preserved-preset proof failed")


if __name__ == "__main__":
    main()
