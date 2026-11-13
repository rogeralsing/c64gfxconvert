const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const { createContext, ImageData, rgbToOklab } = require('./fixtures/sprite-images.cjs');

const runtime = createContext(['ifli.js', 'talent-palette.js', 'talent-neighbors.js', 'talent-mapping.js', 'palettes.js']);
const observations = vm.runInContext('TALENT_NEIGHBOR_DATA', runtime);

function image(colors, width = colors.length) {
  const source = new ImageData(width, colors.length / width);
  colors.forEach((rgb, index) => source.data.set([...rgb.slice(0, 3), rgb[3] ?? 255], index * 4));
  return source;
}

const limits = { minLightness: 0, maxLightness: 100 };
function palette(colors) {
  return colors.map((rgb, index) => ({ index, rgb, lightness: rgbToOklab(...rgb).lightness }));
}
const grays = palette([0, 64, 128, 192, 255].map(value => [value, value, value]));

test('each source pixel chooses its nearest Talent color independently of neighbors and scan order', () => {
  const colors = [[0, 0, 0], [255, 255, 255], [128, 128, 128]];
  const expected = [0, 4, 2];
  for (const width of [1, 3]) {
    const mapped = runtime.mapToTalentVirtualPalette(image(colors, width), grays, limits);
    assert.deepEqual(Array.from(mapped.virtualIndices), expected,
      'a neighboring black pixel must not prevent white or gray from selecting their exact virtual colors');
    assert.deepEqual(Array.from(mapped.pixels.data), colors.flatMap(rgb => [...rgb, 255]));
  }
  const reversed = runtime.mapToTalentVirtualPalette(image([...colors].reverse()), grays, limits);
  assert.deepEqual(Array.from(reversed.virtualIndices), [...expected].reverse());
});

test('Talent chooses brightness before hue, then retains hue choices at similar brightness', () => {
  const colors = palette([[50, 50, 50], [120, 80, 75], [80, 105, 140], [210, 210, 210]]);
  const source = image([[105, 85, 120], [200, 100, 100], [170, 170, 170], [0, 0, 170]]);
  const mapped = runtime.mapToTalentVirtualPalette(source, colors, limits);
  assert.deepEqual(Array.from(mapped.virtualIndices), [1, 2, 3, 0],
    'a closer hue must not move a source pixel to the wrong brightness row');
  assert.deepEqual(Array.from(mapped.pixels.data), [1, 2, 3, 0].flatMap(index => [...colors[index].rgb, 255]));

  const state = runtime.createC64PaletteState('peptoette-a', 'talent');
  const blue = state.virtualPalette.find(color => color.colorIndices.join('-') === '6-6');
  const brown = state.virtualPalette.find(color => color.colorIndices.join('-') === '9-9');
  const nearBlue = image([[48, 50, 140]]);
  const hueMatch = runtime.mapToTalentVirtualPalette(nearBlue, [brown, blue], limits);
  assert.equal(hueMatch.virtualIndices[0], blue.index,
    'blue and brown share a brightness row, so a blue source must retain its hue');
});

test('skin highlights retain intermediate Talent tones instead of collapsing to pink and yellow', () => {
  const state = runtime.createC64PaletteState('peptoette-a', 'talent');
  // Pixels sampled from the supplied face: cheek highlight, cheek shadow, and midtone.
  const samples = [[248, 152, 106], [228, 104, 54], [246, 118, 72]];
  const source = image(Array.from({ length: 24 * 8 }, (_, pixel) => samples[Math.floor(pixel % 24 / 8)]), 24);
  const mapped = runtime.mapToTalentVirtualPalette(source, state.virtualPalette, limits, 1);
  const pairs = new Set(Array.from(mapped.virtualIndices, index =>
    state.virtualPalette.find(color => color.index === index).colorIndices.join('-')));
  assert.ok(pairs.has('10-15'), 'pink + light gray must appear in the cheek shadow');
  assert.ok(pairs.has('7-15'), 'yellow + light gray must appear in the cheek highlight');
  assert.ok(pairs.size >= 4, 'brightness interpolation must retain intermediate tones across these skin samples');
});

test('Talent and Computed use the same brightness interpolation and ordered dither on equivalent rows', () => {
  const colors = palette(Array.from({ length: 17 }, (_, row) => {
    const gray = Math.min(row * 16, 255);
    return [gray, gray, gray];
  })).map((color, row) => ({ ...color, brightnessBands: [Math.floor(row / 2), Math.ceil(row / 2)] }));
  const bands = Array.from({ length: 9 }, () => ({}));
  const source = image(Array.from({ length: 64 }, (_, pixel) => [
    41 + pixel % 8 * 23, 41 + pixel % 8 * 23, 41 + pixel % 8 * 23, pixel === 17 ? 0 : pixel % 2 ? 127 : 255
  ]), 8);
  const settings = { ...limits, excludedIndices: [5, 9] };
  for (const amount of [0, 0.5, 1]) {
    const computed = runtime.mapToIfliVirtualPalette(source, colors, bands, amount,
      { excludedIndices: settings.excludedIndices });
    const talent = runtime.mapToTalentVirtualPalette(source, colors, settings, amount);
    assert.deepEqual(talent.virtualIndices, computed.virtualIndices, `dither ${amount}`);
    assert.deepEqual(talent.pixels.data, computed.pixels.data, `dither ${amount}`);
  }
});

test('flat fields contain one actual virtual color with no ordered or tiled dither', () => {
  const flat = image(Array.from({ length: 64 }, () => [95, 95, 95]), 8);
  const mapped = runtime.mapToTalentVirtualPalette(flat, grays, limits);
  assert.equal(new Set(mapped.virtualIndices).size, 1);
  const index = mapped.virtualIndices[0];
  assert.deepEqual(Array.from(mapped.pixels.data), Array.from({ length: 64 }, () => [...grays[index].rgb, 255]).flat());
});

test('transparent gaps and partial alpha do not affect independent color choices', () => {
  const source = image([[0, 0, 0, 127], [64, 64, 64], [19, 87, 123, 0], [192, 192, 192], [255, 255, 255]]);
  const before = new Uint8ClampedArray(source.data);
  const mapped = runtime.mapToTalentVirtualPalette(source, grays, limits);
  assert.deepEqual(Array.from(mapped.virtualIndices), [0, 1, 255, 3, 4]);
  assert.equal(mapped.pixels.data[3], 127);
  assert.deepEqual(Array.from(mapped.pixels.data.slice(8, 12)), [19, 87, 123, 0]);
  assert.deepEqual(source.data, before);
});

test('Talent mapping writes actual palette RGB values and preserves source pixels', () => {
  for (const paletteId of ['colodore', 'pepto', 'peptoette-a']) {
    const state = runtime.createC64PaletteState(paletteId, 'talent');
    const source = image(Array.from(state.virtualPalette, (color, index) => [...color.rgb, index % 2 ? 127 : 255]));
    const before = new Uint8ClampedArray(source.data);
    const mapped = runtime.mapToTalentVirtualPalette(source, state.virtualPalette, limits, 1);
    const byIndex = new Map(state.virtualPalette.map(color => [color.index, color]));
    for (let pixel = 0; pixel < mapped.virtualIndices.length; pixel += 1) {
      const selected = byIndex.get(mapped.virtualIndices[pixel]);
      assert.ok(selected, 'mapping must select an enabled Talent color');
      assert.deepEqual(Array.from(mapped.pixels.data.slice(pixel * 4, pixel * 4 + 3)), Array.from(selected.rgb));
      assert.equal(mapped.pixels.data[pixel * 4 + 3], before[pixel * 4 + 3]);
    }
    assert.deepEqual(source.data, before);
  }
});

test('black-blue, black-gray, and black-purple are actual Talent mixtures before physical checker rendering', () => {
  const state = runtime.createC64PaletteState('peptoette-a', 'talent');
  for (const [component, rgb] of [[6, [35, 35, 95]], [11, [55, 55, 55]], [4, [90, 47, 98]]]) {
    const pair = state.virtualPalette.find(color => color.colorIndices.join('-') === `0-${component}`);
    const source = image(Array.from({ length: 16 }, () => rgb), 4);
    const mapped = runtime.mapToTalentVirtualPalette(source, state.virtualPalette);
    assert.deepEqual(Array.from(mapped.virtualIndices), Array(16).fill(pair.index));
    assert.deepEqual(mapped.pixels.data, source.data, 'C64 Palette displays the mixture RGB itself');
    const checkers = runtime.resolveVirtualPaletteColors(mapped, state.virtualPalette, state.palette, 'checkers');
    for (let y = 0; y < 4; y += 1) {
      for (let x = 0; x < 4; x += 1) {
        const expected = state.palette[(x + y) & 1 ? component : 0].rgb;
        assert.deepEqual(Array.from(checkers.data.slice((y * 4 + x) * 4, (y * 4 + x) * 4 + 3)), Array.from(expected));
      }
    }
  }
});

test('every complete scale increases actual lightness and has all contacts in its stated source image', () => {
  for (const paletteId of ['colodore', 'pepto', 'peptoette-a']) {
    const state = runtime.createC64PaletteState(paletteId, 'talent');
    const byIndex = new Map(state.virtualPalette.map(color => [color.index, color]));
    const lengths = new Set();
    for (const ramp of state.talentToneModel.ramps) {
      const evidence = observations.images.find(image => image.id === ramp.imageId);
      assert.ok(evidence);
      const tones = Array.from(ramp.indices, index => byIndex.get(index));
      assert.deepEqual(Array.from(tones[0].colorIndices), [0, 0]);
      assert.deepEqual(Array.from(tones.at(-1).colorIndices), [1, 1]);
      lengths.add(tones.length);
      for (let position = 1; position < tones.length; position += 1) {
        const previous = tones[position - 1];
        const current = tones[position];
        assert.ok(current.lightness > previous.lightness);
        const a = previous.colorIndices.join('-');
        const b = current.colorIndices.join('-');
        const edge = evidence.edges.find(edge => edge.a === a && edge.b === b || edge.a === b && edge.b === a);
        assert.ok(edge && edge.count >= observations.minContacts, `${paletteId}, image ${ramp.imageId}: ${a}/${b}`);
      }
    }
    assert.ok(lengths.size > 1, 'observed scales may have different numbers of steps');
  }
});

test('Talent caps and exclusions restrict actual tones without altering transparent source bytes', () => {
  const state = runtime.createC64PaletteState('colodore', 'talent');
  const byIndex = new Map(state.virtualPalette.map(color => [color.index, color]));
  const excluded = state.virtualPalette.find(color => color.lightness * 100 > 31 && color.lightness * 100 < 67);
  const source = image([[31, 73, 91, 0], ...Array.from({ length: 255 }, (_, gray) => [gray, gray, gray])], 16);
  const mapped = runtime.mapToTalentVirtualPalette(source, state.virtualPalette,
    { minLightness: 31, maxLightness: 67, excludedIndices: [excluded.index] });
  assert.equal(mapped.virtualIndices[0], 255);
  assert.deepEqual(Array.from(mapped.pixels.data.slice(0, 4)), [31, 73, 91, 0]);
  for (const index of mapped.virtualIndices.slice(1)) {
    const lightness = rgbToOklab(...byIndex.get(index).rgb).lightness * 100;
    assert.ok(lightness >= 31 && lightness <= 67);
    assert.notEqual(index, excluded.index);
  }
});
