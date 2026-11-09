(function (root) {
  'use strict';

  const WIDTH = 320, HEIGHT = 200, COLS = 40, ROWS = 25;
  const CAMERA = 3.2;
  const TOTAL = WIDTH * HEIGHT;

  class SphereRenderer {
    constructor() {
      this.hits = new Float32Array(TOTAL * 3);
      this.inside = new Uint8Array(TOTAL);
      this.source = new Uint8Array(TOTAL);
      this.output = new Uint8Array(TOTAL);
      this.screen = new Uint8Array(COLS * ROWS);
      this.activeCells = new Uint8Array(COLS * ROWS);
      this.radius = 0;
      this.cache = new Map();
    }

    setRadius(radius) {
      if (radius === this.radius) return;
      this.radius = radius;
      const focal = radius * Math.sqrt(CAMERA * CAMERA - 1);
      this.inside.fill(0);
      this.activeCells.fill(0);
      this.surfacePixels = 0;
      for (let y = 0; y < HEIGHT; y++) {
        for (let x = 0; x < WIDTH; x++) {
          const i = y * WIDTH + x;
          const dx = (x + 0.5 - WIDTH / 2) / focal;
          const dy = (HEIGHT / 2 - y - 0.5) / focal;
          const a = dx * dx + dy * dy + 1;
          const discriminant = CAMERA * CAMERA - a * (CAMERA * CAMERA - 1);
          if (discriminant < 0) continue;
          const t = (CAMERA - Math.sqrt(discriminant)) / a;
          this.hits[3 * i] = t * dx;
          this.hits[3 * i + 1] = t * dy;
          this.hits[3 * i + 2] = CAMERA - t;
          this.inside[i] = 1;
          this.activeCells[(y >> 3) * COLS + (x >> 3)] = 1;
          this.surfacePixels++;
        }
      }
      this.activeCellCount = this.activeCells.reduce((sum, value) => sum + value, 0);
    }

    render(state, font) {
      if (font !== this.lastFont) {
        this.cache.clear();
        this.lastFont = font;
      }
      this.setRadius(state.radius);
      const sy = Math.sin(state.angle), cy = Math.cos(state.angle);
      const pitch = state.tilt * Math.PI / 180;
      const sx = Math.sin(pitch), cx = Math.cos(pitch);
      const bands = state.checks / 2;
      // Intersections remain in camera space. The inverse rotation maps the
      // surface into object space, so the checkerboard turns with the sphere.
      for (let i = 0; i < TOTAL; i++) {
        if (!this.inside[i]) { this.source[i] = 0; continue; }
        if (state.solid) { this.source[i] = 1; continue; }
        const px = this.hits[3 * i], py = this.hits[3 * i + 1], pz = this.hits[3 * i + 2];
        const x = cy * px - sy * pz;
        const z1 = sy * px + cy * pz;
        const y = cx * py + sx * z1;
        const z = -sx * py + cx * z1;
        const u = (Math.atan2(x, z) + Math.PI) * state.checks / (2 * Math.PI);
        const v = (Math.asin(Math.max(-1, Math.min(1, y))) + Math.PI / 2) * bands / Math.PI;
        this.source[i] = (Math.floor(u) ^ Math.floor(v)) & 1;
      }

      let mismatches = 0, surfaceErrors = 0, usedCount = 0, exactCells = 0;
      const used = new Uint16Array(font.glyphs.length);
      const errors = new Uint8Array(COLS * ROWS);
      for (let cellY = 0; cellY < ROWS; cellY++) {
        for (let cellX = 0; cellX < COLS; cellX++) {
          const cell = cellY * COLS + cellX;
          let lo = 0, hi = 0;
          for (let y = 0; y < 8; y++) {
            const start = (cellY * 8 + y) * WIDTH + cellX * 8;
            for (let x = 0; x < 8; x++) {
              if (!this.source[start + x]) continue;
              const bit = y * 8 + x;
              if (bit < 32) lo |= 1 << bit;
              else hi |= 1 << (bit - 32);
            }
          }
          lo >>>= 0; hi >>>= 0;
          // The font cache only stores matches; it never adds glyphs.
          const key = lo + ':' + hi;
          let match = this.cache.get(key);
          if (!match) {
            match = root.GlyphMath.nearestGlyph(lo, hi, font);
            if (this.cache.size > 24000) this.cache.clear();
            this.cache.set(key, match);
          }
          this.screen[cell] = match.index;
        }
      }
      const silhouette = root.DirectCore && root.DirectCore.constrainToSilhouette
        ? root.DirectCore.constrainToSilhouette(this.screen, font, state.radius)
        : { lookups: 0, changes: 0, tableBytes: 0, indexBytes: 0 };
      for (let cellY = 0; cellY < ROWS; cellY++) {
        for (let cellX = 0; cellX < COLS; cellX++) {
          const cell = cellY * COLS + cellX, code = this.screen[cell];
          const glyph = font.glyphs[code];
          let cellError = 0;
          if (used[code]++ === 0) usedCount++;
          // The displayed image is reconstructed only from the screen codes
          // and the immutable font. Reference pixels never enter this path.
          for (let y = 0; y < 8; y++) {
            const start = (cellY * 8 + y) * WIDTH + cellX * 8;
            const bits = y < 4 ? glyph.lo : glyph.hi;
            for (let x = 0; x < 8; x++) {
              const value = (bits >>> ((y & 3) * 8 + x)) & 1;
              this.output[start + x] = value;
              if (value !== this.source[start + x]) {
                cellError++;
                if (this.inside[start + x]) surfaceErrors++;
              }
            }
          }
          errors[cell] = cellError;
          mismatches += cellError;
          if (this.activeCells[cell] && cellError === 0) exactCells++;
        }
      }
      return this.stats = {
        mismatches, surfaceErrors, usedCount, exactCells, used, errors, silhouette,
        surfacePixels: this.surfacePixels,
        activeCells: this.activeCellCount,
        // Includes errors spilling outside the silhouette. Empty screen area
        // cannot dilute this figure. Values can exceed 100% in pathological cases.
        normalizedError: mismatches / Math.max(1, this.surfacePixels),
        fullFrameError: mismatches / TOTAL
      };
    }

    resetFont() { this.cache.clear(); }
  }

  const api = { SphereRenderer, WIDTH, HEIGHT, COLS, ROWS };
  root.SphereMath = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
