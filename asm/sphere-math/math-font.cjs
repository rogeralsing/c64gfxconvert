(function (root) {
  'use strict';

  const cache = new Map();

  function popcount32(value) {
    value >>>= 0;
    value -= (value >>> 1) & 0x55555555;
    value = (value & 0x33333333) + ((value >>> 2) & 0x33333333);
    return (((value + (value >>> 4)) & 0x0f0f0f0f) * 0x01010101) >>> 24;
  }

  function makeGlyph(predicate, kind) {
    const rows = new Uint8Array(8);
    let lo = 0, hi = 0;
    for (let y = 0; y < 8; y++) {
      for (let x = 0; x < 8; x++) {
        if (!predicate(x, y)) continue;
        rows[y] |= 0x80 >>> x;
        const bit = y * 8 + x;
        if (bit < 32) lo |= 1 << bit;
        else hi |= 1 << (bit - 32);
      }
    }
    lo >>>= 0;
    hi >>>= 0;
    return { lo, hi, rows, coverage: (popcount32(lo) + popcount32(hi)) / 64, kind };
  }

  function complement(glyph) {
    return {
      lo: (~glyph.lo) >>> 0,
      hi: (~glyph.hi) >>> 0,
      rows: Uint8Array.from(glyph.rows, row => row ^ 255),
      coverage: 1 - glyph.coverage,
      kind: glyph.kind
    };
  }

  function key(glyph) { return glyph.lo + ':' + glyph.hi; }

  function distance(a, b) {
    return popcount32(a.lo ^ b.lo) + popcount32(a.hi ^ b.hi);
  }

  function generateFont(requestedLimit = 256) {
    const limit = Math.max(16, Math.min(256, Math.floor(requestedLimit)));
    if (cache.has(limit)) return cache.get(limit);
    const glyphs = [];
    const seen = new Set();
    function add(glyph) {
      const id = key(glyph);
      if (seen.has(id) || glyphs.length >= limit) return false;
      seen.add(id);
      glyphs.push(glyph);
      return true;
    }
    // All combinations of four 4×4 quadrants form the coarse baseline.
    for (let mask = 0; mask < 16; mask++) {
      add(makeGlyph((x, y) => (mask >>> ((x >= 4 ? 1 : 0) + (y >= 4 ? 2 : 0))) & 1, 'quadrant'));
    }

    const edges = [];
    const corners = [];
    const candidateKeys = new Set(seen);
    function candidate(list, glyph) {
      const id = key(glyph);
      if (candidateKeys.has(id)) return;
      candidateKeys.add(id);
      list.push(glyph);
    }

    // A glyph is the sampled half-plane n·p >= d; no scene data is involved.
    for (let a = 0; a < 32; a++) {
      const angle = a * Math.PI / 16;
      const nx = Math.cos(angle), ny = Math.sin(angle);
      const extent = 3.5 * (Math.abs(nx) + Math.abs(ny));
      for (let offset = 1; offset < 16; offset++) {
        const d = extent * (offset / 8 - 1);
        const glyph = makeGlyph((x, y) => nx * (x - 3.5) + ny * (y - 3.5) >= d, 'edge');
        candidate(edges, glyph);
        candidate(edges, complement(glyph));
      }
    }

    // Intersections and XORs of two half-planes cover wedges and checker crossings.
    const normals = Array.from({ length: 8 }, (_, i) => [Math.cos(i * Math.PI / 8), Math.sin(i * Math.PI / 8)]);
    for (let a = 0; a < normals.length; a++) {
      for (let b = a + 2; b < normals.length; b += 2) {
        const [ax, ay] = normals[a], [bx, by] = normals[b];
        for (const da of [-2, 0, 2]) for (const db of [-2, 0, 2]) {
          const sideA = (x, y) => ax * (x - 3.5) + ay * (y - 3.5) >= da;
          const sideB = (x, y) => bx * (x - 3.5) + by * (y - 3.5) >= db;
          const corner = makeGlyph((x, y) => sideA(x, y) && sideB(x, y), 'corner');
          const crossing = makeGlyph((x, y) => sideA(x, y) !== sideB(x, y), 'crossing');
          candidate(corners, corner);
          candidate(corners, complement(corner));
          candidate(corners, crossing);
          candidate(corners, complement(crossing));
        }
      }
    }

    function fillFrom(pool, target) {
      const scores = new Int16Array(pool.length);
      for (let i = 0; i < pool.length; i++) {
        let closest = 64;
        for (const glyph of glyphs) closest = Math.min(closest, distance(pool[i], glyph));
        scores[i] = closest;
      }
      while (glyphs.length < target) {
        let best = -1, score = -1;
        for (let i = 0; i < pool.length; i++) {
          if (!seen.has(key(pool[i])) && scores[i] > score) { best = i; score = scores[i]; }
        }
        if (best < 0) break;
        const selected = pool[best];
        add(selected);
        const inverse = complement(selected);
        if (glyphs.length < target) add(inverse);
        for (let i = 0; i < pool.length; i++) {
          scores[i] = Math.min(scores[i], distance(pool[i], selected), distance(pool[i], inverse));
        }
      }
    }

    const edgeTarget = 16 + Math.round((limit - 16) * 0.8 / 2) * 2;
    fillFrom(edges, edgeTarget);
    fillFrom(corners, limit);
    if (glyphs.length < limit) fillFrom(edges, limit);
    const exact = new Map(glyphs.map((glyph, index) => [key(glyph), index]));
    let signature = 0x811c9dc5;
    for (const glyph of glyphs) for (const row of glyph.rows) {
      signature = Math.imul(signature ^ row, 0x01000193) >>> 0;
    }
    const font = {
      glyphs, limit, count: glyphs.length, exact,
      signature: signature.toString(16).padStart(8, '0'),
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
    // Baseline indices 0 and 15 are always empty and full.
    if ((lo | hi) === 0) return { index: 0, error: 0 };
    if (lo === 0xffffffff && hi === 0xffffffff) return { index: 15, error: 0 };
    const exact = font.exact.get(lo + ':' + hi);
    if (exact !== undefined) return { index: exact, error: 0 };
    let bestIndex = 0, bestError = 65;
    for (let i = 0; i < font.count; i++) {
      const error = popcount32(lo ^ font.lo[i]) + popcount32(hi ^ font.hi[i]);
      if (error < bestError) { bestError = error; bestIndex = i; }
    }
    return { index: bestIndex, error: bestError };
  }

  const api = { generateFont, nearestGlyph, popcount32 };
  root.GlyphMath = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
