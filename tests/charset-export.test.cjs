const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { TextEncoder } = require('node:util');

const context = vm.createContext({ Uint8Array, TextEncoder });
for (const file of ['afli-sprite-export.js', 'charset-export.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), context);
}
const { encodeC64Charset } = context;
const palette = Array.from({ length: 16 }, (_, index) => ({ index, rgb: [index * 16, index * 8, index * 4] }));

function decode(charset, screen, colorRam, background, shared) {
  const pixels = new Uint8ClampedArray(320 * 200 * 4);
  for (let y = 0; y < 200; y += 1) {
    for (let x = 0; x < 320; x += 1) {
      const cell = Math.floor(y / 8) * 40 + Math.floor(x / 8);
      const attribute = colorRam[cell];
      const bits = charset[screen[cell] * 8 + y % 8];
      const localX = x % 8;
      let colorIndex;
      if (attribute >= 8) {
        const code = bits >> (6 - 2 * Math.floor(localX / 2)) & 3;
        colorIndex = [background, shared[0], shared[1], attribute - 8][code];
      } else {
        colorIndex = (bits & (128 >> localX)) === 0 ? background : attribute;
      }
      pixels.set([...palette[colorIndex].rgb, 255], (y * 320 + x) * 4);
    }
  }
  return pixels;
}

function fixture() {
  const charset = new Uint8Array(2048);
  charset.set([0x1b, 0xe4, 0x55, 0xaa, 0xff, 0, 0x81, 0x18]);
  charset.set([0x80, 0x40, 0x20, 0x10, 8, 4, 2, 1], 8);
  charset.set([0xff, 0xaa, 0x55, 0, 0x1b, 0xe4, 0x33, 0xcc], 16);
  const screen = new Uint8Array(1000);
  const colorRam = new Uint8Array(1000).fill(1);
  screen[1] = 1;
  screen[999] = 2;
  colorRam[0] = 12;
  colorRam[1] = 3;
  colorRam[999] = 15;
  const settings = { backgroundColorIndex: 6, multicolorIndices: [5, 14] };
  const pixels = { width: 320, height: 200,
    data: decode(charset, screen, colorRam, 6, [5, 14]) };
  const result = { pixels, charset, screen, colorRam, characterCount: 3,
    unrestrictedCharacterCount: 3, approximatedCellCount: 0, ...settings };
  return { result, settings };
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

test('exports native mixed hires and multicolor character data that independently reproduces the preview', () => {
  const { result, settings } = fixture();
  const before = structuredClone(result);
  const files = entries(encodeC64Charset(result, settings, [...palette].reverse()));
  const charset = files.get('charset.bin');
  const screen = files.get('screen.bin');
  const colors = files.get('color-ram.bin');
  const manifest = JSON.parse(files.get('manifest.json').toString('utf8'));
  assert.equal(charset.length, 2048);
  assert.equal(screen.length, 1000);
  assert.equal(colors.length, 1000);
  assert.deepEqual([...charset.subarray(0, 8)], [0x1b, 0xe4, 0x55, 0xaa, 0xff, 0, 0x81, 0x18]);
  assert.deepEqual([screen[1], screen[999], colors[0], colors[1], colors[999]], [1, 2, 12, 3, 15]);
  assert.deepEqual(decode(charset, screen, colors, manifest.hardware.backgroundColorRegister,
    manifest.hardware.sharedMulticolorRegisters), result.pixels.data);
  for (const [x, expected] of [[0, 6], [1, 6], [2, 5], [3, 5], [4, 14], [5, 14], [6, 4], [7, 4], [8, 3], [9, 6]]) {
    assert.deepEqual([...result.pixels.data.subarray(x * 4, x * 4 + 4)], [...palette[expected].rgb, 255]);
  }
  assert.equal(manifest.format, 'c64-multicolor-charset');
  assert.equal(manifest.characterCount, 3);
  assert.equal(manifest.approximatedCellCount, 0);
  assert.equal(manifest.hiresCellCount, 998);
  assert.equal(manifest.multicolorCellCount, 2);
  assert.deepEqual(manifest.optimization, { similarityThreshold: 35 });
  assert.equal(manifest.hardware.bitmapMode, false);
  assert.equal(manifest.hardware.extendedColorMode, false);
  assert.equal(manifest.hardware.multicolorMode, true);
  assert.equal(manifest.layout.loadAddressesIncluded, false);
  assert.deepEqual(result, before);
});

test('export preserves disabled and maximum similarity settings while deriving mode counts from color RAM', () => {
  for (const similarityThreshold of [0, 100]) {
    const { result, settings } = fixture();
    settings.similarityThreshold = similarityThreshold;
    result.similarityThreshold = similarityThreshold;
    result.similarityMergedCellCount = 17;
    result.hiresCellCount = 0;
    result.multicolorCellCount = 1000;
    const files = entries(encodeC64Charset(result, settings, palette));
    const manifest = JSON.parse(files.get('manifest.json').toString('utf8'));
    assert.deepEqual(manifest.optimization, { similarityThreshold, similarityMergedCellCount: 17 });
    assert.equal(manifest.hiresCellCount, 998);
    assert.equal(manifest.multicolorCellCount, 2);
  }
});

test('rejects stale shared colors, invalid glyph references, color RAM, geometry, and preview bytes', () => {
  for (const change of [
    ({ settings }) => { settings.backgroundColorIndex = 7; },
    ({ settings }) => { settings.multicolorIndices = [5, 13]; },
    ({ result }) => { result.multicolorIndices = [16, 14]; },
    ({ result }) => { result.characterCount = 257; },
    ({ result }) => { result.screen[10] = 3; },
    ({ result }) => { result.colorRam[999] = 16; },
    ({ result }) => { result.charset = new Uint8Array(2047); },
    ({ result }) => { result.pixels.width = 160; },
    ({ result }) => { result.pixels.data[3] = 0; },
    ({ result }) => { result.colorRam[1] = 11; },
    ({ result }) => { result.charset[0] ^= 0x40; },
    ({ result }) => { result.unrestrictedCharacterCount = 2; },
    ({ result }) => { result.approximatedCellCount = 1001; },
    ({ settings }) => { settings.similarityThreshold = -1; },
    ({ settings }) => { settings.similarityThreshold = 101; },
    ({ settings }) => { settings.similarityThreshold = null; },
    ({ settings }) => { settings.similarityThreshold = '35'; },
    ({ result }) => { result.similarityThreshold = 0; },
    ({ result }) => { result.similarityMergedCellCount = -1; }
  ]) {
    const data = fixture();
    change(data);
    assert.throws(() => encodeC64Charset(data.result, data.settings, palette), /Character export requires|Character pixels must/);
  }
  const data = fixture();
  assert.throws(() => encodeC64Charset(data.result, data.settings, palette.slice(1)), /valid indexed C64 palette/);
});
