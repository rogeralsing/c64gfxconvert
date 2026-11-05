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
  [0, 0, 0], [255, 255, 255], [150, 40, 46], [91, 214, 206],
  [159, 45, 173], [65, 185, 54], [39, 36, 196], [239, 243, 71],
  [159, 72, 21], [94, 53, 0], [218, 95, 102], [71, 71, 71],
  [120, 120, 120], [145, 255, 132], [104, 100, 255], [174, 174, 174]
].map((rgb, index) => ({ index, rgb }));
const bands = [[0], [6, 9], [2, 11], [4, 8], [14, 12], [5, 10], [3, 15], [13, 7], [1]]
  .map(indices => {
    const colors = indices.map(index => ({ color: palette[index], lab: rgbToOklab(...palette[index].rgb) }));
    return { colors, lightness: colors.reduce((sum, entry) => sum + entry.lab.lightness, 0) / colors.length };
  });
const context = vm.createContext({ ImageData, Uint8Array, Uint8ClampedArray, rgbToOklab });
vm.runInContext(fs.readFileSync(path.join(__dirname, '../ifli.js'), 'utf8'), context);
const { buildIfliVirtualPalette, mapToIfliVirtualPalette, resolveVirtualPaletteColors, splitIfliColumns } = context;
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
  const grays = [0, 1, 48, 79, 120, 174, 255];
  const mapped = mapToIfliVirtualPalette(source(grays.map(gray => [gray, gray, gray])), virtualPalette, bands);
  for (const [pixel, gray] of grays.entries()) {
    const actual = byIndex.get(mapped.virtualIndices[pixel]);
    if (gray === 48) {
      const targetLightness = rgbToOklab(gray, gray, gray).lightness;
      const actualLightness = rgbToOklab(...actual.rgb).lightness;
      assert.ok(Math.abs(actualLightness - targetLightness) < 0.08,
        `dark gray 48 should not become a medium brown: ${actualLightness}`);
    } else {
      const expected = gray <= 1 ? 0 : gray === 79 ? 71 : gray;
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

test('virtual brightness caps clamp both ends of the palette image even with dithering', () => {
  const pixels = source(Array.from({ length: 256 }, (_, gray) => [gray, gray, gray]));
  const before = new Uint8ClampedArray(pixels.data);
  for (const limits of [{ minLevel: 1, maxLevel: 15 }, { minLevel: 4, maxLevel: 11 }]) {
    for (const dither of [0, 0.4, 1]) {
      const mapped = mapToIfliVirtualPalette(pixels, virtualPalette, bands, dither, limits);
      const rows = Array.from(mapped.virtualIndices, index => bucket(byIndex.get(index)));
      assert.equal(rows[0], limits.minLevel, 'black must clamp to the lowest allowed virtual row');
      assert.equal(rows[255], limits.maxLevel, 'white must clamp to the highest allowed virtual row');
      assert.ok(rows.every(row => row >= limits.minLevel && row <= limits.maxLevel), `dither ${dither}`);
      for (let pixel = 0; pixel < rows.length; pixel += 1) {
        const selected = byIndex.get(mapped.virtualIndices[pixel]);
        assert.deepEqual(Array.from(mapped.pixels.data.subarray(pixel * 4, pixel * 4 + 3)),
          Array.from(selected.rgb, Math.round), 'display must retain the selected component pair');
      }
    }
  }
  assert.deepEqual(pixels.data, before, 'palette caps must not change the source');
});

test('a single selected virtual row stays exact across all 17 levels at full dither', () => {
  const pixels = source(palette.map(color => color.rgb));
  for (let level = 0; level <= 16; level += 1) {
    const mapped = mapToIfliVirtualPalette(pixels, virtualPalette, bands, 1, { minLevel: level, maxLevel: level });
    for (const index of mapped.virtualIndices) {
      const selected = byIndex.get(index);
      assert.equal(bucket(selected), level);
      if (level === 1) {
        assert.equal(selected.colorIndices[0], 0);
        assert.ok([6, 9].includes(selected.colorIndices[1]), 'row 1 is black mixed with blue or brown');
      }
      if (level === 2) assert.ok(selected.colorIndices.every(color => [6, 9].includes(color)), 'row 2 uses blue/brown');
    }
  }
});

test('each excluded virtual color stays out of the mapping at every dither strength', () => {
  const pixels = source(Array.from({ length: 4 }, () => virtualPalette.map(color => color.rgb)).flat(), virtualPalette.length);
  const before = new Uint8ClampedArray(pixels.data);
  const metadata = JSON.stringify(virtualPalette);
  for (const color of virtualPalette) {
    for (const dither of [0, 0.4, 1]) {
      const mapped = mapToIfliVirtualPalette(pixels, virtualPalette, bands, dither, { excludedIndices: [color.index] });
      assert.ok(!mapped.virtualIndices.includes(color.index), `excluded color ${color.index}, dither ${dither}`);
      assert.ok(Array.from(mapped.virtualIndices).every(index => byIndex.has(index)), 'replacement colors must retain valid pair indices');
    }
  }
  assert.deepEqual(pixels.data, before, 'exclusions must not change the source');
  assert.equal(JSON.stringify(virtualPalette), metadata, 'exclusions must not alter the shared palette');
});

test('excluded brightness rows fall back to an enabled row inside the selected caps', () => {
  const pixels = source([[0, 0, 0], [20, 20, 20], [255, 255, 255]]);
  const excludedIndices = virtualPalette.filter(color => bucket(color) === 1).map(color => color.index);
  for (const dither of [0, 0.4, 1]) {
    const mapped = mapToIfliVirtualPalette(pixels, virtualPalette, bands, dither,
      { minLevel: 1, maxLevel: 2, excludedIndices });
    assert.ok(Array.from(mapped.virtualIndices).every(index => bucket(byIndex.get(index)) === 2));
  }
});

test('a sole enabled virtual color maps every opaque pixel while preserving alpha and transparent RGB', () => {
  const gray = virtualPalette.find(color => color.colorIndices.every(index => index === 12));
  const excludedIndices = virtualPalette.filter(color => color.index !== gray.index).map(color => color.index);
  const pixels = source([[11, 22, 33, 0], [0, 0, 0, 1], [255, 255, 255, 127], [255, 0, 0, 255]]);
  const mapped = mapToIfliVirtualPalette(pixels, virtualPalette, bands, 1, { excludedIndices });
  assert.deepEqual(Array.from(mapped.virtualIndices), [255, gray.index, gray.index, gray.index]);
  assert.deepEqual(Array.from(mapped.pixels.data), [11, 22, 33, 0, 120, 120, 120, 1, 120, 120, 120, 127, 120, 120, 120, 255]);
  assert.throws(() => mapToIfliVirtualPalette(pixels, virtualPalette, bands, 1,
    { minLevel: 0, maxLevel: 7, excludedIndices }), /enabled virtual color.*brightness range/);
  assert.throws(() => mapToIfliVirtualPalette(pixels, virtualPalette, bands, 1,
    { excludedIndices: virtualPalette.map(color => color.index) }), /enabled virtual color.*brightness range/);
});

test('virtual brightness caps reject invalid or inverted row bounds', () => {
  const pixels = source([[128, 128, 128]]);
  for (const limits of [
    { minLevel: -1 }, { maxLevel: 17 }, { minLevel: 5, maxLevel: 4 },
    { minLevel: 0.5 }, { maxLevel: NaN }
  ]) {
    assert.throws(() => mapToIfliVirtualPalette(pixels, virtualPalette, bands, 1, limits), /brightness limits/);
  }
});

test('virtual lines and checkers resolve retained pairs before splitting exact IFLI columns', () => {
  const width = virtualPalette.length * 2;
  const height = 4;
  const pixels = source(Array.from({ length: width * height }, () => [17, 33, 66]), width);
  const indices = new Uint8Array(width * height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      indices[y * width + x] = virtualPalette[(Math.floor(x / 2) + x % 2) % virtualPalette.length].index;
    }
  }
  for (const pattern of ['lines', 'checkers']) {
    const resolved = resolveVirtualPaletteColors({ pixels, virtualIndices: indices }, virtualPalette, palette, pattern);
    assert.equal(resolved.width, width);
    assert.equal(resolved.height, height);
    const frames = splitIfliColumns(resolved);
    assert.equal(frames.length, 2);
    for (let phase = 0; phase < 2; phase += 1) {
      assert.equal(frames[phase].width, width / 2);
      assert.equal(frames[phase].height, height);
      for (let y = 0; y < height; y += 1) {
        for (let x = 0; x < width / 2; x += 1) {
          const pair = virtualPalette[(x + phase) % virtualPalette.length].colorIndices;
          const component = pattern === 'lines' ? y % 2 : (y % 2) ^ phase;
          const expected = [...palette[pair[component]].rgb, 255];
          const offset = (y * width / 2 + x) * 4;
          assert.deepEqual(Array.from(frames[phase].data.subarray(offset, offset + 4)), expected,
            `${pattern}, frame ${phase}, row ${y}, column ${x}`);
        }
      }
    }
  }
});

test('virtual patterns preserve partial alpha and transparent or sentinel RGBA without changing their source', () => {
  const pair = virtualPalette.find(color => color.colorIndices[0] !== color.colorIndices[1]);
  const [first, second] = pair.colorIndices.map(index => palette[index].rgb);
  const pixels = source([
    [11, 22, 33, 0], [7, 8, 9, 127], [21, 22, 23, 255], [7, 8, 9, 1],
    [7, 8, 9, 31], [51, 52, 53, 0], [7, 8, 9, 255], [41, 42, 43, 61]
  ], 4);
  const indices = Uint8Array.from([254, pair.index, 255, pair.index, pair.index, 254, pair.index, 255]);
  const beforePixels = new Uint8ClampedArray(pixels.data);
  const beforeIndices = new Uint8Array(indices);
  for (const pattern of ['lines', 'checkers']) {
    const resolved = resolveVirtualPaletteColors({ pixels, virtualIndices: indices }, virtualPalette, palette, pattern);
    const frames = splitIfliColumns(resolved);
    const odd = pattern === 'lines' ? first : second;
    assert.deepEqual(Array.from(frames[0].data), [11, 22, 33, 0, 21, 22, 23, 255, ...second, 31, ...second, 255]);
    assert.deepEqual(Array.from(frames[1].data), [...odd, 127, ...odd, 1, 51, 52, 53, 0, 41, 42, 43, 61]);
  }
  assert.deepEqual(pixels.data, beforePixels);
  assert.deepEqual(indices, beforeIndices);
});

test('IFLI column splitting preserves real source colors without virtual color mapping or averaging', () => {
  const pixels = source([
    [11, 22, 33, 0], [39, 36, 196], [150, 40, 46, 127], [255, 255, 255],
    [94, 53, 0], [71, 71, 71, 1], [145, 255, 132], [120, 120, 120, 61]
  ], 4);
  const before = new Uint8ClampedArray(pixels.data);
  const frames = splitIfliColumns(pixels);
  assert.deepEqual(Array.from(frames[0].data), [11, 22, 33, 0, 150, 40, 46, 127, 94, 53, 0, 255, 145, 255, 132, 255]);
  assert.deepEqual(Array.from(frames[1].data), [39, 36, 196, 255, 255, 255, 255, 255, 71, 71, 71, 1, 120, 120, 120, 61]);
  assert.deepEqual(pixels.data, before);
});

test('IFLI splitting and virtual resolution reject invalid geometry, indices, pairs, and patterns', () => {
  const pixels = source([[7, 8, 9], [7, 8, 9]], 2);
  const mapping = { pixels, virtualIndices: new Uint8Array(2) };
  for (const width of [0, 1, 3, 2.5]) {
    assert.throws(() => splitIfliColumns({ ...pixels, width }),
      /positive even width/);
  }
  assert.throws(() => splitIfliColumns({ ...pixels, data: new Uint8ClampedArray(4) }), /matching pixels/);
  assert.throws(() => resolveVirtualPaletteColors({ ...mapping, virtualIndices: new Uint8Array(1) }, virtualPalette, palette),
    /matching pixels and indices/);
  assert.throws(() => resolveVirtualPaletteColors({ ...mapping, virtualIndices: Uint8Array.from([254, 254]) }, virtualPalette, palette),
    /valid virtual pairs/);
  assert.throws(() => resolveVirtualPaletteColors(mapping, virtualPalette, palette, 'invalid'), /pattern/);
});
