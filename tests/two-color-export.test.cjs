const assert = require('node:assert/strict');
const test = require('node:test');
const { ImageData, palette, createContext } = require('./fixtures/sprite-images.cjs');
const { encodeTwoColorHiresArt } = createContext(['two-color-export.js']);

function fixture(pair = [6, 13]) {
  const pixels = new ImageData(320, 200);
  for (let offset = 0; offset < pixels.data.length; offset += 4) {
    pixels.data.set([...palette[pair[0]].rgb, 255], offset);
  }
  return { pixels, colorIndices: pair };
}

test('Art Studio export preserves all pixels and both selected colors in the external file layout', () => {
  const result = fixture();
  for (const [x, y] of [[0, 0], [7, 0], [8, 0], [0, 7], [319, 7], [0, 8], [123, 99], [319, 199]]) {
    result.pixels.data.set([...palette[13].rgb, 255], (y * 320 + x) * 4);
  }
  const before = new Uint8ClampedArray(result.pixels.data);
  const file = encodeTwoColorHiresArt(result, [...palette].reverse());
  assert.equal(file.length, 9009);
  assert.deepEqual(Array.from(file.slice(0, 2)), [0, 0x20]);
  for (const [offset, expected] of [[2, 0x81], [10, 0x80], [9, 0x80], [321, 0x01],
    [322, 0x80], [3965, 0x10], [8001, 0x01]]) assert.equal(file[offset], expected, `byte ${offset}`);
  assert.ok(file.subarray(8002, 9002).every(byte => byte === 0xd6));
  assert.equal(file[9002], 6);
  assert.ok(file.subarray(9003).every(byte => byte === 0));

  // Independent tile/row traversal decodes the Art Studio/VIC-II storage contract.
  for (let tile = 0; tile < 1000; tile += 1) {
    const screen = file[8002 + tile];
    for (let row = 0; row < 8; row += 1) {
      const bits = file[2 + tile * 8 + row];
      for (let bit = 0; bit < 8; bit += 1) {
        const color = bits & (0x80 >> bit) ? screen >> 4 : screen & 15;
        const x = tile % 40 * 8 + bit;
        const y = Math.floor(tile / 40) * 8 + row;
        const offset = (y * 320 + x) * 4;
        assert.deepEqual(Array.from(result.pixels.data.slice(offset, offset + 4)), [...palette[color].rgb, 255]);
      }
    }
  }
  assert.deepEqual(result.pixels.data, before);
});

test('a repeated selected color remains a valid solid hires image', () => {
  const file = encodeTwoColorHiresArt(fixture([5, 5]), palette);
  assert.ok(file.subarray(2, 8002).every(byte => byte === 0));
  assert.ok(file.subarray(8002, 9002).every(byte => byte === 0x55));
});

test('export rejects invalid geometry, selected colors, transparency, and off-palette pixels', () => {
  for (const [mutate, message] of [
    [result => { result.pixels.width = 160; }, /320 × 200/],
    [result => { result.pixels.data = new Uint8ClampedArray(4); }, /320 × 200/],
    [result => { result.colorIndices = [0]; }, /two C64 palette colors/],
    [result => { result.colorIndices = [6, 16]; }, /two C64 palette colors/],
    [result => { result.pixels.data[3] = 254; }, /opaque and match/],
    [result => { result.pixels.data.set([...palette[5].rgb, 255]); }, /opaque and match/]
  ]) {
    const result = fixture();
    mutate(result);
    assert.throws(() => encodeTwoColorHiresArt(result, palette), message);
  }
});
