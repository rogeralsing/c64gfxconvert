const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../image-layout.js'), 'utf8'), context);
const { getC64ImageLeftInset, getC64ImagePlacement } = context;

test('all FLI modes fit wide images after exactly two reserved character columns', () => {
  for (const mode of ['fli', 'ifli', 'virtual-fli', 'afli', 'virtual-afli']) {
    assert.equal(getC64ImageLeftInset(mode), 16, mode);
    assert.deepEqual({ ...getC64ImagePlacement(1000, 500, mode) }, {
      x: 16, y: 24, width: 304, height: 152,
      leftInset: 16, availableWidth: 304, canvasWidth: 320, canvasHeight: 200
    }, mode);
  }
});

test('all FLI modes center tall images inside the remaining 304-pixel area', () => {
  for (const mode of ['fli', 'ifli', 'virtual-fli', 'afli', 'virtual-afli']) {
    assert.deepEqual({ ...getC64ImagePlacement(100, 400, mode) }, {
      x: 143, y: 0, width: 50, height: 200,
      leftInset: 16, availableWidth: 304, canvasWidth: 320, canvasHeight: 200
    }, mode);
  }
});

test('bitmap and hires images retain the entire 320 by 200 display area', () => {
  for (const mode of ['bitmap', 'hires']) {
    assert.equal(getC64ImageLeftInset(mode), 0, mode);
    assert.deepEqual({ ...getC64ImagePlacement(1000, 500, mode) }, {
      x: 0, y: 20, width: 320, height: 160,
      leftInset: 0, availableWidth: 320, canvasWidth: 320, canvasHeight: 200
    }, mode);
    assert.deepEqual({ ...getC64ImagePlacement(100, 400, mode) }, {
      x: 135, y: 0, width: 50, height: 200,
      leftInset: 0, availableWidth: 320, canvasWidth: 320, canvasHeight: 200
    }, mode);
  }
});

test('rejects nonpositive, nonfinite, and nonnumeric source dimensions', () => {
  for (const invalid of [0, -1, NaN, Infinity, -Infinity, undefined, '320']) {
    assert.throws(() => getC64ImagePlacement(invalid, 200, 'ifli'), /positive finite numbers/);
    assert.throws(() => getC64ImagePlacement(320, invalid, 'ifli'), /positive finite numbers/);
  }
});

test('omitted transform fields retain the original placement', () => {
  for (const transform of [{}, { scale: 1 }, { offsetX: 0 }, { offsetY: 0 },
    { scale: 1, offsetX: 0, offsetY: 0 },
    { scale: undefined, offsetX: undefined, offsetY: undefined }]) {
    assert.deepEqual({ ...getC64ImagePlacement(1000, 500, 'ifli', transform) }, {
      x: 16, y: 24, width: 304, height: 152,
      leftInset: 16, availableWidth: 304, canvasWidth: 320, canvasHeight: 200
    });
  }
});

test('zoom preserves aspect ratio and the center of the usable display area', () => {
  for (const { source, mode, scale, expected } of [
    { source: [1000, 500], mode: 'fli', scale: 2,
      expected: { x: -136, y: -52, width: 608, height: 304 } },
    { source: [1000, 500], mode: 'bitmap', scale: 0.5,
      expected: { x: 80, y: 60, width: 160, height: 80 } },
    { source: [100, 400], mode: 'hires', scale: 1.5,
      expected: { x: 122.5, y: -50, width: 75, height: 300 } }
  ]) {
    const { x, y, width, height } = getC64ImagePlacement(...source, mode, { scale });
    assert.deepEqual({ x, y, width, height }, expected, mode);
    assert.equal(width / height, source[0] / source[1], mode);
  }
});

test('pan uses display pixels after zoom in both full-width and reserved modes', () => {
  const transform = { scale: 2, offsetX: 24, offsetY: -10 };
  for (const { modes, expected } of [
    { modes: ['fli', 'ifli', 'virtual-fli', 'afli', 'virtual-afli'],
      expected: { x: -112, y: -62, width: 608, height: 304 } },
    { modes: ['bitmap', 'hires'],
      expected: { x: -136, y: -70, width: 640, height: 320 } }
  ]) {
    for (const mode of modes) {
      const { x, y, width, height } = getC64ImagePlacement(1000, 500, mode, transform);
      assert.deepEqual({ x, y, width, height }, expected, mode);
    }
  }
});

test('rejects nonpositive scales and nonfinite or nonnumeric transform values', () => {
  for (const scale of [0, -1, NaN, Infinity, -Infinity, null, '1', true]) {
    assert.throws(() => getC64ImagePlacement(320, 200, 'ifli', { scale }), /scale.*positive finite/);
  }
  for (const invalid of [NaN, Infinity, -Infinity, null, '1', true]) {
    assert.throws(() => getC64ImagePlacement(320, 200, 'ifli', { offsetX: invalid }), /offsets.*finite/);
    assert.throws(() => getC64ImagePlacement(320, 200, 'ifli', { offsetY: invalid }), /offsets.*finite/);
  }
});
