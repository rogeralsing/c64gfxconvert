const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { TextEncoder } = require('node:util');

const context = vm.createContext({ Uint8Array, TextEncoder });
for (const file of ['afli-sprite-export.js', 'sprite-grid-export.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), context);
}
const { encodeC64SpriteGrid } = context;

function fixture(overlay = true) {
  const settings = {
    columns: 2, rows: 2, backgroundColorIndex: 6, multicolorIndices: [5, 7],
    spriteColorIndices: [1, 2, 3, 4, 5, 6, 7, 8],
    overlayColorIndices: [15, 14, 13, 12, 11, 10, 9, 8], overlay
  };
  const cells = settings.columns * settings.rows;
  const sprites = Array.from({ length: cells * (overlay ? 2 : 1) }, (_, index) => {
    const cell = index % cells;
    const multicolor = !overlay || index >= cells;
    const data = new Uint8Array(64);
    data[0] = 0x80 >> index;
    data[62] = index + 1;
    return { index, column: cell % 2, row: Math.floor(cell / 2), multicolor,
      colorIndex: (multicolor ? settings.spriteColorIndices : settings.overlayColorIndices)[cell], data };
  });
  return { settings, result: { pixels: { width: 48, height: 42, data: new Uint8ClampedArray(48 * 42 * 4) }, sprites } };
}

// Shared ZIP framing and CRC32 are covered by afli-sprite-export.test.cjs.
function entries(archive) {
  const zip = Buffer.from(archive);
  const files = new Map();
  let offset = 0;
  while (zip.readUInt32LE(offset) === 0x04034b50) {
    const size = zip.readUInt32LE(offset + 18);
    const nameLength = zip.readUInt16LE(offset + 26);
    const start = offset + 30 + nameLength + zip.readUInt16LE(offset + 28);
    files.set(zip.toString('utf8', offset + 30, offset + 30 + nameLength), zip.subarray(start, start + size));
    offset = start + size;
  }
  return files;
}

test('exports native hardware frames and matching VIC colors, masks, and grid positions', () => {
  for (const overlay of [false, true]) {
    const { settings, result } = fixture(overlay);
    const before = structuredClone(result);
    const files = entries(encodeC64SpriteGrid(result, settings));
    const binary = files.get('sprites.bin');
    const manifest = JSON.parse(files.get('manifest.json').toString('utf8'));
    assert.equal(binary.length, overlay ? 512 : 256);
    assert.equal(manifest.format, 'c64-sprite-grid');
    assert.deepEqual(manifest.image, { width: 48, height: 42, pixelAspectRatio: [1, 1] });
    assert.equal(manifest.hardware.spriteEnableMask, overlay ? 255 : 15);
    assert.equal(manifest.hardware.multicolorEnableMask, overlay ? 240 : 15);
    assert.deepEqual(manifest.hardware.sharedMulticolorRegisters, [5, 7]);
    assert.equal(manifest.hardware.backgroundColorRegister, 6);
    assert.deepEqual(manifest.hardware.spriteColorRegisters, overlay ? [15, 14, 13, 12, 1, 2, 3, 4] : [1, 2, 3, 4]);
    for (let index = 0; index < result.sprites.length; index += 1) {
      assert.equal(binary[index * 64], 0x80 >> index);
      assert.equal(binary[index * 64 + 62], index + 1);
      assert.equal(binary[index * 64 + 63], 0);
      assert.deepEqual([manifest.sprites[index].x, manifest.sprites[index].y],
        [(index % 4 % 2) * 24, Math.floor(index % 4 / 2) * 21]);
      assert.equal(manifest.sprites[index].byteOffset, index * 64);
    }
    assert.deepEqual(result, before);
  }
});

test('rejects stale grid data, reordered sprites, invalid colors, and oversized hardware allocations', () => {
  for (const change of [
    ({ settings }) => { settings.columns = 3; settings.rows = 2; },
    ({ settings }) => { settings.backgroundColorIndex = 16; },
    ({ result }) => { result.pixels.width = 24; },
    ({ result }) => { result.sprites.reverse(); },
    ({ result }) => { result.sprites[0].multicolor = true; },
    ({ result }) => { result.sprites[7].colorIndex = 8; },
    ({ result }) => { result.sprites[0].data = new Uint8Array(63); },
    ({ result }) => { result.sprites[0].data[63] = 255; }
  ]) {
    const data = fixture();
    change(data);
    assert.throws(() => encodeC64SpriteGrid(data.result, data.settings), /Sprite export requires|Sprite frames must/);
  }
});
