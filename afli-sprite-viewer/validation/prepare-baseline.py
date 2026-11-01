#!/usr/bin/env python3
"""Decode the unmodified source AFLI for the independent sprite-overlay oracle."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
source = ROOT / 'images/face-afl.afl'
data = source.read_bytes()
assert len(data) == 16385 and data[:2] == bytes([0, 0x40])
html = (ROOT / 'index.html').read_text()
declaration = html.split('const C64_PALETTE = [', 1)[1].split('];', 1)[0]
colors = re.findall(r"index:\s*(\d+),\s*name:\s*'([^']+)',\s*hex:\s*'([^']+)',\s*rgb:\s*\[(\d+),\s*(\d+),\s*(\d+)\]", declaration)
palette = {int(index): {'name': name, 'hex': color, 'rgb': [int(r), int(g), int(b)]}
           for index, name, color, r, g, b in colors}
assert sorted(palette) == list(range(16))
indices = bytearray(320 * 200)
for y in range(200):
    for column in range(40):
        tile = (y >> 3) * 40 + column
        screen = data[2 + (y & 7) * 1024 + tile]
        bitmap = data[0x2002 + tile * 8 + (y & 7)]
        for bit in range(8):
            indices[y * 320 + column * 8 + bit] = screen >> 4 if bitmap & (0x80 >> bit) else screen & 15
rgb = bytes(channel for color in indices for channel in palette[color]['rgb'])
image = Image.frombytes('RGB', (320, 200), rgb)
index_path = OUT / 'face-afl-baseline-color-indices.bin'
png_path = OUT / 'face-afl-baseline.png'
index_path.write_bytes(indices)
image.save(png_path)
try:
    font = ImageFont.truetype('/System/Library/Fonts/Menlo.ttc', 16)
except OSError:
    font = ImageFont.load_default()
labeled = Image.new('RGB', (640, 448), '#141721')
draw = ImageDraw.Draw(labeled)
draw.text((8, 4), 'face-afl.afl — ORIGINAL SOURCE BASELINE', font=font, fill='white')
draw.text((8, 26), 'Expected decode; no sprites; full 320×200', font=font, fill='#B8C0D6')
labeled.paste(image.resize((640, 400), Image.Resampling.NEAREST), (0, 48))
labeled.save(OUT / 'face-afl-baseline-labeled.png')
sha = lambda value: hashlib.sha256(value).hexdigest()
metadata = {
    'kind': 'unmodified original source decode; not an emulator capture or a sprite composite',
    'source': str(source), 'source_bytes': len(data), 'source_sha256': sha(data),
    'source_load_address': '$4000', 'dimensions': [320, 200],
    'palette_source': str(ROOT / 'index.html'), 'palette': palette,
    'palette_declaration_sha256': sha(declaration.encode()),
    'color_indices': str(index_path), 'color_indices_sha256': sha(indices),
    'baseline_png': str(png_path), 'baseline_png_sha256': sha(png_path.read_bytes()),
    'color_index_histogram': dict(sorted(Counter(indices).items())),
    'source_mask_applied': False, 'sprite_overlay_applied': False,
    'agreed_valid_source_rect': [112, 0, 320, 200],
    'agreed_sprite_field_rect': [112, 0, 304, 200]
}
(OUT / 'baseline-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
print(json.dumps({'baseline_png': str(png_path), 'indices': str(index_path),
                  'source_sha256': metadata['source_sha256'],
                  'color_indices_sha256': metadata['color_indices_sha256']}, indent=2))
