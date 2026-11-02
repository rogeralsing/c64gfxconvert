const assert = require('node:assert/strict');
const test = require('node:test');
const { palette, bands, createContext, image, setPixel, ImageData } = require('./fixtures/sprite-images.cjs');
const context = createContext(['fli.js', 'scanline-dither.js', 'afli-export.js']);
const { breakUpScanlines, optimizeAfliImage, encodeAfli } = context;
const at = (pixels, x, y) => Array.from(pixels.data.subarray((y * pixels.width + x) * 4,
  (y * pixels.width + x + 1) * 4));

function stripes(width, height) {
  const pixels = new ImageData(width, height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      pixels.data.set([...palette[y & 1 ? 9 : 2].rgb, 255], (y * width + x) * 4);
    }
  }
  return pixels;
}

test('only a narrow strip around repeated line ends becomes staggered dither, preserving colors and solid interiors', () => {
  const source = stripes(48, 12);
  for (let y = 0; y < 12; y += 1) {
    for (let x = 0; x < 24; x += 1) source.data.set([...palette[2].rgb, 255], (y * 48 + x) * 4);
  }
  const before = new Uint8ClampedArray(source.data);
  const result = breakUpScanlines(source);
  const brown = [...palette[9].rgb, 255];
  const inserted = Array.from({ length: 24 }, (_, x) => x).filter(x => at(result, x, 1).join() === brown.join());
  assert.deepEqual(inserted, [18, 21, 23], 'sparse opposing pixels approach the boundary');
  assert.notDeepEqual(Array.from(result.data.subarray(48 * 4, 2 * 48 * 4)),
    Array.from(result.data.subarray(3 * 48 * 4, 4 * 48 * 4)), 'neighboring line ends stagger');
  for (let y = 0; y < 12; y += 1) {
    const expected = [];
    const actual = [];
    for (let x = 0; x < 48; x += 1) {
      expected.push(at(source, x, y).join());
      actual.push(at(result, x, y).join());
      if (x < 17 || x >= 31 || y % 2 === 0) {
        assert.deepEqual(at(result, x, y), at(source, x, y), 'pixels outside endpoint strips stay unchanged');
      }
    }
    assert.deepEqual(actual.sort(), expected.sort(), 'each line retains its colors and mean brightness');
  }
  assert.deepEqual(source.data, before);
  assert.deepEqual(breakUpScanlines(source).data, result.data, 'same input produces the same pattern');
});

test('vertical bars are not horizontal interlace lines', () => {
  const source = stripes(48, 12);
  for (let y = 0; y < 12; y += 1) {
    for (let x = 0; x < 24; x += 1) source.data.set([...palette[2].rgb, 255], (y * 48 + x) * 4);
  }
  const transpose = source => {
    const result = new ImageData(source.height, source.width);
    for (let y = 0; y < source.height; y += 1) {
      for (let x = 0; x < source.width; x += 1) result.data.set(at(source, x, y), (x * source.height + y) * 4);
    }
    return result;
  };
  const vertical = transpose(source);
  assert.deepEqual(breakUpScanlines(vertical).data, vertical.data);
});

test('detects isolated solid lines on either row parity with matching top, bottom, and one end', () => {
  for (const y of [1, 2, 3]) {
    for (const side of ['left', 'right', 'both']) {
      for (const length of [2, 4, 16]) {
        const source = new ImageData(48, 7);
        for (let row = 0; row < 7; row += 1) {
          for (let x = 0; x < 48; x += 1) source.data.set([...palette[2].rgb, 255], (row * 48 + x) * 4);
        }
        const start = side === 'right' ? 0 : side === 'left' ? 48 - length : 16;
        const end = start + length;
        for (let x = start; x < end; x += 1) source.data.set([...palette[8].rgb, 255], (y * 48 + x) * 4);
        const actual = breakUpScanlines(source);
        assert.notDeepEqual(actual.data, source.data, `single ${side}-ended ${length}-pixel line on row ${y}`);
        for (let row = 0; row < 7; row += 1) {
          if (row === y) continue;
          assert.deepEqual(Array.from(actual.data.subarray(row * 48 * 4, (row + 1) * 48 * 4)),
            Array.from(source.data.subarray(row * 48 * 4, (row + 1) * 48 * 4)), 'top and bottom stay intact');
        }
      }
    }
  }
});

test('a repeated stripe on one side cannot compensate for mismatched immediate top or bottom', () => {
  for (const invalid of ['top', 'bottom', 'partial-top', 'partial-bottom', 'side']) {
    const source = image(palette[2].rgb, 48);
    // The former two-rows-away heuristic sees another orange line here.
    for (const y of [1, 3]) {
      for (let x = 24; x < 48; x += 1) setPixel(source, x, y, palette[8].rgb);
    }
    if (invalid === 'side') {
      for (let x = 0; x < 24; x += 1) setPixel(source, x, 3, palette[6].rgb);
    } else {
      const row = invalid.includes('top') ? 2 : 4;
      const start = invalid.startsWith('partial') ? 40 : 0;
      for (let x = start; x < 48; x += 1) setPixel(source, x, row, palette[6].rgb);
    }
    const actual = breakUpScanlines(source);
    assert.deepEqual(Array.from(actual.data.subarray(3 * 48 * 4, 4 * 48 * 4)),
      Array.from(source.data.subarray(3 * 48 * 4, 4 * 48 * 4)), invalid);
  }
});

test('solid areas, single edges, short details, transparency, and existing dither stay intact', () => {
  const cases = [image(palette[2].rgb), stripes(32, 8), stripes(7, 8), new ImageData(1, 1)];
  const edge = image(palette[2].rgb);
  for (let y = 100; y < 200; y += 1) {
    for (let x = 0; x < 320; x += 1) setPixel(edge, x, y, palette[9].rgb);
  }
  cases.push(edge);
  const dither = stripes(32, 8);
  for (let y = 0; y < 8; y += 1) {
    for (let x = 1; x < 32; x += 2) dither.data.set([...palette[y & 1 ? 2 : 9].rgb, 255], (y * 32 + x) * 4);
  }
  cases.push(dither);
  const alpha = stripes(32, 8);
  for (let offset = 3; offset < alpha.data.length; offset += 4) alpha.data[offset] = offset % 8 === 3 ? 0 : 128;
  cases.push(alpha);
  for (const source of cases) assert.deepEqual(breakUpScanlines(source).data, source.data);
  assert.throws(() => breakUpScanlines({ width: 8, height: 8, data: new Uint8Array(8) }), /RGBA pixels/);
});

test('processed targets retain their dither through AFLI fitting and independent decoding of exported row colors', () => {
  const source = stripes(320, 200);
  // A stepped silhouette tests runs which start/end at different X positions.
  for (let y = 0; y < 200; y += 1) {
    for (let x = 0; x < 16 + Math.floor(y / 8) * 4; x += 1) setPixel(source, x, y, palette[2].rgb);
  }
  const processed = breakUpScanlines(source);
  assert.notDeepEqual(processed.data, source.data);
  const result = optimizeAfliImage(processed, palette, bands);
  const program = encodeAfli(result, palette);
  for (let y = 0; y < 200; y += 1) {
    for (let x = 0; x < 320; x += 1) {
      const cell = (y >> 3) * 40 + (x >> 3);
      const colors = program[2 + (y & 7) * 1024 + cell];
      const bits = program[8194 + cell * 8 + (y & 7)];
      const color = bits & (128 >> (x & 7)) ? colors >> 4 : colors & 15;
      assert.deepEqual([...palette[color].rgb, 255], at(processed, x, y));
    }
  }
});
