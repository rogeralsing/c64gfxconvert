'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {createHash} = require('node:crypto');
const {generateFont, toBytes} = require('./font.cjs');

const font = generateFont(), bytes = toBytes(font);
assert.equal(bytes.length, 2048);
assert.deepEqual(font.glyphs[0].rows, Array(8).fill(0));
assert.deepEqual(font.glyphs[15].rows, Array(8).fill(255));
const key = rows => Array.from(rows).join(',');
const shapes = new Set(font.glyphs.slice(0, font.usedCount).map(g => key(g.rows)));
assert.equal(shapes.size, font.usedCount);
if (font.excludedSmallFragments !== undefined) assert.equal(font.excludedSmallFragments, 24);
for (const glyph of font.glyphs.slice(0, font.usedCount)) {
  assert(shapes.has(key(glyph.rows.map(row => row ^ 255))), `Missing inverse of${glyph.index}`);
  if (glyph.kind !== 'basic') assert(Math.min(glyph.filled, 64 - glyph.filled) > 2);
  if (glyph.predefined && glyph.emptySide) {
    for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
      const n = glyph.emptyPixels;
      const empty = {left: x < n, right: x >= 8 - n, top: y < n, bottom: y >= 8 - n}[glyph.emptySide];
      assert.equal((glyph.rows[y] >>> (7 - x)) & 1, Number(!empty));
    }
  }
  const rotated = Array.from({length: 8}, (_, y) => {
    let row = 0;
    for (let x = 0; x < 8; x++) if ((glyph.rows[7 - x] >>> (7 - y)) & 1) row |= 128 >>> x;
    return row;
  });
  assert(shapes.has(key(rotated)), `Missing quarter turn of${glyph.index}`);
}
const output = path.join(__dirname, 'build');
fs.mkdirSync(output, {recursive: true});
const template = fs.readFileSync(path.join(__dirname, 'atlas-template.html'), 'utf8');
assert.equal(template.split('/*FONT_DATA*/null').length, 2);
fs.writeFileSync(path.join(output, 'atlas.html'), template.replace('/*FONT_DATA*/null', JSON.stringify(font)));
fs.writeFileSync(path.join(output, 'font.bin'), bytes);
const report = {pass: true, usedCount: font.usedCount, reservedSlots: 256 - font.usedCount,
  predefinedGlyphs: font.glyphs.filter(g => g.predefined).length,
  diagonalGlyphs: font.glyphs.filter(g => g.kind === 'diagonal').length, excludedSmallFragments: font.excludedSmallFragments,
  junctionGlyphs: font.glyphs.filter(g => g.kind === 'corner' || g.kind === 'crossing').length,
  maximumExcludedFragmentPixels: font.maximumExcludedFragmentPixels, fontBytes: bytes.length,
  families: Object.fromEntries([...new Set(font.glyphs.map(g => g.family))].map(family => [family, font.glyphs.filter(g => g.family === family).length])),
  predefinedStripPixelsExact: true, uniqueUsedShapes: true, allRotationsAndInversesPresent: true,
  sha256: createHash('sha256').update(bytes).digest('hex')};
fs.writeFileSync(path.join(output, 'manifest.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report, null, 2));
