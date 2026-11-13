#!/usr/bin/env python3
"""Verify sound added to the exact approved six-second monochrome GIF movie.

The source screen codes and font are immutable inputs here. This verifier
does not render, rematch, resize or otherwise change the approved pictures.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
APPROVED = HERE / "assets/approved"
PINNED = {
    "manifest.json": "e013c164956dfdaeeba64371119ad911b85d354b21fbb7e0a8fa28d5ab1f4449",
    "screen.frames": "631fa988e77cf2713fc5ac38e8a4b54a5c69f2a4f89b035b27f4ef89344092aa",
    "font.bin": "7fa677802cbea962c5530f0596bfe1e60dffccd6d3739ddd4cb0ff36aa06d5e6",
}
spec = importlib.util.spec_from_file_location("approved_gif_native_proof", HERE / "verify_av.py")
av = importlib.util.module_from_spec(spec)
spec.loader.exec_module(av)


def source_identity(folder: Path) -> dict:
    hashes = {name: av.digest((APPROVED / name).read_bytes()) for name in PINNED}
    assert hashes == PINNED, "Approved GIF source data changed"
    original = json.loads((APPROVED / "manifest.json").read_text())
    build = json.loads((folder / "build.json").read_text())
    assert (original["frameCount"], original["fps"], original["durationSeconds"]) == (60, 10, 6)
    assert build["film"]["frameCount"] == 60
    assert build["film"]["sourceFPS"] == 10
    assert build["film"]["expectedRGBAHashes"] == original["expectedDecodedRGBAHashes"]
    assert (folder / "font.bin").read_bytes() == (APPROVED / "font.bin").read_bytes()
    assert (folder / "expected-screen.frames").read_bytes() == (APPROVED / "screen.frames").read_bytes()
    assert build["preparation"]["sourceDurationSeconds"] == 6
    assert build["preparation"]["sourceSha256"] == "a8b1b7c7d359ada8e3119ed0f74838de57ce764552915b594d769855248a9554"
    assert build["film"]["frontBufferRendering"] is True
    assert 5.9999 <= build["preparation"]["nativeDurationSeconds"] <= 6.0001
    return {"passed": True, "approvedSource": str(APPROVED), "hashes": hashes,
            "identicalFontBytes": 2048, "identicalScreenBytes": 60000,
            "frames": 60, "sourceFPS": 10, "durationSeconds": 6,
            "picturesRerenderedOrRematched": False}


def verify(folder: Path) -> dict:
    folder = folder.resolve()
    identity = source_identity(folder)
    # The two owned VICE runs are independent: one records actual audio and
    # ring generations; the other boots from disk and checks display memory.
    with ThreadPoolExecutor(max_workers=1) as executor:
        capture = executor.submit(subprocess.run, ["rtk", "proxy", sys.executable,
                                  str(HERE / "verify.py"), "--build", str(folder)],
                                  check=True, timeout=90)
        video = av.verify(folder, direct_front=True)
        capture.result()
    sound = json.loads((folder / "verification/verification.json").read_text())
    assert sound["passed"] and video["passed"]
    assert sound["programSha256"] == video["programSha256"]
    assert source_identity(folder) == identity
    result = {"passed": True, "programSha256": video["programSha256"],
              "approvedPictures": identity, "video": video, "sound": sound}
    av.audio.save(folder / "verification/gif-verification.json", result)
    print(json.dumps({"passed": True, "frames": 60, "sourceFPS": 10,
                      "screenAndFontBytesUnchanged": True,
                      "sampleValues": sound["digital"]["samples"],
                      "audio": sound["audio"]["file"]}, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=HERE / "work/mickey-gif-av")
    args = parser.parse_args()
    verify(args.build)
