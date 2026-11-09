'use strict';

// Host-side export of the HTML matching renderer. The C64 only needs the fixed
// character set and the resulting 40 x 25 screen codes, never the reference pixels.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {generateFont, toBytes} = require('../font.cjs');
const {buildBrowserSource} = require('../browser-font.cjs');
const {encodePackets, decodePackets} = require('../../precomputed/hybrid/delta.cjs');

const OUTPUT = path.join(__dirname, 'build');
const FRAME_COUNT = 384;
const INITIAL_ANGLE = 0.38;
const SETTINGS = Object.freeze({checks: 20, radius: 145, tilt: 65, solid: false});
const EXPECTED_FONT_SHA256 = 'e4071e1e3176e3ee65eeb5fc2df5bb3eccab7b733b9ea7cbb276a2f3a65a1aac';
const sha256 = value => crypto.createHash('sha256').update(value).digest('hex');
const summarize = values => ({min: Math.min(...values), mean: values.reduce((a, b) => a + b, 0) / values.length, max: Math.max(...values)});

function reconstruct(screen, charset) {
  const pixels = Buffer.alloc(320 * 200);
  for (let cell = 0; cell < screen.length; cell++) {
    const left = (cell % 40) * 8, top = Math.floor(cell / 40) * 8;
    for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
      pixels[(top + y) * 320 + left + x] = (charset[screen[cell] * 8 + y] >>> (7 - x)) & 1;
    }
  }
  return pixels;
}

function differences(a, b) {
  let count = 0;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) count++;
  return count;
}

function main() {
  fs.mkdirSync(OUTPUT, {recursive: true});
  const sourceNames = ['font.cjs', 'general-palette.json', 'browser-font.cjs', 'matching/direct-core.js', 'matching/sphere-renderer.js'];
  const sources = sourceNames.map(name => ({name, sha256: sha256(fs.readFileSync(path.join(__dirname, '..', name)))}));
  const palette = generateFont(), charset = toBytes(palette);
  assert.equal(palette.usedCount, 256);
  assert.equal(charset.length, 2048);
  assert.equal(sha256(charset), EXPECTED_FONT_SHA256);
  const context = vm.createContext({});
  vm.runInContext(buildBrowserSource(palette), context, {filename: 'browser-font.generated.js'});
  for (const name of ['matching/direct-core.js', 'matching/sphere-renderer.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', name), 'utf8'), context, {filename: name});
  }
  const font = context.GlyphMath.generateFont(256);
  const renderer = new context.SphereMath.SphereRenderer();
  const frames = [], mismatchCounts = [], edgeCounts = [], used = new Uint32Array(256);
  let firstBitmap, firstReference, firstStats;
  const started = process.hrtime.bigint();
  for (let index = 0; index < FRAME_COUNT; index++) {
    const stats = renderer.render({...SETTINGS, angle: INITIAL_ANGLE + index * 2 * Math.PI / FRAME_COUNT}, font);
    const screen = Buffer.from(renderer.screen);
    const bitmap = reconstruct(screen, charset);
    assert(bitmap.equals(Buffer.from(renderer.output)), `Fixed-font reconstruction mismatch at frame ${index}`);
    frames.push(screen);
    mismatchCounts.push(stats.mismatches);
    edgeCounts.push(screen.reduce((sum, code) => sum + (code !== 0 && code !== 15), 0));
    for (const code of screen) used[code]++;
    if (index === 0) {
      firstBitmap = bitmap;
      firstReference = Buffer.from(renderer.source);
      firstStats = {mismatches: stats.mismatches, normalizedError: stats.normalizedError, fullFrameError: stats.fullFrameError, usedCount: stats.usedCount, activeCells: stats.activeCells, surfacePixels: stats.surfacePixels};
    }
    if (index % 64 === 63) console.log(`Rendered and reconstructed ${index + 1}/${FRAME_COUNT} frames.`);
  }
  renderer.render({...SETTINGS, angle: INITIAL_ANGLE + 2 * Math.PI}, font);
  assert(Buffer.from(renderer.screen).equals(frames[0]), 'Full 360-degree screen closure failed');
  assert(Buffer.from(renderer.source).equals(firstReference), 'Full 360-degree reference closure failed');
  renderer.render({...SETTINGS, angle: INITIAL_ANGLE + 2 * Math.PI / 10}, font);
  const shortTurn = {degrees: 36, differentChars: differences(frames[0], renderer.screen), differentReferencePixels: differences(firstReference, renderer.source)};
  assert(shortTurn.differentChars > 0, 'Unexpected 36-degree screen repetition');

  const changes = [], patchSizes = [], packetParts = [frames[0]];
  let packetWrites = 0, packetCount = 0;
  // movie.delta: raw first screen, then LE16 length + delta packet stream for
  // frames 1..383, then frame 0. Repeating those 384 records loops exactly.
  for (let next = 1; next <= FRAME_COUNT; next++) {
    const target = frames[next % FRAME_COUNT], previous = frames[next - 1];
    changes.push(differences(target, previous));
    const payload = Buffer.from(encodePackets(target, previous));
    const stats = {};
    assert(Buffer.from(decodePackets(payload, previous, stats)).equals(target), `Delta roundtrip mismatch at frame ${next}`);
    const length = Buffer.alloc(2);
    length.writeUInt16LE(payload.length);
    packetParts.push(length, payload);
    patchSizes.push(payload.length);
    packetWrites += stats.written || 0;
    packetCount += stats.packets || 0;
  }
  const movie = Buffer.concat(frames), packetMovie = Buffer.concat(packetParts);
  const firstPgm = Buffer.concat([Buffer.from('P5\n320 200\n255\n'), Buffer.from(Uint8Array.from(firstBitmap, value => value * 255))]);
  fs.writeFileSync(path.join(OUTPUT, 'font.bin'), charset);
  fs.writeFileSync(path.join(OUTPUT, 'frame0.screen'), frames[0]);
  fs.writeFileSync(path.join(OUTPUT, 'frame0.bitmap'), firstBitmap);
  fs.writeFileSync(path.join(OUTPUT, 'frame0.pgm'), firstPgm);
  fs.writeFileSync(path.join(OUTPUT, 'movie.frames'), movie);
  fs.writeFileSync(path.join(OUTPUT, 'movie.delta'), packetMovie);
  const metadata = {
    settings: {...SETTINGS, checkerRows: SETTINGS.checks / 2, diameter: SETTINGS.radius * 2, initialAngleRadians: INITIAL_ANGLE, grid: false, fontGlyphs: 256},
    screen: {columns: 40, rows: 25, pixelWidth: 320, pixelHeight: 200, background: 0, foreground: 1, emptyGlyph: 0, filledGlyph: 15},
    font: {bytes: charset.length, sha256: sha256(charset), browserSignature: font.signature, immutableForAllFrames: true},
    sources,
    frame0: {...firstStats, screenSha256: sha256(frames[0]), bitmapSha256: sha256(firstBitmap), referenceSha256: sha256(firstReference)},
    animation: {frames: FRAME_COUNT, rotationDegrees: 360, stepDegrees: 360 / FRAME_COUNT, secondsAt25Fps: FRAME_COUNT / 25, fullTurnClosure: true, shortTurn, changedCharsPerCyclicFrame: summarize(changes), edgeCharsPerFrame: summarize(edgeCounts), mismatchPixelsPerFrame: summarize(mismatchCounts), glyphsUsed: used.reduce((sum, count) => sum + (count > 0), 0)},
    files: {
      'font.bin': {bytes: charset.length, sha256: sha256(charset)},
      'frame0.screen': {bytes: frames[0].length, sha256: sha256(frames[0])},
      'frame0.bitmap': {bytes: firstBitmap.length, sha256: sha256(firstBitmap), format: '320x200 row-major bytes, zero or one, reconstructed from fixed font and screen'},
      'movie.frames': {bytes: movie.length, sha256: sha256(movie), format: '384 consecutive 1000-byte character screens'},
      'movie.delta': {bytes: packetMovie.length, sha256: sha256(packetMovie), format: '1000-byte initial screen; 384 records of LE16 length and delta-packets64 payload for 1..383,0; repeat records to loop'}
    },
    compression: {codec: 'delta-packets64', lag: 1, initialRawScreenBytes: 1000, cyclicPatchRecords: FRAME_COUNT, payloadBytes: patchSizes.reduce((a, b) => a + b, 0), recordLengthBytes: FRAME_COUNT * 2, totalBytes: packetMovie.length, totalWithFontBytes: packetMovie.length + charset.length, patchPayloadBytes: summarize(patchSizes), meanWrittenCharsPerFrame: packetWrites / FRAME_COUNT, meanPacketsPerFrame: packetCount / FRAME_COUNT, patchSizes},
    verification: {glyphOnlyReconstructionFrames: FRAME_COUNT, deltaRoundtripFrames: FRAME_COUNT, referencePixelsAreNotUsedDuringPlayback: true, hostSeconds: Number(process.hrtime.bigint() - started) / 1e9, c64TimingMeasured: false}
  };
  fs.writeFileSync(path.join(OUTPUT, 'metadata.json'), JSON.stringify(metadata, null, 2) + '\n');
  console.log(JSON.stringify({...metadata, sources: undefined, compression: {...metadata.compression, patchSizes: undefined}}, null, 2));
  return metadata;
}

module.exports = {main, reconstruct};
if (require.main === module) main();
