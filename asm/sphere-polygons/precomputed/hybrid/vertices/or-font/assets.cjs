'use strict';

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const zlib = require('node:zlib');

const ROOT = path.resolve(__dirname, '../../../..');
const spanAtlas = require('../span-atlas/generate.cjs');
const {createModel} = require(path.join(ROOT, 'native-model.cjs'));
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const pop = Uint8Array.from({length: 256}, (_, value) => {
  let count = 0;
  for (; value; value &= value - 1) count++;
  return count;
});

function glyphKey(font, code) {
  return font.subarray(code * 8, code * 8 + 8).toString('hex');
}

function glyphError(a, ac, b, bc) {
  let error = 0;
  for (let y = 0; y < 8; y++) error += pop[a[ac * 8 + y] ^ b[bc * 8 + y]];
  return error;
}

function safeAt(font, code, cell) {
  const left = (cell % 40) * 8;
  const top = Math.floor(cell / 40) * 8;
  for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
    if (((font[code * 8 + y] >>> (7 - x)) & 1) &&
        (left + x - 160) ** 2 + (top + y - 100) ** 2 > 94 ** 2) return false;
  }
  return true;
}

// Every byte remains a logical eight-probe coverage mask. Visually identical
// slots must remain distinct because later polygon contributions OR into them.
function makeMaskFont(oldFont, glyphLut) {
  const font = Buffer.alloc(2048);
  for (let mask = 0; mask < 256; mask++) {
    oldFont.copy(font, mask * 8, glyphLut[mask] * 8, glyphLut[mask] * 8 + 8);
  }
  assert(font.subarray(0, 8).every(byte => byte === 0));
  assert(font.subarray(255 * 8).every(byte => byte === 255));
  return font;
}

function makeCircleMap(font, baseline) {
  const sourceCount = Math.max(...baseline.compact.filter(value => value !== 255)) + 1;
  assert.equal(baseline.remap.length % sourceCount, 0);
  const groups = Array.from({length: baseline.remap.length / sourceCount}, () => []);
  for (let record = 0; record < baseline.clipRecords.length; record += 4) {
    const cell = baseline.clipRecords.readUInt16LE(record);
    const offset = baseline.clipRecords.readUInt16LE(record + 2);
    assert.equal(offset % sourceCount, 0);
    groups[offset / sourceCount].push(cell);
  }
  const circleMap = Buffer.alloc(baseline.remap.length);
  groups.forEach((cells, group) => {
    assert(cells.length);
    // Baseline classes share their allowed old-font glyphs. Check every cell
    // anyway so the safety property does not depend on that implementation.
    const candidates = Array.from({length: 256}, (_, code) => code)
      .filter(code => cells.every(cell => safeAt(font, code, cell)));
    assert(candidates.includes(0));
    for (let source = 0; source < sourceCount; source++) {
      const target = baseline.remap[group * sourceCount + source];
      let best = 0, bestError = 65;
      for (const code of candidates) {
        const error = glyphError(font, code, baseline.font, target);
        if (error < bestError) {best = code; bestError = error;}
      }
      circleMap[group * sourceCount + source] = best;
    }
  });
  const coverageCompact = Buffer.alloc(256);
  for (let mask = 0; mask < 256; mask++) coverageCompact[mask] = baseline.compact[baseline.glyphLut[mask]];
  assert(!coverageCompact.includes(255));
  return {circleMap, coverageCompact, sourceCount, groupCount: groups.length};
}

function resolve(coverage, tables, clipRecords) {
  const screen = Buffer.from(coverage);
  for (let record = 0; record < clipRecords.length; record += 4) {
    const cell = clipRecords.readUInt16LE(record);
    const offset = clipRecords.readUInt16LE(record + 2);
    screen[cell] = tables.circleMap[offset + tables.coverageCompact[screen[cell]]];
  }
  return screen;
}

function pixels(font, screen) {
  const image = Buffer.alloc(64000);
  for (let cell = 0; cell < 1000; cell++) for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
    image[(Math.floor(cell / 40) * 8 + y) * 320 + (cell % 40) * 8 + x] =
      (font[screen[cell] * 8 + y] >>> (7 - x)) & 1;
  }
  return image;
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function png(width, height, rgb) {
  const chunk = (type, data) => {
    const name = Buffer.from(type), result = Buffer.alloc(data.length + 12);
    result.writeUInt32BE(data.length);name.copy(result, 4);data.copy(result, 8);
    result.writeUInt32BE(crc32(Buffer.concat([name, data])), data.length + 8);
    return result;
  };
  const header = Buffer.alloc(13);header.writeUInt32BE(width);header.writeUInt32BE(height, 4);
  header[8] = 8;header[9] = 2;
  const scanlines = Buffer.alloc((width * 3 + 1) * height);
  for (let y = 0; y < height; y++) rgb.copy(scanlines, y * (width * 3 + 1) + 1, y * width * 3, (y + 1) * width * 3);
  return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]), chunk('IHDR', header), chunk('IDAT', zlib.deflateSync(scanlines)), chunk('IEND', Buffer.alloc(0))]);
}

function visualDiff(before, after) {
  const rgb = Buffer.alloc(960 * 200 * 3);
  for (let y = 0; y < 200; y++) for (let x = 0; x < 320; x++) {
    const index = y * 320 + x, a = before[index], b = after[index];
    for (let panel = 0; panel < 3; panel++) {
      const offset = (y * 960 + panel * 320 + x) * 3;
      const color = panel < 2 ? [255 * (panel ? b : a), 255 * (panel ? b : a), 255 * (panel ? b : a)] :
        a === b ? [a * 64, a * 64, a * 64] : a ? [255, 64, 64] : [64, 220, 255];
      rgb.set(color, offset);
    }
  }
  return png(960, 200, rgb);
}

function findCorpus(explicit) {
  const candidates = explicit ? [path.resolve(explicit)] : [
    path.join(__dirname, '../span-atlas/build/assets/spans.sa64'),
    path.join(ROOT, 'precomputed/hybrid/results/vertices/span-atlas/spans.sa64')
  ];
  const corpus = candidates.find(file => fs.existsSync(file));
  if (!corpus) throw Error('Build the baseline span-atlas corpus first');
  return corpus;
}

function generate(outputDir = path.join(__dirname, 'build/assets'), options = {}) {
  const corpus = findCorpus(options.corpus);
  const movie = fs.readFileSync(corpus), decoded = spanAtlas.deserialize(movie), model = createModel();
  const baseline = model.assets, font = makeMaskFont(baseline.font, baseline.glyphLut);
  const tables = makeCircleMap(font, baseline), coverages = [], references = [], oldReferences = [], frameErrors = [];
  const usedMasks = new Set(), usedUnclippedMasks = new Set(), neededClipGlyphs = new Set(), clipCells = new Set();
  for (let record = 0; record < baseline.clipRecords.length; record += 4) clipCells.add(baseline.clipRecords.readUInt16LE(record));
  let protrudingPixels = 0, changedTiles = 0, worstTileError = 0, lostPixels = 0, addedPixels = 0;
  for (const spans of decoded.frames) {
    const coverage = spanAtlas.coverageFor(spans, model.tables), oldScreen = Buffer.from(model.resolve(coverage));
    const screen = resolve(coverage, tables, baseline.clipRecords);
    const oldPixels = pixels(baseline.font, oldScreen), newPixels = pixels(font, screen);
    let error = 0, changed = 0;
    for (let cell = 0; cell < 1000; cell++) {
      usedMasks.add(coverage[cell]);
      if (!clipCells.has(cell)) {
        usedUnclippedMasks.add(coverage[cell]);
        assert.equal(glyphError(font, screen[cell], baseline.font, oldScreen[cell]), 0);
      } else neededClipGlyphs.add(oldScreen[cell]);
      const tileError = glyphError(font, screen[cell], baseline.font, oldScreen[cell]);
      if (tileError) changed++;
      worstTileError = Math.max(worstTileError, tileError);
    }
    for (let index = 0; index < 64000; index++) {
      if (oldPixels[index] !== newPixels[index]) {
        error++;
        if (oldPixels[index]) lostPixels++; else addedPixels++;
      }
      if (newPixels[index] && (index % 320 - 160) ** 2 + (Math.floor(index / 320) - 100) ** 2 > 94 ** 2) protrudingPixels++;
    }
    changedTiles += changed;frameErrors.push({frame: frameErrors.length, pixels: error, tiles: changed});
    coverages.push(Buffer.from(coverage));references.push(screen);oldReferences.push(oldScreen);
  }
  assert.equal(protrudingPixels, 0);

  // Investigate aliases only in memory. The shipped charset still preserves
  // every one of the 256 logical masks for arbitrary future geometry.
  const fontImages = new Set(Array.from({length: 256}, (_, mask) => glyphKey(font, mask)));
  const missingClipGlyphs = [...neededClipGlyphs].filter(code => !fontImages.has(glyphKey(baseline.font, code))).sort((a,b) => a-b);
  const spareMasks = Array.from({length: 256}, (_, mask) => mask).filter(mask => !usedMasks.has(mask));
  let corpusAliasExact = false;
  if (missingClipGlyphs.length <= spareMasks.length) {
    const aliasFont = Buffer.from(font);
    missingClipGlyphs.forEach((code, index) => baseline.font.copy(aliasFont, spareMasks[index] * 8, code * 8, code * 8 + 8));
    const aliasTables = makeCircleMap(aliasFont, baseline);
    corpusAliasExact = coverages.every((coverage, frame) => {
      for (const mask of usedMasks) assert.equal(glyphError(aliasFont, mask, font, mask), 0);
      const actual = pixels(aliasFont, resolve(coverage, aliasTables, baseline.clipRecords));
      return actual.equals(pixels(baseline.font, oldReferences[frame]));
    });
    assert(corpusAliasExact);
  }

  const worst = frameErrors.reduce((a,b) => b.pixels > a.pixels ? b : a);
  const shared = {
    'font.bin': font,
    'coverage-compact.bin': tables.coverageCompact,
    'circle-map.bin': tables.circleMap,
    'clip-records.bin': baseline.clipRecords
  };
  for (const name of ['sample-row-lo', 'sample-row-hi', 'left-masks', 'right-masks']) {
    shared[name + '.bin'] = fs.readFileSync(path.join(ROOT, 'assets', name + '.bin'));
  }
  const report = {
    pass: true, format: 'SA64 v1 with coverage-indexed OR font', frames: decoded.frames.length,
    charset: {bytes: font.length, slots: 256, distinctBitmaps: fontImages.size, duplicateSlotsRetained: 256 - fontImages.size,
      all256MaskGlyphsEqualBaseline: true, emptyCode: 0, fullCode: 255},
    clip: {cells: clipCells.size, classes: tables.groupCount, sourceGlyphs: tables.sourceCount,
      coverageCompactBytes: tables.coverageCompact.length, mapBytes: tables.circleMap.length,
      recordsBytes: baseline.clipRecords.length, protrudingPixels,
      objective: 'minimum Hamming error against baseline clipped glyph among zero-protrusion mask-font glyphs'},
    errorAgainstBaselineClipped: {pixels: lostPixels + addedPixels, meanPixelsPerFrame: (lostPixels + addedPixels) / decoded.frames.length,
      fractionOfAllPixels: (lostPixels + addedPixels) / (decoded.frames.length * 64000), lostPixels, addedPixels,
      changedTiles, meanChangedTilesPerFrame: changedTiles / decoded.frames.length, worstTileError,
      worstFrame: worst, frames: frameErrors},
    reachability: {distinctFinalMasks: usedMasks.size, distinctUnclippedMasks: usedUnclippedMasks.size,
      globallyUnusedFinalMasks: spareMasks.length, requiredClippedGlyphs: neededClipGlyphs.size,
      requiredClippedGlyphsAbsentFromGeneralMaskFont: missingClipGlyphs.length,
      missingOldGlyphCodes: missingClipGlyphs, corpusAliasExact,
      aliasNote: 'Verified in memory only; aliases would change unused mask slots and are not shipped because new poses may reach them.'},
    movieBytes: movie.length, movieSha256: sha(movie), fontSha256: sha(font),
    sourceCorpus: path.relative(ROOT, corpus), coverageBytesCompared: decoded.frames.length * 1000,
    screenBytesCompared: decoded.frames.length * 1000,
    sharedTableBytes: Object.values(shared).reduce((sum, bytes) => sum + bytes.length, 0),
    bytes: Object.fromEntries(Object.entries(shared).map(([name, bytes]) => [name, bytes.length])),
    visualDiff: {file: 'clip-diff.png', frame: worst.frame, panels: ['baseline clipped', 'OR-font clipped', 'red removed; cyan added']}
  };
  fs.mkdirSync(outputDir, {recursive: true});
  for (const [name, bytes] of Object.entries(shared)) fs.writeFileSync(path.join(outputDir, name), bytes);
  fs.writeFileSync(path.join(outputDir, 'spans.sa64'), movie);
  fs.writeFileSync(path.join(outputDir, 'reference.bin'), Buffer.concat(references));
  fs.writeFileSync(path.join(outputDir, 'coverage-reference.bin'), Buffer.concat(coverages));
  fs.writeFileSync(path.join(outputDir, 'baseline-reference.bin'), Buffer.concat(oldReferences));
  fs.writeFileSync(path.join(outputDir, 'clip-diff.png'), visualDiff(pixels(baseline.font, oldReferences[worst.frame]), pixels(font, references[worst.frame])));
  fs.writeFileSync(path.join(outputDir, 'manifest.json'), JSON.stringify(report, null, 2) + '\n');
  return report;
}

module.exports = {generate, makeMaskFont, makeCircleMap, resolve};
if (require.main === module) console.log(JSON.stringify(generate(process.argv[2]), null, 2));
