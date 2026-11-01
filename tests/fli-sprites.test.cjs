const assert = require('node:assert/strict');
const test = require('node:test');
const { palette, bands, rgbToOklab, createContext, image, setPixel } = require('./fixtures/sprite-images.cjs');
const { createFliSpriteImage, optimizeFliImage } = createContext(['fli.js', 'afli-sprites.js', 'fli-sprites.js']);
const rgbIndices = new Map(palette.map(color => [color.rgb.join(','), color.index]));

function colorAt(pixels, x, y) {
  const offset = (y * pixels.width + x) * 4;
  return rgbIndices.get(Array.from(pixels.data.subarray(offset, offset + 3)).join(','));
}

function assertFliConstraints(fli) {
  assert.equal(fli.pixels.width, 160);
  assert.equal(fli.pixels.height, 200);
  assert.equal(fli.tileColors.length, 1000);
  assert.equal(fli.rowColors.length, 16000);
  for (let tileY = 0; tileY < 25; tileY += 1) {
    for (let tileX = 0; tileX < 40; tileX += 1) {
      const tile = tileY * 40 + tileX;
      for (let row = 0; row < 8; row += 1) {
        const allowed = [fli.backgroundColorIndex, fli.tileColors[tile],
          ...fli.rowColors.subarray(tile * 16 + row * 2, tile * 16 + row * 2 + 2)];
        for (let column = 0; column < 4; column += 1) {
          assert.ok(allowed.includes(colorAt(fli.pixels, tileX * 4 + column, tileY * 8 + row)));
        }
      }
    }
  }
}

test('FLI sprites retain hires source columns over a wide-pixel bitmap without changing either input', () => {
  const source = image();
  const targets = image(palette[0].rgb, 160);
  setPixel(source, 112, 0, palette[1].rgb);
  setPixel(source, 111, 0, palette[1].rgb);
  setPixel(source, 304, 0, palette[1].rgb);
  setPixel(targets, 56, 0, palette[2].rgb);
  setPixel(targets, 57, 0, palette[3].rgb);
  const beforeSource = new Uint8ClampedArray(source.data);
  const beforeTargets = new Uint8ClampedArray(targets.data);
  const result = createFliSpriteImage(source, targets, palette, bands, 0, 1, 0, 0);
  assert.equal(result.pixels.width, 320);
  assert.equal(result.pixels.height, 200);
  assert.equal(result.spriteMask.length, 320 * 200);
  assert.equal(result.spritePixelCount, 1);
  assert.equal(result.spriteMask[111], 0);
  assert.equal(result.spriteMask[112], 1);
  assert.equal(result.spriteMask[113], 0);
  assert.equal(result.spriteMask[304], 0);
  assert.equal(colorAt(result.pixels, 112, 0), 1, 'a hires sprite replaces just the left half');
  assert.equal(colorAt(result.pixels, 113, 0), 2, 'the right half retains its bitmap color');
  assert.equal(colorAt(result.pixels, 114, 0), 3);
  assert.equal(colorAt(result.pixels, 115, 0), 3, 'uncovered bitmap pixels stay double width');
  assert.equal(result.spritePixels.data[113 * 4 + 3], 0);
  assert.equal(result.matchAmount, 0);
  assert.equal(result.ditherAmount, 0);
  assert.deepEqual(source.data, beforeSource);
  assert.deepEqual(targets.data, beforeTargets);
  assertFliConstraints(result.fli);

  setPixel(source, 112, 1, [...palette[1].rgb, 64]);
  setPixel(source, 113, 1, [...palette[1].rgb, 0]);
  const beforeAlphaSource = new Uint8ClampedArray(source.data);
  for (const [background, expectedMask] of [[0, 0], [1, 1]]) {
    const alphaResult = createFliSpriteImage(source, targets, palette, bands, background, 1, 0.25, 0);
    assert.equal(alphaResult.spriteMask[320 + 112], expectedMask,
      `partial white must be matched over background ${background}`);
    assert.equal(alphaResult.spriteMask[320 + 113], 0, 'fully transparent source never becomes a sprite');
  }
  assert.deepEqual(source.data, beforeAlphaSource);
  assert.deepEqual(targets.data, beforeTargets);
});

test('fully covered wide pixels release their FLI color slots across the shared tile', () => {
  const source = image();
  const targets = image(palette[0].rgb, 160);
  const rows = [[1, 2, 3, 4], [5, 6, 7, 8]];
  for (let y = 0; y < 8; y += 1) {
    rows[y % 2].forEach((color, column) => setPixel(targets, 56 + column, y, palette[color].rgb));
    for (let x = 112; x < 116; x += 1) setPixel(source, x, y, palette[1].rgb);
  }
  const result = createFliSpriteImage(source, targets, palette, bands, 0, 1, 0, 0);
  assert.equal(result.spritePixelCount, 32);
  for (let y = 0; y < 8; y += 1) {
    for (let x = 112; x < 120; x += 1) {
      const expected = x < 116 ? 1 : rows[y % 2][Math.floor((x - 112) / 2)];
      assert.equal(colorAt(result.pixels, x, y), expected, `${x},${y}`);
    }
  }
  assertFliConstraints(result.fli);
});

test('a partly covered wide pixel still determines the tile color needed by its visible half', () => {
  const source = image();
  const targets = image(palette[0].rgb, 160);
  const rows = [[2, 4, 5, 3], [2, 8, 7, 6]];
  for (let y = 0; y < 8; y += 1) {
    rows[y % 2].forEach((color, column) => setPixel(targets, 56 + column, y, palette[color].rgb));
    for (const x of [112, 114, 115]) setPixel(source, x, y, palette[1].rgb);
  }
  const result = createFliSpriteImage(source, targets, palette, bands, 0, 1, 0, 0);
  assert.equal(result.fli.tileColors[14], 2, 'red is the only shared color that preserves all visible targets');
  for (let y = 0; y < 8; y += 1) {
    assert.equal(colorAt(result.pixels, 113, y), 2, 'the uncovered red half cannot be discarded');
    for (let column = 2; column < 4; column += 1) {
      assert.equal(colorAt(result.fli.pixels, 56 + column, y), rows[y % 2][column]);
    }
  }
});

test('FLI bitmap strips reserve the sprite color even when it is the global background', () => {
  for (const [spriteColor, background] of [[1, 0], [1, 1], [0, 0]]) {
    const source = image(spriteColor === 0 ? [1, 1, 1] : [254, 254, 254]);
    const targets = image(palette[spriteColor].rgb, 160);
    [spriteColor, spriteColor, 7, 15].forEach((color, x) => setPixel(targets, 56 + x, 0, palette[color].rgb));
    setPixel(source, 112, 0, palette[spriteColor].rgb);
    const result = createFliSpriteImage(source, targets, palette, bands, background, spriteColor, 0, 0);
    assert.equal(result.spritePixelCount, 1);
    assert.equal(result.fli.backgroundColorIndex, background, 'the global hardware background stays selected');
    for (let x = 56; x < 60; x += 1) {
      assert.notEqual(colorAt(result.fli.pixels, x, 0), spriteColor, `active row ${spriteColor}/${background}/${x}`);
    }
    assert.ok(!result.fli.rowColors.subarray(224, 226).includes(spriteColor), 'both free colors serve the bitmap');
    assert.equal(colorAt(result.fli.pixels, 56, 1), spriteColor, 'an inactive scanline can still use the sprite color');
    assert.equal(colorAt(result.fli.pixels, 60, 0), spriteColor, 'the neighboring strip is unaffected');
    assert.equal(colorAt(result.pixels, 112, 0), spriteColor, 'the overlay still supplies its selected color');
    assertFliConstraints(result.fli);
  }
});

// This oracle enumerates the hardware allocations directly. It deliberately
// avoids the production fitter's four-pixel subset partition algorithm.
const labs = palette.map(color => rgbToOklab(...color.rgb));
const lightness = palette.map(color => bands.find(band => band.colors.some(entry => entry.color.index === color.index)).lightness);
function error(target, candidate) {
  return [(lightness[target] - lightness[candidate]) ** 2,
    (labs[target].a - labs[candidate].a) ** 2 + (labs[target].b - labs[candidate].b) ** 2];
}
function better(next, previous) {
  return next[0] < previous[0] - 1e-12 || Math.abs(next[0] - previous[0]) <= 1e-12 && next[1] < previous[1] - 1e-12;
}
function exhaustiveTileError(rows, weights, spriteColor = null, background = 0) {
  let best = [Infinity, Infinity];
  for (let tile = 0; tile < 16; tile += 1) {
    const total = [0, 0];
    for (let row = 0; row < 8; row += 1) {
      const excluded = weights[row].some(weight => weight < 2) ? spriteColor : null;
      let rowBest = [Infinity, Infinity];
      for (let first = 0; first < 16; first += 1) {
        if (first === excluded) continue;
        for (let second = first; second < 16; second += 1) {
          if (second === excluded) continue;
          const score = [0, 0];
          for (let column = 0; column < 4; column += 1) {
            let pixelBest = [Infinity, Infinity];
            for (const color of [background, tile, first, second]) {
              if (color === excluded) continue;
              const next = error(rows[row][column], color);
              if (better(next, pixelBest)) pixelBest = next;
            }
            score[0] += weights[row][column] * pixelBest[0];
            score[1] += weights[row][column] * pixelBest[1];
          }
          if (better(score, rowBest)) rowBest = score;
        }
      }
      total[0] += rowBest[0];
      total[1] += rowBest[1];
    }
    if (better(total, best)) best = total;
  }
  return best;
}

test('FLI fitting minimizes brightness then chroma using the count of uncovered hires halves', () => {
  const rows = [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12], [13, 14, 15, 1],
    [6, 2, 5, 3], [7, 4, 8, 12], [9, 1, 11, 13], [15, 10, 14, 2]];
  const weights = [[1, 2, 2, 2], [2, 1, 2, 2], [2, 2, 1, 2], [2, 2, 2, 2],
    [0, 1, 2, 2], [2, 0, 1, 2], [2, 2, 0, 1], [1, 2, 2, 0]];
  const source = image();
  const targets = image(palette[0].rgb, 160);
  rows.forEach((row, y) => row.forEach((color, column) => {
    setPixel(targets, 56 + column, y, palette[color].rgb);
    for (let half = 0; half < 2 - weights[y][column]; half += 1) {
      setPixel(source, 112 + column * 2 + half, y, palette[1].rgb);
    }
  }));
  for (const background of [0, 1]) {
    const result = createFliSpriteImage(source, targets, palette, bands, background, 1, 0, 0);
    const actual = [0, 0];
    rows.forEach((row, y) => row.forEach((target, column) => {
      const next = error(target, colorAt(result.fli.pixels, 56 + column, y));
      actual[0] += weights[y][column] * next[0];
      actual[1] += weights[y][column] * next[1];
    }));
    const expected = exhaustiveTileError(rows, weights, 1, background);
    assert.ok(Math.abs(actual[0] - expected[0]) < 1e-10, `brightness ${actual[0]} versus ${expected[0]}`);
    assert.ok(Math.abs(actual[1] - expected[1]) < 1e-10, `chroma ${actual[1]} versus ${expected[1]}`);
    assertFliConstraints(result.fli);
  }
});

test('FLI sprite conversion rejects a wide-pixel source, a hires target, and malformed overlay masks', () => {
  const source = image();
  const targets = image(palette[0].rgb, 160);
  assert.throws(() => createFliSpriteImage(targets, targets, palette, bands, 0, 1, 0.25, 1), /320 × 200 RGB source/);
  assert.throws(() => createFliSpriteImage(source, source, palette, bands, 0, 1, 0.25, 1), /160 × 200 target/);
  assert.throws(() => createFliSpriteImage(source, targets, palette, bands, 16, 1, 0.25, 1), /background color/);
  assert.throws(() => optimizeFliImage(targets, palette, bands, 0, new Uint8Array(160 * 200)), /two binary hires bytes/);
  const malformed = new Uint8Array(320 * 200);
  malformed[112] = 2;
  assert.throws(() => optimizeFliImage(targets, palette, bands, 0, malformed), /two binary hires bytes/);
});
