const assert = require('node:assert/strict');
const test = require('node:test');
const { palette, bands, createContext, image, setPixel } = require('./fixtures/sprite-images.cjs');
const context = createContext(['fli.js', 'afli-export.js', 'pafli.js', 'pafli-player-data.js', 'pafli-export.js']);
const { optimizePafliImages, alignPafliFrame, encodePafliPrg } = context;
const rgb = (pixels, x, y) => Array.from(pixels.data.subarray((y * 320 + x) * 4, (y * 320 + x) * 4 + 3));

test('four-pixel compensation keeps landmarks fixed and clears the bottom eight rows', () => {
  const source = image(palette[6].rgb);
  for (let y = 0; y < 200; y += 1) {
    for (const x of [28, 41, 42, 43, 127, 128, 129, 315, 319]) setPixel(source, x, y, palette[1].rgb);
  }
  const before = new Uint8ClampedArray(source.data);
  const result = optimizePafliImages(source, palette, bands);
  for (let y = 0; y < 200; y += 1) {
    for (let x = 28; x < 320; x += 1) {
      const expected = y >= 192 ? palette[0].rgb : rgb(source, x, y);
      assert.deepEqual(rgb(result.frames[0].pixels, x, y), expected);
      assert.deepEqual(rgb(result.frames[1].pixels, x - 4, y), expected);
      assert.deepEqual(rgb(result.displayFrames[0], x, y), expected);
      assert.deepEqual(rgb(result.displayFrames[1], x, y), expected);
      assert.deepEqual(rgb(result.blended, x, y), expected);
    }
    for (const frame of result.displayFrames) {
      for (let x = 0; x < 28; x += 1) assert.deepEqual(rgb(frame, x, y), palette[0].rgb);
    }
  }
  assert.deepEqual(source.data, before);
});

test('each phase groups different source pixels into its two-color scanline cells', () => {
  const source = image();
  for (let x = 32; x < 48; x += 1) setPixel(source, x, 0, palette[[6, 2, 5, 6][(x - 32) >> 2]].rgb);
  const result = optimizePafliImages(source, palette, bands);
  const rowColors = (frame, column) => Array.from(result.frames[frame].rowColors.subarray(column * 16, column * 16 + 2)).sort((a, b) => a - b);
  assert.deepEqual(rowColors(0, 4), [2, 6], 'phase A cell x32..39 sees blue and red');
  assert.deepEqual(rowColors(1, 4), [2, 5], 'phase B cell x32..39 sees source x36..43, red and green');
  assert.deepEqual(rgb(result.displayFrames[0], 35, 0), palette[6].rgb);
  assert.deepEqual(rgb(result.displayFrames[1], 35, 0), palette[6].rgb);
  assert.deepEqual(rgb(result.displayFrames[0], 36, 0), palette[2].rgb);
  assert.deepEqual(rgb(result.displayFrames[1], 36, 0), palette[2].rgb);
});

test('standalone PRG contains both independently decodable AFLI banks and preserves the aligned preview', () => {
  const source = image();
  let random = 0x1234abcd;
  for (let y = 0; y < 200; y += 1) {
    for (let x = 28; x < 320; x += 1) {
      random = (Math.imul(random, 1664525) + 1013904223) >>> 0;
      setPixel(source, x, y, palette[random >>> 28].rgb);
    }
  }
  const result = optimizePafliImages(source, palette, bands);
  const program = encodePafliPrg(result, palette);
  assert.equal(program.length, 48013);
  assert.deepEqual(Array.from(program.subarray(0, 2)), [1, 8]);
  assert.equal(Buffer.from(program.subarray(7, 11)).toString(), '8384');
  let changed = 0;
  for (let phase = 0; phase < 2; phase += 1) {
    const start = 2 + (phase === 0 ? 0x4000 : 0x83e8) - 0x0801;
    for (let bank = 0; bank < 8; bank += 1) {
      assert.ok(program.subarray(start + bank * 1024 + 960, start + bank * 1024 + 1000)
        .every(byte => byte === 0), 'both bottom-row colors are black');
    }
    assert.ok(program.subarray(start + 8192 + 7680, start + 8192 + 8000).every(byte => byte === 0),
      'bottom-row bitmap bits are zero');
    for (let y = 0; y < 200; y += 1) {
      for (let x = 28; x < 320; x += 1) {
        const rawX = x - phase * 4;
        const cell = (y >> 3) * 40 + (rawX >> 3);
        const attributes = program[start + (y & 7) * 1024 + cell];
        const bitmap = program[start + 8192 + cell * 8 + (y & 7)];
        const color = bitmap & (128 >> (rawX & 7)) ? attributes >> 4 : attributes & 15;
        assert.deepEqual(rgb(result.displayFrames[phase], x, y), palette[color].rgb, `${phase}: ${x},${y}`);
        if (phase === 1 && rgb(result.displayFrames[0], x, y).join(',') !== palette[color].rgb.join(',')) changed += 1;
      }
    }
  }
  assert.ok(changed > 0, 'phase offset produces different legal approximations, rather than duplicate frames');
  for (const [x, y] of [[36, 0], [100, 79], [319, 199]]) {
    const expected = rgb(result.displayFrames[0], x, y).map((channel, i) =>
      Math.round((channel + rgb(result.displayFrames[1], x, y)[i]) / 2));
    assert.deepEqual(rgb(result.blended, x, y), expected);
  }
});

test('rejects malformed frame geometry and unexportable allocations', () => {
  assert.throws(() => optimizePafliImages(image(palette[0].rgb, 160), palette, bands), /320 × 200/);
  assert.throws(() => alignPafliFrame(image(), 2, palette[0].rgb), /phase 0 or 1/);
  assert.throws(() => encodePafliPrg({ frames: [] }, palette), /two fitted AFLI frames/);
  assert.throws(() => encodePafliPrg({ frames: [{ pixels: image(), rowColors: [] }, {}] }, palette), /fitted row colors/);
});
