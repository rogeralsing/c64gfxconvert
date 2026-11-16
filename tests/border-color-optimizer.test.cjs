const assert = require('node:assert/strict');
const test = require('node:test');
const { ImageData, palette, createContext, setPixel } = require('./fixtures/sprite-images.cjs');

const runtime = createContext(['border-sprites.js', 'border-color-optimizer.js']);
const { optimizeC64BorderColors, convertC64BorderSprites, getC64BorderLayout } = runtime;
function settings(mode = 'multicolor') {
  return { vertical: { enabled: true, mode, colorIndex: 13 },
    sides: { enabled: true, mode, colorIndex: 13 }, multicolorIndices: [5, 7], optimizeColors: true };
}
function pixels(config, colorAt) {
  const { width, height, coreX, coreY } = getC64BorderLayout(config);
  const source = new ImageData(width, height);
  for (let y = 0; y < height; y += 1) for (let x = 0; x < width; x += 1) {
    const border = x < coreX || x >= coreX + 320 || y < coreY || y >= coreY + 200;
    setPixel(source, x, y, palette[border ? colorAt(x, y, coreX, coreY) : 0].rgb);
  }
  return source;
}

test('finds the common multicolor pair and independent foregrounds for exactly representable native artwork', () => {
  const config = settings(), foregrounds = [2, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14, 15];
  const source = pixels(config, (x, y) => {
    const vertical = y < 35 || y >= 235;
    let index;
    if (y < 35) index = Math.floor((y + 7) / 21) * 8 + Math.floor(x / 48);
    else if (y >= 235) index = 16 + Math.floor((y - 235) / 21) * 8 + Math.floor(x / 48);
    else index = (x < 24 ? 32 : 42) + Math.min(9, Math.floor((y - 35) / 21));
    return [0, 1, 6, foregrounds[index % foregrounds.length]][Math.floor(x / (vertical ? 4 : 2)) % 4];
  });
  const original = new Uint8ClampedArray(source.data), updates = [];
  const plan = optimizeC64BorderColors(source, palette, config, 0, false, { onProgress: progress => updates.push(progress) });
  assert.deepEqual(Array.from(plan.multicolorIndices).sort((a, b) => a - b), [1, 6]);
  assert.ok(plan.baselineError > 0);
  assert.ok(plan.optimizedError < 1e-8);
  assert.ok(new Set(plan.colorIndices).size > 3);
  assert.equal(plan.metric, 'native-pixel-oklab-sse');
  assert.equal(updates[0].completed, 0);
  assert.equal(updates.at(-1).completed, updates.at(-1).total);
  const result = convertC64BorderSprites(source, palette, config, 0, false, { colorPlan: plan });
  assert.deepEqual(result.pixels.data, source.data, 'the selected hardware allocation reproduces every source pixel');
  assert.deepEqual(source.data, original);
  assert.deepEqual(config.multicolorIndices, [5, 7], 'optimization does not overwrite manual controls');
});

test('ties palette choices across both MCI fields and retains irrelevant shared colors for hires sprites', () => {
  const config = settings('hires');
  const source = pixels(config, (x, y) => y < 35 ? 3 : y >= 235 ? 14 : x < 24 ? 2 : 5);
  const first = optimizeC64BorderColors(source, palette, config, 0, true);
  const second = optimizeC64BorderColors(source, palette, config, 0, true);
  assert.deepEqual(Array.from(first.multicolorIndices), [5, 7]);
  assert.deepEqual(first, second, 'equal inputs keep deterministic foregrounds and tie-breaking');
  assert.ok(first.optimizedError < first.baselineError);
  assert.equal(first.phaseCount, 2);
  const result = convertC64BorderSprites(source, palette, config, 0, true, { colorPlan: first });
  result.frames[0].sprites.forEach((sprite, index) => {
    assert.equal(sprite.colorIndex, result.frames[1].sprites[index].colorIndex);
  });
  assert.throws(() => convertC64BorderSprites(source, palette, config, 0, true), /completed color plan/);
  assert.throws(() => convertC64BorderSprites(source, palette, config, 0, false, { colorPlan: first }), /completed color plan/);
});

test('automatic search cannot bypass virtual-color exclusions by choosing an unavailable component set', () => {
  const virtual = createContext(['ifli.js', 'talent-palette.js', 'talent-neighbors.js', 'talent-mapping.js',
    'palettes.js', 'layers.js', 'virtual-color-mapping.js', 'border-sprites.js', 'border-color-optimizer.js']);
  const state = virtual.createC64PaletteState('colodore', 'talent');
  const tone = state.virtualPalette.find(color => color.colorIndices.join('-') === '0-6');
  assert.ok(tone);
  const config = settings('hires');
  config.vertical.colorIndex = config.sides.colorIndex = 6;
  config.sides.enabled = false;
  const source = pixels(config, () => 5);
  const options = { virtualPalette: state.virtualPalette, virtualColorMode: 'talent',
    brightnessBands: state.brightnessBands, layers: [{ source, pattern: 'lines', dither: 0,
      paletteSettings: { minLightness: 0, maxLightness: 100,
        excludedIndices: state.virtualPalette.filter(color => color.index !== tone.index).map(color => color.index) } }] };
  const plan = virtual.optimizeC64BorderColors(source, palette, config, 0, false, options);
  assert.ok(plan.colorIndices.every(color => color === 6), 'green cannot escape the sole enabled black-blue mixture');
  assert.ok(plan.optimizedError <= plan.baselineError);
  const result = virtual.convertC64BorderSprites(source, palette, config, 0, false, { ...options, colorPlan: plan });
  const offset = (10 * result.width + 20) * 4;
  assert.deepEqual(Array.from(result.palettePixels.data.subarray(offset, offset + 3)), Array.from(tone.rgb));

  // A manual foreground with no legal mixture still has a real appearance.
  // Its finite baseline allows an automatic palette to repair that choice.
  config.vertical.colorIndex = 0;
  const virtualSource = new ImageData(source.width, source.height);
  for (let index = 0; index < virtualSource.data.length; index += 4) {
    virtualSource.data.set([...tone.rgb, 255], index);
  }
  const repaired = virtual.optimizeC64BorderColors(virtualSource, palette, config, 0, false,
    { ...options, layers: [{ ...options.layers[0], source: virtualSource }] });
  assert.ok([repaired.baselineError, repaired.optimizedError, repaired.improvementPercent].every(Number.isFinite));
  assert.ok(repaired.optimizedError < repaired.baselineError);
});
