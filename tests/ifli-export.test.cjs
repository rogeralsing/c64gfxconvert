const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const context = vm.createContext({ Uint8Array });
vm.runInContext(fs.readFileSync(path.join(__dirname, '../ifli-export.js'), 'utf8'), context);
const encodeFunPaintIfli = context.encodeFunPaintIfli;

function fixture() {
  const palette = Array.from({ length: 16 }, (_, index) => ({
    index,
    rgb: [index, index + 16, index + 32]
  }));
  const frames = Array.from({ length: 2 }, () => {
    const data = new Uint8ClampedArray(160 * 200 * 4);
    for (let offset = 0; offset < data.length; offset += 4) {
      data.set([...palette[9].rgb, 255], offset);
    }
    return { pixels: { width: 160, height: 200, data }, rowColors: new Uint8Array(16000) };
  });
  return {
    palette,
    result: { frames, backgroundColorIndex: 9, tileColors: new Uint8Array(1000).fill(7) }
  };
}

function setTileRow(result, palette, phase, tile, row, first, second, indices) {
  const frame = result.frames[phase];
  frame.rowColors[tile * 16 + row * 2] = first;
  frame.rowColors[tile * 16 + row * 2 + 1] = second;
  const x = tile % 40 * 4;
  const y = Math.floor(tile / 40) * 8 + row;
  indices.forEach((index, column) => {
    frame.pixels.data.set([...palette[index].rgb, 255], (y * 160 + x + column) * 4);
  });
}

test('writes the Fun Painter II binary contract across both phases and all screen pages', () => {
  const { result, palette } = fixture();
  result.tileColors[0] = 3;
  result.tileColors[999] = 15;
  setTileRow(result, palette, 0, 0, 0, 1, 2, [9, 1, 2, 3]);
  setTileRow(result, palette, 1, 0, 0, 4, 5, [3, 5, 4, 9]);
  setTileRow(result, palette, 0, 0, 7, 6, 8, [8, 9, 3, 6]);
  setTileRow(result, palette, 0, 40, 0, 14, 1, [1, 14, 7, 9]);
  setTileRow(result, palette, 0, 999, 7, 10, 11, [15, 11, 10, 9]);
  setTileRow(result, palette, 1, 999, 7, 12, 13, [9, 12, 13, 15]);

  const file = encodeFunPaintIfli(result, [...palette].reverse());
  assert.equal(file.length, 33694);
  assert.deepEqual(Array.from(file.subarray(0, 18)), [
    0xf0, 0x3f, 0x46, 0x55, 0x4e, 0x50, 0x41, 0x49, 0x4e,
    0x54, 0x20, 0x28, 0x4d, 0x54, 0x29, 0x20, 0x00, 0xad
  ]);
  // Literal file offsets come from the external FP2 layout, including its load address.
  for (const [offset, expected] of [
    [18, 0x12], [7186, 0x68], [58, 0xe1], [8185, 0xab],
    [8210, 0x1b], [8217, 0x8d], [8530, 0x9c], [16209, 0xe4],
    [16402, 3], [16403, 7], [17401, 15],
    [17402, 0x45], [25569, 0xcd], [25594, 0xe4], [33593, 0x1b]
  ]) assert.equal(file[offset], expected, `file byte ${offset}`);
  assert.ok(file.subarray(16210, 16402).every(value => value === 9));
  assert.ok(file.subarray(33594, 33694).every(value => value === 9));
  for (let page = 0; page < 8; page += 1) {
    assert.ok(file.subarray(18 + page * 1024 + 1000, 18 + (page + 1) * 1024).every(value => value === 0));
    assert.ok(file.subarray(17402 + page * 1024 + 1000, 17402 + (page + 1) * 1024).every(value => value === 0));
  }
});

test('rejects unsupported geometry and invalid fitted color indices before producing a file', () => {
  const cases = [
    [({ result }) => { result.frames.pop(); }, /two fitted frames/],
    [({ result }) => { result.frames[0].pixels.width = 159; }, /160 × 200/],
    [({ result }) => { result.tileColors[0] = 16; }, /tile colors/],
    [({ result }) => { result.frames[1].rowColors[15999] = 16; }, /row colors/],
    [({ palette }) => { palette[15].index = 0; }, /unique C64 color indices/]
  ];
  for (const [mutate, message] of cases) {
    const data = fixture();
    mutate(data);
    assert.throws(() => encodeFunPaintIfli(data.result, data.palette), message);
  }
});

test('rejects pixels that cannot retain their fitted preview color in the hardware allocation', () => {
  const cases = [
    [({ result }) => { result.frames[0].pixels.data[3] = 254; }, /opaque colors/],
    [({ result }) => { result.frames[0].pixels.data[0] = 255; }, /opaque colors/],
    [({ result, palette }) => {
      result.frames[0].pixels.data.set([...palette[10].rgb, 255], 0);
    }, /does not match its fitted colors/]
  ];
  for (const [mutate, message] of cases) {
    const data = fixture();
    mutate(data);
    assert.throws(() => encodeFunPaintIfli(data.result, data.palette), message);
  }
});
