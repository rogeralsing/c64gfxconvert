'use strict';

// The reference corpus is the exact fixed-font HTML output. Codecs operate on
// 1,000 character codes; reference pixels are never part of native playback.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const delta = require('../../precomputed/hybrid/delta.cjs');
const rle = require('../../precomputed/hybrid/baseline-rle.cjs');

const HERE = __dirname;
const OUT = path.join(HERE, 'build', 'delta');
const SCREEN = 1000;
const ARENA_START = 0x3000;
const ARENA_END = 0xd000;
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const summary = values => ({min: Math.min(...values), mean: values.reduce((a, b) => a + b, 0) / values.length, max: Math.max(...values)});

function encodeSparse(target, previous, xor = false) {
  const bytes = [];
  for (let page = 0; page < 4; page++) {
    const pairs = [];
    for (let offset = 0; offset < Math.min(256, SCREEN - page * 256); offset++) {
      const cell = page * 256 + offset;
      if (target[cell] !== previous[cell]) pairs.push(offset, xor ? target[cell] ^ previous[cell] : target[cell]);
    }
    assert(pairs.length < 512, 'Sparse count8 supports at most 255 updates per page');
    bytes.push(pairs.length / 2, ...pairs);
  }
  return Buffer.from(bytes);
}

function decodeSparse(payload, previous, xor = false) {
  const output = Buffer.from(previous);
  let read = 0;
  for (let page = 0; page < 4; page++) {
    const count = payload[read++];
    for (let pair = 0; pair < count; pair++) {
      const offset = payload[read++], value = payload[read++];
      assert(offset < Math.min(256, SCREEN - page * 256));
      const cell = page * 256 + offset;
      output[cell] = xor ? output[cell] ^ value : value;
    }
  }
  assert.equal(read, payload.length);
  return output;
}

function maxPrefix(payloads, capacity = ARENA_END - ARENA_START) {
  let bytes = 0, frames = 1;
  for (const payload of payloads.slice(0, -1)) {
    if (bytes + payload.length > capacity) break;
    bytes += payload.length;
    frames++;
  }
  return {frames, transitions: frames - 1, payloadBytes: bytes, remainingArenaBytes: capacity - bytes,
    secondsAt25Fps: frames / 25, secondsAt50Fps: frames / 50,
    angularRangeDegrees: (frames - 1) * 360 / payloads.length,
    initialRawScreenBytesOutsideArena: SCREEN, pointerBytesOutsideArena: frames * 2};
}

function corpus(options = {}) {
  const source = path.join(HERE, '..', 'c64-preview', 'build');
  const raw = fs.readFileSync(options.framesPath || path.join(source, 'movie.frames'));
  const font = fs.readFileSync(path.join(source, 'font.bin'));
  assert.equal(raw.length, 384000);
  assert.equal(font.length, 2048);
  assert.equal(sha(font), 'e4071e1e3176e3ee65eeb5fc2df5bb3eccab7b733b9ea7cbb276a2f3a65a1aac');
  const frames = Array.from({length: raw.length / SCREEN}, (_, i) => raw.subarray(i * SCREEN, (i + 1) * SCREEN));
  return {raw, font, frames, source};
}

function main(options = {}) {
  const output = options.output || OUT;
  fs.mkdirSync(output, {recursive: true});
  const {raw, font, frames, source} = corpus(options);
  const metadata = JSON.parse(fs.readFileSync(path.join(source, 'metadata.json')));
  const encoded = {packets: [], sparse: [], rle: []};
  const writes = [], changes = [];
  for (let i = 0; i < frames.length; i++) {
    const previous = frames[i], target = frames[(i + 1) % frames.length];
    const stats = {};
    const packets = Buffer.from(delta.encodePackets(target, previous));
    assert(Buffer.from(delta.decodePackets(packets, previous, stats)).equals(target));
    const sparse = encodeSparse(target, previous);
    assert(decodeSparse(sparse, previous).equals(target));
    const key = Buffer.from(rle.encode(target));
    assert(Buffer.from(rle.decode(key)).equals(target));
    encoded.packets.push(packets);
    encoded.sparse.push(sparse);
    encoded.rle.push(key);
    writes.push(stats.written);
    changes.push(target.reduce((sum, value, cell) => sum + (value !== previous[cell]), 0));
  }
  const report = {
    pass: true, settings: metadata.settings, frames: frames.length,
    imageSource: options.framesPath ? 'Flat 200-face geometry, eight-probe coverage and selected font' : 'Analytic sphere, exact HTML matching-renderer character screens',
    motion: 'Existing camera-Y rotation of the tilted sphere; 384 distinct poses over 360 degrees. No own-axis symmetry substitution.',
    sourceScreensSha256: sha(raw), fontSha256: sha(font), screenBytes: SCREEN, fontBytes: font.length,
    arena: {start: ARENA_START, endExclusive: ARENA_END, bytes: ARENA_END - ARENA_START,
      otherReserved: 'Code and pointer tables $1000-$1fff, font $2000-$27ff, raw first screen $2800-$2be7; working screens below $1000.'},
    changedCharacters: summary(changes), packetWrittenCharacters: summary(writes),
    formats: {}, nativeTimingMeasuredBy: 'verify-delta.py; this storage study contains no inferred native FPS.'
  };
  for (const [name, payloads] of Object.entries(encoded)) {
    let offset = 0;
    const index = payloads.map(payload => {
      const record = {offset, bytes: payload.length};
      offset += payload.length;
      return record;
    });
    fs.writeFileSync(path.join(output, `${name}.bin`), Buffer.concat(payloads));
    fs.writeFileSync(path.join(output, `${name}-index.json`), JSON.stringify(index));
    report.formats[name] = {cyclicPayloadBytes: offset, cyclicPointerBytes: payloads.length * 2,
      totalFullTurnWithRawSeedAndFont: offset + payloads.length * 2 + SCREEN + font.length,
      payloadBytes: summary(payloads.map(payload => payload.length)), maximumPrefix: maxPrefix(payloads),
      nativeImplementation: name !== 'rle'};
  }
  fs.writeFileSync(path.join(output, 'font.bin'), font);
  fs.writeFileSync(path.join(output, 'reference.frames'), raw);
  fs.writeFileSync(path.join(output, 'study.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report, null, 2));
  return report;
}

module.exports = {main, corpus, encodeSparse, decodeSparse, maxPrefix, OUT, ARENA_START, ARENA_END, summary, sha};
if (require.main === module) {
  const geometry = process.argv.includes('--geometry');
  main(geometry ? {framesPath: path.join(HERE, 'build/geometry/frames.screen'), output: path.join(OUT, 'geometry-storage')} : {});
}
