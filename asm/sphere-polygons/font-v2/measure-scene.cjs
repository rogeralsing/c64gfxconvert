'use strict';

// Measure every unique screen, starting with an implicit blank screen.
// A repeating suffix adds its outgoing last-to-loop-start delta exactly once.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {encodeSparse, decodeSparse} = require('./large-benchmark/delta-study.cjs');
const {encodeGroups, decodeGroups} = require('./large-benchmark/codegen-study.cjs');
const {encodePairs, decodePairs} = require('../precomputed/hybrid/delta.cjs');

const here = __dirname;
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const statistics = values => values.length ? {min: Math.min(...values), mean: values.reduce((sum, value) => sum + value, 0) / values.length, max: Math.max(...values)} : null;
const codecs = {
  sparse: {encode: (previous, target) => encodeSparse(target, previous), decode: (bytes, previous) => decodeSparse(bytes, previous)},
  literal: {encode: (previous, target) => encodePairs(target, previous), decode: (bytes, previous) => decodePairs(bytes, previous)},
  groups: {encode: (previous, target) => encodeGroups(previous, target, false), decode: (bytes, previous) => decodeGroups(bytes, previous, false)},
  hybrid: {encode: (previous, target) => encodeGroups(previous, target, true), decode: (bytes, previous) => decodeGroups(bytes, previous, true)}
};

function main(argv = process.argv.slice(2)) {
  const option = (name, fallback) => argv.find(value => value.startsWith(`--${name}=`))?.slice(name.length + 3) || fallback;
  const input = path.resolve(option('input', path.join(here, 'build/scenes/spiral')));
  const output = path.resolve(option('output', path.join(here, 'build/scene-storage/spiral')));
  const selectedCodec = option('codec', 'all');
  assert(selectedCodec === 'all' || Object.hasOwn(codecs, selectedCodec), 'Unknown scene codec.');
  const selected = Object.entries(codecs).filter(([name]) => selectedCodec === 'all' || name === selectedCodec);
  const metadata = JSON.parse(fs.readFileSync(path.join(input, 'metadata.json')));
  const scene = JSON.parse(fs.readFileSync(path.join(input, 'scene.json')));
  const raw = fs.readFileSync(path.join(input, 'reference.frames'));
  const font = fs.readFileSync(path.join(input, 'font.bin'));
  assert.equal(raw.length % 1000, 0);
  assert(font.length >= 1344 && font.length <= 2048 && font.length % 8 === 0);
  if (metadata.fontMode === 'fixed256') assert.equal(font.length, 2048, 'A fixed256 film must ship all 256 glyphs.');
  else assert.equal(sha(font.subarray(0, 1344)), '68ad34844c8a998f5270c31bc16962545f6c3232555fa03f9faec134c21c5b59');
  const frameCount = raw.length / 1000;
  const poses = Array.isArray(scene) ? scene : scene.frames;
  assert.equal(poses.length, frameCount);
  const fps = metadata.fps || scene.fps || 25;
  const loop = scene.loop || metadata.loop || null;
  if (loop) {
    assert(Number.isInteger(loop.startFrame) && loop.startFrame > 0);
    assert(Number.isInteger(loop.frameCount) && loop.frameCount > 1);
    assert.equal(loop.startFrame + loop.frameCount, frameCount);
    assert.equal(metadata.verification.loopEndpointMatchesStart, true,
      'The separately rendered loop endpoint must exactly match the first loop frame.');
    assert.equal(metadata.verification.loopUnwrappedPeriodMatchesStart, true,
      'The full unwrapped own-axis rotation period must reproduce the first loop image.');
  }
  const frames = Array.from({length: frameCount}, (_, index) => raw.subarray(index * 1000, (index + 1) * 1000));
  assert(frames[0].every(code => code === 0), 'The first image must be an entirely empty screen.');
  assert(raw.every(code => code < font.length / 8));
  fs.mkdirSync(output, {recursive: true});
  fs.writeFileSync(path.join(output, 'font.bin'), font);
  fs.writeFileSync(path.join(output, 'reference.frames'), raw);
  const edges = Array.from({length: frameCount - 1}, (_, fromPose) => ({fromPose, targetPose: fromPose + 1, closing: false}));
  if (loop) edges.push({fromPose: frameCount - 1, targetPose: loop.startFrame, closing: true});
  const changes = [], phases = [];
  for (const edge of edges) {
    const {fromPose, targetPose} = edge;
    changes.push(frames[targetPose].reduce((sum, code, cell) => sum + (code !== frames[fromPose][cell]), 0));
    const frame = poses[targetPose];
    phases.push(frame.phase || ((frame.time ?? frame.t ?? targetPose / fps) < 3 ? 'grow' : 'hold'));
  }
  const formats = {};
  for (const [name, codec] of selected) {
    const chunks = [], index = [];
    let cursor = 0;
    let actual = Buffer.alloc(1000);
    for (const edge of edges) {
      const {fromPose, targetPose} = edge;
      const payload = Buffer.from(codec.encode(frames[fromPose], frames[targetPose]));
      actual = Buffer.from(codec.decode(payload, actual));
      assert(actual.equals(frames[targetPose]), `${name}: playback differs at frame ${targetPose}`);
      index.push({...edge, offset: cursor, bytes: payload.length});
      chunks.push(payload); cursor += payload.length;
    }
    const data = Buffer.concat(chunks);
    fs.writeFileSync(path.join(output, name + '.bin'), data);
    fs.writeFileSync(path.join(output, name + '-index.json'), JSON.stringify(index, null, 2) + '\n');
    const phaseStats = {};
    for (const phase of new Set(phases)) {
      const selected = index.filter((record, row) => phases[row] === phase);
      const updateCounts = changes.filter((count, row) => phases[row] === phase);
      phaseStats[phase] = {transitions: selected.length, bytes: selected.reduce((sum, record) => sum + record.bytes, 0),
        bytesPerFrame: statistics(selected.map(record => record.bytes)), changedCharactersPerFrame: statistics(updateCounts)};
    }
    const introPayloadBytes = loop ? index.filter(row => row.fromPose < loop.startFrame).reduce((sum, row) => sum + row.bytes, 0) : data.length;
    const loopPayloadBytes = loop ? index.filter(row => row.fromPose >= loop.startFrame).reduce((sum, row) => sum + row.bytes, 0) : 0;
    const closingPatchBytes = loop ? index.at(-1).bytes : 0;
    formats[name] = {payloadBytes: data.length, pointerTableBytes: frameCount * 2,
      totalAnimationBytesWithPointers: data.length + frameCount * 2,
      totalAnimationAndFontBytes: data.length + frameCount * 2 + font.length,
      originalUncompressedScreenBytes: raw.length,
      implicitInitialBlankScreenBytes: 0,
      sourceCapacityBytes: 40960, fitsSourceCapacity: data.length <= 40960,
      unusedSourceBytes: 40960 - data.length,
      bytesPerFrame: statistics(index.map(record => record.bytes)), phaseStats,
      sourceSha256: sha(data), transitionsVerified: index.length,
      introPayloadBytes, loopPayloadBytes, closingPatchBytes,
      loopEntryPayloadBytes: loop ? index[loop.startFrame - 1].bytes : 0,
      introAccounting: 'The one-time intro includes its transition into the first loop image; the repeating suffix includes all outgoing loop deltas and its closing delta.',
      finiteClip: !loop, closingPatchIncluded: Boolean(loop)};
  }
  const report = {pass: true, frameCount, fps, nominalDurationSeconds: frameCount / fps,
    fontGlyphs: font.length / 8, fontBytes: font.length,
    firstImageIsImplicitBlank: true, uncompressedFramesBytes: raw.length,
    introSeconds: scene.introSeconds ?? frameCount / fps,
    loop: loop ? {...loop, durationSeconds: loop.frameCount / fps} : null,
    changedCharactersPerTransition: statistics(changes), formats,
    hashes: {font: sha(font), reference: sha(raw)},
    sourceScene: path.relative(here, input), sourceMetadata: metadata,
    capacityScope: loop ? 'All unique intro and loop screens. The first screen is cleared at startup. The last stored patch returns to the first loop frame; the intro is never repeated.' : 'Entire finite scene. The first screen is cleared at startup; only frame0-to1 through penultimate-to-final deltas are stored. No final-to-first closing patch.',
    runtimeScope: 'No Huffman or disk loading. Offline exact character data only; native player and working-memory costs are measured by the scene-player build.',
    nativeTimingMeasured: false};
  fs.writeFileSync(path.join(output, 'study.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({pass: true, frameCount, fps, nominalDurationSeconds: frameCount / fps,
    changedCharactersPerTransition: report.changedCharactersPerTransition,
    formats: Object.fromEntries(Object.entries(formats).map(([name, record]) => [name,
      {payloadBytes: record.payloadBytes, totalAnimationAndFontBytes: record.totalAnimationAndFontBytes,
        bytesPerFrame: record.bytesPerFrame, phaseStats: record.phaseStats}]))}, null, 2));
  return report;
}

module.exports = {main};
if (require.main === module) main();
