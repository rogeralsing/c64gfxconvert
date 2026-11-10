#!/usr/bin/env python3
"""Verify actual PAL/VIC playback with a true variable-sized 4x4-logical font."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("font4_native_delta", HERE / "large-benchmark/verify-delta.py")
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)


def main(args):
    root = HERE / "build/font4-native" / f"font{args.glyphs}"
    name = f"{args.codec}-front"
    font = (root / name / "font.bin").read_bytes()
    if len(font) != args.glyphs * 8:
        raise AssertionError("Native font must load exactly eight bytes per selected glyph")
    for code in range(args.glyphs):
        for row in range(8):
            value = font[code * 8 + row]
            if value != font[code * 8 + (row ^ 1)]:
                raise AssertionError("Logical rows do not expand exactly2x")
            for column in range(0, 8, 2):
                if (value >> column) & 1 != (value >> (column + 1)) & 1:
                    raise AssertionError("Logical columns do not expand exactly2x")
    proof = native.verify(name, args.vice, root)
    if not proof["pass"]:
        raise AssertionError("Native font4 playback failed scanout verification")
    build = proof["manifest"]
    corpus = (HERE / "build/font4-storage" / f"font{args.glyphs}" / "reference.frames").read_bytes()
    if (root / name / "reference.frames").read_bytes() != corpus[:build["storedFrames"] * 1000]:
        raise AssertionError("Native source does not match the host fixed-font corpus")
    result = {"pass": True, "glyphCount": args.glyphs, "codec": args.codec,
              "fontBytes": len(font), "packedLogicalFontBytes": args.glyphs * 2,
              "fontRamSavedVersus256Glyph8x8": 2048 - len(font),
              "storedFrames": build["storedFrames"], "payloadBytes": build["payloadBytes"],
              "sourceArenaBytes": build["dataArenaBytes"],
              "codeStateAndPointersBytes": build["codeStateAndPointersBytes"],
              "meanFps": proof["mean_fps"], "renderCycles": proof["render_cycles"],
              "fieldsPerImage": proof["observed_fields_per_image"],
              "nativeFramesVerified": proof["checked_frames"],
              "actualVisibleFieldsVerified": proof["actual_visible_fields_verified"],
              "secondsOfStoredFramesAtMeasuredFps": proof["secondsOfStoredPosesAtMeasuredFps"],
              "angularRangeDegrees": build["angularRangeDegrees"],
              "programSha256": proof["program_sha256"], "movieSha256": proof["movie_sha256"],
              "fontSha256": proof["font_sha256"],
              "fullCorpusSha256": hashlib.sha256(corpus).hexdigest(),
              "program": str(root / name / "player.prg"),
              "receipt": str(root / name / "pal-proof/verification.json"),
              "scope": "Every actual VIC field of the stored forward prefix, normalPAL, speed100%, warpdisabled. Allscreen glyphcodes are below the selected font count."}
    (root / f"summary-{args.codec}.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--glyphs", type=int, choices=(64, 128, 256), default=64)
    parser.add_argument("--codec", choices=("groups", "hybrid"), default="hybrid")
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    main(parser.parse_args())
