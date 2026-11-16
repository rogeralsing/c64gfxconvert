const assert = require('node:assert/strict');
const test = require('node:test');
const { ImageData, palette, createContext, setPixel } = require('./fixtures/sprite-images.cjs');

const { normalizeC64BorderSprites, getC64BorderLayout, convertC64BorderSprites,
  composeC64BorderPreview } = createContext(['border-sprites.js']);

function settings(vertical = true, sides = true, mode = 'hires') {
  return { vertical: { enabled: vertical, mode, colorIndex: 1 },
    sides: { enabled: sides, mode, colorIndex: 1 }, multicolorIndices: [5, 6] };
}
function source(config, rgba = [...palette[1].rgb, 255]) {
  const { width, height } = getC64BorderLayout(config);
  const pixels = new ImageData(width, height);
  for (let offset = 0; offset < pixels.data.length; offset += 4) pixels.data.set(rgba, offset);
  return pixels;
}
const pixel = (pixels, x, y) => Array.from(pixels.data.subarray((y * pixels.width + x) * 4,
  (y * pixels.width + x) * 4 + 4));

// Independent VIC bit decoding exercises the native data contract rather than
// reusing conversion helpers to construct the expected visible image.
function decode(result) {
  const { width, height, backgroundColorIndex } = result;
  const pixels = new ImageData(width, height);
  for (let offset = 0; offset < pixels.data.length; offset += 4) pixels.data.set([...palette[backgroundColorIndex].rgb, 255], offset);
  for (const sprite of result.sprites) {
    const colors = sprite.multicolor
      ? [backgroundColorIndex, result.config.multicolorIndices[0], sprite.colorIndex, result.config.multicolorIndices[1]]
      : [backgroundColorIndex, sprite.colorIndex];
    let top = sprite.y;
    for (let row = 0; row < 21; row += 1) {
      for (let x = 0; x < sprite.displayWidth; x += 1) {
        const bit = Math.floor(x / (sprite.xExpanded ? 2 : 1));
        const byte = sprite.data[row * 3 + Math.floor(bit / 8)];
        const code = sprite.multicolor ? byte >> (6 - Math.floor(bit % 8 / 2) * 2) & 3 : byte >> (7 - bit % 8) & 1;
        const displayX = sprite.x + x;
        for (let repeat = 0; repeat < sprite.rowHeights[row]; repeat += 1) {
          const displayY = top + repeat;
          if (displayX >= 0 && displayX < width && displayY >= 0 && displayY < height &&
              displayX >= sprite.clip.x && displayX < sprite.clip.x + sprite.clip.width &&
              displayY >= sprite.clip.y && displayY < sprite.clip.y + sprite.clip.height) {
            setPixel(pixels, displayX, displayY, palette[colors[code]].rgb);
            assert.equal(result.opaqueMask[displayY * width + displayX], code === 0 ? 0 : 1);
          }
        }
      }
      top += sprite.rowHeights[row];
    }
  }
  return pixels;
}

test('each enabled PAL border fills its complete visible area without blank multiplexing rows', () => {
  for (const [vertical, sides, width, height, count] of [
    [false, false, 320, 200, 0], [true, false, 320, 272, 32],
    [false, true, 368, 200, 20], [true, true, 368, 272, 52]
  ]) {
    const config = settings(vertical, sides);
    const result = convertC64BorderSprites(source(config), palette, config);
    assert.equal(result.width, width);
    assert.equal(result.height, height);
    assert.equal(result.sprites.length, count);
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const inCore = x >= (sides ? 24 : 0) && x < (sides ? 344 : 320) &&
          y >= (vertical ? 35 : 0) && y < (vertical ? 235 : 200);
        assert.deepEqual(pixel(result.pixels, x, y), [...palette[inCore ? 0 : 1].rgb, 255]);
      }
    }
    assert.ok(result.sprites.every(sprite => sprite.data.length === 64 && sprite.data[63] === 0));
    for (const sprite of result.sprites.filter(sprite => sprite.group === 'left' || sprite.group === 'right')) {
      assert.equal(sprite.vicY, sprite.band === 9 ? 229 : 50 + sprite.band * 21);
      assert.equal(sprite.yExpanded, false);
      assert.equal(sprite.displayHeight, 21);
      assert.ok(sprite.rowHeights.every(height => height === 1));
      assert.notEqual(sprite.data[60], 0,
        'the last visible sprite row must remain filled');
    }
  }
});

test('packs native multicolor code order and reproduces every fitted border pixel from sprite bytes', () => {
  const config = settings(true, true, 'multicolor');
  const image = source(config, [...palette[0].rgb, 255]);
  const colors = [0, 5, 1, 6];
  for (let y = 0; y < image.height; y += 1) {
    for (let x = 0; x < image.width; x += 1) {
      const vertical = y < 35 || y >= 235;
      const step = vertical ? 4 : 2;
      setPixel(image, x, y, palette[colors[Math.floor(x / step) % 4]].rgb);
    }
  }
  const result = convertC64BorderSprites(image, palette, config);
  const top = result.sprites.find(sprite => sprite.group === 'top' && sprite.x === 0);
  const bottom = result.sprites.find(sprite => sprite.group === 'bottom' && sprite.x === 0);
  const left = result.sprites.find(sprite => sprite.group === 'left' && sprite.band === 0);
  assert.equal(top.data[21], 0x1b, 'top source row seven is the first visible row after cropping');
  assert.equal(bottom.data[0], 0x1b);
  assert.equal(left.data[0], 0x1b);
  assert.deepEqual(result.pixels.data, decode(result).data);
  for (const group of ['top', 'bottom']) {
    for (const band of [0, 1]) {
      assert.deepEqual(Array.from(result.sprites.filter(sprite => sprite.group === group && sprite.band === band),
        sprite => sprite.hardwareSlot).sort(), [0, 1, 2, 3, 4, 5, 6, 7]);
    }
  }
});

test('hires borders retain their own resolution and source alpha resolves to the shared image background', () => {
  const config = settings();
  const image = source(config, [255, 255, 255, 0]);
  for (let y = 0; y < 35; y += 1) {
    for (let x = 0; x < image.width; x += 1) setPixel(image, x, y, palette[Math.floor(x / 2) % 2].rgb);
  }
  for (let y = 35; y < 235; y += 1) {
    for (let x = 0; x < 24; x += 1) setPixel(image, x, y, palette[(x + y - 35) % 2].rgb);
  }
  const result = convertC64BorderSprites(image, palette, config, 9);
  assert.equal(result.sprites.find(sprite => sprite.group === 'top').data[21], 0x55);
  assert.equal(result.sprites.find(sprite => sprite.group === 'left').data[0], 0x55);
  assert.equal(result.sprites.find(sprite => sprite.group === 'left').data[3], 0xaa,
    'successive side rows retain single-pixel vertical detail');
  assert.deepEqual(pixel(result.pixels, 0, 235), [...palette[9].rgb, 255]);
  assert.ok(result.sprites.filter(sprite => sprite.group === 'bottom').every(sprite => sprite.data.every(value => value === 0)));
  assert.deepEqual(result.pixels.data, decode(result).data);

  const detail = source(config, [255, 255, 255, 0]);
  for (let y = 0; y < detail.height; y += 1) {
    if (y >= 35 && y < 235) continue;
    for (let x = 0; x < detail.width; x += 1) {
      setPixel(detail, x, y, palette[(Math.floor(x / 2) + y) % 2].rgb);
    }
  }
  const singleRows = convertC64BorderSprites(detail, palette, config);
  for (let y = 0; y < detail.height; y += 1) {
    if (y >= 35 && y < 235) continue;
    for (let x = 0; x < detail.width; x += 1) {
      assert.deepEqual(pixel(singleRows.pixels, x, y),
        [...palette[(Math.floor(x / 2) + y) % 2].rgb, 255],
        `vertical border row ${y} must retain its own source pixels, including both band joins`);
    }
  }
  assert.deepEqual(singleRows.pixels.data, decode(singleRows).data);
});

test('composes either bitmap resolution at the PAL core origin without changing border frames or input pixels', () => {
  const config = settings();
  const borderSource = source(config);
  setPixel(borderSource, 344, 35, palette[0].rgb);
  setPixel(borderSource, 344, 36, palette[0].rgb);
  const result = convertC64BorderSprites(borderSource, palette, config);
  const original = new Uint8ClampedArray(result.pixels.data);
  for (const width of [160, 320]) {
    const core = new ImageData(width, 200);
    for (let y = 0; y < 200; y += 1) {
      for (let x = 0; x < width; x += 1) setPixel(core, x, y, [x % 256, y, 77, 255]);
    }
    const composed = composeC64BorderPreview(core, result);
    assert.deepEqual(pixel(composed, 24, 35), [0, 0, 77, 255]);
    assert.deepEqual(pixel(composed, 343, 234), [(width - 1) % 256, 199, 77, 255]);
    assert.deepEqual(pixel(composed, 25, 35), [width === 160 ? 0 : 1, 0, 77, 255]);
    assert.deepEqual(pixel(composed, 23, 35), [...palette[1].rgb, 255]);
    const shifted = composeC64BorderPreview(core, result, true);
    assert.deepEqual(pixel(composed, 344, 35), [...palette[0].rgb, 255], 'unshifted field has no bitmap spill');
    assert.deepEqual(pixel(shifted, 344, 35), [(width - 1) % 256, 0, 77, 255], 'transparent sprite code reveals the shifted bitmap');
    assert.deepEqual(pixel(shifted, 344, 37), [...palette[1].rgb, 255], 'opaque sprite code covers the shifted bitmap');
    assert.deepEqual(pixel(shifted, 345, 35), [...palette[1].rgb, 255], 'spill reaches only the first border column');
  }
  assert.deepEqual(result.pixels.data, original);
});

test('interlaced sprites fit both physical X phases and retain sprite priority over the shifted bitmap edge', () => {
  const config = settings(true, true, 'multicolor');
  config.multicolorIndices = [0, 1];
  const image = source(config);
  const stripe = [1, 1, 1, 0, 0, 0, 0, 1];
  for (let y = 0; y < image.height; y += 1) {
    for (let x = 0; x < image.width; x += 1) setPixel(image, x, y, palette[stripe[x % 8]].rgb);
  }
  const result = convertC64BorderSprites(image, palette, config, 0, true);
  assert.equal(result.interlaced, true);
  assert.equal(result.frames.length, 2);
  assert.equal(result.pixels, result.frames[0].pixels);
  assert.equal(result.sprites, result.frames[0].sprites);
  assert.notDeepEqual(result.frames[0].sprites[0].data, result.frames[1].sprites[0].data,
    'the second phase must refit its shifted source groups, not reuse the first phase bytes');
  for (const [phase, frame] of result.frames.entries()) {
    assert.equal(frame.phase, phase);
    assert.equal(frame.offsetX, phase);
    assert.deepEqual(frame.pixels.data, decode(frame).data);
    frame.sprites.forEach((sprite, index) => {
      const first = result.frames[0].sprites[index];
      assert.equal(sprite.x, first.x + phase);
      assert.equal(sprite.vicX, first.vicX + phase);
      assert.equal(sprite.clip.x, first.clip.x + phase);
      assert.equal(sprite.y, first.y);
    });
  }
  const core = new ImageData(320, 200);
  for (let y = 0; y < 200; y += 1) {
    for (let x = 0; x < 320; x += 1) setPixel(core, x, y, palette[x === 319 ? 5 : 0].rgb);
  }
  const shifted = composeC64BorderPreview(core, result.frames[1], true);
  assert.deepEqual(pixel(shifted, 24, 35), [...palette[1].rgb, 255],
    'the shifted left sprite covers the bitmap first column when its native code is opaque');
  assert.deepEqual(pixel(shifted, 344, 35), [...palette[5].rgb, 255],
    'the shifted right sprite leaves the bitmap spill visible before its first X position');
  assert.deepEqual(pixel(shifted, 345, 35), [...palette[1].rgb, 255]);
});

test('settings default to off, copy shared colors, and reject malformed source or unsupported colors and modes', () => {
  const defaults = normalizeC64BorderSprites();
  assert.equal(defaults.vertical.enabled, false);
  assert.equal(defaults.sides.enabled, false);
  const config = settings();
  const normalized = normalizeC64BorderSprites(config);
  normalized.multicolorIndices[0] = 12;
  normalized.vertical.enabled = false;
  assert.equal(config.multicolorIndices[0], 5);
  assert.equal(config.vertical.enabled, true);
  for (const malformed of [
    { vertical: { enabled: 'true' } }, { sides: { mode: 'overlay' } }, { optimizeColors: 'true' },
    { sides: { colorIndex: 16 } }, { multicolorIndices: [1] }, { multicolorIndices: [1, -1] }
  ]) assert.throws(() => normalizeC64BorderSprites(malformed), /Border sprite/);
  assert.throws(() => convertC64BorderSprites(new ImageData(320, 200), palette, config), /physical-pixel source/);
  assert.throws(() => convertC64BorderSprites(source(config), palette.slice(1), config), /16-color C64 palette/);
  assert.throws(() => convertC64BorderSprites(source(config), palette, config, 16), /shared image background/);
});

const virtualRuntime = createContext(['ifli.js', 'talent-palette.js', 'talent-neighbors.js',
  'talent-mapping.js', 'palettes.js', 'layers.js', 'virtual-color-mapping.js', 'border-sprites.js']);

function virtualFixture(mode = 'talent', pattern = 'checkers') {
  const state = virtualRuntime.createC64PaletteState('colodore', mode);
  const tone = state.virtualPalette.find(color => color.colorIndices.join('-') === '0-6');
  assert.ok(tone);
  const config = settings();
  config.vertical.colorIndex = config.sides.colorIndex = 6;
  config.multicolorIndices = [0, 6];
  const image = source(config, [...tone.rgb, 255]);
  const paletteSettings = { minLevel: 0, maxLevel: 16, minLightness: 0, maxLightness: 100,
    excludedIndices: [] };
  const options = { virtualPalette: state.virtualPalette, virtualColorMode: mode,
    brightnessBands: state.brightnessBands,
    layers: [{ source: image, pattern, paletteSettings, dither: 0 }] };
  return { config, image, options, state, tone, paletteSettings };
}

function borderColors(pixels, box) {
  const found = new Set();
  for (let y = box.y; y < box.y + box.height; y += 1) {
    for (let x = box.x; x < box.x + box.width; x += 1) {
      found.add(pixel(pixels, x, y).slice(0, 3).join(','));
    }
  }
  return found;
}

test('legal black-blue virtual colors survive native hires, multicolor and expanded sprite grids', () => {
  const legal = new Set([palette[0].rgb.join(','), palette[6].rgb.join(',')]);
  for (const mode of ['talent', 'computed']) {
    for (const nativeMode of ['hires', 'multicolor']) {
      const { config, image, options, tone, paletteSettings } = virtualFixture(mode);
      config.vertical.mode = config.sides.mode = nativeMode;
      // Disabled solid entries do not disable the same colors as mixed components.
      paletteSettings.excludedIndices = options.virtualPalette.filter(color =>
        color.colorIndices[0] === color.colorIndices[1]).map(color => color.index);
      const oldSolidFit = virtualRuntime.convertC64BorderSprites(image, palette, config);
      assert.equal(borderColors(oldSolidFit.pixels, { x: 0, y: 35, width: 24, height: 200 }).size, 1,
        'the legacy nearest-solid path reproduces the reported flattening');
      const result = virtualRuntime.convertC64BorderSprites(image, palette, config, 0, false, options);
      for (const box of [{ x: 0, y: 35, width: 24, height: 200 },
        { x: 0, y: 0, width: 368, height: 35 }, { x: 0, y: 235, width: 368, height: 37 }]) {
        assert.deepEqual(borderColors(result.pixels, box), legal,
          `${mode}/${nativeMode}: native cells must retain both virtual components`);
      }
      const side = result.sprites.find(sprite => sprite.group === 'left' && sprite.band === 0);
      const next = result.sprites.find(sprite => sprite.group === 'left' && sprite.band === 1);
      assert.equal(side.data[0], nativeMode === 'hires' ? 0x55 : 0x22);
      assert.equal(next.data[0], nativeMode === 'hires' ? 0xaa : 0x88,
        'checker phase continues across odd-height 21-line sprite reuse');
      for (const [y, color] of [[13, 0], [14, 6], [255, 0], [256, 6]]) {
        assert.deepEqual(pixel(result.pixels, 0, y), [...palette[color].rgb, 255],
          'virtual checker phase must continue on consecutive raster rows across both vertical band joins');
      }
      assert.deepEqual(pixel(result.palettePixels, 0, 35), [...tone.rgb.map(Math.round), 255],
        'palette preview retains the chosen virtual RGB before native resolution');
      assert.deepEqual(result.pixels.data, decode(result).data,
        'native frame bytes independently reproduce the fitted virtual pattern');
    }
  }
});

test('border virtual fitting honors Off, exclusions, lightness limits and the selected hardware colors', () => {
  for (const mode of ['talent', 'computed']) {
    const { config, image, options, tone, paletteSettings } = virtualFixture(mode, 'lines');
    const original = virtualRuntime.convertC64BorderSprites(image, palette, config);
    options.layers[0].pattern = 'off';
    const off = virtualRuntime.convertC64BorderSprites(image, palette, config, 0, false, options);
    assert.deepEqual(off.pixels.data, original.pixels.data);
    assert.equal(off.palettePixels, undefined);
    options.layers[0].pattern = 'lines';
    paletteSettings.excludedIndices = [tone.index];
    const excluded = virtualRuntime.convertC64BorderSprites(image, palette, config, 0, false, options);
    assert.equal(borderColors(excluded.pixels, { x: 0, y: 35, width: 24, height: 200 }).size, 1,
      'an excluded mixed entry must not be silently recreated');
    paletteSettings.excludedIndices = [];
    if (mode === 'talent') paletteSettings.maxLightness = Math.floor(tone.lightness * 100) - 1;
    else paletteSettings.maxLevel = 0;
    const capped = virtualRuntime.convertC64BorderSprites(image, palette, config, 0, false, options);
    assert.deepEqual(borderColors(capped.pixels, { x: 0, y: 35, width: 24, height: 200 }),
      new Set([palette[0].rgb.join(',')]));
    paletteSettings.maxLevel = 16;
    paletteSettings.maxLightness = 100;
    config.vertical.colorIndex = config.sides.colorIndex = 1;
    const noBlue = virtualRuntime.convertC64BorderSprites(image, palette, config, 0, false, options);
    assert.ok(!borderColors(noBlue.pixels, { x: 0, y: 35, width: 24, height: 200 }).has(palette[6].rgb.join(',')),
      'virtual colors must never add a missing hardware component');
  }
});

test('per-layer virtual patterns compose with alpha and follow each shifted MCI field on the native grid', () => {
  const { config, image, options } = virtualFixture('talent', 'lines');
  const upper = new ImageData(image.width, image.height);
  for (let y = 135; y < 235; y += 1) for (let x = 0; x < 24; x += 1) {
    setPixel(upper, x, y, pixel(image, x, y));
  }
  options.layers.push({ ...options.layers[0], source: upper, pattern: 'checkers' });
  const result = virtualRuntime.convertC64BorderSprites(image, palette, config, 0, true, options);
  const first = result.frames[0], second = result.frames[1];
  assert.deepEqual(pixel(first.pixels, 0, 45), [...palette[0].rgb, 255]);
  assert.deepEqual(pixel(first.pixels, 1, 45), [...palette[0].rgb, 255], 'transparent upper layer leaves lower lines visible');
  assert.deepEqual(pixel(first.pixels, 0, 135), [...palette[0].rgb, 255]);
  assert.deepEqual(pixel(first.pixels, 1, 135), [...palette[6].rgb, 255], 'opaque upper layer keeps its own checker pattern');
  assert.deepEqual(pixel(second.pixels, 1, 135), [...palette[6].rgb, 255], 'phase B resolves its actual shifted source/core parity');
  assert.deepEqual(pixel(second.pixels, 2, 135), [...palette[0].rgb, 255]);
  for (const frame of result.frames) assert.deepEqual(frame.pixels.data, decode(frame).data);
  assert.equal(result.frames[1].sprites[0].x, result.frames[0].sprites[0].x + 1);
});
