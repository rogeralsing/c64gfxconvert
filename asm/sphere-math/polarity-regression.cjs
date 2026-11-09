'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createModel } = require('./native-model.cjs');

test('analytic tiles preserve their filled side across the complete rotation phase period', () => {
  const model = createModel();
  let checked = 0;
  for (let spin = 0; spin < 128; spin++) {
    const output = model.reconstruct(model.render(spin, 0));
    const reference = model.reference(spin).pixels;
    for (let tile = 0; tile < model.manifest.tileCount; tile++) {
      const record = tile * 13;
      // Sparse silhouette/pole approximations have a separate shape limitation.
      if (model.assets.records[record + 2] & 1) continue;
      const cell = model.assets.records[record] + 256 * model.assets.records[record + 1];
      const left = cell % 40 * 8, top = Math.floor(cell / 40) * 8;
      let errors = 0;
      for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
        const index = (top + y) * 320 + left + x;
        errors += Number(output[index] !== reference[index]);
      }
      // A complement wins precisely when more than half the pixels disagree.
      // Small contour errors are allowed; reversing the entire fill is not.
      assert.ok(errors <= 32,
        `spin=${spin}, cell=${cell} (${left},${top}): ${errors}/64 wrong; inverted glyph has ${64-errors}/64 wrong`);
      checked++;
    }
  }
  assert.ok(checked > 0, 'The real analytic tile path must be exercised');
});
