#!/usr/bin/env python3
"""Compare a stable VICE PAL frame with a source AFLI reference by color index.

RGB-to-index correlation is permitted only after verifying the displayed RAM
payload against the original file with the player's explicit left24-pixel mask.
It accommodates VICE's different RGB palette
without changing image geometry or allowing per-pixel color substitutions.
"""
from collections import Counter
from pathlib import Path
import argparse
import hashlib
import json

from PIL import Image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('name', choices=('darth1', 'darth2', 'Gladjefull-p', 'pumpkin', 'face-afl', 'wh40k'))
parser.add_argument('screenshot', type=Path)
parser.add_argument('payload_dump', type=Path, nargs='+', help='raw16,192-byte active AFLI bank dump ($4000..$7F3F or $C000..$FF3F), without a load header')
parser.add_argument('--output', type=Path)
parser.add_argument('--source', type=Path, help='Read one exact AFLI path instead of its Downloads basename')
args = parser.parse_args()
folder = Path(__file__).resolve().parent
source_path = (args.source or Path('/Users/rogerjohansson/Downloads') / f'{args.name}.afl').resolve()
source = source_path.read_bytes()
assert len(source) == 16385 and source[:2] == b'\x00\x40'
expected_payload = bytearray(source[2:2+16192])
for bank in range(8):
    for tile_row in range(25):
        offset = bank*1024+tile_row*40
        expected_payload[offset:offset+3] = bytes(3)
for tile_row in range(25):
    offset = 8192+tile_row*320
    expected_payload[offset:offset+24] = bytes(24)
memory_reports = []
for path in args.payload_dump:
    dump = path.read_bytes()
    assert len(dump) == 16192, f'Unexpected active RAM payload length {len(dump)}'
    assert dump == expected_payload, f'Displayed AFLI RAM differs from the explicitly masked source: {path}'
    memory_reports.append({'path': str(path.resolve()), 'bytes_matched': len(dump),
                           'sha256': hashlib.sha256(dump).hexdigest()})
reference = (folder / f'{args.name}-expected-color-indices.bin').read_bytes()
assert len(reference) == 64000
expected = bytes(reference[y*320+x] for y in range(200) for x in range(24, 320))
image = Image.open(args.screenshot).convert('RGB')
assert image.size == (384, 272), f'Expected normal PAL384×272 screenshot, got {image.size}'

candidates = []
for origin_y in range(30, 39):
    for origin_x in range(30, 35):
        actual = list(image.crop((origin_x+24, origin_y, origin_x+320, origin_y+200)).getdata())
        joint = Counter(zip(actual, expected))
        mapping = {}
        for rgb in set(actual):
            mapping[rgb] = max(((count, index) for (color, index), count in joint.items() if color == rgb))[1]
        mismatches = sum(mapping[rgb] != index for rgb, index in zip(actual, expected))
        one_to_one = len(set(mapping.values())) == len(mapping)
        candidates.append({'origin': [origin_x, origin_y], 'mismatches': mismatches,
                           'one_to_one': one_to_one, 'mapping': mapping})
best = min(candidates, key=lambda item: item['mismatches'])
zeros = [item for item in candidates if item['mismatches'] == 0 and item['one_to_one']]
report = {
    'name': args.name, 'source': str(source_path), 'screenshot': str(args.screenshot.resolve()),
    'screenshot_sha256': hashlib.sha256(args.screenshot.read_bytes()).hexdigest(),
    'source_sha256': hashlib.sha256(source).hexdigest(),
    'payload_dumps': memory_reports, 'source_active_payload_bytes_matched': 16192,
    'display_mask': {'left_hires_pixels': 24,
                     'screen_bytes_zeroed': 'first3tilecolumns of each25tile-rows in all8screenpages',
                     'bitmap_bytes_zeroed': 'first24bytes of each25character rows',
                     'source_file_modified': False, 'unused_bitmap_tail_compared': False},
    'comparison': 'one global one-to-one VICE RGB-to-C64-index mapping after exact RAM payload match',
    'screenshot_dimensions': list(image.size), 'source_crop': [24, 0, 320, 200],
    'compared_pixels': len(expected), 'minimum_mismatches': best['mismatches'],
    'best_origin': best['origin'],
    'zero_mismatch_origins': [item['origin'] for item in zeros],
    'expected_reference_sha256': hashlib.sha256(reference).hexdigest(),
    'vice_rgb_to_c64_index': {','.join(map(str, rgb)): index for rgb, index in sorted(best['mapping'].items())}
}
if len(zeros) == 1:
    report['active_frame_origin'] = zeros[0]['origin']
    report['pass'] = True
else:
    report['pass'] = False
output = args.output or folder / f'{args.name}-vice-comparison.json'
output.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
assert report['pass'], 'VICE frame does not uniquely match the visible expected color indices'
