'use strict';

// Fit a general mathematical font to case-balanced bitmap samples. Complete
// D4/reflection/inversion orbits move together; no particular glyph is locked.
const crypto = require('node:crypto');
const fontModule = require('./font.cjs');
const {candidates, orbit} = require('./junction-candidates.cjs');
const {candidates: lineCandidates} = require('./line-candidates.cjs');

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
function filled(rows) { return rows.reduce((sum, row) => sum + popcount(row), 0); }

function mathematicalPool() {
  const base = fontModule.generateBaseFont();
  const source = [...base.glyphs.slice(0, base.usedCount), ...lineCandidates(15), ...candidates()];
  const seen = new Set(), glyphs = [];
  for (const value of source) {
    const key = rowKey(value.rows);
    if (seen.has(key)) continue;
    seen.add(key);
    glyphs.push({...value, rows: Array.from(value.rows), fixed: false});
  }
  const groups = new Map();
  for (const glyph of glyphs) {
    const id = orbit(glyph.rows).map(value => rowKey(value.rows)).sort()[0];
    if (!groups.has(id)) groups.set(id, []);
    groups.get(id).push(glyph);
  }
  const result = [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([id, values], index) => {
    const masks = values.map(glyph => words(glyph.rows));
    return {id, index, glyphs: values, size: values.length,
      lo: Uint32Array.from(masks, value => value[0]), hi: Uint32Array.from(masks, value => value[1])};
  });
  const keys = new Set(glyphs.map(glyph => rowKey(glyph.rows)));
  for (const group of result) {
    if (![2, 4, 8, 16].includes(group.size)) throw new Error('Unexpected mathematical orbit size.');
    for (const value of orbit(group.glyphs[0].rows)) if (!keys.has(rowKey(value.rows))) throw new Error('Incomplete mathematical candidate orbit.');
  }
  return {glyphs, groups: result};
}

function parsePatterns(training) {
  if (!Array.isArray(training.targetPatterns) || !training.targetPatterns.length) throw new Error('Expected nonempty training targetPatterns.');
  const patterns = training.targetPatterns;
  const lo = new Uint32Array(patterns.length), hi = new Uint32Array(patterns.length), weights = new Float64Array(patterns.length);
  const allowedLo = new Uint32Array(patterns.length).fill(0xffffffff), allowedHi = new Uint32Array(patterns.length).fill(0xffffffff);
  let hasConstraints = false;
  let instances = 0, weightSum = 0;
  patterns.forEach((value, index) => {
    if (!Array.isArray(value.rows) || value.rows.length !== 8 || !value.rows.every(byte => Number.isInteger(byte) && byte >= 0 && byte <= 255)) throw new Error('Invalid eight-byte bitmap pattern.');
    if (!Number.isFinite(value.weight) || value.weight < 0) throw new Error('Expected nonnegative case-balanced pattern weight.');
    [lo[index], hi[index]] = words(value.rows);
    if (value.allowedRows !== undefined) {
      if (!Array.isArray(value.allowedRows) || value.allowedRows.length !== 8 || !value.allowedRows.every(byte => Number.isInteger(byte) && byte >= 0 && byte <= 255)) throw new Error('Invalid eight-byte allowed mask.');
      [allowedLo[index], allowedHi[index]] = words(value.allowedRows);
      if ((lo[index] & ~allowedLo[index]) || (hi[index] & ~allowedHi[index])) throw new Error('Target pixels escape the allowed mask.');
      hasConstraints = true;
    }
    weights[index] = value.weight;
    weightSum += value.weight;
    instances += value.count || 0;
  });
  return {patterns, lo, hi, allowedLo, allowedHi, hasConstraints, weights, instances, weightSum};
}

function optimizeGeneral(training, options = {}) {
  const started = performance.now(), progress = options.progress || (() => {});
  const maxSwaps = options.maxSwaps ?? 8, maxSeconds = options.maxSeconds ?? 150;
  const pool = mathematicalPool(), groups = pool.groups, data = parsePatterns(training), count = data.patterns.length;
  const seed = options.seed || fontModule.generateJunctionFont();
  const seedKeys = new Set(seed.glyphs.slice(0, seed.usedCount).map(glyph => rowKey(glyph.rows)));
  const seedGroups = groups.filter(group => group.glyphs.every(glyph => seedKeys.has(rowKey(glyph.rows)))).map(group => group.index);
  if (seedGroups.reduce((sum, index) => sum + groups[index].size, 0) !== 256) throw new Error('Seed must contain 256 complete candidate-orbit glyphs.');

  const distances = groups.map(group => {
    const result = new Uint8Array(count);
    for (let i = 0; i < count; i++) {
      const lo = data.lo[i], hi = data.hi[i];
      let minimum = 65;
      for (let glyph = 0; glyph < group.size; glyph++) {
        if ((group.lo[glyph] & ~data.allowedLo[i]) || (group.hi[glyph] & ~data.allowedHi[i])) continue;
        const error = popcount(lo ^ group.lo[glyph]) + popcount(hi ^ group.hi[glyph]);
        if (error < minimum) minimum = error;
        if (!minimum) break;
      }
      result[i] = minimum;
    }
    return result;
  });
  progress({stage: 'distances', patterns: count, glyphs: pool.glyphs.length, orbits: groups.length});

  function objective(selected) {
    const best = new Uint8Array(count).fill(65);
    for (const index of selected) {
      const row = distances[index];
      for (let i = 0; i < count; i++) if (row[i] < best[i]) best[i] = row[i];
    }
    let error = 0;
    for (let i = 0; i < count; i++) error += best[i] * data.weights[i];
    return {error, best};
  }
  function canFill(remaining, selected, excluded) {
    const reachable = new Uint8Array(remaining + 1); reachable[0] = 1;
    for (const group of groups) {
      if (selected.has(group.index) || group.index === excluded) continue;
      for (let value = remaining; value >= group.size; value--) if (reachable[value - group.size]) reachable[value] = 1;
    }
    return Boolean(reachable[remaining]);
  }

  // A fresh greedy seed can change the number of 2/4/8/16-shape orbits. The
  // subsequent swaps preserve each orbit size, but never any particular shape.
  function greedySeed() {
    const selected = new Set(), best = new Uint8Array(count).fill(65);
    let used = 0;
    while (used < 256) {
      let winner = -1, winnerScore = -1;
      for (const group of groups) {
        if (selected.has(group.index) || used + group.size > 256) continue;
        if (!canFill(256 - used - group.size, selected, group.index)) continue;
        const row = distances[group.index]; let gain = 0;
        for (let i = 0; i < count; i++) if (row[i] < best[i]) gain += (best[i] - row[i]) * data.weights[i];
        const score = gain / group.size;
        if (score > winnerScore + 1e-15) {winner = group.index; winnerScore = score;}
      }
      if (winner < 0) throw new Error('Could not complete a 256-glyph orbit palette.');
      selected.add(winner); used += groups[winner].size;
      const row = distances[winner];
      for (let i = 0; i < count; i++) if (row[i] < best[i]) best[i] = row[i];
    }
    return [...selected].sort((a, b) => a - b);
  }

  const seedObjective = objective(seedGroups);
  const greedy = greedySeed(), greedyObjective = objective(greedy);
  let selected = greedyObjective.error < seedObjective.error - 1e-12 ? greedy : seedGroups.slice();
  const initialChoice = selected === greedy ? 'fresh-greedy' : 'current-font';
  const swaps = [];
  let current = objective(selected).error;
  let stopReason = 'swap-limit', passesConsidered = 0;
  progress({stage: 'seeds', currentFontError: seedObjective.error, greedyError: greedyObjective.error, chosen: initialChoice});

  for (let step = 0; step < maxSwaps; step++) {
    if ((performance.now() - started) / 1000 >= maxSeconds) {stopReason = 'time-limit'; break;}
    passesConsidered++;
    selected.sort((a, b) => a - b);
    const selectedSet = new Set(selected), best = new Uint8Array(count).fill(65), second = new Uint8Array(count).fill(65), owner = new Uint16Array(count);
    for (let position = 0; position < selected.length; position++) {
      const row = distances[selected[position]];
      for (let i = 0; i < count; i++) {
        const error = row[i];
        if (error < best[i]) {second[i] = best[i]; best[i] = error; owner[i] = position;}
        else if (error < second[i]) second[i] = error;
      }
    }
    let winningError = current, remove = -1, add = -1;
    // Add a candidate orbit, then account only for samples whose best original
    // orbit would be removed. This evaluates every equal-size swap exactly.
    for (const group of groups) {
      if (selectedSet.has(group.index)) continue;
      const row = distances[group.index], penalties = new Float64Array(selected.length);
      let gain = 0;
      for (let i = 0; i < count; i++) {
        const withAdded = Math.min(best[i], row[i]);
        gain += (best[i] - withAdded) * data.weights[i];
        penalties[owner[i]] += (Math.min(second[i], row[i]) - withAdded) * data.weights[i];
      }
      for (let position = 0; position < selected.length; position++) {
        if (groups[selected[position]].size !== group.size) continue;
        const error = current - gain + penalties[position];
        if (error < winningError - 1e-12) {winningError = error; remove = position; add = group.index;}
      }
    }
    if (remove < 0) {stopReason = 'equal-size-orbit-plateau'; break;}
    const removed = selected[remove]; selected[remove] = add;
    const exact = objective(selected).error;
    if (exact > current - 1e-12 || Math.abs(exact - winningError) > 1e-9) throw new Error('Swap did not improve its exact weighted objective.');
    swaps.push({step, removedOrbit: groups[removed].id, addedOrbit: groups[add].id, glyphs: groups[add].size, before: current, after: exact});
    current = exact;
    progress({stage: 'swap', step, error: current});
  }

  const selectedGlyphs = selected.sort((a, b) => a - b).flatMap(index => groups[index].glyphs);
  const selectedKeys = new Set(selectedGlyphs.map(glyph => rowKey(glyph.rows)));
  if (selectedGlyphs.length !== 256 || selectedKeys.size !== 256) throw new Error('Expected 256 unique selected mathematical glyphs.');
  const empty = selectedGlyphs.find(glyph => glyph.rows.every(row => row === 0));
  const full = selectedGlyphs.find(glyph => glyph.rows.every(row => row === 255));
  if (!empty || !full) throw new Error('Data-selected font omitted empty or full; no mandatory glyph was silently forced.');
  const other = selectedGlyphs.filter(glyph => glyph !== empty && glyph !== full);
  const glyphs = []; let next = 0;
  for (let index = 0; index < 256; index++) {
    const source = index === 0 ? empty : index === 15 ? full : other[next++];
    glyphs.push({...source, rows: source.rows.slice(), index, filled: filled(source.rows), fixed: false});
  }
  for (const glyph of glyphs) {
    if (glyph.index !== 0 && glyph.index !== 15 && Math.min(glyph.filled, 64 - glyph.filled) <= 2) throw new Error('Selected a forbidden tiny fragment.');
    for (const value of orbit(glyph.rows)) if (!selectedKeys.has(rowKey(value.rows))) throw new Error('Selected font lost D4/inversion symmetry.');
  }
  const bytes = Buffer.from(glyphs.flatMap(glyph => glyph.rows));
  // Independent pixel-by-pixel oracle, including inadmissible-glyph rejection.
  // Its row loop does not reuse packed-word distances or group minima.
  const oracleIndices = [], oracleMasks = new Set();
  for (let i = 0; i < count && oracleIndices.length < Math.min(10, count); i++) {
    const id = data.allowedLo[i] + ':' + data.allowedHi[i];
    if (oracleMasks.has(id)) continue;
    oracleMasks.add(id); oracleIndices.push(i);
  }
  for (let i = 0; oracleIndices.length < Math.min(10, count); i++) if (!oracleIndices.includes(i)) oracleIndices.push(i);
  const finalBest = objective(selected).best;
  function oracleError(pattern, values) {
    let best = 65;
    const allowed = pattern.allowedRows || Array(8).fill(255);
    for (const glyph of values) {
      let error = 0, admissible = true;
      for (let y = 0; y < 8 && admissible; y++) for (let x = 0; x < 8; x++) {
        const value = (glyph.rows[y] >>> (7 - x)) & 1;
        if (value && !((allowed[y] >>> (7 - x)) & 1)) {admissible = false; break;}
        error += Number(value !== ((pattern.rows[y] >>> (7 - x)) & 1));
      }
      if (admissible && error < best) best = error;
    }
    return best;
  }
  let oracleGroupChecks = 0, oracleInfeasibleGroups = 0;
  const oracleChecks = oracleIndices.map(index => {
    const seedError = oracleError(data.patterns[index], seed.glyphs.slice(0, seed.usedCount));
    const fittedError = oracleError(data.patterns[index], glyphs);
    if (seedError !== seedObjective.best[index] || fittedError !== finalBest[index]) throw new Error('Independent admissible pixel oracle disagrees with the distance matrix.');
    for (const group of groups) {
      const error = oracleError(data.patterns[index], group.glyphs);
      if (error !== distances[group.index][index]) throw new Error('Independent group admissibility oracle disagrees with the distance matrix.');
      oracleGroupChecks++; oracleInfeasibleGroups += Number(error === 65);
    }
    return {patternIndex: index, rows: data.patterns[index].rows, allowedRows: data.patterns[index].allowedRows || Array(8).fill(255), seedError, fittedError, exact: true};
  });
  const removed = seed.glyphs.slice(0, seed.usedCount).filter(glyph => !selectedKeys.has(rowKey(glyph.rows)));
  const added = glyphs.filter(glyph => !seedKeys.has(rowKey(glyph.rows)));
  const report = {
    pass: true, scope: 'All glyphs unlocked; bounded mathematical-orbit optimization using training targets only.',
    objective: data.hasConstraints ? 'sum(pattern.weight * minimum admissible64bitHammingError); exact corrected pixel matcher including circle admissibility.' : 'sum(pattern.weight * nearest64bitHammingError); lower bound before actual renderer selection and circle restrictions.',
    constraintMode: data.hasConstraints ? 'exact-circle-admissible' : 'unconstrained', infeasibleGroupCost: 65,
    normalization: training.normalization, trainingCases: training.caseCount, trainingFrames: training.frames,
    trainingPatternClasses: count, trainingTileInstances: data.instances, weightSum: data.weightSum,
    candidateGlyphs: pool.glyphs.length, candidateOrbits: groups.length,
    candidatePool: {maxHalfPlaneNormalComponent: 15, translatedHalfPlanes: true, junctionThresholds: [-6,-4,-2,0,2,4,6]},
    selectedGlyphs: glyphs.length, selectedOrbits: selected.length, lockedGlyphs: 0,
    emptyAndFullSelectedByData: true, emptyIndex: 0, fullIndex: 15,
    initialChoice, seedError: seedObjective.error, greedyError: greedyObjective.error, optimizedError: current,
    seedSha256: crypto.createHash('sha256').update(Buffer.from(seed.glyphs.slice(0, seed.usedCount).flatMap(glyph => glyph.rows))).digest('hex'),
    improvement: seedObjective.error - current, relativeImprovement: (seedObjective.error - current) / seedObjective.error,
    sameSizeOrbitSwapLimit: maxSwaps, actualSwaps: swaps.length,
    stopReason, passesConsidered, noImprovingEqualSizeSwapVerified: stopReason === 'equal-size-orbit-plateau',
    searchLimits: 'Compare current font and fresh gain-per-slot greedy palette, then at most maxSwaps improving equal-size orbit replacements. This is not a global optimum.',
    orbitSizes: Object.fromEntries([2, 4, 8, 16].map(size => [size, selected.filter(index => groups[index].size === size).length])),
    completeRotationsMirrorsInverses: true, maximumExcludedFragmentPixels: 2, allShapesMathematical: true,
    retainedShapes: 256 - removed.length, removedShapes: removed.length, newShapes: added.length,
    removed: removed.map(glyph => ({rows: glyph.rows, kind: glyph.kind, family: glyph.family, label: glyph.label})),
    added: added.map(glyph => ({rows: glyph.rows, kind: glyph.kind, family: glyph.family, label: glyph.label})),
    kinds: Object.fromEntries(['basic', 'diagonal', 'corner', 'crossing'].map(kind => [kind, glyphs.filter(glyph => glyph.kind === kind).length])),
    swaps, sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
    trainingSha256: crypto.createHash('sha256').update(JSON.stringify(training)).digest('hex'),
    elapsedSeconds: (performance.now() - started) / 1000, distanceMatrixBytes: groups.length * count,
    validationUsedForSelection: false,
    independentPixelOracle: {pass: true, targetPatterns: oracleChecks.length, groupChecks: oracleGroupChecks,
      inadmissibleGroupCasesAt65: oracleInfeasibleGroups, checks: oracleChecks}
  };
  return {palette: {glyphs, usedCount: 256, fontBytes: 2048, lockedGlyphs: 0,
    maximumExcludedFragmentPixels: 2, allShapesMathematical: true, optimization: {trainingCases: training.caseCount, trainingFrames: training.frames, sha256: report.sha256}}, report};
}

module.exports = {optimizeGeneral, mathematicalPool};

if (require.main === module) {
  const fs = require('node:fs');
  if (!process.argv[2] || !process.argv[3]) throw new Error('Usage: node optimize-general.cjs TRAIN_PATTERNS.json OUTPUT.json [--seed PALETTE.json]');
  const training = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const seedArgument = process.argv.indexOf('--seed');
  let seed;
  if (seedArgument >= 0) {
    if (!process.argv[seedArgument + 1]) throw new Error('Missing --seed JSON path.');
    const value = JSON.parse(fs.readFileSync(process.argv[seedArgument + 1], 'utf8'));
    seed = value.palette || value;
  }
  const maxSwapArgument = process.argv.indexOf('--max-swaps');
  const maxSwaps = maxSwapArgument < 0 ? undefined : Number(process.argv[maxSwapArgument + 1]);
  if (maxSwaps !== undefined && (!Number.isInteger(maxSwaps) || maxSwaps < 0 || maxSwaps > 64)) throw new Error('Invalid --max-swaps limit.');
  const result = optimizeGeneral(training, {seed, maxSwaps, progress: value => process.stderr.write(JSON.stringify(value) + '\n')});
  fs.writeFileSync(process.argv[3], JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify({...result.report, added: undefined, removed: undefined, swaps: undefined}, null, 2));
}
