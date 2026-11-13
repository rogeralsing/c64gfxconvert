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

test('Talent scores complete dark-to-light paths before choosing a scale for a smooth color region', () => {
  const palette = [[0, 0, 0], [55, 49, 49], [105, 96, 96], [165, 150, 150],
    [49, 49, 55], [96, 96, 105], [150, 150, 165], [255, 255, 255]]
    .map((rgb, index) => ({ index, rgb, lightness: rgbToOklab(...rgb).lightness }));
  const paths = [[0, 1, 2, 3, 7], [0, 4, 5, 6, 7]];
  const toneModel = {
    ramps: paths.map(indices => ({ indices })),
    segments: paths.flatMap(indices => indices.slice(1).map((index, position) =>
      ({ indices: [indices[position], index] })))
  };
  const gradient = [[4, 2], [2, 3]].flatMap(([from, to]) => Array.from({ length: 32 }, (_, step) =>
    palette[from].rgb.map((value, channel) => Math.round(value + (palette[to].rgb[channel] - value) * step / 31))));
  const limits = { minLightness: 0, maxLightness: 100 };
  const mapped = runtime.mapToTalentVirtualPalette(image(gradient), palette, toneModel, 0, limits);
  const indices = Array.from(mapped.virtualIndices);
  assert.ok(indices.every(index => paths[0].includes(index)),
    'the exact dark blue lure must not make a coherent warm gradient alternate between incompatible scales');
  assert.ok(indices.includes(2) && indices.includes(3), 'the chosen path retains the lighter source steps');
  const reversed = runtime.mapToTalentVirtualPalette(image([...gradient].reverse()), palette, toneModel, 0, limits);
  assert.deepEqual(Array.from(reversed.virtualIndices), [...indices].reverse(),
    'path choice follows source lightness, not the order pixels happen to occupy in memory');
});

test('actual source lightness selects the scale step even when another step has a closer hue', () => {
  const palette = [[0, 0, 0], [140, 70, 80], [100, 150, 120], [203, 204, 124], [255, 255, 255]]
    .map((rgb, index) => ({ index, rgb, lightness: rgbToOklab(...rgb).lightness }));
  const toneModel = {
    ramps: [{ indices: [0, 1, 2, 3, 4] }],
    segments: [{ indices: [0, 1] }, { indices: [1, 2] }, { indices: [2, 3] }, { indices: [3, 4] }]
  };
  // This warm source is closest in lightness to step 2. Chroma must not pull it back to pink step 1.
  const source = image(Array.from({ length: 16 }, () => [180, 110, 120]), 4);
  const limits = { minLightness: 0, maxLightness: 100 };
  const plain = runtime.mapToTalentVirtualPalette(source, palette, toneModel, 0, limits);
  assert.deepEqual(Array.from(plain.virtualIndices), Array(16).fill(2));
  const dithered = runtime.mapToTalentVirtualPalette(source, palette, toneModel, 1, limits);
  assert.deepEqual([...new Set(dithered.virtualIndices)].sort(), [1, 2],
    'dither uses the two measured lightness neighbors, not a chroma shortcut to a different interval');
});

test('separate warm and cool gradients keep their own scales across sharp edges and transparent holes', () => {
  const palette = [[0, 0, 0], [80, 20, 20], [150, 60, 60], [220, 120, 120],
    [20, 20, 80], [60, 60, 150], [120, 120, 220], [255, 255, 255]]
    .map((rgb, index) => ({ index, rgb, lightness: rgbToOklab(...rgb).lightness }));
  const paths = [[0, 1, 2, 3, 7], [0, 4, 5, 6, 7]];
  const toneModel = {
    ramps: paths.map(indices => ({ indices })),
    segments: paths.flatMap(indices => indices.slice(1).map((index, position) =>
      ({ indices: [indices[position], index] })))
  };
  const gradient = (from, to) => Array.from({ length: 33 }, (_, step) =>
    palette[from].rgb.map((value, channel) => Math.round(value + (palette[to].rgb[channel] - value) * step / 32)));
  for (const separator of [[], [[19, 87, 123, 0]]]) {
    const colors = [...gradient(1, 3), ...separator, ...gradient(4, 6)];
    colors[0] = [...colors[0], 127];
    const source = image(colors);
    const before = new Uint8ClampedArray(source.data);
    for (const amount of [0, 1]) {
      const mapped = runtime.mapToTalentVirtualPalette(source, palette, toneModel, amount,
        { minLightness: 0, maxLightness: 100 });
      const warm = Array.from(mapped.virtualIndices.slice(0, 33));
      const cool = Array.from(mapped.virtualIndices.slice(33 + separator.length));
      assert.ok(warm.every(index => [1, 2, 3].includes(index)) && warm.includes(1) && warm.includes(3));
      assert.ok(cool.every(index => [4, 5, 6].includes(index)) && cool.includes(4) && cool.includes(6));
      assert.equal(mapped.pixels.data[3], 127);
      if (separator.length) {
        assert.equal(mapped.virtualIndices[33], 255);
        assert.deepEqual(Array.from(mapped.pixels.data.slice(33 * 4, 34 * 4)), [19, 87, 123, 0]);
      }
    }
    assert.deepEqual(source.data, before);
  }
});

test('isolated exact Talent tones retain RGB and lightness at every dither strength', () => {
  for (const paletteId of ['colodore', 'pepto', 'peptoette-a']) {
    const state = runtime.createC64PaletteState(paletteId, 'talent');
    const source = image(Array.from(state.virtualPalette, (color, index) =>
      [[...color.rgb, index % 2 ? 127 : 255], [13, 29, 47, 0]]).flat());
    const before = new Uint8ClampedArray(source.data);
    for (const amount of [0, 0.5, 1]) {
      const mapped = runtime.mapToTalentVirtualPalette(source, state.virtualPalette, state.talentToneModel, amount);
      const byIndex = new Map(state.virtualPalette.map(color => [color.index, color]));
      for (const [pixel, color] of state.virtualPalette.entries()) {
        assert.deepEqual(Array.from(byIndex.get(mapped.virtualIndices[pixel * 2]).rgb), Array.from(color.rgb),
          `${paletteId}, dither ${amount}: exact tones must not snap to an averaged brightness row`);
      }
      assert.deepEqual(mapped.pixels.data, before);
    }
    assert.deepEqual(source.data, before);
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

test('Talent dithers flat tones only between displayed neighbors and never bridges an excluded tone', () => {
  const state = runtime.createC64PaletteState('peptoette-a', 'talent');
  const byIndex = new Map(state.virtualPalette.map(color => [color.index, color]));
  const segments = new Set(state.talentToneModel.segments.map(segment => Array.from(segment.indices).sort((a, b) => a - b).join('-')));
  let dithered = 0;
  for (let gray = 3; gray < 255; gray += 3) {
    const tile = image(Array.from({ length: 16 }, () => [gray, gray, gray]), 4);
    const mapped = runtime.mapToTalentVirtualPalette(tile, state.virtualPalette, state.talentToneModel, 1);
    const chosen = [...new Set(mapped.virtualIndices)].sort((a, b) => a - b);
    assert.ok(chosen.length <= 2);
    if (chosen.length === 2) {
      dithered += 1;
      assert.ok(segments.has(chosen.join('-')), `gray ${gray} must use an observed neighbor`);
    }
  }
  assert.ok(dithered > 20, 'the ramp must interpolate tones, not merely quantize them');

  const ramp = state.talentToneModel.ramps[0].indices;
  let endpoints;
  for (let position = 2; position < ramp.length; position += 1) {
    const pair = [ramp[position - 2], ramp[position]];
    if (!segments.has([...pair].sort((a, b) => a - b).join('-'))) { endpoints = pair; break; }
  }
  assert.ok(endpoints);
  const colors = endpoints.map(index => byIndex.get(index));
  const rgb = colors[0].rgb.map((value, channel) => Math.round((value + colors[1].rgb[channel]) / 2));
  const tile = image(Array.from({ length: 16 }, () => rgb), 4);
  const mapped = runtime.mapToTalentVirtualPalette(tile, state.virtualPalette, state.talentToneModel, 1,
    { excludedIndices: state.virtualPalette.filter(color => !endpoints.includes(color.index)).map(color => color.index) });
  assert.equal(new Set(mapped.virtualIndices).size, 1, 'exclusions cannot create a new neighbor across a gap');
});

test('continuous Talent lightness caps restrict actual tones and preserve transparent source bytes', () => {
  const state = runtime.createC64PaletteState('colodore', 'talent');
  const byIndex = new Map(state.virtualPalette.map(color => [color.index, color]));
  const source = image([[31, 73, 91, 0], ...Array.from({ length: 255 }, (_, gray) => [gray, gray, gray])], 16);
  for (const amount of [0, 1]) {
    const mapped = runtime.mapToTalentVirtualPalette(source, state.virtualPalette, state.talentToneModel, amount,
      { minLightness: 31, maxLightness: 67 });
    assert.equal(mapped.virtualIndices[0], 255);
    assert.deepEqual(Array.from(mapped.pixels.data.slice(0, 4)), [31, 73, 91, 0]);
    for (const index of mapped.virtualIndices.slice(1)) {
      const lightness = rgbToOklab(...byIndex.get(index).rgb).lightness * 100;
      assert.ok(lightness >= 31 && lightness <= 67);
    }
  }
});
