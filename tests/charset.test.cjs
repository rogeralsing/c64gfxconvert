const assert = require('node:assert/strict');
const test = require('node:test');
const { ImageData, palette, rgbToOklab, createContext, setPixel } = require('./fixtures/sprite-images.cjs');

const { createC64CharsetImage } = createContext(['charset.js']);
const settings = { backgroundColorIndex: 0, multicolorIndices: [5, 6] };
function image(rgba = [0, 0, 0, 255]) {
  const source = new ImageData(320, 200);
  for (let offset = 0; offset < source.data.length; offset += 4) source.data.set(rgba, offset);
  return source;
}
function drawCell(source, cell, glyph, attribute, options = settings, colors = palette) {
  const originX = cell % 40 * 8;
  const originY = Math.floor(cell / 40) * 8;
  for (let y = 0; y < 8; y += 1) {
    for (let x = 0; x < 8; x += 1) {
      let index = options.backgroundColorIndex;
      if (attribute & 8) {
        const code = Math.floor(glyph[y] / 2 ** (6 - Math.floor(x / 2) * 2)) % 4;
        index = [options.backgroundColorIndex, ...options.multicolorIndices, attribute & 7][code];
      } else if (glyph[y] & (128 >> x)) index = attribute;
      setPixel(source, originX + x, originY + y, colors[index].rgb);
    }
  }
}
function decode(result, colors = palette) {
  const output = image();
  for (let cell = 0; cell < 1000; cell += 1) {
    const glyph = result.charset.subarray(result.screen[cell] * 8, result.screen[cell] * 8 + 8);
    drawCell(output, cell, glyph, result.colorRam[cell], result, colors);
  }
  return output;
}

test('mixed hires and multicolor cells share glyph bytes while retaining independent cell colors and mode', () => {
  const source = image();
  const glyph = [0x1b, 0x6c, 0xb1, 0xc6, 0x1b, 0x6c, 0xb1, 0xc6];
  drawCell(source, 0, glyph, 7);
  drawCell(source, 1, glyph, 3);
  drawCell(source, 2, glyph, 10);
  const result = createC64CharsetImage(source, palette, settings);
  assert.deepEqual(result.pixels.data, source.data);
  assert.deepEqual(result.pixels.data, decode(result).data);
  assert.equal(result.colorRam[0], 7);
  assert.equal(result.colorRam[1], 3);
  assert.equal(result.colorRam[2], 10);
  assert.equal(result.screen[0], result.screen[1]);
  assert.equal(result.screen[1], result.screen[2]);
  assert.equal(result.characterCount, 2);
  assert.equal(result.unrestrictedCharacterCount, 2);
  assert.equal(result.approximatedCellCount, 0);
  assert.deepEqual(Array.from(result.charset.subarray(result.screen[0] * 8, result.screen[0] * 8 + 8)), glyph);
  assert.ok(result.charset.subarray(result.characterCount * 8).every(value => value === 0));
});

test('multicolor characters use shared colors above seven and three-bit individual foregrounds', () => {
  const options = { backgroundColorIndex: 13, multicolorIndices: [15, 14] };
  const source = image([...palette[13].rgb, 255]);
  drawCell(source, 0, Array(8).fill(0x1b), 10, options);
  const result = createC64CharsetImage(source, palette, options);
  assert.deepEqual(result.pixels.data, source.data);
  assert.equal(result.colorRam[0], 10);
  assert.deepEqual(Array.from(result.charset.subarray(result.screen[0] * 8, result.screen[0] * 8 + 8)), Array(8).fill(0x1b));
  assert.ok(result.colorRam.every(attribute => attribute < 16));
});

test('near blue tiles share one placement index with independent multicolor foregrounds below the character limit', () => {
  const options = { backgroundColorIndex: 0, multicolorIndices: [14, 6] };
  const source = image();
  const first = Array(8).fill(0x1b);
  const second = [...first];
  second[0] = 0x2b;
  drawCell(source, 0, first, 13, options);
  drawCell(source, 1, second, 15, options);
  const result = createC64CharsetImage(source, palette, options);
  assert.equal(result.unrestrictedCharacterCount, 3);
  assert.equal(result.characterCount, 2);
  assert.equal(result.screen[0], result.screen[1]);
  assert.equal(result.colorRam[0], 13);
  assert.equal(result.colorRam[1], 15);
  assert.equal(result.similarityMergedCellCount, 1);
  assert.deepEqual(result.pixels.data, decode(result).data);
  const exact = createC64CharsetImage(source, palette, { ...options, similarityThreshold: 0 });
  assert.equal(exact.characterCount, 3);
  assert.notEqual(exact.screen[0], exact.screen[1]);
  assert.deepEqual(exact.pixels.data, source.data);
});

test('default similarity protects sharp details while maximum similarity can merge a one-pixel variation', () => {
  const source = image();
  const first = Array(8).fill(0x55);
  const second = [...first];
  second[0] = 0x54;
  drawCell(source, 0, first, 1);
  drawCell(source, 1, second, 1);
  const conservative = createC64CharsetImage(source, palette, settings);
  assert.notEqual(conservative.screen[0], conservative.screen[1]);
  assert.deepEqual(conservative.pixels.data, source.data);
  const strong = createC64CharsetImage(source, palette, { ...settings, similarityThreshold: 100 });
  assert.equal(strong.screen[0], strong.screen[1]);
  assert.equal(strong.characterCount, 2);
  assert.deepEqual(strong.pixels.data, decode(strong).data);
  const edges = image();
  drawCell(edges, 0, first, 1);
  drawCell(edges, 1, [0, 0, ...first.slice(2)], 1);
  const distinctEdges = createC64CharsetImage(edges, palette, { ...settings, similarityThreshold: 100 });
  assert.notEqual(distinctEdges.screen[0], distinctEdges.screen[1]);
  assert.deepEqual(distinctEdges.pixels.data, edges.data);
});

test('perceptual fitness merges close blue shades in hires while retaining multicolor where four wide colors fit better', () => {
  const options = { backgroundColorIndex: 0, multicolorIndices: [6, 14] };
  const source = image();
  for (let y = 0; y < 8; y += 1) {
    for (let x = 1; x < 8; x += 2) setPixel(source, x, y, y & 1 ? [45, 40, 205] : palette[6].rgb);
  }
  drawCell(source, 1, Array(8).fill(0x1b), 13, options);
  const result = createC64CharsetImage(source, palette, options);
  assert.equal(result.colorRam[0], 6);
  assert.equal(result.colorRam[1], 13);
  assert.equal(result.hiresCellCount, 999);
  assert.equal(result.multicolorCellCount, 1);
  for (let y = 0; y < 8; y += 1) {
    assert.deepEqual(Array.from(result.pixels.data.subarray((y * 320 + 1) * 4, (y * 320 + 1) * 4 + 4)),
      [...palette[6].rgb, 255]);
  }
  assert.deepEqual(result.pixels.data, decode(result).data);
});

test('overfull character screens reuse at most 256 stored glyphs and preview the actual hardware output', () => {
  const source = image();
  let random = 0x12345678;
  for (let cell = 0; cell < 1000; cell += 1) {
    const glyph = Array.from({ length: 8 }, () => {
      random ^= random << 13; random ^= random >>> 17; random ^= random << 5;
      return random & 255;
    });
    drawCell(source, cell, glyph, (cell % 2 ? 8 : 0) + cell % 7 + 1);
  }
  const result = createC64CharsetImage(source, palette, settings);
  assert.equal(result.charset.length, 2048);
  assert.equal(result.screen.length, 1000);
  assert.equal(result.colorRam.length, 1000);
  assert.equal(result.characterCount, 256);
  assert.equal(result.unrestrictedCharacterCount, 1000);
  assert.ok(result.approximatedCellCount >= 744);
  assert.ok(result.screen.every(index => index < result.characterCount));
  assert.deepEqual(result.pixels.data, decode(result).data);
  assert.notDeepEqual(result.pixels.data, source.data);
  const labCache = new Map();
  function lab(data, offset) {
    const key = data[offset] | data[offset + 1] << 8 | data[offset + 2] << 16;
    if (!labCache.has(key)) labCache.set(key, Object.values(rgbToOklab(data[offset], data[offset + 1], data[offset + 2])));
    return labCache.get(key);
  }
  let error = 0;
  for (let offset = 0; offset < source.data.length; offset += 4) {
    const target = lab(source.data, offset);
    const actual = lab(result.pixels.data, offset);
    error += target.reduce((sum, value, channel) => sum + (value - actual[channel]) ** 2, 0);
  }
  // Previous byte-Hamming selection scored 0.10343527 on this deterministic colored fixture.
  assert.ok(error / 64000 < 0.09, `Mean Oklab error: ${error / 64000}`);
  const repeat = createC64CharsetImage(source, palette, settings);
  assert.deepEqual(result.charset, repeat.charset);
  assert.deepEqual(result.screen, repeat.screen);
  assert.deepEqual(result.colorRam, repeat.colorRam);
});

test('transparent source uses selected background and partial alpha composites in linear light', () => {
  const options = { backgroundColorIndex: 3, multicolorIndices: [5, 6] };
  const empty = createC64CharsetImage(image([255, 255, 255, 0]), palette, options);
  assert.equal(empty.characterCount, 1);
  assert.ok(empty.charset.every(value => value === 0));
  assert.ok(empty.screen.every(value => value === 0));
  assert.ok(empty.colorRam.every(value => value === 0));
  assert.deepEqual(Array.from(empty.pixels.data.subarray(0, 4)), [...palette[3].rgb, 255]);
  const partial = createC64CharsetImage(image([255, 255, 255, 128]), palette,
    { backgroundColorIndex: 0, multicolorIndices: [15, 12] });
  assert.deepEqual(Array.from(partial.pixels.data.subarray(0, 4)), [...palette[15].rgb, 255]);
});

test('per-pixel float dither maps preserve separate strengths and exact colors remain exact', () => {
  const colors = palette.map(color => ({ ...color, rgb: color.index === 1 ? [255, 255, 255] : [0, 0, 0] }));
  const options = { backgroundColorIndex: 0, multicolorIndices: [0, 1] };
  const source = image([170, 170, 170, 255]);
  const strengths = new Float32Array(320 * 200);
  for (let y = 0; y < 200; y += 1) strengths.fill(1, y * 320 + 160, (y + 1) * 320);
  const result = createC64CharsetImage(source, colors, options, strengths);
  let rightBlack = 0;
  for (let y = 0; y < 200; y += 1) {
    for (let x = 0; x < 320; x += 1) {
      const value = result.pixels.data[(y * 320 + x) * 4];
      if (x < 160) assert.equal(value, 255);
      else if (value === 0) rightBlack += 1;
    }
  }
  assert.ok(rightBlack > 0);
  assert.deepEqual(result.pixels.data, decode(result, colors).data);
  const exact = createC64CharsetImage(image([255, 255, 255, 255]), colors, options, 1);
  assert.ok(exact.pixels.data.every(value => value === 255));
});

test('overfull dictionaries preserve retained ordered dither glyphs instead of flattening gray cells', () => {
  const colors = palette.map(color => ({ ...color, rgb: color.index === 1 ? [255, 255, 255] : [0, 0, 0] }));
  const options = { backgroundColorIndex: 0, multicolorIndices: [0, 1], similarityThreshold: 0 };
  const source = image([255, 255, 255, 255]);
  let random = 0x12345678;
  for (let cell = 0; cell < 500; cell += 1) {
    const glyph = Array.from({ length: 8 }, () => {
      random ^= random << 13; random ^= random >>> 17; random ^= random << 5;
      return random & 255;
    });
    drawCell(source, cell, glyph, 1, options, colors);
  }
  for (let cell = 500; cell < 800; cell += 1) {
    for (let y = 0; y < 8; y += 1) {
      for (let x = 0; x < 8; x += 1) {
        setPixel(source, cell % 40 * 8 + x, Math.floor(cell / 40) * 8 + y, [170, 170, 170]);
      }
    }
  }
  const result = createC64CharsetImage(source, colors, options, 1);
  assert.equal(result.unrestrictedCharacterCount, 502);
  assert.equal(result.characterCount, 256);
  for (let cell = 500; cell < 800; cell += 1) {
    assert.equal(result.colorRam[cell], 1);
    assert.deepEqual(Array.from(result.charset.subarray(result.screen[cell] * 8, result.screen[cell] * 8 + 8)),
      [0x55, 0xff, 0x55, 0xff, 0x55, 0xff, 0x55, 0xff]);
  }
  assert.deepEqual(result.pixels.data, decode(result, colors).data);
});

test('rejects invalid source dimensions, palette settings, and dither strengths', () => {
  const source = image();
  assert.throws(() => createC64CharsetImage(new ImageData(160, 200), palette, settings), /320 × 200 source/);
  assert.throws(() => createC64CharsetImage(source, palette.slice(0, 15), settings), /indexed 16-color/);
  for (const options of [{ backgroundColorIndex: 16, multicolorIndices: [1, 2] },
    { backgroundColorIndex: 0, multicolorIndices: [1] }, { backgroundColorIndex: 0, multicolorIndices: [1, -1] }]) {
    assert.throws(() => createC64CharsetImage(source, palette, options), /background and two shared/);
  }
  for (const similarityThreshold of [-1, 101, 35.5, NaN, '35']) {
    assert.throws(() => createC64CharsetImage(source, palette, { ...settings, similarityThreshold }), /tile similarity/);
  }
  for (const dither of [-1, NaN, '1', new Float32Array(1), new Float64Array(320 * 200).fill(2)]) {
    assert.throws(() => createC64CharsetImage(source, palette, settings, dither), /between 0 and 1/);
  }
});
