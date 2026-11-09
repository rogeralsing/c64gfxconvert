'use strict';

// Scene-independent junction shapes. Coordinates are doubled about the tile
// centre: a*(2*x-7) + b*(2*y-7) >= threshold. This keeps every test integral.
const {generateBaseFont: generateFont} = require('./font.cjs');

function key(rows) { return Array.from(rows).join(','); }
function filledPixels(rows) {
  return Array.from(rows).reduce((sum, row) => sum + row.toString(2).replace(/0/g, '').length, 0);
}

function transformRows(rows, turn, mirror, inverted) {
  return Array.from({length: 8}, (_, y) => {
    let row = 0;
    for (let x = 0; x < 8; x++) {
      let sx = x, sy = y;
      if (mirror) sx = 7 - sx;
      for (let i = 0; i < turn; i++) [sx, sy] = [sy, 7 - sx];
      const value = ((rows[sy] >>> (7 - sx)) & 1) ^ Number(inverted);
      if (value) row |= 128 >>> x;
    }
    return row;
  });
}

function orbit(rows) {
  const result = new Map();
  for (let turn = 0; turn < 4; turn++) for (const mirror of [false, true]) for (const inverted of [false, true]) {
    const transformed = transformRows(rows, turn, mirror, inverted);
    const id = key(transformed);
    if (!result.has(id)) result.set(id, {rows: transformed, transform: {turn, mirror, inverted}});
  }
  return [...result.values()];
}

function planeMask({a, b, threshold}) {
  return Array.from({length: 8}, (_, y) => {
    let row = 0;
    for (let x = 0; x < 8; x++) if (a * (2 * x - 7) + b * (2 * y - 7) >= threshold) row |= 128 >>> x;
    return row;
  });
}

function pairMask(first, second, operation) {
  const a = planeMask(first), b = planeMask(second);
  return a.map((row, y) => operation === 'xor' ? row ^ b[y] : row & b[y]);
}

function candidates() {
  const palette = generateFont();
  const original = new Set(palette.glyphs.slice(0, palette.usedCount).map(glyph => key(glyph.rows)));
  const result = [], seen = new Set(original);

  function addOrbit(rows, details) {
    const variants = orbit(rows);
    const orbitId = variants.map(value => key(value.rows)).sort()[0];
    for (const value of variants) {
      const id = key(value.rows), filled = filledPixels(value.rows);
      if (seen.has(id) || Math.min(filled, 64 - filled) <= 2) continue;
      seen.add(id);
      result.push({rows: value.rows, filled, kind: details.kind, label: details.label, family: details.family,
        metadata: {...details.metadata, orbitId, transform: value.transform}});
    }
  }

  // Ten of these sixteen quadrant combinations are absent from the 230-shape
  // half-plane palette: eight corner polarities and two opposite-quadrant joins.
  for (let mask = 0; mask < 16; mask++) {
    const rows = Array.from({length: 8}, (_, y) => {
      let row = 0;
      for (let x = 0; x < 8; x++) if ((mask >>> (Number(x >= 4) + 2 * Number(y >= 4))) & 1) row |= 128 >>> x;
      return row;
    });
    addOrbit(rows, {kind: mask === 6 || mask === 9 ? 'crossing' : 'corner', label: 'Kvadranthörn eller korsning', family: 'quadrants', metadata: {operation: 'quadrants', quadrantMask: mask}});
  }

  // Cardinal and 45-degree boundaries at seven integer positions. AND supplies
  // solid corners; XOR supplies two alternating filled regions at a checker join.
  const normals = [[1, 0], [1, 1], [0, 1], [-1, 1]];
  const thresholds = [-6, -4, -2, 0, 2, 4, 6];
  for (let first = 0; first < normals.length; first++) for (let second = first + 1; second < normals.length; second++) {
    for (const t0 of thresholds) for (const t1 of thresholds) {
      const a = {a: normals[first][0], b: normals[first][1], threshold: t0};
      const b = {a: normals[second][0], b: normals[second][1], threshold: t1};
      for (const operation of ['and', 'xor']) {
        addOrbit(pairMask(a, b, operation), {kind: operation === 'xor' ? 'crossing' : 'corner',
          label: operation === 'xor' ? 'Förskjuten schackkorsning' : 'Förskjutet hörn', family: 'junction', metadata: {operation, lines: [a, b]}});
        if (operation === 'and') {
          const reversed = {...b, a: -b.a, b: -b.b, threshold: 1 - b.threshold};
          addOrbit(pairMask(a, reversed, operation), {kind: 'corner', label: 'Förskjutet hörn', family: 'junction', metadata: {operation, lines: [a, reversed]}});
        }
      }
    }
  }

  // Additional shallow joins without a dense arbitrary-angle search. Complete
  // symmetry orbits guarantee that every generated orientation has its inverse.
  const shallowPairs = [[[2, 1], [-1, 2]], [[1, 0], [1, 2]], [[0, 1], [2, 1]]];
  for (const [first, second] of shallowPairs) for (const t0 of thresholds) for (const t1 of thresholds) {
    const a = {a: first[0], b: first[1], threshold: t0};
    const b = {a: second[0], b: second[1], threshold: t1};
    for (const operation of ['and', 'xor']) addOrbit(pairMask(a, b, operation), {
      kind: operation === 'xor' ? 'crossing' : 'corner', label: operation === 'xor' ? 'Lutande schackkorsning' : 'Lutande hörn',
      family: 'shallow-junction', metadata: {operation, lines: [a, b]}});
  }
  return result;
}

function recommended() {
  const pool = candidates(), byKey = new Map(pool.map(value => [key(value.rows), value]));
  const quadrant = pool.filter(value => value.family === 'quadrants');
  // Two perpendicular sloping boundaries supply a rotated checker X. The
  // phase was selected from the finite orbit pool by the 384-pose bitmap-error
  // census. Its complete sixteen-shape D4/inverse orbit is not an axis join.
  const seed = pairMask({a: 2, b: 1, threshold: -2}, {a: -1, b: 2, threshold: -2}, 'xor');
  const shifted = orbit(seed).map(value => byKey.get(key(value.rows))).filter(Boolean);
  return [...quadrant, ...shifted];
}

module.exports = {candidates, recommended, orbit, planeMask, pairMask, transformRows};

if (require.main === module) {
  const assert = require('node:assert/strict');
  const pool = candidates(), shapes = new Set(pool.map(value => key(value.rows)));
  const palette = generateFont(), all = new Set([...palette.glyphs.slice(0, palette.usedCount).map(value => key(value.rows)), ...shapes]);
  for (const value of pool) {
    assert(Math.min(value.filled, 64 - value.filled) > 2);
    for (const counterpart of orbit(value.rows)) assert(all.has(key(counterpart.rows)), 'Incomplete symmetry orbit');
  }
  const choice = recommended(), choiceKeys = new Set(choice.map(value => key(value.rows)));
  assert.equal(choice.length, 26);
  assert.equal(choiceKeys.size, 26);
  assert.equal(choice.filter(value => value.family === 'quadrants').length, 10);
  for (const value of choice) for (const counterpart of orbit(value.rows)) assert(choiceKeys.has(key(counterpart.rows)), 'Incomplete recommended symmetry orbit');
  console.log(JSON.stringify({pass: true, candidates: pool.length,
    kinds: Object.fromEntries(['corner', 'crossing'].map(kind => [kind, pool.filter(value => value.kind === kind).length])),
    families: Object.fromEntries(['quadrants', 'junction', 'shallow-junction'].map(family => [family, pool.filter(value => value.family === family).length])),
    recommended: choice.length, recommendedQuadrants: 10, recommendedAngledCrossings: 16,
    basePalettePreserved: true, maximumExcludedFragmentPixels: 2, completeRotationsMirrorsInverses: true}, null, 2));
}
