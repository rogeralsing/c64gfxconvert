'use strict';

// Offline geometry inputs for the large-sphere native benchmarks. Runtime
// renderers receive integer vertices or per-face spans, never reference pixels.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const raster = require('../../raster.cjs');
const {generateFont, toBytes} = require('../font.cjs');

const OUTPUT = path.join(__dirname, 'build/geometry');
const SETTINGS = Object.freeze({width: 320, height: 200, columns: 40, rows: 25,
  radius: 145, diameter: 290, checks: 20, bands: 10, tilt: 65, camera: 3.2,
  initialAngle: 0.38, frames: 384, stepDegrees: 0.9375});
const SAMPLE_OFFSETS = [1, 4, 6];
const SAMPLE_Y = Array.from({length: 75}, (_, index) => Math.floor(index / 3) * 8 + SAMPLE_OFFSETS[index % 3]);
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const popcount8 = value => value.toString(2).replace(/0/g, '').length;
const summarize = values => ({min: Math.min(...values), mean: values.reduce((sum, value) => sum + value, 0) / values.length, max: Math.max(...values)});

function mesh() {
  const vertices = [[0, -1, 0]];
  const index = (row, column) => row === 0 ? 0 : row === SETTINGS.bands ? vertices.length - 1 : 1 + (row - 1) * SETTINGS.checks + ((column % SETTINGS.checks) + SETTINGS.checks) % SETTINGS.checks;
  for (let row = 1; row < SETTINGS.bands; row++) {
    const latitude = -Math.PI / 2 + row * Math.PI / SETTINGS.bands;
    for (let column = 0; column < SETTINGS.checks; column++) {
      const longitude = -Math.PI + column * 2 * Math.PI / SETTINGS.checks;
      vertices.push([Math.cos(latitude) * Math.sin(longitude), Math.sin(latitude), Math.cos(latitude) * Math.cos(longitude)]);
    }
  }
  vertices.push([0, 1, 0]);
  const faces = [];
  for (let row = 0; row < SETTINGS.bands; row++) for (let column = 0; column < SETTINGS.checks; column++) {
    const corners = [index(row, column), index(row, column + 1), index(row + 1, column + 1), index(row + 1, column)];
    let indices = corners.filter((value, i) => value !== corners[(i + corners.length - 1) % corners.length]);
    const points = indices.map(value => vertices[value]);
    const center = [0, 1, 2].map(axis => points.reduce((sum, point) => sum + point[axis], 0) / points.length);
    const a = points[0], b = points[1], c = points[2];
    const ab = b.map((value, axis) => value - a[axis]), ac = c.map((value, axis) => value - a[axis]);
    let normal = [ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0]];
    if (normal.reduce((sum, value, axis) => sum + value * center[axis], 0) < 0) {
      indices = indices.reverse();
      normal = normal.map(value => -value);
    }
    faces.push({id: faces.length, row, column, color: (row ^ column) & 1, indices, center, normal});
  }
  assert.equal(vertices.length, 182);
  assert.equal(faces.length, 200);
  assert.equal(faces.filter(face => face.indices.length === 3).length, 40);
  assert.equal(faces.filter(face => face.color).length, 100);
  return {vertices, faces, whiteFaces: faces.filter(face => face.color)};
}

function rotate(point, angle) {
  const [x, y, z] = point;
  const tilt = SETTINGS.tilt * Math.PI / 180;
  const sx = Math.sin(tilt), cx = Math.cos(tilt), sy = Math.sin(angle), cy = Math.cos(angle);
  const y1 = cx * y - sx * z, z1 = sx * y + cx * z;
  return [cy * x + sy * z1, y1, -sy * x + cy * z1];
}

function project(model, angle) {
  const focal = SETTINGS.radius * Math.sqrt(SETTINGS.camera ** 2 - 1);
  const world = model.vertices.map(vertex => rotate(vertex, angle));
  const xy = world.map(([x, y, z]) => [Math.round(160 + focal * x / (SETTINGS.camera - z)) || 0, Math.round(100 - focal * y / (SETTINGS.camera - z)) || 0]);
  const visible = model.whiteFaces.map(face => {
    const n = rotate(face.normal, angle), center = rotate(face.center, angle);
    return n[2] * SETTINGS.camera - n.reduce((sum, value, axis) => sum + value * center[axis], 0) > 1e-12;
  });
  return {xy, visible};
}

function faceSpans(indices, xy) {
  const points = indices.map(index => xy[index]);
  const minY = Math.min(...points.map(point => point[1])), maxY = Math.max(...points.map(point => point[1]));
  let first = SAMPLE_Y.findIndex(y => y >= minY);
  if (first === -1) return null;
  let end = first;
  while (end < SAMPLE_Y.length && SAMPLE_Y[end] < maxY) end++;
  if (first === end) return null;
  const spans = [];
  for (let sample = first; sample < end; sample++) {
    const y = SAMPLE_Y[sample], crossings = [];
    for (let edge = 0; edge < points.length; edge++) {
      let [x0, y0] = points[edge], [x1, y1] = points[(edge + 1) % points.length];
      if (y0 === y1) continue;
      if (y0 > y1) [x0, y0, x1, y1] = [x1, y1, x0, y0];
      if (y < y0 || y >= y1) continue;
      // All arithmetic before ceil is integer. This is the exact contract for
      // the native signed-edge walker, including slopes directed to the left.
      crossings.push(x0 + Math.ceil(((y - y0) * (x1 - x0)) / (y1 - y0)));
    }
    if (crossings.length < 2) { spans.push([0, 0]); continue; }
    const left = Math.max(0, Math.min(320, Math.min(...crossings)));
    const right = Math.max(0, Math.min(320, Math.max(...crossings)));
    spans.push(right > left ? [left, right] : [0, 0]);
  }
  if (!spans.some(([left, right]) => right > left)) return null;
  return {first, spans};
}

function fill(faces, tables) {
  const coverage = Buffer.alloc(1000);
  for (const face of faces) for (let offset = 0; offset < face.spans.length; offset++) {
    const [left, right] = face.spans[offset];
    if (right <= left) continue;
    const sample = face.first + offset, group = sample % 3, row = Math.floor(sample / 3) * 40;
    const lc = left >>> 3, rc = right >>> 3;
    const lm = tables.leftMasks[group * 8 + (left & 7)], rm = tables.rightMasks[group * 8 + (right & 7)];
    if (lc === rc) coverage[row + lc] |= lm & rm;
    else {
      if (lm && lc < 40) coverage[row + lc] |= lm;
      for (let column = lc + 1; column < rc; column++) coverage[row + column] |= tables.fullMasks[group];
      if (rm && rc < 40) coverage[row + rc] |= rm;
    }
  }
  return coverage;
}

function pointCoverage(model, xy, visible) {
  // Independent even/odd polygon tests at the eight probe positions. This
  // validates signed coordinates, clipped spans and mask endpoints without
  // sharing the scanline walker, span serializer or left/right mask tables.
  const coverage = Buffer.alloc(1000);
  for (let faceIndex = 0; faceIndex < model.whiteFaces.length; faceIndex++) {
    if (!visible[faceIndex]) continue;
    const points = model.whiteFaces[faceIndex].indices.map(index => xy[index]);
    const minX = Math.min(...points.map(point => point[0])), maxX = Math.max(...points.map(point => point[0]));
    const minY = Math.min(...points.map(point => point[1])), maxY = Math.max(...points.map(point => point[1]));
    for (let row = Math.max(0, Math.floor(minY / 8)); row < Math.min(25, Math.ceil(maxY / 8)); row++) {
      for (let column = Math.max(0, Math.floor(minX / 8)); column < Math.min(40, Math.ceil(maxX / 8)); column++) {
        for (let py = 0; py < 3; py++) for (let px = 0; px < 3; px++) {
          const bit = raster.sampleBit(py, px, 8);
          if (!bit) continue;
          const x = column * 8 + SAMPLE_OFFSETS[px], y = row * 8 + SAMPLE_OFFSETS[py];
          let inside = false;
          for (let edge = 0; edge < points.length; edge++) {
            const a = points[edge], b = points[(edge + 1) % points.length];
            if ((a[1] > y) !== (b[1] > y) && x < a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])) inside = !inside;
          }
          if (inside) coverage[row * 40 + column] |= bit;
        }
      }
    }
  }
  return coverage;
}

function serializeFaces(faces) {
  const out = Buffer.alloc(2 + faces.reduce((sum, face) => sum + 2 + face.spans.length * 4, 0));
  out.writeUInt16LE(faces.length);
  let offset = 2;
  for (const face of faces) {
    out[offset++] = face.first;
    out[offset++] = face.spans.length;
    for (const [left, right] of face.spans) {
      out.writeUInt16LE(left, offset); out.writeUInt16LE(right, offset + 2); offset += 4;
    }
  }
  return out;
}

function deserializeFaces(bytes) {
  const faces = [];
  let offset = 2;
  for (let index = 0; index < bytes.readUInt16LE(0); index++) {
    const first = bytes[offset++], count = bytes[offset++], spans = [];
    for (let sample = 0; sample < count; sample++) {
      spans.push([bytes.readUInt16LE(offset), bytes.readUInt16LE(offset + 2)]); offset += 4;
    }
    faces.push({first, spans});
  }
  assert.equal(offset, bytes.length);
  return faces;
}

function circleTables(font, glyphLut, coverages) {
  const maps = [], mapIndices = new Map(), records = [], reachable = [...new Set(glyphLut)];
  let outsideCovered = 0;
  for (let cell = 0; cell < 1000; cell++) {
    const left = cell % 40 * 8, top = Math.floor(cell / 40) * 8;
    const mask = Array.from({length: 8}, (_, y) => {
      let row = 0;
      for (let x = 0; x < 8; x++) if ((left + x + 0.5 - 160) ** 2 + (top + y + 0.5 - 100) ** 2 <= SETTINGS.radius ** 2) row |= 128 >>> x;
      return row;
    });
    if (mask.every(row => row === 255)) continue;
    if (mask.every(row => row === 0) && !coverages.some(coverage => coverage[cell] !== 0)) continue;
    if (mask.every(row => row === 0)) outsideCovered++;
    const candidates = font.glyphs.filter(glyph => glyph.rows.every((row, y) => (row & ~mask[y]) === 0));
    assert(candidates.length);
    const map = Buffer.alloc(256);
    for (const source of reachable) {
      let best = 0, error = 65;
      for (const glyph of candidates) {
        const value = glyph.rows.reduce((sum, row, y) => sum + popcount8(row ^ font.glyphs[source].rows[y]), 0);
        if (value < error) { error = value; best = glyph.index; }
      }
      map[source] = best;
    }
    const key = map.toString('hex');
    let mapIndex = mapIndices.get(key);
    if (mapIndex === undefined) { mapIndex = maps.length; maps.push(map); mapIndices.set(key, mapIndex); }
    records.push({cell, offset: mapIndex * 256});
  }
  const serialized = Buffer.alloc(records.length * 4);
  records.forEach((record, index) => { serialized.writeUInt16LE(record.cell, index * 4); serialized.writeUInt16LE(record.offset, index * 4 + 2); });
  return {records, maps, serialized, remap: Buffer.concat(maps), reachable: reachable.length, outsideCovered};
}

function resolve(coverage, glyphLut, circle) {
  const screen = Buffer.alloc(coverage.length);
  for (let cell = 0; cell < screen.length; cell++) screen[cell] = glyphLut[coverage[cell]];
  for (const {cell, offset} of circle.records) screen[cell] = circle.remap[offset + screen[cell]];
  return screen;
}

function encodeGeometryDelta(projections, visibilities, topology) {
  // GX16 container: header, global topology, one full signed16 XY state, then
  // fixed-size nibble deltas and visibility. Both nibbles are signed -8..7.
  const first = Buffer.alloc(projections[0].length * 4);
  projections[0].forEach(([x, y], index) => { first.writeInt16LE(x, index * 4); first.writeInt16LE(y, index * 4 + 2); });
  const header = Buffer.alloc(16);
  header.write('GX16'); header[4] = 1; header.writeUInt16LE(projections.length, 5);
  header.writeUInt16LE(projections[0].length, 7); header.writeUInt16LE(topology.length, 9);
  header[11] = visibilities[0].length; header.writeUInt16LE(SETTINGS.radius, 12); header[14] = SETTINGS.checks; header[15] = SETTINGS.bands;
  const parts = [header, topology, first, visibilities[0]];
  for (let pose = 1; pose < projections.length; pose++) {
    const packed = Buffer.alloc(projections[pose].length);
    projections[pose].forEach(([x, y], index) => {
      const dx = x - projections[pose - 1][index][0], dy = y - projections[pose - 1][index][1];
      assert(dx >= -8 && dx <= 7 && dy >= -8 && dy <= 7);
      packed[index] = ((dx & 15) << 4) | (dy & 15);
    });
    parts.push(packed, visibilities[pose]);
  }
  return Buffer.concat(parts);
}

function decodeGeometryDelta(bytes) {
  assert.equal(bytes.subarray(0, 4).toString(), 'GX16'); assert.equal(bytes[4], 1);
  const count = bytes.readUInt16LE(5), vertexCount = bytes.readUInt16LE(7), topologyBytes = bytes.readUInt16LE(9), visibilityBytes = bytes[11];
  let offset = 16 + topologyBytes;
  let xy = Array.from({length: vertexCount}, (_, index) => [bytes.readInt16LE(offset + index * 4), bytes.readInt16LE(offset + index * 4 + 2)]);
  offset += vertexCount * 4;
  const projections = [xy.map(point => point.slice())], visibilities = [Buffer.from(bytes.subarray(offset, offset + visibilityBytes))];
  offset += visibilityBytes;
  for (let pose = 1; pose < count; pose++) {
    xy = xy.map(([x, y], index) => {
      const packed = bytes[offset + index], hi = packed >>> 4, lo = packed & 15;
      return [x + (hi < 8 ? hi : hi - 16), y + (lo < 8 ? lo : lo - 16)];
    });
    offset += vertexCount;
    projections.push(xy); visibilities.push(Buffer.from(bytes.subarray(offset, offset + visibilityBytes)));
    offset += visibilityBytes;
  }
  assert.equal(offset, bytes.length);
  return {projections, visibilities, topology: bytes.subarray(16, 16 + topologyBytes)};
}

function encodeGeometryBook(projections, visibilities, topology) {
  const frequency = new Map();
  for (let pose = 1; pose < projections.length; pose++) projections[pose].forEach(([x, y], index) => {
    const dx = x - projections[pose - 1][index][0], dy = y - projections[pose - 1][index][1];
    assert(dx >= -8 && dx <= 7 && dy >= -8 && dy <= 7);
    const packed = ((dx & 15) << 4) | (dy & 15);
    frequency.set(packed, (frequency.get(packed) || 0) + 1);
  });
  const ordered = [...frequency.entries()].sort((a, b) => b[1] - a[1] || a[0] - b[0]);
  const book = Buffer.from(ordered.slice(0, 15).map(([packed]) => packed));
  const indexByPair = new Map([...book].map((value, index) => [value, index]));
  const first = Buffer.alloc(projections[0].length * 4);
  projections[0].forEach(([x, y], index) => { first.writeInt16LE(x, index * 4); first.writeInt16LE(y, index * 4 + 2); });
  const header = Buffer.alloc(16);
  header.write('GX4B'); header[4] = 1; header.writeUInt16LE(projections.length, 5);
  header.writeUInt16LE(projections[0].length, 7); header.writeUInt16LE(topology.length, 9);
  header[11] = visibilities[0].length; header[12] = book.length; header[13] = SETTINGS.checks; header[14] = SETTINGS.bands; header[15] = SETTINGS.radius;
  const parts = [header, book, topology, first, visibilities[0]], poseBytes = [], escapeCounts = [];
  for (let pose = 1; pose < projections.length; pose++) {
    const nibbles = [];
    let escapes = 0;
    projections[pose].forEach(([x, y], index) => {
      const dx = x - projections[pose - 1][index][0], dy = y - projections[pose - 1][index][1];
      const pair = ((dx & 15) << 4) | (dy & 15), code = indexByPair.get(pair);
      if (code === undefined) { nibbles.push(15, pair >>> 4, pair & 15); escapes++; }
      else nibbles.push(code);
    });
    assert.equal(nibbles.length % 2, 0);
    const packed = Buffer.alloc(nibbles.length / 2);
    for (let index = 0; index < packed.length; index++) packed[index] = (nibbles[index * 2] << 4) | nibbles[index * 2 + 1];
    parts.push(packed, visibilities[pose]); poseBytes.push(packed.length + visibilities[pose].length); escapeCounts.push(escapes);
  }
  return {bytes: Buffer.concat(parts), book, poseBytes, escapeCounts, frequencies: ordered};
}

function decodeGeometryBook(bytes) {
  assert.equal(bytes.subarray(0, 4).toString(), 'GX4B'); assert.equal(bytes[4], 1);
  const count = bytes.readUInt16LE(5), vertexCount = bytes.readUInt16LE(7), topologyBytes = bytes.readUInt16LE(9), visibilityBytes = bytes[11], bookCount = bytes[12];
  const book = bytes.subarray(16, 16 + bookCount), topology = bytes.subarray(16 + bookCount, 16 + bookCount + topologyBytes);
  let offset = 16 + bookCount + topologyBytes;
  let xy = Array.from({length: vertexCount}, (_, index) => [bytes.readInt16LE(offset + index * 4), bytes.readInt16LE(offset + index * 4 + 2)]);
  offset += vertexCount * 4;
  const projections = [xy.map(point => point.slice())], visibilities = [Buffer.from(bytes.subarray(offset, offset + visibilityBytes))];
  offset += visibilityBytes;
  for (let pose = 1; pose < count; pose++) {
    let half = 0;
    function nibble() {
      if (half === 0) { half = 1; return bytes[offset] >>> 4; }
      half = 0; return bytes[offset++] & 15;
    }
    xy = xy.map(([x, y]) => {
      const code = nibble(), packed = code === 15 ? (nibble() << 4) | nibble() : book[code];
      const hi = packed >>> 4, lo = packed & 15;
      return [x + (hi < 8 ? hi : hi - 16), y + (lo < 8 ? lo : lo - 16)];
    });
    assert.equal(half, 0);
    projections.push(xy); visibilities.push(Buffer.from(bytes.subarray(offset, offset + visibilityBytes))); offset += visibilityBytes;
  }
  assert.equal(offset, bytes.length);
  return {projections, visibilities, topology};
}

function encodeGeometryPlane(projections, visibilities, topology) {
  const packedBook = encodeGeometryBook(projections, visibilities, topology).book;
  const book = Buffer.alloc(packedBook.length * 2), indexByPair = new Map();
  [...packedBook].forEach((pair, index) => {
    const dx = pair >>> 4, dy = pair & 15;
    book.writeInt8(dx < 8 ? dx : dx - 16, index * 2);
    book.writeInt8(dy < 8 ? dy : dy - 16, index * 2 + 1);
    indexByPair.set(pair, index);
  });
  const header = Buffer.alloc(16);
  header.write('GXP4'); header[4] = 1; header.writeUInt16LE(projections.length, 5);
  header.writeUInt16LE(projections[0].length, 7); header.writeUInt16LE(topology.length, 9);
  header[11] = visibilities[0].length; header[12] = packedBook.length; header[13] = SETTINGS.checks; header[14] = SETTINGS.bands; header[15] = SETTINGS.radius;
  const first = Buffer.alloc(projections[0].length * 4);
  projections[0].forEach(([x, y], index) => { first.writeInt16LE(x, index * 4); first.writeInt16LE(y, index * 4 + 2); });
  const parts = [header, book, topology, first, visibilities[0]];
  let offset = header.length + book.length + topology.length;
  const index = [{pose: 0, offset, length: first.length + visibilities[0].length, escapes: 0, seed: true}];
  offset += first.length + visibilities[0].length;
  const poseBytes = [], escapeCounts = [];
  for (let pose = 1; pose < projections.length; pose++) {
    const plane = Buffer.alloc(Math.ceil(projections[pose].length / 2)), escapes = [];
    projections[pose].forEach(([x, y], vertex) => {
      const dx = x - projections[pose - 1][vertex][0], dy = y - projections[pose - 1][vertex][1];
      const packed = ((dx & 15) << 4) | (dy & 15), code = indexByPair.get(packed);
      const token = code === undefined ? 15 : code;
      plane[vertex >> 1] |= token << ((vertex & 1) ? 0 : 4);
      if (code === undefined) escapes.push(dx & 255, dy & 255);
    });
    const escaped = Buffer.from(escapes), length = plane.length + escaped.length + visibilities[pose].length;
    parts.push(plane, escaped, visibilities[pose]); index.push({pose, offset, length, escapes: escaped.length / 2, seed: false}); offset += length;
    poseBytes.push(length); escapeCounts.push(escaped.length / 2);
  }
  return {bytes: Buffer.concat(parts), book, index, poseBytes, escapeCounts};
}

function decodeGeometryPlane(bytes) {
  assert.equal(bytes.subarray(0, 4).toString(), 'GXP4'); assert.equal(bytes[4], 1);
  const count = bytes.readUInt16LE(5), vertexCount = bytes.readUInt16LE(7), topologyBytes = bytes.readUInt16LE(9), visibilityBytes = bytes[11], bookCount = bytes[12];
  const book = bytes.subarray(16, 16 + bookCount * 2), topology = bytes.subarray(16 + bookCount * 2, 16 + bookCount * 2 + topologyBytes);
  let offset = 16 + bookCount * 2 + topologyBytes;
  let xy = Array.from({length: vertexCount}, (_, index) => [bytes.readInt16LE(offset + index * 4), bytes.readInt16LE(offset + index * 4 + 2)]);
  offset += vertexCount * 4;
  const projections = [xy.map(point => point.slice())], visibilities = [Buffer.from(bytes.subarray(offset, offset + visibilityBytes))]; offset += visibilityBytes;
  for (let pose = 1; pose < count; pose++) {
    const plane = bytes.subarray(offset, offset + Math.ceil(vertexCount / 2)); offset += plane.length;
    xy = xy.map(([x, y], vertex) => {
      const token = (plane[vertex >> 1] >>> ((vertex & 1) ? 0 : 4)) & 15;
      let dx, dy;
      if (token === 15) { dx = bytes.readInt8(offset++); dy = bytes.readInt8(offset++); }
      else { dx = book.readInt8(token * 2); dy = book.readInt8(token * 2 + 1); }
      return [x + dx, y + dy];
    });
    projections.push(xy); visibilities.push(Buffer.from(bytes.subarray(offset, offset + visibilityBytes))); offset += visibilityBytes;
  }
  assert.equal(offset, bytes.length);
  return {projections, visibilities, topology};
}

function main() {
  fs.mkdirSync(OUTPUT, {recursive: true});
  const font = generateFont(), bytes = toBytes(font), tables = raster.buildTables(bytes), model = mesh();
  const frames = [], coverages = [], projections = [], visibilities = [], xyParts = [], spanParts = [], spanIndex = [];
  const bounds = {minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity, edgeAbsDx: 0, edgeAbsDy: 0};
  let spanBytes = 0;
  for (let pose = 0; pose < SETTINGS.frames; pose++) {
    const angle = SETTINGS.initialAngle + pose * 2 * Math.PI / SETTINGS.frames;
    const projection = project(model, angle), faces = [];
    const visibility = Buffer.alloc(Math.ceil(model.whiteFaces.length / 8));
    for (let index = 0; index < model.whiteFaces.length; index++) {
      if (!projection.visible[index]) continue;
      visibility[index >> 3] |= 1 << (index & 7);
      const face = model.whiteFaces[index], spans = faceSpans(face.indices, projection.xy);
      if (spans) faces.push({id: face.id, ...spans});
      for (let edge = 0; edge < face.indices.length; edge++) {
        const a = projection.xy[face.indices[edge]], b = projection.xy[face.indices[(edge + 1) % face.indices.length]];
        bounds.edgeAbsDx = Math.max(bounds.edgeAbsDx, Math.abs(a[0] - b[0]));
        bounds.edgeAbsDy = Math.max(bounds.edgeAbsDy, Math.abs(a[1] - b[1]));
      }
    }
    const xy = Buffer.alloc(model.vertices.length * 4);
    projection.xy.forEach(([x, y], index) => {
      xy.writeInt16LE(x, index * 4); xy.writeInt16LE(y, index * 4 + 2);
      bounds.minX = Math.min(bounds.minX, x); bounds.maxX = Math.max(bounds.maxX, x);
      bounds.minY = Math.min(bounds.minY, y); bounds.maxY = Math.max(bounds.maxY, y);
    });
    const encoded = serializeFaces(faces), coverage = fill(faces, tables);
    assert(fill(deserializeFaces(encoded), tables).equals(coverage), `Span roundtrip failed at pose ${pose}`);
    assert(pointCoverage(model, projection.xy, projection.visible).equals(coverage), `Independent polygon-probe mismatch at pose ${pose}`);
    spanParts.push(encoded); coverages.push(coverage); projections.push(projection.xy); visibilities.push(visibility); xyParts.push(xy);
    spanIndex.push({pose, offset: spanBytes, length: encoded.length, visibleFaces: projection.visible.filter(Boolean).length,
      filledFaces: faces.length, samples: faces.reduce((sum, face) => sum + face.spans.length, 0), faceIds: faces.map(face => face.id)});
    spanBytes += encoded.length;
  }
  const circle = circleTables(font, tables.glyphLut, coverages);
  for (const coverage of coverages) frames.push(resolve(coverage, tables.glyphLut, circle));
  const firstBitmap = Buffer.alloc(64000);
  for (let cell = 0; cell < 1000; cell++) for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
    firstBitmap[(Math.floor(cell / 40) * 8 + y) * 320 + (cell % 40) * 8 + x] = (bytes[frames[0][cell] * 8 + y] & (128 >>> x)) ? 255 : 0;
  }
  const pgm = Buffer.concat([Buffer.from('P5\n320 200\n255\n'), firstBitmap]);
  let quality = null;
  const analyticPath = path.join(__dirname, '../c64-preview/build/movie.frames');
  if (fs.existsSync(analyticPath)) {
    const analytic = fs.readFileSync(analyticPath), analyticFont = fs.readFileSync(path.join(path.dirname(analyticPath), 'font.bin'));
    assert(analyticFont.equals(bytes)); assert.equal(analytic.length, SETTINGS.frames * 1000);
    const samples = [];
    for (let pose = 0; pose < SETTINGS.frames; pose += 24) {
      let differentPixels = 0, differentCharacters = 0;
      for (let cell = 0; cell < 1000; cell++) {
        const a = frames[pose][cell], b = analytic[pose * 1000 + cell];
        if (a !== b) differentCharacters++;
        for (let row = 0; row < 8; row++) differentPixels += popcount8(bytes[a * 8 + row] ^ bytes[b * 8 + row]);
      }
      samples.push({pose, differentCharacters, differentPixels, fractionOfScreenPixels: differentPixels / 64000});
    }
    quality = {comparison: 'Reconstructed geometry glyph pixels versus reconstructed analytic HTML glyph pixels; not error against an ideal bitmap.',
      poses: samples.length, analyticFramesSha256: sha(analytic), geometryFramesSha256: sha(Buffer.concat(frames)),
      differentCharacters: summarize(samples.map(sample => sample.differentCharacters)),
      differentPixels: summarize(samples.map(sample => sample.differentPixels)),
      fractionOfScreenPixels: summarize(samples.map(sample => sample.fractionOfScreenPixels)), samples};
    fs.writeFileSync(path.join(OUTPUT, 'quality-comparison.json'), JSON.stringify(quality, null, 2) + '\n');
  }
  const closure = project(model, SETTINGS.initialAngle + 2 * Math.PI);
  assert.deepEqual(closure.xy, projections[0], '360-degree integer geometry closure');
  assert.deepEqual(closure.visible, project(model, SETTINGS.initialAngle).visible, '360-degree visibility closure');
  const topology = Buffer.from(model.whiteFaces.flatMap(face => [face.indices.length, ...face.indices]));
  const deltaParts = [xyParts[0], visibilities[0]], deltaPairs = new Set();
  let maxDx = 0, maxDy = 0;
  for (let pose = 1; pose < SETTINGS.frames; pose++) {
    const packed = Buffer.alloc(model.vertices.length);
    for (let vertex = 0; vertex < model.vertices.length; vertex++) {
      const dx = projections[pose][vertex][0] - projections[pose - 1][vertex][0];
      const dy = projections[pose][vertex][1] - projections[pose - 1][vertex][1];
      maxDx = Math.max(maxDx, Math.abs(dx)); maxDy = Math.max(maxDy, Math.abs(dy));
      deltaPairs.add(dx + ',' + dy);
      assert(dx >= -8 && dx <= 7 && dy >= -8 && dy <= 7, 'Projected coordinate delta exceeds signed nibble');
      packed[vertex] = ((dx & 15) << 4) | (dy & 15);
    }
    deltaParts.push(packed, visibilities[pose]);
  }
  const geometryDelta = encodeGeometryDelta(projections, visibilities, topology), decodedGeometry = decodeGeometryDelta(geometryDelta);
  assert.deepEqual(decodedGeometry.projections, projections, 'Signed-nibble XY container decode');
  assert.deepEqual(decodedGeometry.visibilities, visibilities, 'Visibility container decode');
  assert(decodedGeometry.topology.equals(topology));
  const geometryBook = encodeGeometryBook(projections, visibilities, topology), decodedBook = decodeGeometryBook(geometryBook.bytes);
  assert.deepEqual(decodedBook.projections, projections, 'Pair-book XY container decode');
  assert.deepEqual(decodedBook.visibilities, visibilities, 'Pair-book visibility decode');
  assert(decodedBook.topology.equals(topology));
  const geometryPlane = encodeGeometryPlane(projections, visibilities, topology), decodedPlane = decodeGeometryPlane(geometryPlane.bytes);
  assert.deepEqual(decodedPlane.projections, projections, 'Pair-plane XY container decode');
  assert.deepEqual(decodedPlane.visibilities, visibilities, 'Pair-plane visibility decode');
  assert(decodedPlane.topology.equals(topology));
  const edgeParts = [], edgeIndex = [];
  let edgeBytes = 0;
  for (let pose = 0; pose < SETTINGS.frames; pose++) {
    const visible = model.whiteFaces.filter((face, index) => visibilities[pose][index >> 3] & (1 << (index & 7)));
    const bytes = Buffer.alloc(model.vertices.length * 4 + 2 + visible.reduce((sum, face) => sum + 1 + face.indices.length, 0));
    projections[pose].forEach(([x, y], index) => {
      bytes[index] = x & 255; bytes[model.vertices.length + index] = (x >> 8) & 255;
      bytes[2 * model.vertices.length + index] = y & 255; bytes[3 * model.vertices.length + index] = (y >> 8) & 255;
    });
    let offset = model.vertices.length * 4; bytes.writeUInt16LE(visible.length, offset); offset += 2;
    for (const face of visible) { bytes[offset++] = face.indices.length; for (const index of face.indices) bytes[offset++] = index; }
    edgeParts.push(bytes); edgeIndex.push({pose, offset: edgeBytes, length: bytes.length, visibleFaces: visible.length}); edgeBytes += bytes.length;
  }
  const pool = new Map(), references = [];
  let poolBytes = 0;
  for (const encoded of spanParts) {
    const faces = deserializeFaces(encoded), frameReferences = [];
    for (const face of faces) {
      const originX = Math.min(...face.spans.filter(([l, r]) => r > l).map(([left]) => left));
      const normalized = Buffer.alloc(1 + face.spans.length * 4); normalized[0] = face.spans.length;
      face.spans.forEach(([left, right], index) => {
        normalized.writeInt16LE(right > left ? left - originX : 0, 1 + index * 4);
        normalized.writeInt16LE(right > left ? right - originX : 0, 3 + index * 4);
      });
      const key = normalized.toString('hex');
      let entry = pool.get(key);
      if (!entry) { entry = {offset: poolBytes, bytes: normalized}; pool.set(key, entry); poolBytes += normalized.length; }
      frameReferences.push({first: face.first, originX, offset: entry.offset});
    }
    references.push(frameReferences);
  }
  const assets = {'font.bin': bytes, 'glyph-lut.bin': Buffer.from(tables.glyphLut),
    'left-mask.bin': Buffer.from(tables.leftMasks), 'right-mask.bin': Buffer.from(tables.rightMasks),
    'full-mask.bin': Buffer.from(tables.fullMasks), 'sample-y.bin': Buffer.from(SAMPLE_Y),
    'row-offset-lo.bin': Buffer.from(tables.rowOffsetLo), 'row-offset-hi.bin': Buffer.from(tables.rowOffsetHi),
    'clip-records.bin': circle.serialized, 'limb-remap.bin': circle.remap,
    'frames.spans': Buffer.concat(spanParts), 'frames.xy16': Buffer.concat(xyParts),
    'frames.visibility': Buffer.concat(visibilities), 'frames.xy-delta8': Buffer.concat(deltaParts),
    'movie.gx16': geometryDelta, 'movie.gx4b': geometryBook.bytes, 'xy-pair-book.bin': geometryBook.book, 'frames.edges': Buffer.concat(edgeParts),
    'movie.gxp4': geometryPlane.bytes, 'xy-pair-book-xy.bin': geometryPlane.book,
    'topology.bin': topology, 'frames.coverage': Buffer.concat(coverages), 'frames.screen': Buffer.concat(frames), 'frame000.pgm': pgm};
  for (const [name, data] of Object.entries(assets)) fs.writeFileSync(path.join(OUTPUT, name), data);
  fs.writeFileSync(path.join(OUTPUT, 'spans-index.json'), JSON.stringify(spanIndex, null, 2) + '\n');
  fs.writeFileSync(path.join(OUTPUT, 'edges-index.json'), JSON.stringify(edgeIndex, null, 2) + '\n');
  fs.writeFileSync(path.join(OUTPUT, 'gxp4-index.json'), JSON.stringify(geometryPlane.index, null, 2) + '\n');
  fs.writeFileSync(path.join(OUTPUT, 'mesh.json'), JSON.stringify(model, null, 2) + '\n');
  const metadata = {settings: SETTINGS, mesh: {vertices: model.vertices.length, faces: model.faces.length, whiteFaces: model.whiteFaces.length,
    triangles: 40, quads: 160, whiteTriangles: 20, whiteQuads: 80}, bounds,
    spanAbi: 'frame:u16LE faceCount; face:u8 firstSample,u8 sampleCount; samples:u16LE left,u16LE right; half-open [left,right), clip0..320; empty0,0',
    xyAbi: '182 signed little-endian int16 X,Y pairs per pose (728 bytes); projection rounds nearest integer; visible white-face flags separate13bytes LSB-first',
    topologyAbi: '100 white faces in mesh order: bytevertexCount then bytevertexindices',
    edgesAbi: '182 Xlo bytes,182 Xhi,182 Ylo,182 Yhi;LE16 visibleFaceCount; visible faces bytevertexCount then bytevertexindices. Variable per-pose lengths in edges-index.json',
    crossingRule: 'Order each edge by y0<y1; include y0<=sampleY<y1; crossing=x0+ceil((sampleY-y0)*(x1-x0)/(y1-y0)); sampleY=charRow*8+[1,4,6]',
    clipAbi: 'Records: LE16 cell,LE16 byteOffset into limb-remap.bin; direct256byte glyphcode map; only reachable glyph-lut codes populated',
    fontSha256: sha(bytes), glyphLookupReachable: circle.reachable, clipRecords: circle.records.length,
    clipMaps: circle.maps.length, coveredFullyOutsideCells: circle.outsideCovered,
    perFrame: {visibleFaces: summarize(spanIndex.map(frame => frame.visibleFaces)), filledFaces: summarize(spanIndex.map(frame => frame.filledFaces)),
      spanSamples: summarize(spanIndex.map(frame => frame.samples)), spanBytes: summarize(spanIndex.map(frame => frame.length))},
    xyDelta8: {firstPoseBytes: xyParts[0].length + visibilities[0].length, subsequentPoseBytes: model.vertices.length + visibilities[0].length,
      maxAbsDx: maxDx, maxAbsDy: maxDy, distinctDeltaPairs: deltaPairs.size, totalIncludingTopology: topology.length + assets['frames.xy-delta8'].length},
    geometryDeltaContainer: {magic: 'GX16', headerBytes: 16, topologyBytes: topology.length, firstPoseBytes: xyParts[0].length + visibilities[0].length,
      nextPoseBytes: model.vertices.length + visibilities[0].length, totalBytes: geometryDelta.length, roundtripFrames: SETTINGS.frames,
      includesAllVertices: true, includesVisibility: true, includesSharedTopology: true, nativeDecoderImplemented: false},
    geometryBookContainer: {magic: 'GX4B', headerBytes: 16, pairBookBytes: geometryBook.book.length, topologyBytes: topology.length,
      firstPoseBytes: xyParts[0].length + visibilities[0].length, nextPoseBytes: summarize(geometryBook.poseBytes),
      escapesPerPose: summarize(geometryBook.escapeCounts), totalBytes: geometryBook.bytes.length, roundtripFrames: SETTINGS.frames,
      includesAllVertices: true, includesVisibility: true, includesSharedTopology: true, nativeDecoderImplemented: false,
      codec: '15 most frequent signed XY-delta pairs indexed by 4 bits; escape15 followed by signed4bit dx,dy. Exactly182 tokens then13 visibility bytes per subsequent pose.'},
    geometryPlaneContainer: {magic: 'GXP4', headerBytes: 16, pairBookBytes: geometryPlane.book.length, topologyBytes: topology.length,
      firstPoseBytes: xyParts[0].length + visibilities[0].length, nextPoseBytes: summarize(geometryPlane.poseBytes),
      escapesPerPose: summarize(geometryPlane.escapeCounts), totalBytes: geometryPlane.bytes.length, roundtripFrames: SETTINGS.frames,
      includesAllVertices: true, includesVisibility: true, includesSharedTopology: true, nativeDecoderImplemented: false,
      abi: 'Header16, book15*(signed8dx,signed8dy), topology480, seed182*(LEs16X,LEs16Y)+visibility13. Each subsequent pose:91byte tokenplane, highnibble evenvertex/lownibble oddvertex; escape15 reads2signed8dx,dy bytes from following escapeplane in vertex order; visibility13 last. Per-pose indices in gxp4-index.json.'},
    spanPoolEstimate: {description: 'Exact normalized raw16bit spans, no packing; shared x translation, firstSample and pooloffset per face. An estimate, not a native decoder.',
      patterns: pool.size, poolBytes, referenceBytes: references.reduce((sum, refs) => sum + 2 + refs.length * 7, 0),
      totalBytes: poolBytes + references.reduce((sum, refs) => sum + 2 + refs.length * 7, 0)},
    files: Object.fromEntries(Object.entries(assets).map(([name, data]) => [name, {bytes: data.length, sha256: sha(data)}])),
    verification: {spanRoundtripFrames: SETTINGS.frames, independentEvenOddProbeFrames: SETTINGS.frames, geometryDeltaRoundtripFrames: SETTINGS.frames,
      fullTurnGeometryClosure: true, runtimeContainsReferencePixels: false, nativeMeasured: false},
    qualityComparison: quality,
    imageScope: 'Perspective flat 200-face checker mesh at the same radius, checker count, font and orientation as the curved analytic reference. Flat faces are not pixel-identical to spherical checker patches.'};
  fs.writeFileSync(path.join(OUTPUT, 'metadata.json'), JSON.stringify(metadata, null, 2) + '\n');
  console.log(JSON.stringify(metadata, null, 2));
  return {metadata, assets, spanIndex, model, projections, visibilities};
}

module.exports = {SETTINGS, SAMPLE_Y, mesh, rotate, project, faceSpans, fill, serializeFaces, deserializeFaces, circleTables, resolve,
  encodeGeometryDelta, decodeGeometryDelta, encodeGeometryBook, decodeGeometryBook, encodeGeometryPlane, decodeGeometryPlane, main};
if (require.main === module) main();
