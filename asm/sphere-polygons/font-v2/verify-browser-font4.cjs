'use strict';

// Cross the browser/native byte boundary, then exercise actual rendering at
// several settings. The expected display uses the frozen C64 font and mapping.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {buildBrowserSource4} = require('./browser-font4.cjs');

const here = __dirname;
const read = file => fs.readFileSync(path.join(here, file));
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const nativeFont = read('build/font4-dedupe/font.bin');
const nativeMap = JSON.parse(read('build/font4-dedupe/map.json'));
const fineScreens = read('c64-preview/build/movie.frames');
const coarseScreens = read('build/font4-dedupe/reference.frames');
const context = vm.createContext({});
vm.runInContext(buildBrowserSource4(), context, {filename: 'browser-font4.generated.js'});
for (const name of ['direct-core.js', 'sphere-renderer.js']) {
  vm.runInContext(read('matching/' + name).toString(), context, {filename: name});
}
const math = context.GlyphMath;
const coarse = math.generateCoarsenedFont(), fine = math.generateFont(256);
assert.equal(coarse, math.generateCoarsenedFont());
assert.equal(coarse.sourceFont, fine);
assert.equal(coarse.count, 168);
assert.equal(coarse.emptyGlyph, 0);
assert.equal(coarse.filledGlyph, 8);
assert.deepEqual(Buffer.from(coarse.glyphs.flatMap(glyph => Array.from(glyph.rows))), nativeFont);
assert.deepEqual(Buffer.from(coarse.oldToNew), Buffer.from(nativeMap));
assert.equal(sha(Buffer.from(fine.glyphs.flatMap(glyph => Array.from(glyph.rows)))),
  'e4071e1e3176e3ee65eeb5fc2df5bb3eccab7b733b9ea7cbb276a2f3a65a1aac');
assert.deepEqual(Buffer.from(math.mapCoarsenedScreen(fineScreens, coarse)), coarseScreens);

function pixels(screen) {
  const result = Buffer.alloc(64000);
  for (let cell = 0; cell < 1000; cell++) {
    const left = cell % 40 * 8, top = Math.floor(cell / 40) * 8;
    for (let row = 0; row < 8; row++) for (let x = 0; x < 8; x++) {
      result[(top + row) * 320 + left + x] = (nativeFont[screen[cell] * 8 + row] >>> (7 - x)) & 1;
    }
  }
  return result;
}

// Independent reduction through a 160x100 intermediate, then expansion.
function referencePixels(source) {
  const small = new Uint8Array(160 * 100), output = Buffer.alloc(64000);
  for (let y = 0; y < 100; y++) for (let x = 0; x < 160; x++) {
    let count = 0;
    for (let dy = 0; dy < 2; dy++) for (let dx = 0; dx < 2; dx++) count += source[(y * 2 + dy) * 320 + x * 2 + dx];
    small[y * 160 + x] = Number(count >= 3);
  }
  for (let y = 0; y < 200; y++) for (let x = 0; x < 320; x++) output[y * 320 + x] = small[(y >> 1) * 160 + (x >> 1)];
  return output;
}

const normalRenderer = new context.SphereMath.SphereRenderer();
const coarseRenderer = new context.SphereMath.SphereRenderer();
const cases = [
  {radius: 145, checks: 20, tilt: 65, angle: .38, solid: false},
  {radius: 94, checks: 12, tilt: 22, angle: 1.1, solid: false},
  {radius: 120, checks: 24, tilt: -45, angle: 2.4, solid: false},
  {radius: 145, checks: 20, tilt: 65, angle: .38, solid: true}
];
for (const state of cases) {
  normalRenderer.render(state, fine);
  const stats = math.renderCoarsened(coarseRenderer, state, coarse);
  const wanted = Uint8Array.from(normalRenderer.screen, code => nativeMap[code]);
  const expectedPixels = pixels(wanted);
  assert.deepEqual(Buffer.from(coarseRenderer.screen), Buffer.from(wanted));
  assert.deepEqual(Buffer.from(coarseRenderer.output), expectedPixels);
  assert.deepEqual(Buffer.from(coarseRenderer.source), Buffer.from(normalRenderer.source));
  const expectedReference = referencePixels(normalRenderer.source);
  assert.deepEqual(Buffer.from(coarseRenderer.displayReference), expectedReference);
  assert.notEqual(coarseRenderer.displayReference, coarseRenderer.source);
  assert.equal(coarseRenderer.lastFont, fine, 'The matching renderer must select from the original font.');
  const expectedUsed = new Uint16Array(168), expectedErrors = new Uint8Array(1000);
  let mismatch = 0, exactCells = 0;
  for (let cell = 0; cell < 1000; cell++) {
    expectedUsed[wanted[cell]]++;
    const left = cell % 40 * 8, top = Math.floor(cell / 40) * 8;
    for (let row = 0; row < 8; row++) for (let x = 0; x < 8; x++) {
      const at = (top + row) * 320 + left + x;
      if (expectedPixels[at] !== expectedReference[at]) { expectedErrors[cell]++; mismatch++; }
    }
    if (normalRenderer.activeCells[cell] && expectedErrors[cell] === 0) exactCells++;
  }
  assert.deepEqual(Array.from(stats.used), Array.from(expectedUsed));
  assert.deepEqual(Buffer.from(stats.errors), Buffer.from(expectedErrors));
  assert.equal(stats.mismatches, mismatch);
  assert.equal(stats.usedCount, expectedUsed.reduce((sum, value) => sum + (value > 0), 0));
  assert.equal(stats.exactCells, exactCells);
  assert.equal(stats.displayedFontCount, 168);
  assert.equal(stats.sourceFontCount, 256);
  assert.equal(stats.mismatches % 4, 0, 'Coarse differences must cover complete 2x2 pixels.');
}
const proof = {pass: true, browserFontBytes: nativeFont.length, browserGlyphs: coarse.count,
  browserFontSha256: sha(nativeFont), glyphMappingsChecked: nativeMap.length,
  corpusCharacterMappingsChecked: fineScreens.length, actualRendererSettingsChecked: cases.length,
  originalFontSelectionPreserved: true, displayPixelsAndErrorStatisticsVerified: true,
  coarseReferenceResolution: [160, 100], originalFineReferencePreserved: true,
  source: 'Exact existing-font coarsening and deduplication; no new palette or glyph matching.'};
fs.mkdirSync(path.join(here, 'build'), {recursive: true});
fs.writeFileSync(path.join(here, 'build/browser-font4-proof.json'), JSON.stringify(proof, null, 2) + '\n');
console.log(JSON.stringify(proof, null, 2));
