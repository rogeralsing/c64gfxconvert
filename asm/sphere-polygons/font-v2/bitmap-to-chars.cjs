'use strict';

// Whole-image bitmap matching against the existing immutable coarse font.
// This deliberately has no sphere mask, geometry, or fine-font remapping.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const os = require('node:os');
const {execFileSync} = require('node:child_process');
const {generateFont, toBytes} = require('./font.cjs');
const {dedupe} = require('./font4-dedupe.cjs');

const WIDTH = 320, HEIGHT = 200, PIXELS = WIDTH * HEIGHT;
const FONT_SHA = '68ad34844c8a998f5270c31bc16962545f6c3232555fa03f9faec134c21c5b59';
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const popcount = value => {
  value -= (value >>> 1) & 0x55555555;
  value = (value & 0x33333333) + ((value >>> 2) & 0x33333333);
  return (((value + (value >>> 4)) & 0x0f0f0f0f) * 0x01010101) >>> 24;
};

function fixedFont() {
  const transformed = dedupe(toBytes(generateFont()));
  assert.equal(transformed.font.length, 1344);
  assert.equal(sha(transformed.font), FONT_SHA, 'The existing168-glyph font must remain unchanged.');
  return transformed;
}

function bitmapLayout(metadata, byteLength) {
  const {width, height, fps} = metadata;
  const frameCount = metadata.frameCount ?? metadata.count;
  assert(width === 320 && height === 200 || width === 160 && height === 100,
    'Packed bitmap dimensions must be320x200 or160x100.');
  assert(Number.isFinite(fps) && fps > 0, 'fps must be positive.');
  assert(Number.isInteger(frameCount) && frameCount > 0, 'frameCount must be a positive integer.');
  assert(metadata.bitOrder === undefined || metadata.bitOrder === 'MSB-first', 'Only MSB-first packed bits are supported.');
  const frameBytes = width * height / 8;
  assert.equal(byteLength, frameBytes * frameCount, 'Packed movie byte length must exactly match dimensions and frameCount.');
  return {width, height, fps, frameCount, frameBytes, scale: WIDTH / width};
}

function unpackFrame(packed, width, height) {
  assert(width === 320 && height === 200 || width === 160 && height === 100);
  assert.equal(packed.length, width * height / 8, 'Incorrect packed frame length.');
  const output = Buffer.alloc(PIXELS), scale = WIDTH / width, stride = width / 8;
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const value = (packed[y * stride + (x >>> 3)] >>> (7 - (x & 7))) & 1;
    for (let dy = 0; dy < scale; dy++) for (let dx = 0; dx < scale; dx++) output[(y * scale + dy) * WIDTH + x * scale + dx] = value;
  }
  return output;
}

function createMatcher(font = fixedFont().font) {
  assert.equal(sha(font), FONT_SHA);
  const glyphs = Array.from({length: font.length / 8}, (_, code) => {
    const rows = font.subarray(code * 8, code * 8 + 8);
    return {lo: rows.readUInt32LE(0), hi: rows.readUInt32LE(4), filled: rows.reduce((sum, row) => sum + popcount(row), 0)};
  });
  const cache = new Map();
  return function matchFrame(pixels, objectMask = null) {
    assert.equal(pixels.length, PIXELS);
    if (objectMask) assert.equal(objectMask.length, PIXELS);
    const screen = Buffer.alloc(1000), errors = Buffer.alloc(1000), usage = new Set();
    let mismatches = 0, whitePixels = 0, sourceWhitePixels = 0, exactCells = 0;
    let silhouetteSpill = 0, sourceWhiteOutsideMask = 0;
    for (let cell = 0; cell < 1000; cell++) {
      const left = cell % 40 * 8, top = Math.floor(cell / 40) * 8;
      let lo = 0, hi = 0, maskLo = 0, maskHi = 0;
      for (let row = 0; row < 8; row++) {
        let bits = 0, maskBits = objectMask ? 0 : 255;
        for (let x = 0; x < 8; x++) {
          bits |= pixels[(top + row) * WIDTH + left + x] << (7 - x);
          if (objectMask) maskBits |= objectMask[(top + row) * WIDTH + left + x] << (7 - x);
        }
        if (row < 4) lo |= bits << (row * 8);
        else hi |= bits << ((row - 4) * 8);
        if (row < 4) maskLo |= maskBits << (row * 8);
        else maskHi |= maskBits << ((row - 4) * 8);
      }
      const key = (lo >>> 0) + ':' + (hi >>> 0) + (objectMask ? '|' + (maskLo >>> 0) + ':' + (maskHi >>> 0) : '');
      let best = cache.get(key);
      if (!best) {
        best = {code: 0, error: 65};
        for (let code = 0; code < glyphs.length; code++) {
          if (objectMask && ((glyphs[code].lo & ~maskLo) !== 0 || (glyphs[code].hi & ~maskHi) !== 0)) continue;
          const error = popcount(lo ^ glyphs[code].lo) + popcount(hi ^ glyphs[code].hi);
          if (error < best.error) best = {code, error};
          if (error === 0) break;
        }
        if (cache.size >= 200000) cache.clear();
        cache.set(key, best);
      }
      screen[cell] = best.code; errors[cell] = best.error; usage.add(best.code);
      mismatches += best.error; whitePixels += glyphs[best.code].filled;
      sourceWhitePixels += popcount(lo) + popcount(hi);
      if (objectMask) {
        silhouetteSpill += popcount(glyphs[best.code].lo & ~maskLo) + popcount(glyphs[best.code].hi & ~maskHi);
        sourceWhiteOutsideMask += popcount(lo & ~maskLo) + popcount(hi & ~maskHi);
      }
      exactCells += Number(best.error === 0);
    }
    return {screen, errors, statistics: {mismatches, mismatchedPixels: mismatches,
      fullFrameError: mismatches / PIXELS, exactCells, usedCount: usage.size,
      sourceWhitePixels, outputWhitePixels: whitePixels, maxTileError: Math.max(...errors),
      silhouetteSpill: objectMask ? silhouetteSpill : null,
      sourceWhiteOutsideMask: objectMask ? sourceWhiteOutsideMask : null}};
  };
}

function selfTest() {
  // Construct packed bits independently, with explicit byte/bit boundary cases.
  for (const [width, height] of [[320, 200], [160, 100]]) {
    const packed = Buffer.alloc(width * height / 8), expected = Buffer.alloc(PIXELS);
    const points = [[0, 0], [7, 0], [8, 1], [width - 1, height - 1]];
    const scale = WIDTH / width;
    for (const [x, y] of points) {
      packed[(y * width + x) >>> 3] |= 0x80 >>> (x % 8);
      for (let dy = 0; dy < scale; dy++) for (let dx = 0; dx < scale; dx++) expected[(y * scale + dy) * WIDTH + x * scale + dx] = 1;
    }
    assert(unpackFrame(packed, width, height).equals(expected), 'MSB order or2x2 expansion differs.');
    assert.throws(() => bitmapLayout({width, height, fps: 25, frameCount: 2}, packed.length));
    assert.throws(() => unpackFrame(packed.subarray(1), width, height));
  }
  const {font} = fixedFont(), match = createMatcher(font);
  // Every existing glyph is encoded as a known packed bitmap and reconstructed.
  for (const [width, height] of [[320, 200], [160, 100]]) {
    const packed = Buffer.alloc(width * height / 8), scale = WIDTH / width;
    for (let code = 0; code < 168; code++) for (let row = 0; row < 8 / scale; row++) for (let x = 0; x < 8 / scale; x++) {
      const value = (font[code * 8 + row * scale] >>> (7 - x * scale)) & 1;
      const px = code % 40 * (8 / scale) + x, py = Math.floor(code / 40) * (8 / scale) + row;
      if (value) packed[(py * width + px) >>> 3] |= 0x80 >>> (px % 8);
    }
    const pixels = unpackFrame(packed, width, height), result = match(pixels), reconstructed = Buffer.alloc(PIXELS);
    for (let cell = 0; cell < 1000; cell++) for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) reconstructed[(Math.floor(cell / 40) * 8 + y) * WIDTH + cell % 40 * 8 + x] = (font[result.screen[cell] * 8 + y] >>> (7 - x)) & 1;
    assert(reconstructed.equals(pixels)); assert.equal(result.statistics.mismatches, 0);
    for (let code = 0; code < 168; code++) assert.equal(result.screen[code], code);
  }
  const checker = Buffer.alloc(PIXELS);
  for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) checker[y * WIDTH + x] = (x + y) & 1;
  const lossy = match(checker);
  assert.equal(lossy.screen[0], 0); assert.equal(lossy.errors[0], 32); assert.equal(lossy.statistics.mismatches, 32);
  // Identical targets under different masks must not share cached selections.
  const solid = Buffer.alloc(PIXELS), upper = Buffer.alloc(PIXELS), lower = Buffer.alloc(PIXELS);
  for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
    solid[y * WIDTH + x] = 1;
    (y < 4 ? upper : lower)[y * WIDTH + x] = 1;
  }
  const upperMatch = match(solid, upper), lowerMatch = match(solid, lower);
  assert.equal(match(solid).screen[0], 8);
  assert.notEqual(upperMatch.screen[0], lowerMatch.screen[0]);
  for (const [masked, mask] of [[upperMatch, upper], [lowerMatch, lower]]) {
    let misses = 0;
    for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
      const rendered = (font[masked.screen[0] * 8 + y] >>> (7 - x)) & 1;
      assert(rendered <= mask[y * WIDTH + x]); misses += 1 - rendered;
    }
    assert.equal(misses, 32); assert.equal(masked.statistics.mismatches, 32); assert.equal(masked.statistics.silhouetteSpill, 0);
  }
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'bitmap-to-chars-check-'));
  try {
    for (const [width, height] of [[320, 200], [160, 100]]) {
      const scale = WIDTH / width, frameBytes = width * height / 8;
      const packed = Buffer.alloc(frameBytes * 2);
      for (let y = 0; y < 8 / scale; y++) packed[frameBytes + y * width / 8] = scale === 1 ? 0xff : 0xf0;
      const input = path.join(fixture, `${width}.frames`), meta = path.join(fixture, `${width}.json`), output = path.join(fixture, `${width}-out`);
      fs.writeFileSync(input, packed); fs.writeFileSync(meta, JSON.stringify({name: 'fixture', width, height, fps: 25, frameCount: 2}));
      const argumentsForFixture = ['--frames', input, '--metadata', meta, '--output', output];
      const converted = JSON.parse(execFileSync(process.execPath, [__filename, ...argumentsForFixture], {encoding: 'utf8'}));
      const screens = fs.readFileSync(path.join(output, 'reference.frames'));
      assert.equal(screens.length, 2000); assert.equal(screens[1000], 8);
      assert(screens.subarray(0, 1000).every(code => code === 0));
      assert(screens.subarray(1001).every(code => code === 0));
      assert.equal(converted.totalMismatchedPixels, 0);
      assert.equal(converted.errorSummary.silhouetteSpill, null);
      assert.equal(converted.errorSummary.sourceWhiteOutsideMask, null);
      assert(fs.readFileSync(path.join(output, 'font.bin')).equals(font));
      const expectedIdeal = Buffer.alloc(PIXELS * 2);
      for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) expectedIdeal[PIXELS + y * WIDTH + x] = 1;
      assert(fs.readFileSync(path.join(output, 'ideal.frames')).equals(expectedIdeal));
      assert.deepEqual(JSON.parse(fs.readFileSync(path.join(output, 'playback.json'))), [{op: 'play', startFrame: 0, frameCount: 2, repeat: 1}, {op: 'hold'}]);
      const maskPath = path.join(fixture, `${width}-mask.frames`), maskedOutput = output + '-masked';
      fs.writeFileSync(maskPath, packed);
      fs.writeFileSync(meta, JSON.stringify({name: 'fixture', width, height, fps: 25, frameCount: 2, objectMaskFile: maskPath}));
      const withMask = JSON.parse(execFileSync(process.execPath, [__filename, '--frames', input, '--metadata', meta, '--output', maskedOutput, '--prepend-blank'], {encoding: 'utf8'}));
      const maskedScreens = fs.readFileSync(path.join(maskedOutput, 'reference.frames'));
      assert.equal(withMask.frameCount, 3); assert.equal(maskedScreens[2000], 8);
      assert(maskedScreens.subarray(0, 2000).every(code => code === 0));
      assert.equal(withMask.errorSummary.silhouetteSpill, 0);
      fs.writeFileSync(input, packed.subarray(1));
      assert.throws(() => execFileSync(process.execPath, [__filename, ...argumentsForFixture], {stdio: 'pipe'}));
    }
  } finally {fs.rmSync(fixture, {recursive: true, force: true});}
  const result = {pass: true, packedSizesTested: [[320, 200], [160, 100]], glyphsExactlyReconstructed: 168,
    msbOrderVerified: true, expansion2x2Verified: true, endToEndFilesVerified: true,
    mismatchLengthRejected: true, maskAdmissibilityAndCacheVerified: true, knownHammingError: 32, fontSha256: sha(font)};
  console.log(JSON.stringify(result, null, 2));
  return result;
}

function main(argv = process.argv.slice(2)) {
  if (argv.length === 1 && argv[0] === '--self-test') return selfTest();
  const options = {};
  for (let index = 0; index < argv.length; index++) {
    const [key, inline] = argv[index].split('=');
    assert(['--frames', '--metadata', '--output', '--prepend-blank', '--mask'].includes(key), 'Unknown option ' + key);
    if (key === '--prepend-blank') {assert(inline === undefined); options[key] = true;}
    else {options[key] = inline ?? argv[++index]; assert(options[key], 'Missing value for ' + key);}
  }
  assert(options['--frames'] && options['--metadata'], 'Use --frames /absolute/source.frames --metadata /absolute/metadata.json [--output DIRECTORY] [--prepend-blank] [--mask /absolute/mask.frames].');
  const framesPath = path.resolve(options['--frames']), metadataPath = path.resolve(options['--metadata']);
  const source = JSON.parse(fs.readFileSync(metadataPath)), packed = fs.readFileSync(framesPath);
  const layout = bitmapLayout(source, packed.length), prepend = Boolean(options['--prepend-blank']);
  const declaredMask = options['--mask'] || source.objectMaskFile;
  const maskPath = declaredMask ? path.resolve(path.dirname(metadataPath), declaredMask) : null;
  const packedMask = maskPath ? fs.readFileSync(maskPath) : null;
  if (packedMask) assert.equal(packedMask.length, packed.length, 'Object mask must use the same packed dimensions and frameCount as the source movie.');
  if (source.frames !== undefined) assert(Array.isArray(source.frames) && source.frames.length === layout.frameCount, 'Optional source.frames must describe every packed input frame.');
  const name = source.name || path.basename(framesPath, path.extname(framesPath));
  const safeName = name.replace(/[^a-zA-Z0-9_-]/g, '-');
  const output = path.resolve(options['--output'] || path.join(__dirname, 'build/bitmap-scenes', safeName));
  const {font, map} = fixedFont(), match = createMatcher(font);
  const count = layout.frameCount + Number(prepend), screens = Buffer.alloc(count * 1000), poses = [], statistics = [];
  const idealHash = crypto.createHash('sha256');
  fs.mkdirSync(output, {recursive: true});
  const idealFile = fs.openSync(path.join(output, 'ideal.frames'), 'w');
  const errorFile = fs.openSync(path.join(output, 'tile-errors.frames'), 'w');
  try {
    for (let index = 0; index < count; index++) {
      const sourceFrame = index - Number(prepend);
      const pixels = sourceFrame < 0 ? Buffer.alloc(PIXELS) : unpackFrame(packed.subarray(sourceFrame * layout.frameBytes, (sourceFrame + 1) * layout.frameBytes), layout.width, layout.height);
      const mask = packedMask ? sourceFrame < 0 ? Buffer.alloc(PIXELS) : unpackFrame(packedMask.subarray(sourceFrame * layout.frameBytes, (sourceFrame + 1) * layout.frameBytes), layout.width, layout.height) : null;
      const converted = match(pixels, mask);
      if (mask) assert.equal(converted.statistics.silhouetteSpill, 0);
      converted.screen.copy(screens, index * 1000);
      fs.writeSync(idealFile, pixels); idealHash.update(pixels); fs.writeSync(errorFile, converted.errors);
      const phase = sourceFrame < 0 ? 'blank' : source.frames?.[sourceFrame]?.phase || 'bitmap';
      assert.equal(typeof phase, 'string', 'Frame phase must be a string.');
      poses.push({index, frame: index, time: index / layout.fps, phase, visible: converted.screen.some(code => code !== 0), sourceFrame: sourceFrame < 0 ? null : sourceFrame});
      statistics.push({frame: index, phase, sourceFrame: sourceFrame < 0 ? null : sourceFrame, ...converted.statistics});
    }
  } finally {fs.closeSync(idealFile); fs.closeSync(errorFile);}
  const scene = {name, kind: 'bitmap', title: source.title ?? name, description: source.description ?? '',
    fps: layout.fps, width: WIDTH, height: HEIGHT, frameCount: count,
    durationSeconds: count / layout.fps, introSeconds: count / layout.fps, loop: null, phaseLabels: source.phaseLabels, frames: poses};
  const totalMismatchedPixels = statistics.reduce((sum, row) => sum + row.mismatches, 0);
  const metadata = {pass: true, name, kind: 'bitmap', title: scene.title, description: scene.description,
    sceneSource: source.sceneSource ?? null, phaseLabels: source.phaseLabels, fps: layout.fps, frameCount: count, frameBytes: 1000,
    width: WIDTH, height: HEIGHT, durationSeconds: scene.durationSeconds, introSeconds: scene.introSeconds, loop: null,
    fontGlyphs: font.length / 8, fontBytes: font.length, emptyGlyph: map[0], filledGlyph: map[15],
    bitmapSource: {frames: framesPath, metadata: metadataPath, ...layout, bitOrder: 'MSB-first', prependedBlankFrames: Number(prepend)},
    glyphSelection: 'Direct minimum8x8 bitmap Hamming error among the unchanged168 coarse glyphs; equal errors choose the lowest glyph code. ' + (packedMask ? 'All white glyph pixels must lie inside the supplied object mask; mask bits are included in the match cache key. ' : 'No silhouette constraint. ') + 'No fine-font remapping or font training.',
    objectMask: packedMask ? {file: maskPath, sha256: sha(packedMask), format: 'Same packed frame layout as the source bitmap', whiteGlyphPixelsMustBeSubset: true} : null,
    verification: {firstFrameEmpty: screens.subarray(0, 1000).every(code => code === 0), everyCodeWithinFixedFont: screens.every(code => code < 168), noClosingPatch: true},
    hashes: {font: sha(font), screens: sha(screens), ideal: idealHash.digest('hex'), sourcePacked: sha(packed)},
    errorSummary: {totalMismatchedPixels, meanMismatchedPixelsPerFrame: totalMismatchedPixels / count,
      meanPixelErrorFraction: totalMismatchedPixels / (count * PIXELS), comparedPixels: count * PIXELS,
      silhouetteSpill: packedMask ? statistics.reduce((sum, row) => sum + row.silhouetteSpill, 0) : null,
      sourceWhiteOutsideMask: packedMask ? statistics.reduce((sum, row) => sum + row.sourceWhiteOutsideMask, 0) : null},
    nativeTimingMeasured: false, statistics};
  for (const [filename, bytes] of Object.entries({'font.bin': font, 'reference.frames': screens, 'initial.screen': screens.subarray(0, 1000), 'scene.json': JSON.stringify(scene, null, 2) + '\n', 'metadata.json': JSON.stringify(metadata, null, 2) + '\n'})) fs.writeFileSync(path.join(output, filename), bytes);
  if (count <= 255) fs.writeFileSync(path.join(output, 'playback.json'), JSON.stringify([{op: 'play', startFrame: 0, frameCount: count, repeat: 1}, {op: 'hold'}], null, 2) + '\n');
  const result = {...metadata, statistics: undefined, output, totalMismatchedPixels,
    nativeStartupNote: metadata.verification.firstFrameEmpty ? 'First character screen is blank and compatible with the native startup clear.' : 'This movie starts with a nonblank character screen. Use --prepend-blank for the current native startup-clear pipeline.'};
  console.log(JSON.stringify(result, null, 2));
  return result;
}

module.exports = {main, createMatcher, fixedFont, unpackFrame};
if (require.main === module) main();
