const assert = require('node:assert/strict');
const test = require('node:test');
const { createContext, ImageData } = require('./fixtures/sprite-images.cjs');

const runtime = createContext(['ifli.js', 'talent-palette.js', 'talent-neighbors.js',
  'talent-mapping.js', 'palettes.js', 'virtual-color-mapping.js']);

function options(mode) {
  const state = runtime.createC64PaletteState('peptoette-a', mode);
  return { virtualPalette: state.virtualPalette, virtualColorMode: mode, palette: state.palette,
    brightnessBands: state.brightnessBands, pattern: 'checkers', dither: 0,
    paletteSettings: mode === 'talent' ? { minLightness: 0, maxLightness: 100 }
      : { minLevel: 0, maxLevel: 16 } };
}
const tone = (settings, first, second) => settings.virtualPalette.find(color =>
  color.colorIndices[0] === first && color.colorIndices[1] === second);
function image(rgb, width = 4, height = 4, alpha = 255) {
  const source = new ImageData(width, height);
  for (let offset = 0; offset < source.data.length; offset += 4) source.data.set([...rgb, alpha], offset);
  return source;
}
const pixel = (source, x, y) => Array.from(source.data.slice((y * source.width + x) * 4,
  (y * source.width + x) * 4 + 4));

test('both document palette modes retain the black-blue virtual identity and resolve native component colors', () => {
  for (const mode of ['talent', 'computed']) {
    const settings = options(mode);
    const mixture = tone(settings, 0, 6);
    const source = image(mixture.rgb);
    const before = new Uint8ClampedArray(source.data);
    const result = runtime.mapC64VirtualColors(source, settings);
    assert.ok(Array.from(result.mapping.virtualIndices).every(index => index === mixture.index), mode);
    for (let y = 0; y < source.height; y += 1) for (let x = 0; x < source.width; x += 1) {
      assert.deepEqual(pixel(result.target, x, y), [...settings.palette[(x + y) & 1 ? 6 : 0].rgb, 255], mode);
    }
    assert.deepEqual(source.data, before);
  }
});

test('hardware component limits keep mixed entries independent of disabled solids and respect tone exclusions and ranges', () => {
  for (const mode of ['talent', 'computed']) {
    const settings = options(mode);
    const mixture = tone(settings, 0, 6);
    settings.allowedColorIndices = [0, 6];
    settings.paletteSettings.excludedIndices = [tone(settings, 0, 0).index, tone(settings, 6, 6).index];
    const source = image(settings.palette[1].rgb);
    const result = runtime.mapC64VirtualColors(source, settings);
    assert.ok(Array.from(result.mapping.virtualIndices).every(index => index === mixture.index), mode);
    settings.paletteSettings.excludedIndices.push(mixture.index);
    assert.equal(runtime.mapC64VirtualColors(source, settings), null, `${mode}: no enabled representable tone`);
    settings.paletteSettings = mode === 'talent' ? { minLightness: 80, maxLightness: 100 }
      : { minLevel: 10, maxLevel: 16 };
    assert.equal(runtime.mapC64VirtualColors(source, settings), null, `${mode}: capped legal tones`);
    assert.equal(runtime.mapC64VirtualColors(source, { ...settings, pattern: 'off' }), null);
  }
});

test('core-relative origins preserve checker and line phases without altering alpha or hidden pixels', () => {
  const settings = options('talent');
  const source = image(tone(settings, 0, 6).rgb, 3, 3, 128);
  source.data.set([13, 17, 19, 0], 0);
  for (const pattern of ['checkers', 'lines']) {
    const result = runtime.mapC64VirtualColors(source, { ...settings, pattern, originX: -3, originY: 4 });
    assert.equal(result.mapping.virtualIndices[0], 255);
    assert.deepEqual(pixel(result.mapping.pixels, 0, 0), [13, 17, 19, 0]);
    assert.deepEqual(pixel(result.target, 0, 0), [13, 17, 19, 0]);
    for (let y = 0; y < source.height; y += 1) for (let x = 0; x < source.width; x += 1) {
      if (!x && !y) continue;
      const parity = (y + 4 + (pattern === 'checkers' ? x - 3 : 0)) & 1;
      assert.deepEqual(pixel(result.target, x, y), [...settings.palette[parity ? 6 : 0].rgb, 128]);
    }
  }
});

test('Talent pairs follow the document row lattice when a region starts on an odd row', () => {
  const settings = options('talent');
  const source = image([51, 51, 51], 1, 3);
  source.data.set([50, 50, 50, 255], 0);
  const result = runtime.mapC64VirtualColors(source, { ...settings, originY: 1 });
  assert.deepEqual(Array.from(result.mapping.virtualIndices), [
    tone(settings, 0, 9).index, tone(settings, 0, 11).index, tone(settings, 0, 11).index
  ], 'the leading unpaired row must not borrow the next region row’s virtual choice');
});
