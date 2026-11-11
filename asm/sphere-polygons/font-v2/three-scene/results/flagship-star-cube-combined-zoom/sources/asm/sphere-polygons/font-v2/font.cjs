'use strict';

// A deterministic mathematical palette. The first 30 shapes are predefined; all
// remaining usable shapes are integer half-planes, independent of any scene.
function generateBaseFont() {
  const glyphs = [], seen = new Set(), excluded = new Set();
  function add(rows, details) {
    rows = Array.from(rows);
    const key = rows.join(',');
    if (seen.has(key)) return false;
    const filled = rows.reduce((sum, row) => sum + row.toString(2).replace(/0/g, '').length, 0);
    if (details.kind === 'diagonal' && Math.min(filled, 64 - filled) <= 2) {
      excluded.add(key);
      return false;
    }
    seen.add(key);
    const index = glyphs.length;
    glyphs.push({index, rows, filled, kind: 'basic', family: 'axis', ...details});
    return true;
  }
  add(Array(8).fill(0), {label: 'Tomt', predefined: true});
  for (let n = 1; n <= 7; n++) add(Array(8).fill((1 << (8 - n)) - 1), {label: `${n} px tomt till vänster`, predefined: true, emptySide: 'left', emptyPixels: n});
  for (let n = 1; n <= 7; n++) add(Array(8).fill((255 << n) & 255), {label: `${n} px tomt till höger`, predefined: true, emptySide: 'right', emptyPixels: n});
  add(Array(8).fill(255), {label: 'Fyllt', predefined: true});
  for (let n = 1; n <= 7; n++) add(Array.from({length: 8}, (_, y) => y < n ? 0 : 255), {label: `${n} px tomt upptill`, predefined: true, emptySide: 'top', emptyPixels: n});
  for (let n = 1; n <= 7; n++) add(Array.from({length: 8}, (_, y) => y < 8 - n ? 255 : 0), {label: `${n} px tomt nedtill`, predefined: true, emptySide: 'bottom', emptyPixels: n});

  function halfPlane(a, b, threshold, family) {
    const rows = Array.from({length: 8}, (_, y) => {
      let row = 0;
      for (let x = 0; x < 8; x++) if (a * x + b * y >= threshold) row |= 128 >>> x;
      return row;
    });
    const direction = `${b > 0 ? 'nedåt' : 'uppåt'} ${a > 0 ? 'höger' : 'vänster'}`;
    return add(rows, {kind: 'diagonal', family, label: `Diagonal ${family === '45' ? '45°' : family} · ${direction}`, normal: [a, b], threshold, predefined: false});
  }
  function completeFamily(normals, family) {
    for (const [a0, b0] of normals) for (const sx of [1, -1]) for (const sy of [1, -1]) {
      const a = a0 * sx, b = b0 * sy;
      const low = Math.min(0, 7 * a) + Math.min(0, 7 * b);
      const high = Math.max(0, 7 * a) + Math.max(0, 7 * b);
      for (let threshold = low + 1; threshold <= high; threshold++) halfPlane(a, b, threshold, family);
    }
  }
  completeFamily([[1, 1]], '45');
  completeFamily([[1, 2], [2, 1]], '1:2');
  // One complete rotation/reflection/inversion orbit of a central 1:3 cut.
  for (let turn = 0; turn < 4; turn++) for (const mirror of [false, true]) for (const inverse of [false, true]) {
    let a = 1, b = 3, threshold = 14;
    for (let r = 0; r < turn; r++) [a, b, threshold] = [-b, a, threshold - 7 * b];
    if (mirror) [a, threshold] = [-a, threshold - 7 * a];
    if (inverse) [a, b, threshold] = [-a, -b, 1 - threshold];
    halfPlane(a, b, threshold, '1:3');
  }
  const usedCount = glyphs.length;
  if (usedCount !== 230) throw new Error(`Expected230 unique mathematical shapes, got${usedCount}`);
  for (let index = usedCount; index < 256; index++) glyphs.push({index, rows: Array(8).fill(0), filled: 0, label: 'Reserverat', kind: 'reserved', family: 'reserved', predefined: false});
  return {glyphs, usedCount, fontBytes: 2048, excludedSmallFragments: excluded.size, maximumExcludedFragmentPixels: 2};
}

function generateJunctionFont(options = {}) {
  const base = generateBaseFont();
  if (options.junctions === false) return base;
  const additions = options.additions ?? require('./junction-selection.json').glyphs;
  const glyphs = base.glyphs.slice(0, base.usedCount);
  for (const value of additions) glyphs.push({...value, index: glyphs.length, predefined: false});
  if (glyphs.length !== 256) throw new Error(`Expected 256 shapes with junctions, got ${glyphs.length}`);
  return {...base, glyphs, usedCount: glyphs.length, junctionGlyphs: additions.length};
}

function generateFont(options = {}) {
  if (options.junctions === false) return generateBaseFont();
  if (options.additions) return generateJunctionFont(options);
  const palette = require('./general-palette.json');
  return {...palette, glyphs: palette.glyphs.map(({fixed, ...glyph}) => ({...glyph, rows: glyph.rows.slice()}))};
}

function toBytes(font = generateFont()) {
  return Buffer.from(font.glyphs.flatMap(glyph => glyph.rows));
}

module.exports = {generateBaseFont, generateJunctionFont, generateFont, toBytes};
