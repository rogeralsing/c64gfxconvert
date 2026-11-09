'use strict';

const {generateFont: generatePalette} = require('./font.cjs');

// Keep the browser adapter self-contained so previews need no file requests.
function installGlyphMath(root, palette) {
  const cache = new Map();

  function popcount32(value) {
    value >>>= 0;
    value -= (value >>> 1) & 0x55555555;
    value = (value & 0x33333333) + ((value >>> 2) & 0x33333333);
    return (((value + (value >>> 4)) & 0x0f0f0f0f) * 0x01010101) >>> 24;
  }

  function generateFont(requestedLimit = 256) {
    const requested = Number(requestedLimit);
    const limit = Math.max(30, Math.min(256, Number.isFinite(requested) ? Math.floor(requested) : 256));
    if (cache.has(limit)) return cache.get(limit);
    // Reserved slots remain export padding, never glyph-selection candidates.
    const count = Math.min(limit, palette.usedCount);
    const glyphs = palette.glyphs.slice(0, count).map(source => {
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
    const exact = new Map(glyphs.map((glyph, index) => [glyph.lo + ':' + glyph.hi, index]));
    let signature = 0x811c9dc5;
    for (const glyph of glyphs) for (const row of glyph.rows) signature = Math.imul(signature ^ row, 0x01000193) >>> 0;
    const font = {
      glyphs, limit, count, exact, signature: signature.toString(16).padStart(8, '0'),
      lo: Uint32Array.from(glyphs, glyph => glyph.lo),
      hi: Uint32Array.from(glyphs, glyph => glyph.hi),
      kinds: glyphs.reduce((counts, glyph) => {
        counts[glyph.kind] = (counts[glyph.kind] || 0) + 1;
        return counts;
      }, {})
    };
    cache.set(limit, font);
    return font;
  }

  function nearestGlyph(lo, hi, font) {
    lo >>>= 0;
    hi >>>= 0;
    if ((lo | hi) === 0) return {index: 0, error: 0};
    if (lo === 0xffffffff && hi === 0xffffffff) return {index: 15, error: 0};
    const exact = font.exact.get(lo + ':' + hi);
    if (exact !== undefined) return {index: exact, error: 0};
    let bestIndex = 0, bestError = 65;
    for (let index = 0; index < font.count; index++) {
      const error = popcount32(lo ^ font.lo[index]) + popcount32(hi ^ font.hi[index]);
      if (error < bestError) { bestError = error; bestIndex = index; }
    }
    return {index: bestIndex, error: bestError};
  }

  const api = {generateFont, nearestGlyph, popcount32};
  root.GlyphMath = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
}

function buildBrowserSource(palette = generatePalette()) {
  const active = {usedCount: palette.usedCount, glyphs: palette.glyphs.slice(0, palette.usedCount)};
  return '(' + installGlyphMath.toString() + ')(typeof window !== "undefined" ? window : globalThis,' + JSON.stringify(active) + ');\n';
}

module.exports = {buildBrowserSource};
if (require.main === module) process.stdout.write(buildBrowserSource());
