#!/usr/bin/env python3
"""Use the existing real-VIC native proof for the four-page grouped decoder."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("grouped_delta_native", HERE / "verify-delta.py")
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)


def main(args):
    root = HERE / "build/grouped-native" / args.dataset
    proof = native.verify("hybrid-front", args.vice, root)
    if not proof["pass"]:
        raise AssertionError("Grouped writes failed native screen/scanout verification")
    build = proof["manifest"]
    corpus = (HERE / "build/codegen" / args.dataset / "reference.frames").read_bytes()
    if (root / "hybrid-front/reference.frames").read_bytes() != corpus[:build["storedFrames"] * 1000]:
        raise AssertionError("Native corpus differs from the host grouped reference")
    report = {
        "pass": True, "dataset": args.dataset, "codec": build["codec"], "abi": build["abi"],
        "storedFrames": build["storedFrames"], "payloadBytes": build["payloadBytes"],
        "sourceArenaBytes": build["dataArenaBytes"], "programBytes": build["programBytes"],
        "codeStateAndPointersBytes": build["codeStateAndPointersBytes"],
        "meanFps": proof["mean_fps"], "renderCycles": proof["render_cycles"],
        "fieldsPerImage": proof["observed_fields_per_image"],
        "nativeFramesVerified": proof["checked_frames"],
        "actualVisibleFieldsVerified": proof["actual_visible_fields_verified"],
        "secondsOfStoredFramesAtMeasuredFps": proof["secondsOfStoredPosesAtMeasuredFps"],
        "angularRangeDegrees": build["angularRangeDegrees"],
        "programSha256": proof["program_sha256"], "movieSha256": proof["movie_sha256"],
        "fullCorpusSha256": hashlib.sha256(corpus).hexdigest(),
        "program": str(root / "hybrid-front/player.prg"),
        "receipt": str(root / "hybrid-front/pal-proof/verification.json"),
        "scope": "Every field of the largest stored forward prefix. Grouping preserves page order and reorders cells within pages; actual VIC scanout is pixel-exact."
    }
    (root / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("analytic", "protected4"), default="analytic")
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    main(parser.parse_args())
