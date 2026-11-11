// Empirical, pose-aligned semantic 2x character zoom. No C64 player changes.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';

const here = path.dirname(fileURLToPath(import.meta.url));
const fontRoot = path.dirname(here);
const build = path.join(fontRoot, 'build/char-zoom-study');
const output = path.join(here, 'results/char-zoom-study');
const accepted = path.join(fontRoot, 'build/three-scene-flagship-star-pal');
const scene = path.join(here, 'demo-flagship-star.mjs');
const exporter = path.join(here, 'export.mjs');
const require = createRequire(import.meta.url);
const {createMatcher, unpackFrame} = require('../bitmap-to-chars.cjs');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const FONT_SHA = '1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1';
const REFERENCE_SHA = '5c245453149adfa4bafd433efa50b606a614ff3264eac46f0c5a0906bc9b698c';
const FRAME_COUNT = 96, TRAIN_COUNT = 72;
const SOURCE_COLS = 40, SOURCE_ROWS = 25, TARGET_COLS = 80, TARGET_ROWS = 50;
const SW = 320, SH = 200, TW = 640, TH = 400;
const read = file => fs.readFileSync(file);
const writeJson = (file, value) => fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');
fs.mkdirSync(build, {recursive: true});
fs.mkdirSync(output, {recursive: true});

// The accepted low-resolution export is reused only after source and byte locks.
const lowMetadata = JSON.parse(read(path.join(accepted, 'render/metadata.json')));
assert.equal(lowMetadata.sourceSha256, sha(read(scene)));
assert.equal(lowMetadata.width, 160); assert.equal(lowMetadata.height, 100);
assert.equal(lowMetadata.quantization.mode, 'ordered');
const lowBitmap = read(path.join(accepted, 'render/bitmap.frames'));
const lowMask = read(path.join(accepted, 'render/object-mask.frames'));
assert.equal(sha(lowBitmap), lowMetadata.hashes.frames);
assert.equal(sha(lowMask), lowMetadata.hashes.objectMask);
const originalReference = read(path.join(here, 'results/flagship-star-ten-buffer/reference.frames'));
const font = read(path.join(here, 'results/flagship-star-ten-buffer/font.bin'));
assert.equal(sha(font), FONT_SHA); assert.equal(sha(originalReference), REFERENCE_SHA);
assert.equal(originalReference.length, 97000);

// Changing only raster dimensions leaves createScene's closed-over PAL camera
// and every update(frame/25) unchanged. Each raw pixel still expands 2x2, so
// ordered-dither pitch/phase is screen anchored at both render resolutions.
const zoomScene = path.join(build, 'scene-2x.mjs');
fs.writeFileSync(zoomScene, `import {config as original, createScene} from ${JSON.stringify(pathToFileURL(scene).href)};\nexport {createScene};\nexport const config={...original,width:320,height:200,sourceDependencies:[${JSON.stringify(scene)}]};\n`);
const highDir = path.join(build, 'render-2x');
const cachedHigh = path.join(highDir, 'metadata.json');
let highMetadata = fs.existsSync(cachedHigh) ? JSON.parse(read(cachedHigh)) : null;
const wrapperSha = sha(read(zoomScene));
if (!highMetadata || highMetadata.sourceSha256 !== wrapperSha ||
    highMetadata.sourceDependencies?.[0]?.sha256 !== sha(read(scene))) {
  // Reuse the installed pinned exporter when this isolated worktree lacks its
  // node_modules. Its source must be byte identical to the current exporter.
  const installedExporter = fs.existsSync(path.join(here, 'node_modules')) ? exporter :
    '/Users/rogerjohansson/.codex/worktrees/c64-sphere-font-publish-20261109/c64/asm/sphere-polygons/font-v2/three-scene/export.mjs';
  assert.equal(sha(read(installedExporter)), sha(read(exporter)));
  execFileSync('rtk', ['proxy', process.execPath, installedExporter,
    '--scene', zoomScene, '--output', highDir, '--quantize', 'ordered', '--write-mask'],
  {stdio: 'inherit', maxBuffer: 1024 * 1024});
  highMetadata = JSON.parse(read(cachedHigh));
}
assert.equal(highMetadata.width, 320); assert.equal(highMetadata.height, 200);
assert.equal(highMetadata.frameCount, 97);
const highBitmap = read(path.join(highDir, 'bitmap.frames'));
const highMask = read(path.join(highDir, 'object-mask.frames'));
assert.equal(sha(highBitmap), highMetadata.hashes.frames);
assert.equal(sha(highMask), highMetadata.hashes.objectMask);

const canonical = Buffer.alloc(256), seenGlyphs = new Map();
for (let code = 0; code < 256; code++) {
  const key = font.subarray(code * 8, code * 8 + 8).toString('hex');
  if (!seenGlyphs.has(key)) seenGlyphs.set(key, code);
  canonical[code] = seenGlyphs.get(key);
}
const glyphPixels = Array.from({length: 256}, (_, code) => Uint8Array.from(
  {length: 64}, (_, pixel) => font[code * 8 + (pixel >> 3)] >> (7 - (pixel & 7)) & 1));
const normalize = chars => Buffer.from(Array.from(chars, code => canonical[code]));
const maskedMatcher = createMatcher(font, true), unmaskedMatcher = createMatcher(font, true);
const sourceChars = Buffer.alloc(FRAME_COUNT * 1000);
const targetChars = Buffer.alloc(FRAME_COUNT * 4000);
const unmaskedChars = Buffer.alloc(FRAME_COUNT * 4000);
const sourcePixels = [], targetPixels = [], targetMasks = [];
const fitStarted = performance.now();
let exactAcceptedPoseFits = 0;

function packed(pixels, width, height) {
  const bytes = Buffer.alloc(width * height / 8);
  for (let i = 0; i < pixels.length; i++) if (pixels[i]) bytes[i >> 3] |= 128 >> (i & 7);
  return bytes;
}
function fitHigh(packedFrame, packedMask) {
  const pixels = Buffer.alloc(TW * TH), mask = Buffer.alloc(TW * TH);
  const screen = Buffer.alloc(4000), unmasked = Buffer.alloc(4000);
  // Existing createMatcher has a fixed 320x200 boundary. Four glyph-aligned
  // quadrants give exactly the same per-cell decisions as a full640x400 call.
  for (let qy = 0; qy < 2; qy++) for (let qx = 0; qx < 2; qx++) {
    const raw = Buffer.alloc(2000), rawMask = Buffer.alloc(2000);
    for (let y = 0; y < 100; y++) {
      packedFrame.copy(raw, y * 20, (qy * 100 + y) * 40 + qx * 20,
        (qy * 100 + y) * 40 + qx * 20 + 20);
      packedMask.copy(rawMask, y * 20, (qy * 100 + y) * 40 + qx * 20,
        (qy * 100 + y) * 40 + qx * 20 + 20);
    }
    const p = unpackFrame(raw, 160, 100), m = unpackFrame(rawMask, 160, 100);
    const fit = normalize(maskedMatcher(p, m).screen);
    const fitUnmasked = normalize(unmaskedMatcher(p).screen);
    for (let y = 0; y < 200; y++) {
      p.copy(pixels, (qy * 200 + y) * TW + qx * 320, y * 320, (y + 1) * 320);
      m.copy(mask, (qy * 200 + y) * TW + qx * 320, y * 320, (y + 1) * 320);
    }
    for (let y = 0; y < 25; y++) {
      fit.copy(screen, (qy * 25 + y) * 80 + qx * 40, y * 40, (y + 1) * 40);
      fitUnmasked.copy(unmasked, (qy * 25 + y) * 80 + qx * 40, y * 40, (y + 1) * 40);
    }
  }
  return {pixels, mask, screen, unmasked};
}
for (let f = 0; f < FRAME_COUNT; f++) {
  const pose = f + 1;
  const p = unpackFrame(lowBitmap.subarray(pose * 2000, (pose + 1) * 2000), 160, 100);
  const m = unpackFrame(lowMask.subarray(pose * 2000, (pose + 1) * 2000), 160, 100);
  const fittedRaw = maskedMatcher(p, m).screen;
  exactAcceptedPoseFits += Number(fittedRaw.equals(originalReference.subarray(pose * 1000, (pose + 1) * 1000)));
  const fitted = normalize(fittedRaw);
  assert(fitted.equals(normalize(originalReference.subarray(pose * 1000, (pose + 1) * 1000))),
    `Normal fit differs from accepted PAL pose${pose}`);
  fitted.copy(sourceChars, f * 1000); sourcePixels.push(p);
  const high = fitHigh(highBitmap.subarray(pose * 8000, (pose + 1) * 8000),
    highMask.subarray(pose * 8000, (pose + 1) * 8000));
  high.screen.copy(targetChars, f * 4000); high.unmasked.copy(unmaskedChars, f * 4000);
  targetPixels.push(high.pixels); targetMasks.push(high.mask);
}
console.log(JSON.stringify({stage: 'matched', poses: FRAME_COUNT,
  normalAll96PosesMatchAcceptedPal: true, seconds: (performance.now() - fitStarted) / 1000}));

const records = Array.from({length: 256}, (_, code) => ({code, canonicalCode: canonical[code],
  trainCount: 0, validationCount: 0, trainHistogram: new Map(), validationHistogram: new Map(),
  trainOnes: new Uint32Array(256)}));
const zeroDiagnostics = {train: {total: 0, genuineBackground: 0, geometryBut1BitBlank: 0,
  whiteDetailAt2x: 0, whiteDetailAlreadyAt1x: 0}, heldout: {total: 0, genuineBackground: 0,
  geometryBut1BitBlank: 0, whiteDetailAt2x: 0, whiteDetailAlreadyAt1x: 0}};
function targetCell(sourceCell, q) {
  return (Math.floor(sourceCell / 40) * 2 + (q >> 1)) * 80 + (sourceCell % 40) * 2 + (q & 1);
}
function pixelAt(pixels, sourceCell, q, pixel) {
  const cell = targetCell(sourceCell, q);
  return pixels[(Math.floor(cell / 80) * 8 + (pixel >> 3)) * TW + (cell % 80) * 8 + (pixel & 7)];
}
for (let f = 0; f < FRAME_COUNT; f++) for (let cell = 0; cell < 1000; cell++) {
  const code = sourceChars[f * 1000 + cell], record = records[code], training = f < TRAIN_COUNT;
  record[training ? 'trainCount' : 'validationCount']++;
  const quad = Array.from({length: 4}, (_, q) => targetChars[f * 4000 + targetCell(cell, q)]);
  const key = quad.join(','), histogram = record[training ? 'trainHistogram' : 'validationHistogram'];
  histogram.set(key, (histogram.get(key) || 0) + 1);
  if (training) for (let q = 0; q < 4; q++) for (let p = 0; p < 64; p++)
    record.trainOnes[q * 64 + p] += pixelAt(targetPixels[f], cell, q, p);
  if (code === 0) {
    let white = 0, mask = 0, lowWhite = 0;
    for (let q = 0; q < 4; q++) for (let p = 0; p < 64; p++) {
      white += pixelAt(targetPixels[f], cell, q, p);
      mask += pixelAt(targetMasks[f], cell, q, p);
    }
    for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++)
      lowWhite += sourcePixels[f][(Math.floor(cell / 40) * 8 + y) * SW + (cell % 40) * 8 + x];
    const d = zeroDiagnostics[training ? 'train' : 'heldout']; d.total++;
    d[white ? 'whiteDetailAt2x' : mask ? 'geometryBut1BitBlank' : 'genuineBackground']++;
    d.whiteDetailAlreadyAt1x += Number(lowWhite > 0);
  }
}

function chooseGlyph(ones, count) {
  let best = 0, bestCost = Infinity;
  for (let code = 0; code < 256; code++) {
    if (canonical[code] !== code) continue;
    let cost = 0;
    for (let p = 0; p < 64; p++) cost += glyphPixels[code][p] ? count - ones[p] : ones[p];
    if (cost < bestCost) { best = code; bestCost = cost; }
  }
  return best;
}
function literalPixel(code, q, p) {
  const x = (q & 1) * 8 + (p & 7), y = (q >> 1) * 8 + (p >> 3);
  return glyphPixels[code][(y >> 1) * 8 + (x >> 1)];
}
const learnedLut = Buffer.alloc(1024), modalLut = Buffer.alloc(1024), literalLut = Buffer.alloc(1024);
for (const record of records) {
  const variants = [...record.trainHistogram].sort((a, b) => b[1] - a[1] ||
    a[0].localeCompare(b[0], 'en', {numeric: true}));
  for (let q = 0; q < 4; q++) {
    const literal = Uint32Array.from({length: 64}, (_, p) => literalPixel(record.code, q, p));
    literalLut[record.code * 4 + q] = chooseGlyph(literal, 1);
    learnedLut[record.code * 4 + q] = record.trainCount ?
      chooseGlyph(record.trainOnes.subarray(q * 64, q * 64 + 64), record.trainCount) : literalLut[record.code * 4 + q];
    modalLut[record.code * 4 + q] = variants.length ? Number(variants[0][0].split(',')[q]) : literalLut[record.code * 4 + q];
  }
  record.variants = variants.map(([quad, count]) => ({chars: quad.split(',').map(Number), count,
    share: count / record.trainCount}));
  record.dominantQuad = record.variants[0]?.chars ?? null;
  record.dominantShare = record.variants[0]?.share ?? null;
  record.variantCount = variants.length;
  record.heldoutVariantCount = record.validationHistogram.size;
  record.unseenInTraining = record.trainCount === 0;
  record.learnedQuad = [...learnedLut.subarray(record.code * 4, record.code * 4 + 4)];
  record.modalQuad = [...modalLut.subarray(record.code * 4, record.code * 4 + 4)];
  record.heldoutCount = record.validationCount;
  record.variants = record.variants.slice(0, 20);
}
// Aliases must behave as the same source shape, including unobserved aliases.
for (let code = 0; code < 256; code++) if (canonical[code] !== code) for (let q = 0; q < 4; q++) {
  learnedLut[code * 4 + q] = learnedLut[canonical[code] * 4 + q];
  modalLut[code * 4 + q] = modalLut[canonical[code] * 4 + q];
  literalLut[code * 4 + q] = literalLut[canonical[code] * 4 + q];
}

const METHODS = ['learned', 'modal', 'literalPixels', 'literalFont', 'directMasked', 'directUnmasked'];
const blankMetric = () => ({pixels: 0, objectPixels: 0, referenceWhitePixels: 0, mismatches: 0,
  objectMismatches: 0, outsideMismatches: 0, outsideWhiteSpill: 0, missedWhitePixels: 0, extraWhitePixels: 0});
const aggregates = Object.fromEntries(['train', 'heldout'].map(split =>
  [split, Object.fromEntries(METHODS.map(method => [method, blankMetric()]))]));
const perFrame = [], charErrors = records.map(() => ({train: {}, heldout: {}}));
for (const c of charErrors) for (const split of ['train', 'heldout'])
  for (const method of METHODS) c[split][method] = {mismatches: 0, objectMismatches: 0, outsideWhiteSpill: 0};
const countMetric = (metric, expected, actual, mask) => {
  metric.pixels++; metric.objectPixels += mask; metric.referenceWhitePixels += expected;
  if (expected !== actual) {
    metric.mismatches++; metric[mask ? 'objectMismatches' : 'outsideMismatches']++;
    metric[expected ? 'missedWhitePixels' : 'extraWhitePixels']++;
  }
  metric.outsideWhiteSpill += Number(!mask && actual);
};
function finishMetric(m) {
  return {...m, fullFrameError: m.mismatches / m.pixels,
    objectError: m.objectPixels ? m.objectMismatches / m.objectPixels : 0,
    outsideSpillRate: m.pixels !== m.objectPixels ? m.outsideWhiteSpill / (m.pixels - m.objectPixels) : 0};
}
for (let f = 0; f < FRAME_COUNT; f++) {
  const split = f < TRAIN_COUNT ? 'train' : 'heldout';
  const frame = {index: f, pose: f + 1, split,
    methods: Object.fromEntries(METHODS.map(method => [method, blankMetric()]))};
  for (let cell = 0; cell < 1000; cell++) {
    const code = sourceChars[f * 1000 + cell];
    for (let q = 0; q < 4; q++) {
      const target = targetCell(cell, q), at = code * 4 + q;
      const glyphs = {learned: glyphPixels[learnedLut[at]], modal: glyphPixels[modalLut[at]],
        literalFont: glyphPixels[literalLut[at]], directMasked: glyphPixels[targetChars[f * 4000 + target]],
        directUnmasked: glyphPixels[unmaskedChars[f * 4000 + target]]};
      for (let p = 0; p < 64; p++) {
        const expected = pixelAt(targetPixels[f], cell, q, p), mask = pixelAt(targetMasks[f], cell, q, p);
        for (const method of METHODS) {
          const actual = method === 'literalPixels' ? literalPixel(code, q, p) : glyphs[method][p];
          countMetric(frame.methods[method], expected, actual, mask);
          const ce = charErrors[code][split][method];
          ce.mismatches += Number(expected !== actual);
          ce.objectMismatches += Number(mask && expected !== actual);
          ce.outsideWhiteSpill += Number(!mask && actual);
        }
      }
    }
  }
  for (const method of METHODS) {
    for (const key of Object.keys(aggregates[split][method])) aggregates[split][method][key] += frame.methods[method][key];
    frame.methods[method] = finishMetric(frame.methods[method]);
  }
  perFrame.push(frame);
}
for (const split of ['train', 'heldout']) for (const method of METHODS) {
  aggregates[split][method] = finishMetric(aggregates[split][method]);
  const m = aggregates[split][method];
  m.extraMismatchesVsDirectMasked = m.mismatches - aggregates[split].directMasked.mismatches;
  m.extraMismatchesVsDirectUnmasked = m.mismatches - aggregates[split].directUnmasked.mismatches;
}
assert(aggregates.train.learned.mismatches <= aggregates.train.modal.mismatches,
  'Minimum-SUM training fit must beat or tie modal quadruplets.');
for (const split of ['train', 'heldout']) for (const method of METHODS)
  if (method !== 'literalPixels') assert(aggregates[split][method].mismatches >= aggregates[split].directUnmasked.mismatches,
    'Independent per-target-cell unmasked fit is the glyph Hamming lower bound.');
for (const r of records) {
  r.errors = charErrors[r.code];
  delete r.trainHistogram; delete r.validationHistogram; delete r.trainOnes;
  if (canonical[r.code] !== r.code) {
    r.learnedQuad = records[canonical[r.code]].learnedQuad;
    r.modalQuad = records[canonical[r.code]].modalQuad;
  }
}

const files = {font: 'font.bin', sourceChars: 'source.chars', targetChars: 'target.chars',
  targetUnmaskedChars: 'target-unmasked.chars', sourceBitmap: 'source.bitmap', targetBitmap: 'target.bitmap',
  mask: 'target.mask', learnedLut: 'learned.lut', modalLut: 'modal.lut', literalLut: 'literal.lut',
  normalization: 'glyph-normalization.bin'};
const bytes = {font, sourceChars, targetChars, targetUnmaskedChars: unmaskedChars,
  sourceBitmap: Buffer.concat(sourcePixels.map(p => packed(p, SW, SH))),
  targetBitmap: Buffer.concat(targetPixels.map(p => packed(p, TW, TH))),
  mask: Buffer.concat(targetMasks.map(p => packed(p, TW, TH))),
  learnedLut, modalLut, literalLut, normalization: canonical};
const hashes = {};
for (const [key, name] of Object.entries(files)) {
  fs.writeFileSync(path.join(output, name), bytes[key]); hashes[key] = {bytes: bytes[key].length, sha256: sha(bytes[key])};
  assert(read(path.join(output, name)).equals(bytes[key]));
}
// Independently inspect the serialized output at raster coordinates, rather
// than reusing the quadrant/stitch helper that produced it.
for (const [input, file, rawWidth, rawHeight] of [[lowBitmap, files.sourceBitmap, 160, 100],
  [highBitmap, files.targetBitmap, 320, 200], [highMask, files.mask, 320, 200]]) {
  const saved = read(path.join(output, file)), width = rawWidth * 2;
  const inputFrameBytes = rawWidth * rawHeight / 8, outputFrameBytes = width * rawHeight * 2 / 8;
  for (let f = 0; f < FRAME_COUNT; f++) for (let y = 0; y < rawHeight; y++) for (let x = 0; x < rawWidth; x++) {
    const expected = input[(f + 1) * inputFrameBytes + y * rawWidth / 8 + (x >> 3)] >> (7 - (x & 7)) & 1;
    for (let dy = 0; dy < 2; dy++) for (let dx = 0; dx < 2; dx++) {
      const at = (y * 2 + dy) * width + x * 2 + dx;
      assert.equal(saved[f * outputFrameBytes + (at >> 3)] >> (7 - (at & 7)) & 1, expected,
        `${file}: serialized raster coordinate differs at pose${f + 1},${x},${y}`);
    }
  }
}
const usedCanonical = records.filter(r => canonical[r.code] === r.code && r.trainCount + r.validationCount > 0);
const objectGlyphs = usedCanonical.filter(r => r.code !== 0);
const ambiguity = {usedCanonicalGlyphs: usedCanonical.length, uniqueFontShapes: seenGlyphs.size,
  nonblankUsedGlyphs: objectGlyphs.length,
  nonblankTrainingOccurrenceWeightedDominantShare: objectGlyphs.reduce((sum, r) => sum + (r.dominantShare || 0) * r.trainCount, 0) /
    objectGlyphs.reduce((sum, r) => sum + r.trainCount, 0),
  heldoutUnseenGlyphs: records.filter(r => r.validationCount && !r.trainCount).map(r => ({code: r.code, count: r.validationCount})),
  nonblankSingleVariantGlyphs: objectGlyphs.filter(r => r.variantCount === 1).length};
const study = {schemaVersion: 1, title: 'Empirisk 2× teckenzoom', frameCount: FRAME_COUNT,
  source: {cols: SOURCE_COLS, rows: SOURCE_ROWS, width: SW, height: SH, frameBytes: 1000},
  target: {cols: TARGET_COLS, rows: TARGET_ROWS, width: TW, height: TH, frameBytes: 4000},
  files, hashes, fontSha256: FONT_SHA,
  frames: perFrame.map(({index, pose, split}) => ({index, pose, split})),
  split: {train: {firstPose: 1, lastPose: 72, count: 72}, heldout: {firstPose: 73, lastPose: 96, count: 24}},
  coordinates: {rule: 'source cell(x,y) maps to target cells(2*x,2*y)..(2*x+1,2*y+1); crop only after full-view render',
    glyphPixels: '8x8', quadrupletOrder: ['TL', 'TR', 'BL', 'BR'], packedBitmap: 'MSB-first, top-to-bottom, byte-aligned rows',
    sourceRowStrideBytes: 40, targetRowStrideBytes: 80, displayPixelAspect: 59 / 63},
  method: {geometry: 'Same mesh, pose, lighting and PAL-correct orthographic frustum; only GPU raster160x100→320x200; both expand pixels2x2.',
    dither: 'Ordered4x4 Bayer remains at fixed raw screen-pixel pitch and phase; no bitmap/dither upscaling.',
    sourceSelection: 'Existing immutable-font matcher with per-occurrence object-mask admissibility, identical to accepted PAL renderer.',
    learned: 'For each normalized source shape and output quadrant, minimize SUM pixel Hamming to training2x reference bitmaps; lowest glyph-code ties.',
    modal: 'Most frequent observed direct-masked target quadruplet in training; lexicographic numeric tie.',
    duplicates: 'Identical font bitmaps normalize to lowest glyph code before histograms/training; aliases share LUT.',
    unseenFallback: 'Nearest font glyph per quadrant of literal2x repeated source glyph pixels; lowest code ties.',
    directMasked: 'Existing direct target renderer: independent per-cell Hamming fit, no white glyph bits allowed outside GPU object mask; NOT an unconditional Hamming lower bound.',
    directUnmasked: 'Independent per-target-cell minimum Hamming font fit without mask; true glyph context-loss lower bound.',
    literalPixels: 'Repeat every source glyph pixel2x2, no target-font fit.',
    literalFont: 'Nearest target font to each quadrant of literal repeated source glyph.'},
  metrics: aggregates, ambiguity, zeroDiagnostics, characters: records, perFrame,
  provenance: {sourceScene: path.relative(here, scene), sourceSceneSha256: sha(read(scene)),
    exporterSha256: sha(read(exporter)), acceptedPalReferenceSha256: REFERENCE_SHA,
    lowExport: {bitmapSha256: sha(lowBitmap), maskSha256: sha(lowMask)},
    highExport: {bitmapSha256: sha(highBitmap), maskSha256: sha(highMask), metadata: path.relative(here, cachedHigh)},
    originalSourceFontUnchanged: sha(read(path.join(here, 'results/flagship-star-ten-buffer/font.bin'))) === FONT_SHA}};
writeJson(path.join(output, 'study.json'), study);
const proof = {passed: true, sourceAll96PosesEqualAcceptedPal: true, fontLockedAndUnchanged: true,
  sourceAll96PosesByteEqualAcceptedPal: exactAcceptedPoseFits === FRAME_COUNT,
  exactAcceptedPoseFits, serializedRasterBitsMatchGpuAtEveryPixel: true,
  normalizedGlyphCodes: true, fullView2xCellAlignment: true, trainHeldoutDisjoint: true,
  heldoutNeverUsedToFitLut: true, learnedTrainingErrorAtMostModal: true,
  directUnmaskedLowerBoundForAllGlyphMethods: true, filesReadBackByteIdentical: true,
  metrics: aggregates, ambiguity, zeroDiagnostics, hashes};
writeJson(path.join(output, 'proof.json'), proof);
fs.copyFileSync(fileURLToPath(import.meta.url), path.join(output, 'study-char-zoom.mjs'));
fs.copyFileSync(zoomScene, path.join(output, 'scene-2x.mjs'));
writeJson(path.join(output, 'render-2x-metadata.json'), highMetadata);
fs.writeFileSync(path.join(output, 'README.md'), `# Empirical character zoom\n\nRun from the C64 repository with \`rtk proxy node asm/sphere-polygons/font-v2/three-scene/study-char-zoom.mjs\`. The page consumes \`study.json\` and its listed packed binary files.\n\n96 existing star poses:1–72 train;73–96 contiguous heldout. Full-view geometry is rerendered at twice the raster dimensions with the same camera and pixel/dither pitch. Each source character selects four output characters. All source/font/player files stay unchanged.\n\nCompare minimum-SUM learned LUT, modal quadruplet LUT, literal repeated pixels and direct target font fits. Object-only errors and outside spill are separate; char0 over a dark object is not automatically a lost feature. Direct masked fit follows the existing renderer, while unmasked direct fit is the actual per-cell Hamming lower bound. Each LUT is1024B; this is offline measurement, with no C64 player or FPS claim.\n\nSee \`proof.json\` for PAL-source equivalence, locks and serialized-byte checks.\n`);
console.log(JSON.stringify({stage: 'complete', output, metrics: aggregates, ambiguity, zeroDiagnostics}, null, 2));
