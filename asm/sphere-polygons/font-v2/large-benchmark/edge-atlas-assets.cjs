'use strict';

// Individual precomputed edge paths for the large sphere. The native variant
// aggregates their crossings into each face's spans before character filling.
// This sequential format does not claim a shared edge atlas at runtime.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const geometry = require('./geometry.cjs');
const raster = require('../../raster.cjs');

const INPUT = path.join(__dirname, 'build/geometry');
const OUTPUT = path.join(__dirname, 'build/edge-paths');
const ARENA_BYTES = 24064;
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const summary = values => ({min: Math.min(...values), mean: values.reduce((sum, value) => sum + value, 0) / values.length, max: Math.max(...values)});

function edgePath(a, b) {
  let [x0, y0] = a, [x1, y1] = b;
  if (y0 === y1) return null;
  if (y0 > y1) [x0, y0, x1, y1] = [x1, y1, x0, y0];
  const first = geometry.SAMPLE_Y.findIndex(y => y >= y0);
  if (first < 0) return null;
  const values = [];
  for (let sample = first; sample < geometry.SAMPLE_Y.length && geometry.SAMPLE_Y[sample] < y1; sample++) {
    const crossing = x0 + Math.ceil((geometry.SAMPLE_Y[sample] - y0) * (x1 - x0) / (y1 - y0));
    values.push(Math.max(0, Math.min(320, crossing)));
  }
  return values.length ? {first, values} : null;
}

function serialize(faces) {
  const length = 2 + faces.reduce((sum, face) => sum + 3 + face.edges.reduce((n, edge) => n + 4 + edge.values.length - 1, 0), 0);
  const bytes = Buffer.alloc(length);
  bytes.writeUInt16LE(faces.length);
  let offset = 2;
  for (const face of faces) {
    bytes[offset++] = face.first; bytes[offset++] = face.count; bytes[offset++] = face.edges.length;
    for (const edge of face.edges) {
      bytes[offset++] = edge.first; bytes[offset++] = edge.values.length;
      bytes.writeUInt16LE(edge.values[0], offset); offset += 2;
      for (let index = 1; index < edge.values.length; index++) {
        const delta = edge.values[index] - edge.values[index - 1];
        assert(delta >= -128 && delta <= 127, 'Edge path delta exceeds signed byte');
        bytes.writeInt8(delta, offset++);
      }
    }
  }
  assert.equal(offset, bytes.length);
  return bytes;
}

function decode(bytes) {
  const faces = [];
  let offset = 2;
  for (let faceIndex = 0; faceIndex < bytes.readUInt16LE(0); faceIndex++) {
    const first = bytes[offset++], count = bytes[offset++], edgeCount = bytes[offset++];
    const left = new Uint16Array(count).fill(0xffff), right = new Uint16Array(count);
    for (let edgeIndex = 0; edgeIndex < edgeCount; edgeIndex++) {
      const edgeFirst = bytes[offset++], edgeSamples = bytes[offset++];
      let value = bytes.readUInt16LE(offset); offset += 2;
      for (let sample = 0; sample < edgeSamples; sample++) {
        if (sample) value += bytes.readInt8(offset++);
        assert(value >= 0 && value <= 320);
        const row = edgeFirst + sample - first;
        assert(row >= 0 && row < count);
        left[row] = Math.min(left[row], value); right[row] = Math.max(right[row], value);
      }
    }
    const spans = Array.from({length: count}, (_, index) => right[index] > left[index] ? [left[index], right[index]] : [0, 0]);
    faces.push({first, spans});
  }
  assert.equal(offset, bytes.length);
  return faces;
}

function prefix(rows, capacity, withPointers) {
  let frames = 0, bytes = 0;
  for (const row of rows) {
    const candidate = bytes + row.length;
    if (candidate + (withPointers ? 2 * (frames + 1) : 0) > capacity) break;
    bytes = candidate; frames++;
  }
  return {frames, payloadBytes: bytes, pointerBytes: withPointers ? 2 * frames : 0,
    totalBytes: bytes + (withPointers ? 2 * frames : 0), unusedBytes: capacity - bytes - (withPointers ? 2 * frames : 0)};
}

function main() {
  fs.mkdirSync(OUTPUT, {recursive: true});
  const model = geometry.mesh(), sourceXY = fs.readFileSync(path.join(INPUT, 'frames.xy16'));
  const visibility = fs.readFileSync(path.join(INPUT, 'frames.visibility'));
  const sourceSpans = fs.readFileSync(path.join(INPUT, 'frames.spans'));
  const sourceIndex = JSON.parse(fs.readFileSync(path.join(INPUT, 'spans-index.json')));
  const expectedCoverage = fs.readFileSync(path.join(INPUT, 'frames.coverage'));
  const font = fs.readFileSync(path.join(INPUT, 'font.bin')), tables = raster.buildTables(font);
  const frames = [], index = [], normalizedPool = new Map(), dedupPrefix = [];
  const faceCounts = [], edgeCounts = [], sampleCounts = [];
  let offset = 0, maxDelta = 0, crossingsAbove255 = 0, normalizedPoolBytes = 0, referencesBytes = 0;
  for (let pose = 0; pose < geometry.SETTINGS.frames; pose++) {
    const xy = Array.from({length: model.vertices.length}, (_, vertex) => [sourceXY.readInt16LE(pose * 728 + vertex * 4), sourceXY.readInt16LE(pose * 728 + vertex * 4 + 2)]);
    const faces = [];
    for (let faceIndex = 0; faceIndex < model.whiteFaces.length; faceIndex++) {
      if (!(visibility[pose * 13 + (faceIndex >> 3)] & (1 << (faceIndex & 7)))) continue;
      const face = model.whiteFaces[faceIndex], canonical = geometry.faceSpans(face.indices, xy);
      if (!canonical) continue;
      const edges = [];
      for (let edge = 0; edge < face.indices.length; edge++) {
        const result = edgePath(xy[face.indices[edge]], xy[face.indices[(edge + 1) % face.indices.length]]);
        if (!result) continue;
        edges.push(result);
        const normalized = Buffer.alloc(result.values.length); normalized[0] = result.values.length;
        for (let sample = 1; sample < result.values.length; sample++) {
          const delta = result.values[sample] - result.values[sample - 1];
          maxDelta = Math.max(maxDelta, Math.abs(delta));
          normalized.writeInt8(delta, sample);
        }
        crossingsAbove255 += result.values.filter(value => value > 255).length;
        const key = normalized.toString('hex');
        if (!normalizedPool.has(key)) { normalizedPool.set(key, normalized); normalizedPoolBytes += normalized.length; }
      }
      faces.push({first: canonical.first, count: canonical.spans.length, edges});
    }
    const bytes = serialize(faces), decoded = decode(bytes), canonicalBytes = geometry.serializeFaces(decoded);
    const source = sourceIndex[pose];
    assert(canonicalBytes.equals(sourceSpans.subarray(source.offset, source.offset + source.length)), `Canonical span mismatch at pose ${pose}`);
    assert(geometry.fill(decoded, tables).equals(expectedCoverage.subarray(pose * 1000, (pose + 1) * 1000)), `Coverage mismatch at pose ${pose}`);
    const edges = faces.reduce((sum, face) => sum + face.edges.length, 0);
    const samples = faces.reduce((sum, face) => sum + face.edges.reduce((n, edge) => n + edge.values.length, 0), 0);
    frames.push(bytes); index.push({pose, offset, length: bytes.length, faces: faces.length, edges, samples}); offset += bytes.length;
    faceCounts.push(faces.length); edgeCounts.push(edges); sampleCounts.push(samples);
    // Dedup estimate only: each reference uses firstSample8, firstX16 and a
    // two-byte pool offset. Counts and delta paths live in the shared pool.
    referencesBytes += 2 + faces.length * 3 + edges * 5;
    dedupPrefix.push({frames: pose + 1, poolBytes: normalizedPoolBytes, referencesBytes,
      pointerBytes: 2 * (pose + 1), totalBytes: normalizedPoolBytes + referencesBytes + 2 * (pose + 1)});
  }
  const data = Buffer.concat(frames);
  fs.writeFileSync(path.join(OUTPUT, 'frames.edgepaths'), data);
  fs.writeFileSync(path.join(OUTPUT, 'index.json'), JSON.stringify(index, null, 2) + '\n');
  fs.writeFileSync(path.join(OUTPUT, 'dedup-prefix-estimate.json'), JSON.stringify(dedupPrefix, null, 2) + '\n');
  const dedupFits = dedupPrefix.filter(row => row.totalBytes <= ARENA_BYTES);
  const poolOffsetBytes = normalizedPoolBytes <= 65536 ? 2 : 3;
  const wideReferenceBytes = referencesBytes + edgeCounts.reduce((sum, count) => sum + count, 0) * (poolOffsetBytes - 2);
  const metadata = {settings: geometry.SETTINGS,
    scope: 'Sequential precomputed individual edge paths. Native runtime still aggregates min/max face crossings and fills character coverage. This is not a runtime shared atlas.',
    abi: 'Frame:u16LE faceCount; face:u8 firstSample,u8 sampleCount,u8 edgeCount; edge:u8 firstSample,u8 count,u16LE firstClippedCeilX,then count-1 signed8 deltaX. All crossing X clipped0..320; sampleY=charRow*8+[1,4,6]. Empty/offscreen faces omitted.',
    decodeRule: 'Initialize face left to65535 and right to0. Reconstruct each edge path and aggregate min/max per sample. If right<=left, canonical span is0,0; otherwise[left,right).',
    frames: frames.length, bytes: data.length, sha256: sha(data), maxAbsoluteEdgeDelta: maxDelta, crossingsAbove255,
    perFrame: {bytes: summary(index.map(row => row.length)), faces: summary(faceCounts), edges: summary(edgeCounts), edgeSamples: summary(sampleCounts)},
    capacityBytes: ARENA_BYTES, capacitySequential: prefix(index, ARENA_BYTES, false), capacityWithTwoByteFramePointers: prefix(index, ARENA_BYTES, true),
    normalizedDedupEstimate: {nativeImplemented: false, patterns: normalizedPool.size, poolBytes: normalizedPoolBytes,
      referenceBytesAssuming16BitOffsets: referencesBytes, poolOffsetBytesNeededForFullMovie: poolOffsetBytes,
      fullMovieReferenceBytes: wideReferenceBytes, fullMovieBytes: normalizedPoolBytes + wideReferenceBytes + 2 * frames.length,
      maxPrefixFittingArenaWithPointers: dedupFits.length ? dedupFits[dedupFits.length - 1] : null,
      caveat: 'Offline exact normalized path sharing estimate. Not the native sequential edge-path codec. A full pool larger than65536 needs wider offsets; arena prefixes fit16bit offsets.'},
    sourceHashes: {xy: sha(sourceXY), visibility: sha(visibility), spans: sha(sourceSpans), coverage: sha(expectedCoverage), font: sha(font)},
    verification: {canonicalSpanFramesExact: frames.length, coverageFramesExact: frames.length, runtimeUsesReferencePixels: false, nativeMeasured: false}};
  fs.writeFileSync(path.join(OUTPUT, 'metadata.json'), JSON.stringify(metadata, null, 2) + '\n');
  fs.writeFileSync(path.join(OUTPUT, 'README.md'), '# Precomputed individual edge paths\n\n' + metadata.scope + '\n\n' + metadata.abi + '\n\n' + metadata.decodeRule + '\n\nRegenerate from the repository root:\n\n```sh\nrtk proxy node asm/sphere-polygons/font-v2/large-benchmark/edge-atlas-assets.cjs\n```\n\nThe generator verifies all384 records against the frozen geometry pipeline\'s canonical spans and coverage bytes. Native timing is reported separately.\n');
  console.log(JSON.stringify(metadata, null, 2));
  return {metadata, index, data};
}

module.exports = {edgePath, serialize, decode, prefix, main};
if (require.main === module) main();
