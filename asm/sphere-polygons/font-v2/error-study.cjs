'use strict';

// Offline font diagnostics use the same bitmap reference and constrained
// nearest-glyph renderer as the HTML preview. No analysis data enters playback.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {buildBrowserSource} = require('./browser-font.cjs');
const {generateBaseFont, generateFont} = require('./font.cjs');

const EXPERIMENT = path.join(__dirname, 'legacy');
const keyOf = rows => Array.from(rows, row => row.toString(16).padStart(2, '0')).join('');
const rowsOf = key => Array.from({length: 8}, (_, y) => parseInt(key.slice(y * 2, y * 2 + 2), 16));
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

function transformRows(rows, turn, mirror, inverted) {
  return Array.from({length: 8}, (_, y) => {
    let row = 0;
    for (let x = 0; x < 8; x++) {
      let sx = x, sy = y;
      if (mirror) sx = 7 - sx;
      for (let n = 0; n < turn; n++) [sx, sy] = [sy, 7 - sx];
      const bit = ((rows[sy] >>> (7 - sx)) & 1) ^ Number(inverted);
      if (bit) row |= 128 >>> x;
    }
    return row;
  });
}

function canonicalKey(rows) {
  let best = null;
  for (let turn = 0; turn < 4; turn++) for (const mirror of [false, true]) for (const inverted of [false, true]) {
    const key = keyOf(transformRows(rows, turn, mirror, inverted));
    if (best === null || key < best) best = key;
  }
  return best;
}

function tileRows(pixels, cell) {
  const left = (cell % 40) * 8, top = Math.floor(cell / 40) * 8;
  return Array.from({length: 8}, (_, y) => {
    let row = 0;
    for (let x = 0; x < 8; x++) if (pixels[(top + y) * 320 + left + x]) row |= 128 >>> x;
    return row;
  });
}

function popcount(value) {
  value = value - ((value >>> 1) & 0x55);
  value = (value & 0x33) + ((value >>> 2) & 0x33);
  return (value + (value >>> 4)) & 15;
}

function createRuntime(palette, options = {}) {
  const context = vm.createContext({});
  vm.runInContext(buildBrowserSource(palette), context);
  const runtimeDirectory = path.resolve(options.sourceDirectory || EXPERIMENT);
  const sources = {};
  for (const name of ['direct-core.js', 'sphere-renderer.js']) {
    const filename = path.join(runtimeDirectory, name), source = fs.readFileSync(filename, 'utf8');
    sources[filename] = sha(source);
    vm.runInContext(source, context, {filename});
  }
  const font = context.GlyphMath.generateFont(256);
  assert.equal(font.count, palette.usedCount);
  assert.equal(font.glyphs.length, palette.usedCount);
  for (let index = 0; index < font.count; index++) assert.deepEqual(Array.from(font.glyphs[index].rows), palette.glyphs[index].rows);
  const runtimeVersion = options.runtimeVersion || (runtimeDirectory === EXPERIMENT ? 'legacy-html-v1'
    : 'source-sha256-' + sha(Object.values(sources).join('|')).slice(0, 16));
  return {renderer: new context.SphereMath.SphereRenderer(), font, sources, runtimeDirectory, runtimeVersion};
}

function record(map, key, rows, error, example, exactKey) {
  let entry = map.get(key);
  if (!entry) {
    entry = {key, rows, count: 0, totalError: 0, maxError: 0, example, exactKeys: new Set()};
    map.set(key, entry);
  }
  entry.count++;
  entry.totalError += error;
  if (error > entry.maxError) {entry.maxError = error; entry.example = example;}
  entry.exactKeys.add(exactKey);
}

function finishEntries(map, grouped) {
  return [...map.values()].map(entry => {
    const {exactKeys, ...value} = entry;
    value.meanError = entry.totalError / entry.count;
    if (grouped) {value.variants = exactKeys.size; value.exactPatternKeys = [...exactKeys].sort();}
    return value;
  }).sort((a, b) => b.count - a.count || b.totalError - a.totalError || a.key.localeCompare(b.key));
}

function runStudy(palette = generateBaseFont(), options = {}) {
  const frames = options.frames ?? 384, threshold = options.threshold ?? 3;
  const startAngle = options.startAngle ?? 0.38, periodDegrees = options.periodDegrees ?? 360;
  assert(Number.isInteger(frames) && frames > 0);
  assert(Number.isInteger(threshold) && threshold >= 0 && threshold < 64);
  const state = {angle: startAngle, tilt: options.tilt ?? 22, checks: options.checks ?? 12,
    radius: options.radius ?? 94, solid: false};
  const {renderer, font, sources, runtimeDirectory, runtimeVersion} = createRuntime(palette, {
    sourceDirectory: options.sourceDirectory || options.runtimeDirectory, runtimeVersion: options.runtimeVersion});
  const exact = new Map(), groups = new Map(), canonicalCache = new Map();
  const errorHistogram = Array(65).fill(0), frameSummaries = [];
  const usage = palette.glyphs.slice(0, palette.usedCount).map((glyph, index) => ({index,
    label: glyph.label, kind: glyph.kind, predefined: index < 30 || glyph.predefined === true, rows: Array.from(glyph.rows),
    count: 0, sphereCount: 0, framesUsed: 0, sphereFramesUsed: 0}));
  let totalPixelErrors = 0, filteredPixelErrors = 0, badTiles = 0, totalSurfacePixels = 0, activeSphereTilesChecked = 0, firstBitmap;
  for (let frame = 0; frame < frames; frame++) {
    state.angle = startAngle + frame * periodDegrees * Math.PI / (180 * frames);
    const stats = renderer.render(state, font);
    if (!frame) firstBitmap = Uint8Array.from(renderer.source);
    let frameErrors = 0, frameBadTiles = 0, frameFilteredErrors = 0, maxError = 0;
    const frameUses = new Uint16Array(font.count), sphereFrameUses = new Uint16Array(font.count);
    for (let cell = 0; cell < 1000; cell++) {
      const glyphIndex = renderer.screen[cell];
      usage[glyphIndex].count++; frameUses[glyphIndex]++;
      if (renderer.activeCells[cell]) {usage[glyphIndex].sphereCount++; sphereFrameUses[glyphIndex]++; activeSphereTilesChecked++;}
      const rows = tileRows(renderer.source, cell), selectedRows = Array.from(font.glyphs[renderer.screen[cell]].rows);
      const error = rows.reduce((sum, row, y) => sum + popcount(row ^ selectedRows[y]), 0);
      // Independently count row-byte XOR errors against the renderer's own
      // pixel-loop count before including the tile in either census.
      assert.equal(error, stats.errors[cell]);
      errorHistogram[error]++;
      frameErrors += error;
      maxError = Math.max(maxError, error);
      if (error <= threshold) continue;
      const key = keyOf(rows);
      let canonical = canonicalCache.get(key);
      if (canonical === undefined) {canonical = canonicalKey(rows); canonicalCache.set(key, canonical);}
      const example = {frame, cell, targetRows: rows, selectedRows, glyphIndex: renderer.screen[cell], error};
      record(exact, key, rows, error, example, key);
      record(groups, canonical, rowsOf(canonical), error, example, key);
      frameBadTiles++; frameFilteredErrors += error;
    }
    for (let index = 0; index < usage.length; index++) {
      usage[index].framesUsed += Number(frameUses[index] !== 0);
      usage[index].sphereFramesUsed += Number(sphereFrameUses[index] !== 0);
    }
    assert.equal(frameErrors, stats.mismatches);
    totalPixelErrors += frameErrors;
    filteredPixelErrors += frameFilteredErrors;
    badTiles += frameBadTiles;
    totalSurfacePixels += stats.surfacePixels;
    frameSummaries.push({frame, angleRadians: state.angle, angleDegrees: state.angle * 180 / Math.PI,
      totalPixelErrors: frameErrors, badTiles: frameBadTiles, filteredPixelErrors: frameFilteredErrors, maxError});
  }
  const closureComparisons = {};
  for (const degrees of new Set([60, 360, periodDegrees])) {
    state.angle = startAngle + degrees * Math.PI / 180;
    renderer.render(state, font);
    let differences = 0;
    for (let pixel = 0; pixel < firstBitmap.length; pixel++) differences += Number(firstBitmap[pixel] !== renderer.source[pixel]);
    closureComparisons[degrees] = differences;
  }
  const endpointPixelDifferences = closureComparisons[periodDegrees];
  const exactPatterns = finishEntries(exact, false), patternGroups = finishEntries(groups, true);
  const sum = (array, field) => array.reduce((value, row) => value + row[field], 0);
  assert.equal(sum(exactPatterns, 'count'), badTiles);
  assert.equal(sum(patternGroups, 'count'), badTiles);
  assert.equal(sum(exactPatterns, 'totalError'), filteredPixelErrors);
  assert.equal(sum(patternGroups, 'totalError'), filteredPixelErrors);
  assert.equal(errorHistogram.reduce((count, n) => count + n, 0), frames * 1000);
  assert.equal(errorHistogram.slice(threshold + 1).reduce((count, n) => count + n, 0), badTiles);
  assert.equal(sum(usage, 'count'), frames * 1000);
  assert.equal(sum(usage, 'sphereCount'), activeSphereTilesChecked);
  const unused = usage.filter(glyph => glyph.sphereCount === 0);
  const bytes = Buffer.from(palette.glyphs.slice(0, palette.usedCount).flatMap(glyph => glyph.rows));
  return {pass: true, comparison: 'matching', threshold,
    thresholdMeaning: `Strictly more than ${threshold} different pixels in one 8x8 character tile; ${threshold + 1}..64 errors qualify.`,
    occurrenceMeaning: 'Pattern frequencies count qualifying tile occurrences only, across all sampled frames.',
    frames, font: {count: font.count, activeBytes: bytes.length, signature: font.signature, sha256: sha(bytes)},
    runtime: {sourceDirectory: runtimeDirectory, version: runtimeVersion},
    sample: {startAngle, periodDegrees, stepDegrees: periodDegrees / frames, tilt: state.tilt, checks: state.checks, radius: state.radius,
      endpointPixelDifferences, closesAtSampleEndpoint: endpointPixelDifferences === 0, closureComparisons},
    summary: {tilesChecked: frames * 1000, totalPixelErrors, filteredPixelErrors, badTiles,
      uniqueExactPatterns: exactPatterns.length, symmetryGroups: patternGroups.length,
      activeSphereTilesChecked, unusedGlyphs: unused.length,
      unusedGlyphIndices: unused.map(glyph => glyph.index),
      meanErrorPerBadTile: badTiles ? filteredPixelErrors / badTiles : 0,
      meanPixelErrorsPerFrame: totalPixelErrors / frames, normalizedError: totalPixelErrors / totalSurfacePixels},
    grouping: {exact: 'Identical eight reference-bitmap row bytes, before font selection.',
      symmetry: 'The same target bitmap after any quarter-turn, reflection or black/white inversion; 16 transformations.'},
    usageMeaning: {count: 'Occurrences across all screen tiles, including the empty background.',
      sphereCount: 'Occurrences in geometrically active sphere tiles only; use this count to assess rare glyphs.',
      predefined: 'Identifies the first30 prescribed basic shapes for display only; every glyph has equal ranking eligibility.'},
    assertions: {allTileErrorsIndependentlyRecounted: true, exactCountEqualsBadTiles: true, groupCountEqualsBadTiles: true,
      exactErrorSumEqualsFilteredErrors: true, groupErrorSumEqualsFilteredErrors: true,
      allGlyphUsesEqualTilesChecked: true, sphereGlyphUsesEqualActiveSphereTilesChecked: true},
    errorHistogram, frameSummaries, exactPatterns, patternGroups, usage, sourceSha256: sources};
}

module.exports = {runStudy, canonicalKey, transformRows, tileRows, createRuntime};

if (require.main === module) {
  const args = process.argv.slice(2), current = args.includes('--current');
  const value = (flag, fallback) => {const index = args.indexOf(flag); return index < 0 ? fallback : args[index + 1];};
  const output = path.resolve(value('--output', path.join(__dirname, 'build', current ? 'error-current.json' : 'error-baseline.json')));
  const report = runStudy(current ? generateFont() : generateBaseFont(), {
    frames: Number(value('--frames', 384)), periodDegrees: Number(value('--degrees', 360)),
    sourceDirectory: value('--runtime-dir', undefined)});
  fs.mkdirSync(path.dirname(output), {recursive: true});
  fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({output, font: report.font, sample: report.sample, summary: report.summary, assertions: report.assertions}, null, 2));
}
