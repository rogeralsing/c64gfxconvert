'use strict';

// Fixed 4x4 logical glyphs, expanded to ordinary 8x8 C64 character bytes.
// Palette fitting uses even poses only; odd poses remain a held-out control.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {SphereRenderer} = require('./matching/sphere-renderer.js');

const HERE = __dirname;
const OUT = path.join(HERE, 'build/font4');
const WIDTH = 320, HEIGHT = 200, CELLS = 1000, FRAMES = 384;
const SETTINGS = {radius: 145, checks: 20, tilt: 65, initialAngle: 0.38, frames: FRAMES, stepDegrees: 0.9375};
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const pop = Uint8Array.from({length: 65536}, (_, value) => {
  let count = 0; for (; value; value &= value - 1) count++; return count;
});
const summarize = values => ({min: Math.min(...values), mean: values.reduce((sum, value) => sum + value, 0) / values.length, max: Math.max(...values)});

function idealFrame(renderer, angle) {
  const source = Buffer.alloc(WIDTH * HEIGHT);
  const sy = Math.sin(angle), cy = Math.cos(angle);
  const pitch = SETTINGS.tilt * Math.PI / 180, sx = Math.sin(pitch), cx = Math.cos(pitch);
  for (let i = 0; i < source.length; i++) {
    if (!renderer.inside[i]) continue;
    const px = renderer.hits[3 * i], py = renderer.hits[3 * i + 1], pz = renderer.hits[3 * i + 2];
    const x = cy * px - sy * pz;
    const z1 = sy * px + cy * pz;
    const y = cx * py + sx * z1;
    const z = -sx * py + cx * z1;
    const u = (Math.atan2(x, z) + Math.PI) * SETTINGS.checks / (2 * Math.PI);
    const v = (Math.asin(Math.max(-1, Math.min(1, y))) + Math.PI / 2) * (SETTINGS.checks / 2) / Math.PI;
    source[i] = (Math.floor(u) ^ Math.floor(v)) & 1;
  }
  return source;
}

function majorityMask(source, cell) {
  const left = cell % 40 * 8, top = Math.floor(cell / 40) * 8;
  let mask = 0;
  for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) {
    const first = (top + 2 * y) * WIDTH + left + 2 * x;
    const filled = source[first] + source[first + 1] + source[first + WIDTH] + source[first + WIDTH + 1];
    // Either answer costs two physical pixels in a tie. Prefer black stably.
    if (filled > 2) mask |= 1 << (4 * y + x);
  }
  return mask;
}

function allowedMask(inside, cell) {
  const left = cell % 40 * 8, top = Math.floor(cell / 40) * 8;
  let mask = 0;
  for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) {
    const first = (top + 2 * y) * WIDTH + left + 2 * x;
    if (inside[first] && inside[first + 1] && inside[first + WIDTH] && inside[first + WIDTH + 1]) mask |= 1 << (4 * y + x);
  }
  return mask;
}

function expandMasks(masks) {
  const font = Buffer.alloc(masks.length * 8);
  for (let glyph = 0; glyph < masks.length; glyph++) for (let y = 0; y < 4; y++) {
    let row = 0;
    for (let x = 0; x < 4; x++) if (masks[glyph] & (1 << (4 * y + x))) row |= 3 << (6 - 2 * x);
    font[glyph * 8 + y * 2] = font[glyph * 8 + y * 2 + 1] = row;
  }
  return font;
}

function initialPalette(frequency, count) {
  const observed = Array.from({length: 65536}, (_, mask) => mask).filter(mask => frequency[mask]);
  const selected = [0, 65535], selectedSet = new Set(selected);
  const distance = Uint8Array.from(observed, mask => Math.min(pop[mask], pop[mask ^ 65535]));
  while (selected.length < count) {
    let best = -1, score = -1;
    for (let i = 0; i < observed.length; i++) {
      if (selectedSet.has(observed[i])) continue;
      const candidate = frequency[observed[i]] * distance[i] * distance[i];
      if (candidate > score) { score = candidate; best = i; }
    }
    assert(best >= 0);
    const next = observed[best]; selected.push(next); selectedSet.add(next);
    for (let i = 0; i < observed.length; i++) distance[i] = Math.min(distance[i], pop[observed[i] ^ next]);
  }
  return selected;
}

function fitPalette(frequency, count) {
  const observed = Array.from({length: 65536}, (_, mask) => mask).filter(mask => frequency[mask]);
  let palette = initialPalette(frequency, count), history = [];
  for (let iteration = 0; iteration < 20; iteration++) {
    const weights = new Float64Array(count), ones = Array.from({length: count}, () => new Float64Array(16));
    const nearest = new Uint8Array(observed.length);
    let objective = 0;
    for (let i = 0; i < observed.length; i++) {
      const mask = observed[i]; let best = 0, error = 17;
      for (let glyph = 0; glyph < palette.length; glyph++) {
        const candidate = pop[mask ^ palette[glyph]];
        if (candidate < error) { error = candidate; best = glyph; }
      }
      nearest[i] = error; objective += frequency[mask] * error; weights[best] += frequency[mask];
      for (let bit = 0; bit < 16; bit++) if (mask & (1 << bit)) ones[best][bit] += frequency[mask];
    }
    history.push(objective);
    const proposed = palette.map((previous, glyph) => {
      if (!weights[glyph]) return previous;
      let mask = 0;
      for (let bit = 0; bit < 16; bit++) {
        if (ones[glyph][bit] * 2 > weights[glyph] ||
            (ones[glyph][bit] * 2 === weights[glyph] && (previous & (1 << bit)))) mask |= 1 << bit;
      }
      return mask;
    });
    // Empty/full are naturally retained by their observed weight; no per-shape
    // optimizer locks are introduced. Fill any duplicate centroid with a real
    // training target that is far from the current distinct palette.
    const unique = Array.from(new Set(proposed));
    while (unique.length < count) {
      let best = -1, score = -1;
      for (let i = 0; i < observed.length; i++) {
        const mask = observed[i];
        let distance = 17;
        for (const glyph of unique) distance = Math.min(distance, pop[mask ^ glyph]);
        const candidate = frequency[mask] * distance * distance;
        if (candidate > score) { score = candidate; best = mask; }
      }
      assert(best >= 0 && !unique.includes(best)); unique.push(best);
    }
    const stable = unique.every((mask, glyph) => mask === palette[glyph]);
    palette = unique;
    if (stable) break;
  }
  assert(palette.includes(0) && palette.includes(65535), 'Observed empty and full forms must survive palette fitting');
  palette = [0, 65535, ...palette.filter(mask => mask !== 0 && mask !== 65535)];
  assert.equal(palette.length, count);
  assert.equal(new Set(palette).size, count);
  return {palette, history};
}

function physicalError(source, mask, cell, inside) {
  const left = cell % 40 * 8, top = Math.floor(cell / 40) * 8;
  let total = 0, spill = 0;
  for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
    const at = (top + y) * WIDTH + left + x;
    const output = (mask >>> (Math.floor(y / 2) * 4 + Math.floor(x / 2))) & 1;
    total += output !== source[at]; spill += output && !inside[at];
  }
  return {total, spill};
}

function main() {
  fs.mkdirSync(OUT, {recursive: true});
  const renderer = new SphereRenderer(); renderer.setRadius(SETTINGS.radius);
  const allowed = Uint16Array.from({length: CELLS}, (_, cell) => allowedMask(renderer.inside, cell));
  const ideal = Buffer.alloc(FRAMES * WIDTH * HEIGHT), target = new Uint16Array(FRAMES * CELLS);
  const trainFrequency = new Uint32Array(65536), controlFrequency = new Uint32Array(65536);
  const quantizationError = [], safeQuantizationError = [];
  for (let pose = 0; pose < FRAMES; pose++) {
    const pixels = idealFrame(renderer, SETTINGS.initialAngle + pose * 2 * Math.PI / FRAMES);
    pixels.copy(ideal, pose * WIDTH * HEIGHT);
    let qError = 0, safeError = 0;
    for (let cell = 0; cell < CELLS; cell++) {
      const mask = majorityMask(pixels, cell); target[pose * CELLS + cell] = mask;
      (pose % 2 ? controlFrequency : trainFrequency)[mask]++;
      qError += physicalError(pixels, mask, cell, renderer.inside).total;
      safeError += physicalError(pixels, mask & allowed[cell], cell, renderer.inside).total;
    }
    quantizationError.push(qError); safeQuantizationError.push(safeError);
    if (pose % 96 === 95) console.log(`Generated mathematical ideal and 4x4 targets ${pose + 1}/${FRAMES}`);
  }
  const previousMetadata = JSON.parse(fs.readFileSync(path.join(HERE, 'c64-preview/build/metadata.json')));
  assert.equal(sha(ideal.subarray(0, WIDTH * HEIGHT)), previousMetadata.frame0.referenceSha256,
    'Mathematical source must match the original HTML renderer');
  assert(idealFrame(renderer, SETTINGS.initialAngle + 2 * Math.PI).equals(ideal.subarray(0, WIDTH * HEIGHT)));
  fs.writeFileSync(path.join(OUT, 'ideal.frames'), ideal);
  const targetBytes = Buffer.alloc(target.length * 2);
  for (let i = 0; i < target.length; i++) targetBytes.writeUInt16LE(target[i], i * 2);
  fs.writeFileSync(path.join(OUT, 'targets16.bin'), targetBytes);
  fs.writeFileSync(path.join(OUT, 'allowed16.bin'), Buffer.from(allowed.buffer));
  const summaries = [];
  for (const count of [64, 128, 256]) {
    const fitted = fitPalette(trainFrequency, count), masks = fitted.palette;
    const font = expandMasks(masks), screens = Buffer.alloc(FRAMES * CELLS);
    const matchCache = new Map(), use = new Uint32Array(count);
    const perFrameErrors = [], perFrameExact = [];
    let trainLogicalError = 0, controlLogicalError = 0, spillPixels = 0;
    for (let pose = 0; pose < FRAMES; pose++) {
      const pixels = ideal.subarray(pose * WIDTH * HEIGHT, (pose + 1) * WIDTH * HEIGHT);
      let error = 0, exact = 0;
      for (let cell = 0; cell < CELLS; cell++) {
        const targetMask = target[pose * CELLS + cell], allowedMask = allowed[cell];
        const key = targetMask + allowedMask * 65536;
        let glyph = matchCache.get(key);
        if (glyph === undefined) {
          let distance = 17; glyph = 0;
          for (let code = 0; code < masks.length; code++) {
            if (masks[code] & (~allowedMask & 65535)) continue;
            const candidate = pop[targetMask ^ masks[code]];
            if (candidate < distance) { distance = candidate; glyph = code; }
          }
          matchCache.set(key, glyph);
        }
        screens[pose * CELLS + cell] = glyph; use[glyph]++;
        const logicalError = pop[targetMask ^ masks[glyph]];
        if (pose % 2) controlLogicalError += logicalError; else trainLogicalError += logicalError;
        exact += logicalError === 0;
        const pixel = physicalError(pixels, masks[glyph], cell, renderer.inside);
        error += pixel.total; spillPixels += pixel.spill;
      }
      perFrameErrors.push(error); perFrameExact.push(exact);
    }
    assert.equal(spillPixels, 0, 'No selected glyph may spill outside the circle');
    assert(screens.every(code => code < count));
    for (let glyph = 0; glyph < masks.length; glyph++) for (let row = 0; row < 8; row++) {
      assert.equal(font[glyph * 8 + row], font[glyph * 8 + (row ^ 1)]);
      for (let bit = 0; bit < 8; bit += 2) assert.equal((font[glyph * 8 + row] >>> bit) & 1, (font[glyph * 8 + row] >>> (bit + 1)) & 1);
    }
    const metadata = {
      pass: true, glyphs: count, logicalPixelsPerGlyph: [4, 4], physicalPixelsPerLogicalPixel: [2, 2],
      fontBytes: font.length, possibleUnrestrictedMasks: 65536,
      emptyGlyph: 0, filledGlyph: 1, settings: SETTINGS,
      training: {poses: 192, parity: 'even', objective: 'frequency-weighted Hamming distance of 16-bit majority masks',
        paletteFitting: 'weighted farthest initialization then Hamming k-modes medians', objectiveHistory: fitted.history,
        observedDistinctMasks: trainFrequency.reduce((sum, value) => sum + (value > 0), 0),
        logicalPixelErrorsPerTile: trainLogicalError / (192 * CELLS)},
      control: {poses: 192, parity: 'odd; not used for palette fitting',
        observedDistinctMasks: controlFrequency.reduce((sum, value) => sum + (value > 0), 0),
        logicalPixelErrorsPerTile: controlLogicalError / (192 * CELLS)},
      fullCorpus: {poses: FRAMES, observedDistinctMajorityMasks: new Set(target).size,
        exactMajorityTargetCellsPerFrame: summarize(perFrameExact),
        exactMajorityTargetCellFraction: perFrameExact.reduce((sum, value) => sum + value, 0) / (FRAMES * CELLS),
        physicalPixelErrorsPerFrame: summarize(perFrameErrors),
        meanFullScreenPixelErrorFraction: perFrameErrors.reduce((sum, value) => sum + value, 0) / (FRAMES * WIDTH * HEIGHT),
        meanSphereAreaPixelErrorFraction: perFrameErrors.reduce((sum, value) => sum + value, 0) / (FRAMES * renderer.surfacePixels),
        usedGlyphs: use.reduce((sum, value) => sum + (value > 0), 0),
        glyphUsage: Array.from(use), worstPose: perFrameErrors.indexOf(Math.max(...perFrameErrors)),
        perFramePixelErrors: perFrameErrors, silhouetteSpillPixels: spillPixels},
      resolutionOnly: {unrestricted4x4PixelErrorsPerFrame: summarize(quantizationError),
        silhouetteSafe4x4PixelErrorsPerFrame: summarize(safeQuantizationError)},
      scope: 'Fixed font fitted to even poses of this one large-sphere scene; odd poses are held out. This is not a claim that 64 glyphs represent every 4x4 mask or every future scene.',
      matching: 'Majority per physical 2x2 block, ties black; nearest 16-bit Hamming glyph constrained to whole2x2 blocks inside the fixed sphere silhouette.',
      hashes: {font: sha(font), screens: sha(screens), mathematicalSource: sha(ideal)},
      nativeTimingMeasured: false
    };
    fs.writeFileSync(path.join(OUT, `font${count}.bin`), font);
    fs.writeFileSync(path.join(OUT, `frames${count}.screen`), screens);
    fs.writeFileSync(path.join(OUT, `masks${count}.json`), JSON.stringify(masks));
    fs.writeFileSync(path.join(OUT, `metadata${count}.json`), JSON.stringify(metadata, null, 2) + '\n');
    summaries.push(metadata);
    console.log(JSON.stringify({glyphs: count, fontBytes: font.length, used: metadata.fullCorpus.usedGlyphs,
      exactCells: metadata.fullCorpus.exactMajorityTargetCellFraction,
      fullScreenError: metadata.fullCorpus.meanFullScreenPixelErrorFraction,
      train: metadata.training.logicalPixelErrorsPerTile, control: metadata.control.logicalPixelErrorsPerTile}));
  }
  fs.writeFileSync(path.join(OUT, 'summary.json'), JSON.stringify({pass: true, settings: SETTINGS, cases: summaries}, null, 2) + '\n');
  return summaries;
}

module.exports = {main, idealFrame, majorityMask, allowedMask, expandMasks, fitPalette};
if (require.main === module) main();
