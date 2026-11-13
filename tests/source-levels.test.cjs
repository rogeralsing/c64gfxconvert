const assert = require('node:assert/strict');
const test = require('node:test');
const { ImageData, createContext } = require('./fixtures/sprite-images.cjs');
const { applySourceLevels, createSourceCurveLookup } = createContext(['source-levels.js']);

function pixels(colors) {
  return new ImageData(new Uint8ClampedArray(colors.flat()), colors.length, 1);
}

test('neutral source levels preserve every channel and alpha exactly', () => {
  const source = pixels([[0, 0, 0, 255], [17, 96, 231, 128], [255, 255, 255, 255], [90, 20, 45, 0]]);
  const before = new Uint8ClampedArray(source.data);
  const result = applySourceLevels(source);
  assert.strictEqual(result, source);
  assert.deepEqual(result.data, before);
  assert.deepEqual(source.data, before);
});

test('editable curve points remap leveled RGB without altering alpha or transparent source bytes', () => {
  const source = pixels([[64, 96, 192, 128], [77, 88, 99, 0]]);
  const before = new Uint8ClampedArray(source.data);
  const result = applySourceLevels(source, {
    blackPoint: 64, whitePoint: 192, gamma: 2,
    curvePoints: [{ input: 0, output: 10 }, { input: 128, output: 64 }, { input: 255, output: 240 }]
  });
  assert.deepEqual(Array.from(result.data), [10, 64, 240, 128, 77, 88, 99, 0]);
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

test('tone curves pass through control points and preserve each segment including flat and inverted sections', () => {
  const curves = [
    [{ input: 0, output: 0 }, { input: 32, output: 8 }, { input: 96, output: 150 }, { input: 180, output: 200 }, { input: 255, output: 255 }],
    [{ input: 0, output: 0 }, { input: 64, output: 200 }, { input: 128, output: 80 }, { input: 192, output: 240 }, { input: 255, output: 255 }],
    [{ input: 0, output: 32 }, { input: 64, output: 32 }, { input: 128, output: 180 }, { input: 192, output: 180 }, { input: 255, output: 240 }],
    [{ input: 0, output: 255 }, { input: 255, output: 0 }]
  ];
  for (const curvePoints of curves) {
    const before = structuredClone(curvePoints);
    const lookup = createSourceCurveLookup(curvePoints);
    for (const point of curvePoints) assert.equal(lookup[point.input], point.output);
    for (let index = 0; index < curvePoints.length - 1; index += 1) {
      const first = curvePoints[index];
      const second = curvePoints[index + 1];
      for (let value = first.input; value <= second.input; value += 1) {
        assert.ok(lookup[value] >= Math.min(first.output, second.output));
        assert.ok(lookup[value] <= Math.max(first.output, second.output));
        if (value > first.input) {
          assert.ok(first.output < second.output ? lookup[value] >= lookup[value - 1]
            : first.output > second.output ? lookup[value] <= lookup[value - 1]
              : lookup[value] === first.output);
        }
      }
    }
    assert.deepEqual(curvePoints, before);
  }
  const peak = createSourceCurveLookup([{ input: 0, output: 0 }, { input: 128, output: 200 }, { input: 255, output: 100 }]);
  assert.equal(peak[127], 200, 'the curve should flatten smoothly into an edited peak');
  assert.equal(peak[129], 200, 'the edited peak should not introduce a sharp linear corner');
});

test('curve validation rejects unusable points and defaults to a neutral transfer', () => {
  assert.deepEqual(Array.from(createSourceCurveLookup()), Array.from({ length: 256 }, (_, input) => input));
  for (const curvePoints of [
    null, [], [{ input: 0, output: 0 }],
    [{ input: 1, output: 0 }, { input: 255, output: 255 }],
    [{ input: 0, output: 0 }, { input: 254, output: 255 }],
    [{ input: 0, output: 0 }, { input: 128, output: 90 }, { input: 128, output: 120 }, { input: 255, output: 255 }],
    [{ input: 0, output: 0 }, { input: 200, output: 180 }, { input: 100, output: 80 }, { input: 255, output: 255 }],
    [{ input: 0, output: -1 }, { input: 255, output: 255 }],
    [{ input: 0, output: 0 }, { input: 255, output: 256 }],
    [{ input: 0, output: 0 }, { input: 128.5, output: 128 }, { input: 255, output: 255 }],
    [{ input: 0, output: 0 }, { input: 128, output: NaN }, { input: 255, output: 255 }]
  ]) {
    assert.throws(() => createSourceCurveLookup(curvePoints), { name: 'RangeError' });
  }
});
