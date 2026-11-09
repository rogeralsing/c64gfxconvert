'use strict';

// Behavioral proof for the polygon/character boundary. Quality measurements use
// an independent floating polygon reference rather than the native span code.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const Meshes = require('./meshes.cjs');
const Geometry = require('./geometry.cjs');
const Raster = require('./raster.cjs');
const Reference = require('./reference.cjs');
const Native = require('./native-model.cjs');

function sha256(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function topology(mesh, expected) {
  assert.equal(mesh.vertices.length, expected.vertices, mesh.name + ' must retain every vertex');
  assert.equal(mesh.faces.length, expected.faces, mesh.name + ' must retain every face');
  const edges = new Map(), used = new Set(), kinds = {};
  for (const face of mesh.faces) {
    assert.equal(new Set(face.indices).size, face.indices.length, 'A face cannot repeat a vertex');
    kinds[face.indices.length] = (kinds[face.indices.length] || 0) + 1;
    for (let i = 0; i < face.indices.length; i++) {
      const a = face.indices[i], b = face.indices[(i + 1) % face.indices.length];
      assert(a >= 0 && a < mesh.vertices.length && b >= 0 && b < mesh.vertices.length);
      used.add(a); used.add(b);
      const key = Math.min(a, b) + ':' + Math.max(a, b);
      if (!edges.has(key)) edges.set(key, []);
      edges.get(key).push([a, b]);
    }
  }
  assert.equal(used.size, mesh.vertices.length, 'All retained vertices must belong to the surface');
  assert.equal(mesh.vertices.length - edges.size + mesh.faces.length, 2, 'The complete ball must have spherical topology');
  for (const [key, owners] of edges) {
    assert.equal(owners.length, 2, 'Surface edge ' + key + ' must have two owners');
    assert.equal(owners[0][0], owners[1][1], 'Shared edge winding must oppose');
    assert.equal(owners[0][1], owners[1][0], 'Shared edge winding must oppose');
  }
  assert.deepEqual(kinds, expected.kinds);
  return { vertices: used.size, faces: mesh.faces.length, edges: edges.size, kinds, closed: true };
}

// Integer even-odd point inclusion, with the independently specified half-open
// edge rule. The strict cross-product comparison includes left/top crossings
// and excludes right/bottom crossings without division or floating tolerance.
function containsHalfOpen(points, x, y) {
  let inside = false;
  for (let i = 0; i < points.length; i++) {
    let a = points[i], b = points[(i + 1) % points.length];
    if (a[1] > b[1]) [a, b] = [b, a];
    const dy = b[1] - a[1];
    if (!dy || y < a[1] || y >= b[1]) continue;
    if (x * dy < a[0] * dy + (y - a[1]) * (b[0] - a[0])) inside = !inside;
  }
  return inside;
}

function pointOracle(polygons, bits) {
  const coverage = bits === 9 ? new Uint16Array(1000) : new Uint8Array(1000);
  const points = bits === 9
    ? [[1, 1], [4, 1], [6, 1], [1, 4], [4, 4], [6, 4], [1, 6], [4, 6], [6, 6]]
    : [[1, 1], [4, 1], [6, 1], [1, 4], [6, 4], [1, 6], [4, 6], [6, 6]];
  for (let row = 0; row < 25; row++) for (let column = 0; column < 40; column++) {
    for (let bit = 0; bit < points.length; bit++) {
      const x = column * 8 + points[bit][0], y = row * 8 + points[bit][1];
      if (polygons.some(polygon => containsHalfOpen(polygon, x, y))) coverage[row * 40 + column] |= 1 << bit;
    }
  }
  return coverage;
}

function rasterPolygons(polygons, tables) {
  const xs = [], ys = [], faces = [];
  for (const points of polygons) {
    const indices = [];
    for (const [x, y] of points) { indices.push(xs.length); xs.push(x); ys.push(y); }
    faces.push(indices);
  }
  return Raster.rasterize(Uint8Array.from(xs), Uint8Array.from(ys), faces, { tables });
}

function syntheticCoverage(font) {
  const convex = [
    [[81, 65], [113, 65], [113, 97], [81, 97]],
    [[80, 63], [123, 97], [88, 112]],
    [[145, 70], [170, 80], [179, 104], [152, 124], [132, 98]],
    [[95, 83], [116, 72], [141, 84], [145, 108], [120, 124], [99, 111]]
  ];
  const leftHalf = [[80, 80], [84, 80], [84, 88], [80, 88]];
  const rightHalf = [[84, 80], [88, 80], [88, 88], [84, 88]];
  const results = [];
  for (const bits of [8, 9]) {
    const tables = Raster.buildTables(font, { bits });
    for (const points of convex) {
      const expected = pointOracle([points], bits);
      const normal = rasterPolygons([points], tables);
      const reversed = rasterPolygons([[...points].reverse()], tables);
      assert.deepEqual(normal.coverage, expected, bits + '-probe convex coverage must match independent point inclusion');
      assert.deepEqual(reversed.coverage, expected, 'Winding must not change white coverage');
    }
    const combined = rasterPolygons([leftHalf, rightHalf], tables);
    const reverseOrder = rasterPolygons([rightHalf, leftHalf], tables);
    assert.deepEqual(combined.coverage, pointOracle([leftHalf, rightHalf], bits), 'Faces sharing a character cell must compose');
    assert.deepEqual(combined.screen, reverseOrder.screen, 'White face order must not erase earlier samples');
    const cell = 10 * 40 + 10;
    assert.equal(combined.coverage[cell], (1 << bits) - 1, 'Two adjacent half faces must produce complete cell coverage');
    assert([...font.glyphs[combined.screen[cell]].rows].every(row => row === 255), 'Complete coverage must display a solid glyph');
    const empty = rasterPolygons([], tables);
    assert(empty.coverage.every(value => value === 0));
    assert([...new Set(empty.screen)].every(glyph => [...font.glyphs[glyph].rows].every(row => row === 0)), 'Empty geometry must display only blank glyphs');
    results.push({ bits, convexCases: convex.length, winding: true, sharedCellComposition: true, emptyAndFull: true });
  }
  return results;
}

function poses() {
  const samples = [
    [0, 0, 0], [64, 0, 0], [128, 0, 0], [192, 0, 0],
    [0, 64, 0], [0, 128, 0], [0, 0, 64], [0, 0, 128]
  ];
  for (let i = 0; i < 24; i++) samples.push([(11 + i * 37) & 255, (24 + i * 19) & 255, (7 + i * 53) & 255]);
  return samples.map(([yaw, pitch, roll]) => ({ yaw, pitch, roll }));
}

function measureQuality(model, name, samples) {
  const rows = [], used = new Set();
  let totalErrors = 0, totalReferenceArea = 0, circleSpill = 0;
  for (const { yaw, pitch, roll } of samples) {
    const frame = model.frame(name, yaw, pitch, roll);
    const projected = Geometry.projectFloat(name, yaw, pitch, roll);
    const reference = Reference.projectedReference(projected, { pixelOffset: 0 });
    const quality = Reference.compare(frame.screen, model.font, reference, { pixelOffset: 0 });
    assert.equal(frame.screen.length, 1000, 'A native frame must fill one character screen');
    assert.equal(quality.circleSpill, 0, name + ' must never light a font dot beyond radius 94 at ' + [yaw, pitch, roll]);
    for (const glyph of frame.screen) used.add(glyph);
    totalErrors += quality.errors;
    totalReferenceArea += reference.area;
    circleSpill += quality.circleSpill;
    rows.push({ yaw, pitch, roll, ...quality, referenceArea: reference.area,
      visibleWhiteFaces: frame.geometry.faces.filter(face => face.visible && face.color).length });
  }
  assert(used.size > 16 && [...used].some(glyph => glyph >= 16), 'The native renderer must actually use the finer mathematical font');
  return { poses: rows.length, weightedMeanError: totalErrors / totalReferenceArea,
    meanError: rows.reduce((sum, row) => sum + row.error, 0) / rows.length,
    maxError: Math.max(...rows.map(row => row.error)), minError: Math.min(...rows.map(row => row.error)),
    circleSpill, usedGlyphCount: used.size, usedFineGlyphCount: [...used].filter(glyph => glyph >= 16).length,
    usedGlyphs: [...used].sort((a, b) => a - b), rows };
}

function verify() {
  const model = Native.createModel();
  const fontBefore = Buffer.from(model.assets.font);
  const expectedFont = Buffer.concat(model.font.glyphs.map(glyph => Buffer.from(glyph.rows)));
  assert.deepEqual(fontBefore, expectedFont, 'Native assets must use the same fixed mathematical font');
  const result = {
    passed: true,
    scope: 'Host behavioral proof and measurements of actual native-model screen codes; emulator equivalence is verified separately.',
    exactOracle: 'Integer half-open even-odd inclusion for synthetic convex polygons only. Folded real Q3 silhouettes are measured against floating polygons, not asserted to match point coverage.',
    topology: {
      checker: topology(Meshes.checker, { vertices: 62, faces: 72, kinds: { 3: 24, 4: 48 } }),
      football: topology(Meshes.football, { vertices: 60, faces: 32, kinds: { 5: 12, 6: 20 } })
    },
    syntheticCoverage: syntheticCoverage(model.font),
    font: { glyphs: model.font.glyphs.length, bytes: fontBefore.length, signature: model.font.signature,
      sha256: sha256(fontBefore), nativeLookupBytes: model.assets.glyphLut.length,
      nativeLookupReachableGlyphs: new Set(model.assets.glyphLut).size, coverageBits: model.tables.bits },
    qualityReference: 'Independent projectedReference(projectFloat(model,yaw,pitch,roll)), integer dot centers, white polygon union.',
    qualityUnits: 'Error is differing lit/unlit dots divided by the visible reference polygon area. Circle spill is an absolute count of lit dots beyond radius 94.',
    quality: {}
  };
  const samples = poses();
  for (const name of ['checker', 'football']) result.quality[name] = measureQuality(model, name, samples);
  assert.deepEqual(model.assets.font, fontBefore, 'Rotating either model must leave the fixed font unchanged');
  result.font.unchangedAcrossFrames = true;
  result.inputs = Object.fromEntries(['meshes.cjs', 'geometry.cjs', 'raster.cjs', 'native-model.cjs', 'reference.cjs', 'assets/font.bin', 'assets/glyph-lut.bin']
    .map(file => [file, sha256(fs.readFileSync(path.join(__dirname, file)))]));
  return result;
}

module.exports = { verify, containsHalfOpen };

if (require.main === module) {
  const output = path.join(__dirname, 'build', 'host-verification.json');
  let result;
  try { result = verify(); }
  catch (error) { result = { passed: false, error: error.message, stack: error.stack }; process.exitCode = 1; }
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result.passed ? {
    passed: true, artifact: output, topology: result.topology, font: result.font,
    quality: Object.fromEntries(Object.entries(result.quality).map(([name, quality]) => [name,
      { poses: quality.poses, meanError: quality.meanError, maxError: quality.maxError,
        circleSpill: quality.circleSpill, usedGlyphCount: quality.usedGlyphCount }]))
  } : result, null, 2));
}
