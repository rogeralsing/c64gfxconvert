'use strict';

const WIDTH = 40;
const HEIGHT = 25;
const SAMPLE_OFFSETS = [1, 4, 6];
const SAMPLE_Y = Uint8Array.from({ length: 75 }, (_, i) => Math.floor(i / 3) * 8 + SAMPLE_OFFSETS[i % 3]);
const SAMPLE_GAP = Uint8Array.from({ length: 75 }, (_, i) => [3, 2, 3][i % 3]);

function popcount(value) {
  value >>>= 0;
  value -= (value >>> 1) & 0x55555555;
  value = (value & 0x33333333) + ((value >>> 2) & 0x33333333);
  return (((value + (value >>> 4)) & 0x0f0f0f0f) * 0x01010101) >>> 24;
}

function normalizeFont(font) {
  if (font && font.glyphs) return font.glyphs;
  if (!font || font.length !== 2048) throw new Error('Raster LUT construction requires the fixed 2,048-byte font.');
  return Array.from({ length: 256 }, (_, index) => {
    const rows = Uint8Array.from(font.subarray(index * 8, index * 8 + 8));
    let lo = 0, hi = 0;
    for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) if ((rows[y] >>> (7 - x)) & 1) {
      const bit = y * 8 + x;
      if (bit < 32) lo |= 1 << bit;
      else hi |= 1 << (bit - 32);
    }
    return { lo: lo >>> 0, hi: hi >>> 0, rows, kind: 'font' };
  });
}

function sampleBit(sampleRow, sampleColumn, bits) {
  if (bits === 9) return 1 << (sampleRow * 3 + sampleColumn);
  if (sampleRow === 0) return 1 << sampleColumn;
  if (sampleRow === 1) return sampleColumn === 1 ? 0 : 1 << (sampleColumn === 0 ? 3 : 4);
  return 1 << (5 + sampleColumn);
}

function buildTables(font, options = {}) {
  const bits = options.bits === 9 ? 9 : 8;
  const glyphs = normalizeFont(font);
  const signatures = new Uint16Array(glyphs.length);
  for (let index = 0; index < glyphs.length; index++) {
    const glyph = glyphs[index];
    for (let y = 0; y < 3; y++) for (let x = 0; x < 3; x++) {
      if ((glyph.rows[SAMPLE_OFFSETS[y]] >>> (7 - SAMPLE_OFFSETS[x])) & 1) signatures[index] |= sampleBit(y, x, bits);
    }
  }
  const distances = new Uint8Array(glyphs.length * glyphs.length);
  for (let a = 0; a < glyphs.length; a++) for (let b = 0; b < glyphs.length; b++) {
    distances[a * glyphs.length + b] = popcount(glyphs[a].lo ^ glyphs[b].lo) + popcount(glyphs[a].hi ^ glyphs[b].hi);
  }
  const priorities = { quadrant: 0, edge: 1, corner: 2, crossing: 3, font: 0 };
  const glyphLut = new Uint8Array(1 << bits);
  for (let signature = 0; signature < glyphLut.length; signature++) {
    let minimum = bits + 1;
    const candidates = [];
    for (let glyph = 0; glyph < glyphs.length; glyph++) {
      const error = popcount(signature ^ signatures[glyph]);
      if (error < minimum) { minimum = error; candidates.length = 0; }
      if (error === minimum) candidates.push(glyph);
    }
    let best = candidates[0], bestScore = Infinity;
    for (const glyph of candidates) {
      let score = 0;
      for (const other of candidates) score += distances[glyph * glyphs.length + other];
      score = score * 8 + (priorities[glyphs[glyph].kind] || 0);
      if (score < bestScore) { bestScore = score; best = glyph; }
    }
    glyphLut[signature] = best;
  }
  glyphLut[0] = glyphs.findIndex(glyph => glyph.lo === 0 && glyph.hi === 0);
  glyphLut[glyphLut.length - 1] = glyphs.findIndex(glyph => glyph.lo === 0xffffffff && glyph.hi === 0xffffffff);

  const firstSample = new Uint8Array(256);
  let first = 0;
  for (let y = 0; y < 256; y++) {
    while (first < SAMPLE_Y.length && SAMPLE_Y[first] < y) first++;
    firstSample[y] = first;
  }
  const MaskArray = bits === 8 ? Uint8Array : Uint16Array;
  const leftMasks = new MaskArray(24), rightMasks = new MaskArray(24), fullMasks = new MaskArray(3);
  for (let row = 0; row < 3; row++) for (let sub = 0; sub < 8; sub++) for (let column = 0; column < 3; column++) {
    const bit = sampleBit(row, column, bits);
    if (SAMPLE_OFFSETS[column] >= sub) leftMasks[row * 8 + sub] |= bit;
    if (SAMPLE_OFFSETS[column] < sub) rightMasks[row * 8 + sub] |= bit;
    fullMasks[row] |= bit;
  }
  const ratioQ = new Uint8Array(4096), ratioR = new Uint8Array(4096);
  for (let dy = 1; dy < 64; dy++) for (let dx = 0; dx < 64; dx++) {
    ratioQ[dy * 64 + dx] = Math.floor(dx / dy);
    ratioR[dy * 64 + dx] = dx % dy;
  }
  const rowOffsetLo = Uint8Array.from({ length: 75 }, (_, i) => (Math.floor(i / 3) * WIDTH) & 255);
  const rowOffsetHi = Uint8Array.from({ length: 75 }, (_, i) => (Math.floor(i / 3) * WIDTH) >>> 8);
  const ratioRowLo = Uint8Array.from({ length: 64 }, (_, i) => (i * 64) & 255);
  const ratioRowHi = Uint8Array.from({ length: 64 }, (_, i) => (i * 64) >>> 8);
  return { bits, glyphLut, lut: glyphLut, signatures, sampleY: SAMPLE_Y, sampleGap: SAMPLE_GAP,
    firstSample, leftMasks, rightMasks, fullMasks, ratioQ, ratioR, rowOffsetLo, rowOffsetHi, ratioRowLo, ratioRowHi };
}

function rasterize(projectedX, projectedY, faces, options = {}) {
  const tables = options.tables;
  if (!tables) throw new Error('Pass tables from buildTables(font) to rasterize().');
  const coverage = tables.bits === 9 ? new Uint16Array(1000) : new Uint8Array(1000);
  const left = new Uint8Array(75), right = new Uint8Array(75);
  const ops = { polygons: 0, edges: 0, edgeSamples: 0, ddaSteps: 0, sampleSpans: 0,
    coverageClears: 1000, boundClears: 0, coverageWrites: 0, fullCharWrites: 0, boundaryCharWrites: 0, fontLookups: 1000 };
  function write(index, mask, full) {
    if (!mask) return;
    coverage[index] |= mask;
    ops.coverageWrites++;
    if (full) ops.fullCharWrites++;
    else ops.boundaryCharWrites++;
  }
  // Faces are already selected for white material and front-facing orientation.
  for (let faceIndex = 0; faceIndex < faces.length; faceIndex++) {
    const record = faces[faceIndex];
    if (record.color === 0 || record.visible === false || (options.frontFaces && !options.frontFaces[faceIndex])) continue;
    const face = Array.isArray(record) || ArrayBuffer.isView(record) ? record : record.indices;
    if (face.length < 3 || face.length > 6) throw new Error('Native raster accepts convex polygons with 3..6 vertices.');
    let minY = 255, maxY = 0;
    for (const vertex of face) {
      const x = projectedX[vertex], y = projectedY[vertex];
      if (!Number.isInteger(x) || !Number.isInteger(y) || x < 0 || x > 255 || y < 0 || y > 255) throw new Error('Projected coordinates must be unsigned Q3-char bytes.');
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
    const start = tables.firstSample[minY], end = tables.firstSample[maxY];
    if (start === end) continue;
    ops.polygons++;
    left.fill(255, start, end); right.fill(0, start, end);
    ops.boundClears += (end - start) * 2;
    for (let edge = 0; edge < face.length; edge++) {
      const a = face[edge], b = face[(edge + 1) % face.length];
      let x0 = projectedX[a], y0 = projectedY[a], x1 = projectedX[b], y1 = projectedY[b];
      if (y0 === y1) continue;
      if (y0 > y1) { [x0, x1] = [x1, x0]; [y0, y1] = [y1, y0]; }
      const dx = Math.abs(x1 - x0), dy = y1 - y0, direction = x1 < x0 ? -1 : 1;
      if (dx > 63 || dy > 63) throw new Error('Edge exceeds the native 64×64 ratio table.');
      const q = tables.ratioQ[dy * 64 + dx], r = tables.ratioR[dy * 64 + dx];
      const edgeStart = tables.firstSample[y0], edgeEnd = tables.firstSample[y1];
      if (edgeStart === edgeEnd) continue;
      let x = x0, remainder = 0;
      function step(count) {
        x += direction * q * count;
        remainder += r * count;
        while (remainder >= dy) { remainder -= dy; x += direction; }
        ops.ddaSteps += count;
      }
      step(tables.sampleY[edgeStart] - y0);
      ops.edges++;
      for (let sample = edgeStart; sample < edgeEnd; sample++) {
        const ceilX = x + Number(direction > 0 && remainder !== 0);
        left[sample] = Math.min(left[sample], ceilX);
        right[sample] = Math.max(right[sample], ceilX);
        ops.edgeSamples++;
        if (sample + 1 < edgeEnd) step(tables.sampleGap[sample]);
      }
    }
    for (let sample = start; sample < end; sample++) {
      const l = left[sample], r = right[sample];
      if (r <= l) continue;
      const sampleRow = sample % 3, row = Math.floor(sample / 3) * WIDTH;
      const lc = l >>> 3, rc = r >>> 3;
      const leftMask = tables.leftMasks[sampleRow * 8 + (l & 7)];
      const rightMask = tables.rightMasks[sampleRow * 8 + (r & 7)];
      ops.sampleSpans++;
      if (lc === rc) write(row + lc, leftMask & rightMask, false);
      else {
        write(row + lc, leftMask, false);
        for (let column = lc + 1; column < rc; column++) write(row + column, tables.fullMasks[sampleRow], true);
        write(row + rc, rightMask, false);
      }
    }
  }
  const screen = Uint8Array.from(coverage, signature => tables.glyphLut[signature]);
  return { coverage, screen, ops };
}

module.exports = { WIDTH, HEIGHT, SAMPLE_OFFSETS, sampleBit, buildTables, rasterize };
