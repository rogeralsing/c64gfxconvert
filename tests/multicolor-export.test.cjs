const assert = require('node:assert/strict');
const test = require('node:test');
const { ImageData, palette, bands, createContext, image, setPixel } = require('./fixtures/sprite-images.cjs');
const { encodeMulticolorBitmapKoala, optimizeMulticolorBitmapImage } = createContext([
  'fli.js', 'multicolor-export.js'
]);

function fixture() {
  const pixels = new ImageData(160, 200);
  const backgroundColorIndex = 6;
  const available = palette.filter(color => color.index !== backgroundColorIndex).map(color => color.index);
  const tileColors = new Uint8Array(3000);
  for (let tile = 0; tile < 1000; tile += 1) {
    const colors = [backgroundColorIndex, ...[0, 1, 2].map(offset => available[(tile + offset) % 15])];
    tileColors.set(colors.slice(1), tile * 3);
    for (let row = 0; row < 8; row += 1) {
      for (let column = 0; column < 4; column += 1) {
        setPixel(pixels, tile % 40 * 4 + column, Math.floor(tile / 40) * 8 + row,
          palette[colors[(tile + row + column) % 4]].rgb);
      }
    }
  }
  return { pixels, backgroundColorIndex, tileColors };
}

function decodeKoala(file) {
  const pixels = new Uint8ClampedArray(160 * 200 * 4);
  // Decode the external VIC-II/Koala layout independently of the exporter.
  for (let y = 0; y < 200; y += 1) {
    for (let x = 0; x < 160; x += 1) {
      const tile = Math.floor(y / 8) * 40 + Math.floor(x / 4);
      const pair = file[2 + tile * 8 + y % 8] >> (6 - x % 4 * 2) & 3;
      const screen = file[8002 + tile];
      const color = [file[10002], screen >> 4, screen & 15, file[9002 + tile] & 15][pair];
      pixels.set([...palette[color].rgb, 255], (y * 160 + x) * 4);
    }
  }
  return pixels;
}

test('Koala export preserves pixels, cell colors, and background in the native file layout', () => {
  const result = fixture();
  const beforePixels = result.pixels.data.slice();
  const beforeColors = result.tileColors.slice();
  const file = encodeMulticolorBitmapKoala(result, [...palette].reverse());
  assert.equal(file.length, 10003);
  assert.deepEqual(Array.from(file.slice(0, 2)), [0, 0x60]);
  for (const [offset, expected] of [
    [2, 0x1b], [3, 0x6c], [9, 0xc6], [10, 0x6c], [314, 0xc6], [322, 0x1b], [8001, 0xb1],
    [8002, 0x01], [8003, 0x12], [8041, 0xab], [8042, 0xbc], [9001, 0xab],
    [9002, 2], [9003, 3], [9041, 12], [9042, 13], [10001, 12], [10002, 6]
  ]) assert.equal(file[offset], expected, `byte ${offset}`);
  assert.deepEqual(decodeKoala(file), result.pixels.data);
  assert.deepEqual(result.pixels.data, beforePixels);
  assert.deepEqual(result.tileColors, beforeColors);
});

test('Koala export accepts the fitted multicolor result without changing its image', () => {
  const source = image(palette[6].rgb, 160);
  for (let y = 0; y < 8; y += 1) {
    for (let x = 0; x < 4; x += 1) setPixel(source, x, y, palette[(y * 4 + x) % 16].rgb);
  }
  setPixel(source, 159, 199, palette[13].rgb);
  const result = optimizeMulticolorBitmapImage(source, palette, bands, 6);
  assert.notDeepEqual(result.pixels.data, source.data);
  const file = encodeMulticolorBitmapKoala(result, palette);
  assert.equal(file[10002], 6);
  assert.deepEqual(decodeKoala(file), result.pixels.data);
});

test('Koala export rejects invalid geometry, colors, transparency, and unallocated pixels', () => {
  for (const [mutate, message] of [
    [result => { result.pixels.width = 320; }, /160 × 200/],
    [result => { result.pixels.data = new Uint8ClampedArray(4); }, /160 × 200/],
    [result => { result.backgroundColorIndex = 16; }, /palette|color/i],
    [result => { result.tileColors = new Uint8Array(3); }, /color/i],
    [result => { result.tileColors[0] = 16; }, /color/i],
    [result => { result.pixels.data[3] = 254; }, /opaque|allocated/i],
    [result => { setPixel(result.pixels, 0, 0, palette[5].rgb); }, /opaque|allocated/i],
    [result => { setPixel(result.pixels, 0, 0, [12, 34, 56]); }, /opaque|allocated/i]
  ]) {
    const result = fixture();
    mutate(result);
    assert.throws(() => encodeMulticolorBitmapKoala(result, palette), message);
  }
});
