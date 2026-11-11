#!/usr/bin/env python3
"""Prove the orbiting ball survives fixed-font matching in front of/behind glass.

The hidden-ball controls are independently Bayer-quantized and matched in
Python. No font, movie, packing, or player files are changed by this check.
"""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
DEFAULT = HERE.parent / 'build/three-scene-glass'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rank(x, y):
    def pair(a, b):
        return 2 * (a ^ b) + b
    return 4 * pair(x & 1, y & 1) + pair((x >> 1) & 1, (y >> 1) & 1)


def quantize(rgba):
    assert len(rgba) == 64000
    bits = bytearray(16000)
    for y in range(100):
        for x in range(160):
            pixel = y * 160 + x
            at = pixel * 4
            assert rgba[at] == rgba[at + 1] == rgba[at + 2]
            bits[pixel] = rgba[at] * rgba[at + 3] / 255 >= (rank(x, y) + .5) * 255 / 16
    return bits


def unpack(packed):
    assert len(packed) == 2000
    return bytearray((packed[index >> 3] >> (7 - (index & 7))) & 1 for index in range(16000))


def expand(logical):
    assert len(logical) == 16000
    return bytearray(logical[(y // 2) * 160 + x // 2] for y in range(200) for x in range(320))


def match(pixels, mask, font):
    glyphs = [int.from_bytes(font[index:index + 8], 'big') for index in range(0, len(font), 8)]
    cache = {}
    output = bytearray(1000)
    for cell in range(1000):
        left, top = cell % 40 * 8, cell // 40 * 8
        target, allowed = 0, 0
        for row in range(8):
            for x in range(8):
                index = (top + row) * 320 + left + x
                target = (target << 1) | pixels[index]
                allowed = (allowed << 1) | mask[index]
        key = target, allowed
        if key not in cache:
            best_code, best_error = 0, 65
            for code, glyph in enumerate(glyphs):
                if glyph & ~allowed:
                    continue
                error = (target ^ glyph).bit_count()
                if error < best_error:
                    best_code, best_error = code, error
                if not error:
                    break
            assert best_error < 65
            cache[key] = best_code
        output[cell] = cache[key]
    return bytes(output)


def render(screen, font):
    pixels = bytearray(64000)
    for cell, code in enumerate(screen):
        left, top = cell % 40 * 8, cell // 40 * 8
        for row in range(8):
            for x in range(8):
                pixels[(top + row) * 320 + left + x] = (font[code * 8 + row] >> (7 - x)) & 1
    return pixels


def image(pixels):
    return Image.frombytes('L', (320, 200), bytes(value * 255 for value in pixels)).convert('RGB')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT)
    parser.add_argument('--output', type=Path)
    options = parser.parse_args()
    base = options.input.resolve()
    output = options.output.resolve() if options.output else base / 'character-visibility.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    characters = base / 'characters'
    source = json.loads((base / 'render/metadata.json').read_text())
    metadata = json.loads((characters / 'metadata.json').read_text())
    proof = json.loads((base / 'verification.json').read_text())
    assert proof['pass'] and proof['loop']['endpointMatchesStart']
    assert metadata['frameCount'] == source['frameCount'] == 161
    assert metadata['fontExtension']['firstEligibleSourceFrame'] == 0
    assert metadata['bitmapSource']['prependedBlankFrames'] == 0
    font = (characters / 'font.bin').read_bytes()
    screens = (characters / 'reference.frames').read_bytes()
    movie = (base / 'render' / source['framesFile']).read_bytes()
    masks = (base / 'render' / source['objectMaskFile']).read_bytes()
    matching_masks = Path(metadata['objectMask']['file']).read_bytes()
    rings = (base / proof['outline']['ringMaskFile']).read_bytes() if proof.get('outline') else None
    assert len(font) == 2048 and len(screens) == 161000
    assert font == Path(metadata['fontExtension']['source']).read_bytes(), 'Existing fixed font was changed'
    assert sha(font) == metadata['hashes']['font']
    assert sha(screens) == metadata['hashes']['screens']
    assert sha(movie) == source['hashes']['frames'] == metadata['hashes']['sourcePacked'] == proof['bitmapSha256']
    assert sha(masks) == source['hashes']['objectMask']
    assert sha(matching_masks) == metadata['objectMask']['sha256']
    if rings:
        assert sha(rings) == proof['outline']['ringMaskSha256']
        assert matching_masks == masks or all(allowed == (original & ~ring) for allowed, original, ring in zip(matching_masks, masks, rings))
    else:
        assert matching_masks == masks
    assert sha(Path(source['sceneSource']).read_bytes()) == source['sourceSha256'] == proof['sourceSha256']
    assert source.get('sourceDependencies', []) == proof.get('sourceDependencies', [])
    for dependency in source.get('sourceDependencies', []):
        assert sha(Path(dependency['source']).read_bytes()) == dependency['sha256']
    comparison = Image.new('RGB', (640, 448))
    comparison_draw = ImageDraw.Draw(comparison)
    controls = Image.new('RGB', (960, 448))
    controls_draw = ImageDraw.Draw(controls)
    optical = Image.new('RGB', (960, 448))
    optical_draw = ImageDraw.Draw(optical)
    rows = []
    for row, (frame, side) in enumerate(((41, 'front'), (121, 'behind'))):
        full_rgba = (base / f'control-{side}-full.rgba').read_bytes()
        hidden_rgba = (base / f'control-{side}-hidden.rgba').read_bytes()
        ball_rgba = (base / f'control-{side}-ball.rgba').read_bytes()
        no_refraction_rgba = (base / f'control-{side}-no-refraction.rgba').read_bytes()
        no_refraction_hidden_rgba = (base / f'control-{side}-no-refraction-hidden.rgba').read_bytes()
        sharp_rgba = (base / f'control-{side}-sharp.rgba').read_bytes()
        sharp_hidden_rgba = (base / f'control-{side}-sharp-hidden.rgba').read_bytes()
        full_mask = (base / f'control-{side}-full-mask.frames').read_bytes()
        hidden_mask = (base / f'control-{side}-hidden-mask.frames').read_bytes()
        affected_mask = (base / f'control-{side}-affected-mask.frames').read_bytes()
        gpu_control = next(item for item in proof['controls'] if item['side'] == side)
        assert sha(full_rgba) == gpu_control['fullSha256']
        assert sha(hidden_rgba) == gpu_control['hiddenSha256']
        assert sha(ball_rgba) == gpu_control['ballOnlySha256']
        for data, key in ((no_refraction_rgba, 'noRefractionSha256'),
                          (no_refraction_hidden_rgba, 'noRefractionHiddenSha256'),
                          (sharp_rgba, 'sharpSha256'), (sharp_hidden_rgba, 'sharpHiddenSha256'),
                          (full_mask, 'fullMaskSha256'), (hidden_mask, 'hiddenMaskSha256'),
                          (affected_mask, 'affectedMaskSha256')):
            assert sha(data) == gpu_control[key]
        logical_target = unpack(movie[frame * 2000:(frame + 1) * 2000])
        assert logical_target == quantize(full_rgba)
        logical_mask = unpack(masks[frame * 2000:(frame + 1) * 2000])
        assert unpack(full_mask) == logical_mask, ('Independent full GPU mask differs from export', side)
        # Refracted pixels may move outside the original ball footprint. Use the
        # measured full-minus-hidden support together with the no-glass ball.
        allowed_pose = unpack(matching_masks[frame * 2000:(frame + 1) * 2000])
        target, hidden_target, mask, roi = map(expand, (logical_target, quantize(hidden_rgba),
                                                       allowed_pose, unpack(affected_mask)))
        hidden_allowed = expand(unpack(hidden_mask))
        actual_screen = screens[frame * 1000:(frame + 1) * 1000]
        full_match = match(target, mask, font)
        assert full_match == actual_screen, ('Independent full-frame matcher differs from packed movie', side)
        hidden_screen = match(hidden_target, hidden_allowed, font)
        no_refraction_target = expand(quantize(no_refraction_rgba))
        no_refraction_hidden_target = expand(quantize(no_refraction_hidden_rgba))
        sharp_target = expand(quantize(sharp_rgba))
        sharp_hidden_target = expand(quantize(sharp_hidden_rgba))
        no_refraction_screen = match(no_refraction_target, mask, font)
        no_refraction_hidden_screen = match(no_refraction_hidden_target, hidden_allowed, font)
        sharp_screen = match(sharp_target, mask, font)
        sharp_hidden_screen = match(sharp_hidden_target, hidden_allowed, font)
        actual, hidden = render(actual_screen, font), render(hidden_screen, font)
        no_refraction = render(no_refraction_screen, font)
        no_refraction_hidden = render(no_refraction_hidden_screen, font)
        sharp = render(sharp_screen, font)
        sharp_hidden = render(sharp_hidden_screen, font)
        assert all(not pixel or allowed for pixel, allowed in zip(actual, mask))
        assert all(not pixel or allowed for pixel, allowed in zip(hidden, hidden_allowed))
        roi_pixels = sum(roi)
        source_changes = sum(in_roi and a != b for in_roi, a, b in zip(roi, target, hidden_target))
        output_changes = sum(in_roi and a != b for in_roi, a, b in zip(roi, actual, hidden))
        shared_changes = sum(in_roi and a != b and c != d for in_roi, a, b, c, d in zip(roi, target, hidden_target, actual, hidden))
        actual_white = sum(in_roi and pixel for in_roi, pixel in zip(roi, actual))
        hidden_white = sum(in_roi and pixel for in_roi, pixel in zip(roi, hidden))
        changed_chars = [cell for cell, (a, b) in enumerate(zip(actual_screen, hidden_screen)) if a != b]
        refracted_contribution = bytearray(a != b for a, b in zip(actual, hidden))
        straight_contribution = bytearray(a != b for a, b in zip(no_refraction, no_refraction_hidden))
        sharp_contribution = bytearray(a != b for a, b in zip(sharp, sharp_hidden))
        refraction_pixels = sum(in_roi and a != b for in_roi, a, b in zip(roi, refracted_contribution, straight_contribution))
        softening_pixels = sum(in_roi and a != b for in_roi, a, b in zip(roi, refracted_contribution, sharp_contribution))
        direct_refraction_pixels = sum(in_roi and a != b for in_roi, a, b in zip(roi, actual, no_refraction))
        direct_softening_pixels = sum(in_roi and a != b for in_roi, a, b in zip(roi, actual, sharp))
        outline_control = None
        if rings:
            ring = expand(unpack(rings[frame*2000:(frame+1)*2000]))
            no_outline_rgba = (base / f'control-{side}-no-outline.rgba').read_bytes()
            no_outline_mask = (base / f'control-{side}-no-outline-mask.frames').read_bytes()
            assert sha(no_outline_rgba) == gpu_control['outline']['noOutlineSha256']
            assert sha(no_outline_mask) == gpu_control['outline']['noOutlineMaskSha256']
            no_outline_screen = match(expand(quantize(no_outline_rgba)), expand(unpack(no_outline_mask)), font)
            no_outline = render(no_outline_screen, font)
            ring_white = sum(in_ring and pixel for in_ring, pixel in zip(ring, actual))
            no_outline_white = sum(in_ring and pixel for in_ring, pixel in zip(ring, no_outline))
            assert ring_white == 0, ('The nearest glyph filled the opaque black annulus', side, ring_white)
            if side == 'front':
                assert no_outline_white >= 16, ('The black outline does not separate from the no-outline image', no_outline_white)
            else:
                assert actual_screen == no_outline_screen
            outline_control = {'ringPhysicalPixels': sum(ring), 'actualRingWhitePixels': ring_white,
                               'noOutlineRingWhitePixels': no_outline_white,
                               'ringWhitesRemoved': no_outline_white-ring_white}
            if side == 'front':
                outline_panel = Image.new('RGB', (960, 224))
                outline_draw = ImageDraw.Draw(outline_panel)
                for column, (title, pixels) in enumerate((('No outline control', no_outline),
                                                          ('Actual C64 black outline', actual),
                                                          ('Measured annulus: all black in C64', ring))):
                    outline_draw.text((column*320+6, 5), title, fill='white')
                    outline_panel.paste(image(pixels), (column*320, 24))
                outline_panel.save(output.parent / 'characters-outline-control.png')
                (output.parent / 'control-front-no-outline.screen').write_bytes(no_outline_screen)
        assert output_changes >= 32, ('Ball lost during fixed-font matching', side, output_changes)
        assert shared_changes >= 16, ('Character differences do not coincide with the actual ball', side, shared_changes)
        assert actual_white > hidden_white, ('Ball loses its brighter tone through glass', side)
        if side == 'behind':
            assert refraction_pixels >= 40, ('Spatial refraction lost in fixed-font matching', refraction_pixels)
            if gpu_control['optics'].get('softeningRequired', True):
                assert softening_pixels >= 16, ('Optical softening lost in fixed-font matching', softening_pixels)
        row_data = {'frame': frame, 'side': side, 'ballRoiPixels': roi_pixels,
                    'sourceChangedPixelsInBallRoi': source_changes,
                    'characterChangedPixelsInBallRoi': output_changes,
                    'changedPixelsSharedWithSourceBall': shared_changes,
                    'characterWhitePixelsInBallRoi': actual_white,
                    'hiddenControlWhitePixelsInBallRoi': hidden_white,
                    'netWhitePixelIncreaseInBallRoi': actual_white - hidden_white,
                    'changedCharacterCount': len(changed_chars), 'changedCharacterPositions': changed_chars,
                    'fullCharacterMatchEqualsActualMovie': True, 'independentMaskEqualsActualGpuSilhouette': True,
                    'refractedContributionDifferenceFromNoRefractionPixels': refraction_pixels,
                    'softenedContributionDifferenceFromSharpPixels': softening_pixels,
                    'directRefractionDifferencePixels': direct_refraction_pixels,
                    'directSofteningDifferencePixels': direct_softening_pixels,
                    **({'outline': outline_control} if outline_control else {}),
                    'sourceRgbaSha256': sha(full_rgba), 'hiddenRgbaSha256': sha(hidden_rgba),
                    'actualScreenSha256': sha(actual_screen), 'hiddenScreenSha256': sha(hidden_screen)}
        rows.append(row_data)
        y = row * 224
        comparison_draw.text((6, y + 5), f'{side.upper()} / frame {frame}: bitmap | actual C64 character pixels', fill='white')
        comparison.paste(image(target), (0, y + 24))
        comparison.paste(image(actual), (320, y + 24))
        difference = bytearray(a != b for a, b in zip(actual, hidden))
        for column, (title, pixels) in enumerate((('Ball visible', actual), ('Same cube, ball hidden', hidden), ('Character pixel changes', difference))):
            controls_draw.text((column * 320 + 6, y + 5), f'{side.upper()}: {title}', fill='white')
            controls.paste(image(pixels), (column * 320, y + 24))
        for column, (title, pixels) in enumerate((('No refraction', no_refraction), ('Sharp refraction', sharp), ('Refraction + softening', actual))):
            optical_draw.text((column * 320 + 6, y + 5), f'{side.upper()}: {title}', fill='white')
            optical.paste(image(pixels), (column * 320, y + 24))
        (output.parent / f'control-{side}-hidden.screen').write_bytes(hidden_screen)
    comparison.save(output.parent / 'bitmap-vs-characters-front-back.png')
    controls.save(output.parent / 'characters-transparency-control.png')
    optical.save(output.parent / 'characters-optics-controls.png')
    assert rows[0]['hiddenScreenSha256'] != rows[1]['hiddenScreenSha256'], 'The moving cube became static in character conversion'
    outline_proof = None
    if rings:
        ring_whites = 0
        for frame in range(source['frameCount']):
            actual = render(screens[frame*1000:(frame+1)*1000], font)
            ring = expand(unpack(rings[frame*2000:(frame+1)*2000]))
            ring_whites += sum(in_ring and pixel for in_ring, pixel in zip(ring, actual))
        assert ring_whites == 0, 'The black annulus is not preserved in every character frame'
        if proof['shape']['type'] == 'BoxGeometry':
            old_screens = (base.parent / 'three-scene-glass-refraction/characters/reference.frames').read_bytes()
            assert screens[81000:] == old_screens[81000:], 'The outline changed a stored behind-half character image'
            comparison_method = 'byte comparison with same cube before outline'
        else:
            assert proof['outline']['comparison']['method'] == 'actual GPU same-shape no-outline control'
            assert proof['outline']['unchangedBehindFrames'] == 80
            assert matching_masks[81*2000:] == masks[81*2000:]
            comparison_method = '80 identical same-shape GPU no-outline targets and masks, deterministic immutable-font matching'
        outline_proof = {'everyFrameRingWhitePixels': 0, 'unchangedBehindCharacterFrames': 80,
                         'actualOpaqueRingMasksUsed': True, 'behindComparison': comparison_method}
    report = {'pass': True, 'scope': 'Semantic visibility after immutable-font matching; PAL decoder equivalence is checked separately.',
              'model': source.get('title', source['name']), 'shape': proof['shape'], 'fontModified': False,
              'fontSha256': sha(font), 'characterMovieSha256': sha(screens),
              'bitmapSha256': sha(movie), 'sceneSha256': source['sourceSha256'],
              'sourceDependencies': source.get('sourceDependencies', []),
              'independentMatcher': 'Python 64-bit minimum Hamming distance, lowest-code tie, all 256 fixed glyphs; each full/hidden control uses its independently rendered per-pose opaque object mask.',
              'behindBallSurvivesCharacterConversion': True,
              'behindRefractionSurvivesCharacterConversion': True,
              'behindSofteningSurvivesCharacterConversion': rows[1]['softenedContributionDifferenceFromSharpPixels'] >= 16,
              'behindRefractionAndSofteningSurviveCharacterConversion': rows[1]['softenedContributionDifferenceFromSharpPixels'] >= 16,
              'movingCubeSurvivesCharacterConversion': True,
              'allSelectedActualScreensEqualIndependentMatching': True, 'controls': rows,
              **({'outline': outline_proof} if outline_proof else {}),
              'previews': ['bitmap-vs-characters-front-back.png', 'characters-transparency-control.png', 'characters-optics-controls.png']
                          + (['characters-outline-control.png'] if rings else [])}
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
