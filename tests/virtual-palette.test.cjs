const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class ImageData {
  constructor(data, width, height) {
    if (typeof data === 'number') {
      this.width = data;
      this.height = width;
      this.data = new Uint8ClampedArray(data * width * 4);
    } else {
      this.data = data;
      this.width = width;
      this.height = height;
    }
  }
}

function linear(channel) {
  const value = channel / 255;
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}

function rgbToOklab(red, green, blue) {
  const [r, g, b] = [red, green, blue].map(linear);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return {
    lightness: 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
    a: 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
    b: 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
  };
}

const palette = [
  [0, 0, 0], [255, 255, 255], [141, 51, 61], [101, 191, 179],
  [142, 55, 162], [76, 165, 73], [51, 44, 173], [205, 209, 86],
  [143, 80, 27], [83, 61, 1], [189, 99, 109], [79, 79, 79],
  [118, 118, 118], [139, 233, 139], [108, 101, 230], [163, 163, 163]
].map((rgb, index) => ({ index, rgb }));
const bands = [[0], [6, 9], [2, 11], [4, 8], [14, 12], [5, 10], [3, 15], [13, 7], [1]]
  .map(indices => {
    const colors = indices.map(index => ({ color: palette[index], lab: rgbToOklab(...palette[index].rgb) }));
    return { colors, lightness: colors.reduce((sum, entry) => sum + entry.lab.lightness, 0) / colors.length };
  });
const context = vm.createContext({ ImageData, Uint8Array, Uint8ClampedArray, rgbToOklab });
vm.runInContext(fs.readFileSync(path.join(__dirname, '../ifli.js'), 'utf8'), context);
const { buildIfliVirtualPalette, mapToIfliVirtualPalette } = context;
const virtualPalette = buildIfliVirtualPalette(palette, bands);
const byIndex = new Map(virtualPalette.map(color => [color.index, color]));
const bucket = color => color.brightnessBands[0] + color.brightnessBands[1];

function source(colors, width = colors.length) {
  const pixels = new ImageData(width, colors.length / width);
  colors.forEach((color, index) => pixels.data.set([...color.slice(0, 3), color[3] ?? 255], index * 4));
  return pixels;
}

test('pink cannot mix with yellow or light green in either order', () => {
  for (const colors of [palette, [...palette].reverse()]) {
    const generated = buildIfliVirtualPalette(colors, bands);
    const pairs = new Set(generated.map(color => color.colorIndices.join('-')));
    for (const forbidden of ['7-10', '10-13']) {
      assert.equal(pairs.has(forbidden), false, `forbidden pair ${forbidden}`);
    }
    for (const allowed of ['7-7', '10-10', '13-13', '7-15', '10-15']) {
      assert.ok(pairs.has(allowed), `legal pair ${allowed} must remain available`);
    }
  }
});

test('neutral shadows use palette lightness instead of uniformly spaced row numbers', () => {
  const grays = [0, 1, 48, 79, 118, 163, 255];
  const mapped = mapToIfliVirtualPalette(source(grays.map(gray => [gray, gray, gray])), virtualPalette, bands);
  for (const [pixel, gray] of grays.entries()) {
    const actual = byIndex.get(mapped.virtualIndices[pixel]);
    if (gray === 48) {
      const targetLightness = rgbToOklab(gray, gray, gray).lightness;
      const actualLightness = rgbToOklab(...actual.rgb).lightness;
      assert.ok(Math.abs(actualLightness - targetLightness) < 0.08,
        `dark gray 48 should not become a medium brown: ${actualLightness}`);
    } else {
      const expected = gray <= 1 ? 0 : gray;
      assert.deepEqual(Array.from(actual.rgb), [expected, expected, expected], `gray ${gray}`);
    }
  }
});

test('a neutral ramp visits all 17 brightness rows without reversing them', () => {
  const grays = Array.from({ length: 256 }, (_, value) => [value, value, value]);
  const mapped = mapToIfliVirtualPalette(source(grays), virtualPalette, bands);
  const rows = Array.from(mapped.virtualIndices, index => bucket(byIndex.get(index)));
  for (let index = 1; index < rows.length; index += 1) {
    assert.ok(rows[index] >= rows[index - 1], `ramp reversed at gray ${index}`);
  }
  assert.deepEqual([...new Set(rows)], Array.from({ length: 17 }, (_, index) => index));
});

test('color choice minimizes chroma within its selected brightness row', () => {
  const colors = [[255, 0, 0], [0, 255, 0], [0, 0, 255], [80, 160, 180], [230, 180, 30], [140, 80, 210]];
  const mapped = mapToIfliVirtualPalette(source(colors), virtualPalette, bands);
  colors.forEach((rgb, pixel) => {
    const target = rgbToOklab(...rgb);
    const selected = byIndex.get(mapped.virtualIndices[pixel]);
    const chromaError = color => {
      const lab = rgbToOklab(...color.rgb);
      return (target.a - lab.a) ** 2 + (target.b - lab.b) ** 2;
    };
    for (const candidate of virtualPalette.filter(color => bucket(color) === bucket(selected))) {
      assert.ok(chromaError(selected) <= chromaError(candidate) + 1e-12, `RGB ${rgb}`);
    }
  });
});

test('ordered dither fills the large black-to-dark-color gap from either nearest row', () => {
  for (const gray of [4, 16]) {
    const targetLightness = rgbToOklab(gray, gray, gray).lightness;
    const errors = [];
    for (const amount of [0, 0.4, 1]) {
      const tile = source(Array.from({ length: 16 }, () => [gray, gray, gray]), 4);
      const mapped = mapToIfliVirtualPalette(tile, virtualPalette, bands, amount);
      const chosen = Array.from(mapped.virtualIndices, index => byIndex.get(index));
      const rows = new Set(chosen.map(bucket));
      assert.ok([...rows].every(row => row === 0 || row === 1), `gray ${gray}, dither ${amount}`);
      if (amount === 0) assert.deepEqual([...rows], [gray === 4 ? 0 : 1]);
      if (amount === 1) assert.equal(rows.size, 2, `gray ${gray} should use both dark neighbors`);
      const averageLightness = chosen.reduce((sum, color) => sum + rgbToOklab(...color.rgb).lightness, 0) / chosen.length;
      errors.push(Math.abs(averageLightness - targetLightness));
    }
    assert.ok(errors[1] < errors[0], `partial dither should improve gray ${gray}`);
    assert.ok(errors[2] < errors[1], `full dither should improve gray ${gray}`);
    assert.ok(errors[2] < 0.012, `full dither should preserve dark lightness: gray ${gray}, error ${errors[2]}`);
  }
});

test('dither leaves black and white endpoints unchanged', () => {
  const tile = source(Array.from({ length: 16 }, (_, index) => index % 2 ? [255, 255, 255] : [0, 0, 0]), 4);
  for (const amount of [0, 0.4, 1]) {
    const mapped = mapToIfliVirtualPalette(tile, virtualPalette, bands, amount);
    assert.deepEqual(mapped.pixels.data, tile.data, `dither ${amount}`);
  }
});

test('alpha, transparent RGB, source pixels, and saved pair metadata remain intact', () => {
  const pixels = source([[19, 31, 47, 0], [200, 20, 40, 1], [30, 160, 90, 127], [244, 244, 244, 255]]);
  const before = new Uint8ClampedArray(pixels.data);
  const metadata = JSON.stringify(virtualPalette);
  const mapped = mapToIfliVirtualPalette(pixels, virtualPalette, bands, 0.75);
  assert.equal(mapped.virtualIndices[0], 255);
  assert.deepEqual(Array.from(mapped.pixels.data.subarray(0, 4)), [19, 31, 47, 0]);
  for (let pixel = 1; pixel < 4; pixel += 1) {
    assert.equal(mapped.pixels.data[pixel * 4 + 3], pixels.data[pixel * 4 + 3]);
    const selected = byIndex.get(mapped.virtualIndices[pixel]);
    assert.deepEqual(Array.from(mapped.pixels.data.subarray(pixel * 4, pixel * 4 + 3)), Array.from(selected.rgb, Math.round));
  }
  assert.deepEqual(pixels.data, before);
  assert.equal(JSON.stringify(virtualPalette), metadata);
});

test('invalid component bands and missing selected rows produce clear errors', () => {
  const invalid = virtualPalette.map((color, index) => index === 0 ? { ...color, brightnessBands: [0, 9] } : color);
  assert.throws(() => mapToIfliVirtualPalette(source([[0, 0, 0]]), invalid, bands), /brightness bands/);
  const missingWhite = virtualPalette.filter(color => bucket(color) !== 16);
  assert.throws(() => mapToIfliVirtualPalette(source([[255, 255, 255]]), missingWhite, bands), /brightness level 16/);
});
