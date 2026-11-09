'use strict';

// Collect only training reference pixels and their geometric circle masks.
// The original renderer's reference stage is reused verbatim; an early return
// skips all glyph matching and therefore cannot bake font decisions into data.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {buildBrowserSource} = require('./browser-font.cjs');

const DIRECTORY = path.join(__dirname, 'legacy');
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const hex = Array.from({length: 256}, (_, value) => value.toString(16).padStart(2, '0'));
const keyOf = rows => rows.map(value => hex[value]).join('');

function tileRows(pixels, cell) {
  const x0 = (cell % 40) * 8, y0 = Math.floor(cell / 40) * 8, rows = [];
  for (let y = 0; y < 8; y++) {
    let row = 0;
    for (let x = 0; x < 8; x++) if (pixels[(y0 + y) * 320 + x0 + x]) row |= 128 >>> x;
    rows.push(row);
  }
  return rows;
}

function referenceRuntime(rendererSource) {
  const marker = '      let mismatches = 0, surfaceErrors = 0, usedCount = 0, exactCells = 0;';
  assert.equal(rendererSource.split(marker).length, 2, 'Reference-stage boundary changed.');
  const fastSource = rendererSource.replace(marker, '      return this.source;\n' + marker);
  const runtime = vm.createContext({}); runtime.window = runtime;
  vm.runInContext(fastSource, runtime, {filename: 'sphere-renderer-reference-only.js'});
  return {renderer: new runtime.SphereMath.SphereRenderer(), modifiedSourceSha256: sha(fastSource)};
}

function fullRuntime(rendererSource, palette) {
  const runtime = vm.createContext({}); runtime.window = runtime;
  for (const [name, source] of [['browser-font.js', buildBrowserSource(palette)],
    ['direct-core.js', fs.readFileSync(path.join(DIRECTORY, 'direct-core.js'), 'utf8')],
    ['sphere-renderer.js', rendererSource]]) vm.runInContext(source, runtime, {filename: name});
  return {renderer: new runtime.SphereMath.SphereRenderer(), font: runtime.GlyphMath.generateFont(256)};
}

function collectConstrained(training, palette, options = {}) {
  const started = performance.now(), progress = options.progress || (() => {});
  const cases = training.cases;
  assert(Array.isArray(cases) && cases.length === 36, 'Expected the 36 training cases.');
  assert(cases.every(item => item.split === 'train'), 'Only training cases may be collected.');
  assert.equal(cases.reduce((sum, item) => sum + item.frames, 0), 1152);
  const sourcePath = path.join(DIRECTORY, 'sphere-renderer.js');
  const source = fs.readFileSync(sourcePath, 'utf8');
  const fast = referenceRuntime(source), full = fullRuntime(source, palette), parity = [];
  for (const index of [0, 13, 35]) {
    const item = cases[index], angle = (item.phaseDegrees + 3 * 360 / item.frames) * Math.PI / 180;
    const state = {angle, tilt: item.tilt, radius: item.radius, checks: item.checks, solid: false};
    full.renderer.render(state, full.font);
    const pixels = fast.renderer.render(state, null);
    assert.deepEqual(Buffer.from(pixels), Buffer.from(full.renderer.source));
    assert.deepEqual(Buffer.from(fast.renderer.inside), Buffer.from(full.renderer.inside));
    assert.equal(fast.renderer.surfacePixels, full.renderer.surfacePixels);
    parity.push({caseId: item.id, radius: item.radius, tilt: item.tilt, checks: item.checks,
      angleRadians: angle, pixelsCompared: pixels.length, exact: true, sourcePixelsSha256: sha(Buffer.from(pixels)), insideSha256: sha(Buffer.from(fast.renderer.inside))});
  }
  progress({stage: 'reference-parity', cases: parity.length, pixelsCompared: parity.length * 64000, exact: true});

  const targets = new Map(), allowedCache = new Map(), perCase = [];
  let frames = 0;
  for (const item of cases) {
    const counts = new Map();
    let surfacePixels = 0;
    for (let frame = 0; frame < item.frames; frame++) {
      const angle = (item.phaseDegrees + frame * 360 / item.frames) * Math.PI / 180;
      const pixels = fast.renderer.render({angle, tilt: item.tilt, radius: item.radius, checks: item.checks, solid: false}, null);
      surfacePixels = fast.renderer.surfacePixels;
      assert.equal(surfacePixels, item.surfacePixels);
      if (!allowedCache.has(item.radius)) allowedCache.set(item.radius, Array.from({length: 1000}, (_, cell) => {
        const rows = tileRows(fast.renderer.inside, cell);
        return {rows, key: keyOf(rows)};
      }));
      const allowed = allowedCache.get(item.radius);
      for (let cell = 0; cell < 1000; cell++) {
        const rows = tileRows(pixels, cell), targetKey = keyOf(rows), mask = allowed[cell];
        for (let y = 0; y < 8; y++) assert.equal(rows[y] & ~mask.rows[y], 0, 'Reference pixels escaped geometric circle.');
        const key = targetKey + ':' + mask.key;
        const previous = counts.get(key);
        if (previous) previous.count++;
        else counts.set(key, {key, targetKey, rows, allowedRows: mask.rows, count: 1});
      }
      frames++;
    }
    const occurrences = [...counts.values()].reduce((sum, value) => sum + value.count, 0);
    assert.equal(occurrences, item.frames * 1000);
    for (const [key, value] of counts) {
      let target = targets.get(key);
      if (!target) {target = {...value, count: 0, weight: 0}; targets.set(key, target);}
      target.count += value.count;
      target.weight += value.count / (item.frames * surfacePixels * cases.length);
    }
    perCase.push({...item, surfacePixels, tiles: occurrences, targetAndMaskClasses: counts.size});
    progress({stage: 'case', completed: perCase.length, total: cases.length, caseId: item.id, elapsedSeconds: (performance.now() - started) / 1000});
  }
  const targetPatterns = [...targets.values()].sort((a, b) => b.weight - a.weight || a.key.localeCompare(b.key));
  const instances = targetPatterns.reduce((sum, value) => sum + value.count, 0);
  const weightSum = targetPatterns.reduce((sum, value) => sum + value.weight, 0);
  assert.equal(frames, 1152); assert.equal(instances, 1152000);
  const expectedWeight = cases.reduce((sum, item) => sum + 1000 / (item.surfacePixels * cases.length), 0);
  assert(Math.abs(weightSum - expectedWeight) < 1e-10);
  assert.equal(sha(fs.readFileSync(sourcePath)), sha(source), 'Original reference source changed while collecting.');
  return {scope: 'TRAIN ONLY: all reference bitmap tiles paired with exact circle-admissibility masks',
    caseCount: cases.length, frames, normalization: training.normalization,
    weightMeaning: 'Sum count/(case frames * actual visible sphere pixels * training case count); exact mean per-case normalized error for best admissible glyph matching.',
    constraintMeaning: 'A glyph is admissible only if every filled pixel is also filled in allowedRows. A group with no admissible glyph has cost65.',
    cases: perCase, targetPatterns,
    assertions: {referenceParityCases: parity.length, referenceParityPixels: parity.length * 64000,
      referencePixelsAndInsideMasksEqualOriginal: true, countsConserved: true, tileInstances: instances,
      caseWeightsEqual: true, targetNeverOutsideAllowed: true, onlyTrainingCases: true, weightSum},
    referenceParity: parity, source: {path: sourcePath, sha256: sha(source), fastReferenceSha256: fast.modifiedSourceSha256,
      modification: 'Insert return this.source immediately before the original glyph-matching stage; all reference geometry and pixel evaluation remain verbatim.'},
    allowedMaskClasses: new Set(targetPatterns.map(value => keyOf(value.allowedRows))).size,
    elapsedSeconds: (performance.now() - started) / 1000};
}

module.exports = {collectConstrained};

if (require.main === module) {
  const trainingPath = process.argv[2] || path.join(__dirname, 'build/general-train-patterns.json');
  const seedPath = process.argv[3] || path.join(__dirname, 'build/general-candidate-r2.json');
  const output = process.argv[4] || path.join(__dirname, 'build/general-constrained-train-patterns.json');
  const training = JSON.parse(fs.readFileSync(trainingPath, 'utf8'));
  const seed = JSON.parse(fs.readFileSync(seedPath, 'utf8'));
  const result = collectConstrained(training, seed.palette || seed, {progress: value => process.stderr.write(JSON.stringify(value) + '\n')});
  fs.writeFileSync(output, JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify({output, caseCount: result.caseCount, frames: result.frames, patterns: result.targetPatterns.length,
    allowedMaskClasses: result.allowedMaskClasses, assertions: result.assertions, elapsedSeconds: result.elapsedSeconds}, null, 2));
}
