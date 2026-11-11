'use strict';

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {spawnSync} = require('node:child_process');

const here = __dirname;
const assets = path.join(here, 'build/geometry');
const output = path.join(here, 'build/native-geometry');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const hex = value => '$' + value.toString(16);

function compressFrame(raw) {
  const parts = [raw.subarray(0, 2)];
  let cursor = 2;
  const faces = raw.readUInt16LE(0);
  for (let face = 0; face < faces; face++) {
    const first = raw[cursor++], count = raw[cursor++];
    parts.push(Buffer.from([first, count]));
    let previousLeft, previousRight;
    for (let sample = 0; sample < count; sample++) {
      const left = raw.readUInt16LE(cursor), right = raw.readUInt16LE(cursor + 2);
      const absolute = raw.subarray(cursor, cursor + 4);
      cursor += 4;
      const dl = left - previousLeft, dr = right - previousRight;
      if (sample === 0) parts.push(absolute);
      else if (dl >= -7 && dl <= 7 && dr >= -7 && dr <= 7) parts.push(Buffer.from([(dl + 7) | (dr + 7) << 4]));
      else parts.push(Buffer.from([255]), absolute);
      previousLeft = left; previousRight = right;
    }
  }
  assert.equal(cursor, raw.length);
  return Buffer.concat(parts);
}

function decompressFrame(packed) {
  let cursor = 2;
  const parts = [packed.subarray(0, 2)];
  for (let face = 0; face < packed.readUInt16LE(0); face++) {
    const first = packed[cursor++], count = packed[cursor++];
    parts.push(Buffer.from([first, count]));
    let left, right;
    for (let sample = 0; sample < count; sample++) {
      if (sample === 0 || packed[cursor] === 255) {
        if (sample !== 0) cursor++;
        left = packed.readUInt16LE(cursor); right = packed.readUInt16LE(cursor + 2); cursor += 4;
      } else {
        const delta = packed[cursor++]; left += (delta & 15) - 7; right += (delta >>> 4) - 7;
      }
      const bytes = Buffer.alloc(4); bytes.writeUInt16LE(left); bytes.writeUInt16LE(right, 2); parts.push(bytes);
    }
  }
  assert.equal(cursor, packed.length);
  return Buffer.concat(parts);
}

function main(argv = process.argv.slice(2)) {
  const option = (name, fallback) => argv.find(value => value.startsWith(`--${name}=`))?.split('=')[1] ?? fallback;
  const source = option('source', 'packed'), fill = option('fill', 'fast');
  assert(['raw', 'packed', 'edges', 'xy-delta', 'edge-paths'].includes(source));
  assert(['individual', 'fast'].includes(fill));
  const kind = {raw: 0, edges: 1, packed: 2, 'xy-delta': 3, 'edge-paths': 4}[source];
  fs.mkdirSync(output, {recursive: true});
  const raw = fs.readFileSync(path.join(assets, 'frames.spans'));
  const rawIndex = JSON.parse(fs.readFileSync(path.join(assets, 'spans-index.json')));
  const frames = rawIndex.map(record => raw.subarray(record.offset, record.offset + record.length));
  let selectedFrames;
  if (source === 'packed') {
    selectedFrames = frames.map(frame => {
      const compressed = compressFrame(frame);
      assert(decompressFrame(compressed).equals(frame), 'Compressed spans did not reproduce the raw face crossings');
      return compressed;
    });
  } else if (source === 'raw') selectedFrames = frames;
  else if (source === 'edges') {
    const edgeRaw = fs.readFileSync(path.join(assets, 'frames.edges'));
    const edgeIndex = JSON.parse(fs.readFileSync(path.join(assets, 'edges-index.json')));
    selectedFrames = edgeIndex.map(record => edgeRaw.subarray(record.offset, record.offset + record.length));
  } else if (source === 'xy-delta') {
    const xyRaw = fs.readFileSync(path.join(here, 'build/native-xy/frames.source'));
    const xyIndex = JSON.parse(fs.readFileSync(path.join(here, 'build/native-xy/index.json')));
    selectedFrames = xyIndex.map(record => xyRaw.subarray(record.offset, record.offset + record.length));
  } else {
    const edgeRaw = fs.readFileSync(path.join(here, 'build/edge-paths/frames.edgepaths'));
    const edgeIndex = JSON.parse(fs.readFileSync(path.join(here, 'build/edge-paths/index.json')));
    selectedFrames = edgeIndex.map(record => edgeRaw.subarray(record.offset, record.offset + record.length));
  }
  const staticStart = 0x4000;
  const staticBytes = 256 + 24 + 24 + 75 + 75 + 75 + 75 + 16 + 16 +
    fs.statSync(path.join(assets, 'clip-records.bin')).size + fs.statSync(path.join(assets, 'limb-remap.bin')).size;
  const movieAddress = (staticStart + staticBytes + 255) & ~255;
  const sourceCapacity = 0xd000 - movieAddress;
  assert(Math.max(...selectedFrames.map(frame => frame.length)) <= sourceCapacity);
  fs.writeFileSync(path.join(output, 'initial-frame.bin'), selectedFrames[0]);
  fs.writeFileSync(path.join(output, 'frames-source.bin'), Buffer.concat(selectedFrames));
  let offset = 0;
  const sourceIndex = selectedFrames.map((frame, pose) => {
    const record = {pose, offset, length: frame.length}; offset += frame.length; return record;
  });
  fs.writeFileSync(path.join(output, 'source-index.json'), JSON.stringify(sourceIndex, null, 2) + '\n');
  fs.writeFileSync(path.join(output, 'config.inc'), [
    `.const SOURCE_KIND = ${kind}`,
    `.const FAST_FILL = ${fill === 'fast'}`,
    `.const CLIP_RECORD_COUNT = ${fs.statSync(path.join(assets, 'clip-records.bin')).size / 4}`,
    `.const MOVIE_ADDRESS = ${hex(movieAddress)}`,
    ''
  ].join('\n'));
  const edgeInclude = kind === 4 ? '.import source "../../edge-atlas-source.asm"\nprepare_initial_source:\n' : '.import source "../../edge-source.asm"\n';
  fs.writeFileSync(path.join(output, 'selected-edge.asm'), kind === 1 || kind === 3 || kind === 4 ? edgeInclude : 'prepare_source: rts\nprepare_face: rts\nprepare_initial_source:\n');
  const assembler = process.env.KICKASS || '/Users/rogerjohansson/.local/bin/kickass';
  const built = spawnSync('rtk', ['proxy', assembler, 'geometry-player.asm', '-odir', output, '-o', path.join(output, 'player.prg'), '-debugdump', '-debug', '-symbolfile', '-vicesymbols'], {cwd: here, stdio: 'inherit'});
  if (built.status !== 0) throw new Error(`Assembler failed (${built.status ?? built.signal})`);
  const symbols = fs.readFileSync(path.join(output, 'geometry-player.sym'), 'utf8');
  const labels = Object.fromEntries(Array.from(symbols.matchAll(/\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)/g), match => [match[1], parseInt(match[2], 16)]));
  const lengths = selectedFrames.map(frame => frame.length);
  let prefixFrames = 0, prefixBytes = 0;
  while (prefixFrames < lengths.length && prefixBytes + lengths[prefixFrames] <= sourceCapacity) prefixBytes += lengths[prefixFrames++];
  const fontBytes = fs.statSync(path.join(assets, 'font.bin')).size;
  const codeBytes = labels.player_code_end - labels.start;
  const edgeCodeBytes = labels.edge_code_end ? labels.edge_code_end - 0xe000 : 0;
  const manifest = {
    source, fill, sourceKind: kind, settings: JSON.parse(fs.readFileSync(path.join(assets, 'metadata.json'))).settings,
    poseCount: selectedFrames.length, fontBytes, codeBytes, edgeCodeBytes,
    compactXyStaticBytesIncludedInEdgeSection: kind === 3 ? 728 + 30 + 480 : 0,
    lookupAndRemapBytes: staticBytes, movieAddress, movieLimit: 0xd000, sourceCapacity,
    frameSourceBytes: {min: Math.min(...lengths), mean: lengths.reduce((sum, value) => sum + value, 0) / lengths.length, max: Math.max(...lengths), total: lengths.reduce((sum, value) => sum + value, 0)},
    capacity: {actualPrefixFrames: prefixFrames, actualPrefixSourceBytes: prefixBytes, uniformMeanEstimateFrames: Math.floor(sourceCapacity / (lengths.reduce((sum, value) => sum + value, 0) / lengths.length)), pointerTableNotIncluded: true, note: 'Sequential records need no per-frame pointers. This benchmark loads one frame; capacity describes a sequential source movie within the same layout.'},
    runtime: {screenBytes: 2048, coverageBytes: 1024, spanArrayBytes: 4 * 75, zeroPageBytes: 31 + (kind === 1 || kind === 3 || kind === 4 ? 17 : 0), colorRamBytes: 1000, compactXyBytes: kind === 3 ? 728 + 91 + 13 : 0},
    programBytes: fs.statSync(path.join(output, 'player.prg')).size,
    hashes: {program: sha(fs.readFileSync(path.join(output, 'player.prg'))), font: sha(fs.readFileSync(path.join(assets, 'font.bin'))), source: sha(Buffer.concat(selectedFrames))},
    timingVerified: false
  };
  fs.writeFileSync(path.join(output, 'build.json'), JSON.stringify(manifest, null, 2) + '\n');
  const destination = path.join(output, 'variants', `${source}-${fill}`);
  fs.mkdirSync(destination, {recursive: true});
  for (const name of ['player.prg', 'geometry-player.sym', 'build.json', 'frames-source.bin', 'source-index.json']) fs.copyFileSync(path.join(output, name), path.join(destination, name));
  console.log(JSON.stringify(manifest, null, 2));
  return manifest;
}

module.exports = {main, compressFrame, decompressFrame};
if (require.main === module) main();
