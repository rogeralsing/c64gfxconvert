#!/usr/bin/env python3
"""Verify the calibrated original-film C64 player and its actual SID audio.

The existing native verifiers own the machine-level contracts. This entry point
adds the source-lineage check that distinguishes the new original-film clip
from the preserved, separately timed GIF version.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_identity(build_folder: Path, assets: Path, calibration: Path) -> dict:
    build = json.loads((build_folder / "build.json").read_text())
    source = json.loads((calibration / "source/source.json").read_text())
    manifest = json.loads((assets / "manifest.json").read_text())
    bitmap = calibration / "contrast/outlines/binary.frames"
    audio = calibration / "source/original-audio.wav"
    if not source["passed"] or (source["startSeconds"], source["durationSeconds"],
                                source["fps"], source["frameCount"]) != (32, 6, 10, 60):
        raise ValueError("Expected the calibrated forward original interval 32–38 seconds")
    pts = source["selectedSourcePTS"]
    if len(pts) != 60 or any(b <= a for a, b in zip(pts, pts[1:])):
        raise ValueError("Original frame timestamps must advance without reversal")
    if manifest["sourceBinarySha256"] != digest(bitmap):
        raise ValueError("Character conversion did not use the selected outline bitmaps")
    if manifest["sourceAudioSha256"] != digest(audio) or digest(audio) != source["audioSha256"]:
        raise ValueError("Original-film soundtrack identity differs")
    if build["preparation"]["sourceSha256"] != digest(audio):
        raise ValueError("The C64 sample source differs from the matching original interval")
    if build["preparation"]["sourceDurationSeconds"] != 6:
        raise ValueError("Expected the complete unretimed six-second soundtrack")
    for filename, installed in (("font.bin", "font.bin"),
                                ("screen.frames", "expected-screen.frames")):
        if (assets / filename).read_bytes() != (build_folder / installed).read_bytes():
            raise ValueError(f"C64 build differs from converted source: {filename}")
    film = build["film"]
    if (film["frameCount"], film["sourceFPS"], film["durationSeconds"]) != (60, 10, 6):
        raise ValueError("C64 movie duration or frame rate differs from calibration")
    if film["expectedRGBAHashes"] != manifest["expectedDecodedRGBAHashes"]:
        raise ValueError("C64 build declares a different reconstructed movie")
    if not film["frontBufferRendering"]:
        raise ValueError("Expected the existing direct front-buffer delta player")
    return {"passed": True, "sourceIntervalSeconds": [32, 38], "frameCount": 60,
            "fps": 10, "durationSeconds": 6, "forwardOnly": True,
            "sourceBitmapSha256": digest(bitmap), "sourceAudioSha256": digest(audio),
            "fontSha256": digest(assets / "font.bin"),
            "screenSha256": digest(assets / "screen.frames"),
            "audioRetimedOrGated": False}


def verify(build_folder: Path, assets: Path, calibration: Path) -> dict:
    build_folder, assets, calibration = (path.resolve() for path in
                                         (build_folder, assets, calibration))
    identity = source_identity(build_folder, assets, calibration)
    spec = importlib.util.spec_from_file_location("original_native_av", EXPERIMENT / "verify_av.py")
    av = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(av)
    with ThreadPoolExecutor(max_workers=1) as pool:
        sound_job = pool.submit(subprocess.run, ["rtk", "proxy", sys.executable,
                                str(EXPERIMENT / "verify.py"), "--build", str(build_folder)],
                                check=True, timeout=120)
        video = av.verify(build_folder, direct_front=True)
        sound_job.result()
    sound = json.loads((build_folder / "verification/verification.json").read_text())
    if not (video["passed"] and sound["passed"]):
        raise ValueError("Native C64 picture or SID verification failed")
    if video["programSha256"] != sound["programSha256"]:
        raise ValueError("Picture and sound verifiers ran different programs")
    if source_identity(build_folder, assets, calibration) != identity:
        raise ValueError("Source inputs changed during native verification")
    result = {"passed": True, "programSha256": video["programSha256"],
              "originalSource": identity, "video": video, "sound": sound}
    output = build_folder / "verification/original-verification.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": True, "frames": 60, "fps": 10,
                      "audio": sound["audio"]["file"], "proof": str(output)}, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=EXPERIMENT / "work/original-c64/player")
    parser.add_argument("--assets", type=Path, default=EXPERIMENT / "work/original-c64/assets")
    parser.add_argument("--calibration", type=Path, default=EXPERIMENT / "work/original-calibration")
    args = parser.parse_args()
    verify(args.build, args.assets, args.calibration)


if __name__ == "__main__":
    main()
