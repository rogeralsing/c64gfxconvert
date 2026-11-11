'use strict';

// Universal drawing font: one fixed 256-glyph charset, better than PETSCII.
//
// Slot map (canonical order, frozen):
//   0            empty
//   1..8         H:left   thickness 1..8 (8 = full)
//   9..15        H:right  thickness 1..7
//   16..22       V:top    thickness 1..7
//   23..29       V:bottom thickness 1..7
//   ...          d45 chains, 4 sign combos of normal (1,1), every threshold
//   ...          d12 chains, 8 sign combos of normals (1,2),(2,1), sampled
//   ...          H/V bands (1px, 2px), checker phases, Bayer tones
//   last N       content glyphs, optimized once over the multi-corpus census
//
// Every ramp chain is contiguous and ascending in thickness, so a decoder can
// walk a line as code = chain.base + thickness: "start char + increment".
// Chains do not include the empty glyph; thickness 0 maps to slot 0.

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');

const HERE = __dirname;
const ROWS = fn => Array.from({length: 8}, (_, y) => fn(y));
const maskL = k => (255 << (8 - k)) & 255;
const halfPlane = (a, b, t) => ROWS(y => {
  let r = 0;
  for (let x = 0; x < 8; x++) if (a * x + b * y >= t) r |= 128 >>> x;
  return r;
});
const BAYER4 = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];

// DIRS index: the raster direction used to walk a line for each chain family.
const DIRS = [[1, 0], [0, 1], [1, 1], [1, -1], [2, 1], [2, -1], [1, 2], [1, -2]];
const dirIndexFor = (a, b) => DIRS.findIndex(([dx, dy]) => Math.abs(dx) === Math.abs(a) && Math.abs(dy) === Math.abs(b));

function chainDefs({d12Stride = 3} = {}) {
  const chains = [];
  chains.push({name: 'H:left', dir: 0, bitmaps: Array.from({length: 8}, (_, k) => ROWS(() => maskL(k + 1))), minT: 1}); // steps 1..8, 8 = full
  chains.push({name: 'H:right', dir: 0, bitmaps: Array.from({length: 7}, (_, k) => ROWS(() => (1 << (k + 1)) - 1)), minT: 1});
  chains.push({name: 'V:top', dir: 1, bitmaps: Array.from({length: 7}, (_, k) => ROWS(y => y < k + 1 ? 255 : 0)), minT: 1});
  chains.push({name: 'V:bottom', dir: 1, bitmaps: Array.from({length: 7}, (_, k) => ROWS(y => y < 7 - k ? 255 : 0)), minT: 1});
  for (const [sx, sy] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) {
    const a = sx, b = sy;
    const lo = Math.min(0, 7 * a) + Math.min(0, 7 * b), hi = Math.max(0, 7 * a) + Math.max(0, 7 * b);
    chains.push({
      name: `d45:${a},${b}`, dir: dirIndexFor(a, b), minT: lo + 1,
      bitmaps: Array.from({length: hi - lo}, (_, i) => halfPlane(a, b, lo + 1 + i)),
    });
  }
  for (const [a0, b0] of [[1, 2], [2, 1]]) {
    for (const [sx, sy] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) {
      const a = a0 * sx, b = b0 * sy;
      const lo = Math.min(0, 7 * a) + Math.min(0, 7 * b), hi = Math.max(0, 7 * a) + Math.max(0, 7 * b);
      const bitmaps = [];
      for (let t = lo + 1; t <= hi; t += d12Stride) bitmaps.push(halfPlane(a, b, t));
      chains.push({name: `d12:${a},${b}`, dir: dirIndexFor(a, b), minT: lo + 1, bitmaps});
    }
  }
  return chains;
}

function buildFont(options = {}) {
  const {d12Stride = 3, contentRows = []} = options;
  const rows = [];
  const seen = new Set();
  const slotMap = {empty: 0, chains: [], bands: [], checker: [], bayer: [], contentBase: 0};
  const push = (bitmap, tag) => {
    const at = rows.length;
    rows.push(bitmap);
    return at;
  };
  push(ROWS(() => 0));
  for (const chain of chainDefs({d12Stride})) {
    chain.base = rows.length;
    chain.codes = chain.bitmaps.map(b => push(b));
    slotMap.chains.push(chain);
  }
  // bands: horizontal 1px at each row, 2px at each offset; vertical same
  for (let y = 0; y < 8; y++) slotMap.bands.push({name: `h1:${y}`, code: push(ROWS(yy => yy === y ? 255 : 0))});
  for (let y = 0; y <= 6; y++) slotMap.bands.push({name: `h2:${y}`, code: push(ROWS(yy => (yy === y || yy === y + 1) ? 255 : 0))});
  for (let x = 0; x < 8; x++) slotMap.bands.push({name: `v1:${x}`, code: push(ROWS(() => 128 >>> x))});
  for (let x = 0; x <= 6; x++) slotMap.bands.push({name: `v2:${x}`, code: push(ROWS(() => (3 << (6 - x)) & 255))});
  // checker phases
  slotMap.checker.push(push(ROWS(y => ((y & 1) ? 0b01010101 : 0b10101010))));
  slotMap.checker.push(push(ROWS(y => ((y & 1) ? 0b10101010 : 0b01010101))));
  slotMap.checker.push(push(ROWS(y => (y & 2) ? 0b00001111 : 0b11110000)));
  slotMap.checker.push(push(ROWS(y => (y & 2) ? 0b11110000 : 0b00001111)));
  // Bayer 4x4 tones 1..15 (0 = shared empty, 16 = H:left thickness 8 full)
  for (let level = 1; level <= 15; level++) {
    slotMap.bayer.push(push(ROWS(y => {
      let row = 0;
      for (let x = 0; x < 8; x++) if (BAYER4[x % 4][y % 4] < level) row |= 128 >>> x;
      return row;
    })));
  }
  slotMap.contentBase = rows.length;
  for (const bitmap of contentRows) {
    if (rows.length >= 256) break;
    push(bitmap);
  }
  while (rows.length < 256) push(ROWS(y => y === 7 ? 0xAA : 0));
  return {rows: rows.slice(0, 256), slotMap, fixedSlots: slotMap.contentBase, contentSlots: 256 - slotMap.contentBase};
}

function toBytes(font) {
  const out = Buffer.alloc(2048);
  font.rows.forEach((bitmapRows, code) => {
    for (let r = 0; r < 8; r++) out[code * 8 + r] = bitmapRows[r];
  });
  return out;
}

// bitmap-to-chars writes ideal.frames as a 320x200 raster of byte-valued
// binary pixels, not eight packed row bytes per character. Keep that layout
// in one reader so the optimizer and the line study use identical targets.
const CORPORA = [
  ['solid-star', 'three-scene-solid-star/characters'],
  ['sphere-to-cube-zoom', 'raw-literal-storage'],
  ['gradient-dither-cube', 'three-scene-gradient-c64/characters'],
  ['dithered-star', 'three-scene-dithered-star/characters'],
  ['tumbling-star', 'three-scene-tumbling-star/characters'],
  ['glass-diamond', 'three-scene-glass-diamond/characters'],
  ['glass-star', 'three-scene-glass-star/characters'],
  ['glass-outline', 'three-scene-glass-outline/characters'],
  ['flagship-star', 'three-scene-flagship-star/characters'],
];
const sha256 = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

function readCorpus(dir, name = path.basename(dir)) {
  const reference = fs.readFileSync(path.join(dir, 'reference.frames'));
  const font = fs.readFileSync(path.join(dir, 'font.bin'));
  assert(reference.length > 0 && reference.length % 1000 === 0, `${name}: invalid 1000-byte screen frames`);
  const frames = reference.length / 1000;
  assert(font.length > 0 && font.length <= 2048 && font.length % 8 === 0, `${name}: invalid charset`);
  assert(reference.every(code => code < font.length / 8), `${name}: code outside charset`);
  const metadataPath = path.join(dir, 'metadata.json'), studyPath = path.join(dir, 'study.json');
  const study = fs.existsSync(studyPath) ? JSON.parse(fs.readFileSync(studyPath)) : null;
  const metadata = fs.existsSync(metadataPath) ? JSON.parse(fs.readFileSync(metadataPath)) : study?.sourceMetadata || {};
  if (metadata.frameCount !== undefined) assert.equal(metadata.frameCount, frames, `${name}: metadata frame count`);
  if (metadata.width !== undefined) assert.equal(metadata.width, 320, `${name}: raster width`);
  if (metadata.height !== undefined) assert.equal(metadata.height, 200, `${name}: raster height`);
  if (study?.frameCount !== undefined) assert.equal(study.frameCount, frames, `${name}: study frame count`);
  const idealPath = path.join(dir, 'ideal.frames');
  const ideal = fs.existsSync(idealPath) ? fs.readFileSync(idealPath) : null;
  if (ideal) {
    assert.equal(ideal.length, frames * 320 * 200, `${name}: ideal.frames must contain 64000 raster bytes per frame`);
    assert(ideal.every(value => value === 0 || value === 1), `${name}: nonbinary raster pixel`);
  }
  return {name, dir, reference, font, ideal, frames, hasIdeal: Boolean(ideal),
    metadata, loop: metadata.loop || study?.loop || null,
    hashes: {reference: sha256(reference), font: sha256(font), ...(ideal ? {ideal: sha256(ideal)} : {})}};
}

function tileRows(corpus, frame, cell) {
  assert(Number.isInteger(frame) && frame >= 0 && frame < corpus.frames);
  assert(Number.isInteger(cell) && cell >= 0 && cell < 1000);
  if (!corpus.ideal) {
    const start = corpus.reference[frame * 1000 + cell] * 8;
    return Array.from(corpus.font.subarray(start, start + 8));
  }
  const start = frame * 64000 + Math.floor(cell / 40) * 8 * 320 + (cell % 40) * 8;
  return Array.from({length: 8}, (_, row) => {
    let packed = 0;
    for (let x = 0; x < 8; x++) packed |= corpus.ideal[start + row * 320 + x] << (7 - x);
    return packed;
  });
}

module.exports = {buildFont, toBytes, chainDefs, DIRS, CORPORA, readCorpus, tileRows, sha256};

if (require.main === module) {
  const font = buildFont();
  console.log(JSON.stringify({
    fixedSlots: font.fixedSlots,
    contentSlots: font.contentSlots,
    chains: font.slotMap.chains.map(c => `${c.name}@${c.base}(${c.bitmaps.length},dir${c.dir})`),
  }, null, 1));
  fs.mkdirSync(path.join(HERE, 'build'), {recursive: true});
  fs.writeFileSync(path.join(HERE, 'build', 'font-blank.bin'), toBytes(font));
}
