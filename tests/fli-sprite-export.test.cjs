const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { TextEncoder } = require('node:util');

const context = vm.createContext({ Uint8Array, TextEncoder });
for (const name of ['afli-sprite-export.js', 'fli-sprite-export.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', name), 'utf8'), context);
}
const { encodeFliSpriteLayers } = context;

function fixture() {
  const palette = Array.from({ length: 16 }, (_, index) => ({ index, name: `Color ${index}`, rgb: [index, index + 16, index + 32] }));
  const rowColors = new Uint8Array(16000);
  for (let row = 0; row < 8000; row += 1) rowColors.set([4, 8], row * 2);
  const result = {
    pixels: { width: 320, height: 200, data: new Uint8ClampedArray(256000) },
    fli: {
      pixels: { width: 160, height: 200, data: new Uint8ClampedArray(128000) },
      backgroundColorIndex: 6, rowColors, tileColors: new Uint8Array(1000).fill(9)
    },
    spriteMask: new Uint8Array(64000), spriteColorIndex: 1
  };
  const data = { palette, result };
  for (let tile = 0; tile < 1000; tile += 1) {
    for (let row = 0; row < 8; row += 1) setRow(data, tile, row, 4, 8, [0, 1, 2, 3]);
  }
  return data;
}

function setRow({ result, palette }, tile, row, first, second, codes) {
  const fli = result.fli;
  fli.rowColors.set([first, second], (tile * 8 + row) * 2);
  const colors = [6, first, second, fli.tileColors[tile]];
  const y = Math.floor(tile / 40) * 8 + row;
  codes.forEach((code, column) => {
    const x = tile % 40 * 4 + column;
    const rgba = [...palette[colors[code]].rgb, 255];
    fli.pixels.data.set(rgba, (y * 160 + x) * 4);
    result.pixels.data.set(rgba, (y * 320 + x * 2) * 4);
    result.pixels.data.set(rgba, (y * 320 + x * 2 + 1) * 4);
  });
}

// ZIP framing and CRC32 have their primary tests in afli-sprite-export.test.cjs.
// Read the shared stored container here to test the distinct FLI RAM contract.
function entries(archive) {
  const zip = Buffer.from(archive);
  const files = new Map();
  let offset = 0;
  while (zip.readUInt32LE(offset) === 0x04034b50) {
    assert.equal(zip.readUInt16LE(offset + 8), 0);
    const size = zip.readUInt32LE(offset + 18);
    const nameLength = zip.readUInt16LE(offset + 26);
    const start = offset + 30 + nameLength + zip.readUInt16LE(offset + 28);
    files.set(zip.toString('utf8', offset + 30, offset + 30 + nameLength), zip.subarray(start, start + size));
    offset = start + size;
  }
  assert.equal(zip.readUInt32LE(offset), 0x02014b50);
  return files;
}

test('exports real FLI RAM offsets and independently decodes all 32,000 wide pixels plus a hires mask', () => {
  const data = fixture();
  setRow(data, 0, 0, 1, 2, [0, 1, 2, 3]);
  setRow(data, 0, 7, 3, 4, [3, 2, 1, 0]);
  setRow(data, 40, 0, 5, 7, [2, 3, 0, 1]);
  setRow(data, 39, 3, 0, 13, [1, 1, 2, 0]);
  setRow(data, 999, 7, 14, 15, [3, 0, 0, 3]);
  data.result.fli.tileColors[500] = 10;
  for (let row = 0; row < 8; row += 1) setRow(data, 500, row, 4, 8, [0, 1, 2, 3]);
  for (const [x, y] of [[112, 0], [113, 199], [303, 199]]) data.result.spriteMask[y * 320 + x] = 1;
  const before = structuredClone(data);
  const files = entries(encodeFliSpriteLayers(data.result, [...data.palette].reverse(), 6));
  assert.deepEqual([...files.keys()], ['bitmap.bin', 'screen.bin', 'color-ram.bin', 'sprites.bin', 'manifest.json']);
  const bitmap = files.get('bitmap.bin');
  const screens = files.get('screen.bin');
  const colors = files.get('color-ram.bin');
  assert.equal(bitmap.length, 8000);
  assert.equal(screens.length, 8192);
  assert.equal(colors.length, 1000);
  for (const [offset, value] of [[0, 0x12], [7168, 0x34], [40, 0x57], [3111, 0x0d], [8167, 0xef]]) {
    assert.equal(screens[offset], value, `screen byte ${offset}`);
  }
  for (const [offset, value] of [[0, 0x1b], [7, 0xe4], [320, 0xb1], [315, 0x58], [7999, 0xc3]]) {
    assert.equal(bitmap[offset], value, `bitmap byte ${offset}`);
  }
  assert.equal(colors[500], 10);
  for (let bank = 0; bank < 8; bank += 1) {
    assert.ok(screens.subarray(bank * 1024 + 1000, (bank + 1) * 1024).every(value => value === 0));
  }
  for (let y = 0; y < 200; y += 1) {
    for (let x = 0; x < 160; x += 1) {
      const tile = Math.floor(y / 8) * 40 + Math.floor(x / 4);
      const screen = screens[(y % 8) * 1024 + tile];
      const code = bitmap[tile * 8 + y % 8] >> (6 - 2 * (x % 4)) & 3;
      const color = [6, screen >> 4, screen & 15, colors[tile]][code];
      const offset = (y * 160 + x) * 4;
      assert.deepEqual([...data.result.fli.pixels.data.subarray(offset, offset + 4)], [...data.palette[color].rgb, 255]);
    }
  }
  const mask = files.get('sprites.bin');
  assert.equal(mask.length, 4800);
  assert.equal(mask[0], 0x80);
  assert.equal(mask[199 * 24], 0x40, 'one odd hires column is not expanded into a wide pixel');
  assert.equal(mask[4799], 1);
  const manifest = JSON.parse(files.get('manifest.json').toString('utf8'));
  assert.equal(manifest.format, 'c64-fli-sprite-layers');
  assert.equal(manifest.version, 1);
  assert.deepEqual(manifest.image, { width: 160, height: 200, pixelAspectRatio: [2, 1] });
  assert.deepEqual(manifest.canvas, { width: 320, height: 200 });
  assert.deepEqual(manifest.backgroundColor, { index: 6, name: 'Color 6', rgb: [6, 22, 38] });
  assert.deepEqual(manifest.spriteColor, { index: 1, name: 'Color 1', rgb: [1, 17, 33] });
  assert.equal(manifest.files.screen, 'screen.bin');
  assert.equal(manifest.mask.hardwareFrames, false);
  assert.deepEqual(data, before);
});

test('encodes duplicate background, tile, and row colors with the first valid multicolor code', () => {
  const data = fixture();
  data.result.fli.tileColors[0] = 6;
  for (let row = 0; row < 8; row += 1) setRow(data, 0, row, 4, 8, [0, 1, 2, 3]);
  setRow(data, 0, 0, 6, 6, [3, 2, 1, 0]);
  setRow(data, 1, 0, 4, 4, [2, 1, 3, 0]);
  setRow(data, 2, 0, 6, 9, [1, 3, 2, 0]);
  const bitmap = entries(encodeFliSpriteLayers(data.result, data.palette, 6)).get('bitmap.bin');
  assert.deepEqual([bitmap[0], bitmap[8], bitmap[16]], [0x00, 0x5c, 0x28]);
});

test('rejects incorrect geometry, palette, background, row/tile allocations, and masks', () => {
  for (const [mutate, background, message] of [
    [({ result }) => { result.pixels.width = 160; }, 6, /320 × 200 canvas/],
    [({ result }) => { result.fli.pixels.width = 320; }, 6, /160 × 200 FLI image/],
    [({ result }) => { result.fli.tileColors = new Uint8Array(999); }, 6, /fitted colors/],
    [({ result }) => { result.spriteMask = new Uint8Array(32000); }, 6, /fitted colors/],
    [({ palette }) => { palette[15].rgb = palette[0].rgb; }, 6, /unique C64/],
    [() => {}, 7, /background must match/],
    [({ result }) => { result.fli.tileColors[999] = 16; }, 6, /tile colors must/],
    [({ result }) => { result.fli.rowColors[15999] = 16; }, 6, /row colors must/],
    [({ result }) => { result.fli.pixels.data[3] = 254; }, 6, /opaque colors/],
    [({ result, palette }) => { result.fli.pixels.data.set([...palette[15].rgb, 255], 0); }, 6, /does not match its fitted colors/],
    [({ result }) => { result.spriteColorIndex = 16; }, 6, /sprite color/],
    [({ result }) => { result.spriteMask[112] = 2; }, 6, /0 or 1/],
    [({ result }) => { result.spriteMask[304] = 1; }, 6, /columns 112 through 303/]
  ]) {
    const data = fixture();
    mutate(data);
    assert.throws(() => encodeFliSpriteLayers(data.result, data.palette, background), message);
  }
});
