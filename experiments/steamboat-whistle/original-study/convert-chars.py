#!/usr/bin/env python3
"""Fit the existing weighted Hamming hires font trainer to original-film frames.

The selected original bitmap frames are authoritative. This step does not crop,
resize, grade, retime or change the soundtrack. One newly fitted 256-glyph font
serves all 60 frames, using fixed black foreground and white background.
"""
from __future__ import annotations
import argparse
import hashlib
import heapq
import json
from pathlib import Path
import time
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT, CELLS = 320, 200, 1000
LEVELS = np.array([0], dtype=np.int32)
C64 = np.array([0], dtype=np.uint8)
POPCOUNT = np.array([value.bit_count() for value in range(256)], dtype=np.uint8)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def tiles(frames):
    return frames.reshape(-1, 25, 8, 40, 8).transpose(0, 1, 3, 2, 4).reshape(-1, 64)


# Existing optimizer functions below are reused without algorithm changes.
TRAINER_PROVENANCE = {'optimizerPath': '/Users/rogerjohansson/.codex/worktrees/c64-fine-pixel-dither-20261112/c64/asm/sphere-polygons/font-v2/ecm-solid-font/mickey-gif/hires/build-font.py', 'optimizerSha256': '2eef4184c4349f2161b1bda794c6c673eae4aa7f49720eb7cb60d33dafcc7414', 'monochromeCostPath': '/Users/rogerjohansson/.codex/worktrees/c64-fine-pixel-dither-20261112/c64/asm/sphere-polygons/font-v2/ecm-solid-font/mickey-gif/mono/build-font.py', 'monochromeCostSha256': '3d3805eac257351581d54c5d395f9ba33c3534bdcd19324a2568e003a225dc23', 'copiedFunctions': ['unpack', 'match', 'candidate_masks', 'weighted_gains', 'select_font', 'refine_font', 'decode', 'rgba_hashes', 'verify_matching_literally', 'metrics_for'], 'algorithm': 'Existing frequency/error-weighted greedy selection, exact XOR/popcount cost, one bounded refinement; no new optimizer'}

def unpack(book):
    return np.unpackbits(np.asarray(book, dtype=np.uint8), axis=1, bitorder="big")


def costs_for_book(targets, book, with_colors=False):
    """Original XOR/popcount error, scaled to exact black/white pixel SSE."""
    packed = np.packbits(targets == 0, axis=1, bitorder="big")
    costs = np.empty((len(book), len(targets)), dtype=np.uint32)
    for code_at in range(0, len(book), 64):
        glyphs = book[code_at:code_at + 64]
        for at in range(0, len(targets), 512):
            xor = np.bitwise_xor(glyphs[:, None, :], packed[None, at:at + 512, :])
            mismatch = POPCOUNT[xor].sum(2, dtype=np.uint32)
            costs[code_at:code_at + len(glyphs), at:at + mismatch.shape[1]] = mismatch * 65025
    return (costs, np.zeros(costs.shape, dtype=np.uint8)) if with_colors else costs


def match(targets, book):
    costs, colors = costs_for_book(targets, book, with_colors=True)
    codes = costs.argmin(0).astype(np.uint16)
    positions = np.arange(len(targets))
    return codes, colors[codes, positions], costs[codes, positions]


def candidate_masks(targets, weights, cap):
    # These are actual unions of source color regions, without complement or
    # mirror folding: fixed white BG cannot freely swap/invert its colors.
    anchors = [bytes(8), bytes([255] * 8)]
    anchor_errors = costs_for_book(targets, np.frombuffer(b"".join(anchors), np.uint8).reshape(2, 8)).min(0)
    frequency, difficulty = {}, {}
    for target, count, error in zip(targets, weights, anchor_errors):
        ink = np.unique(target[target != 255])
        for subset in range(1, 1 << len(ink)):
            selected = ink[[bool(subset & (1 << index)) for index in range(len(ink))]]
            key = np.packbits(np.isin(target, selected), bitorder="big").tobytes()
            if key in anchors:
                continue
            frequency[key] = frequency.get(key, 0) + int(count)
            difficulty[key] = difficulty.get(key, 0) + int(count) * int(error)
    by_frequency = sorted(frequency, key=lambda key: (-frequency[key], -difficulty[key], key))
    by_error = sorted(frequency, key=lambda key: (-difficulty[key], -frequency[key], key))
    chosen = list(anchors)
    seen = set(chosen)
    # Keep common regions and infrequent regions responsible for high error.
    for ranked, quota in ((by_frequency, (cap - 2) * 3 // 4), (by_error, cap - 2), (by_frequency, cap - 2)):
        added = 0
        for key in ranked:
            if len(chosen) >= cap or added >= quota:
                break
            if key not in seen:
                chosen.append(key)
                seen.add(key)
                added += 1
    assert len(chosen) >= 256, "Source contains fewer than 256 useful observed shapes."
    book = np.frombuffer(b"".join(chosen), dtype=np.uint8).reshape(-1, 8).copy()
    return book, {"observedSourceRegionMasks": len(frequency) + 2, "candidateCount": len(book),
                  "candidateCap": cap, "frequencyQuota": (cap - 2) * 3 // 4,
                  "candidateSource": "Binary unions of actual source four-gray regions",
                  "orderedDitherSeeds": 0, "randomDitherSeeds": 0,
                  "complementFolding": False, "forcedSymmetryOrbits": False}


def weighted_gains(best, costs, weights):
    gains = np.empty(len(costs), dtype=np.int64)
    for at in range(0, len(costs), 32):
        improvement = np.maximum(best[None, :].astype(np.int64) - costs[at:at + 32], 0)
        gains[at:at + len(improvement)] = improvement @ weights
    return gains


def select_font(candidates, costs, weights):
    # Same weighted error-reduction criterion as the original font optimizer.
    # Lazy upper bounds select the same greedy maximum without rescanning the
    # whole bounded cost matrix 254 times.
    selected = [0, 1]
    selected_set = set(selected)
    best = costs[selected].min(0)
    gains = weighted_gains(best, costs, weights)
    heap = [(-int(gain), index) for index, gain in enumerate(gains) if index not in selected_set]
    heapq.heapify(heap)
    steps = []
    while len(selected) < 256 and heap:
        _, choice = heapq.heappop(heap)
        gain = int(np.maximum(best.astype(np.int64) - costs[choice], 0) @ weights)
        if heap and gain < -heap[0][0]:
            heapq.heappush(heap, (-gain, choice))
            continue
        selected.append(choice)
        selected_set.add(choice)
        best = np.minimum(best, costs[choice])
        steps.append({"code": len(selected) - 1, "candidate": choice,
                      "weightedSquaredErrorSaved": gain,
                      "remainingSquaredError": int(best.astype(np.int64) @ weights)})
        if len(selected) % 32 == 0:
            print(json.dumps({"phase": "greedy", "glyphs": len(selected),
                              "squaredError": steps[-1]["remainingSquaredError"]}), flush=True)
    assert len(selected) == 256
    return candidates[selected].copy(), steps


def refine_font(targets, weights, book, candidates, candidate_costs, rounds):
    history = []
    for iteration in range(rounds):
        codes, foregrounds, errors = match(targets, book)
        before = int(errors.astype(np.int64) @ weights)
        bits = unpack(book)
        updated = book.copy()
        seen = {row.tobytes() for row in book}
        for code in range(2, 256):
            indices = np.flatnonzero(codes == code)
            if not len(indices):
                continue
            target = targets[indices].astype(np.int64)
            fg = LEVELS[foregrounds[indices]].astype(np.int64)[:, None]
            difference = (target - fg) ** 2 - (target - 255) ** 2
            summed = (difference * weights[indices, None]).sum(0)
            proposed_bits = np.where(summed == 0, bits[code], summed < 0)
            proposed = np.packbits(proposed_bits, bitorder="big")
            old_key = updated[code].tobytes()
            seen.remove(old_key)
            if proposed.tobytes() not in seen:
                updated[code] = proposed
            seen.add(updated[code].tobytes())
        next_codes, _, next_errors = match(targets, updated)
        unused = [code for code in range(2, 256) if not np.any(next_codes == code)]
        used_keys = {row.tobytes() for row in updated}
        residual = next_errors.copy()
        for code in unused:
            gains = weighted_gains(residual, candidate_costs, weights)
            choice = None
            for index in np.argsort(-gains, kind="stable"):
                if candidates[index].tobytes() not in used_keys:
                    choice = int(index)
                    break
            if choice is None or gains[choice] <= 0:
                continue
            used_keys.remove(updated[code].tobytes())
            updated[code] = candidates[choice]
            used_keys.add(updated[code].tobytes())
            residual = np.minimum(residual, candidate_costs[choice])
        _, _, final_errors = match(targets, updated)
        after = int(final_errors.astype(np.int64) @ weights)
        assert after <= before
        history.append({"iteration": iteration + 1, "squaredErrorBefore": before,
                        "squaredErrorAfter": after, "saved": before - after,
                        "unusedSlotsConsidered": len(unused)})
        print(json.dumps({"phase": "refinement", **history[-1]}), flush=True)
        book = updated
        if after == before:
            break
    return book, history


def decode(screens, colors, book):
    bits = unpack(book).reshape(len(book), 8, 8)[screens]
    lookup = np.zeros(16, dtype=np.uint8)
    lookup[C64] = LEVELS.astype(np.uint8)
    pixels = np.where(bits, lookup[colors, None, None], 255).astype(np.uint8)
    return pixels.reshape(-1, 25, 40, 8, 8).transpose(0, 1, 3, 2, 4).reshape(-1, HEIGHT, WIDTH)


def rgba_hashes(frames):
    values = []
    for frame in frames:
        rgba = np.empty((HEIGHT, WIDTH, 4), dtype=np.uint8)
        rgba[..., :3] = frame[..., None]
        rgba[..., 3] = 255
        values.append(sha(rgba.tobytes()))
    return values


def verify_matching_literally(targets, codes, foregrounds, errors, book):
    # Independent pixel expansion checks the sufficient-statistics optimizer.
    # Every chosen tile is checked; a spread of targets also checks all256x4
    # alternatives by literal pixel subtraction rather than the cost formula.
    bits = unpack(book)
    actual = np.where(bits[codes], LEVELS[foregrounds, None], 255)
    literal_errors = ((targets.astype(np.int64) - actual) ** 2).sum(1)
    assert np.array_equal(literal_errors, errors)
    for index in np.linspace(0, len(targets) - 1, min(96, len(targets)), dtype=int):
        target = targets[index].astype(np.int64)
        all_errors = []
        for value in LEVELS:
            decoded = np.where(bits, value, 255).astype(np.int64)
            all_errors.append(((decoded - target) ** 2).sum(1))
        assert int(np.min(all_errors)) == int(errors[index])


def metrics_for(gray, nearest, actual, screens, colors, book, base):
    target_tiles = base.tiles(nearest).astype(np.int32)
    source_tiles = base.tiles(gray).astype(np.int32)
    actual_tiles = base.tiles(actual).astype(np.int32)
    different = np.count_nonzero(actual_tiles != target_tiles, axis=1)
    squared = ((actual_tiles - target_tiles).astype(np.int64) ** 2).sum(1)
    gray_squared = ((actual_tiles - source_tiles).astype(np.int64) ** 2).sum(1)
    flat_codes = screens.reshape(-1)
    flat_colors = colors.reshape(-1)

    def example(index):
        frame, position = divmod(int(index), CELLS)
        code = int(flat_codes[index])
        return {"frame": frame, "position": position, "x": position % 40, "y": position // 40,
                "code": code, "foregroundC64": int(flat_colors[index]),
                "squaredError": int(squared[index]), "differentPixels": int(different[index]),
                "sourcePixels": source_tiles[index].tolist(), "targetPixels": target_tiles[index].tolist(),
                "actualPixels": actual_tiles[index].tolist(), "glyphRows": book[code].tolist()}

    per_glyph = []
    for code in range(len(book)):
        indices = np.flatnonzero(flat_codes == code)
        total = int(squared[indices].sum())
        worst = int(indices[np.argmax(squared[indices])]) if len(indices) else None
        per_glyph.append({"code": code, "count": len(indices), "totalSquaredError": total,
                          "averageSquaredError": total / (len(indices) * 64) if len(indices) else 0,
                          "differentPixels": int(different[indices].sum()),
                          "framesUsed": np.unique(indices // CELLS).tolist(),
                          "errorHistogram": np.bincount(different[indices], minlength=65).tolist(),
                          "worstExample": example(worst) if worst is not None else None})
    worst_indices = np.argsort(-squared, kind="stable")[:32]
    total = int(squared.sum())
    return {"frameCount": len(gray), "totalCells": len(flat_codes), "totalPixels": int(nearest.size),
            "errorReference": "Full-resolution nearest four-gray target, fixed global white background",
            "totalSquaredError": total, "averageSquaredError": total / nearest.size,
            "differentPixels": int(different.sum()),
            "graySourceSquaredError": int(gray_squared.sum()), "graySourceMSE": float(gray_squared.sum() / gray.size),
            "errorHistogram": np.bincount(different, minlength=65).tolist(),
            "cellsWithMoreThan3DifferentPixels": int(np.count_nonzero(different > 3)),
            "usedGlyphs": int(np.count_nonzero(np.bincount(flat_codes, minlength=len(book)))),
            "unusedGlyphs": np.flatnonzero(np.bincount(flat_codes, minlength=len(book)) == 0).tolist(),
            "perGlyph": per_glyph, "worstExamples": [example(int(index)) for index in worst_indices],
            "perFrame": [{"frame": frame,
                           "totalSquaredError": int(squared[frame * CELLS:(frame + 1) * CELLS].sum()),
                           "averageSquaredError": float(squared[frame * CELLS:(frame + 1) * CELLS].sum() / (WIDTH * HEIGHT)),
                           "differentPixels": int(different[frame * CELLS:(frame + 1) * CELLS].sum())}
                          for frame in range(len(gray))]}


def pixel_quality(target, actual):
    ink = target == 0
    plotted = actual == 0
    true_ink = int(np.count_nonzero(ink & plotted))
    missing = int(np.count_nonzero(ink & ~plotted))
    extra = int(np.count_nonzero(~ink & plotted))
    return {"pixelCount": int(target.size), "differentPixels": missing + extra,
            "pixelErrorPercent": 100 * (missing + extra) / target.size,
            "sourceInkPixels": int(ink.sum()), "preservedInkPixels": true_ink,
            "missingInkPixels": missing, "extraInkPixels": extra,
            "inkRecall": true_ink / max(1, int(ink.sum()))}


def pictures(output, target, actual, baseline, book, metrics):
    selected = [0, 6, 12, 18, 24, 30, 36, 42, 48, 59]
    image = Image.new("RGB", (960, len(selected) * 224), "#171815")
    draw = ImageDraw.Draw(image)
    for row, index in enumerate(selected):
        for column, (label, frames) in enumerate([
                ("Chosen original bitmap", target), ("New fitted 256 chars", actual),
                ("Old GIF font rematched only", baseline)]):
            x, y = column * 320, row * 224
            draw.text((x + 4, y + 4), f"{label} / frame {index}", fill="white")
            image.paste(Image.fromarray(frames[index]), (x, y + 22))
    image.save(output / "comparison-contact.png")
    # Short side-by-side contact for quick inspection at native output geometry.
    short = Image.new("RGB", (1280, 440), "#171815")
    draw = ImageDraw.Draw(short)
    for column, index in enumerate([0, 13, 36, 59]):
        for row, (label, frames) in enumerate([("Bitmap", target), ("New characters", actual)]):
            x, y = column * 320, row * 220
            draw.text((x + 4, y + 3), f"{label} / frame {index}", fill="white")
            short.paste(Image.fromarray(frames[index]), (x, y + 20))
    short.save(output / "reconstruction-contact.png")
    atlas = Image.new("RGB", (768, 832), "#171815")
    draw = ImageDraw.Draw(atlas)
    bits = unpack(book).reshape(256, 8, 8)
    for code in range(256):
        x, y = (code % 16) * 48, (code // 16) * 52
        glyph = np.where(bits[code], 0, 255).astype(np.uint8)
        atlas.paste(Image.fromarray(glyph).resize((40, 40), Image.Resampling.NEAREST), (x, y))
        draw.text((x, y + 40), f"{code}:{metrics['perGlyph'][code]['count']}", fill="white")
    atlas.save(output / "atlas.png")


def convert(args):
    started = time.monotonic()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    input_path = args.input.resolve()
    source_raw = input_path.read_bytes()
    parameters_path = input_path.parent / "parameters.json"
    parameters = json.loads(parameters_path.read_text())
    frame_count = parameters["frameCount"]
    if len(source_raw) != frame_count * HEIGHT * WIDTH:
        raise ValueError("Selected bitmap size is not frameCount*320*200")
    if sha(source_raw) != parameters["hashes"]["binary.frames"]:
        raise ValueError("Selected original bitmap does not match its grading proof")
    binary = np.frombuffer(source_raw, np.uint8).reshape(frame_count, HEIGHT, WIDTH)
    if not np.isin(binary, [0, 255]).all():
        raise ValueError("Input must be the selected 1-bit bitmap frames")
    source_json = BASE / "work/original-calibration/source/source.json"
    source = json.loads(source_json.read_text())
    audio_path = Path(source["audioFile"])
    source_audio = audio_path.read_bytes()
    if sha(source_audio) != source["audioSha256"]:
        raise ValueError("Original matching source audio does not match source.json")
    if frame_count != 60 or source["fps"] != 10 or source["durationSeconds"] != 6:
        raise ValueError("This native integration expects the original six-second 60-frame clip")
    protected = {name: sha((BASE / "assets/approved" / name).read_bytes())
                 for name in ["font.bin", "screen.frames", "manifest.json"]}
    unique, inverse, weights = np.unique(tiles(binary), axis=0, return_inverse=True, return_counts=True)
    weights = weights.astype(np.int64)
    cap = min(args.candidate_cap, (args.cost_memory_mib * 1024 * 1024) // (len(unique) * 4))
    if cap < 256:
        raise ValueError("Cost memory budget cannot fit 256 candidates")
    print(json.dumps({"phase": "selected-original-bitmap", "uniqueTargetTiles": len(unique),
                      "candidateCap": cap, "sourceBinarySha256": sha(source_raw)}), flush=True)
    candidates, training = candidate_masks(unique, weights, cap)
    costs = costs_for_book(unique, candidates)
    book, steps = select_font(candidates, costs, weights)
    book, refinement = refine_font(unique, weights, book, candidates, costs, args.refine_rounds)
    codes, foregrounds, errors = match(unique, book)
    verify_matching_literally(unique, codes, foregrounds, errors, book)
    if foregrounds.any():
        raise ValueError("Monochrome fitting produced an unexpected color slot")
    screens = codes[inverse].reshape(frame_count, CELLS).astype(np.uint8)
    colors = np.zeros_like(screens)
    actual = decode(screens, colors, book)
    metrics = metrics_for(binary, binary, actual, screens, colors, book, SimpleNamespace(tiles=tiles))
    metrics["errorReference"] = "Selected original outlines bitmap; exact XOR/popcount Hamming distance"
    metrics["fullScreenQuality"] = pixel_quality(binary, actual)
    metrics["contentQuality"] = pixel_quality(binary[:, :, 10:310], actual[:, :, 10:310])
    metrics["perFrameQuality"] = [pixel_quality(binary[i, :, 10:310], actual[i, :, 10:310]) for i in range(frame_count)]
    if metrics["differentPixels"] * 65025 != int(errors.astype(np.int64) @ weights):
        raise ValueError("Decoded reconstruction disagrees with weighted fitting error")
    old_book = np.frombuffer((BASE / "assets/approved/font.bin").read_bytes(), np.uint8).reshape(256, 8)
    old_codes, _, _ = match(unique, old_book)
    old_actual = decode(old_codes[inverse].reshape(frame_count, CELLS), colors, old_book)
    metrics["oldGIFFontRematchedToSameBitmap"] = pixel_quality(binary[:, :, 10:310], old_actual[:, :, 10:310])
    training.update({"candidateSource": "Actual observed masks from selected binary original-film tiles; no dither or geometry seeds",
                     "trainedOnAllFrames": True, "trainingFrameCount": frame_count,
                     "trainingCells": int(weights.sum()), "uniqueTargetTiles": len(unique),
                     "fixedFontGlyphs": 256, "anchors": {"0": "empty", "1": "full"},
                     "boundedCostMatrixBytes": int(costs.nbytes),
                     "costMemoryLimitBytes": args.cost_memory_mib * 1024 * 1024,
                     "greedySteps": steps, "refinements": refinement,
                     "trainerProvenance": TRAINER_PROVENANCE,
                     "literalAllChosenTargetsVerified": True,
                     "literalExhaustiveAlternativeChecks": min(96, len(unique))})
    font_raw = book.tobytes()
    screen_raw = screens.tobytes()
    if len(font_raw) != 2048 or len(screen_raw) != 60000:
        raise ValueError("Native font/screens sizes are incorrect")
    if book[0].any() or not np.all(book[1] == 255):
        raise ValueError("Reused trainer empty/full anchors changed")
    blobs = {"font.bin": font_raw, "screen.frames": screen_raw,
             "nearest.frames": source_raw, "reconstructed.frames": actual.tobytes()}
    for name, raw in blobs.items():
        (output / name).write_bytes(raw)
    write_json(output / "metrics.json", metrics)
    write_json(output / "training.json", training)
    write_json(output / "usage.json", [{key: item[key] for key in ["code", "count", "differentPixels", "framesUsed"]}
                                       for item in metrics["perGlyph"]])
    pictures(output, binary, actual, old_actual, book, metrics)
    protected_after = {name: sha((BASE / "assets/approved" / name).read_bytes()) for name in protected}
    if protected_after != protected or input_path.read_bytes() != source_raw or audio_path.read_bytes() != source_audio:
        raise ValueError("Accepted assets or selected original source changed during fitting")
    manifest = {"passed": True, "title": "Steamboat Willie — originalfilm med tydliga konturer",
                "variant": "original-film-outlines-trained256", "hardwareMode": "hires",
                "ecmEnabled": False, "monochrome": True, "fixedForegroundC64": 0,
                "globalBackgroundC64": 1, "backgroundColorIndex": 1,
                "nativeMovieHasColorStream": False, "colorRamChangesPerFrame": 0,
                "frameCount": frame_count, "fps": 10, "durationSeconds": 6,
                "width": WIDTH, "height": HEIGHT, "columns": 40, "rows": 25,
                "screenFrameBytes": 1000, "glyphs": 256, "fontBytes": 2048,
                "fontSha256": sha(font_raw), "screenSha256": sha(screen_raw),
                "sourceBinarySha256": sha(source_raw), "sourceAudioSha256": sha(source_audio),
                "sourceRGBSha256": source["rgbSha256"], "sourcePTS": source["selectedSourcePTS"],
                "sourceStartSeconds": source["startSeconds"], "sourceFile": source["source"],
                "sourceAudioFile": str(audio_path), "sourceBinaryFile": str(input_path),
                "sourceGrade": parameters, "fontRefitted": True,
                "oneFixedFontForWholeMovie": True, "acceptedAssetsUnchanged": True,
                "pixelAspectRatio": {"numerator": 59, "denominator": 63},
                "dithering": False, "retiming": False, "sourceFrameOrderUnchanged": True,
                "expectedDecodedRGBAHashes": rgba_hashes(actual),
                "metrics": {"fullScreen": metrics["fullScreenQuality"], "content": metrics["contentQuality"],
                            "oldGIFFontRematchedToSameBitmap": metrics["oldGIFFontRematchedToSameBitmap"],
                            "usedGlyphs": metrics["usedGlyphs"]},
                "files": {"font": "font.bin", "screen": "screen.frames", "nearest": "nearest.frames",
                          "reconstructed": "reconstructed.frames", "metrics": "metrics.json",
                          "training": "training.json", "usage": "usage.json", "atlas": "atlas.png"},
                "hashes": {name: sha(raw) for name, raw in blobs.items()},
                "nativePlaybackVerified": False, "elapsedSeconds": time.monotonic() - started}
    for name in ["metrics.json", "training.json", "usage.json"]:
        manifest["hashes"][name] = sha((output / name).read_bytes())
    write_json(output / "manifest.json", manifest)
    print(json.dumps({"passed": True, "output": str(output), "fontSha256": manifest["fontSha256"],
                      "screenSha256": manifest["screenSha256"], "metrics": manifest["metrics"],
                      "elapsedSeconds": manifest["elapsedSeconds"]}, indent=2), flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=BASE / "work/original-calibration/contrast/outlines/binary.frames")
    parser.add_argument("--output", type=Path, default=BASE / "work/original-c64/assets")
    parser.add_argument("--candidate-cap", type=int, default=1536)
    parser.add_argument("--cost-memory-mib", type=int, default=96)
    parser.add_argument("--refine-rounds", type=int, default=1)
    args = parser.parse_args()
    if args.candidate_cap < 256 or args.cost_memory_mib < 16 or not 0 <= args.refine_rounds <= 3:
        parser.error("Need >=256 candidates, >=16 MiB cost memory and 0..3 refinement rounds")
    convert(args)


if __name__ == "__main__":
    main()
