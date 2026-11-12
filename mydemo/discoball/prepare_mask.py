#!/usr/bin/env python3
"""Scale the supplied sphere to the model and export an ordered-dithered C64 mask."""

import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from model import HEXAGON_RADIUS

HERE = Path(__file__).resolve().parent


def main():
    source = HERE / "assets" / "ball-source.png"
    image = Image.open(source).convert("RGB")
    bounds = image.getbbox()
    if bounds is None:
        raise ValueError("The source image is entirely black")
    width, height = bounds[2]-bounds[0], bounds[3]-bounds[1]
    side = max(width, height)
    crop = Image.new("RGB", (side, side))
    crop.paste(image.crop(bounds), ((side-width)//2, (side-height)//2))

    # Truncating an icosahedron edge at one third gives this circumradius.
    # Model coordinates display at 2x in both axes; choose an even diameter.
    radius = HEXAGON_RADIUS*math.sqrt(5+4/math.sqrt(5))/3
    diameter = 2*math.ceil(2*radius)
    luminance = np.asarray(crop.convert("L").resize((diameter, diameter),
                           Image.Resampling.LANCZOS), dtype=np.float64)
    coverage = luminance/max(float(luminance.max()), 1)
    bayer = np.zeros((1, 1), dtype=np.int32)
    for _ in range(3):
        bayer = np.block([[4*bayer, 4*bayer+2], [4*bayer+3, 4*bayer+1]])
    threshold = np.tile((bayer+0.5)/64, (math.ceil(diameter/8),)*2)[:diameter, :diameter]
    selected = coverage > threshold
    selected &= ((np.arange(diameter)[:, None]+0.5-diameter/2)**2
                 +(np.arange(diameter)[None, :]+0.5-diameter/2)**2) <= (diameter/2)**2
    pixels = np.zeros((200, 320), dtype=bool)
    left, top = 160-diameter//2, 100-diameter//2
    pixels[top:top+diameter, left:left+diameter] = selected
    # Keep every existing dither bit. Add only a symmetric one-pixel outline
    # just outside the fitted sphere, in the same color as its inner pixels.
    outline = Image.new("1", (320, 200))
    ImageDraw.Draw(outline).ellipse((left-1, top-1, left+diameter, top+diameter), outline=1, width=1)
    pixels |= np.asarray(outline, dtype=bool)

    palette_file = HERE.parents[1] / "palettes" / "colodore.vpl"
    palette = [tuple(int(v, 16) for v in line.split()[:3])
               for line in palette_file.read_text().splitlines()
               if line.strip() and not line.startswith("#")]
    rgb = np.asarray(palette, dtype=np.uint8)[np.where(pixels, 0, 4)]
    result = Image.fromarray(rgb)
    result.save(HERE / "assets" / "ball-hexagon.png")
    # Art Studio stores eight vertical bitmap bytes per 8x8 screen cell.
    packed = np.packbits(pixels, axis=1).reshape(25, 8, 40).transpose(0, 2, 1).tobytes()
    artwork = b"\x00\x20"+packed+bytes([0x04])*1000+bytes(7)
    (HERE / "assets" / "ball-hexagon.art").write_bytes(artwork)
    report = {"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "source_bounds": bounds, "canvas": [320, 200], "diameter": diameter,
              "center": [160, 100], "dither": "8x8 ordered Bayer",
              "color_indices": [4, 0], "background_color": 4, "sphere_color": 0,
              "outline_color": 0, "outline_width": 1, "outline_diameter": diameter+2,
              "background_pixels": int((~pixels).sum()), "inner_pixels": int(pixels.sum())}
    (HERE / "assets" / "ball-hexagon.json").write_text(json.dumps(report, indent=2)+"\n")
    (HERE / "build").mkdir(exist_ok=True)
    result.resize((960, 600), Image.Resampling.NEAREST).save(HERE / "build" / "ball-hexagon-preview.png")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
