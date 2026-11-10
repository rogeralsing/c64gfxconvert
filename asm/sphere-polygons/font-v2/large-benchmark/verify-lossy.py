#!/usr/bin/env python3
"""Verify native lossy-reference playback and bound its independent pixel error."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("lossy_delta_native", HERE / "verify-delta.py")
delta = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(delta)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check_error(dataset, threshold, reference, protect_solids=False):
    font = (HERE.parent / "c64-preview/build/font.bin").read_bytes()
    ideal_path = (HERE.parent / "c64-preview/build/movie.frames") if dataset == "analytic" else HERE / "build/geometry/frames.screen"
    ideal = ideal_path.read_bytes()
    reconstructed = reference.read_bytes()
    if len(ideal) != 384000 or len(reconstructed) != len(ideal) or len(font) != 2048:
        raise ValueError("Expected 384 complete character screens and a fixed 2048-byte font")
    if reconstructed[:1000] != ideal[:1000]:
        raise AssertionError("The seed screen must remain exact")
    distances = [[sum((font[a * 8 + row] ^ font[b * 8 + row]).bit_count() for row in range(8))
                  for b in range(256)] for a in range(256)]
    solid_codes = {code for code in range(256) if font[code * 8:(code + 1) * 8] in (bytes(8), bytes([255]) * 8)}
    frame_errors = []
    differing_cells = []
    worst_cell = 0
    solid_cells_checked = 0
    for pose in range(384):
        errors = 0
        changed = 0
        for cell in range(1000):
            at = pose * 1000 + cell
            wanted, actual = ideal[at], reconstructed[at]
            if protect_solids and wanted in solid_codes:
                solid_cells_checked += 1
                if actual != wanted:
                    raise AssertionError(f"Solid target changed at pose {pose}, cell {cell}")
            difference = distances[wanted][actual]
            if difference > threshold:
                raise AssertionError(f"Cell error exceeds threshold at pose {pose}, cell {cell}: {difference}")
            worst_cell = max(worst_cell, difference)
            errors += difference
            changed += wanted != actual
        frame_errors.append(errors)
        differing_cells.append(changed)
    return {"pass": True, "frames": 384, "cellsChecked": 384000,
            "thresholdPixelsPerCell": threshold, "worstCellPixelError": worst_cell,
            "solidTargetsProtected": protect_solids, "solidTargetCellsChecked": solid_cells_checked,
            "pixelErrorsPerFrame": {"min": min(frame_errors), "mean": statistics.mean(frame_errors), "max": max(frame_errors)},
            "differentCharacterCellsPerFrame": {"min": min(differing_cells), "mean": statistics.mean(differing_cells), "max": max(differing_cells)},
            "idealScreensSha256": sha(ideal), "displayedScreensSha256": sha(reconstructed),
            "fontSha256": sha(font),
            "scope": "Extra pixel error against the lossless font-rendered target, not against the mathematical sphere bitmap."}


def reuse_identical_proof(root, name, dataset):
    baseline_root = HERE / "build/delta"
    if dataset == "geometry":
        baseline_root /= "geometry-native"
    baseline, current = baseline_root / name, root / name
    files = ("player.prg", "movie.bin", "font.bin", "initial.screen", "reference.frames", "pointers.bin")
    identity = {}
    for filename in files:
        original, candidate = (baseline / filename).read_bytes(), (current / filename).read_bytes()
        if candidate != original:
            raise AssertionError("Cannot reuse native proof: changed " + filename)
        identity[filename] = {"byteIdentical": True, "sha256": sha(candidate), "bytes": len(candidate)}
    receipt = baseline / "pal-proof/verification.json"
    proof = json.loads(receipt.read_text())
    if not proof["pass"] or proof["program_sha256"] != identity["player.prg"]["sha256"]:
        raise AssertionError("Original native proof is missing or does not match the exact PRG")
    proof["manifest"] = json.loads((current / "build.json").read_text())
    proof["measurement_reused_by_byte_identity"] = True
    proof["reused_receipt"] = str(receipt)
    proof["identity_checks"] = identity
    return proof


def main(args):
    directory = f"threshold-{args.threshold}" + ("-protect-solids" if args.protect_solids else "")
    root = HERE / "build/lossy-native" / args.dataset / directory
    manifest = json.loads((root / "manifest.json").read_text())
    error = check_error(args.dataset, args.threshold, Path(manifest["framesPath"]), args.protect_solids)
    names = args.variants or manifest["variants"]
    proofs = []
    for name in names:
        if name not in manifest["variants"]:
            raise ValueError("Unknown native variant " + name)
        build = json.loads((root / name / "build.json").read_text())
        expected_prefix = Path(manifest["framesPath"]).read_bytes()[:build["storedFrames"] * 1000]
        if (root / name / "reference.frames").read_bytes() != expected_prefix:
            raise AssertionError("Native build reference differs from the current feedback-filtered source")
        proof = reuse_identical_proof(root, name, args.dataset) if args.reuse_identical else delta.verify(name, args.vice, root)
        if not proof["pass"]:
            raise AssertionError("Native playback did not pass: " + name)
        build = proof["manifest"]
        row = {"name": name, "pass": True, "dataset": args.dataset, "threshold": args.threshold,
               "protectSolids": args.protect_solids,
               "storedFrames": build["storedFrames"], "payloadBytes": build["payloadBytes"],
               "sourceArenaBytes": build["dataArenaBytes"], "programBytes": build["programBytes"],
               "codeStateAndPointersBytes": build["codeStateAndPointersBytes"],
               "fontBytes": build["fontBytes"], "seedScreenBytes": build["seedScreenBytes"],
               "workScreenBytes": build["workScreenBytes"],
               "meanFps": proof["mean_fps"], "renderCycles": proof["render_cycles"],
               "copyCycles": proof["copy_cycles"], "fieldsPerImage": proof["observed_fields_per_image"],
               "nativeFramesVerified": proof["checked_frames"],
               "actualVisibleFieldsVerified": proof["actual_visible_fields_verified"],
               "secondsOfStoredFramesAtMeasuredFps": proof["secondsOfStoredPosesAtMeasuredFps"],
               "angularRangeDegrees": build["angularRangeDegrees"],
               "programSha256": proof["program_sha256"], "movieSha256": proof["movie_sha256"],
               "referenceSha256": proof["reference_sha256"],
               "program": str(root / name / "player.prg"),
               "receipt": proof.get("reused_receipt", str(root / name / "pal-proof/verification.json")),
               "measurementReusedByByteIdentity": proof.get("measurement_reused_by_byte_identity", False),
               "identityChecks": proof.get("identity_checks"),
               "scope": "All stored forward-prefix frames; not an all-384-transition native sweep."}
        (root / f"native-{name}.json").write_text(json.dumps(row, indent=2) + "\n")
        proofs.append(row)
    all_rows = []
    for name in manifest["variants"]:
        summary = root / f"native-{name}.json"
        if summary.is_file():
            row = json.loads(summary.read_text())
            if row["programSha256"] != sha((root / name / "player.prg").read_bytes()):
                raise AssertionError("Stale native summary for " + name)
            if row["referenceSha256"] != sha((root / name / "reference.frames").read_bytes()):
                raise AssertionError("Stale native reference summary for " + name)
            all_rows.append(row)
    result = {"pass": len(all_rows) == len(manifest["variants"]) and all(row["pass"] for row in all_rows),
              "dataset": args.dataset, "thresholdPixelsPerCell": args.threshold,
              "protectSolids": args.protect_solids,
              "errorBound": error, "variants": {row["name"]: row for row in all_rows},
              "nativePlayerUnchanged": True, "filteredDuringPlayback": False}
    (root / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variants", nargs="*")
    parser.add_argument("--dataset", choices=("analytic", "geometry"), default="analytic")
    parser.add_argument("--threshold", type=int, default=2)
    parser.add_argument("--protect-solids", action="store_true", help="Use the host policy that keeps empty and full target cells exact")
    parser.add_argument("--reuse-identical", action="store_true", help="Reuse an existing passing native receipt only after exact binary and input equality checks")
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    main(parser.parse_args())
