'use strict';

// The training corpus supplies weighted reference patterns, not glyph choices.
// Evaluation below still renders every frame through the actual HTML matcher
// and its circle constraint. Iteration-control validation monitors later rounds;
// the separate final-test cases remain unevaluated until search has stopped.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {createRuntime, canonicalKey, tileRows} = require('./error-study.cjs');
const {generateFont} = require('./font.cjs');
const OUT = path.join(__dirname, 'build');
const keyOf = rows => Array.from(rows, row => row.toString(16).padStart(2, '0')).join('');
const rowsOf = key => Array.from({length: 8}, (_, y) => parseInt(key.slice(y * 2, y * 2 + 2), 16));
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const sum = (rows, name) => rows.reduce((total, row) => total + row[name], 0);

function makeCases(split, tilts, radii, checksValues, frames) {
  const cases = [];
  for (const tilt of tilts) for (const radius of radii) for (const checks of checksValues) {
    const index = cases.length;
    const [phaseStart, phaseStep] = {train: [17.125, 37.25], validation: [29.96875, 53.75], 'final-test': [41.4375, 71.375]}[split];
    const phaseDegrees = (phaseStart + index * phaseStep) % 360;
    cases.push({id: `${split}-t${tilt}-r${radius}-c${checks}`, split, tilt, radius, checks, frames, phaseDegrees});
  }
  return cases;
}
const trainingCases = () => makeCases('train', [-45, 0, 22, 50], [64, 94, 120], [12, 16, 24], 32);
const validationCases = () => makeCases('validation', [-30, 15, 60], [78, 106], [14, 20], 24);
// Merely defining this grid does not render it or expose its reference targets.
// writeBundle deliberately evaluates only training and iteration-control cases.
const finalCases = () => makeCases('final-test', [-60, -15, 35, 65], [70, 100], [18, 22], 24);

function usageRows(palette) {
  return palette.glyphs.slice(0, palette.usedCount).map((glyph, index) => ({index, label: glyph.label,
    kind: glyph.kind, predefined: glyph.predefined === true, rows: Array.from(glyph.rows),
    count: 0, sphereCount: 0, framesUsed: 0, sphereFramesUsed: 0, weightedSphereUsage: 0}));
}

function addPattern(map, key, rows, error, example, exactKey) {
  let entry = map.get(key);
  if (!entry) {entry = {key, rows, count: 0, totalError: 0, maxError: 0, example, exactKeys: new Set()}; map.set(key, entry);}
  entry.count++; entry.totalError += error; entry.exactKeys.add(exactKey);
  if (error > entry.maxError) {entry.maxError = error; entry.example = example;}
}

function finishPatterns(map, grouped) {
  return [...map.values()].map(({exactKeys, ...entry}) => ({...entry,
    meanError: entry.totalError / entry.count,
    ...(grouped ? {variants: exactKeys.size, exactPatternKeys: [...exactKeys].sort()} : {})
  })).sort((a, b) => b.count - a.count || b.totalError - a.totalError || a.key.localeCompare(b.key));
}

function assertCounts(report) {
  const {summary, usage, exactPatterns, patternGroups, errorHistogram} = report;
  assert.equal(sum(usage, 'count'), summary.tilesChecked);
  assert.equal(sum(usage, 'sphereCount'), summary.activeSphereTilesChecked);
  assert(Math.abs(sum(usage, 'weightedSphereUsage') - 1) < 1e-10);
  assert.equal(sum(exactPatterns, 'count'), summary.badTiles);
  assert.equal(sum(patternGroups, 'count'), summary.badTiles);
  assert.equal(sum(exactPatterns, 'totalError'), summary.filteredPixelErrors);
  assert.equal(sum(patternGroups, 'totalError'), summary.filteredPixelErrors);
  assert.equal(errorHistogram.reduce((total, n) => total + n, 0), summary.tilesChecked);
  assert.equal(errorHistogram.slice(4).reduce((total, n) => total + n, 0), summary.badTiles);
}

function summarize({usage, perCase, exactPatterns, patternGroups}) {
  const frames = sum(perCase, 'frames'), unused = usage.filter(glyph => glyph.sphereCount === 0);
  const totalPixelErrors = sum(perCase, 'totalPixelErrors');
  return {tilesChecked: frames * 1000, totalPixelErrors, filteredPixelErrors: sum(perCase, 'filteredPixelErrors'),
    badTiles: sum(perCase, 'badTiles'), uniqueExactPatterns: exactPatterns.length, symmetryGroups: patternGroups.length,
    activeSphereTilesChecked: sum(perCase, 'activeSphereTilesChecked'), unusedGlyphs: unused.length,
    unusedGlyphIndices: unused.map(glyph => glyph.index), meanPixelErrorsPerFrame: totalPixelErrors / frames,
    meanCaseNormalizedError: sum(perCase, 'meanNormalizedError') / perCase.length,
    normalizedError: totalPixelErrors / sum(perCase, 'surfacePixelOccurrences')};
}

function evaluatePalette(palette, cases, options = {}) {
  assert(cases.length > 0);
  const started = Date.now(), {renderer, font, sources, runtimeDirectory, runtimeVersion} = createRuntime(palette, {
    sourceDirectory: options.sourceDirectory || options.runtimeDirectory, runtimeVersion: options.runtimeVersion});
  const usage = usageRows(palette), perCase = [], exactMap = new Map(), groupMap = new Map();
  const canonicalCache = new Map(), targetMap = new Map(), errorHistogram = Array(65).fill(0);
  let absoluteFrame = 0;
  for (const item of cases) {
    const caseUsage = usage.map(({index}) => ({index, count: 0, sphereCount: 0, framesUsed: 0, sphereFramesUsed: 0, weightedSphereUsage: 0}));
    const targetCounts = new Map(), exactKeys = new Set(), groupKeys = new Set();
    const result = {...item, tilesChecked: item.frames * 1000, activeSphereTilesChecked: 0,
      surfacePixels: 0, surfacePixelOccurrences: 0, totalPixelErrors: 0, filteredPixelErrors: 0, badTiles: 0};
    for (let frame = 0; frame < item.frames; frame++) {
      const angle = (item.phaseDegrees + frame * 360 / item.frames) * Math.PI / 180;
      const stats = renderer.render({angle, tilt: item.tilt, radius: item.radius, checks: item.checks, solid: false}, font);
      result.surfacePixels = stats.surfacePixels; result.surfacePixelOccurrences += stats.surfacePixels;
      const frameUses = new Uint16Array(font.count), sphereUses = new Uint16Array(font.count);
      let independentErrors = 0;
      for (let cell = 0; cell < 1000; cell++) {
        const index = renderer.screen[cell], glyph = font.glyphs[index];
        caseUsage[index].count++; frameUses[index]++;
        if (renderer.activeCells[cell]) {caseUsage[index].sphereCount++; sphereUses[index]++; result.activeSphereTilesChecked++;}
        const rows = tileRows(renderer.source, cell), key = keyOf(rows);
        if (options.collectTargets) {
          const current = targetCounts.get(key);
          if (current) current.count++; else targetCounts.set(key, {rows, count: 1});
        }
        const selectedRows = Array.from(glyph.rows);
        let error = 0;
        for (let y = 0; y < 8; y++) error += fontPopcount(rows[y] ^ selectedRows[y]);
        assert.equal(error, stats.errors[cell]); independentErrors += error; errorHistogram[error]++;
        if (error <= 3) continue;
        let canonical = canonicalCache.get(key);
        if (canonical === undefined) {canonical = canonicalKey(rows); canonicalCache.set(key, canonical);}
        const example = {caseId: item.id, split: item.split, frame, absoluteFrame, cell,
          angleRadians: angle, targetRows: rows, selectedRows, glyphIndex: index, error};
        addPattern(exactMap, key, rows, error, example, key);
        addPattern(groupMap, canonical, rowsOf(canonical), error, example, key);
        exactKeys.add(key); groupKeys.add(canonical); result.badTiles++; result.filteredPixelErrors += error;
      }
      assert.equal(independentErrors, stats.mismatches);
      result.totalPixelErrors += independentErrors;
      for (let index = 0; index < font.count; index++) {
        caseUsage[index].framesUsed += Number(frameUses[index] !== 0);
        caseUsage[index].sphereFramesUsed += Number(sphereUses[index] !== 0);
      }
      absoluteFrame++;
    }
    for (let index = 0; index < usage.length; index++) {
      const value = caseUsage[index];
      for (const field of ['count', 'sphereCount', 'framesUsed', 'sphereFramesUsed']) usage[index][field] += value[field];
      value.weightedSphereUsage = value.sphereCount / result.activeSphereTilesChecked;
      usage[index].weightedSphereUsage += value.weightedSphereUsage / cases.length;
    }
    if (options.collectTargets) for (const [key, value] of targetCounts) {
      let target = targetMap.get(key);
      if (!target) {target = {key, rows: value.rows, count: 0, weight: 0}; targetMap.set(key, target);}
      target.count += value.count;
      target.weight += value.count / (item.frames * result.surfacePixels * cases.length);
    }
    result.meanNormalizedError = result.totalPixelErrors / result.surfacePixelOccurrences;
    result.uniqueExactPatterns = exactKeys.size; result.symmetryGroups = groupKeys.size; result.usage = caseUsage;
    perCase.push(result);
    if (options.progress) options.progress({caseId: item.id, completed: perCase.length, total: cases.length, seconds: (Date.now() - started) / 1000});
  }
  const exactPatterns = finishPatterns(exactMap, false), patternGroups = finishPatterns(groupMap, true);
  const frames = sum(perCase, 'frames');
  const report = {pass: true, comparison: 'matching', threshold: 3, frames,
    thresholdMeaning: 'Strictly more than3 different pixels per8x8 tile:4..64 errors qualify.',
    occurrenceMeaning: 'Raw pattern frequencies count qualifying tile occurrences across every sampled case and frame.',
    font: {count: font.count, activeBytes: font.count * 8, signature: font.signature,
      sha256: sha(Buffer.from(palette.glyphs.slice(0, palette.usedCount).flatMap(glyph => glyph.rows)))},
    runtime: {sourceDirectory: runtimeDirectory, version: runtimeVersion},
    sample: {scope: options.scope || 'Balanced multi-view corpus', caseCount: cases.length,
      cases: perCase.map(({id, split, tilt, radius, checks, frames, phaseDegrees, surfacePixels}) =>
        ({id, split, tilt, radius, checks, frames, phaseDegrees, surfacePixels, weight: 1 / cases.length})),
      normalization: 'Each case receives equal weight; pixel error is divided by its actual visible sphere-pixel area and frame count.',
      yawDegreesPerCase: 360},
    summary: summarize({usage, perCase, exactPatterns, patternGroups}),
    grouping: {exact: 'Identical eight reference-bitmap row bytes, before font selection.',
      symmetry: 'Quarter-turn, reflection and black/white inversion of the same target bitmap:16 transformations.'},
    usageMeaning: {count: 'Raw occurrences across every screen tile, including background.',
      sphereCount: 'Raw occurrences in geometrically active sphere tiles.',
      weightedSphereUsage: 'Mean across cases of sphereCount divided by that case active sphere-tile count; all glyphs sum to1.'},
    assertions: {allTileErrorsIndependentlyRecounted: true, exactCountEqualsBadTiles: true, groupCountEqualsBadTiles: true,
      exactErrorSumEqualsFilteredErrors: true, groupErrorSumEqualsFilteredErrors: true,
      allGlyphUsesEqualTilesChecked: true, sphereGlyphUsesEqualActiveSphereTilesChecked: true, caseWeightsEqual: true},
    errorHistogram, perCase, exactPatterns, patternGroups, usage, sourceSha256: sources, runtimeMs: Date.now() - started};
  assertCounts(report);
  if (options.collectTargets) {
    report.targetPatterns = [...targetMap.values()].sort((a, b) => b.weight - a.weight || a.key.localeCompare(b.key));
    assert.equal(sum(report.targetPatterns, 'count'), frames * 1000);
    const expectedWeight = cases.reduce((total, item, index) => total + 1000 / (perCase[index].surfacePixels * cases.length), 0);
    assert(Math.abs(sum(report.targetPatterns, 'weight') - expectedWeight) < 1e-10);
  }
  return report;
}

function fontPopcount(value) {
  value -= (value >>> 1) & 0x55;
  value = (value & 0x33) + ((value >>> 2) & 0x33);
  return (value + (value >>> 4)) & 15;
}

function mergePatterns(reports, field, grouped) {
  const map = new Map();
  for (const report of reports) for (const entry of report[field]) {
    let target = map.get(entry.key);
    if (!target) {target = {...entry, count: 0, totalError: 0, maxError: 0, exactKeys: new Set()}; map.set(entry.key, target);}
    target.count += entry.count; target.totalError += entry.totalError;
    if (entry.maxError > target.maxError) {target.maxError = entry.maxError; target.example = entry.example;}
    for (const key of grouped ? entry.exactPatternKeys : [entry.key]) target.exactKeys.add(key);
  }
  return finishPatterns(map, grouped);
}

function combineReports(reports) {
  assert(reports.length > 0);
  for (const report of reports) {
    assert.equal(report.font.sha256, reports[0].font.sha256);
    assert.deepEqual(report.sourceSha256, reports[0].sourceSha256);
  }
  const perCase = reports.flatMap(report => report.perCase), count = perCase.length;
  const usage = reports[0].usage.map(value => ({...value, count: 0, sphereCount: 0, framesUsed: 0, sphereFramesUsed: 0, weightedSphereUsage: 0}));
  for (const report of reports) for (const value of report.usage) {
    for (const field of ['count', 'sphereCount', 'framesUsed', 'sphereFramesUsed']) usage[value.index][field] += value[field];
    usage[value.index].weightedSphereUsage += value.weightedSphereUsage * report.perCase.length / count;
  }
  const exactPatterns = mergePatterns(reports, 'exactPatterns', false), patternGroups = mergePatterns(reports, 'patternGroups', true);
  const first = reports[0], report = {...first, frames: sum(perCase, 'frames'),
    sample: {...first.sample, scope: 'Balanced training and iteration-control cases, combined for usage evidence', caseCount: count,
      cases: reports.flatMap(report => report.sample.cases).map(item => ({...item, weight: 1 / count}))},
    summary: summarize({usage, perCase, exactPatterns, patternGroups}),
    errorHistogram: Array.from({length: 65}, (_, error) => reports.reduce((sum, report) => sum + report.errorHistogram[error], 0)),
    usage, perCase, exactPatterns, patternGroups, runtimeMs: sum(reports, 'runtimeMs')};
  delete report.targetPatterns;
  assertCounts(report);
  return report;
}

function writeJson(filename, value) {
  const destination = path.join(OUT, filename), temporary = destination + '.tmp';
  fs.mkdirSync(OUT, {recursive: true}); fs.writeFileSync(temporary, JSON.stringify(value, null, 2) + '\n');
  fs.renameSync(temporary, destination); return destination;
}

function writeBundle(palette = generateFont(), prefix = 'general-baseline', options = {}) {
  const runtimeOptions = {sourceDirectory: options.sourceDirectory || options.runtimeDirectory, runtimeVersion: options.runtimeVersion};
  const train = evaluatePalette(palette, trainingCases(), {...runtimeOptions, scope: 'Balanced training corpus', collectTargets: options.collectTargets === true, progress: options.progress});
  if (train.targetPatterns) {
    writeJson('general-train-patterns.json', {scope: 'TRAIN ONLY: reference targets across balanced cases', caseCount: train.sample.caseCount,
      frames: train.frames, normalization: train.sample.normalization,
      weightMeaning: 'Sum of occurrence count/(case frames * visible sphere pixels * number of cases); weighted Hamming loss equals mean normalized per-case pixel error before circle constraints.',
      cases: train.sample.cases, targetPatterns: train.targetPatterns});
    delete train.targetPatterns;
    if (options.patternsReady) options.patternsReady(path.join(OUT, 'general-train-patterns.json'));
  }
  writeJson(prefix + '-train.json', train);
  const validation = evaluatePalette(palette, validationCases(), {...runtimeOptions, scope: 'Iteration-control validation corpus', progress: options.progress});
  writeJson(prefix + '-validation.json', validation);
  const combined = combineReports([train, validation]);
  writeJson(prefix + '-combined.json', combined);
  return {train, validation, combined};
}

module.exports = {trainingCases, validationCases, finalCases, evaluatePalette, combineReports, writeBundle};

if (require.main === module) {
  const args = process.argv.slice(2), value = (flag, fallback) => {const index = args.indexOf(flag); return index < 0 ? fallback : args[index + 1];};
  const palettePath = value('--palette', null), input = palettePath ? JSON.parse(fs.readFileSync(palettePath, 'utf8')) : null;
  const palette = input ? (input.palette || input) : generateFont();
  const prefix = value('--prefix', 'general-baseline');
  const bundle = writeBundle(palette, prefix, {collectTargets: args.includes('--collect'), runtimeDirectory: value('--runtime-dir', undefined),
    progress: progress => console.log(JSON.stringify(progress)), patternsReady: file => console.log(JSON.stringify({trainingPatternsReady: file}))});
  console.log(JSON.stringify(Object.fromEntries(Object.entries(bundle).map(([split, report]) => [split,
    {file: path.join(OUT, prefix + '-' + split + '.json'), frames: report.frames, caseCount: report.sample.caseCount,
      font: report.font, summary: report.summary, runtimeMs: report.runtimeMs}])), null, 2));
}
