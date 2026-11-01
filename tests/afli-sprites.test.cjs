const assert = require('node:assert/strict');
const test = require('node:test');
const { palette, bands, createContext, image, setPixel } = require('./fixtures/sprite-images.cjs');
const context = createContext(['fli.js', 'afli-sprites.js', 'afli-export.js']);
const { createAfliSpriteImage, encodeAfli } = context;

function tileMask(mask, x = 112) {
  return Array.from({ length: 16 }, (_, index) => mask[Math.floor(index / 4) * 320 + x + index % 4]);
}

test('sprite pixels free both AFLI row colors while keeping an exportable underlay', () => {
  const source = image();
  const targets = image();
  const expected = [1, 1, 1, 0, 0, 2, 2, 2];
  expected.forEach((color, x) => {
    setPixel(source, 112 + x, 0, palette[color].rgb);
    setPixel(targets, 112 + x, 0, palette[color === 1 ? 7 : color].rgb);
  });
  const result = createAfliSpriteImage(source, targets, palette, bands, 1, 0, 0);
  for (let x = 0; x < 8; x += 1) {
    const offset = (112 + x) * 4;
    assert.deepEqual(Array.from(result.pixels.data.subarray(offset, offset + 4)), [...palette[expected[x]].rgb, 255]);
  }
  assert.deepEqual(Array.from(result.afli.rowColors.subarray(14 * 8 * 2, 14 * 8 * 2 + 2)), [0, 2]);
  assert.equal(result.spritePixelCount, 3);
  assert.equal(encodeAfli(result.afli, palette).length, 16385);
});

test('all sixteen C64 colors can be exact sprite colors only inside the eight-sprite field', () => {
  for (const color of palette) {
    const source = image(color.rgb);
    const result = createAfliSpriteImage(source, source, palette, bands, color.index, 0, 1);
    assert.equal(result.spritePixelCount, 192 * 200, color.index);
    assert.equal(result.spriteColorIndex, color.index);
    for (let y = 0; y < 200; y += 1) {
      for (const x of [0, 111, 304, 319]) assert.equal(result.spriteMask[y * 320 + x], 0, `${color.index}, ${x}, ${y}`);
      for (const x of [112, 303]) {
        const offset = (y * 320 + x) * 4;
        assert.equal(result.spriteMask[y * 320 + x], 1);
        assert.deepEqual(Array.from(result.spritePixels.data.subarray(offset, offset + 4)), [...color.rgb, 255]);
      }
    }
  }
});

test('sprite matching reads visible source RGB rather than snapped targets and preserves both inputs', () => {
  const source = image(palette[1].rgb);
  const targets = image(palette[6].rgb);
  setPixel(source, 112, 0, [...palette[1].rgb, 0]);
  setPixel(source, 113, 0, [...palette[1].rgb, 128]);
  setPixel(source, 115, 0, palette[6].rgb);
  setPixel(targets, 115, 0, palette[1].rgb);
  const beforeSource = new Uint8ClampedArray(source.data);
  const beforeTargets = new Uint8ClampedArray(targets.data);
  const result = createAfliSpriteImage(source, targets, palette, bands, 1, 0, 0);
  assert.equal(result.spriteMask[112], 0, 'transparent hidden white is not a sprite');
  assert.equal(result.spriteMask[113], 0, 'half-opacity white over the black matte is not exact white');
  assert.equal(result.spriteMask[114], 1, 'source white is selected even when its virtual target is blue');
  assert.equal(result.spriteMask[115], 0, 'a snapped white target cannot turn a blue source pixel into a sprite');
  assert.equal(result.spritePixels.data[112 * 4 + 3], 0);
  assert.deepEqual(source.data, beforeSource);
  assert.deepEqual(targets.data, beforeTargets);
});

test('sprite dithering feathers the match edge with a deterministic ordered 4×4 pattern', () => {
  const targets = image(palette[1].rgb);
  for (const [gray, hardCount, featherCount] of [[224, 16, 9], [213, 0, 4]]) {
    const source = image([gray, gray, gray]);
    const results = [0, 0.5, 1].map(amount => createAfliSpriteImage(source, targets, palette, bands, 1, 0.25, amount));
    const counts = results.map(result => tileMask(result.spriteMask).reduce((sum, value) => sum + value, 0));
    assert.equal(counts[0], hardCount, gray);
    assert.equal(counts[2], featherCount, gray);
    assert.ok(gray === 224 ? counts[0] >= counts[1] && counts[1] >= counts[2]
      : counts[0] <= counts[1] && counts[1] <= counts[2], gray);
    assert.deepEqual(tileMask(results[2].spriteMask), tileMask(results[2].spriteMask, 116));
    const repeated = createAfliSpriteImage(source, targets, palette, bands, 1, 0.25, 1);
    assert.deepEqual(repeated.spriteMask, results[2].spriteMask);
  }
  const far = createAfliSpriteImage(image(palette[0].rgb), targets, palette, bands, 1, 0.25, 1);
  assert.equal(far.spritePixelCount, 0);
});

test('extended sprite matching reaches distant colors monotonically while retaining transparency and hardware bounds', () => {
  const source = image(palette[0].rgb);
  const targets = image(palette[0].rgb);
  setPixel(source, 112, 0, [255, 0, 255, 0]);
  for (const dither of [0, 1]) {
    let previous;
    for (const amount of [0, 1, 2, 3, 4, 5]) {
      const result = createAfliSpriteImage(source, targets, palette, bands, 1, amount, dither);
      if (amount <= 1) assert.equal(result.spritePixelCount, 0, 'black is outside the original white match range');
      if (amount === 3) assert.ok(result.spritePixelCount > 0, 'a larger radius reaches black from white');
      if (amount === 5) assert.equal(result.spritePixelCount, 192 * 200 - 1, 'maximum range includes every visible field pixel');
      assert.equal(result.matchAmount, amount);
      for (let pixel = 0; pixel < result.spriteMask.length; pixel += 1) {
        const x = pixel % 320;
        if (x < 112 || x > 303 || pixel === 112) assert.equal(result.spriteMask[pixel], 0);
        if (previous?.[pixel]) assert.equal(result.spriteMask[pixel], 1, 'increasing range cannot remove a sprite pixel');
      }
      previous = result.spriteMask;
    }
  }
});

test('sprite conversion rejects mismatched image geometry and invalid color or control values', () => {
  const source = image();
  const targets = image();
  assert.throws(() => createAfliSpriteImage({ ...source, width: 160 }, targets, palette, bands, 1, 0.25, 1), /matching 320 × 200/);
  assert.throws(() => createAfliSpriteImage(source, { ...targets, height: 199 }, palette, bands, 1, 0.25, 1), /matching 320 × 200/);
  assert.throws(() => createAfliSpriteImage(source, targets, palette, bands, 16, 0.25, 1), /color from 0 to 15/);
  for (const value of [-0.1, 5.1, NaN, '0.5']) {
    assert.throws(() => createAfliSpriteImage(source, targets, palette, bands, 1, value, 1), /between 0 and 5/);
  }
  for (const value of [-0.1, 1.1, NaN, '0.5']) {
    assert.throws(() => createAfliSpriteImage(source, targets, palette, bands, 1, 0.25, value), /between 0 and 1/);
  }
});
