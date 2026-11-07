const assert = require('node:assert/strict');
const test = require('node:test');
const { ImageData, palette, createContext } = require('./fixtures/sprite-images.cjs');
const { convertTwoColorHires, compositeTwoColorHires } = createContext(['two-color.js']);

function solid(gray, alpha = 255) {
  const image = new ImageData(4, 4);
  for (let offset = 0; offset < image.data.length; offset += 4) image.data.set([gray, gray, gray, alpha], offset);
  return image;
}

function colors(image) {
  return Array.from({ length: image.width * image.height }, (_, pixel) =>
    Array.from(image.data.subarray(pixel * 4, pixel * 4 + 3)));
}

test('source luma drives the two-color threshold regardless of output hue or brightness', () => {
  const source = new ImageData(new Uint8ClampedArray([
    0, 0, 0, 255, 127, 127, 127, 255, 128, 128, 128, 255,
    255, 255, 255, 255, 0, 0, 255, 128, 0, 255, 0, 255,
    17, 29, 41, 0
  ]), 7, 1);
  const before = new Uint8ClampedArray(source.data);
  for (const pair of [[2, 6], [6, 2], [0, 1], [13, 7]]) {
    const result = convertTwoColorHires(source, palette, pair, 0);
    assert.deepEqual(colors(result).slice(0, 6), [0, 0, 1, 1, 0, 1].map(slot => palette[pair[slot]].rgb));
    assert.equal(result.data[19], 128);
    assert.deepEqual(Array.from(result.data.slice(24)), [17, 29, 41, 0]);
    assert.deepEqual(source.data, before);
    assert.equal(result.width, source.width);
    assert.equal(result.height, source.height);
  }
});

test('ordered dither spans quarter tones while zero strength keeps a hard threshold', () => {
  for (const [gray, orderedCount, thresholdCount] of [
    [0, 0, 0], [64, 4, 0], [128, 8, 16], [191, 12, 16], [255, 16, 16]
  ]) {
    const source = solid(gray);
    for (const [strength, expected] of [[1, orderedCount], [0, thresholdCount]]) {
      const result = convertTwoColorHires(source, palette, [0, 1], strength);
      assert.equal(colors(result).filter(rgb => rgb[0] === 255).length, expected, `${gray}, ${strength}`);
    }
  }
  assert.equal(colors(convertTwoColorHires(solid(96), palette, [0, 1], 0.5))
    .filter(rgb => rgb[0] === 255).length, 4);
});

test('transparent layers reveal lower layers without introducing a third color', () => {
  const below = convertTwoColorHires(solid(255), palette, [6, 13]);
  const above = convertTwoColorHires(solid(0, 128), palette, [6, 13]);
  const result = compositeTwoColorHires([below, above], 4, 4, palette[6].rgb);
  assert.equal(colors(result).filter(rgb => rgb.join() === palette[6].rgb.join()).length, 8);
  assert.equal(colors(result).filter(rgb => rgb.join() === palette[13].rgb.join()).length, 8);
  assert.ok(Array.from(result.data).every((value, offset) => offset % 4 !== 3 || value === 255));
  assert.deepEqual(colors(compositeTwoColorHires([convertTwoColorHires(solid(255, 0), palette, [6, 13])],
    4, 4, palette[6].rgb)), Array.from({ length: 16 }, () => palette[6].rgb));
});
