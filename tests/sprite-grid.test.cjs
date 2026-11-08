const assert = require('node:assert/strict');
const test = require('node:test');
const { ImageData, palette, createContext, setPixel } = require('./fixtures/sprite-images.cjs');

const { createC64SpriteGridImage } = createContext(['sprite-grid.js']);
const settings = (overrides = {}) => ({
  columns: 1, rows: 1, backgroundColorIndex: 0, multicolorIndices: [5, 6],
  spriteColorIndices: Array(8).fill(2), overlayColorIndices: Array(8).fill(1),
  overlay: false, ...overrides
});
function image(options, rgba = [...palette[0].rgb, 255]) {
  const pixels = new ImageData(options.columns * 24, options.rows * 21);
  for (let offset = 0; offset < pixels.data.length; offset += 4) pixels.data.set(rgba, offset);
  return pixels;
}
const pixel = (pixels, x, y) => Array.from(pixels.data.subarray((y * pixels.width + x) * 4,
  (y * pixels.width + x) * 4 + 4));

test('packs all four hardware color codes and retains individual sprite colors across a 2×2 grid', () => {
  const options = settings({ columns: 2, rows: 2, spriteColorIndices: [2, 7, 8, 3, 2, 2, 2, 2] });
  const source = image(options);
  for (let cell = 0; cell < 4; cell += 1) {
    const x = cell % 2 * 24;
    const y = Math.floor(cell / 2) * 21;
    for (const [pair, color] of [0, 5, options.spriteColorIndices[cell], 6].entries()) {
      setPixel(source, x + pair * 2, y, palette[color].rgb);
      setPixel(source, x + pair * 2 + 1, y, palette[color].rgb);
    }
    setPixel(source, x + 22, y + 20, palette[6].rgb);
    setPixel(source, x + 23, y + 20, palette[6].rgb);
  }
  const result = createC64SpriteGridImage(source, palette, options);
  assert.equal(result.pixels.width, 48);
  assert.equal(result.pixels.height, 42);
  assert.equal(result.sprites.length, 4);
  for (let cell = 0; cell < 4; cell += 1) {
    const sprite = result.sprites[cell];
    assert.equal(sprite.index, cell);
    assert.equal(sprite.column, cell % 2);
    assert.equal(sprite.row, Math.floor(cell / 2));
    assert.equal(sprite.colorIndex, options.spriteColorIndices[cell]);
    assert.equal(sprite.multicolor, true);
    assert.equal(sprite.data.length, 64);
    assert.equal(sprite.data[0], 0x1b);
    assert.equal(sprite.data[62], 0x03);
    assert.equal(sprite.data[63], 0);
    assert.deepEqual(pixel(result.pixels, sprite.column * 24 + 4, sprite.row * 21),
      [...palette[options.spriteColorIndices[cell]].rgb, 255]);
  }
});

test('multicolor fitting forces both halves to one color without leaking colors from adjacent sprites', () => {
  const options = settings({ columns: 2, spriteColorIndices: [2, 7, 2, 2, 2, 2, 2, 2] });
  const source = image(options);
  setPixel(source, 0, 0, palette[2].rgb);
  setPixel(source, 1, 0, palette[1].rgb);
  for (let x = 24; x < 48; x += 1) setPixel(source, x, 0, palette[7].rgb);
  const result = createC64SpriteGridImage(source, palette, options);
  assert.deepEqual(pixel(result.pixels, 0, 0), pixel(result.pixels, 1, 0));
  assert.ok([0, 5, 2, 6].some(index =>
    pixel(result.pixels, 0, 0).slice(0, 3).every((value, channel) => value === palette[index].rgb[channel])));
  assert.equal(result.sprites[1].data[0], 0xaa);
  assert.deepEqual(pixel(result.pixels, 24, 0), [...palette[7].rgb, 255]);
});

test('hires overlays resolve either half of a multicolor pair and occupy front-priority hardware slots', () => {
  const options = settings({ columns: 2, rows: 2, overlay: true,
    overlayColorIndices: [1, 7, 8, 3, 1, 1, 1, 1] });
  const source = image(options);
  for (let cell = 0; cell < 4; cell += 1) {
    const x = cell % 2 * 24;
    const y = Math.floor(cell / 2) * 21;
    for (const [offset, color] of [options.overlayColorIndices[cell], 2, 2, options.overlayColorIndices[cell]].entries()) {
      setPixel(source, x + offset, y, palette[color].rgb);
    }
  }
  const result = createC64SpriteGridImage(source, palette, options);
  assert.equal(result.sprites.length, 8);
  for (let cell = 0; cell < 4; cell += 1) {
    const front = result.sprites[cell];
    const back = result.sprites[cell + 4];
    const x = cell % 2 * 24;
    const y = Math.floor(cell / 2) * 21;
    assert.equal(front.index, cell);
    assert.equal(front.multicolor, false);
    assert.equal(front.colorIndex, options.overlayColorIndices[cell]);
    assert.equal(front.data[0], 0x90);
    assert.equal(back.index, cell + 4);
    assert.equal(back.multicolor, true);
    assert.equal(back.data[0], 0xa0);
    assert.deepEqual(pixel(result.multicolorPixels, x, y), [...palette[2].rgb, 255]);
    assert.deepEqual(pixel(result.overlayPixels, x, y), [...palette[options.overlayColorIndices[cell]].rgb, 255]);
    assert.deepEqual(pixel(result.overlayPixels, x + 1, y), [0, 0, 0, 0]);
    assert.deepEqual(pixel(result.pixels, x, y), [...palette[options.overlayColorIndices[cell]].rgb, 255]);
    assert.deepEqual(pixel(result.pixels, x + 1, y), [...palette[2].rgb, 255]);
  }
});

test('transparent source uses selected background and partial alpha composites in linear light', () => {
  const options = settings({ backgroundColorIndex: 3, overlay: true });
  const transparent = createC64SpriteGridImage(image(options, [255, 255, 255, 0]), palette, options);
  assert.ok(transparent.sprites.every(sprite => sprite.data.every(value => value === 0)));
  assert.deepEqual(pixel(transparent.pixels, 0, 0), [...palette[3].rgb, 255]);
  const partialOptions = settings({ multicolorIndices: [15, 1], spriteColorIndices: Array(8).fill(12) });
  const partial = createC64SpriteGridImage(image(partialOptions, [255, 255, 255, 128]), palette, partialOptions);
  assert.equal(partial.sprites[0].data[0], 0x55);
  assert.deepEqual(pixel(partial.pixels, 0, 0), [...palette[15].rgb, 255]);
});

test('ordered dithering mixes legal pair colors while preserving exact color matches', () => {
  const options = settings({ multicolorIndices: [1, 0], spriteColorIndices: Array(8).fill(0) });
  const source = image(options, [170, 170, 170, 255]);
  const flat = createC64SpriteGridImage(source, palette, options);
  const dithered = createC64SpriteGridImage(source, palette, options, 1);
  assert.ok(flat.sprites[0].data.slice(0, 63).every(value => value === 0x55));
  assert.ok(dithered.sprites[0].data.slice(0, 63).some(value => value !== 0x55));
  for (let y = 0; y < 21; y += 1) {
    for (let x = 0; x < 24; x += 2) {
      assert.deepEqual(pixel(dithered.pixels, x, y), pixel(dithered.pixels, x + 1, y));
    }
  }
  const exact = createC64SpriteGridImage(image(options, [255, 255, 255, 255]), palette, options, 1);
  assert.ok(exact.sprites[0].data.slice(0, 63).every(value => value === 0x55));
});

test('float strength maps preserve different layer dithering strengths across adjacent sprite cells', () => {
  const options = settings({ columns: 2, multicolorIndices: [1, 0], spriteColorIndices: Array(8).fill(0) });
  const source = image(options, [170, 170, 170, 255]);
  for (const FloatArray of [Float32Array, Float64Array]) {
    const strengths = new FloatArray(source.width * source.height);
    for (let y = 0; y < source.height; y += 1) strengths.fill(1, y * source.width + 24, (y + 1) * source.width);
    const result = createC64SpriteGridImage(source, palette, options, strengths);
    assert.ok(result.sprites[0].data.slice(0, 63).every(value => value === 0x55));
    assert.ok(result.sprites[1].data.slice(0, 63).some(value => value !== 0x55));
  }
  for (const strengths of [new Float32Array(1), new Float32Array(source.width * source.height).fill(-1),
    new Float64Array(source.width * source.height).fill(NaN), new Uint8Array(source.width * source.height)]) {
    assert.throws(() => createC64SpriteGridImage(source, palette, options, strengths), /matching float strength map/);
  }
});

test('supports eight-sprite rows and columns and rejects grids beyond the hardware budget', () => {
  for (const [columns, rows, overlay] of [[1, 8, false], [8, 1, false], [2, 4, false], [1, 4, true], [4, 1, true]]) {
    const options = settings({ columns, rows, overlay });
    const result = createC64SpriteGridImage(image(options), palette, options);
    assert.equal(result.sprites.length, 8);
    assert.equal(result.pixels.width, columns * 24);
    assert.equal(result.pixels.height, rows * 21);
  }
  for (const overrides of [{ columns: 3, rows: 3 }, { columns: 2, rows: 3, overlay: true },
    { columns: 0 }, { rows: -1 }, { rows: 1.5 }, { overlay: 1 }]) {
    const options = settings(overrides);
    assert.throws(() => createC64SpriteGridImage(null, palette, options), /at most eight hardware sprites/);
  }
});

test('rejects invalid palette settings, source sizes, and dither strengths', () => {
  const options = settings();
  for (const overrides of [{ backgroundColorIndex: 16 }, { multicolorIndices: [1] },
    { spriteColorIndices: Array(8).fill(-1) }, { overlayColorIndices: [1] }]) {
    assert.throws(() => createC64SpriteGridImage(image(options), palette, settings(overrides)), /background, two shared colors/);
  }
  assert.throws(() => createC64SpriteGridImage(new ImageData(12, 21), palette, options), /24 × 21 source image/);
  assert.throws(() => createC64SpriteGridImage(image(options), palette.slice(0, 15), options), /indexed 16-color/);
  for (const dither of [-1, 2, NaN, '1']) {
    assert.throws(() => createC64SpriteGridImage(image(options), palette, options, dither), /between 0 and 1/);
  }
});
