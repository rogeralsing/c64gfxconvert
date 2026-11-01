const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { TextEncoder } = require('node:util');

const context = vm.createContext({ Uint8Array, TextEncoder });
for (const file of ['afli-export.js', 'afli-sprite-export.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), context);
}
const { encodeAfliSpriteLayers } = context;

function fixture() {
  const palette = Array.from({ length: 16 }, (_, index) => ({
    index, name: index === 10 ? 'Ljus röd' : `Color ${index}`, rgb: [index, index + 16, index + 32]
  }));
  const underlay = new Uint8ClampedArray(256000);
  const rowColors = new Uint8Array(16000);
  for (let pixel = 0; pixel < 64000; pixel += 1) underlay.set([...palette[9].rgb, 255], pixel * 4);
  for (let row = 0; row < 8000; row += 1) rowColors.set([9, 7], row * 2);
  const result = {
    pixels: { width: 320, height: 200, data: new Uint8ClampedArray(underlay) },
    afli: { pixels: { width: 320, height: 200, data: underlay }, rowColors },
    spriteMask: new Uint8Array(64000),
    spriteColorIndex: 10,
    spritePixels: { width: 320, height: 200, data: new Uint8ClampedArray(256000) }
  };
  return { result, palette };
}

function setMask({ result, palette }, x, y) {
  const pixel = y * 320 + x;
  result.spriteMask[pixel] = 1;
  const rgba = [...palette[result.spriteColorIndex].rgb, 255];
  result.pixels.data.set(rgba, pixel * 4);
  result.spritePixels.data.set(rgba, pixel * 4);
}

// Independent table-based checksum and central-directory reader. Production
// computes CRC bit by bit and writes ZIP records; this reads their wire format.
const crcTable = Array.from({ length: 256 }, (_, value) => {
  for (let bit = 0; bit < 8; bit += 1) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
  return value >>> 0;
});
function crc32(data) {
  let crc = 0xffffffff;
  for (const byte of data) crc = crcTable[(crc ^ byte) & 255] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function readZip(bytes) {
  const zip = Buffer.from(bytes);
  const end = zip.length - 22;
  assert.equal(zip.readUInt32LE(end), 0x06054b50);
  assert.equal(zip.readUInt16LE(end + 4), 0);
  assert.equal(zip.readUInt16LE(end + 6), 0);
  assert.equal(zip.readUInt16LE(end + 8), 3);
  assert.equal(zip.readUInt16LE(end + 10), 3);
  assert.equal(zip.readUInt16LE(end + 20), 0);
  const start = zip.readUInt32LE(end + 16);
  assert.equal(start + zip.readUInt32LE(end + 12), end);
  const files = new Map();
  let central = start;
  let nextLocal = 0;
  for (let file = 0; file < 3; file += 1) {
    assert.equal(zip.readUInt32LE(central), 0x02014b50);
    assert.equal(zip.readUInt16LE(central + 8), 0x0800);
    assert.equal(zip.readUInt16LE(central + 10), 0, 'stored, not compressed');
    const checksum = zip.readUInt32LE(central + 16);
    const length = zip.readUInt32LE(central + 24);
    assert.equal(zip.readUInt32LE(central + 20), length);
    const nameLength = zip.readUInt16LE(central + 28);
    const name = zip.toString('utf8', central + 46, central + 46 + nameLength);
    const local = zip.readUInt32LE(central + 42);
    assert.equal(local, nextLocal);
    assert.equal(zip.readUInt32LE(local), 0x04034b50);
    assert.equal(zip.readUInt16LE(local + 6), 0x0800);
    assert.equal(zip.readUInt16LE(local + 8), 0);
    assert.equal(zip.readUInt32LE(local + 14), checksum);
    assert.equal(zip.readUInt32LE(local + 18), length);
    assert.equal(zip.readUInt32LE(local + 22), length);
    assert.equal(zip.readUInt16LE(local + 26), nameLength);
    const extraLength = zip.readUInt16LE(local + 28);
    assert.equal(zip.toString('utf8', local + 30, local + 30 + nameLength), name);
    const dataStart = local + 30 + nameLength + extraLength;
    const data = zip.subarray(dataStart, dataStart + length);
    assert.equal(crc32(data), checksum, `${name} CRC32`);
    assert.equal(files.has(name), false);
    files.set(name, data);
    nextLocal = dataStart + length;
    central += 46 + nameLength + zip.readUInt16LE(central + 30) + zip.readUInt16LE(central + 32);
  }
  assert.equal(nextLocal, start);
  assert.equal(central, end);
  return files;
}

test('writes a valid stored ZIP with an AFLI underlay and an explicit raster-layer manifest', () => {
  assert.equal(crc32(Buffer.from('123456789')), 0xcbf43926);
  const data = fixture();
  setMask(data, 112, 0);
  const zip = encodeAfliSpriteLayers(data.result, [...data.palette].reverse());
  const files = readZip(zip);
  assert.deepEqual([...files.keys()], ['image.afl', 'sprites.bin', 'manifest.json']);
  const afli = files.get('image.afl');
  assert.equal(afli.length, 16385);
  assert.deepEqual([...afli.subarray(0, 2)], [0, 0x40]);
  assert.equal(afli[2 + 14], 0x97);
  assert.equal(afli[8194 + 14 * 8], 0xff, 'covered underlay remains color9, not sprite color10');
  const manifest = JSON.parse(files.get('manifest.json').toString('utf8'));
  assert.equal(manifest.format, 'c64-afli-sprite-layers');
  assert.equal(manifest.version, 1);
  assert.deepEqual(manifest.spriteColor, { index: 10, name: 'Ljus röd', rgb: [10, 26, 42] });
  assert.deepEqual(manifest.image, { width: 320, height: 200, pixelAspectRatio: [1, 1] });
  assert.deepEqual(manifest.layout.afliValidRect, { x: 112, y: 0, width: 208, height: 200 });
  assert.deepEqual(manifest.layout.spriteRect, { x: 112, y: 0, width: 192, height: 200 });
  assert.equal(manifest.mask.format, 'packed-raster-mask');
  assert.equal(manifest.mask.byteLength, 4800);
  assert.equal(manifest.mask.bytesPerRow, 24);
  assert.equal(manifest.mask.bitOrder, 'msb-first');
  assert.equal(manifest.mask.hardwareFrames, false);
  assert.equal(manifest.referencePlayer.programIncluded, false);
  assert.equal(manifest.referencePlayer.acceptsThisMask, false);
  assert.equal(manifest.referencePlayer.spriteReuseRows, 21);
});

test('packs exact row-major bits across all eight sprites and row199 without aliasing or source mutation', () => {
  const data = fixture();
  for (const column of [0, 7, 8, 23, 24, 191]) setMask(data, 112 + column, 0);
  for (let sprite = 0; sprite < 8; sprite += 1) {
    for (const column of [0, 7, 8, 23]) setMask(data, 112 + sprite * 24 + column, 199);
  }
  setMask(data, 303, 198);
  const before = {
    mask: new Uint8Array(data.result.spriteMask), pixels: new Uint8ClampedArray(data.result.pixels.data),
    afli: new Uint8ClampedArray(data.result.afli.pixels.data), rows: new Uint8Array(data.result.afli.rowColors),
    sprite: new Uint8ClampedArray(data.result.spritePixels.data), palette: JSON.stringify(data.palette)
  };
  const packed = readZip(encodeAfliSpriteLayers(data.result, data.palette)).get('sprites.bin');
  assert.equal(packed.length, 4800);
  assert.deepEqual([...packed.subarray(0, 4)], [0x81, 0x80, 0x01, 0x80]);
  assert.equal(packed[23], 0x01);
  assert.ok(packed.subarray(24, 198 * 24).every(value => value === 0));
  assert.equal(packed[198 * 24 + 23], 0x01);
  assert.deepEqual([...packed.subarray(199 * 24)], Array.from({ length: 8 }, () => [0x81, 0x80, 0x01]).flat());
  for (let y = 0; y < 200; y += 1) {
    for (let x = 0; x < 192; x += 1) {
      const bit = Number(Boolean(packed[y * 24 + Math.floor(x / 8)] & (128 >> (x % 8))));
      assert.equal(bit, data.result.spriteMask[y * 320 + 112 + x], `mask (${x}, ${y})`);
    }
  }
  assert.deepEqual(data.result.spriteMask, before.mask);
  assert.deepEqual(data.result.pixels.data, before.pixels);
  assert.deepEqual(data.result.afli.pixels.data, before.afli);
  assert.deepEqual(data.result.afli.rowColors, before.rows);
  assert.deepEqual(data.result.spritePixels.data, before.sprite);
  assert.equal(JSON.stringify(data.palette), before.palette);
});

test('rejects malformed layer geometry, nonbinary or out-of-field masks, and invalid fitted AFLI', () => {
  for (const [mutate, message] of [
    [({ result }) => { result.pixels.width = 319; }, /320 × 200/],
    [({ result }) => { result.afli.pixels.height = 199; }, /320 × 200/],
    [({ result }) => { result.spriteMask = new Uint8Array(63999); }, /matching sprite mask/],
    [({ result }) => { result.spriteMask[112] = 2; }, /0 or 1/],
    [({ result }) => { result.spriteMask[111] = 1; }, /columns 112 through 303/],
    [({ result }) => { result.spriteMask[199 * 320 + 304] = 1; }, /columns 112 through 303/],
    [({ result }) => { result.spriteColorIndex = 16; }, /color from 0 to 15/],
    [({ result }) => { result.spriteColorIndex = 1.5; }, /color from 0 to 15/],
    [({ result }) => { result.afli.pixels.data[3] = 0; }, /opaque colors/],
    [({ result }) => { result.afli.rowColors[15999] = 16; }, /row colors must/]
  ]) {
    const data = fixture();
    mutate(data);
    assert.throws(() => encodeAfliSpriteLayers(data.result, data.palette), message);
  }
});
