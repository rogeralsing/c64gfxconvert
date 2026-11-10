'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createModel } = require('./native-model.cjs');

test('every lit pixel stays inside the mathematical sphere in both native modes', () => {
  const model = createModel();
  const { width, height, radius } = model.manifest.geometry;
  const exterior = [];
  // Independent screen-space geometry; this does not read the model's reference.
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const dx = x + 0.5 - width / 2, dy = y + 0.5 - height / 2;
    if (dx * dx + dy * dy > radius * radius) exterior.push(y * width + x);
  }
  for (const mode of [0, 1]) for (let spin = 0; spin < 128; spin++) {
    const pixels = model.reconstruct(model.render(spin, mode));
    for (const index of exterior) {
      assert.equal(pixels[index], 0,
        `mode=${mode}, spin=${spin}: stray pixel at (${index % width},${Math.floor(index / width)}) outside radius ${radius}`);
    }
  }
});
