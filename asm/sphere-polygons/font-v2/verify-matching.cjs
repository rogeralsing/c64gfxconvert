'use strict';

// Independent row-byte oracle for the actual pixel matcher, including the
// requirement that every lit font pixel lies inside the sphere silhouette.
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const assert = require('node:assert/strict'), {createHash} = require('node:crypto');
const {buildBrowserSource} = require('./browser-font.cjs');
const {generateFont} = require('./font.cjs');
const legacy = path.join(__dirname, 'legacy');
const input = process.argv[2] ? JSON.parse(fs.readFileSync(process.argv[2], 'utf8')) : null;
const palette = input ? input.palette || input : generateFont();
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
function runtime(folder) {
  const context = vm.createContext({});
  vm.runInContext(buildBrowserSource(palette), context);
  for (const name of ['direct-core.js', 'sphere-renderer.js']) vm.runInContext(fs.readFileSync(path.join(folder, name), 'utf8'), context);
  return {font: context.GlyphMath.generateFont(), renderer: new context.SphereMath.SphereRenderer()};
}
const original = runtime(legacy), corrected = runtime(path.join(__dirname, 'matching'));
const rowPopcount = value => {let result = 0; for (let bit = 0; bit < 8; bit++) result += (value >>> bit) & 1; return result;};
let tiles = 0, savedPixels = 0;
for (const radius of [64, 94, 120]) {
  const allowed = Array.from({length: 1000}, (_, cell) => {
    const left = (cell % 40) * 8, top = Math.floor(cell / 40) * 8;
    const mask = Array.from({length: 8}, (_, y) => {
      let row = 0;
      for (let x = 0; x < 8; x++) if ((left + x + .5 - 160) ** 2 + (top + y + .5 - 100) ** 2 <= radius ** 2) row |= 128 >>> x;
      return row;
    });
    return palette.glyphs.filter(glyph => glyph.rows.every((row, y) => !(row & ~mask[y])));
  });
  for (const tilt of [-45, 22, 50]) for (const angle of [.38, 1.1, 2.4]) {
    const state = {radius, tilt, angle, checks: 24, solid: false};
    original.renderer.render(state, original.font); corrected.renderer.render(state, corrected.font);
    assert.deepEqual(Buffer.from(original.renderer.source), Buffer.from(corrected.renderer.source));
    for (let cell = 0; cell < 1000; cell++) {
      const left = (cell % 40) * 8, top = Math.floor(cell / 40) * 8;
      const target = Array.from({length: 8}, (_, y) => {
        let row = 0;
        for (let x = 0; x < 8; x++) if (corrected.renderer.source[(top + y) * 320 + left + x]) row |= 128 >>> x;
        return row;
      });
      let minimum = 65;
      for (const glyph of allowed[cell]) minimum = Math.min(minimum, glyph.rows.reduce((error, row, y) => error + rowPopcount(row ^ target[y]), 0));
      assert.equal(corrected.renderer.stats.errors[cell], minimum, `Nonoptimal admissible glyph at cell${cell}`);
      assert(corrected.renderer.stats.errors[cell] <= original.renderer.stats.errors[cell]);
      savedPixels += original.renderer.stats.errors[cell] - corrected.renderer.stats.errors[cell];
      tiles++;
    }
  }
}
const result = {pass: true, contexts: 27, tilesAgainstExhaustiveIndependentOracle: tiles,
  pixelErrorsSaved: savedPixels, regressedTiles: 0, sourceBitmapUnchanged: true,
  fontSha256: sha(Buffer.from(palette.glyphs.flatMap(glyph => glyph.rows))),
  sources: Object.fromEntries(['direct-core.js', 'sphere-renderer.js'].map(name => [name, sha(fs.readFileSync(path.join(__dirname, 'matching', name)))]))};
fs.mkdirSync(path.join(__dirname, 'build'), {recursive: true});
fs.writeFileSync(path.join(__dirname, 'build/matching-proof.json'), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify(result, null, 2));
