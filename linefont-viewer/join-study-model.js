/* Fixed-point mirror of mydemo/linedrawer/{cube_model,ball_model}.py. */
(function (root) {
  "use strict";

  const width = 160;
  const height = 100;
  const columns = width / 4;
  const cellCount = columns * height / 4;
  const patchLimit = 55;

  function rotateCube(vertices, sine, angles) {
    const [sy, sp, sr] = angles.map(phase => sine[phase & 255]);
    const [cy, cp, cr] = angles.map(phase => sine[(phase + 64) & 255]);
    return vertices.map(([x, y, z]) => {
      const x1 = (x * cy + z * sy) >> 8;
      const z1 = (z * cy - x * sy) >> 8;
      const y1 = (y * cp - z1 * sp) >> 8;
      const z2 = (y * sp + z1 * cp) >> 8;
      return [(x1 * cr - y1 * sr) >> 8, (x1 * sr + y1 * cr) >> 8, z2];
    });
  }

  function rotateBall(half, sine, angles) {
    const [sy, sp, sr] = angles.map(phase => (sine[phase & 255] + 2) >> 2);
    const [cy, cp, cr] = angles.map(phase => (sine[(phase + 64) & 255] + 2) >> 2);
    const mul = (a, b) => (a * b) >> 6;
    const clampQ6 = value => Math.max(-64, Math.min(64, value));
    const yx = mul(sp, sy);
    const yz = -mul(sp, cy);
    const matrix = [
      [clampQ6(mul(cr, cy) - mul(sr, yx)), -mul(sr, cp), clampQ6(mul(cr, sy) - mul(sr, yz))],
      [clampQ6(mul(sr, cy) + mul(cr, yx)), mul(cr, cp), clampQ6(mul(sr, sy) + mul(cr, yz))],
      [-mul(cp, sy), sp, mul(cp, cy)],
    ];
    const rotated = half.map(([x, y, z]) => matrix.map(([a, b, c]) => (x * a + y * b + z * c) >> 4));
    // The second half uses the negated, already-rounded coordinates.
    return rotated.concat(rotated.map(point => point.map(value => -value)));
  }

  function project(data, mesh, n) {
    const angles = data.initialAngles.map((phase, axis) => phase + n * data.angleSteps[axis]);
    const [tx, ty, tz] = data.motionPhases.map((phase, axis) => {
      const angle = (phase + n * data.motionSteps[axis]) & 255;
      return (data.sine[angle] * mesh.motionAmplitudes[axis]) >> 8;
    });
    const vertices = mesh.precision === 8
      ? rotateCube(mesh.vertices, data.sine, angles)
      : rotateBall(mesh.vertices, data.sine, angles);

    return vertices.map(([x, y, z]) => {
      const depth = Math.max(data.depthMin, Math.min(data.depthMax, mesh.cameraDepth + tz + z));
      const reciprocal = depth <= data.depthNearMax
        ? data.reciprocal[depth - data.depthMin]
        : data.farReciprocal[Math.floor(depth / data.farBin) - data.farFirst];
      const px = ((x + tx) * reciprocal + 32768) >> 16;
      const py = ((y + ty) * reciprocal + 32768) >> 16;
      return [width / 2 + px, height / 2 - py];
    });
  }

  function faceIsVisible(points, [a, b, c, d]) {
    const [x0, y0] = points[a];
    const [x1, y1] = points[b];
    const [x2, y2] = points[c];
    const [x3, y3] = points[d];
    return (x2 - x0) * (y3 - y1) - (y2 - y0) * (x3 - x1) > 0;
  }

  function ratio(numerator, denominator) {
    return denominator > 0 ? [numerator, denominator] : [-numerator, -denominator];
  }

  function compareRatio([a, b], [c, d]) {
    return a * d - c * b;
  }

  function clipSegment(start, end) {
    const delta = [end[0] - start[0], end[1] - start[1]];
    const limits = [width - 1, height - 1];
    let enter = [0, 1];
    let leave = [1, 1];

    for (let axis = 0; axis < 2; axis++) {
      const coordinate = start[axis];
      const step = delta[axis];
      const limit = limits[axis];
      if (step === 0) {
        if (coordinate < 0 || coordinate > limit) return null;
        continue;
      }
      const low = ratio(-coordinate, step);
      const high = ratio(limit - coordinate, step);
      const [near, far] = step > 0 ? [low, high] : [high, low];
      if (compareRatio(near, enter) > 0) enter = near;
      if (compareRatio(far, leave) < 0) leave = far;
      if (compareRatio(enter, leave) > 0) return null;
    }

    // Keep clipping ratios exact until the half-up endpoint rounding.
    return [enter, leave].flatMap(([num, den]) => start.map((coordinate, axis) => {
      const scaled = coordinate * den + delta[axis] * num;
      return Math.floor((2 * scaled + den) / (2 * den));
    }));
  }

  function cellIndex(x, y) {
    return (y >> 2) * columns + (x >> 2);
  }

  function normalizedCells([x0, y0, x1, y1]) {
    const dx = Math.abs(x1 - x0);
    const dy = Math.abs(y1 - y0);
    const sx = x1 < x0 ? -1 : 1;
    const sy = y1 < y0 ? -1 : 1;
    const yMajor = dy > dx;
    const major = yMajor ? dy : dx;
    const minor = yMajor ? dx : dy;
    const rate = major ? Math.floor((512 * minor + major) / (2 * major)) : 0;
    const cells = new Map();
    for (let step = 0; step <= major; step++) {
      const offset = (128 + step * rate) >> 8;
      const x = x0 + sx * (yMajor ? offset : step);
      const y = y0 + sy * (yMajor ? step : offset);
      const key = cellIndex(x, y);
      const bit = 1 << ((y & 3) * 4 + (x & 3));
      cells.set(key, (cells.get(key) || 0) | bit);
    }
    return cells;
  }

  function collectVertices(points, incidentEdges, edgeCells) {
    const vertexDegree = new Uint8Array(cellCount);
    const vertexMasks = new Uint16Array(cellCount);

    for (let vertex = 0; vertex < points.length; vertex++) {
      const [x, y] = points[vertex];
      if (x < 0 || x >= width || y < 0 || y >= height) continue;
      const key = cellIndex(x, y);
      let degree = 0;
      let mask = 0;
      for (const edge of incidentEdges[vertex]) {
        const arm = edgeCells[edge]?.get(key);
        if (arm === undefined) continue;
        degree++;
        mask |= arm;
      }
      if (degree < 2) continue;
      vertexDegree[key] = Math.max(vertexDegree[key], degree);
      vertexMasks[key] |= mask;
    }

    return {vertexDegree, vertexMasks};
  }

  function frame(data, shape, n) {
    const mesh = data.shapes[shape];
    const points = project(data, mesh, n);
    const faces = mesh.faces.map(face => faceIsVisible(points, face));
    const bank = new Set(data.bank);
    const patches = new Set();
    const edgeCells = new Array(mesh.edges.length);
    const masks = new Uint16Array(cellCount);
    const legacyMasks = new Uint16Array(cellCount);
    const contributions = new Uint8Array(cellCount);
    const stampMasks = [];

    for (let edge = 0; edge < mesh.edges.length; edge++) {
      const [left, right] = mesh.edgeFaces[edge];
      if (!faces[left] && !faces[right]) continue;
      const [a, b] = mesh.edges[edge];
      const segment = clipSegment(points[a], points[b]);
      if (!segment) continue;
      const cells = normalizedCells(segment);
      edgeCells[edge] = cells;

      for (const [key, mask] of cells) {
        masks[key] |= mask;
        contributions[key]++;
        stampMasks.push(mask);
        const merged = legacyMasks[key] | mask;
        if (bank.has(merged) || patches.has(merged)) {
          legacyMasks[key] = merged;
        } else if (patches.size < patchLimit) {
          patches.add(merged);
          legacyMasks[key] = merged;
        } else {
          legacyMasks[key] = mask;
        }
      }
    }

    const vertices = collectVertices(points, mesh.incidentEdges, edgeCells);
    return {masks, contributions, ...vertices, stampMasks, legacyPatches: patches.size};
  }

  const api = {frame};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JoinStudyModel = api;
})(globalThis);
