const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const context = vm.createContext({ Uint8Array });
vm.runInContext(fs.readFileSync(path.join(__dirname, '../afli-export.js'), 'utf8'), context);
const encodeAfli = context.encodeAfli;

function fixture() {
  const palette = Array.from({ length: 16 }, (_, index) => ({ index, rgb: [index, index + 16, index + 32] }));
  const data = new Uint8ClampedArray(320 * 200 * 4);
  const rowColors = new Uint8Array(16000);
  for (let pixel = 0; pixel < 64000; pixel += 1) data.set([...palette[9].rgb, 255], pixel * 4);
  for (let row = 0; row < 8000; row += 1) rowColors.set([9, 7], row * 2);
  return { palette, result: { pixels: { width: 320, height: 200, data }, rowColors } };
}

function setTileRow(result, palette, tile, row, first, second, colors) {
  result.rowColors.set([first, second], (tile * 8 + row) * 2);
  const x = tile % 40 * 8;
  const y = Math.floor(tile / 40) * 8 + row;
  colors.forEach((color, column) => result.pixels.data.set([...palette[color].rgb, 255], (y * 320 + x + column) * 4));
}

test('writes the AFLI-editor banks, bitmap bits, and exact recognized length', () => {
  const { result, palette } = fixture();
  setTileRow(result, palette, 0, 0, 1, 2, [1, 2, 1, 2, 2, 1, 2, 1]);
  setTileRow(result, palette, 0, 7, 3, 4, [4, 3, 3, 3, 3, 4, 4, 4]);
  setTileRow(result, palette, 40, 0, 5, 6, [6, 6, 5, 6, 5, 6, 5, 5]);
  setTileRow(result, palette, 39, 3, 0, 13, [0, 0, 0, 13, 13, 13, 0, 13]);
  setTileRow(result, palette, 500, 4, 8, 10, [10, 8, 10, 8, 10, 8, 10, 8]);
  setTileRow(result, palette, 999, 7, 14, 15, [14, 15, 15, 15, 15, 15, 15, 14]);
  const sourcePixels = new Uint8ClampedArray(result.pixels.data);
  const sourceRows = new Uint8Array(result.rowColors);
  const file = encodeAfli(result, [...palette].reverse());
  assert.equal(file.length, 16385);
  assert.deepEqual(Array.from(file.subarray(0, 2)), [0, 0x40]);
  // Literal offsets come from the external AFLI-editor/RECOIL binary contract.
  for (const [offset, expected] of [
    [2, 0x12], [7170, 0x34], [42, 0x56], [3113, 0x0d], [4598, 0x8a], [8169, 0xef],
    [8194, 0xa5], [8201, 0x78], [8514, 0x2b], [8509, 0xe2], [12198, 0x55], [16193, 0x81]
  ]) assert.equal(file[offset], expected, `file byte ${offset}`);
  for (let bank = 0; bank < 8; bank += 1) {
    assert.ok(file.subarray(2 + bank * 1024 + 1000, 2 + (bank + 1) * 1024).every(value => value === 0));
  }
  assert.equal(file.subarray(16194).length, 191);
  assert.ok(file.subarray(16194).every(value => value === 0));

  // Decode all 320 columns, independently of the encoder's iteration order.
  for (let y = 0; y < 200; y += 1) {
    for (let x = 0; x < 320; x += 1) {
      const tile = Math.floor(y / 8) * 40 + Math.floor(x / 8);
      const screen = file[2 + (y % 8) * 1024 + tile];
      const set = file[8194 + tile * 8 + y % 8] & (128 >> (x % 8));
      const color = set ? screen >> 4 : screen & 15;
      const offset = (y * 320 + x) * 4;
      assert.deepEqual(Array.from(result.pixels.data.subarray(offset, offset + 4)), [...palette[color].rgb, 255]);
    }
  }
  assert.deepEqual(result.pixels.data, sourcePixels);
  assert.deepEqual(result.rowColors, sourceRows);
});

test('rejects unsupported geometry, row colors, and ambiguous palettes', () => {
  for (const [mutate, message] of [
    [({ result }) => { result.pixels.width = 319; }, /320 × 200/],
    [({ result }) => { result.rowColors = new Uint8Array(15999); }, /fitted row colors/],
    [({ result }) => { result.rowColors[15999] = 16; }, /row colors must/],
    [({ palette }) => { palette[15].index = 0; }, /unique C64 color indices/],
    [({ palette }) => { palette[15].rgb = palette[0].rgb; }, /unique C64 color indices/]
  ]) {
    const data = fixture();
    mutate(data);
    assert.throws(() => encodeAfli(data.result, data.palette), message);
  }
});

test('rejects pixels that cannot preserve the fitted preview color', () => {
  for (const [mutate, message] of [
    [({ result }) => { result.pixels.data[3] = 254; }, /opaque colors/],
    [({ result }) => { result.pixels.data[0] = 255; }, /opaque colors/],
    [({ result, palette }) => { result.pixels.data.set([...palette[10].rgb, 255], 0); }, /does not match its fitted colors/]
  ]) {
    const data = fixture();
    mutate(data);
    assert.throws(() => encodeAfli(data.result, data.palette), message);
  }
});
