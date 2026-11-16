const assert = require('node:assert/strict');
const test = require('node:test');
const { TextEncoder } = require('node:util');
const { ImageData, palette, createContext } = require('./fixtures/sprite-images.cjs');

const context = createContext(['afli-sprite-export.js', 'border-sprites.js', 'border-sprite-export.js']);
context.TextEncoder = TextEncoder;
const { convertC64BorderSprites, encodeC64BorderSpriteZip } = context;

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
