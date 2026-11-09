(function (root) {
  'use strict';

  const methods = root.DirectMethods || (root.DirectMethods = {});
  const priority = { quadrant: 0, edge: 1, corner: 2, crossing: 3 };

  function readGlyphPixel(glyph, x, y) {
    const bit = y * 8 + x;
    return ((bit < 32 ? glyph.lo : glyph.hi) >>> (bit & 31)) & 1;
  }

  function createProbeMethod(columns, tieRule = 'coverage') {
    const cache = new WeakMap();
    const dimension = columns.length;
    const sampleCount = dimension * dimension;
    const size = 1 << sampleCount;
    const points = [];
    for (const y of columns) for (const x of columns) points.push({ x, y });

    function create(font) {
      if (cache.has(font)) return cache.get(font);
      if (!font || !font.glyphs || font.glyphs.length > 256) {
        throw new Error('Probe methods require a fixed font with at most 256 glyphs.');
      }

      // All work in this block depends only on the fixed font, never on a scene.
      const signatures = new Uint16Array(font.glyphs.length);
      const coverage = new Uint8Array(font.glyphs.length);
      const ranks = new Uint8Array(font.glyphs.length);
      for (let i = 0; i < font.glyphs.length; i++) {
        const glyph = font.glyphs[i];
        let bits = 0;
        for (let p = 0; p < points.length; p++) {
          bits |= readGlyphPixel(glyph, points[p].x, points[p].y) << p;
        }
        signatures[i] = bits;
        coverage[i] = Math.round(glyph.coverage * 64);
        ranks[i] = priority[glyph.kind] === undefined ? 4 : priority[glyph.kind];
      }
      const counts = new Uint8Array(size);
      for (let bits = 1; bits < size; bits++) counts[bits] = counts[bits >>> 1] + (bits & 1);
      let distances;
      if (tieRule === 'medoid') {
        const count = font.glyphs.length;
        distances = new Uint8Array(count * count);
        for (let i = 0; i < count; i++) for (let j = 0; j < count; j++) {
          const low = (font.glyphs[i].lo ^ font.glyphs[j].lo) >>> 0;
          const high = (font.glyphs[i].hi ^ font.glyphs[j].hi) >>> 0;
          distances[i * count + j] = counts[low & 255] + counts[(low >>> 8) & 255]
            + counts[(low >>> 16) & 255] + counts[low >>> 24]
            + counts[high & 255] + counts[(high >>> 8) & 255]
            + counts[(high >>> 16) & 255] + counts[high >>> 24];
        }
      }
      const table = new Uint8Array(size);
      for (let bits = 0; bits < size; bits++) {
        const desiredCoverage = counts[bits] * 64;
        let best = 0, bestScore = Infinity;
        if (tieRule === 'medoid') {
          let minimum = sampleCount + 1;
          const candidates = [];
          for (let i = 0; i < signatures.length; i++) {
            const mismatch = counts[bits ^ signatures[i]];
            if (mismatch < minimum) { minimum = mismatch; candidates.length = 0; }
            if (mismatch === minimum) candidates.push(i);
          }
          // A font-only medoid represents all equally compatible glyphs.
          for (const i of candidates) {
            let sum = 0;
            for (const j of candidates) sum += distances[i * signatures.length + j];
            const score = sum * 8 + ranks[i];
            if (score < bestScore) { bestScore = score; best = i; }
          }
          table[bits] = best;
          continue;
        }
        for (let i = 0; i < signatures.length; i++) {
          const mismatch = counts[bits ^ signatures[i]];
          const coverageError = Math.abs(coverage[i] * sampleCount - desiredCoverage);
          // Probe agreement dominates; coverage and a simpler shape break ties.
          const score = mismatch * 65536 + coverageError * 8 + ranks[i];
          if (score < bestScore) { bestScore = score; best = i; }
        }
        table[bits] = best;
      }

      const result = {
        name: dimension + '×' + dimension + ' prober',
        tableBytes: table.byteLength,
        sampleCount,
        points: points.map(point => ({ x: point.x + 0.5, y: point.y + 0.5 })),
        render(state) {
          const scene = root.DirectCore.createScene(state);
          const screen = new Uint8Array(1000);
          let samples = 0, tableReads = 0;
          for (const index of scene.tiles) {
            const tile = scene.tile(index);
            let signature = 0;
            for (let p = 0; p < points.length; p++) {
              const point = points[p];
              signature |= (scene.checkAt(tile.x + point.x + 0.5, tile.y + point.y + 0.5) ? 1 : 0) << p;
            }
            samples += sampleCount;
            screen[index] = table[signature];
            tableReads++;
          }
          const silhouette = root.DirectCore.constrainToSilhouette(screen, font, state.radius);
          return {
            screen,
            ops: {
              ...scene.ops,
              samples,
              tableReads,
              glyphComparisons: 0,
              densePixels: 0,
              silhouetteLookups: silhouette.lookups, silhouetteChanges: silhouette.changes,
              silhouetteTableBytes: silhouette.tableBytes, silhouetteIndexBytes: silhouette.indexBytes
            }
          };
        }
      };
      cache.set(font, result);
      return result;
    }
    return { create };
  }

  // Sparse positions coincide with actual pixel centers in both font and scene.
  methods.probes3 = createProbeMethod([1, 4, 6], 'medoid');
  methods.probes4 = createProbeMethod([0, 2, 5, 7]);
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { probes3: methods.probes3, probes4: methods.probes4 };
  }
})(typeof window !== 'undefined' ? window : globalThis);
