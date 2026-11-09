(function (root) {
  'use strict';

  const SINGLE_ANGLES = 64, SINGLE_OFFSETS = 49, SINGLE_STEP = 0.25;
  const PAIR_ANGLES = 8, PAIR_OFFSETS = 9, PAIR_STEP = 1.25;
  const HALF_STATES = PAIR_ANGLES * PAIR_OFFSETS;
  const FULL_STATES = 2 * HALF_STATES;
  const singleThresholds = Float64Array.from([1, 3, 5, 7, 9, 11, 13, 15], n => Math.tan(n * Math.PI / 64));
  const pairThresholds = Float64Array.from([1, 3], n => Math.tan(n * Math.PI / 16));
  const thresholdBytes = singleThresholds.byteLength + pairThresholds.byteLength;
  const cache = new WeakMap();
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const triangle = count => count * (count + 1) / 2;
  function pairIndex(a, b) { return a < b ? b * (b + 1) / 2 + a : a * (a + 1) / 2 + b; }

  function mathematicalMask(angle, offset) {
    const nx = Math.cos(angle), ny = Math.sin(angle);
    let lo = 0, hi = 0;
    for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
      if (nx * (x - 3.5) + ny * (y - 3.5) < offset) continue;
      const bit = y * 8 + x;
      if (bit < 32) lo |= 1 << bit;
      else hi |= 1 << (bit - 32);
    }
    return { lo: lo >>> 0, hi: hi >>> 0 };
  }

  function makeTables(font) {
    if (cache.has(font)) return cache.get(font);
    const single = new Uint8Array(SINGLE_ANGLES * SINGLE_OFFSETS);
    const xor = new Uint8Array(2 * triangle(HALF_STATES));
    const and = new Uint8Array(triangle(FULL_STATES));
    const pairMasks = [];
    // This scene-independent setup is the only place that samples 64 pixels
    // or searches the font. Runtime receives geometric descriptors, not masks.
    const nearest = (lo, hi) => root.GlyphMath.nearestGlyph(lo >>> 0, hi >>> 0, font).index;
    for (let a = 0; a < SINGLE_ANGLES; a++) for (let d = 0; d < SINGLE_OFFSETS; d++) {
      const mask = mathematicalMask(a * 2 * Math.PI / SINGLE_ANGLES, (d - 24) * SINGLE_STEP);
      single[a * SINGLE_OFFSETS + d] = nearest(mask.lo, mask.hi);
    }
    for (let a = 0; a < PAIR_ANGLES * 2; a++) for (let d = 0; d < PAIR_OFFSETS; d++) {
      pairMasks.push(mathematicalMask(a * Math.PI / PAIR_ANGLES, (d - 4) * PAIR_STEP));
    }
    for (let b = 0; b < HALF_STATES; b++) for (let a = 0; a <= b; a++) {
      const lo = pairMasks[a].lo ^ pairMasks[b].lo, hi = pairMasks[a].hi ^ pairMasks[b].hi;
      const index = pairIndex(a, b) * 2;
      xor[index] = nearest(lo, hi);
      xor[index + 1] = nearest(~lo, ~hi);
    }
    for (let b = 0; b < FULL_STATES; b++) for (let a = 0; a <= b; a++) {
      and[pairIndex(a, b)] = nearest(pairMasks[a].lo & pairMasks[b].lo, pairMasks[a].hi & pairMasks[b].hi);
    }
    const tables = { single, xor, and, bytes: single.byteLength + xor.byteLength + and.byteLength };
    cache.set(font, tables);
    return tables;
  }

  function sector(line, count, thresholds, ops) {
    const ax = Math.abs(line.nx), ay = Math.abs(line.ny);
    const swapped = ay > ax, major = swapped ? ay : ax, minor = swapped ? ax : ay;
    let value = 0;
    // Folding into one octant permits exact angular-sector decisions using
    // only comparisons and products. No per-tile trigonometry or division.
    for (const threshold of thresholds) {
      ops.angleTests++;
      if (minor >= major * threshold) value++;
    }
    if (swapped) value = count / 4 - value;
    if (line.nx < 0) value = count / 2 - value;
    if (line.ny < 0) value = count - value;
    return value % count;
  }

  function orientedState(line, inverted, ops) {
    let a = sector(line, PAIR_ANGLES * 2, pairThresholds, ops), d = line.d;
    if (inverted) { a = (a + PAIR_ANGLES) % (2 * PAIR_ANGLES); d = -d; }
    const offset = clamp(Math.round(d / PAIR_STEP) + 4, 0, PAIR_OFFSETS - 1);
    return a * PAIR_OFFSETS + offset;
  }

  function halfState(line, ops) {
    let a = sector(line, PAIR_ANGLES * 2, pairThresholds, ops);
    let d = line.d, flip = 0;
    if (a >= PAIR_ANGLES) { a -= PAIR_ANGLES; d = -d; flip = 1; }
    return { index: a * PAIR_OFFSETS + clamp(Math.round(d / PAIR_STEP) + 4, 0, PAIR_OFFSETS - 1), flip };
  }

  function preparePlane(plane, camera, focal) {
    const a = camera * camera - 1, b = plane.c - camera * plane.nz;
    return {
      ...plane, a, b,
      xx: (a * plane.nx * plane.nx + b * b) / (focal * focal),
      yy: (a * plane.ny * plane.ny + b * b) / (focal * focal),
      xy: -2 * a * plane.nx * plane.ny / (focal * focal)
    };
  }

  function conicMayCross(plane, tile, scene) {
    const u = (tile.cx - 160) / scene.focal, v = (100 - tile.cy) / scene.focal;
    const q = plane.nx * u + plane.ny * v - plane.nz;
    const value = plane.a * q * q - 2 * scene.camera * plane.b * q + plane.b * plane.b * (1 + u * u + v * v);
    const gx = (2 * plane.a * q * plane.nx - 2 * scene.camera * plane.b * plane.nx + 2 * plane.b * plane.b * u) / scene.focal;
    const gy = -(2 * plane.a * q * plane.ny - 2 * scene.camera * plane.b * plane.ny + 2 * plane.b * plane.b * v) / scene.focal;
    // A quadratic's absolute variation on [-3.5,3.5]^2 has this conservative
    // bound. It can admit hidden rear arcs; the local visible tangent filters
    // distant ones below. Curvature and multiple crossings remain approximate.
    const bound = 3.5 * (Math.abs(gx) + Math.abs(gy)) + 12.25 * (Math.abs(plane.xx) + Math.abs(plane.yy) + Math.abs(plane.xy));
    return Math.abs(value) <= bound + 1e-12;
  }

  function derivatives(point, scene) {
    const t = scene.camera - point.pz;
    const denominator = 1 - scene.camera * point.pz;
    if (Math.abs(denominator) < 1e-10) return null;
    const tx = -t * t * point.px / (scene.focal * denominator);
    const ty = t * t * point.py / (scene.focal * denominator);
    const vx = point.px / t, vy = point.py / t;
    return {
      xx: t / scene.focal + tx * vx, xy: tx * vy, xz: -tx,
      yx: ty * vx, yy: -t / scene.focal + ty * vy, yz: -ty
    };
  }

  function create(font) {
    const tables = makeTables(font);
    function singleGlyph(line, inverted, ops) {
      let a = sector(line, SINGLE_ANGLES, singleThresholds, ops), d = line.d;
      if (inverted) { a = (a + SINGLE_ANGLES / 2) % SINGLE_ANGLES; d = -d; }
      const offset = clamp(Math.round(d / SINGLE_STEP) + 24, 0, SINGLE_OFFSETS - 1);
      ops.tableReads++;
      return tables.single[a * SINGLE_OFFSETS + offset];
    }

    return {
      name: 'Koniska gränser och tangenttabell',
      tableBytes: tables.bytes + thresholdBytes,
      glyphTableBytes: tables.bytes,
      thresholdBytes,
      render(state) {
        const scene = root.DirectCore.createScene(state), screen = new Uint8Array(1000), ops = scene.ops;
        Object.assign(ops, { conicTests: 0, tangentTests: 0, angleTests: 0, fullTiles: 0, lineTiles: 0, pairTiles: 0, complexTiles: 0 });
        const planes = state.solid ? [] : scene.planes.map(plane => preparePlane(plane, scene.camera, scene.focal));
        for (const index of scene.tiles) {
          const tile = scene.tile(index);
          let ax = tile.cx, ay = tile.cy, point = scene.point(ax, ay);
          if (!point) {
            ax = clamp(160, tile.x + 0.5, tile.x + 7.5);
            ay = clamp(100, tile.y + 0.5, tile.y + 7.5);
            point = scene.point(ax, ay);
          }
          if (!point) continue;
          const derivative = derivatives(point, scene), lines = [];
          let anchorBit = 1;
          ops.samples++;
          for (const plane of planes) {
            const h = plane.nx * point.px + plane.ny * point.py + plane.nz * point.pz - plane.c;
            ops.planeTests++;
            anchorBit ^= Number(h >= 0);
            ops.conicTests++;
            if (!derivative || !conicMayCross(plane, tile, scene)) continue;
            const gx = plane.nx * derivative.xx + plane.ny * derivative.xy + plane.nz * derivative.xz;
            const gy = plane.nx * derivative.yx + plane.ny * derivative.yy + plane.nz * derivative.yz;
            const length = Math.hypot(gx, gy);
            if (length < 1e-10) continue;
            const nx = gx / length, ny = gy / length;
            const d = -(h + gx * (tile.cx - ax) + gy * (tile.cy - ay)) / length;
            const support = 3.5 * (Math.abs(nx) + Math.abs(ny));
            ops.tangentTests++;
            // The conic test is conservative; this tangent-distance rejection
            // is deliberately approximate, especially near poles and the rim.
            if (Math.abs(d) > support + 1.5) continue;
            lines.push({ nx, ny, d, anchor: Number(h >= 0), score: Math.abs(d) / support });
          }
          lines.sort((a, b) => a.score - b.score);
          if (lines.length > 2) ops.complexTiles++;
          if (tile.status === 'edge') {
            const dx = tile.cx - 160, dy = tile.cy - 100, length = 2 * Math.hypot(dx, dy);
            const rim = { nx: -2 * dx / length, ny: -2 * dy / length, d: -(state.radius * state.radius - dx * dx - dy * dy) / length };
            if (lines.length) {
              const checker = lines[0], inverted = anchorBit ^ checker.anchor;
              const a = orientedState(rim, false, ops), b = orientedState(checker, inverted, ops);
              ops.tableReads++; ops.pairTiles++;
              screen[index] = tables.and[pairIndex(a, b)];
              if (lines.length === 2) ops.complexTiles++;
            } else if (anchorBit) {
              screen[index] = singleGlyph(rim, false, ops); ops.lineTiles++;
            }
          } else if (lines.length >= 2) {
            const a = halfState(lines[0], ops), b = halfState(lines[1], ops);
            const polarity = anchorBit ^ lines[0].anchor ^ lines[1].anchor ^ a.flip ^ b.flip;
            ops.tableReads++; ops.pairTiles++;
            screen[index] = tables.xor[pairIndex(a.index, b.index) * 2 + polarity];
          } else if (lines.length === 1) {
            screen[index] = singleGlyph(lines[0], anchorBit ^ lines[0].anchor, ops); ops.lineTiles++;
          } else {
            screen[index] = anchorBit ? 15 : 0; ops.fullTiles++;
          }
        }
        const silhouette = root.DirectCore.constrainToSilhouette(screen, font, state.radius);
        Object.assign(ops, {
          silhouetteLookups: silhouette.lookups, silhouetteChanges: silhouette.changes,
          silhouetteTableBytes: silhouette.tableBytes, silhouetteIndexBytes: silhouette.indexBytes
        });
        return { screen, ops };
      }
    };
  }

  root.DirectMethods = root.DirectMethods || {};
  root.DirectMethods.conics = { create };
  if (typeof module !== 'undefined') module.exports = root.DirectMethods.conics;
})(typeof window !== 'undefined' ? window : globalThis);
