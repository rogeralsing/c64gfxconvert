'use strict';

const {generateBaseFont} = require('./font.cjs');
const {candidates, recommended, orbit} = require('./junction-candidates.cjs');

const rowKey = rows => Array.from(rows).join(',');
function popcount(value) {
  value >>>= 0;
  value -= (value >>> 1) & 0x55555555;
  value = (value & 0x33333333) + ((value >>> 2) & 0x33333333);
  return (((value + (value >>> 4)) & 0x0f0f0f0f) * 0x01010101) >>> 24;
}
function words(rows) {
  return [(rows[0] | rows[1] << 8 | rows[2] << 16 | rows[3] << 24) >>> 0,
    (rows[4] | rows[5] << 8 | rows[6] << 16 | rows[7] << 24) >>> 0];
}
function distance(a, b) { return popcount(a[0] ^ b[0]) + popcount(a[1] ^ b[1]); }
function nearest(target, glyphs, limit = 65) {
  let best = limit;
  for (const glyph of glyphs) {
    best = Math.min(best, distance(target, glyph));
    if (best === 0) break;
  }
  return best;
}

function trueAngledCrossing(candidate) {
  const metadata = candidate.metadata;
  if (candidate.kind !== 'crossing' || metadata.operation !== 'xor' || !metadata.lines) return false;
  const [a, b] = metadata.lines;
  if (!a.a || !a.b || !b.a || !b.b) return false;
  const determinant = a.a * b.b - a.b * b.a;
  if (!determinant) return false;
  const x = (a.threshold * b.b - a.b * b.threshold) / determinant;
  const y = (a.a * b.threshold - a.threshold * b.a) / determinant;
  return Math.abs(x) < 7 && Math.abs(y) < 7;
}

function crossingGroups(pool) {
  const groups = new Map();
  for (const glyph of pool) {
    const id = glyph.metadata.orbitId;
    if (!groups.has(id)) groups.set(id, []);
    groups.get(id).push(glyph);
  }
  return [...groups.entries()].filter(([, glyphs]) => glyphs.length === 16 && glyphs.every(trueAngledCrossing))
    .map(([id, glyphs]) => ({id, glyphs, masks: glyphs.map(glyph => words(glyph.rows))}))
    .sort((a, b) => a.id.localeCompare(b.id));
}

function normalizePatterns(input) {
  const source = Array.isArray(input) ? input : input?.exactPatterns;
  if (!Array.isArray(source)) throw new TypeError('Pass patterns as [{rows:[8 bytes], count:N}] or {exactPatterns:[...]}.');
  const patterns = new Map();
  for (const value of source) {
    if (!Array.isArray(value.rows) || value.rows.length !== 8 || !value.rows.every(byte => Number.isInteger(byte) && byte >= 0 && byte <= 255)) {
      throw new TypeError('Every bitmap pattern needs eight integer row bytes.');
    }
    const count = value.count ?? 1;
    if (!Number.isSafeInteger(count) || count < 1) throw new TypeError('Pattern counts must be positive safe integers.');
    const id = rowKey(value.rows);
    const previous = patterns.get(id);
    if (previous) previous.count += count;
    else patterns.set(id, {rows: value.rows.slice(), count, mask: words(value.rows)});
  }
  return [...patterns.values()].sort((a, b) => rowKey(a.rows).localeCompare(rowKey(b.rows)));
}

function chooseJunctions(input = []) {
  const patterns = normalizePatterns(input);
  const base = generateBaseFont();
  const pool = candidates();
  const quadrants = pool.filter(glyph => glyph.family === 'quadrants');
  const groups = crossingGroups(pool);
  const baseMasks = base.glyphs.slice(0, base.usedCount).map(glyph => words(glyph.rows));
  const quadrantMasks = quadrants.map(glyph => words(glyph.rows));
  for (const pattern of patterns) {
    pattern.baseError = nearest(pattern.mask, baseMasks);
    pattern.quadrantError = nearest(pattern.mask, quadrantMasks, pattern.baseError);
  }

  const ranked = groups.map(group => {
    let gain = 0, improvedInstances = 0, exactInstances = 0, maximumError = 0;
    for (const pattern of patterns) {
      const error = nearest(pattern.mask, group.masks, pattern.quadrantError);
      gain += (pattern.quadrantError - error) * pattern.count;
      if (error < pattern.quadrantError) improvedInstances += pattern.count;
      if (error === 0) exactInstances += pattern.count;
      maximumError = Math.max(maximumError, error);
    }
    return {...group, gain, improvedInstances, exactInstances, maximumError};
  }).sort((a, b) => b.gain - a.gain || b.improvedInstances - a.improvedInstances || b.exactInstances - a.exactInstances || a.id.localeCompare(b.id));

  const fallback = recommended().filter(glyph => glyph.kind === 'crossing' && glyph.family !== 'quadrants');
  const fallbackId = fallback[0].metadata.orbitId;
  const best = ranked.length && ranked[0].gain > 0 ? ranked[0] : ranked.find(group => group.id === fallbackId);
  if (!best) throw new Error('The complete sixteen-shape angled XOR fallback is absent.');
  const glyphs = [...quadrants, ...best.glyphs];
  const selectedMasks = best.masks;
  let baseErrorPixels = 0, quadrantErrorPixels = 0, selectedErrorPixels = 0, instances = 0, maximumBaseError = 0, maximumSelectedError = 0;
  for (const pattern of patterns) {
    const error = nearest(pattern.mask, selectedMasks, pattern.quadrantError);
    baseErrorPixels += pattern.baseError * pattern.count;
    quadrantErrorPixels += pattern.quadrantError * pattern.count;
    selectedErrorPixels += error * pattern.count;
    instances += pattern.count;
    maximumBaseError = Math.max(maximumBaseError, pattern.baseError);
    maximumSelectedError = Math.max(maximumSelectedError, error);
  }
  const selectedKeys = new Set(glyphs.map(glyph => rowKey(glyph.rows)));
  if (glyphs.length !== 26 || selectedKeys.size !== 26) throw new Error('Expected 26 distinct additions.');
  for (const glyph of glyphs) for (const counterpart of orbit(glyph.rows)) {
    if (!selectedKeys.has(rowKey(counterpart.rows))) throw new Error('Selected additions have incomplete symmetry.');
  }
  return {glyphs, report: {
    pass: true, objective: 'Count-weighted nearest-glyph Hamming error for the supplied bitmap patterns; no screen-position or circle constraints.',
    inputPatternClasses: Array.isArray(input) ? input.length : input.exactPatterns.length,
    uniquePatternClasses: patterns.length, instances, baseGlyphs: base.usedCount, quadrantGlyphs: quadrants.length,
    crossingGlyphs: best.glyphs.length, totalAddedGlyphs: glyphs.length, totalGlyphs: base.usedCount + glyphs.length,
    candidateCrossingOrbits: groups.length, chosenOrbitId: best.id, chosenLines: best.glyphs[0].metadata.lines,
    fallbackUsed: !ranked.length || ranked[0].gain === 0,
    baseErrorPixels, quadrantErrorPixels, selectedErrorPixels,
    quadrantGainPixels: baseErrorPixels - quadrantErrorPixels,
    crossingGainPixels: quadrantErrorPixels - selectedErrorPixels,
    totalGainPixels: baseErrorPixels - selectedErrorPixels,
    maximumBaseError, maximumSelectedError,
    completeRotationsMirrorsInverses: true, maximumExcludedFragmentPixels: 2,
    topOrbits: ranked.slice(0, 10).map(group => ({orbitId: group.id, gainPixels: group.gain,
      improvedInstances: group.improvedInstances, exactInstances: group.exactInstances,
      maximumError: group.maximumError, lines: group.glyphs[0].metadata.lines}))
  }};
}

module.exports = {chooseJunctions, crossingGroups};

if (require.main === module) {
  const fs = require('node:fs');
  const input = process.argv[2] ? JSON.parse(fs.readFileSync(process.argv[2], 'utf8')) : [];
  const result = chooseJunctions(input);
  if (process.argv[3]) fs.writeFileSync(process.argv[3], JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result.report, null, 2));
}
