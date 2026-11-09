'use strict';

const {generateFont, toBytes} = require('./font.cjs');
const {dedupe} = require('./font4-dedupe.cjs');
const {buildBrowserSource} = require('./browser-font.cjs');

// The fine renderer still chooses the original glyph. Only its completed
// screen is remapped to the coarsened, deduplicated glyphs for presentation.
function installCoarsenedGlyphMath(root, palette) {
  const math = root.GlyphMath;
  let cached;

  function generateCoarsenedFont() {
    if (cached) return cached;
    const glyphs = palette.glyphs.map(source => {
      const rows = Uint8Array.from(source.rows);
      let lo = 0, hi = 0;
      for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
        if (!(rows[y] & (128 >>> x))) continue;
        const bit = y * 8 + x;
        if (bit < 32) lo |= 1 << bit;
        else hi |= 1 << (bit - 32);
      }
      return {...source, rows, lo: lo >>> 0, hi: hi >>> 0,
        coverage: source.filled / 64, sourceKind: source.kind,
        kind: source.kind === 'diagonal' ? 'edge' : source.kind === 'basic' ? 'quadrant' : source.kind};
    });
    let signature = 0x811c9dc5;
    for (const glyph of glyphs) for (const row of glyph.rows) signature = Math.imul(signature ^ row, 0x01000193) >>> 0;
    const oldToNew = Uint8Array.from(palette.oldToNew);
    cached = {
      glyphs, count: glyphs.length, limit: glyphs.length, usedCount: glyphs.length,
      fontBytes: glyphs.length * 8, coarsened: true,
      logicalPixels: [4, 4], physicalPixelsPerLogicalPixel: [2, 2],
      oldToNew, sourceFont: math.generateFont(256),
      emptyGlyph: oldToNew[0], filledGlyph: oldToNew[15],
      exact: new Map(glyphs.map((glyph, index) => [glyph.lo + ':' + glyph.hi, index])),
      signature: signature.toString(16).padStart(8, '0'),
      lo: Uint32Array.from(glyphs, glyph => glyph.lo),
      hi: Uint32Array.from(glyphs, glyph => glyph.hi),
      kinds: glyphs.reduce((counts, glyph) => {
        counts[glyph.kind] = (counts[glyph.kind] || 0) + 1;
        return counts;
      }, {})
    };
    return cached;
  }

  function mapCoarsenedScreen(screen, font = generateCoarsenedFont()) {
    if (!font.coarsened || !font.oldToNew) throw new TypeError('Expected the coarsened font and its original-code mapping.');
    return Uint8Array.from(screen, code => {
      if (code >= font.oldToNew.length) throw new RangeError('Original character code is outside the font mapping.');
      return font.oldToNew[code];
    });
  }

  function coarsenReferencePixels(pixels) {
    if (pixels.length !== 64000) throw new RangeError('Expected a 320 by 200 reference image.');
    const output = new Uint8Array(64000);
    for (let y = 0; y < 200; y += 2) for (let x = 0; x < 320; x += 2) {
      const at = y * 320 + x;
      const value = Number(pixels[at] + pixels[at + 1] + pixels[at + 320] + pixels[at + 321] > 2);
      output[at] = output[at + 1] = output[at + 320] = output[at + 321] = value;
    }
    return output;
  }

  function renderCoarsened(renderer, state, font = generateCoarsenedFont()) {
    const fineStats = renderer.render(state, font.sourceFont);
    const reference = coarsenReferencePixels(renderer.source);
    renderer.displayReference = reference;
    renderer.fineScreen = Uint8Array.from(renderer.screen);
    renderer.screen.set(mapCoarsenedScreen(renderer.fineScreen, font));
    const used = new Uint16Array(font.count);
    const errors = new Uint8Array(1000);
    let mismatches = 0, surfaceErrors = 0, usedCount = 0, exactCells = 0;
    const radiusSquared = state.radius * state.radius;
    for (let cell = 0; cell < 1000; cell++) {
      const code = renderer.screen[cell], glyph = font.glyphs[code];
      const left = (cell % 40) * 8, top = Math.floor(cell / 40) * 8;
      let cellErrors = 0, active = false;
      if (used[code]++ === 0) usedCount++;
      for (let row = 0; row < 8; row++) for (let column = 0; column < 8; column++) {
        const x = left + column, y = top + row, at = y * 320 + x;
        const value = (glyph.rows[row] >>> (7 - column)) & 1;
        const inside = renderer.inside ? !!renderer.inside[at]
          : (x + 0.5 - 160) ** 2 + (100 - y - 0.5) ** 2 <= radiusSquared;
        active ||= inside;
        renderer.output[at] = value;
        if (value !== reference[at]) {
          cellErrors++;
          if (inside) surfaceErrors++;
        }
      }
      errors[cell] = cellErrors;
      mismatches += cellErrors;
      if (active && cellErrors === 0) exactCells++;
    }
    renderer.displayFont = font;
    renderer.fineStats = fineStats;
    return renderer.stats = {...fineStats, mismatches, surfaceErrors, usedCount, exactCells,
      used, errors, normalizedError: mismatches / Math.max(1, fineStats.surfacePixels),
      fullFrameError: mismatches / 64000, coarsened: true,
      displayedFontCount: font.count, sourceFontCount: font.sourceFont.count,
      referenceResolution: [160, 100], referencePixelSize: [2, 2],
      sourceSelection: 'Original fine glyph selection followed by exact old-to-new remapping.'};
  }

  math.generateCoarsenedFont = generateCoarsenedFont;
  math.mapCoarsenedScreen = mapCoarsenedScreen;
  math.coarsenReferencePixels = coarsenReferencePixels;
  math.renderCoarsened = renderCoarsened;
}

function buildBrowserSource4(palette = generateFont()) {
  const {glyphs, map} = dedupe(toBytes(palette));
  const originals = Array.from({length: glyphs.length}, () => []);
  for (let code = 0; code < map.length; code++) originals[map[code]].push(code);
  const coarse = {oldToNew: map, glyphs: glyphs.map((rows, index) => {
    const first = palette.glyphs[originals[index][0]];
    const filled = rows.reduce((sum, row) => sum + Array.from({length: 8}, (_, bit) => (row >>> bit) & 1).reduce((a, b) => a + b, 0), 0);
    return {...first, index, rows: Array.from(rows), filled,
      label: first.label + ' · 4×4', originalCodes: originals[index]};
  })};
  return buildBrowserSource(palette) + '\n(' + installCoarsenedGlyphMath.toString() +
    ')(typeof window !== "undefined" ? window : globalThis,' + JSON.stringify(coarse) + ');\n';
}

module.exports = {buildBrowserSource4};
if (require.main === module) process.stdout.write(buildBrowserSource4());
