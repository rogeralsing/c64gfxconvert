'use strict';

// Host-only opportunity counts. This does not implement delta rendering or
// predict native CPU savings from the number of changed output bytes.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { createModel } = require('./native-model.cjs');

function summary(values) {
  return { samples: values.length, mean: values.reduce((sum, value) => sum + value, 0) / values.length,
    min: Math.min(...values), max: Math.max(...values), total: values.reduce((sum, value) => sum + value, 0) };
}

function differences(a, b) {
  let changed = 0;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) changed++;
  return changed;
}

function samePoints(a, b, translated = false) {
  if (a.length !== b.length) return false;
  const dx = translated ? a[0][0] - b[0][0] : 0;
  const dy = translated ? a[0][1] - b[0][1] : 0;
  return a.every((point, i) => point[0] - b[i][0] === dx && point[1] - b[i][1] === dy);
}

function compare(current, previous) {
  const a = current.geometry, b = previous.geometry;
  let unchangedProjectedVerticesXY = 0, unchangedFacesXY = 0;
  let currentWhiteFrontFaces = 0, unchangedWhiteFrontFacesXY = 0, unchangedWhiteFrontFacesLocalXY = 0;
  for (let vertex = 0; vertex < a.mesh.vertexCount; vertex++) {
    if (a.projectedX[vertex] === b.projectedX[vertex] && a.projectedY[vertex] === b.projectedY[vertex]) unchangedProjectedVerticesXY++;
  }
  for (let face = 0; face < a.faces.length; face++) {
    const now = a.faces[face], before = b.faces[face], same = samePoints(now.points, before.points);
    if (same) unchangedFacesXY++;
    if (!now.color || !now.visible) continue;
    currentWhiteFrontFaces++;
    if (!before.visible || !before.color) continue;
    if (same) unchangedWhiteFrontFacesXY++;
    if (samePoints(now.points, before.points, true)) unchangedWhiteFrontFacesLocalXY++;
  }
  return { changedCoverageCells: differences(current.coverage, previous.coverage),
    changedGlyphCells: differences(current.screen, previous.screen),
    unchangedProjectedVerticesXY, unchangedFacesXY, currentWhiteFrontFaces,
    unchangedWhiteFrontFacesXY, unchangedWhiteFrontFacesLocalXY };
}

function circleCells() {
  let active = 0;
  for (let row = 0; row < 25; row++) for (let column = 0; column < 40; column++) {
    let touches = false;
    for (let y = 0; y < 8 && !touches; y++) for (let x = 0; x < 8; x++) {
      if ((column * 8 + x - 160) ** 2 + (row * 8 + y - 100) ** 2 <= 94 ** 2) { touches = true; break; }
    }
    if (touches) active++;
  }
  return active;
}

function summarizeLag(rows, key, activeCells, vertices) {
  const metrics = Object.keys(rows[0][key]);
  const result = Object.fromEntries(metrics.map(metric => [metric, summary(rows.map(row => row[key][metric]))]));
  result.changedGlyphFractionOf1000 = result.changedGlyphCells.mean / 1000;
  result.changedGlyphFractionOfCircleCells = result.changedGlyphCells.mean / activeCells;
  result.unchangedGlyphFractionOfCircleCells = 1 - result.changedGlyphFractionOfCircleCells;
  result.unchangedProjectedVertexFraction = result.unchangedProjectedVerticesXY.mean / vertices;
  result.exactWhiteFrontFaceReuseFraction = result.unchangedWhiteFrontFacesXY.total / result.currentWhiteFrontFaces.total;
  result.translationInvariantWhiteFrontFaceReuseFraction = result.unchangedWhiteFrontFacesLocalXY.total / result.currentWhiteFrontFaces.total;
  return result;
}

function study({ frames = 64 } = {}) {
  if (!Number.isInteger(frames) || frames < 3 || frames > 256) throw new Error('Frame count must be an integer from 3 to 256.');
  const model = createModel(), activeCells = circleCells();
  const result = {
    scope: 'Host output-change counts only; no native delta prototype, timing or speedup claim.',
    trajectory: { frames, warmupFrames: 2, comparedFramesPerLag: frames - 2,
      start: { yaw: 0, pitch: 24, roll: 0 }, step: { yaw: 2, pitch: 1, roll: 1 }, angleModulo: 256 },
    comparison: {
      lag1: 'Previous presentation t-1; relevant to a persistent single coverage buffer.',
      lag2: 'Previous contents of the destination screen in the existing alternating double buffers: t-2.',
      warmup: 'Both lags use frames t>=2, excluding both uninitialized destination buffers.',
      glyphs: 'Actual post-silhouette-remap fixed-font screen codes.',
      coverage: 'Pre-font/pre-circle coverage bytes; their footprint can extend beyond the final circle.',
      vertices: 'Exact projected X/Y equality, not immutable input world coordinates.',
      faceReuse: 'Current white front faces whose previous visibility and absolute projected polygon are identical.',
      localFaceReuse: 'Additional upper-bound candidates with the same projected polygon after translation; character phase and silhouette remapping can still differ.',
      spans: 'Not measured: the renderer does not expose retained per-face span endpoints. No renderer instrumentation was added.'
    },
    circle: { cx: 160, cy: 100, radius: 94, dotCenterOffset: 0, characterCellsTouched: activeCells },
    font: { glyphs: model.font.glyphs.length, signature: model.font.signature, lookupBytes: model.assets.glyphLut.length },
    models: {}
  };
  for (const name of ['checker', 'football']) {
    const rendered = [], rows = [], coverageUnion = new Set(), glyphUnion = new Set();
    for (let index = 0; index < frames; index++) {
      const yaw = (2 * index) & 255, pitch = (24 + index) & 255, roll = index & 255;
      const frame = model.frame(name, yaw, pitch, roll);
      rendered.push(frame);
      for (let cell = 0; cell < 1000; cell++) {
        if (frame.coverage[cell]) coverageUnion.add(cell);
        if (frame.screen[cell]) glyphUnion.add(cell);
      }
      if (index < 2) continue;
      rows.push({ frame: index, yaw, pitch, roll,
        nonzeroCoverageCells: frame.coverage.reduce((count, value) => count + Number(value !== 0), 0),
        nonblankGlyphCells: frame.screen.reduce((count, value) => count + Number(value !== 0), 0),
        lag1: compare(frame, rendered[index - 1]), lag2: compare(frame, rendered[index - 2]) });
    }
    const mesh = rendered[0].geometry.mesh;
    result.models[name] = { vertices: mesh.vertexCount, faces: mesh.faceCount,
      unionNonzeroCoverageCells: coverageUnion.size, unionNonblankGlyphCells: glyphUnion.size,
      nonzeroCoverageCells: summary(rows.map(row => row.nonzeroCoverageCells)),
      nonblankGlyphCells: summary(rows.map(row => row.nonblankGlyphCells)),
      lag1: summarizeLag(rows, 'lag1', activeCells, mesh.vertexCount),
      lag2: summarizeLag(rows, 'lag2', activeCells, mesh.vertexCount), rows };
  }
  result.inputs = Object.fromEntries(['native-model.cjs', 'geometry.cjs', 'raster.cjs', 'meshes.cjs',
    'assets/font.bin', 'assets/glyph-lut.bin', 'assets/glyph-compact.bin', 'assets/limb-remap.bin', 'assets/clip-records.bin']
    .map(file => [file, crypto.createHash('sha256').update(fs.readFileSync(path.join(__dirname, file))).digest('hex')]));
  return result;
}

module.exports = { study };

if (require.main === module) {
  try {
    const frames = process.argv.length > 2 ? Number(process.argv[2]) : 64;
    const result = study({ frames });
    const output = path.join(__dirname, 'build', 'delta-feasibility.json');
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify({ artifact: output, scope: result.scope, trajectory: result.trajectory, circle: result.circle,
      models: Object.fromEntries(Object.entries(result.models).map(([name, m]) => [name,
        { unionNonzeroCoverageCells: m.unionNonzeroCoverageCells, unionNonblankGlyphCells: m.unionNonblankGlyphCells,
          nonblankGlyphCellsMean: m.nonblankGlyphCells.mean,
          lag1: { changedCoverageMean: m.lag1.changedCoverageCells.mean, changedGlyphMean: m.lag1.changedGlyphCells.mean,
            exactWhiteFrontFaceReuseFraction: m.lag1.exactWhiteFrontFaceReuseFraction,
            unchangedVertexFraction: m.lag1.unchangedProjectedVertexFraction },
          lag2: { changedCoverageMean: m.lag2.changedCoverageCells.mean, changedGlyphMean: m.lag2.changedGlyphCells.mean,
            exactWhiteFrontFaceReuseFraction: m.lag2.exactWhiteFrontFaceReuseFraction,
            unchangedVertexFraction: m.lag2.unchangedProjectedVertexFraction,
            changedGlyphFractionOfCircleCells: m.lag2.changedGlyphFractionOfCircleCells } }])) }, null, 2));
  } catch (error) { console.error('delta-study: ' + error.message); process.exitCode = 1; }
}
