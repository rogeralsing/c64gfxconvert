const assert = require('node:assert/strict');
const test = require('node:test');
const { ImageData, palette, bands, createContext, setPixel } = require('./fixtures/sprite-images.cjs');
const { optimizeMciImages } = createContext(['fli.js']);

function source(width, height, colors) {
  const pixels = new ImageData(width, height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      setPixel(pixels, x, y, palette[colors[(y * width + x) % colors.length]].rgb);
    }
  }
  return pixels;
}

function indices(pixels) {
  const colors = [];
  for (let offset = 0; offset < pixels.data.length; offset += 4) {
    const color = palette.find(entry => entry.rgb.every((channel, index) =>
      channel === pixels.data[offset + index]));
    assert.ok(color, 'every fitted pixel is an exact C64 color');
    assert.equal(pixels.data[offset + 3], 255);
    colors.push(color.index);
  }
  return colors;
}

const costs = Array.from({ length: 16 }, () => []);
for (const targetBand of bands) {
  for (const target of targetBand.colors) {
    for (const candidateBand of bands) {
      for (const candidate of candidateBand.colors) {
        costs[target.color.index][candidate.color.index] = [
          (targetBand.lightness - candidateBand.lightness) ** 2,
          (target.lab.a - candidate.lab.a) ** 2 + (target.lab.b - candidate.lab.b) ** 2
        ];
      }
    }
  }
}
const better = (left, right) => left[0] < right[0] - 1e-12 ||
  (Math.abs(left[0] - right[0]) <= 1e-12 && left[1] < right[1] - 1e-12);
const add = (left, right) => [left[0] + right[0], left[1] + right[1]];

function allocationError(targets, allowed) {
  return targets.reduce((sum, target) => {
    const best = allowed.map(color => costs[target][color])
      .reduce((left, right) => better(right, left) ? right : left);
    return add(sum, best);
  }, [0, 0]);
}

// This oracle enumerates the actual two screen nibbles for each fixed Color
// RAM value, including duplicate/background colors. It does not enumerate
// triples, use fitter tables, or derive expectations from fitted output.
function exhaustiveMciError(phases, background) {
  let joint = [Infinity, Infinity];
  const independent = phases.map(() => [Infinity, Infinity]);
  for (let shared = 0; shared < 16; shared += 1) {
    const phaseErrors = phases.map((targets, phase) => {
      let best = [Infinity, Infinity];
      for (let first = 0; first < 16; first += 1) {
        for (let second = first; second < 16; second += 1) {
          const error = allocationError(targets, [background, shared, first, second]);
          if (better(error, best)) best = error;
        }
      }
      if (better(best, independent[phase])) independent[phase] = best;
      return best;
    });
    const sum = add(...phaseErrors);
    if (better(sum, joint)) joint = sum;
  }
  return { joint, independent: add(...independent) };
}

test('MCI keeps both representable phases and fixes each phase palette for the whole bitmap cell', () => {
  const shared = [2, 6, 7, 13];
  const pairs = [[[3, 5], [4, 8], [9, 10], [11, 12]], [[14, 15], [1, 2], [3, 4], [5, 8]]];
  const phases = pairs.map((phasePairs, phase) => {
    const pixels = new ImageData(8, 16);
    for (let y = 0; y < 16; y += 1) {
      for (let x = 0; x < 8; x += 1) {
        const tile = Math.floor(y / 8) * 2 + Math.floor(x / 4);
        const allowed = [0, shared[tile], ...phasePairs[tile]];
        setPixel(pixels, x, y, palette[allowed[(x + y + phase) % 4]].rgb);
      }
    }
    return pixels;
  });
  const result = optimizeMciImages(...phases, palette, bands, 0);
  assert.equal(result.frames.length, 2);
  assert.equal(result.backgroundColorIndex, 0);
  assert.deepEqual(Array.from(result.tileColors), shared);
  for (let phase = 0; phase < 2; phase += 1) {
    const frame = result.frames[phase];
    assert.equal(frame.pixels.width, 8);
    assert.equal(frame.pixels.height, 16);
    assert.deepEqual(frame.pixels.data, phases[phase].data);
    const colors = indices(frame.pixels);
    for (let tile = 0; tile < 4; tile += 1) {
      const pair = Array.from(frame.rowColors.subarray(tile * 16, tile * 16 + 2));
      assert.deepEqual(pair.slice().sort((a, b) => a - b), pairs[phase][tile]);
      for (let row = 0; row < 8; row += 1) {
        assert.deepEqual(Array.from(frame.rowColors.subarray(tile * 16 + row * 2, tile * 16 + row * 2 + 2)), pair);
        for (let column = 0; column < 4; column += 1) {
          const pixel = (Math.floor(tile / 2) * 8 + row) * 8 + tile % 2 * 4 + column;
          assert.ok([0, result.tileColors[tile], ...pair].includes(colors[pixel]));
        }
      }
    }
  }
});

test('MCI chooses the globally best shared Color RAM value across asymmetric phase palettes', () => {
  const targets = [
    [...Array(10).fill(2), ...Array(8).fill(6), ...Array(8).fill(10), ...Array(6).fill(5)],
    [...Array(15).fill(1), ...Array(8).fill(3), ...Array(7).fill(13), ...Array(2).fill(8)]
  ];
  const oracle = exhaustiveMciError(targets, 0);
  assert.ok(better(oracle.independent, oracle.joint), 'fixture requires a joint compromise between phases');
  const result = optimizeMciImages(...targets.map(colors => source(4, 8, colors)), palette, bands, 0);
  const error = result.frames.reduce((sum, frame, phase) => add(sum,
    indices(frame.pixels).reduce((phaseSum, color, pixel) => add(phaseSum, costs[targets[phase][pixel]][color]), [0, 0])), [0, 0]);
  for (let component = 0; component < 2; component += 1) {
    assert.ok(Math.abs(error[component] - oracle.joint[component]) < 1e-10,
      `error component ${component}: ${error[component]} versus oracle ${oracle.joint[component]}`);
  }
});

test('MCI flattens transparent pixels to its background without changing either source and rejects incompatible geometry', () => {
  const phases = [source(4, 8, [6]), source(4, 8, [13])];
  setPixel(phases[0], 0, 0, [255, 17, 99, 0]);
  setPixel(phases[1], 3, 7, [22, 255, 99, 0]);
  const before = phases.map(pixels => pixels.data.slice());
  const result = optimizeMciImages(...phases, palette, bands, 9);
  assert.equal(indices(result.frames[0].pixels)[0], 9);
  assert.equal(indices(result.frames[1].pixels)[31], 9);
  phases.forEach((pixels, phase) => assert.deepEqual(pixels.data, before[phase]));
  assert.throws(() => optimizeMciImages(source(5, 8, [0]), source(5, 8, [0]), palette, bands, 0), /multiples of 4 × 8/);
  assert.throws(() => optimizeMciImages(source(4, 8, [0]), source(8, 8, [0]), palette, bands, 0), /matching dimensions/);
});
