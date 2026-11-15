const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const context = vm.createContext({ Uint8Array });
vm.runInContext(fs.readFileSync(path.join(__dirname, '../fli-export.js'), 'utf8'), context);
const { encodeFli } = context;

function fixture() {
  const palette = Array.from({ length: 16 }, (_, index) => ({ index, rgb: [index, index + 16, index + 32] }));
  const result = {
    pixels: { width: 160, height: 200, data: new Uint8ClampedArray(128000) },
    backgroundColorIndex: 6,
    tileColors: new Uint8Array(1000).fill(9),
    rowColors: new Uint8Array(16000)
  };
  const data = { result, palette };
  for (let tile = 0; tile < 1000; tile += 1) {
    for (let row = 0; row < 8; row += 1) setRow(data, tile, row, 4, 8, [0, 1, 2, 3]);
  }
  return data;
}

function setRow({ result, palette }, tile, row, first, second, codes) {
  result.rowColors.set([first, second], (tile * 8 + row) * 2);
  const colors = [result.backgroundColorIndex, first, second, result.tileColors[tile]];
  const y = Math.floor(tile / 40) * 8 + row;
  codes.forEach((code, column) => {
    const x = tile % 40 * 4 + column;
    result.pixels.data.set([...palette[colors[code]].rgb, 255], (y * 160 + x) * 4);
  });
}

test('writes native FLIGraph headers and planes while preserving all 32,000 fitted pixels', () => {
  const data = fixture();
  setRow(data, 0, 0, 1, 2, [0, 1, 2, 3]);
  setRow(data, 0, 7, 3, 4, [3, 2, 1, 0]);
  setRow(data, 40, 0, 5, 7, [2, 3, 0, 1]);
  setRow(data, 39, 3, 0, 13, [1, 1, 2, 0]);
  setRow(data, 999, 7, 14, 15, [3, 0, 0, 3]);
  data.result.tileColors[500] = 11;
  for (let row = 0; row < 8; row += 1) setRow(data, 500, row, 8, 10, [2, 1, 0, 3]);
  const before = structuredClone(data);
  const file = encodeFli(data.result, [...data.palette].reverse());

  // Literal offsets and lengths are the external FLIGraph/RECOIL file contract.
  assert.equal(file.length, 17666);
  assert.deepEqual([...file.subarray(0, 2)], [0x00, 0x3b]);
  assert.ok(file.subarray(2, 258).every(value => value === 6), 'selected nonblack background survives every scanline');
  assert.equal(file[758], 11, 'Color RAM tile 500');
  assert.equal(file[1257], 9, 'Color RAM final tile');
  for (const [offset, value] of [
    [1282, 0x12], [8450, 0x34], [1322, 0x57], [4393, 0x0d], [5878, 0x8a], [9449, 0xef],
    [9474, 0x1b], [9481, 0xe4], [9794, 0xb1], [9789, 0x58], [13478, 0x93], [17473, 0xc3]
  ]) assert.equal(file[offset], value, `file byte ${offset}`);
  assert.ok(file.subarray(1258, 1282).every(value => value === 0), 'Color RAM padding');
  for (let bank = 0; bank < 8; bank += 1) {
    assert.ok(file.subarray(1282 + bank * 1024 + 1000, 1282 + (bank + 1) * 1024).every(value => value === 0));
  }
  assert.ok(file.subarray(17474).every(value => value === 0), 'full 192-byte bitmap padding');

  // Decode by display coordinates, independently of the encoder's iteration order.
  for (let y = 0; y < 200; y += 1) {
    for (let x = 0; x < 160; x += 1) {
      const tile = Math.floor(y / 8) * 40 + Math.floor(x / 4);
      const screen = file[1282 + (y % 8) * 1024 + tile];
      const code = file[9474 + tile * 8 + y % 8] >> (6 - 2 * (x % 4)) & 3;
      const color = [file[2 + y], screen >> 4, screen & 15, file[258 + tile]][code];
      const offset = (y * 160 + x) * 4;
      assert.deepEqual([...data.result.pixels.data.subarray(offset, offset + 4)], [...data.palette[color].rgb, 255]);
    }
  }
  assert.deepEqual(data, before);
});

test('keeps repeated background, row, and tile colors representable with deterministic codes', () => {
  const data = fixture();
  data.result.tileColors[0] = 6;
  for (let row = 0; row < 8; row += 1) setRow(data, 0, row, 4, 8, [0, 1, 2, 3]);
  setRow(data, 0, 0, 6, 6, [3, 2, 1, 0]);
  setRow(data, 1, 0, 4, 4, [2, 1, 3, 0]);
  setRow(data, 2, 0, 6, 9, [1, 3, 2, 0]);
  const file = encodeFli(data.result, data.palette);
  assert.deepEqual([file[9474], file[9482], file[9490]], [0x00, 0x5c, 0x28]);
});

test('rejects unsupported geometry, invalid fitted allocations, and ambiguous palettes', () => {
  for (const [mutate, message] of [
    [({ result }) => { result.pixels.width = 320; }, /160 × 200/],
    [({ result }) => { result.pixels.data = new Uint8ClampedArray(127999); }, /160 × 200/],
    [({ result }) => { result.tileColors = new Uint8Array(999); }, /fitted/],
    [({ result }) => { result.rowColors = new Uint8Array(15999); }, /fitted/],
    [({ result }) => { result.backgroundColorIndex = 16; }, /background/],
    [({ result }) => { result.tileColors[999] = 16; }, /tile colors/],
    [({ result }) => { result.rowColors[15999] = 16; }, /row colors/],
    [({ palette }) => { palette.pop(); }, /16-color/],
    [({ palette }) => { palette[15].index = 0; }, /unique C64/],
    [({ palette }) => { palette[15].rgb = palette[0].rgb; }, /unique C64/]
  ]) {
    const data = fixture();
    mutate(data);
    assert.throws(() => encodeFli(data.result, data.palette), message);
  }
});

test('rejects pixels that would change the fitted preview when decoded', () => {
  for (const [mutate, message] of [
    [({ result }) => { result.pixels.data[3] = 254; }, /opaque colors/],
    [({ result }) => { result.pixels.data[0] = 255; }, /opaque colors/],
    [({ result, palette }) => { result.pixels.data.set([...palette[15].rgb, 255], 0); }, /does not match its fitted colors/]
  ]) {
    const data = fixture();
    mutate(data);
    assert.throws(() => encodeFli(data.result, data.palette), message);
  }
});
