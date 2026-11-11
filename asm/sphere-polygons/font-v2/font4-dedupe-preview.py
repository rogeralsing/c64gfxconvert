#!/usr/bin/env python3
"""Show the existing font after 2x2 coarsening and exact deduplication only."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


HERE = Path(__file__).resolve().parent
WIDTH, HEIGHT, CELLS = 320, 200, 1000
BACKGROUND, FOREGROUND, ACCENT = "#111511", "#e5e8dd", "#d1e891"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def typeface(size=14):
    for file in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf"):
        if Path(file).exists():
            return ImageFont.truetype(file, size)
    return ImageFont.load_default()


def image(values, size):
    return Image.fromarray(np.asarray(values, dtype=np.uint8) * 255, "L").convert("RGB").resize(
        size, Image.Resampling.NEAREST)


def pixels(screen, glyphs):
    return glyphs[screen.reshape(25, 40)].transpose(0, 2, 1, 3).reshape(HEIGHT, WIDTH)


def main(args):
    source, output = args.input.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    original = HERE / "c64-preview/build"
    original_font = (original / "font.bin").read_bytes()
    original_codes = (original / "movie.frames").read_bytes()
    new_font = (source / "font.bin").read_bytes()
    new_codes = (source / "reference.frames").read_bytes()
    mapping = json.loads((source / "map.json").read_text())
    if isinstance(mapping, dict):
        mapping = mapping.get("map", mapping.get("oldToNew", mapping.get("mapping")))
    if len(original_font) != 2048 or len(mapping) != 256:
        raise ValueError("Expected the existing 256-character font and one mapping per old code")
    count = len(new_font) // 8
    if not 1 <= count <= 256 or len(new_font) != count * 8:
        raise ValueError("New font must contain complete eight-byte C64 glyphs")
    if len(original_codes) != len(new_codes) or len(original_codes) % CELLS:
        raise ValueError("Old and remapped screens must have identical frame counts")
    old_frames = np.frombuffer(original_codes, dtype=np.uint8).reshape(-1, CELLS)
    new_frames = np.frombuffer(new_codes, dtype=np.uint8).reshape(-1, CELLS)
    old_glyphs = np.unpackbits(np.frombuffer(original_font, dtype=np.uint8).reshape(256, 8, 1), axis=2)
    new_glyphs = np.unpackbits(np.frombuffer(new_font, dtype=np.uint8).reshape(count, 8, 1), axis=2)
    code_map = np.asarray(mapping, dtype=np.uint8)
    if int(code_map.max()) >= count or int(new_frames.max()) >= count:
        raise AssertionError("A mapped code exceeds the deduplicated font")
    if not np.array_equal(code_map[old_frames], new_frames):
        raise AssertionError("The screen is not the exact old-to-new remap")
    # Independent proof that the new glyphs are only strict 2x2-majority
    # reductions of the old ones, with tied blocks becoming empty.
    logical = old_glyphs.reshape(256, 4, 2, 4, 2).sum(axis=(2, 4)) > 2
    coarse = logical.repeat(2, axis=1).repeat(2, axis=2)
    if not np.array_equal(new_glyphs[code_map], coarse):
        raise AssertionError("The font contains a newly selected or incorrectly coarsened glyph")
    if not np.array_equal(new_glyphs[:, 0::2, :], new_glyphs[:, 1::2, :]) or not np.array_equal(
            new_glyphs[:, :, 0::2], new_glyphs[:, :, 1::2]):
        raise AssertionError("The new glyph pixels are not exact 2x2 blocks")
    if len({glyph.tobytes() for glyph in new_glyphs}) != count:
        raise AssertionError("The supposedly deduplicated font still has duplicates")

    font, small = typeface(), typeface(12)

    def comparison(pose):
        result = Image.new("RGB", (1280, 458), BACKGROUND)
        draw = ImageDraw.Draw(result)
        draw.text((16, 9), f"HOST - existing screens remapped, same pose {pose:03d}; no new palette", fill=FOREGROUND, font=font)
        captions = ["Current font: 256 glyphs, 8x8 pixels", f"Same font coarsened + deduplicated: {count} glyphs"]
        panels = [pixels(old_frames[pose], old_glyphs), pixels(new_frames[pose], new_glyphs)]
        for column, (panel, caption) in enumerate(zip(panels, captions)):
            result.paste(image(panel, (640, 400)), (column * 640, 58))
            draw.text((column * 640 + 16, 35), caption, fill=ACCENT, font=font)
        return result

    comparison(0).save(output / "comparison.png")
    selected = min(args.frames, len(new_frames))
    if selected < 1:
        raise ValueError("The selected preview segment is empty")
    images = [comparison(pose) for pose in range(selected)]
    images[0].save(output / "comparison.gif", save_all=True, append_images=images[1:], duration=40,
                   loop=0, optimize=False)
    columns, cell_width, cell_height, top = 16 if count > 64 else 8, 96, 104, 68
    rows = (count + columns - 1) // columns
    atlas = Image.new("RGB", (columns * cell_width, top + rows * cell_height + 16), BACKGROUND)
    draw = ImageDraw.Draw(atlas)
    draw.text((16, 9), f"Existing font, coarsened and deduplicated: {count} glyphs", fill=FOREGROUND, font=font)
    draw.text((16, 34), "Code / occurrences; each grid square is one logical pixel (2x2 physical)", fill=ACCENT, font=small)
    usage = np.bincount(new_frames.reshape(-1), minlength=count)
    for code, glyph in enumerate(new_glyphs):
        x, y = (code % columns) * cell_width + 16, top + (code // columns) * cell_height
        atlas.paste(image(glyph, (64, 64)), (x, y))
        for line in range(5):
            draw.line((x + line * 16, y, x + line * 16, y + 64), fill="#555c50")
            draw.line((x, y + line * 16, x + 64, y + line * 16), fill="#555c50")
        draw.text((x, y + 72), f"{code:03d} / {int(usage[code])}", fill=FOREGROUND, font=small)
    atlas.save(output / "atlas.png")
    metadata = {
        "pass": True, "kind": "host reconstruction, not native VIC scanout",
        "policy": "Existing 256 font glyphs only; strict-majority 2x2 reduction, ties empty; exact deduplication; original screen codes remapped without reselection.",
        "originalGlyphCount": 256, "uniqueGlyphCount": count,
        "originalFontBytes": len(original_font), "fontBytes": len(new_font),
        "all256GlyphMappingsVerified": True, "allExpandedPixelsAre2x2": True,
        "allScreenCellsRemappedExactly": True, "framesVerified": len(new_frames),
        "physicalScreen": [WIDTH, HEIGHT], "logicalDotScreen": [160, 100],
        "hashes": {"originalFont": sha(original_font), "font": sha(new_font),
                   "originalFrames": sha(original_codes), "frames": sha(new_codes)},
        "gif": {"file": "comparison.gif", "frames": selected, "presentationFps": 25,
                "scope": "Finite host comparison segment repeated from its beginning; no native FPS claim."}
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=HERE / "build/font4-dedupe")
    parser.add_argument("--output", type=Path, default=HERE / "build/font4-dedupe-preview")
    parser.add_argument("--frames", type=int, default=64)
    main(parser.parse_args())
