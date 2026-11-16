const assert = require('node:assert/strict');
const test = require('node:test');
const { TextEncoder } = require('node:util');
const { ImageData, palette, createContext } = require('./fixtures/sprite-images.cjs');

const context = createContext(['afli-sprite-export.js', 'border-sprites.js', 'border-color-optimizer.js', 'border-sprite-export.js']);
context.TextEncoder = TextEncoder;
const { convertC64BorderSprites, encodeC64BorderSpriteZip, optimizeC64BorderColors } = context;

function converted(interlaced = false) {
  const settings = { vertical: { enabled: true, mode: 'multicolor', colorIndex: 2 },
    sides: { enabled: true, mode: 'hires', colorIndex: 5 }, multicolorIndices: [1, 14] };
  const source = new ImageData(368, 272);
  for (let y = 0; y < 272; y += 1) {
    for (let x = 0; x < 368; x += 1) {
      source.data.set([...palette[y < 35 || y >= 235 ? 2 : 5].rgb, 255], (y * 368 + x) * 4);
    }
  }
  return convertC64BorderSprites(source, palette, settings, 9, interlaced);
}

// The shared ZIP writer owns CRC/header tests; this reads its public archive
// entries to check that the downloaded native data and placement agree.
function entries(archive) {
  const zip = Buffer.from(archive);
  const files = new Map();
  let offset = 0;
  while (zip.readUInt32LE(offset) === 0x04034b50) {
    const size = zip.readUInt32LE(offset + 18);
    const nameLength = zip.readUInt16LE(offset + 26);
    const start = offset + 30 + nameLength + zip.readUInt16LE(offset + 28);
    files.set(zip.toString('utf8', offset + 30, offset + 30 + nameLength), zip.subarray(start, start + size));
    offset = start + size;
  }
  return files;
}

function normalConverted(mode, interlaced = true) {
  const settings = { vertical: { enabled: true, mode, colorIndex: 2, xExpanded: false },
    sides: { enabled: true, mode: 'hires', colorIndex: 5 }, multicolorIndices: [1, 14] };
  const source = new ImageData(368, 272);
  for (let y = 0; y < 272; y += 1) {
    for (let x = 0; x < 368; x += 1) {
      const vertical = y < 35 || y >= 235;
      const island = [9, 47, 91, 139, 177, 219, 267, 319].some(left => x >= left && x < left + 24);
      const color = vertical ? (island ? 2 : 9) : x < 24 || x >= 344 ? 5 : 9;
      source.data.set([...palette[color].rgb, 255], (y * 368 + x) * 4);
    }
  }
  const colorPlan = optimizeC64BorderColors(source, palette, settings, 9, interlaced);
  return convertC64BorderSprites(source, palette, settings, 9, interlaced, { colorPlan });
}

function decodeBorderField(manifest, binary, phase) {
  const { width, height } = manifest.image;
  const image = new ImageData(width, height);
  const background = manifest.hardware.backgroundColorRegister;
  for (let offset = 0; offset < image.data.length; offset += 4) image.data.set([...palette[background].rgb, 255], offset);
  for (const sprite of manifest.sprites.filter(sprite => (sprite.field ?? 0) === phase)) {
    const codes = sprite.multicolor
      ? [background, manifest.hardware.sharedMulticolorRegisters[0], sprite.colorIndex, manifest.hardware.sharedMulticolorRegisters[1]]
      : [background, sprite.colorIndex];
    for (let y = 0; y < 21; y += 1) for (let x = 0; x < sprite.displayWidth; x += 1) {
      const px = sprite.x + x, py = sprite.y + y;
      if (px < 0 || px >= width || py < 0 || py >= height || px < sprite.clip.x || px >= sprite.clip.x + sprite.clip.width ||
          py < sprite.clip.y || py >= sprite.clip.y + sprite.clip.height) continue;
      const bit = Math.floor(x / (sprite.xExpanded ? 2 : 1));
      const byte = binary[sprite.byteOffset + y * 3 + Math.floor(bit / 8)];
      const code = sprite.multicolor ? (byte >> (6 - 2 * Math.floor(bit % 8 / 2))) & 3 : (byte >> (7 - bit % 8)) & 1;
      image.data.set([...palette[codes[code]].rgb, 255], (py * width + px) * 4);
    }
  }
  return image;
}

test('downloads native multiplexed frames with colors, PAL coordinates, expansion and clipping metadata', () => {
  const result = converted();
  const files = entries(encodeC64BorderSpriteZip(result));
  const binary = files.get('sprites.bin');
  const manifest = JSON.parse(files.get('manifest.json'));
  assert.equal(manifest.format, 'c64-border-sprites');
  assert.equal(binary.length, 52 * 64);
  assert.deepEqual(manifest.image.core, { x: 24, y: 35, width: 320, height: 200 });
  assert.equal(manifest.hardware.programIncluded, false);
  assert.equal(manifest.fields, undefined, 'single-field archives retain their existing shape');
  assert.equal(manifest.hardware.borderOpeningRequired, true);
  assert.equal(manifest.hardware.rasterMultiplexingRequired, true);
  assert.equal(manifest.hardware.backgroundColorRegister, 9);
  assert.deepEqual(manifest.hardware.sharedMulticolorRegisters, [1, 14]);
  for (const sprite of manifest.sprites) {
    assert.equal(sprite.byteOffset, sprite.index * 64);
    assert.equal(sprite.byteLength, 64);
    assert.equal(binary[sprite.byteOffset + 63], 0);
    const vertical = sprite.group === 'top' || sprite.group === 'bottom';
    assert.equal(sprite.mode, vertical ? 'multicolor' : 'hires');
    assert.equal(sprite.colorIndex, vertical ? 2 : 5);
    assert.equal(sprite.xExpanded, vertical);
    assert.equal(sprite.yExpanded, false);
    assert.equal(sprite.vicX, sprite.x);
    assert.equal(sprite.vicY, sprite.y + 15);
    if (sprite.group === 'bottom') {
      assert.equal(binary[sprite.byteOffset], sprite.x < 368 ? 0xaa : 0);
      assert.equal(sprite.vicY, 250 + sprite.band * 21);
    }
    if (vertical) {
      assert.equal(sprite.vicYRegister, sprite.vicY & 0xff);
      assert.equal(sprite.displayHeight, 21);
      assert.ok(sprite.rowHeights.every(height => height === 1));
    }
    if (!vertical) {
      const lastBand = sprite.band === 9;
      assert.equal(binary[sprite.byteOffset], lastBand ? 0 : 0xff);
      assert.equal(sprite.hardwareSlot, (sprite.group === 'left' ? 3 : 4) + (lastBand ? 2 : 0));
      assert.equal(sprite.displayHeight, 21);
      assert.equal(sprite.vicY, lastBand ? 229 : 50 + sprite.band * 21);
      assert.ok(sprite.rowHeights.every(height => height === 1));
      assert.equal(sprite.rowHeights.reduce((sum, value) => sum + value, 0), sprite.displayHeight);
      assert.deepEqual(sprite.clip, { x: sprite.group === 'left' ? 0 : 344,
        y: lastBand ? 224 : 35, width: 24, height: lastBand ? 11 : 200 });
      if (lastBand) {
        assert.ok(binary.subarray(sprite.byteOffset, sprite.byteOffset + 30).every(value => value === 0),
          'the spare slot stays transparent while the preceding side sprite is active');
        assert.equal(binary[sprite.byteOffset + 30], 0xff);
      }
    }
  }
});

test('exports both MCI sprite datasets with field offsets and distinct shifted native data', () => {
  const result = converted(true);
  const files = entries(encodeC64BorderSpriteZip(result));
  const binary = files.get('sprites.bin');
  const manifest = JSON.parse(files.get('manifest.json'));
  assert.equal(binary.length, 104 * 64);
  assert.equal(manifest.interlaced, true);
  assert.deepEqual(manifest.fields, [
    { phase: 0, offsetX: 0, spriteOffset: 0, spriteCount: 52, byteOffset: 0, byteLength: 3328 },
    { phase: 1, offsetX: 1, spriteOffset: 52, spriteCount: 52, byteOffset: 3328, byteLength: 3328 }
  ]);
  assert.equal(manifest.sprites.length, 104);
  for (const [index, sprite] of manifest.sprites.entries()) {
    const phase = Math.floor(index / 52);
    const first = manifest.sprites[index % 52];
    assert.equal(sprite.index, index);
    assert.equal(sprite.field, phase);
    assert.equal(sprite.byteOffset, index * 64);
    assert.equal(sprite.x, first.x + phase);
    assert.equal(sprite.vicX, first.vicX + phase);
    assert.equal(sprite.clip.x, first.clip.x + phase);
  }
  const firstRight = manifest.sprites.find(sprite => sprite.field === 0 && sprite.group === 'right');
  const secondRight = manifest.sprites.find(sprite => sprite.field === 1 && sprite.group === 'right');
  assert.equal(binary[firstRight.byteOffset + 2], 0xff);
  assert.equal(binary[secondRight.byteOffset + 2], 0xfe,
    'the second field preserves its clipped final hires bit instead of duplicating the first dataset');
});

test('rejects inactive, truncated and malformed native border data instead of creating a misleading archive', () => {
  for (const mutate of [
    result => { result.config.vertical.enabled = result.config.sides.enabled = false; },
    result => { result.sprites.pop(); },
    result => { result.sprites[0].data = new Uint8Array(63); },
    result => { result.sprites[0].data[63] = 1; },
    result => { result.backgroundColorIndex = 16; },
    result => { result.config.vertical.mode = 'hires'; },
    result => { result.sprites.find(sprite => sprite.group === 'bottom' && sprite.band === 1).vicYRegister = 271; }
  ]) {
    const result = converted();
    mutate(result);
    assert.throws(() => encodeC64BorderSpriteZip(result), /Border sprite/);
  }
});

test('optimized archives carry resolved shared colors and an authoritative foreground for every logical sprite', () => {
  const manual = converted(true);
  const plan = { multicolorIndices: [3, 14], colorIndices: Array.from({ length: 52 }, (_, index) => index % 16),
    spriteCount: 52, phaseCount: 2, backgroundColorIndex: 9,
    metric: 'native-pixel-oklab-sse', baselineError: 10, optimizedError: 5, improvementPercent: 50 };
  const source = new ImageData(368, 272);
  source.data.set(manual.frames[0].pixels.data);
  const result = convertC64BorderSprites(source, palette, { ...manual.config, optimizeColors: true }, 9, true, { colorPlan: plan });
  const files = entries(encodeC64BorderSpriteZip(result));
  const manifest = JSON.parse(files.get('manifest.json'));
  assert.equal(manifest.settings.optimizeColors, true);
  assert.deepEqual(manifest.hardware.sharedMulticolorRegisters, [3, 14]);
  assert.equal(manifest.hardware.individualSpriteColors, true);
  assert.equal(manifest.colorOptimization.phaseColorsTied, true);
  assert.equal(manifest.colorOptimization.improvementPercent, 50);
  manifest.sprites.forEach((sprite, index) => assert.equal(sprite.colorIndex, plan.colorIndices[index % 52]));
  assert.equal(files.get('sprites.bin').length, 6656);
  result.frames[1].sprites[0].colorIndex = (result.frames[0].sprites[0].colorIndex + 1) % 16;
  assert.throws(() => encodeC64BorderSpriteZip(result), /Border sprite frames/,
    'a second MCI field cannot silently acquire a different palette');
});

test('normal-width archives retain optimized positions and reproduce each native field with background gaps', () => {
  for (const mode of ['hires', 'multicolor']) for (const interlaced of [false, true]) {
    const result = normalConverted(mode, interlaced);
    const files = entries(encodeC64BorderSpriteZip(result));
    const manifest = JSON.parse(files.get('manifest.json'));
    assert.equal(manifest.settings.vertical.xExpanded, false);
    assert.equal(manifest.colorOptimization, undefined, 'manual colors still get optimized placement');
    assert.equal(manifest.placementOptimization.spritesPerBand, 8);
    assert.equal(manifest.placementOptimization.spriteWidth, 24);
    assert.equal(manifest.placementOptimization.phasePositionsTied, true);
    assert.equal(manifest.placementOptimization.uncoveredPixels, 'shared-background');
    assert.equal(manifest.placementOptimization.jointColorOptimization, false);
    assert.equal(manifest.placementOptimization.optimizedError, result.colorPlan.optimizedError);
    assert.deepEqual(manifest.placementOptimization.verticalPositions, Array.from(result.colorPlan.verticalPositions));
    assert.match(manifest.hardware.verticalBandRetrigger, /schedule X and \$D010/);
    const frames = result.frames ?? [result];
    for (const [phase, frame] of frames.entries()) {
      const records = manifest.sprites.filter(sprite => (sprite.field ?? 0) === phase);
      for (const [index, sprite] of records.slice(0, 32).entries()) {
        assert.equal(sprite.displayWidth, 24);
        assert.equal(sprite.xExpanded, false);
        assert.equal(sprite.yExpanded, false);
        assert.equal(sprite.x, result.colorPlan.verticalPositions[index] + phase);
        if (index % 8) assert.ok(sprite.x >= records[index - 1].x + 24);
      }
      assert.deepEqual(decodeBorderField(manifest, files.get('sprites.bin'), phase).data, frame.pixels.data,
        `${mode}, field ${phase}: downloaded native bits and geometry reproduce the preview`);
      const top = records.filter(sprite => sprite.group === 'top' && sprite.band === 0);
      const gaps = Array.from({ length: 368 }, (_, x) => x).filter(x => !top.some(sprite => x >= sprite.x && x < sprite.x + 24));
      assert.ok(gaps.length >= 368 - 8 * 24);
      for (const x of gaps) assert.deepEqual(Array.from(frame.pixels.data.subarray(x * 4, x * 4 + 4)), [...palette[9].rgb, 255]);
    }
  }
});

test('normal-width exports reject pending, overlapping, mismatched and impossible placement plans', () => {
  const original = normalConverted('multicolor');
  for (const mutate of [
    result => { delete result.colorPlan; },
    result => { result.colorPlan.verticalPositions.pop(); },
    result => { result.colorPlan.verticalPositions[1] = result.colorPlan.verticalPositions[0] + 23; },
    result => { result.colorPlan.verticalPositions[31] = 345; },
    result => { result.colorPlan.optimizedError = Infinity; },
    result => { result.frames[0].sprites[0].x += 1; },
    result => { result.frames[0].sprites[0].hardwareSlot = result.frames[0].sprites[1].hardwareSlot; },
    result => { result.frames[1].sprites[0].x += 1; },
    result => { result.frames[1].sprites[0].xExpanded = true; }
  ]) {
    const result = structuredClone(original);
    mutate(result);
    assert.throws(() => encodeC64BorderSpriteZip(result), /border|Border/);
  }
});
