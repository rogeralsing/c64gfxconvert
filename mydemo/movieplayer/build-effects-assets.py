#!/usr/bin/env python3
"""Pack three frozen symmetric ECM movies as independently readable row spans.

This is a lossless transport for the existing screen/color frames. It never
opens a 3D source, selects glyphs or changes any existing generated dataset.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
FONT_SHA = "180223a47f20c13a5ca203d00d80cc49db6d3d5504589c02c0ed59d01870043f"
OBJECTS = ("star-lit", "cube-lit", "ball-lit")
C64 = (0, 12, 15, 1)
FRAMES, ROWS, COLUMNS = 49, 25, 40
DICTIONARY_SIZE = 220


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def render(screens, colors, font, levels):
    """Independent ECM pixel interpretation; no movie-matcher imports."""
    bits = np.unpackbits(np.frombuffer(font, dtype=np.uint8).reshape(64, 8), axis=1)
    foreground = np.empty(colors.shape, dtype=np.uint8)
    for index, actual_c64 in enumerate(C64):
        foreground[colors == actual_c64] = levels[index]
    cells = np.where(bits[screens & 63] != 0, foreground[..., None],
                     np.asarray(levels, dtype=np.uint8)[screens >> 6, None])
    return cells.reshape(FRAMES, ROWS, COLUMNS, 8, 8).transpose(0, 1, 3, 2, 4).reshape(FRAMES, 200, 320)


def rgba_hashes(pixels):
    result = []
    for frame in pixels:
        rgba = np.empty((200, 320, 4), dtype=np.uint8)
        rgba[..., :3] = frame[..., None]
        rgba[..., 3] = 255
        result.append(sha(rgba.tobytes()))
    return result


def row_span(screen, color, glyph_ones):
    foreground_visible = ((screen & 63) != 0) & (color != 0)
    background_visible = (glyph_ones[screen & 63] != 64) & ((screen >> 6) != 0)
    occupied = np.flatnonzero(foreground_visible | background_visible)
    if not len(occupied):
        assert not screen.any() and not color.any(), "A black row must use the normalized empty cell."
        return 0, 0
    first, last = int(occupied[0]), int(occupied[-1]) + 1
    assert not screen[:first].any() and not screen[last:].any()
    assert not color[:first].any() and not color[last:].any()
    return first, last


def encode_row(screen, color, dictionary):
    result = bytearray()
    at = 0
    while at < len(screen):
        code, foreground = int(screen[at]), int(color[at])
        if code & 63 == 0:
            count = 1
            while at + count < len(screen) and count < 8 and int(screen[at + count]) == code:
                count += 1
            result.append(220 + (code >> 6) * 8 + count - 1)
            at += count
        elif (code, foreground) in dictionary:
            result.append(dictionary[code, foreground])
            at += 1
        else:
            result.extend((252 + C64.index(foreground), code))
            at += 1
    return bytes(result)


def decode_movie(raw, offsets, dictionary_screen, dictionary_color):
    """Decode independently of the encoder's spans and token choices."""
    screens = np.zeros((FRAMES, ROWS, COLUMNS), dtype=np.uint8)
    colors = np.zeros(screens.shape, dtype=np.uint8)
    row_token_statistics = Counter()
    for frame in range(FRAMES):
        at = int(offsets[frame])
        for row in range(ROWS):
            start, length = raw[at:at + 2]
            at += 2
            stop = at + length
            x = start
            while at < stop:
                token = raw[at]
                at += 1
                if token < 220:
                    codes, inks = [dictionary_screen[token]], [dictionary_color[token]]
                    row_token_statistics["dictionary"] += 1
                elif token < 252:
                    relative = token - 220
                    count = relative % 8 + 1
                    codes, inks = [relative // 8 << 6] * count, [0] * count
                    row_token_statistics["toneRun"] += 1
                else:
                    assert at < stop, "Truncated escape token."
                    codes, inks = [raw[at]], [C64[token - 252]]
                    at += 1
                    row_token_statistics["escape"] += 1
                assert x + len(codes) <= COLUMNS
                screens[frame, row, x:x + len(codes)] = codes
                colors[frame, row, x:x + len(codes)] = inks
                x += len(codes)
            assert at == stop
        assert at == (int(offsets[frame + 1]) if frame + 1 < FRAMES else len(raw))
    return screens.reshape(FRAMES, 1000), colors.reshape(FRAMES, 1000), dict(row_token_statistics)


def zoom_tables(font):
    bitmaps = np.unpackbits(np.frombuffer(font, dtype=np.uint8).reshape(64, 8), axis=1).reshape(64, 8, 8)
    candidates = bitmaps.reshape(64, 64)
    mapping, swaps, errors = [], [], []
    for source in bitmaps:
        enlarged = source.repeat(2, axis=0).repeat(2, axis=1)
        for top, left in ((0, 0), (0, 8), (8, 0), (8, 8)):
            target = enlarged[top:top + 8, left:left + 8].reshape(64)
            plain = (candidates != target).sum(1)
            inverted = 64 - plain
            # Deterministic ties: exact-color orientation before exchanged
            # colors, then lowest glyph index.
            all_errors = np.concatenate((plain, inverted))
            index = int(all_errors.argmin())
            mapping.append(index % 64)
            swaps.append(index // 64)
            errors.append(int(all_errors[index]))
            reconstructed = candidates[index % 64] ^ (index // 64)
            assert int((reconstructed != target).sum()) == errors[-1]
    return bytes(mapping), bytes(swaps), {
        "quadrantOrder": ["tl", "tr", "bl", "br"], "entries": 256,
        "method": "Minimum 8x8 bitmap Hamming error over frozen glyphs and their complements",
        "sourceExpansion": "Nearest-neighbor 2x in both physical pixel axes",
        "meanPixelErrorsPerQuadrant": float(np.mean(errors)), "worstPixelErrorsPerQuadrant": max(errors),
        "meanErrorFraction": float(np.mean(errors) / 64), "exactQuadrants": errors.count(0),
        "pixelErrorsBySourceGlyph": [errors[at:at + 4] for at in range(0, 256, 4)],
        "foregroundBackgroundPolicy": "Keep original pair, exchanging foreground/background only when swap byte is one"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=HERE / "generated-symmetric")
    parser.add_argument("--output", type=Path, default=HERE / "build")
    args = parser.parse_args()
    data, output = args.data.resolve(), args.output.resolve()
    input_hashes, emitted = {}, {}

    def read(relative):
        raw = (data / relative).read_bytes()
        input_hashes[relative] = sha(raw)
        return raw

    def write(relative, raw):
        path = output / relative
        if not path.exists() or path.read_bytes() != raw:
            path.write_bytes(raw)
        emitted[relative] = {"bytes": len(raw), "sha256": sha(raw)}

    manifest = json.loads(read("manifest.json"))
    font = read("font.bin")
    assert len(font) == 512 and sha(font) == FONT_SHA == manifest["fontSha256"]
    assert manifest["frameCount"] == FRAMES and manifest["glyphs"] == 64
    palette_raw = read("palette.json")
    palette = json.loads(palette_raw)
    assert [item["c64Index"] for item in palette["backgroundSlots"]] == list(C64)
    levels = [item["rgb"][0] for item in palette["backgroundSlots"]]
    assert levels == [0, 120, 174, 255]
    glyph_ones = np.unpackbits(np.frombuffer(font, dtype=np.uint8).reshape(64, 8), axis=1).sum(1)
    assert glyph_ones[0] == 0
    datasets, frequency = {}, Counter()
    for name in OBJECTS:
        item = next(value for value in manifest["objects"] if value["object"] == name)
        raw_screen, raw_color = read(f"{name}/screen.frames"), read(f"{name}/color.frames")
        assert len(raw_screen) == len(raw_color) == FRAMES * 1000
        assert sha(raw_screen) == item["hashes"]["screen.frames"]
        assert sha(raw_color) == item["hashes"]["color.frames"]
        screen = np.frombuffer(raw_screen, dtype=np.uint8).reshape(FRAMES, 1000).copy()
        color = np.frombuffer(raw_color, dtype=np.uint8).reshape(FRAMES, 1000).copy()
        assert np.isin(color, C64).all()
        source_pixels = render(screen, color, font, levels)
        assert rgba_hashes(source_pixels) == item["expectedDecodedRGBAHashes"]
        color[(screen & 63) == 0] = 0
        assert np.array_equal(source_pixels, render(screen, color, font, levels))
        spans = []
        for frame in range(FRAMES):
            for row in range(ROWS):
                start, stop = row_span(screen[frame, row * 40:(row + 1) * 40],
                                       color[frame, row * 40:(row + 1) * 40], glyph_ones)
                spans.append((start, stop))
        frequency.update((int(code), int(ink)) for code, ink in zip(screen.reshape(-1), color.reshape(-1)) if code & 63)
        datasets[name] = (screen, color, source_pixels, spans)
    assert len(frequency) >= DICTIONARY_SIZE
    pairs = sorted(frequency, key=lambda pair: (-frequency[pair], pair))[:DICTIONARY_SIZE]
    dictionary = {pair: token for token, pair in enumerate(pairs)}
    dictionary_screen = bytes(pair[0] for pair in pairs)
    dictionary_color = bytes(pair[1] for pair in pairs)
    output.mkdir(parents=True, exist_ok=True)
    write("font.bin", font)
    write("palette.json", palette_raw)
    write("dict-screen.bin", dictionary_screen)
    write("dict-color.bin", dictionary_color)
    objects, all_stats = [], Counter()
    for object_id, name in enumerate(OBJECTS):
        screen, color, source_pixels, spans = datasets[name]
        packed, offsets = bytearray(), []
        for frame in range(FRAMES):
            offsets.append(len(packed))
            for row in range(ROWS):
                first, stop = spans[frame * ROWS + row]
                begin, end = row * COLUMNS + first, row * COLUMNS + stop
                tokens = encode_row(screen[frame, begin:end], color[frame, begin:end], dictionary)
                assert len(tokens) < 256
                packed.extend((first, len(tokens)))
                packed.extend(tokens)
        assert len(packed) <= 65536 and max(offsets) < 65536
        rows_file, offsets_file = f"{name}.rows", f"{name}.offsets16"
        screen_file, color_file = f"{name}.screen.frames", f"{name}.color.frames"
        write(rows_file, bytes(packed))
        write(offsets_file, np.asarray(offsets, dtype="<u2").tobytes())
        write(screen_file, screen.tobytes())
        write(color_file, color.tobytes())
        decoded_screen, decoded_color, stats = decode_movie(bytes(packed), offsets, dictionary_screen, dictionary_color)
        assert np.array_equal(screen, decoded_screen) and np.array_equal(color, decoded_color)
        assert np.array_equal(source_pixels, render(decoded_screen, decoded_color, font, levels))
        all_stats.update(stats)
        objects.append({"id": object_id, "name": name, "frameCount": FRAMES,
                        "rowsFile": rows_file, "offsetsFile": offsets_file,
                        "screenFile": screen_file, "colorFile": color_file,
                        "rowsBytes": len(packed), "frameOffsets": offsets,
                        "rowRecordsPerFrame": ROWS, "tokenCounts": stats,
                        "meanRowDataBytesPerFrame": len(packed) / FRAMES,
                        "decodedPixelsEqualFrozenSource": True,
                        "screenBytesExact": True, "colorBytesExactAfterBlankForegroundNormalization": True})
    mirrors = {}
    for axis in ("h", "v", "hv"):
        mirror = {}
        mapping, swap = read(f"{axis}-map.bin"), read(f"{axis}-swap.bin")
        assert len(mapping) == len(swap) == 64 and max(mapping) < 64 and max(swap) < 2
        original = np.unpackbits(np.frombuffer(font, dtype=np.uint8).reshape(64, 8), axis=1).reshape(64, 8, 8)
        target = original[:, :, ::-1] if axis == "h" else original[:, ::-1, :] if axis == "v" else original[:, ::-1, ::-1]
        reconstructed = original[np.frombuffer(mapping, dtype=np.uint8)] ^ np.frombuffer(swap, dtype=np.uint8)[:, None, None]
        assert np.array_equal(target, reconstructed)
        for kind, raw in (("map", mapping), ("swap", swap)):
            filename = f"{axis}-{kind}.bin"
            write(filename, raw)
            mirror[f"{kind}File"] = filename
        mirrors[axis] = mirror
    zoom_map, zoom_swap, zoom = zoom_tables(font)
    write("zoom-map.bin", zoom_map)
    write("zoom-swap.bin", zoom_swap)
    zoom.update(mapFile="zoom-map.bin", swapFile="zoom-swap.bin", index="sourceGlyph * 4 + quadrant")
    wave = bytes(math.floor(4.5 + 4.5 * math.sin(2 * math.pi * (row / 24 + phase / 48)) + .5)
                 for row in range(ROWS) for phase in range(48))
    assert len(wave) == 1200 and min(wave) == 0 and max(wave) == 9
    write("wave-ages.bin", wave)
    assert all(sha((data / name).read_bytes()) == digest for name, digest in input_hashes.items())
    result = {"schemaVersion": 1, "format": "ecm-row-span-tokens-v1", "passed": True,
              "fontFile": "font.bin", "fontSha256": FONT_SHA, "fontBytes": 512,
              "paletteFile": "palette.json", "paletteC64": list(C64), "paletteGrayLevels": levels,
              "objects": objects, "frameCount": FRAMES, "rowsPerFrame": ROWS, "columns": COLUMNS,
              "dictionary": {"entries": 220, "screenFile": "dict-screen.bin", "colorFile": "dict-color.bin",
                             "observedNonblankPairs": len(frequency), "selection": "Occurrence count descending, then screen/color ascending",
                             "glyphZeroExcluded": True},
              "rowFormat": {"header": ["startColumn", "encodedByteLength"], "emptyRow": [0, 0],
                            "span": "Smallest horizontal interval containing every nonblack decoded cell",
                            "offsets": "49 little-endian uint16 frame offsets relative to the object rows file",
                            "tokens": {"0..219": "One cell from screen/color dictionary",
                                       "220..251": "Empty glyph with BGslot=(token-220)//8, count=(token-220)%8+1, FG=0",
                                       "252..255": "One literal screen byte follows; foreground is paletteC64[token-252]"}},
              "mirrors": mirrors, "zoom": zoom,
              "wave": {"file": "wave-ages.bin", "rows": 25, "phases": 48, "index": "row*48+phase",
                       "minimumAge": 0, "maximumAge": 9,
                       "formula": "floor(4.5 + 4.5*sin(2*pi*(row/24 + phase/48)) + 0.5)"},
              "totalRowsBytes": sum(item["rowsBytes"] for item in objects),
              "allTokenCounts": dict(all_stats), "binaryFiles": emitted,
              "hashes": {name: record["sha256"] for name, record in emitted.items()},
              "inputHashes": input_hashes, "inputDatasetUnchanged": True,
              "fontRefitted": False, "losslessMoviePixels": True,
              "blankGlyphForegroundNormalizedToZero": True,
              "zoomIsApproximate": True, "nativePlaybackMeasured": False}
    (output / "assets.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": True, "output": str(output), "fontSha256": FONT_SHA,
                      "objects": [{"name": item["name"], "rowsBytes": item["rowsBytes"]} for item in objects],
                      "totalRowsBytes": result["totalRowsBytes"], "zoomMeanPixelErrors": zoom["meanPixelErrorsPerQuadrant"],
                      "zoomWorstPixelErrors": zoom["worstPixelErrorsPerQuadrant"],
                      "assetsSha256": sha((output / "assets.json").read_bytes())}), flush=True)


if __name__ == "__main__":
    main()
