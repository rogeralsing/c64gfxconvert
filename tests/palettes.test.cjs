const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { ImageData, createContext, rgbToOklab } = require('./fixtures/sprite-images.cjs');

const { createC64PaletteState, convertTwoColorHires, mapToIfliVirtualPalette } =
  createContext(['ifli.js', 'palettes.js', 'two-color.js']);

function referencePalette(file) {
  return fs.readFileSync(path.join(__dirname, '../palettes', file), 'utf8').split('\n')
    .map(line => line.trim()).filter(line => /^[\da-f]{2}\s+[\da-f]{2}\s+[\da-f]{2}$/i.test(line))
    .map(line => line.split(/\s+/).map(channel => parseInt(channel, 16)));
}

test('palette presets match their shipped VICE references and return to the Colodore default', () => {
  const state = createC64PaletteState();
  assert.equal(state.id, 'colodore');
  for (const [id, file] of [
    ['colodore', 'colodore.vpl'], ['pepto', 'pepto-pal.vpl'], ['colodore', 'colodore.vpl']
  ]) {
    state.select(id);
    const reference = referencePalette(file);
    assert.equal(reference.length, 16);
    assert.deepEqual(Array.from(state.palette, color => Array.from(color.rgb)), reference);
  }
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
