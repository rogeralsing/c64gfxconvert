const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { ImageData, createContext, rgbToOklab } = require('./fixtures/sprite-images.cjs');

const { createC64PaletteState, convertTwoColorHires, mapToIfliVirtualPalette,
  mapToTalentVirtualPalette, resolveVirtualPaletteColors } =
  createContext(['ifli.js', 'talent-palette.js', 'talent-neighbors.js', 'talent-mapping.js', 'palettes.js', 'two-color.js']);

function referencePalette(file) {
  return fs.readFileSync(path.join(__dirname, '../palettes', file), 'utf8').split('\n')
    .map(line => line.trim()).filter(line => /^[\da-f]{2}\s+[\da-f]{2}\s+[\da-f]{2}$/i.test(line))
    .map(line => line.split(/\s+/).map(channel => parseInt(channel, 16)));
}

test('palette presets match their shipped VICE references and return to the Colodore default', () => {
  const state = createC64PaletteState();
  assert.equal(state.id, 'colodore');
  assert.equal(state.virtualColorMode, 'computed');
  assert.equal(state.virtualPalette.length, 69);
  const blueShadow = state.virtualPalette.find(color => color.colorIndices.join('-') === '0-6');
  assert.equal(blueShadow.index, 1);
  assert.deepEqual(Array.from(blueShadow.rgb), [19.5, 18, 98], 'legacy mixes retain arithmetic half channels');
  for (const [id, file] of [
    ['colodore', 'colodore.vpl'], ['pepto', 'pepto-pal.vpl'],
    ['peptoette-a', 'peptoette-a.vpl'], ['colodore', 'colodore.vpl']
  ]) {
    state.select(id);
    const reference = referencePalette(file);
    assert.equal(reference.length, 16);
    assert.deepEqual(Array.from(state.palette, color => Array.from(color.rgb)), reference);
  }
});

test('Talent offers every observed palette entry without filtering colors by complete scales', () => {
  const state = createC64PaletteState('colodore', 'talent');
  assert.equal(state.id, 'colodore', 'choosing virtual colors must retain the selected base palette');
  assert.equal(state.virtualColorMode, 'talent');
  assert.equal(state.virtualPalette.length, 92);
  assert.equal(state.virtualPalette.filter(color => color.colorIndices[0] !== color.colorIndices[1]).length, 76);
  const green = state.virtualPalette.find(color => color.colorIndices.every(index => index === 5));
  assert.ok(green, 'a color remains available even when it has no complete observed black-to-white scale');
  assert.equal(green.index, 31, 'shared pairs retain their legacy exclusion ID');
  const orange = state.virtualPalette.find(color => color.colorIndices.every(index => index === 8));
  assert.equal(orange.index, 46);
  const grayShadow = state.virtualPalette.find(color => color.colorIndices.join('-') === '0-11');
  assert.ok(grayShadow, 'observed black/dark-gray dithering must be available');
  assert.ok(grayShadow.index >= 69 && grayShadow.index <= 105);
});

test('virtual mode and base palette switches retain exclusion IDs and resolve active C64 component colors', () => {
  const state = createC64PaletteState('colodore', 'talent');
  const active = state.virtualPalette;
  const { computed, talent } = state.virtualPalettes;
  const grayShadow = talent.find(color => color.colorIndices.join('-') === '0-11');
  const pairIndex = grayShadow.index;
  const excludedIndices = [...new Set([...computed, ...talent].map(color => color.index))]
    .filter(index => index !== pairIndex);
  const orange = talent.find(color => color.colorIndices.every(index => index === 8));
  state.setVirtualColorMode('computed');
  assert.strictEqual(state.virtualPalette, active);
  assert.equal(active.some(color => color.index === pairIndex), false);
  state.select('peptoette-a');
  assert.equal(state.virtualColorMode, 'computed');
  assert.deepEqual(Array.from(grayShadow.rgb), [55, 55, 55], 'inactive catalogs must follow the base palette');
  state.setVirtualColorMode('talent');
  assert.strictEqual(state.virtualPalette, active);
  assert.strictEqual(state.virtualPalettes.computed, computed);
  assert.strictEqual(state.virtualPalettes.talent, talent);
  assert.strictEqual(talent.find(color => color.index === pairIndex), grayShadow);
  assert.strictEqual(talent.find(color => color.index === orange.index), orange);
  assert.equal(state.id, 'peptoette-a');
  assert.equal(grayShadow.index, pairIndex);

  const source = new ImageData(2, 2);
  source.data.set([0, 0, 0, 255, 255, 255, 255, 255, 12, 34, 56, 255, 91, 81, 71, 255]);
  const mapped = mapToTalentVirtualPalette(source, active, { excludedIndices });
  assert.deepEqual(Array.from(mapped.virtualIndices), Array(4).fill(pairIndex));
  assert.deepEqual(Array.from(mapped.pixels.data), Array(4).fill([55, 55, 55, 255]).flat());
  const resolved = resolveVirtualPaletteColors(mapped, active, state.palette, 'lines');
  assert.deepEqual(Array.from(resolved.data), [0, 0, 0, 255, 0, 0, 0, 255,
    78, 78, 78, 255, 78, 78, 78, 255]);
  assert.throws(() => state.setVirtualColorMode('unknown'), /virtual color mode/i);
  assert.equal(state.virtualColorMode, 'talent');
  assert.equal(state.id, 'peptoette-a');
});

test('switching palettes refreshes held control colors, virtual colors, and conversion brightness data', () => {
  const state = createC64PaletteState();
  const { palette, brightnessBands, virtualPalette } = state;
  const blue = palette[6];
  const virtualBlue = virtualPalette.find(color => color.colorIndices.every(index => index === 6));
  const source = new ImageData(1, 1);
  source.data.set([0, 0, 0, 255]);

  for (const [id, blueRgb, brownRgb] of [
    ['pepto', [53, 40, 121], [67, 57, 0]],
    ['colodore', [39, 36, 196], [94, 53, 0]]
  ]) {
    state.select(id);
    assert.strictEqual(palette[6], blue);
    assert.strictEqual(virtualPalette[virtualBlue.index], virtualBlue);
    assert.deepEqual(Array.from(blue.rgb), blueRgb);
    assert.deepEqual(Array.from(virtualBlue.rgb), blueRgb);

    const converted = convertTwoColorHires(source, palette, [6, 1], 0);
    assert.deepEqual(Array.from(converted.data), [...blueRgb, 255]);
    const mapped = mapToIfliVirtualPalette(converted, virtualPalette, brightnessBands, 0, {
      excludedIndices: virtualPalette.filter(color => color.index !== virtualBlue.index).map(color => color.index)
    });
    assert.equal(mapped.virtualIndices[0], virtualBlue.index);
    assert.deepEqual(Array.from(mapped.pixels.data), [...blueRgb, 255]);

    const blueLab = rgbToOklab(...blueRgb);
    const brownLab = rgbToOklab(...brownRgb);
    const bandBlue = brightnessBands[1].colors.find(entry => entry.color.index === 6);
    for (const channel of ['lightness', 'a', 'b']) {
      assert.ok(Math.abs(bandBlue.lab[channel] - blueLab[channel]) < 1e-12, `${id} blue ${channel}`);
    }
    assert.ok(Math.abs(brightnessBands[1].lightness - (blueLab.lightness + brownLab.lightness) / 2) < 1e-12);
  }
});
