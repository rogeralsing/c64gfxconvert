#!/usr/bin/env python3
"""Show the approved bitmap, character reconstruction and their pixel difference."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--characters', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.characters.resolve()
    metadata = json.loads((source / 'metadata.json').read_text())
    font = (source / 'font.bin').read_bytes()
    screens = (source / 'reference.frames').read_bytes()
    ideal = (source / 'ideal.frames').read_bytes()
    count = metadata['frameCount']
    assert len(ideal) == count * 64000 and len(screens) == count * 1000
    worst = max(metadata['statistics'], key=lambda row: row['mismatches'])['frame']
    samples = sorted(set([1, min(count-1, 41), min(count-1, 81), min(count-1, 121), count-1, worst]))
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sheet = Image.new('RGB', (960, len(samples)*224), (18, 21, 17))
    draw = ImageDraw.Draw(sheet)
    glyphs = [Image.frombytes('L', (8, 8), bytes(255 if row & (128 >> x) else 0
              for row in font[code*8:code*8+8] for x in range(8))) for code in range(len(font)//8)]
    for row, frame in enumerate(samples):
        reference = Image.frombytes('L', (320, 200), bytes(value*255 for value in ideal[frame*64000:(frame+1)*64000]))
        actual = Image.new('L', (320, 200))
        for cell, code in enumerate(screens[frame*1000:(frame+1)*1000]):
            actual.paste(glyphs[code], (cell % 40 * 8, cell // 40 * 8))
        difference = Image.new('RGB', (320, 200))
        difference.putdata([(a//4, a//4, a//4) if a == b else (255, 75, 75) if a else (75, 220, 255)
                            for a, b in zip(reference.tobytes(), actual.tobytes())])
        error = metadata['statistics'][frame]['mismatches']
        for column, (name, image) in enumerate([('Bitmap', reference), ('Characters', actual), ('Red lost / cyan added', difference)]):
            draw.text((column*320+5, row*224+5), f'{name} | frame {frame} | error {error}px', fill=(217, 241, 138))
            sheet.paste(image, (column*320, row*224+24))
    sheet.save(output / 'glass-source-comparison.png')
    print(json.dumps({'pass': True, 'frames': samples, 'worstFrame': worst,
                      'comparison': str(output / 'glass-source-comparison.png')}))


if __name__ == '__main__':
    main()
