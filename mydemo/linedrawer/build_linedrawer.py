#!/usr/bin/env python3
"""Build the C64 interactive line drawer.

Emits every binary the asm imports plus the ground-truth expected screen and
a manifest of proofs:
  - 200-glyph charset (2x2-expanded 4x4 tiles, char 0 blank)
  - character stamps, eight orientation maps, and Q8 slope templates
  - sine and reciprocal tables and cube topology for real-time projection
  - collision-free glyph lookup with a displacement per high pattern byte
  - screencode flip maps (identity/h/v/hv)
  - single-pixel and bit-reversal tables
  - expected screen bytes from the reference drawer
Then assembles main.asm with Kick Assembler.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from functools import partial

import linedrawer as L
import char_tables
import cube_model

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"

DEMO_LINES = [              # receipt segments without the H/V cases
    (2, 2, 157, 49), (2, 2, 78, 97), (2, 2, 34, 97), (80, 50, 155, 8),
    (19, 14, 10, 43), (120, 90, 30, 20), (60, 80, 140, 70), (5, 90, 150, 92),
    (150, 10, 152, 95),
    (20, 20, 140, 26), (140, 26, 80, 90), (80, 90, 20, 20),   # triangle:
]                           # every corner is a joint of two edges

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def build_displaced_bank(tile_to_code):
    """Pack each high-byte group into a fixed 512-slot glyph dictionary."""
    slot_count = 512
    slot_mask = slot_count - 1
    groups = [[] for _ in range(256)]
    for pattern, code in tile_to_code.items():
        groups[pattern >> 8].append((pattern & 255, code + 1))

    displacement = [0] * len(groups)
    keys_low = bytearray(slot_count)
    keys_high = bytearray(slot_count)
    values = bytearray(slot_count)
    group_order = sorted(range(len(groups)), key=lambda high: (-len(groups[high]), high))
    for high in group_order:
        group = groups[high]
        if not group:
            continue
        for offset in range(slot_count):
            if all(not values[(offset + low) & slot_mask] for low, _ in group):
                displacement[high] = offset
                for low, code in group:
                    slot = (offset + low) & slot_mask
                    keys_low[slot] = low
                    keys_high[slot] = high
                    values[slot] = code
                break
        else:
            raise ValueError(f"Could not assign glyph slots for high pattern byte {high:02x}")

    displacement_low = bytes(offset & 255 for offset in displacement)
    displacement_high = bytes(offset >> 8 for offset in displacement)
    for pattern in range(65536):
        low, high = pattern & 255, pattern >> 8
        offset = displacement_low[high] | (displacement_high[high] << 8)
        slot = (offset + low) & slot_mask
        code = values[slot] if (keys_low[slot], keys_high[slot]) == (low, high) else 0
        expected = tile_to_code.get(pattern, -1) + 1
        if code != expected:
            raise AssertionError(f"Glyph dictionary mismatch for pattern {pattern:04x}")

    return {
        "hashkl": keys_low,
        "hashkh": keys_high,
        "hashv": values,
        "hash-disp-lo": displacement_low,
        "hash-disp-hi": displacement_high,
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shape", choices=("cube", "football", "globe"))
    renderer_options = parser.add_mutually_exclusive_group()
    renderer_options.add_argument("--compact-joins", action="store_true",
                                  help="use the web lab's compact hybrid font for the globe")
    renderer_options.add_argument("--one-char", action="store_true",
                                  help="benchmark the globe using one fixed block character")
    renderer_options.add_argument("--crossing-holes", action="store_true",
                                  help="use fixed line glyphs and blank cells where they cross")
    renderer_options.add_argument("--exact-corners", action="store_true",
                                  help="draw the globe with exact private corner glyphs")
    renderer_options.add_argument("--fixed-junction-font", action="store_true",
                                  help="draw the globe with a fixed font of connected glyphs")
    args = parser.parse_args()
    clean_junctions = args.exact_corners or args.fixed_junction_font
    shape = args.shape or ("globe" if clean_junctions else "cube")
    if clean_junctions and shape != "globe":
        parser.error("the clean junction renderers require --shape globe")
    window_walker = args.crossing_holes or clean_junctions
    if args.compact_joins and shape != "globe":
        parser.error("--compact-joins requires --shape globe")
    if args.one_char and shape != "globe":
        parser.error("--one-char requires --shape globe")
    if args.crossing_holes and shape != "globe":
        parser.error("--crossing-holes requires --shape globe")
    variant = shape
    renderer = "character group stamps"
    if args.compact_joins:
        variant = "globe-compact"
        renderer = "compact final cells"
    elif args.one_char:
        variant = "globe-one-char"
        renderer = "one fixed block character"
    elif args.crossing_holes:
        variant = "globe-holes"
        renderer = "fixed glyphs with crossing holes"
    elif args.exact_corners:
        variant = "globe-exact-corners"
        renderer = "geometric silhouette snapping and exact private collision glyphs"
    elif args.fixed_junction_font:
        variant = "globe-fixed-junction-font"
        renderer = "geometric silhouette snapping and immutable covering glyphs"
    output = BUILD if shape == "cube" else BUILD / variant
    output.mkdir(parents=True, exist_ok=True)
    program = output / ("linedrawer.prg" if shape == "cube" else f"{variant}.prg")
    tile_to_code, tiles, maps = L.build_font()

    # ---- charset ----
    charset = bytearray(2048)
    for i, t in enumerate(tiles):
        for r in range(4):
            for c in range(4):
                if (t >> (r * 4 + c)) & 1:
                    charset[(i + 1) * 8 + 2 * r] |= 0xC0 >> (2 * c)
                    charset[(i + 1) * 8 + 2 * r + 1] |= 0xC0 >> (2 * c)

    # ---- flip maps on screencodes ----
    flips = bytearray(1024)
    for i in range(256):
        flips[i] = i                      # identity
    for k, name in enumerate(("h", "v", "hv")):
        base = (k + 1) * 256
        for i in range(256):
            flips[base + i] = (maps[name][i - 1] + 1) if 1 <= i <= len(tiles) else i

    # Expected screen for the legacy line fixture.
    expected, demo_joints = L.reference_frame(DEMO_LINES, tile_to_code)

    # Reverse map for composing a line stamp with a previously drawn glyph.
    revlo = bytearray(256)
    revhi = bytearray(256)
    for pat, code in tile_to_code.items():
        revlo[code + 1] = pat & 0xFF
        revhi[code + 1] = pat >> 8
    glyph_lookup = {} if window_walker else build_displaced_bank(tile_to_code)

    rev8 = bytes(int(f"{value:08b}"[::-1], 2) for value in range(256))
    # Full bit reversal swaps the two 4-bit rows. Keep their order for H flips.
    hrev8 = bytes((value >> 4) | ((value & 15) << 4) for value in rev8)
    if window_walker:
        import hole_templates
        stamps = hole_templates.build(tile_to_code)
    else:
        stamps = char_tables.build(tile_to_code)
    generated = {
        "charset": charset, "revlo": revlo, "revhi": revhi,
        "flips": flips,
        "expected": expected, "lines": b"".join(bytes(line) for line in DEMO_LINES),
        "bitlo": bytes((1 << bit) & 255 for bit in range(16)),
        "bithi": bytes((1 << bit) >> 8 for bit in range(16)),
        "rev8": rev8, "hrev8": hrev8,
        **glyph_lookup,
        **stamps,
    }
    if clean_junctions:
        import thin_faces
        thin_faces.write_native(BUILD)
    if args.fixed_junction_font:
        import fixed_junction_font
        generated.update(fixed_junction_font.assets())
    for name, data in generated.items():
        (BUILD / f"{name}.bin").write_bytes(data)

    cube_model.emit()
    frame_screen = cube_model.frame_screen
    frame_segments = cube_model.frame_segments
    assembler_args = []
    mesh_binary = []
    if shape != "cube":
        import ball_model

        vertices, faces, edges = ball_model.emit(shape, BUILD)
        frame_screen = partial(ball_model.frame_screen, shape)
        frame_segments = partial(ball_model.frame_segments, shape)
        assembler_args = [f":mesh={shape}", f":vertices={vertices}",
                          f":faces={faces}", f":edges={edges}"]
        mesh_binary = [f"{shape}-mesh"]
    if args.compact_joins:
        subprocess.run(["node", str(HERE / "build_compact_assets.js"), str(BUILD)], check=True)
        assembler_args.append(":compactJoins=1")
        mesh_binary.extend(("compact-charset", "compact-buckets-lo", "compact-buckets-hi",
                            "compact-buckets-length", "compact-keys", "compact-codes",
                            "compact-hash-disp-lo", "compact-hash-disp-hi", "compact-hash-tags",
                            "compact-hash-codes"))
    if args.one_char:
        assembler_args.append(":oneChar=1")
    if window_walker:
        depth, sweep = ball_model.HOLES_CAMERA
        y_sweep = ball_model.HOLES_Y_SWEEP
        assembler_args.extend((":crossingHoles=1", f":cameraDepth={depth}", f":cameraSweep={sweep}",
                               f":motionY={y_sweep}"))
        frame_segments = partial(ball_model.frame_segments, shape, camera=ball_model.HOLES_CAMERA,
                                 y_sweep=y_sweep)
    if clean_junctions:
        assembler_args.append(":exactCorners=1" if args.exact_corners else ":fixedJunctionFont=1")
        mesh_binary.extend(("thin-topology", "thin-gate"))
        frame_segments = thin_faces.frame_segments
    endpoint_cases = cube_model.prove_normalized_endpoints()
    coverage_misses = cube_model.coverage_receipt(tile_to_code, segments_for=frame_segments)
    if not (args.compact_joins or args.one_char or window_walker):
        for n in range(cube_model.FRAMES_TO_VERIFY):
            screen, _ = frame_screen(n, tile_to_code)
            (output / f"expected_frame{n}.bin").write_bytes(screen)
    sweep_ok = L.sweep(count=1500, seed=7)

    result = subprocess.run(
        [str(Path.home() / ".local/bin/kickass"), "main.asm", "-odir", str(output),
         "-o", str(program), "-symbolfile", *assembler_args],
        cwd=HERE, capture_output=True, text=True)
    (output / "build.log").write_text(result.stdout + result.stderr)
    if result.returncode != 0:
        print(result.stdout[-3000:])
        print(result.stderr[-3000:])
        raise SystemExit("kickass failed")

    binaries = {}
    for name in (
        *generated, "sin", "recip", "recip-far", "size-inverse", "edges", "faces", "edgefaces",
        *mesh_binary,
    ):
        data = (BUILD / f"{name}.bin").read_bytes()
        binaries[name] = {"bytes": len(data), "sha256": sha(data)}
    stamp_bytes = sum(len(data) for data in stamps.values())
    if window_walker:
        symbols = (output / "main.sym").read_text()
        native_size = re.search(r"^\.label assembledHoleGlyphBytes=\$([\da-fA-F]+)\b", symbols, re.M)
        if native_size is None:
            raise ValueError("Missing assembled fixed-font glyph table size")
        stamp_bytes = int(native_size[1], 16)
    report = {
        "passed": bool(sweep_ok and not coverage_misses),
        "shape": shape,
        "defaultRenderer": renderer,
        "glyphs": len(tiles),
        "characterTableBytes": stamp_bytes,
        "glyphLookupBytes": sum(len(data) for data in glyph_lookup.values()),
        "cubeRotationFrames": cube_model.ROTATION_FRAMES,
        "cubeProjection": "live",
        "q8EndpointCases": endpoint_cases,
        "sweepPassed": bool(sweep_ok),
        "cubeCoverageMisses": coverage_misses,
        "demoLines": len(DEMO_LINES),
        "program": str(program),
        "programSha256": sha(program.read_bytes()),
        "jointSlotsUsed": len(demo_joints),
        "binaries": binaries,
    }
    if args.fixed_junction_font:
        report["fixedFontCodes"] = 256
        report["glyphLookupBytes"] = sum(len(data) for name, data in generated.items()
                                         if name.startswith("cover-"))
    (output / "linedrawer.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in (
        "passed", "shape", "defaultRenderer", "glyphs", "characterTableBytes", "glyphLookupBytes",
        "cubeRotationFrames", "cubeProjection", "q8EndpointCases",
        "cubeCoverageMisses", "programSha256",
    )}))

if __name__ == "__main__":
    main()
