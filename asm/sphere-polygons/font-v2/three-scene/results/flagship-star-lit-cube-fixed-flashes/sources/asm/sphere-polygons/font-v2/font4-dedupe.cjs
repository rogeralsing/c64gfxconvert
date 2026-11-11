'use strict';

// Coarsen the existing selected font; do not train, add or select new shapes.
// Remapping existing character codes preserves the original animation choices.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {generateFont, toBytes} = require('./font.cjs');

const HERE = __dirname;
const OUT = path.join(HERE, 'build/font4-dedupe');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

function coarsen(rows, mode = 'majority', phaseX = 0, phaseY = 0) {
  const output = Buffer.alloc(8);
  for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) {
    let filled;
    if (mode === 'nearest') filled = (rows[y * 2 + phaseY] >>> (7 - (x * 2 + phaseX))) & 1;
    else {
      let total = 0;
      for (let dy = 0; dy < 2; dy++) for (let dx = 0; dx < 2; dx++) total += (rows[y * 2 + dy] >>> (7 - (x * 2 + dx))) & 1;
      filled = Number(total > 2); // A 2/2 tie has equal error; choose black.
    }
    if (filled) {
      output[y * 2] |= 3 << (6 - 2 * x);
      output[y * 2 + 1] |= 3 << (6 - 2 * x);
    }
  }
  return output;
}

function dedupe(original, mode = 'majority', phaseX = 0, phaseY = 0) {
  const seen = new Map(), glyphs = [], map = [];
  for (let code = 0; code < 256; code++) {
    const rows = coarsen(original.subarray(code * 8, code * 8 + 8), mode, phaseX, phaseY);
    const key = rows.toString('hex');
    if (!seen.has(key)) { seen.set(key, glyphs.length); glyphs.push(rows); }
    map.push(seen.get(key));
  }
  return {font: Buffer.concat(glyphs), glyphs, map};
}

function main() {
  fs.mkdirSync(OUT, {recursive: true});
  const original = toBytes(generateFont());
  assert.equal(original.length, 2048);
  assert.equal(sha(original), 'e4071e1e3176e3ee65eeb5fc2df5bb3eccab7b733b9ea7cbb276a2f3a65a1aac');
  const transformed = dedupe(original);
  const {font, glyphs, map} = transformed;
  const source = fs.readFileSync(path.join(HERE, 'c64-preview/build/movie.frames'));
  assert.equal(source.length, 384000);
  const remapped = Buffer.alloc(source.length);
  for (let index = 0; index < source.length; index++) remapped[index] = map[source[index]];
  const usage = new Uint32Array(glyphs.length);
  const oldGroups = Array.from({length: glyphs.length}, () => []);
  for (let old = 0; old < 256; old++) oldGroups[map[old]].push(old);
  for (const code of remapped) usage[code]++;
  for (let old = 0; old < 256; old++) {
    const expected = coarsen(original.subarray(old * 8, old * 8 + 8));
    assert(font.subarray(map[old] * 8, map[old] * 8 + 8).equals(expected));
  }
  for (const rows of glyphs) for (let row = 0; row < 8; row++) {
    assert.equal(rows[row], rows[row ^ 1]);
    for (let bit = 0; bit < 8; bit += 2) assert.equal((rows[row] >>> bit) & 1, (rows[row] >>> (bit + 1)) & 1);
  }
  const nearestCounts = [];
  for (let phaseY = 0; phaseY < 2; phaseY++) for (let phaseX = 0; phaseX < 2; phaseX++) {
    const candidate = dedupe(original, 'nearest', phaseX, phaseY);
    nearestCounts.push({phaseX, phaseY, uniqueGlyphs: candidate.glyphs.length, fontBytes: candidate.font.length});
  }
  const metadata = {
    pass: true, originalGlyphs: 256, uniqueGlyphs: glyphs.length,
    removedDuplicates: 256 - glyphs.length, originalFontBytes: 2048, fontBytes: font.length,
    logicalPixelsPerGlyph: [4, 4], physicalPixelsPerLogicalPixel: [2, 2],
    transformation: 'Existing8x8 font only: per2x2 block majority, ties black; expand each resulting bit to2x2, then deduplicate equal8-byte glyphs in first-occurrence order.',
    sourceSelection: 'Existing384000 character codes remapped through oldToNew only. No new palette fitting, target rendering or character matching.',
    emptyGlyph: map[0], filledGlyph: map[15], oldEmptyGlyph: 0, oldFilledGlyph: 15,
    nearestNeighborPhaseCounts: nearestCounts,
    frameCount: 384, screenBytes: 1000,
    usedGlyphs: usage.reduce((sum, count) => sum + (count > 0), 0),
    glyphUsage: Array.from(usage), originalCodesByNewGlyph: oldGroups,
    hashes: {originalFont: sha(original), font: sha(font), originalScreens: sha(source), remappedScreens: sha(remapped)},
    verification: {originalGlyphsTransformedAndCompared: 256, displayedCodesRemapped: remapped.length,
      expandedGlyphsStrictly2x2: true, sourceFontUnchanged: true, noNewShapesSelected: true},
    nativeTimingMeasured: false
  };
  fs.writeFileSync(path.join(OUT, 'font.bin'), font);
  fs.writeFileSync(path.join(OUT, 'reference.frames'), remapped);
  fs.writeFileSync(path.join(OUT, 'map.json'), JSON.stringify(map));
  fs.writeFileSync(path.join(OUT, 'glyphs.json'), JSON.stringify(glyphs.map((rows, index) => ({index, rows: Array.from(rows), originalCodes: oldGroups[index]})), null, 2) + '\n');
  fs.writeFileSync(path.join(OUT, 'metadata.json'), JSON.stringify(metadata, null, 2) + '\n');
  console.log(JSON.stringify({pass: true, uniqueGlyphs: glyphs.length, removedDuplicates: 256 - glyphs.length,
    fontBytes: font.length, emptyGlyph: metadata.emptyGlyph, filledGlyph: metadata.filledGlyph,
    nearestNeighborPhaseCounts: nearestCounts, usedGlyphs: metadata.usedGlyphs, hashes: metadata.hashes}, null, 2));
  return metadata;
}

module.exports = {main, coarsen, dedupe};
if (require.main === module) main();
