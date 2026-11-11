'use strict';

// Adapt the validated GXP4 geometry codec to the native edge benchmark.
// Native records append the visible-face count; topology remains shared.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');

const here = __dirname;
const geometry = path.join(here, 'build/geometry');
const output = path.join(here, 'build/native-xy');
const vertices = 182;
const visibilityBytes = 13;
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

function planes(interleaved) {
  const result = Buffer.alloc(vertices * 4);
  for (let vertex = 0; vertex < vertices; vertex++) {
    result[vertex] = interleaved[vertex * 4];
    result[vertices + vertex] = interleaved[vertex * 4 + 1];
    result[vertices * 2 + vertex] = interleaved[vertex * 4 + 2];
    result[vertices * 3 + vertex] = interleaved[vertex * 4 + 3];
  }
  return result;
}

function main() {
  fs.mkdirSync(output, {recursive: true});
  const container = fs.readFileSync(path.join(geometry, 'movie.gxp4'));
  const index = JSON.parse(fs.readFileSync(path.join(geometry, 'gxp4-index.json')));
  const xy = fs.readFileSync(path.join(geometry, 'frames.xy16'));
  const visibility = fs.readFileSync(path.join(geometry, 'frames.visibility'));
  const book = fs.readFileSync(path.join(geometry, 'xy-pair-book-xy.bin'));
  const topology = fs.readFileSync(path.join(geometry, 'topology.bin'));
  assert.equal(book.length, 30);
  const zeroPair = Array.from({length: 15}, (_, item) => item).find(item => book[item * 2] === 0 && book[item * 2 + 1] === 0);
  assert.notEqual(zeroPair, undefined);
  const sourceParts = [];
  const sourceIndex = [];
  let offset = 0;
  for (const record of index) {
    const pose = record.pose;
    const vis = visibility.subarray(pose * visibilityBytes, (pose + 1) * visibilityBytes);
    let faceCount = 0;
    for (const value of vis) for (let bit = 0; bit < 8; bit++) faceCount += (value >>> bit) & 1;
    const count = Buffer.alloc(2); count.writeUInt16LE(faceCount);
    const payload = pose === 0
      ? Buffer.concat([Buffer.alloc(91, zeroPair | zeroPair << 4), vis])
      : container.subarray(record.offset, record.offset + record.length);
    const native = Buffer.concat([payload, count]);
    sourceParts.push(native);
    sourceIndex.push({pose, offset, length: native.length, previousPose: Math.max(0, pose - 1)});
    offset += native.length;
  }
  const planarFrames = [];
  for (let offset = 0; offset < xy.length; offset += vertices * 4) planarFrames.push(planes(xy.subarray(offset, offset + vertices * 4)));
  const source = Buffer.concat(sourceParts);
  const initial = planarFrames[0];
  fs.writeFileSync(path.join(output, 'frames.source'), source);
  fs.writeFileSync(path.join(output, 'index.json'), JSON.stringify(sourceIndex, null, 2) + '\n');
  fs.writeFileSync(path.join(output, 'seed-planes.bin'), initial);
  fs.writeFileSync(path.join(output, 'frames.planes'), Buffer.concat(planarFrames));
  fs.writeFileSync(path.join(output, 'book.bin'), book);
  fs.writeFileSync(path.join(output, 'topology.bin'), topology);
  const metadata = {
    frames: index.length, vertices, initialSeedBytes: initial.length,
    sharedBookBytes: book.length, sharedTopologyBytes: topology.length,
    firstTimedRecordIsNoop: true, recordBytes: source.length,
    subsequentBytes: {min: Math.min(...sourceIndex.slice(1).map(record => record.length)),
      mean: sourceIndex.slice(1).reduce((sum, record) => sum + record.length, 0) / (index.length - 1),
      max: Math.max(...sourceIndex.slice(1).map(record => record.length))},
    abi: '91 high/even-low/odd nibble token bytes; escape15 signed8 dx,dy pairs in vertex order; 13 visibility bytes; LE16 visible white-face count. Initial 728-byte planar XY state and global topology/book are separate static assets.',
    hashes: {source: sha(source), initial: sha(initial), book: sha(book), topology: sha(topology)}
  };
  fs.writeFileSync(path.join(output, 'metadata.json'), JSON.stringify(metadata, null, 2) + '\n');
  console.log(JSON.stringify(metadata, null, 2));
  return metadata;
}

module.exports = {main, planes};
if (require.main === module) main();
