(function (root) {
  'use strict';

  const EDGE_ANGLES = 64;
  const EDGE_OFFSETS = 41;
  const CROSS_ANGLES = 8;
  const CROSS_OFFSETS = [-4, -2, 0, 2, 4];
  const TAU = Math.PI * 2;
  const cache = new WeakMap();

  // All masks and Hamming searches below belong to font-table construction.
  // Runtime sees only quantized geometric parameters and byte table reads.
  function idealMask(predicate) {
    let lo = 0, hi = 0;
    for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
      if (!predicate(x - 3.5, y - 3.5)) continue;
      const bit = y * 8 + x;
      if (bit < 32) lo |= 1 << bit;
      else hi |= 1 << (bit - 32);
    }
    return [lo >>> 0, hi >>> 0];
  }

  function buildTables(font) {
    if (cache.has(font)) return cache.get(font);
    const edges = new Uint8Array(EDGE_ANGLES * EDGE_OFFSETS);
    const crossings = new Uint8Array(2 * CROSS_ANGLES * CROSS_ANGLES * 25);
    for (let a = 0; a < EDGE_ANGLES; a++) {
      const nx = Math.cos(a * TAU / EDGE_ANGLES);
      const ny = Math.sin(a * TAU / EDGE_ANGLES);
      for (let p = 0; p < EDGE_OFFSETS; p++) {
        const d = p / 4 - 5;
        const [lo, hi] = idealMask((x, y) => nx * x + ny * y >= d);
        edges[a * EDGE_OFFSETS + p] = root.GlyphMath.nearestGlyph(lo, hi, font).index;
      }
    }
    for (let a = 0; a < CROSS_ANGLES; a++) for (let b = 0; b < CROSS_ANGLES; b++) {
      const ax = Math.cos(a * TAU / CROSS_ANGLES), ay = Math.sin(a * TAU / CROSS_ANGLES);
      const bx = Math.cos(b * TAU / CROSS_ANGLES), by = Math.sin(b * TAU / CROSS_ANGLES);
      for (let p = 0; p < 5; p++) for (let q = 0; q < 5; q++) {
        const [lo, hi] = idealMask((x, y) => (ax * x + ay * y >= CROSS_OFFSETS[p]) !== (bx * x + by * y >= CROSS_OFFSETS[q]));
        const index = ((a * CROSS_ANGLES + b) * 5 + p) * 5 + q;
        crossings[index] = root.GlyphMath.nearestGlyph(lo, hi, font).index;
        crossings[index + 1600] = root.GlyphMath.nearestGlyph((~lo) >>> 0, (~hi) >>> 0, font).index;
      }
    }
    const tables = { edges, crossings };
    cache.set(font, tables);
    return tables;
  }

  function angleIndex(nx, ny, count) {
    return ((Math.round(Math.atan2(ny, nx) * count / TAU) % count) + count) % count;
  }

  function create(font) {
    const tables = buildTables(font);

    function render(state) {
      const scene = root.DirectCore.createScene(state);
      const screen = new Uint8Array(1000);
      const counters = { uvQueries: 0, tableReads: 0, constantTiles: 0, edgeTiles: 0, crossingTiles: 0, limbTiles: 0, fallbackTiles: 0, angleQueries: 0 };
      const sy = Math.sin(state.angle), cy = Math.cos(state.angle);
      const pitch = state.tilt * Math.PI / 180, sx = Math.sin(pitch), cx = Math.cos(pitch);
      const scale = state.checks / TAU;
      function uvAt(x, y) { counters.uvQueries++; return scene.uvAt(x, y); }
      function valid(uv) { return uv && uv.inside !== false && Number.isFinite(uv.u) && Number.isFinite(uv.v); }
      function parity(uv) { return (Math.floor(uv.u) ^ Math.floor(uv.v)) & 1; }
      function edgeGlyph(nx, ny, d) {
        counters.angleQueries++;
        const a = angleIndex(nx, ny, EDGE_ANGLES);
        const p = Math.max(0, Math.min(EDGE_OFFSETS - 1, Math.round((d + 5) * 4)));
        counters.tableReads++;
        return tables.edges[a * EDGE_OFFSETS + p];
      }
      function fourQuadrants(tile, probes) {
        let mask = 0;
        const points = probes || [uvAt(tile.x + 2, tile.y + 2), uvAt(tile.x + 6, tile.y + 2), uvAt(tile.x + 2, tile.y + 6), uvAt(tile.x + 6, tile.y + 6)];
        for (let q = 0; q < 4; q++) if (valid(points[q]) && parity(points[q])) mask |= 1 << q;
        counters.fallbackTiles++;
        // The fixed font's first sixteen slots are the four-quadrant baseline.
        return mask;
      }
      function limb(tile) {
        counters.limbTiles++;
        const dx = tile.cx - 160, dy = tile.cy - 100;
        const distance = Math.hypot(dx, dy);
        const nx = -dx / Math.max(distance, 1e-9), ny = -dy / Math.max(distance, 1e-9);
        const d = distance - state.radius;
        if (state.solid) return edgeGlyph(nx, ny, d);
        const probes = [uvAt(tile.x + 2, tile.y + 2), uvAt(tile.x + 6, tile.y + 2), uvAt(tile.x + 2, tile.y + 6), uvAt(tile.x + 6, tile.y + 6)];
        let seen = -1, mixed = false;
        for (const probe of probes) if (valid(probe)) {
          const value = parity(probe);
          if (seen === -1) seen = value;
          else if (value !== seen) mixed = true;
        }
        if (mixed) return fourQuadrants(tile, probes);
        if (seen === -1) {
          const radialScale = (state.radius - 0.3) / Math.max(distance, 1e-9);
          const anchor = uvAt(160 + dx * radialScale, 100 + dy * radialScale);
          seen = valid(anchor) ? parity(anchor) : 0;
        }
        return seen ? edgeGlyph(nx, ny, d) : 0;
      }
      function derivatives(center, tile) {
        // Differentiate P=C+t*r and P·P=1. This needs no extra surface probes.
        const px = center.px, py = center.py, pz = center.pz;
        const ru = (tile.cx - 160) / scene.focal, rv = (100 - tile.cy) / scene.focal;
        const t = scene.camera - pz, denominator = px * ru + py * rv - pz;
        const x = cy * px - sy * pz;
        const y = sx * sy * px + cx * py + sx * cy * pz;
        const z = cx * sy * px - sx * py + cx * cy * pz;
        const longitudeDenominator = x * x + z * z;
        const latitudeDenominator = Math.sqrt(Math.max(0, 1 - y * y));
        if (Math.abs(denominator) < 1e-8 || longitudeDenominator < 1e-8 || latitudeDenominator < 1e-8) return null;
        const tx = -t * px / (scene.focal * denominator);
        const ty = t * py / (scene.focal * denominator);
        function direction(dt, dx, dy) {
          const ax = dt * ru + dx, ay = dt * rv + dy, az = -dt;
          const ox = cy * ax - sy * az;
          const oy = sx * sy * ax + cx * ay + sx * cy * az;
          const oz = cx * sy * ax - sx * ay + cx * cy * az;
          return {
            u: scale * (z * ox - x * oz) / longitudeDenominator,
            v: scale * oy / latitudeDenominator
          };
        }
        return { dx: direction(tx, t / scene.focal, 0), dy: direction(ty, 0, -t / scene.focal) };
      }
      function boundary(value, gx, gy) {
        const range = 3.5 * (Math.abs(gx) + Math.abs(gy));
        const low = Math.floor(value - range), high = Math.floor(value + range);
        if (low === high) return null;
        if (high - low > 1) return { complex: true };
        const k = high, length = Math.hypot(gx, gy);
        if (length < 1e-10) return { complex: true };
        return { k, nx: gx / length, ny: gy / length, d: (k - value) / length };
      }

      for (const index of scene.tiles) {
        const tile = scene.tile(index);
        if (tile.status !== 'inside') { screen[index] = limb(tile); continue; }
        if (state.solid) { screen[index] = 15; counters.constantTiles++; continue; }
        const center = uvAt(tile.cx, tile.cy);
        const gradient = valid(center) ? derivatives(center, tile) : null;
        if (!gradient) { screen[index] = fourQuadrants(tile); continue; }
        const u = boundary(center.u, gradient.dx.u, gradient.dy.u);
        const v = boundary(center.v, gradient.dx.v, gradient.dy.v);
        if ((u && u.complex) || (v && v.complex)) { screen[index] = fourQuadrants(tile); continue; }
        if (!u && !v) { screen[index] = parity(center) ? 15 : 0; counters.constantTiles++; continue; }
        if (u && v) {
          const a = angleIndex(u.nx, u.ny, CROSS_ANGLES), b = angleIndex(v.nx, v.ny, CROSS_ANGLES);
          const p = Math.max(0, Math.min(4, Math.round((u.d + 4) / 2)));
          const q = Math.max(0, Math.min(4, Math.round((v.d + 4) / 2)));
          const inverse = (u.k ^ v.k) & 1;
          screen[index] = tables.crossings[(((a * CROSS_ANGLES + b) * 5 + p) * 5 + q) + inverse * 1600];
          counters.tableReads++; counters.angleQueries += 2; counters.crossingTiles++;
        } else {
          const line = u || v;
          const other = u ? Math.floor(center.v) : Math.floor(center.u);
          const whitePositive = (line.k ^ other) & 1;
          const sign = whitePositive ? 1 : -1;
          screen[index] = edgeGlyph(line.nx * sign, line.ny * sign, line.d * sign);
          counters.edgeTiles++;
        }
      }
      const silhouette = root.DirectCore.constrainToSilhouette(screen, font, state.radius);
      return { screen, ops: {
        ...scene.ops, ...counters,
        silhouetteLookups: silhouette.lookups, silhouetteChanges: silhouette.changes,
        silhouetteTableBytes: silhouette.tableBytes, silhouetteIndexBytes: silhouette.indexBytes
      }, scene };
    }

    return {
      name: 'Lokal UV-gradient',
      tableBytes: tables.edges.byteLength + tables.crossings.byteLength,
      description: 'Ett analytiskt UV-prov och exakta lokala derivator ger kantlinjer. Vinkel och läge väljer tecken direkt ur en 5 824-byte-tabell.',
      render
    };
  }

  root.DirectMethods = root.DirectMethods || {};
  root.DirectMethods.gradient = { create };
  if (typeof module !== 'undefined' && module.exports) module.exports = { create };
})(typeof window !== 'undefined' ? window : globalThis);
