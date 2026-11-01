#!/usr/bin/env python3
"""Label actual VICE crops separately from the decoded expected references."""
from pathlib import Path
import json
import argparse
from PIL import Image, ImageDraw, ImageFont

folder = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('names', nargs='*')
parser.add_argument('--isolated', action='store_true', help='Write one image without changing the shared contact sheet')
args = parser.parse_args()
names = args.names or ['darth2']
assert set(names) <= {'darth1', 'darth2', 'Gladjefull-p', 'pumpkin', 'face-afl', 'wh40k'}
assert not args.isolated or len(names) == 1, 'Isolated output requires one source basename'
try:
    font = ImageFont.truetype('/System/Library/Fonts/Menlo.ttc', 15)
except OSError:
    font = ImageFont.load_default()
panels = {}
for name in names:
    report = json.loads((folder / f'{name}-vice-comparison.json').read_text())
    image = Image.open(report['screenshot']).convert('RGB')
    x, y = report.get('active_frame_origin', report['best_origin'])
    actual = image.crop((x+24, y, x+320, y+200))
    actual.save(folder / f'{name}-actual-vice-visible.png')
    panel = Image.new('RGB', (592, 472), '#141721')
    draw = ImageDraw.Draw(panel)
    draw.text((8, 4), f'{name}.afl — ACTUAL VICE CAPTURE', font=font, fill='white')
    draw.text((8, 26), 'Visible x24..319; left24 hardware bug area excluded', font=font, fill='#B8C0D6')
    status = 'PASS: 59,200 pixels match' if report['pass'] else f'FAIL: {report["minimum_mismatches"]} visible pixels differ'
    draw.text((8, 48), status, font=font, fill='#B8E4CE' if report['pass'] else '#FF8F9A')
    panel.paste(actual.resize((592, 400), Image.Resampling.NEAREST), (0, 72))
    panel.save(folder / f'{name}-actual-vice-labeled.png')
    panels[name] = panel
if args.isolated:
    print(folder / f'{names[0]}-actual-vice-labeled.png')
    raise SystemExit(0)
sheet = Image.new('RGB', (len(names)*600-8, 472), '#141721')
for column, name in enumerate(names):
    sheet.paste(panels[name], (column*600, 0))
path = folder / ('darth-actual-vice-captures.png' if names == ['darth1', 'darth2'] else 'afli-actual-vice-captures.png')
sheet.save(path)
print(path)
