const assert = require('node:assert/strict');
const test = require('node:test');
const { ImageData, createContext } = require('./fixtures/sprite-images.cjs');
const { applySourceLevels } = createContext(['source-levels.js']);

function pixels(colors) {
  return new ImageData(new Uint8ClampedArray(colors.flat()), colors.length, 1);
}

test('neutral source levels preserve every channel and alpha exactly', () => {
  const source = pixels([[0, 0, 0, 255], [17, 96, 231, 128], [255, 255, 255, 255], [90, 20, 45, 0]]);
  const before = new Uint8ClampedArray(source.data);
  const result = applySourceLevels(source);
  assert.deepEqual(result.data, before);
  assert.deepEqual(source.data, before);
});

test('black and white points clip and stretch source RGB while preserving transparency and the original image', () => {
  const source = pixels([[32, 64, 96, 255], [64, 128, 192, 128], [192, 224, 255, 255], [77, 88, 99, 0]]);
  const before = new Uint8ClampedArray(source.data);
  const result = applySourceLevels(source, { blackPoint: 64, whitePoint: 192 });
  assert.deepEqual(Array.from(result.data), [0, 0, 64, 255, 0, 128, 255, 128, 255, 255, 255, 255, 77, 88, 99, 0]);
  assert.deepEqual(source.data, before);
  assert.equal(result.width, source.width);
  assert.equal(result.height, source.height);
});

test('midtone gamma lifts or darkens the source without moving its black and white endpoints', () => {
  const source = pixels([[0, 64, 128, 255], [255, 128, 64, 128]]);
  assert.deepEqual(Array.from(applySourceLevels(source, { gamma: 2 }).data), [0, 128, 181, 255, 255, 181, 128, 128]);
  assert.deepEqual(Array.from(applySourceLevels(source, { gamma: 0.5 }).data), [0, 16, 64, 255, 255, 64, 16, 128]);
  assert.throws(() => applySourceLevels(source, { blackPoint: 64, whitePoint: 64 }), { name: 'RangeError' });
});
