#!/usr/bin/env python3
"""Package the eight observed Rimrunner raster captures into reusable local assets.

Inputs are directories raster-00 through raster-07 produced by rimrunner-assets.py.
The scene preview follows the observed raster palette/charset regions. It is a
static reconstruction of this viewport, not an extraction of every level map.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import zipfile

from PIL import Image, ImageDraw


def digest(data):
    return hashlib.sha256(data).hexdigest()


def package(decoded, output, source_receipt):
    decoded, output = decoded.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to replace an existing asset package: {output}")
    archive = output.with_suffix(".zip")
    if archive.exists():
        raise FileExistsError(f"Refusing to replace an existing archive: {archive}")
    phases = []
    for index in range(8):
        directory = decoded / f"raster-{index:02d}"
        manifest = json.loads((directory / "manifest.json").read_text())
        for name, expected in manifest["outputs"].items():
            if digest((directory / name).read_bytes()) != expected["sha256"]:
                raise ValueError(f"Decoded asset differs from its manifest: {directory / name}")
        phases.append((directory, manifest))

    output.mkdir(parents=True)
    (output / "sprites").mkdir()
    (output / "charsets").mkdir()
    (output / "states").mkdir()
    sprites, charsets = [], []
    sprite_ids, charset_ids = {}, {}
    for phase, (directory, manifest) in enumerate(phases):
        state_directory = output / "states" / directory.name
        state_directory.mkdir()
        for name in ("manifest.json", "screen.bin", "color.bin"):
            shutil.copyfile(directory / name, state_directory / name)
        data = (directory / "charset.bin").read_bytes()
        signature = digest(data)
        if signature not in charset_ids:
            identifier = len(charsets)
            charset_ids[signature] = identifier
            stem = f"charset-{identifier:02d}"
            shutil.copyfile(directory / "charset.bin", output / "charsets" / (stem + ".bin"))
            shutil.copyfile(directory / "charset-multicolor.png", output / "charsets" / (stem + "-multicolor.png"))
            shutil.copyfile(directory / "charset-hires.png", output / "charsets" / (stem + "-hires.png"))
            charsets.append({"id": identifier, "file": f"charsets/{stem}.bin", "bytes": len(data),
                             "sha256": signature, "observations": []})
        charsets[charset_ids[signature]]["observations"].append(
            {"phase": phase, "address": manifest["addresses"]["charset"]})
        for sprite in manifest["sprites"]:
            with Image.open(directory / sprite["png_file"]) as image:
                if not sprite["enabled"] or image.getchannel("A").getbbox() is None:
                    continue
            data = (directory / sprite["raw_file"]).read_bytes()
            signature = (digest(data[:63]), sprite["multicolor"], tuple(sprite["palette_indices"]))
            if signature not in sprite_ids:
                identifier = len(sprites)
                sprite_ids[signature] = identifier
                stem = f"sprite-{identifier:03d}"
                shutil.copyfile(directory / sprite["raw_file"], output / "sprites" / (stem + ".bin"))
                shutil.copyfile(directory / sprite["png_file"], output / "sprites" / (stem + ".png"))
                sprites.append({"id": identifier, "raw_file": f"sprites/{stem}.bin",
                                "png_file": f"sprites/{stem}.png", "raw_bytes": 64,
                                "picture_bytes": 63, "sha256": digest(data),
                                "multicolor": sprite["multicolor"],
                                "palette_indices": sprite["palette_indices"], "observations": []})
            sprites[sprite_ids[signature]]["observations"].append(
                {"phase": phase, "slot": sprite["number"], "address": sprite["address"],
                 "x": sprite["x"], "y": sprite["y"],
                 "x_expanded": sprite["x_expanded"], "y_expanded": sprite["y_expanded"]})

    columns, cell_width, cell_height = 8, 40, 38
    atlas = Image.new("RGBA", (columns * cell_width, math.ceil(len(sprites) / columns) * cell_height))
    labels = ImageDraw.Draw(atlas)
    for item in sprites:
        x, y = item["id"] % columns * cell_width, item["id"] // columns * cell_height
        with Image.open(output / item["png_file"]) as image:
            atlas.alpha_composite(image.convert("RGBA"), (x + 8, y))
        labels.text((x + 7, y + 23), f'{item["id"]:03d}', fill=(190, 190, 190, 255))
    atlas.save(output / "sprites-atlas.png")

    # PAL first display line is 51. Region changes are prepared by the original
    # raster handlers at 87, 178, 198, and 216. Preserve the logical cell grid;
    # border clipping, fine scroll, sprite overlays, and per-cycle effects are absent.
    regions = [(7, 0, 36), (0, 36, 127), (4, 127, 147), (5, 147, 165), (6, 165, 200)]
    background = Image.new("RGB", (320, 200))
    for phase, first, end in regions:
        with Image.open(phases[phase][0] / "background-single-state.png") as image:
            background.paste(image.crop((0, first, 320, end)).convert("RGB"), (0, first))
    background.save(output / "background-observed.png")
    background.crop((0, 40, 320, 200)).save(output / "landscape-observed.png")

    # The green runner is assembled from the observed multiplexed sprite slots.
    # This is one observed scene and may include animation transitions between slots.
    # A dismounted rider and the dinosaur can appear as separate green actors.
    pieces, seen = [], set()
    for phase in (3, 4, 5, 6):
        directory, manifest = phases[phase]
        for sprite in manifest["sprites"]:
            if not sprite["enabled"] or not sprite["multicolor"] or sprite["palette_indices"][2] != 5:
                continue
            with Image.open(directory / sprite["png_file"]) as image:
                rgba = image.convert("RGBA")
                if rgba.getchannel("A").getbbox() is None:
                    continue
                key = (sprite["x"], sprite["y"], digest(rgba.tobytes()))
                if key not in seen:
                    seen.add(key)
                    pieces.append((sprite, rgba.copy(), phase))
    if pieces:
        left = min(sprite["x"] for sprite, _, _ in pieces)
        top = min(sprite["y"] for sprite, _, _ in pieces)
        right = max(sprite["x"] + 24 for sprite, _, _ in pieces)
        bottom = max(sprite["y"] + 21 for sprite, _, _ in pieces)
        runner = Image.new("RGBA", (right - left, bottom - top))
        for sprite, image, phase in sorted(pieces, key=lambda piece: -piece[0]["number"]):
            runner.alpha_composite(image, (sprite["x"] - left, sprite["y"] - top))
        runner.save(output / "runner-observed.png")

    receipt = json.loads(source_receipt.read_text())
    manifest = {"format": "Rimrunner observed graphics package v1", "source": receipt,
                "capture_count": len(phases), "sprites": sprites, "charsets": charsets,
                "background_regions": [{"phase": phase, "first_row": first, "end_row": end}
                                       for phase, first, end in regions],
                "limitations": ["One captured viewport and observed sprite poses, not every level or animation.",
                                "Background preview follows raster regions; it is not a complete cycle-exact frame.",
                                "PNG uses Colodore RGB; native C64 indices and raw bytes are preserved.",
                                "Extracted original artwork carries no new reuse or redistribution license."]}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "USAGE.txt").write_text(
        "Rimrunner C64: original graphics extracted from a running UCG release.\n\n"
        "PNG sprite files have transparency. BIN files are raw C64 bytes without a load address.\n"
        "Each sprite BIN has 64 bytes; only the first 63 encode its 24x21 source pixels.\n"
        "Multicolor sprite palette order: transparent, shared color 1, local color, shared color 2.\n"
        "Each charset BIN contains 256 glyphs of 8 bytes. Glyph-sheet colors are generic previews.\n"
        "Per-state screen and color files preserve the actual cell assignments.\n"
        "The manifest records C64 color indices, addresses, observed positions and source hashes.\n\n"
        "background-observed.png is a static viewport reconstruction without sprites.\n"
        "landscape-observed.png contains the observed scenery below the status panel.\n"
        "runner-observed.png combines observed green sprite parts; rider and dinosaur may be separated.\n"
        "This package does not contain every animation or a complete scrolling level map.\n"
        "Extraction does not grant permission to redistribute the original artwork.\n")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(output))
    print(json.dumps({"output": str(output), "archive": str(archive),
                      "observed_sprite_variants": len(sprites), "observed_charsets": len(charsets)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoded", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-receipt", type=Path, required=True)
    arguments = parser.parse_args()
    package(arguments.decoded, arguments.output, arguments.source_receipt)
