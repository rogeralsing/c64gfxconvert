#!/usr/bin/env python3
"""Check the predeclared208×200 AFLI/sprite composite, RAM and advancing frames."""
from pathlib import Path
from collections import Counter
import argparse
import hashlib
import json
import re
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('run', type=Path)
parser.add_argument('receipt', type=Path)
parser.add_argument('--require-black-bottom', action='store_true', help='Also require raw PNG rows232..271 to be black across all384 columns')
args = parser.parse_args()
receipt = json.loads(args.receipt.read_text())
capture = json.loads((args.run / 'capture.json').read_text())
baseline = json.loads((OUT / 'baseline-metadata.json').read_text())
source = (ROOT / 'images/face-afl.afl').read_bytes()
sha = lambda data: hashlib.sha256(data).hexdigest()
assert sha(source) == baseline['source_sha256'] == capture['source_sha256']
assert len(source) == 16385 and source[:2] == bytes([0, 0x40])
original = (OUT / 'face-afl-baseline-color-indices.bin').read_bytes()
assert len(original) == 64000 and sha(original) == baseline['color_indices_sha256']
failures = []
def check(condition, message):
    if not condition:
        failures.append(message)

# Constants come from the contract agreed before the trial, not the capture.
X0, X1, HEIGHT, IMAGE_RASTER, FIRST_SPRITE_RASTER = 112, 320, 200, 48, 32
WIDTH, SCREEN_ORIGIN = X1-X0, (32, 32)
checker = bytes(value for row in range(21)
                for value in [0xf0 if (row//3)%2 == 0 else 0x0f]*3) + bytes(1)
sprites = receipt['sprites']
check(receipt['image_raster_origin'] == IMAGE_RASTER and receipt['image_height'] == HEIGHT, 'Receipt changed image timing/height')
check(receipt['display_mask'] == {'left_hires_pixels':112, 'visible_image_width':208}, 'Receipt changed valid image area')
check(sprites['count'] == 8 and sprites['width'] == 24 and sprites['height'] == 21, 'Receipt changed sprite dimensions/count')
check(sprites['x_source'] == [112+24*i for i in range(8)] and sprites['x_vic'] == [136+24*i for i in range(8)], 'Receipt changed sprite positions')
check(sprites['color'] == 1 and sprites['front'] and not any(sprites[key] for key in ['multicolor','x_expand','y_expand']), 'Receipt changed sprite mode/color/priority')
check(sprites['initial_y'] == 31 and sprites['preamble_y'] == 52, 'Receipt changed initial Y phase')
check(sprites['checker_rows_hex'] == [checker[row*3:row*3+3].hex() for row in range(21)], 'Receipt changed checker pattern')
events = []
for first in range(55, 248, 21):
    for sprite in range(8):
        raster = first + 2*sprite
        if raster <= 247:
            events.append({'raster':raster,'sprite':sprite,'address':f'${0xd001+2*sprite:04x}','new_y':(first+18)%256})
check(sprites['y_update_events'] == events, 'Receipt changed predeclared Y reuse schedule')

# Source, left mask, pointer tails and checker are constructed independently.
expected_ram = bytearray(16384)
expected_ram[:len(source)-2] = source[2:]
for matrix in range(8):
    for tile_row in range(25):
        start = matrix*1024 + tile_row*40
        expected_ram[start:start+14] = bytes(14)
    expected_ram[matrix*1024+1016:matrix*1024+1024] = bytes([0xfd])*8
for tile_row in range(25):
    start = 8192 + tile_row*320
    expected_ram[start:start+112] = bytes(112)
expected_ram[0x3f40:0x3f80] = checker
bank_reports = []
for name, base in [('bank-a.bin',0x4000), ('bank-b.bin',0xc000)]:
    actual = (args.run / name).read_bytes()
    check(len(actual) == 16384, f'{name} length is not16KB')
    assert len(actual) == 16384
    expected = bytearray(expected_ram)
    compared_offsets = range(16384)
    unspecified_ranges = []
    if base == 0xc000:
        expected[0x3ffa:0x3ffc] = bytes([0x8b,0x20])
        irq = actual[0x3ffe:0x4000]
        check(irq in (bytes([0xc3,0x0e]), bytes([0xe5,0x0e])), 'Unexpected live IRQ vector')
        expected[0x3ffe:0x4000] = irq
        # The declared bootstrap copies only through$FFA3. The remaining RAM
        # tail is neither source graphics nor sprite storage. Validate the
        # installed NMI/IRQ vectors there, not unrelated power-on RAM values.
        compared_offsets = [*range(0x3fa4), 0x3ffa, 0x3ffb, 0x3ffe, 0x3fff]
        unspecified_ranges = ['$ffa4-$fff9', '$fffc-$fffd']
    diffs = [offset for offset in compared_offsets if actual[offset] != expected[offset]]
    check(not diffs, f'{name} differs from independently reconstructed RAM')
    bank_reports.append({'file':str((args.run/name).resolve()),'sha256':sha(actual),
                         'bytes_compared':len(compared_offsets),'mismatch_count':len(diffs),
                         'unspecified_non_graphics_tail':unspecified_ranges,
                         'first_mismatches':[{'address':f'${base+o:04x}','expected':expected[o],'actual':actual[o]} for o in diffs[:32]],
                         'valid_source_screen_bytes_preserved':5200,'valid_source_bitmap_bytes_preserved':5200,
                         'pointer_table_entries_checked':64,'checker_bytes_checked':64})

expected, opaque = bytearray(), bytearray()
for y in range(HEIGHT):
    row = (IMAGE_RASTER+y-FIRST_SPRITE_RASTER)%21
    for x in range(X0, X1):
        covered = x < 304 and (((x-X0)%24)//4 + row//3)%2 == 0
        opaque.append(int(covered))
        expected.append(1 if covered else original[y*320+x])
assert sum(opaque) == 19200 and len(expected)-sum(opaque) == 22400
check(capture['pal'] and capture['speed_percent'] == 100 and not capture['warp'] and capture['vsync'], 'Capture is not native PAL100%/warp-off/vsync')
program = Path(capture['program']).read_bytes()
check(sha(program) == capture['program_sha256'] == receipt['files'][0]['output_sha256'], 'Program changed after capture')
known = json.loads((ROOT/'afli-viewer/validation/vice-palette-reference.json').read_text())['mapping']
palette = {tuple(map(int, color.split(','))):index for color,index in known.items()}
samples = capture['samples']
check(len(samples) >= 3, 'Fewer than three captures')
observation = capture.get('register_observation')
expected_y = [31]*8
if observation:
    kernel_row = observation.get('kernel_row_label', observation.get('raster_row'))
    check(kernel_row == 100, 'Changed declared register observation phase')
    symbols = (Path(capture['program']).parent/'boot-rendered.sym').read_text()
    symbol = re.search(r'\.label row100=\$([0-9a-fA-F]+)', symbols)
    check(symbol is not None and observation['address'][1:].lower() == symbol[1].lower(), 'Observation PC differs from the row100 code symbol')
    expected_y = [52]*8
    for event in events:
        if event['raster'] < kernel_row:
            expected_y[event['sprite']] = event['new_y']
sample_reports, hashes, counters = [], [], []
for number, sample in enumerate(samples, 1):
    path = Path(sample['screenshot'])
    image = Image.open(path).convert('RGB')
    check(image.size == (384,272), f'Capture{number} changed dimensions')
    hashes.append(sha(path.read_bytes()))
    check(hashes[-1] == sample['sha256'], f'Capture{number} changed after receipt')
    counter = (args.run/f'frame-counter-{number}.bin').read_bytes()
    check(len(counter) == 1 and counter[0] == sample['frame_counter'], f'Counter{number} mismatch')
    counters.append(sample['frame_counter'])
    observed_raster = observed_cycle = None
    if observation:
        register_line = next((line for line in sample['registers'].splitlines() if line.startswith('.;')), '')
        fields = register_line.split()
        if len(fields) >= 10:
            observed_raster, observed_cycle = int(fields[8]), int(fields[9])
        check(len(fields) >= 10 and fields[0][2:].lower() == observation['address'][1:].lower()
              and 48 <= observed_raster <= 247, f'Capture{number} was not observed at the declared active-image code symbol')
    actual = [palette.get(image.getpixel((SCREEN_ORIGIN[0]+x, SCREEN_ORIGIN[1]+y)), -1)
              for y in range(HEIGHT) for x in range(X0,X1)]
    wrong = [pixel for pixel,(a,e) in enumerate(zip(actual,expected)) if a != e]
    wrong_opaque = sum(opaque[pixel] for pixel in wrong)
    row_errors = dict(Counter(pixel//WIDTH for pixel in wrong))
    check(not wrong, f'Capture{number} has{len(wrong)} pixel mismatches')
    bottom_wrong = [(x,y,image.getpixel((x,y))) for y in range(232,272) for x in range(384)
                    if image.getpixel((x,y)) != (0,0,0)]
    if args.require_black_bottom:
        check(not bottom_wrong, f'Capture{number} has{len(bottom_wrong)} nonblack bottom pixels')
    io = {}
    for line in sample['vic'].splitlines():
        match = re.match(r'>C:([0-9a-fA-F]{4})\s+(.*)',line)
        if match:
            values = match[2].split()[:16]
            if len(values)==16 and all(re.fullmatch('[0-9a-fA-F]{2}',value) for value in values):
                io.update({int(match[1],16)+offset:int(value,16) for offset,value in enumerate(values)})
    check(io.get(0xd015)==255 and io.get(0xd010)==224, f'Capture{number} sprite enable/X-MSB mismatch')
    check(all(io.get(address)==0 for address in [0xd017,0xd01b,0xd01c,0xd01d]), f'Capture{number} sprite mode/priority/expansion mismatch')
    check([io.get(0xd000+2*i,0)+256*((io.get(0xd010,0)>>i)&1) for i in range(8)] == [136+24*i for i in range(8)], f'Capture{number} sprite X mismatch')
    check([io.get(0xd001+2*i) for i in range(8)] == expected_y, f'Capture{number} Y schedule mismatch at observation phase')
    check(all(io.get(0xd027+i,-1)&15 == 1 for i in range(8)), f'Capture{number} sprite color mismatch')
    pointer_line = next((line for line in sample['vic'].splitlines() if line.startswith('Pointer:')), '')
    check(re.findall(r'\$([0-9a-fA-F]{2})',pointer_line)==['fd']*8, f'Capture{number} live sprite pointer mismatch')
    sample_reports.append({'screenshot':str(path),'sha256':hashes[-1],'frame_counter':sample['frame_counter'],
                           'observed_vic_raster':observed_raster,'observed_vic_cycle':observed_cycle,
                           'pixels_compared':len(expected),'opaque_checker_pixels':sum(opaque),
                           'preserved_source_pixels':len(expected)-sum(opaque),
                           'mismatches':len(wrong),'opaque_mismatches':wrong_opaque,
                           'source_mismatches':len(wrong)-wrong_opaque,'row_mismatches':row_errors,
                           'bottom_black_required':args.require_black_bottom,
                           'bottom_rect':[0,232,384,272],'bottom_pixels_checked':15360 if args.require_black_bottom else 0,
                           'bottom_nonblack_pixels':len(bottom_wrong),
                           'bottom_nonblack_by_row':dict(Counter(y for x,y,rgb in bottom_wrong)),
                           'first_bottom_nonblack':[{'x':x,'y':y,'rgb':list(rgb)} for x,y,rgb in bottom_wrong[:32]],
                           'first_mismatches':[{'x':X0+p%WIDTH,'y':p//WIDTH,'expected':expected[p],'actual':actual[p]} for p in wrong[:32]]})
advances = [(after-before)%256 for before,after in zip(counters,counters[1:])]
check(all(0<advance<128 for advance in advances), 'Frame counter did not advance unambiguously')
check(len(set(hashes))==1, 'Repeated raw capture hashes differ')
report = {'pass':not failures,'failures':failures,'source_sha256':sha(source),'program_sha256':sha(program),
          'contract':{'source_rect':[112,0,320,200],'image_origin':[32,32],
                      'image_raster_origin':48,'first_sprite_raster':32,'local_sprite_row':'(source_y+16)%21',
                      'sprite_field':[112,0,304,200],'color_index':1,'checker_block':[4,3]},
          'expected_index_sha256':sha(expected),'opaque_mask_sha256':sha(opaque),
          'bank_reports':bank_reports,'samples':sample_reports,'counter_advances':advances,
          'identical_raw_capture_hashes':len(set(hashes))==1,
          'register_observation':observation or {'phase':'idle after Y rearm'},
          'register_observation_interpretation':'kernel row100 code symbol; actual VIC raster/cycle recorded per sample' if observation else 'idle snapshot',
          'expected_y_at_observation':expected_y,
          'require_black_bottom':args.require_black_bottom,
          'evidence_limit':'Three advancing PAL captures plus RAM/register evidence; no claim of indefinite stability'}
report_path = OUT/f'{args.run.name}-comparison.json'
report_path.write_text(json.dumps(report,indent=2)+'\n')
(OUT/'expected-composite-color-indices.bin').write_bytes(expected)
(OUT/'expected-opaque-mask.bin').write_bytes(opaque)
base_palette = {int(index):color['rgb'] for index,color in baseline['palette'].items()}
rgb = bytes(channel for index in expected for channel in base_palette[index])
Image.frombytes('RGB',(WIDTH,HEIGHT),rgb).save(OUT/'face-afl-expected-sprite-composite.png')
actual_crop = Image.open(samples[0]['screenshot']).convert('RGB').crop((144,32,352,232))
actual_crop.save(OUT/'face-afl-actual-sprite-visible.png')
try:
    font = ImageFont.truetype('/System/Library/Fonts/Menlo.ttc',14)
except OSError:
    font = ImageFont.load_default()
label = Image.new('RGB',(416,472),'#141721');draw = ImageDraw.Draw(label)
draw.text((8,4),'face-afl.afl — ACTUAL VICE',font=font,fill='white')
draw.text((8,26),'Left 112 excluded; full 208×200; 8 sprites',font=font,fill='#B8C0D6')
draw.text((8,48),'PASS: 41,600 pixels × 3 frames' if report['pass'] else 'FAIL: see pixel/RAM report',font=font,fill='#B8E4CE' if report['pass'] else '#FF8F9A')
label.paste(actual_crop.resize((416,400),Image.Resampling.NEAREST),(0,72))
label.save(OUT/'face-afl-actual-sprite-labeled.png')
label.save(OUT/f'{args.run.name}-actual-sprite-labeled.png')
actual_crop.save(OUT/f'{args.run.name}-actual-sprite-visible.png')
full_frame = Image.open(samples[0]['screenshot']).convert('RGB')
full_label = Image.new('RGB',(768,616),'#141721');full_draw = ImageDraw.Draw(full_label)
full_draw.text((8,4),'face-afl.afl — ACTUAL VICE / 8 SPRITE AFLI',font=font,fill='white')
full_draw.text((8,26),'Full frame 384×272; source 208×200; left 112 pixels outside valid area',font=font,fill='#B8C0D6')
status = 'PASS: 41,600 image pixels + 15,360 black pixels below × 3 frames' if report['pass'] and args.require_black_bottom else 'Historical image-only pass; bottom cleanup not accepted' if report['pass'] else 'FAIL: see image/bottom/RAM report'
full_draw.text((8,48),status,font=font,fill='#B8E4CE' if report['pass'] and args.require_black_bottom else '#FF8F9A')
full_label.paste(full_frame.resize((768,544),Image.Resampling.NEAREST),(0,72))
full_path = OUT/f'{args.run.name}-actual-full-frame-labeled.png'
full_label.save(full_path)
print(json.dumps({'pass':report['pass'],'report':str(report_path), 'failures':failures,
                  'pixel_mismatches':[sample['mismatches'] for sample in sample_reports],
                  'bank_mismatches':[bank['mismatch_count'] for bank in bank_reports],
                  'counter_advances':advances,'labeled_actual':str(OUT/'face-afl-actual-sprite-labeled.png'),
                  'labeled_full_frame':str(full_path),
                  'bottom_nonblack_pixels':[sample['bottom_nonblack_pixels'] for sample in sample_reports]},indent=2))
raise SystemExit(0 if report['pass'] else 1)
