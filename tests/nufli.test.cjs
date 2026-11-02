const assert = require('node:assert/strict');
const test = require('node:test');
const { palette, bands, createContext, image, setPixel } = require('./fixtures/sprite-images.cjs');
const { decodeNufli } = require('./fixtures/nufli-decode.cjs');
const context = createContext(['fli.js', 'nufli-data.js', 'nufli.js', 'nufli-export.js']);
const { optimizeNufliImage, encodeNufli, encodeNufliPrg } = context;

function blankPlan() {
  const result = { bitmap: new Uint8Array(8000), screenColors: new Uint8Array(4000),
    spriteBits: new Uint8Array(3600), bugHiresBits: new Uint8Array(600),
    bugMulticolorBits: new Uint8Array(600), bugColors: new Uint8Array(400),
    registerUpdates: new Uint8Array(606) };
  for (let sprite = 0; sprite < 8; sprite += 1) result.registerUpdates[(63 + sprite * 2) * 6 + 5] = 0x11 + sprite * 2;
  return result;
}

test('NUF packs the external file contract and PRG loads the same player at $3000', () => {
  const plan = blankPlan();
  plan.screenColors.fill(0x67);
  plan.bitmap[24] = 0x80; // x=24, y=0: ink blue rather than yellow paper.
  plan.spriteBits[0] = 0x40; // x=26..27, y=0: expanded underlay white.
  plan.registerUpdates[0] = 1;
  plan.bugColors.set([2, 3, 4, 5]);
  plan.bugHiresBits[0] = 0x80;
  plan.bugMulticolorBits[0] = 0x10; // x=2..3: multicolor slot 1, cyan.
  const file = encodeNufli(plan);
  assert.equal(file.length, 23042);
  assert.deepEqual(Array.from(file.subarray(0, 2)), [0, 32]);
  assert.equal(file[0x401a], 0x80);
  assert.equal(file[0x3c02], 0x67);
  assert.equal(file[0x1002], 0x78, 'unchanged player entry begins SEI');
  const indices = decodeNufli(file);
  assert.deepEqual(Array.from(indices.subarray(24, 32)), [6, 7, 1, 1, 7, 7, 7, 7]);
  assert.equal(indices[0], 2);
  assert.equal(indices[2], 3);
  assert.equal(indices[312], 7, 'last character has no underlay');
  const program = encodeNufliPrg(plan);
  assert.deepEqual(Array.from(program.subarray(0, 2)), [1, 8]);
  assert.equal(Buffer.from(program.subarray(7, 13)).toString(), ' 12288');
  assert.deepEqual(program.subarray(2 + 0x2000 - 0x0801), file.subarray(2));
});

test('fitted full-frame preview survives independent NUF decoding across all sprite splits and edges', () => {
  const source = image();
  let random = 123456789;
  for (let y = 0; y < 200; y += 1) {
    for (let x = 0; x < 320; x += 1) {
      random = (Math.imul(random, 1664525) + 1013904223) >>> 0;
      const color = (x >> 3) % 4 === 0 ? (y >> 1) % 16 : (random >>> 28);
      setPixel(source, x, y, palette[color].rgb);
    }
  }
  const before = new Uint8ClampedArray(source.data);
  const result = optimizeNufliImage(source, palette, bands);
  const file = encodeNufli(result);
  const decoded = decodeNufli(file);
  for (let p = 0; p < 64000; p += 1) {
    assert.deepEqual(Array.from(result.pixels.data.subarray(p * 4, p * 4 + 4)),
      [...palette[decoded[p]].rgb, 255], `pixel ${p % 320},${Math.floor(p / 320)}`);
  }
  assert.ok(result.spriteBits.some(byte => byte !== 0));
  assert.ok(result.bugHiresBits.some(byte => byte !== 0));
  assert.ok(result.bugMulticolorBits.some(byte => byte !== 0));
  assert.deepEqual(source.data, before);
});

test('rejects missing, repeated, or mistimed sprite-Y writes instead of exporting a broken player', () => {
  for (const mutate of [
    p => { p.registerUpdates[63 * 6 + 5] = 0; },
    p => { p.registerUpdates[65 * 6 + 5] = 0x11; },
    p => { p.registerUpdates[20 * 6] = 0x11; },
    p => { p.registerUpdates[10 * 6] = 0x73; },
    p => { p.bitmap = new Uint8Array(7999); }
  ]) {
    const plan = blankPlan();
    mutate(plan);
    assert.throws(() => encodeNufli(plan), /NUFLI/);
  }
});

test('joint fitting preserves colors in already representable NUFLI images', () => {
  let random = 12345;
  const next = n => {
    random = (Math.imul(random, 1664525) + 1013904223) >>> 0;
    return (random >>> 16) % n;
  };
  const plans = [];
  const main = blankPlan();
  for (const key of ['bitmap', 'screenColors', 'spriteBits']) {
    for (let i = 0; i < main[key].length; i += 1) main[key][i] = next(256);
  }
  for (let i = 0; i < 606; i += 1) main.registerUpdates[i] = next(16);
  for (let sprite = 0; sprite < 8; sprite += 1) main.registerUpdates[(63 + sprite * 2) * 6 + 5] = 0x11 + sprite * 2;
  main.bugHiresBits.fill(255);
  plans.push(['staggered bitmap and underlay colors', main]);

  const right = blankPlan();
  right.registerUpdates.fill(0);
  for (let row = 0; row <= 100; row += 1) right.registerUpdates[row * 6 + 5] = 2 + row % 14;
  for (let sprite = 0; sprite < 8; sprite += 1) right.registerUpdates[(63 + sprite * 2) * 6] = 0x11 + sprite * 2;
  for (let y = 0; y < 200; y += 1) {
    for (let col = 33; col < 39; col += 1) {
      right.screenColors[(y >> 1) * 40 + col] = 0x10;
      right.bitmap[(y >> 3) * 320 + col * 8 + (y & 7)] = 0x0b;
    }
    right.spriteBits.fill(0x44, y * 18 + 15, y * 18 + 18);
  }
  right.bugHiresBits.fill(255);
  plans.push(['Y updates leave the changing rightmost underlay alone', right]);

  const edge = blankPlan();
  edge.registerUpdates.fill(0);
  for (let sprite = 0; sprite < 8; sprite += 1) edge.registerUpdates[(63 + sprite * 2) * 6] = 0x11 + sprite * 2;
  edge.bugColors.set([2, 3, 4, 5]);
  for (let row = 1; row < 100; row += 1) {
    [0x70, 0x50, 0xe0, 0x60].forEach((command, slot) => {
      edge.registerUpdates[row * 6 + slot + 1] = command | next(16);
    });
  }
  for (let y = 0; y < 200; y += 1) {
    for (let col = 0; col < 3; col += 1) {
      edge.bitmap[(y >> 3) * 320 + col * 8 + (y & 7)] = next(256);
      edge.screenColors[(y >> 1) * 40 + col] = next(256);
      edge.bugHiresBits[y * 3 + col] = next(256);
      edge.bugMulticolorBits[y * 3 + col] = next(256);
    }
  }
  plans.push(['left-edge bitmap and both sprite layers', edge]);

  for (const [name, plan] of plans) {
    // A separate file decoder supplies a legal target, not the fitter's preview.
    const expected = decodeNufli(encodeNufli(plan));
    const source = image();
    for (let p = 0; p < expected.length; p += 1) source.data.set(palette[expected[p]].rgb, p * 4);
    const fitted = optimizeNufliImage(source, palette, bands);
    const actual = decodeNufli(encodeNufli(fitted));
    let mismatches = 0;
    for (let p = 0; p < expected.length; p += 1) if (actual[p] !== expected[p]) mismatches += 1;
    assert.equal(mismatches, 0, name);
  }
});
