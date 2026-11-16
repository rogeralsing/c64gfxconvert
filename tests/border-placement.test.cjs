const assert = require('node:assert/strict');
const test = require('node:test');
const { ImageData, palette, createContext, setPixel, rgbToOklab } = require('./fixtures/sprite-images.cjs');

const runtime = createContext(['border-sprites.js', 'border-color-optimizer.js']);
const { optimizeC64BorderColors, convertC64BorderSprites, getC64BorderLayout, normalizeC64BorderSprites } = runtime;
const positions = [3, 43, 83, 123, 163, 203, 243, 283];
function settings(mode = 'hires', automatic = false) {
  return { vertical: { enabled: true, mode, colorIndex: 1, xExpanded: false },
    sides: { enabled: false, mode: 'hires', colorIndex: 1 }, multicolorIndices: [5, 7],
    ...(automatic ? { optimizeColors: true } : {}) };
}
function artwork(config, background, paint) {
  const layout = getC64BorderLayout(config), image = new ImageData(layout.width, layout.height);
  for (let offset = 0; offset < image.data.length; offset += 4) image.data.set([...palette[background].rgb, 255], offset);
  for (let band = 0; band < 4; band += 1) {
    const top = [-7, 14, 235, 256][band];
    for (let y = Math.max(0, top); y < Math.min(layout.height, top + 21); y += 1) {
      positions.forEach((left, sprite) => {
        for (let x = 0; x < 24; x += 1) setPixel(image, left + x, y, palette[paint(x, sprite, band)].rgb);
      });
    }
  }
  return image;
}

test('normal-width placement finds off-grid islands exactly and scores uncovered pixels against the chosen background', () => {
  for (const background of [0, 9]) {
    const config = settings();
    const source = artwork(config, background, () => 1);
    const baseline = convertC64BorderSprites(source, palette, config, background);
    assert.notDeepEqual(baseline.pixels.data, source.data, 'uniform placement misses off-grid details');
    const plan = optimizeC64BorderColors(source, palette, config, background);
    assert.ok(plan.baselineError > 0);
    assert.ok(plan.optimizedError < 1e-8);
    assert.deepEqual(Array.from(plan.verticalPositions), Array(4).fill(positions).flat());
    assert.deepEqual(Array.from(plan.multicolorIndices), [5, 7], 'manual shared colors stay fixed');
    assert.ok(plan.colorIndices.every(color => color === 1), 'manual foregrounds stay fixed');
    const result = convertC64BorderSprites(source, palette, config, background, false, { colorPlan: plan });
    assert.deepEqual(result.pixels.data, source.data, 'all islands and all uncovered gaps match the source');
    assert.ok(result.sprites.every(sprite => !sprite.xExpanded && sprite.displayWidth === 24));
    assert.equal(result.colorPlan, plan);
    assert.throws(() => convertC64BorderSprites(source, palette, config, background, false,
      { colorPlan: { ...plan, verticalPositions: [3, 26, ...plan.verticalPositions.slice(2)] } }), /nonoverlapping placement plan/);
  }
  const expanded = { ...settings(), vertical: { ...settings().vertical, xExpanded: true } };
  const legacy = { ...expanded, vertical: { enabled: true, mode: 'hires', colorIndex: 1 } };
  assert.deepEqual(normalizeC64BorderSprites(expanded), normalizeC64BorderSprites(legacy));
  assert.throws(() => normalizeC64BorderSprites({ ...legacy, vertical: { ...legacy.vertical, xExpanded: 0 } }), /Border sprite groups/);
});

test('normal placement jointly chooses shared colors, independent foregrounds and minimum-error windows', () => {
  const config = settings('multicolor', true), foregrounds = [2, 3, 4, 5, 8, 9, 10, 11];
  const source = artwork(config, 0, (x, sprite) => [0, 1, 6, foregrounds[sprite]][Math.floor(x / 2) % 4]);
  const before = new Uint8ClampedArray(source.data);
  const plan = optimizeC64BorderColors(source, palette, config);
  assert.ok(plan.optimizedError < 1e-8);
  assert.deepEqual(Array.from(plan.multicolorIndices).sort((a, b) => a - b), [1, 6]);
  assert.ok(new Set(plan.colorIndices).size > 3);
  assert.deepEqual(convertC64BorderSprites(source, palette, config, 0, false, { colorPlan: plan }).pixels.data, source.data);
  assert.deepEqual(source.data, before);
});

test('MCI placement error measures border pixels while native sampling retains the adjacent bitmap pixel', () => {
  for (const pair of [[2, 6], [6, 2]]) {
    const config = settings();
    config.sides = { enabled: true, mode: 'multicolor', colorIndex: 1 };
    config.multicolorIndices = pair;
    const source = artwork(config, 9, () => 1), layout = getC64BorderLayout(config);
    for (let y = layout.coreY; y < layout.coreY + 200; y += 1) {
      for (let x = 0; x < layout.coreX; x += 1) setPixel(source, x, y, palette[6].rgb);
      setPixel(source, layout.coreX, y, palette[2].rgb);
    }
    const plan = optimizeC64BorderColors(source, palette, config, 9, true);
    const result = convertC64BorderSprites(source, palette, config, 9, true, { colorPlan: plan });
    let measured = 0;
    for (const frame of result.frames) for (let y = 0; y < source.height; y += 1) {
      for (let x = 0; x < source.width; x += 1) {
        if (x >= layout.coreX && x < layout.coreX + 320 && y >= layout.coreY && y < layout.coreY + 200) continue;
        const offset = (y * source.width + x) * 4;
        const wanted = rgbToOklab(...source.data.subarray(offset, offset + 3));
        const actual = rgbToOklab(...frame.pixels.data.subarray(offset, offset + 3));
        measured += (wanted.lightness - actual.lightness) ** 2 + (wanted.a - actual.a) ** 2 + (wanted.b - actual.b) ** 2;
      }
    }
    assert.ok(Math.abs(plan.optimizedError - measured) < 1e-7,
      `plan ${plan.optimizedError} must match independent border error ${measured}, shared order ${pair}`);
  }
});

test('odd-X normal sprites preserve the native virtual-color lattice and share their placement between MCI fields', () => {
  const virtual = createContext(['ifli.js', 'talent-palette.js', 'talent-neighbors.js', 'talent-mapping.js',
    'palettes.js', 'layers.js', 'virtual-color-mapping.js', 'border-sprites.js', 'border-color-optimizer.js']);
  const state = virtual.createC64PaletteState('colodore', 'talent');
  const tone = state.virtualPalette.find(color => color.colorIndices.join('-') === '0-6');
  for (const mode of ['hires', 'multicolor']) {
    const config = settings(mode);
    config.vertical.colorIndex = 6;
    config.multicolorIndices = [0, 6];
    const { width, height } = virtual.getC64BorderLayout(config), source = new ImageData(width, height);
    for (let offset = 0; offset < source.data.length; offset += 4) source.data.set([...tone.rgb, 255], offset);
    const options = { virtualPalette: state.virtualPalette, virtualColorMode: 'talent', brightnessBands: state.brightnessBands,
      layers: [{ source, pattern: 'checkers', dither: 0, paletteSettings: { minLightness: 0, maxLightness: 100 } }] };
    const plan = { verticalPositions: Array.from({ length: 32 }, (_, index) => 1 + index % 8 * 24),
      colorIndices: Array(32).fill(6), multicolorIndices: [0, 6], spriteCount: 32, phaseCount: 2, backgroundColorIndex: 0 };
    const result = virtual.convertC64BorderSprites(source, state.palette, config, 0, true, { ...options, colorPlan: plan });
    const cellWidth = mode === 'hires' ? 1 : 2;
    for (const [phase, frame] of result.frames.entries()) {
      const first = frame.sprites[0];
      assert.equal(first.x, 1 + phase);
      for (let column = 0; column < 24 / cellWidth; column += 1) {
        const parity = (Math.floor(first.x / cellWidth) + column - 35) & 1;
        const expected = parity ? 6 : 0;
        const bit = column * (mode === 'hires' ? 1 : 2);
        const value = first.data[7 * 3 + Math.floor(bit / 8)];
        const code = mode === 'hires' ? value >> (7 - bit % 8) & 1 : value >> (6 - bit % 8) & 3;
        assert.equal(code ? 6 : 0, expected, `${mode}, field ${phase}, column ${column}`);
      }
      frame.sprites.forEach((sprite, index) => assert.equal(sprite.x, plan.verticalPositions[index] + phase));
    }
    const optimized = virtual.optimizeC64BorderColors(source, state.palette, config, 0, true, options);
    assert.ok(Number.isFinite(optimized.optimizedError));
    assert.ok(optimized.optimizedError <= optimized.baselineError + 1e-9);
    assert.equal(optimized.phaseCount, 2);
  }
});
