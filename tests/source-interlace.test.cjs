const assert = require('node:assert/strict');
const test = require('node:test');
const { ImageData, createContext } = require('./fixtures/sprite-images.cjs');
const { applyInterlace } = createContext(['source-interlace.js']);

function image(width, height, rgba = [0, 0, 0, 255]) {
  const result = new ImageData(width, height);
  for (let offset = 0; offset < result.data.length; offset += 4) result.data.set(rgba, offset);
  return result;
}

function mask(source) {
  return Array.from({ length: source.height }, (_, y) => Array.from({ length: source.width }, (_, x) =>
    source.data[(y * source.width + x) * 4] ? '#' : '.').join(''));
}

test('default interlace retains alternate odd rows and the original lift and darken arithmetic', () => {
  const source = image(2, 3, [20, 100, 220, 127]);
  const before = new Uint8ClampedArray(source.data);
  assert.deepEqual(Array.from(applyInterlace(source, 0.5).data), [
    20, 100, 220, 127, 20, 100, 220, 127,
    138, 178, 238, 127, 138, 178, 238, 127,
    20, 100, 220, 127, 20, 100, 220, 127
  ]);
  assert.deepEqual(Array.from(applyInterlace(source, -0.5).data), [
    20, 100, 220, 127, 20, 100, 220, 127,
    10, 50, 110, 127, 10, 50, 110, 127,
    20, 100, 220, 127, 20, 100, 220, 127
  ]);
  assert.deepEqual(source.data, before);
});

test('spacing separates one-pixel horizontal lines instead of thickening the bands', () => {
  assert.deepEqual(mask(applyInterlace(image(5, 6), 1, { spacing: 3 })), [
    '.....', '#####', '.....', '.....', '#####', '.....'
  ]);
  assert.deepEqual(mask(applyInterlace(image(3, 2), 1, { spacing: 1 })), ['###', '###']);
});

test('diagonals rise and fall through the same grid with correct wrapping at negative coordinates', () => {
  const source = image(5, 5);
  assert.deepEqual(mask(applyInterlace(source, 1, { spacing: 3, direction: 'diagonal-up' })), [
    '.#..#', '#..#.', '..#..', '.#..#', '#..#.'
  ]);
  assert.deepEqual(mask(applyInterlace(source, 1, { spacing: 3, direction: 'diagonal-down' })), [
    '..#..', '#..#.', '.#..#', '..#..', '#..#.'
  ]);
  assert.deepEqual(mask(applyInterlace(image(4, 3), 1,
    { spacing: 3, direction: 'diagonal-down', phase: -1 })), [
    '.#..', '..#.', '#..#'
  ]);
});

test('hires diagonals keep each logical line two physical pixels wide and one row high', () => {
  assert.deepEqual(mask(applyInterlace(image(8, 4), 1,
    { spacing: 3, direction: 'diagonal-up', pixelWidth: 2 })), [
    '..##....', '##....##', '....##..', '..##....'
  ]);
});

test('interlace preserves transparent RGB and alpha, leaves endpoints bounded, and is inert at zero', () => {
  const source = image(2, 2, [30, 90, 200, 255]);
  source.data.set([91, 72, 53, 0], 8);
  source.data.set([255, 0, 128, 31], 12);
  const before = new Uint8ClampedArray(source.data);
  assert.strictEqual(applyInterlace(source, 0), source);
  const lifted = applyInterlace(source, 1);
  const darkened = applyInterlace(source, -1);
  assert.deepEqual(Array.from(lifted.data.slice(8)), [91, 72, 53, 0, 255, 255, 255, 31]);
  assert.deepEqual(Array.from(darkened.data.slice(8)), [91, 72, 53, 0, 0, 0, 0, 31]);
  assert.deepEqual(source.data, before);
  assert.equal(lifted.width, 2);
  assert.equal(lifted.height, 2);
});

test('interlace rejects unsupported strengths and patterns before rendering', () => {
  const source = image(1, 1);
  for (const amount of [-1.01, 1.01, NaN, Infinity]) {
    assert.throws(() => applyInterlace(source, amount), { name: 'RangeError' });
  }
  for (const options of [
    { spacing: 0 }, { spacing: 33 }, { spacing: 2.5 }, { direction: 'vertical' },
    { pixelWidth: 0 }, { pixelWidth: 3 }, { phase: 0.5 }
  ]) {
    assert.throws(() => applyInterlace(source, 0.5, options), { name: 'RangeError' });
  }
});
