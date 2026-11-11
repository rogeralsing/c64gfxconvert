'use strict';

// Offline scene rendering: analytic sphere samples select the original fixed
// 256-glyph font; completed codes map to its existing 168-glyph coarse version.
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {buildBrowserSource4} = require('./browser-font4.cjs');

const WIDTH = 320, HEIGHT = 200, CAMERA = 3.2;

class SceneRenderer {
  constructor() {
    const context = vm.createContext({});
    vm.runInContext(buildBrowserSource4(), context);
    this.math = context.GlyphMath;
    this.font = this.math.generateCoarsenedFont();
    this.fine = this.font.sourceFont;
    this.fontBytes = Buffer.concat(Array.from(this.font.glyphs, glyph => Buffer.from(glyph.rows)));
    this.source = new Uint8Array(WIDTH * HEIGHT);
    this.output = new Uint8Array(WIDTH * HEIGHT);
    this.inside = new Uint8Array(WIDTH * HEIGHT);
    this.screen = new Uint8Array(1000);
    this.fineScreen = new Uint8Array(1000);
    this.cache = new Map();
    this.requiredLo = new Uint32Array(256);
    this.requiredHi = new Uint32Array(256);
    for (let code = 0; code < 256; code++) {
      const coarse = this.font.glyphs[this.font.oldToNew[code]];
      this.requiredLo[code] = (this.fine.lo[code] | coarse.lo) >>> 0;
      this.requiredHi[code] = (this.fine.hi[code] | coarse.hi) >>> 0;
    }
  }

  selectGlyph(lo, hi, insideLo, insideHi) {
    if ((lo | hi) === 0) return 0;
    const key = lo + ':' + hi + ':' + insideLo + ':' + insideHi;
    if (this.cache.has(key)) return this.cache.get(key);
    let best = 0, error = 65;
    const forbiddenLo = ~insideLo, forbiddenHi = ~insideHi;
    for (let code = 0; code < 256; code++) {
      // The mapped 2x2 pixels must stay inside the moving silhouette too.
      if ((this.requiredLo[code] & forbiddenLo) || (this.requiredHi[code] & forbiddenHi)) continue;
      const candidate = this.math.popcount32(lo ^ this.fine.lo[code]) + this.math.popcount32(hi ^ this.fine.hi[code]);
      if (candidate < error) { best = code; error = candidate; }
    }
    if (this.cache.size > 60000) this.cache.clear();
    this.cache.set(key, best);
    return best;
  }

  render(pose, checks) {
    assert(Number.isInteger(checks) && checks >= 4 && checks % 2 === 0);
    this.source.fill(0); this.output.fill(0); this.inside.fill(0);
    this.screen.fill(0); this.fineScreen.fill(0);
    if (!pose.visible || pose.diameter <= 0) {
      return {surfacePixels: 0, activeCells: 0, usedGlyphs: 1, fineMismatches: 0,
        coarseMismatches: 0, normalizedError: 0, silhouetteSpill: 0};
    }
    const radius = pose.diameter / 2;
    const focal = radius * Math.sqrt(CAMERA * CAMERA - 1);
    const cy = Math.cos(pose.yaw), sy = Math.sin(pose.yaw);
    const cp = Math.cos(pose.pitch), sp = Math.sin(pose.pitch);
    const cr = Math.cos(pose.roll), sr = Math.sin(pose.roll);
    const left = Math.max(0, Math.floor(pose.centerX - radius));
    const right = Math.min(WIDTH, Math.ceil(pose.centerX + radius));
    const top = Math.max(0, Math.floor(pose.centerY - radius));
    const bottom = Math.min(HEIGHT, Math.ceil(pose.centerY + radius));
    let area = 0;
    for (let y = top; y < bottom; y++) for (let x = left; x < right; x++) {
      const dx = (x + 0.5 - pose.centerX) / focal;
      const dy = (pose.centerY - y - 0.5) / focal;
      const a = dx * dx + dy * dy + 1;
      const discriminant = CAMERA * CAMERA - a * (CAMERA * CAMERA - 1);
      if (discriminant < 0) continue;
      const at = y * WIDTH + x;
      this.inside[at] = 1; area++;
      const ray = (CAMERA - Math.sqrt(discriminant)) / a;
      const px = ray * dx, py = ray * dy, pz = CAMERA - ray;
      // Forward object rotation is Rz(roll) Rx(pitch) Ry(yaw).
      // Inverse surface transform applies -roll, -pitch, then -yaw.
      const rx = cr * px + sr * py, ry = -sr * px + cr * py;
      const y1 = cp * ry + sp * pz, z1 = -sp * ry + cp * pz;
      const ox = cy * rx - sy * z1, oz = sy * rx + cy * z1;
      const longitude = (Math.atan2(ox, oz) + Math.PI) * checks / (2 * Math.PI);
      const latitude = (Math.asin(Math.max(-1, Math.min(1, y1))) + Math.PI / 2) * (checks / 2) / Math.PI;
      this.source[at] = (Math.floor(longitude) ^ Math.floor(latitude)) & 1;
    }
    let activeCells = 0, fineMismatches = 0, coarseMismatches = 0, spill = 0;
    const used = new Set([0]);
    for (let cellY = 0; cellY < 25; cellY++) for (let cellX = 0; cellX < 40; cellX++) {
      const cell = cellY * 40 + cellX;
      let lo = 0, hi = 0, insideLo = 0, insideHi = 0;
      for (let row = 0; row < 8; row++) for (let column = 0; column < 8; column++) {
        const at = (cellY * 8 + row) * WIDTH + cellX * 8 + column;
        const bit = row * 8 + column;
        if (this.source[at]) { if (bit < 32) lo |= 1 << bit; else hi |= 1 << (bit - 32); }
        if (this.inside[at]) { if (bit < 32) insideLo |= 1 << bit; else insideHi |= 1 << (bit - 32); }
      }
      lo >>>= 0; hi >>>= 0; insideLo >>>= 0; insideHi >>>= 0;
      if (insideLo | insideHi) activeCells++;
      const fineCode = this.selectGlyph(lo, hi, insideLo, insideHi);
      const coarseCode = this.font.oldToNew[fineCode];
      this.fineScreen[cell] = fineCode;
      this.screen[cell] = coarseCode;
      used.add(coarseCode);
      fineMismatches += this.math.popcount32(lo ^ this.fine.lo[fineCode]) + this.math.popcount32(hi ^ this.fine.hi[fineCode]);
      const rows = this.font.glyphs[coarseCode].rows;
      for (let row = 0; row < 8; row++) for (let column = 0; column < 8; column++) {
        const at = (cellY * 8 + row) * WIDTH + cellX * 8 + column;
        const value = (rows[row] >>> (7 - column)) & 1;
        this.output[at] = value;
        coarseMismatches += Number(value !== this.source[at]);
        spill += Number(value && !this.inside[at]);
      }
    }
    assert.equal(spill, 0, 'A mapped glyph extends outside the moving sphere.');
    return {surfacePixels: area, activeCells, usedGlyphs: used.size, fineMismatches,
      coarseMismatches, normalizedError: coarseMismatches / Math.max(1, area), silhouetteSpill: spill};
  }
}

module.exports = {SceneRenderer, WIDTH, HEIGHT, CAMERA};
