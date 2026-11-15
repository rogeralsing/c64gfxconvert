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
  return colors.map((rgb, index) => ({ index, rgb, colorIndices: [index, index],
    brightnessBands: [index, index], lightness: rgbToOklab(...rgb).lightness }));
}
const grays = palette([0, 64, 128, 192, 255].map(value => [value, value, value]));

test('similar vertical pixels share one averaged virtual color regardless of upper/lower order', () => {
  const state = runtime.createC64PaletteState('peptoette-a', 'talent');
  const shadow = state.virtualPalette.find(color => color.colorIndices.join('-') === '0-9');
  for (const values of [[49, 51], [51, 49]]) {
    const source = image(values.map(value => [value, value, value]), 1);
    const mapped = runtime.mapToTalentVirtualPalette(source, state.virtualPalette, limits);
    assert.deepEqual(Array.from(mapped.virtualIndices), [shadow.index, shadow.index]);
    assert.deepEqual(Array.from(mapped.pixels.data), [58, 43, 0, 255, 58, 43, 0, 255],
      'the pair average must select one virtual tone, rather than favoring the upper source pixel');
  }
});

test('brightness dither makes one virtual choice per vertical pair on smooth surfaces', () => {
  const state = runtime.createC64PaletteState('peptoette-a', 'talent');
  const source = image(Array.from({ length: 64 }, (_, pixel) =>
    Math.floor(pixel / 8) % 2 ? [247, 151, 106] : [248, 152, 106]), 8);
  const byIndex = new Map(state.virtualPalette.map(color => [color.index, color]));
  for (const amount of [0, 0.5, 1]) {
    const mapped = runtime.mapToTalentVirtualPalette(source, state.virtualPalette, limits, amount);
    for (let y = 0; y < source.height; y += 2) {
      for (let x = 0; x < source.width; x += 1) {
        const upper = y * source.width + x;
        const lower = upper + source.width;
        assert.equal(mapped.virtualIndices[upper], mapped.virtualIndices[lower], `dither ${amount}, (${x}, ${y})`);
        assert.deepEqual(Array.from(mapped.pixels.data.slice(upper * 4, upper * 4 + 3)),
          Array.from(mapped.pixels.data.slice(lower * 4, lower * 4 + 3)));
        const color = byIndex.get(mapped.virtualIndices[upper]);
        assert.notEqual(color.colorIndices[0], color.colorIndices[1], 'smooth skin must retain virtual mixed colors');
      }
    }
    if (amount === 0) assert.equal(new Set(mapped.virtualIndices).size, 1);
    if (amount === 1) assert.ok(new Set(mapped.virtualIndices).size > 1, 'brightness interpolation remains active between pairs');
  }
});

test('different pairs and an odd final row choose virtual colors independently without crossing pair boundaries', () => {
  const state = runtime.createC64PaletteState('peptoette-a', 'talent');
  const source = image([
    [35, 35, 95], [52, 51, 131],
    [101, 62, 42], [82, 62, 0],
    [101, 62, 42], [52, 51, 131],
    [255, 255, 255], [82, 62, 0],
    [90, 47, 98], [35, 35, 95]
  ], 2);
  for (const amount of [0, 1]) {
    const mapped = runtime.mapToTalentVirtualPalette(source, state.virtualPalette, limits, amount);
    assert.deepEqual(Array.from(mapped.virtualIndices), [1, 39, 10, 52, 10, 39, 3, 52, 71, 1],
      'detail matching retains black + blue, red + brown, and black + purple instead of forcing solids');
    assert.deepEqual(mapped.pixels.data, source.data, 'exact virtual colors retain the individual source details');
  }
});

test('disabled solids do not exclude separately enabled mixtures from either mapping branch', () => {
  for (const paletteId of ['colodore', 'pepto', 'peptoette-a']) {
    const state = runtime.createC64PaletteState(paletteId, 'talent');
    const brown = state.virtualPalette.find(color => color.colorIndices.join('-') === '9-9');
    const shadow = state.virtualPalette.find(color => color.colorIndices.join('-') === '0-9');
    const source = image([state.palette[9].rgb, shadow.rgb, state.palette[1].rgb, shadow.rgb], 2);
    const before = new Uint8ClampedArray(source.data);
    const mapped = runtime.mapToTalentVirtualPalette(source, state.virtualPalette,
      { ...limits, excludedIndices: [brown.index] }, 1);
    for (const pixel of [0, 2]) {
      const color = state.virtualPalette.find(color => color.index === mapped.virtualIndices[pixel]);
      assert.notEqual(color.index, brown.index, `${paletteId}: disabling solid brown excludes that entry from individual matching`);
      assert.deepEqual(Array.from(mapped.pixels.data.slice(pixel * 4, pixel * 4 + 3)),
        Array.from(color.rgb));
    }
    assert.equal(mapped.virtualIndices[1], shadow.index,
      'disabling solid brown must not disable a separately enabled black + brown mixture');
    assert.equal(mapped.virtualIndices[3], shadow.index);
    assert.deepEqual(source.data, before);
  }
});

test('disabling gray replaces different source pixels with the next enabled virtual colors', () => {
  for (const [paletteId, expectedIndices, expectedPixels] of [
    ['pepto', [50, 105], [110, 95, 82, 255, 117, 117, 117, 255]],
    ['peptoette-a', [59, 78], [100, 100, 100, 255, 119, 119, 119, 255]],
    ['colodore', [59, 50], [99, 99, 99, 255, 141, 100, 88, 255]]
  ]) {
    const state = runtime.createC64PaletteState(paletteId, 'talent');
    const source = image([[100, 100, 100], [116, 116, 116]], 1);
    const before = new Uint8ClampedArray(source.data);
    for (const amount of [0, 1]) {
      const mapped = runtime.mapToTalentVirtualPalette(source, state.virtualPalette,
        { ...limits, excludedIndices: [61] }, amount);
      assert.deepEqual(Array.from(mapped.virtualIndices), expectedIndices,
        `${paletteId}: a differing pair maps each source separately through the complete enabled palette`);
      assert.deepEqual(Array.from(mapped.pixels.data), expectedPixels);
      for (const index of mapped.virtualIndices) {
        const components = state.virtualPalette.find(color => color.index === index).colorIndices;
        assert.notEqual(components[0], components[1], 'disabled gray can be replaced by a mixed color');
      }
    }
    assert.deepEqual(source.data, before);
  }
});

test('individually mapped pixels obey lightness limits as well as explicit exclusions', () => {
  for (const paletteId of ['colodore', 'pepto', 'peptoette-a']) {
    const state = runtime.createC64PaletteState(paletteId, 'talent');
    const gray = state.virtualPalette.find(color => color.colorIndices.join('-') === '12-12');
    const source = image([[0, 0, 0], [255, 255, 255]], 1);
    const mapped = runtime.mapToTalentVirtualPalette(source, state.virtualPalette,
      { minLightness: 40, maxLightness: 80, excludedIndices: [gray.index] }, 1);
    for (const index of mapped.virtualIndices) {
      const color = state.virtualPalette.find(color => color.index === index);
      assert.ok(color.lightness >= 0.4 && color.lightness <= 0.8, `${paletteId}: detail lightness must stay inside the enabled range`);
      assert.notEqual(index, gray.index);
    }
  }
});

test('visible detail, alpha boundaries, and an odd final row work when only mixtures are enabled', () => {
  for (const paletteId of ['colodore', 'pepto', 'peptoette-a']) {
    const state = runtime.createC64PaletteState(paletteId, 'talent');
    const shadow = state.virtualPalette.find(color => color.index === 1);
    const highlight = state.virtualPalette.find(color => color.index === 10);
    const source = image([
      [0, 0, 0, 255], [0, 0, 0, 127], [12, 34, 56, 0],
      [255, 255, 255, 255], [255, 255, 255, 255], [67, 89, 101, 0],
      [0, 0, 0, 80], [255, 255, 255, 255], [11, 22, 33, 0]
    ], 3);
    const before = new Uint8ClampedArray(source.data);
    const excludedIndices = state.virtualPalette.filter(color => ![1, 10].includes(color.index)).map(color => color.index);
    const mapped = runtime.mapToTalentVirtualPalette(source, state.virtualPalette,
      { ...limits, excludedIndices }, 1);
    assert.deepEqual(Array.from(mapped.virtualIndices), [1, 1, 255, 10, 10, 255, 1, 10, 255]);
    for (let pixel = 0; pixel < mapped.virtualIndices.length; pixel += 1) {
      const offset = pixel * 4;
      const index = mapped.virtualIndices[pixel];
      assert.equal(mapped.pixels.data[offset + 3], before[offset + 3]);
      const expected = index === 255 ? Array.from(before.slice(offset, offset + 3))
        : Array.from((index === 1 ? shadow : highlight).rgb);
      assert.deepEqual(Array.from(mapped.pixels.data.slice(offset, offset + 3)), expected);
    }
    assert.deepEqual(source.data, before);
  }
});

test('Talent chooses brightness before hue, then retains hue choices at similar brightness', () => {
  const colors = palette([[50, 50, 50], [120, 80, 75], [80, 105, 140], [210, 210, 210]]);
  const samples = [[105, 85, 120], [200, 100, 100], [170, 170, 170], [0, 0, 170]];
  const source = image([...samples, ...samples], 4);
  const mapped = runtime.mapToTalentVirtualPalette(source, colors, limits);
  const expected = [1, 2, 3, 0, 1, 2, 3, 0];
  assert.deepEqual(Array.from(mapped.virtualIndices), expected,
    'a closer hue must not move a source pixel to the wrong brightness row');
  assert.deepEqual(Array.from(mapped.pixels.data), expected.flatMap(index => [...colors[index].rgb, 255]));

  const state = runtime.createC64PaletteState('peptoette-a', 'talent');
  const blue = state.virtualPalette.find(color => color.colorIndices.join('-') === '6-6');
  const brown = state.virtualPalette.find(color => color.colorIndices.join('-') === '9-9');
  const nearBlue = image([[48, 50, 140], [48, 50, 140]], 1);
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

test('flat fields contain one actual virtual color with no ordered or tiled dither', () => {
  const flat = image(Array.from({ length: 64 }, () => [95, 95, 95]), 8);
  const mapped = runtime.mapToTalentVirtualPalette(flat, grays, limits);
  assert.equal(new Set(mapped.virtualIndices).size, 1);
  const index = mapped.virtualIndices[0];
  assert.deepEqual(Array.from(mapped.pixels.data), Array.from({ length: 64 }, () => [...grays[index].rgb, 255]).flat());
});

test('transparency boundaries and an unpaired last row map independently while matching partial-alpha pairs share a tone', () => {
  const state = runtime.createC64PaletteState('peptoette-a', 'talent');
  const source = image([
    [35, 35, 95, 127], [12, 34, 56, 0], [101, 62, 42, 63], [19, 87, 123, 0],
    [36, 35, 95, 127], [101, 62, 42, 255], [101, 62, 42, 255], [91, 81, 71, 0],
    [35, 35, 95, 32], [19, 87, 123, 0], [52, 51, 131, 80], [101, 62, 42, 0]
  ], 4);
  const before = new Uint8ClampedArray(source.data);
  const mapped = runtime.mapToTalentVirtualPalette(source, state.virtualPalette, limits, 1);
  const byIndex = new Map(state.virtualPalette.map(color => [color.index, color]));
  assert.equal(mapped.virtualIndices[0], mapped.virtualIndices[4]);
  assert.deepEqual(Array.from(byIndex.get(mapped.virtualIndices[0]).colorIndices), [0, 6]);
  assert.deepEqual(Array.from(mapped.virtualIndices), [1, 255, 10, 255, 1, 10, 10, 255, 1, 255, 39, 255],
    'alpha boundaries and the odd final row keep individual virtual choices');
  for (let pixel = 0; pixel < mapped.virtualIndices.length; pixel += 1) {
    assert.equal(mapped.pixels.data[pixel * 4 + 3], before[pixel * 4 + 3]);
    if (before[pixel * 4 + 3] === 0) {
      assert.equal(mapped.virtualIndices[pixel], 255);
      assert.deepEqual(Array.from(mapped.pixels.data.slice(pixel * 4, pixel * 4 + 4)),
        Array.from(before.slice(pixel * 4, pixel * 4 + 4)));
    }
  }
  assert.deepEqual(source.data, before);
});

test('Talent mapping writes actual palette RGB values and preserves source pixels', () => {
  for (const paletteId of ['colodore', 'pepto', 'peptoette-a']) {
    const state = runtime.createC64PaletteState(paletteId, 'talent');
    const row = Array.from(state.virtualPalette, (color, index) => [...color.rgb, index % 2 ? 127 : 255]);
    const source = image([...row, ...row], row.length);
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

test('Talent caps and exclusions restrict virtual surfaces without altering transparent source bytes', () => {
  const state = runtime.createC64PaletteState('colodore', 'talent');
  const byIndex = new Map(state.virtualPalette.map(color => [color.index, color]));
  const excluded = state.virtualPalette.find(color => color.lightness * 100 > 31 && color.lightness * 100 < 67);
  const colors = [[31, 73, 91, 0], ...Array.from({ length: 255 }, (_, gray) => [gray, gray, gray])];
  const paired = [];
  for (let row = 0; row < 16; row += 1) {
    const pixels = colors.slice(row * 16, row * 16 + 16);
    paired.push(...pixels, ...pixels);
  }
  const source = image(paired, 16);
  const mapped = runtime.mapToTalentVirtualPalette(source, state.virtualPalette,
    { minLightness: 31, maxLightness: 67, excludedIndices: [excluded.index] });
  assert.equal(mapped.virtualIndices[0], 255);
  assert.deepEqual(Array.from(mapped.pixels.data.slice(0, 4)), [31, 73, 91, 0]);
  for (const index of mapped.virtualIndices) {
    if (index === 255) continue;
    const lightness = rgbToOklab(...byIndex.get(index).rgb).lightness * 100;
    assert.ok(lightness >= 31 && lightness <= 67);
    assert.notEqual(index, excluded.index);
  }
});
