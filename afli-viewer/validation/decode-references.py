#!/usr/bin/env python3
"""Decode user AFLI files to expected reference assets; these are not emulator captures."""
from collections import Counter
from pathlib import Path
import hashlib
import json
import re
import argparse

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
DOWNLOADS = Path('/Users/rogerjohansson/Downloads')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('names', nargs='*')
parser.add_argument('--isolated', action='store_true', help='Write one image without changing shared metadata or contact sheets')
parser.add_argument('--source', type=Path, help='Read one exact AFLI path instead of its Downloads basename')
args = parser.parse_args()
names = args.names or ['darth2']
assert set(names) <= {'darth1', 'darth2', 'Gladjefull-p', 'pumpkin', 'face-afl', 'wh40k'}, 'Unknown source basename'
assert not args.isolated or len(names) == 1, 'Isolated output requires one source basename'
assert not args.source or len(names) == 1, 'A source override requires one source basename'
html = (ROOT / 'index.html').read_text()
palette_source = html.split('const C64_PALETTE = [', 1)[1].split('];', 1)[0]
entries = re.findall(r"index:\s*(\d+),\s*name:\s*'([^']+)',\s*hex:\s*'([^']+)',\s*rgb:\s*\[(\d+),\s*(\d+),\s*(\d+)\]", palette_source)
assert len(entries) == 16
palette = {int(index): {'name': name, 'hex': color, 'rgb': [int(r), int(g), int(b)]}
           for index, name, color, r, g, b in entries}
assert sorted(palette) == list(range(16))
sha256 = lambda data: hashlib.sha256(data).hexdigest()
try:
    font = ImageFont.truetype('/System/Library/Fonts/Menlo.ttc', 16)
except OSError:
    font = ImageFont.load_default()

receipt = {'kind': 'expected reference decoded from source AFLI; not an emulator capture',
           'palette_source': str(ROOT / 'index.html'),
           'palette_declaration_sha256': sha256(palette_source.encode()),
           'palette': palette, 'images': []}
if not args.isolated and (OUT / 'reference-metadata.json').exists():
    previous = json.loads((OUT / 'reference-metadata.json').read_text())
    assert previous['palette_declaration_sha256'] == receipt['palette_declaration_sha256'], 'Regenerate all references after a palette change'
    receipt['images'] = [entry for entry in previous['images'] if entry['name'] not in names]
panels = {}
for name in names:
    source = (args.source or DOWNLOADS / f'{name}.afl').resolve()
    data = source.read_bytes()
    assert len(data) == 16385, (source, len(data))
    assert data[:2] == b'\x00\x40', (source, data[:2].hex())
    indices = bytearray(320 * 200)
    used_screens, used_bitmap = set(), set()
    for y in range(200):
        row = y & 7
        for column in range(40):
            tile = (y >> 3) * 40 + column
            screen_offset = 2 + row * 1024 + tile
            bitmap_offset = 0x2002 + tile * 8 + row
            screen = data[screen_offset]
            bits = data[bitmap_offset]
            used_screens.add(screen_offset)
            used_bitmap.add(bitmap_offset)
            for bit in range(8):
                color = screen >> 4 if bits & (0x80 >> bit) else screen & 15
                indices[y * 320 + column * 8 + bit] = color
    assert len(used_screens) == len(used_bitmap) == 8000
    rgb = bytes(channel for color in indices for channel in palette[color]['rgb'])
    image = Image.frombytes('RGB', (320, 200), rgb)
    index_path = OUT / f'{name}-expected-color-indices.bin'
    png_path = OUT / f'{name}-expected-afli.png'
    label_path = OUT / f'{name}-expected-labeled.png'
    index_path.write_bytes(indices)
    image.save(png_path)
    panel = Image.new('RGB', (640, 448), '#141721')
    drawing = ImageDraw.Draw(panel)
    drawing.text((10, 5), f'{name}.afl — EXPECTED REFERENCE', fill='#FFFFFF', font=font)
    drawing.text((10, 26), 'Full 320×200 decode; not an emulator capture', fill='#B8C0D6', font=font)
    panel.paste(image.resize((640, 400), Image.Resampling.NEAREST), (0, 48))
    panel.save(label_path)
    panels[name] = panel
    gaps = bytes(data[2 + bank * 1024 + offset] for bank in range(8) for offset in range(1000, 1024))
    bitmap_tail = data[0x2002 + 8000:]
    assert len(gaps) == 192 and len(bitmap_tail) == 191
    receipt['images'].append({
        'name': name, 'source': str(source), 'source_bytes': len(data),
        'load_address': '$4000', 'source_sha256': sha256(data),
        'decoded_dimensions': [320, 200], 'decoded_index_sha256': sha256(indices),
        'decoded_rgb_sha256': sha256(rgb), 'expected_png_sha256': sha256(png_path.read_bytes()),
        'screen_active_bytes': len(used_screens), 'bitmap_active_bytes': len(used_bitmap),
        'screen_gap_bytes': len(gaps), 'screen_gap_nonzero_bytes': sum(value != 0 for value in gaps),
        'bitmap_tail_bytes': len(bitmap_tail), 'bitmap_tail_nonzero_bytes': sum(value != 0 for value in bitmap_tail),
        'palette_index_histogram': dict(sorted(Counter(indices).items())),
        'left_16_hires_pixel_indices': sorted({indices[y*320+x] for y in range(200) for x in range(16)}),
        'reference_png': str(png_path), 'labeled_reference_png': str(label_path),
        'expected_color_indices': str(index_path)
    })
if args.isolated:
    metadata = OUT / f'{names[0]}-reference-metadata.json'
    metadata.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'references': [item['reference_png'] for item in receipt['images']],
                      'metadata': str(metadata),
                      'labeled_reference': str(OUT / f'{names[0]}-expected-labeled.png')}, indent=2))
    raise SystemExit(0)
if all(name in panels for name in ('darth1', 'darth2')):
    sheet = Image.new('RGB', (1288, 448), '#141721')
    for column, name in enumerate(('darth1', 'darth2')):
        sheet.paste(panels[name], (column * 648, 0))
    sheet.save(OUT / 'darth-expected-references.png')
sheet = Image.new('RGB', (len(receipt['images']) * 648 - 8, 448), '#141721')
for column, entry in enumerate(receipt['images']):
    sheet.paste(Image.open(entry['labeled_reference_png']).convert('RGB'), (column * 648, 0))
sheet.save(OUT / 'afli-expected-references.png')
(OUT / 'reference-metadata.json').write_text(json.dumps(receipt, indent=2) + '\n')
(OUT / 'README.md').write_text('''# Expected AFLI references

These images are source-file decodes, **not emulator captures**. The native
320×200 PNGs and 64,000-byte color-index buffers include every source column.
The labeled PNGs use nearest-neighbor 2× display scaling for visual QA.

The script reads the current `C64_PALETTE` declaration in `index.html`.
For scanline y and character column c: tile=(y>>3)*40+c, row=y&7;
screen=file[2+row*1024+tile], bitmap=file[0x2002+tile*8+row].
Bitmap bit 7 is the leftmost pixel; bit 1 selects the screen byte's high nibble,
bit 0 its low nibble. No palette snapping, temporal mixing, or source cropping
is applied. Source hashes, palette values and decoded hashes are recorded in
`reference-metadata.json`.

Regenerate with `rtk proxy python3 afli-viewer/validation/decode-references.py`.
Pass exact source basenames to add or refresh individual references.
''')
print(json.dumps({'references': [item['reference_png'] for item in receipt['images']],
                  'metadata': str(OUT / 'reference-metadata.json'),
                  'contact_sheet': str(OUT / 'afli-expected-references.png')}, indent=2))
