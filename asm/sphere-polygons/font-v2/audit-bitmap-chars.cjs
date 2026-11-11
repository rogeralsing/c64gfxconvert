'use strict';

// Independent reconstruction audit. No converter matching code is imported.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');

const WIDTH = 320, HEIGHT = 200, BASE_FONT_SHA = '68ad34844c8a998f5270c31bc16962545f6c3232555fa03f9faec134c21c5b59';
const sha = data => crypto.createHash('sha256').update(data).digest('hex');
const stats = values => values.length ? {min: Math.min(...values), mean: values.reduce((sum, value) => sum + value, 0) / values.length, max: Math.max(...values)} : null;

function audit({framesPath, metadataPath, charactersPath, maskPath}) {
  const sourceMetadata = JSON.parse(fs.readFileSync(metadataPath));
  const metadata = JSON.parse(fs.readFileSync(path.join(charactersPath, 'metadata.json')));
  const raw = fs.readFileSync(framesPath), font = fs.readFileSync(path.join(charactersPath, 'font.bin'));
  const rawMask = maskPath ? fs.readFileSync(maskPath) : null;
  if (rawMask) assert.equal(rawMask.length, raw.length, 'Mask must have the same packed format and frame count as the source movie.');
  const screens = fs.readFileSync(path.join(charactersPath, 'reference.frames'));
  const {width, height} = sourceMetadata, inputCount = sourceMetadata.frameCount ?? sourceMetadata.count;
  assert(width === 320 && height === 200 || width === 160 && height === 100);
  assert.equal(raw.length, inputCount * width * height / 8);
  assert.equal(screens.length, metadata.frameCount * 1000);
  assert(font.length >= 1344 && font.length <= 2048 && font.length % 8 === 0);
  if (metadata.fontMode === 'fixed256') {
    assert.equal(font.length, 2048, 'A fixed256 film must ship all 256 glyphs.');
    assert.equal(metadata.fontExtension && metadata.fontExtension.fixedFont, true, 'fixed256 metadata must declare the fixed font.');
  } else {
    assert.equal(sha(font.subarray(0, 1344)), BASE_FONT_SHA, 'The original168-glyph prefix must remain byte-identical.');
  }
  const glyphCount = font.length / 8;
  const prepend = metadata.bitmapSource.prependedBlankFrames || 0;
  assert.equal(metadata.frameCount, inputCount + prepend);
  const scale = WIDTH / width, stride = width / 8, frameBytes = width * height / 8;
  const frames = [], histogram = Array(65).fill(0), nonuniformHistogram = Array(65).fill(0), activeUsage = Array(glyphCount).fill(0), uniformFailures = [];
  let fullErrors = 0, bboxErrors = 0, bboxArea = 0, falseWhite = 0, missedWhite = 0;
  let uniformEmpty = 0, uniformFilled = 0, nonuniform = 0, nonuniformErrors = 0, outsideBoundsErrors = 0;
  let activeUniformEmpty = 0, activeUniformFilled = 0;
  let objectPixels = 0, objectErrors = 0, outsideObjectErrors = 0, interiorEmpty = 0, interiorFilled = 0;
  let outputWhiteOutsideObject = 0, sourceWhiteOutsideObject = 0;
  for (let frame = 0; frame < metadata.frameCount; frame++) {
    const sourceFrame = frame - prepend, target = Buffer.alloc(WIDTH * HEIGHT), output = Buffer.alloc(WIDTH * HEIGHT), objectMask = rawMask ? Buffer.alloc(WIDTH * HEIGHT) : null;
    let left = WIDTH, top = HEIGHT, right = -1, bottom = -1, whites = 0;
    for (let y = 0; y < HEIGHT; y++) for (let x = 0; x < WIDTH; x++) {
      const sx = Math.floor(x / scale), sy = Math.floor(y / scale);
      const bit = sourceFrame < 0 ? 0 : (raw[sourceFrame * frameBytes + sy * stride + (sx >>> 3)] >>> (7 - (sx & 7))) & 1;
      target[y * WIDTH + x] = bit;
      if (objectMask) {objectMask[y * WIDTH + x] = sourceFrame < 0 ? 0 : (rawMask[sourceFrame * frameBytes + sy * stride + (sx >>> 3)] >>> (7 - (sx & 7))) & 1; objectPixels += objectMask[y * WIDTH + x];}
      const code = screens[frame * 1000 + Math.floor(y / 8) * 40 + Math.floor(x / 8)];
      assert(code < glyphCount);
      output[y * WIDTH + x] = (font[code * 8 + (y & 7)] >>> (7 - (x & 7))) & 1;
      if (objectMask && objectMask[y * WIDTH + x] === 0) {outputWhiteOutsideObject += output[y * WIDTH + x]; sourceWhiteOutsideObject += bit;}
      if (bit) {left = Math.min(left, x); top = Math.min(top, y); right = Math.max(right, x); bottom = Math.max(bottom, y); whites++;}
    }
    const bounds = right >= 0 ? {left, top, right, bottom, width: right - left + 1, height: bottom - top + 1} : null;
    const area = bounds ? bounds.width * bounds.height : 0;
    let errors = 0, errorsInBounds = 0, extraWhite = 0, missingWhite = 0, nonuniformCells = 0;
    for (let cell = 0; cell < 1000; cell++) {
      const cx = cell % 40 * 8, cy = Math.floor(cell / 40) * 8;
      let cellWhites = 0, cellErrors = 0, cellObjectPixels = 0;
      for (let dy = 0; dy < 8; dy++) for (let dx = 0; dx < 8; dx++) {
        const x = cx + dx, y = cy + dy, pixel = y * WIDTH + x;
        cellWhites += target[pixel];
        if (objectMask) cellObjectPixels += objectMask[pixel];
        if (target[pixel] !== output[pixel]) {
          cellErrors++; errors++;
          if (bounds && x >= left && x <= right && y >= top && y <= bottom) errorsInBounds++;
          if (target[pixel]) missingWhite++; else extraWhite++;
          if (objectMask) {if (objectMask[pixel]) objectErrors++; else outsideObjectErrors++;}
        }
      }
      const code = screens[frame * 1000 + cell];
      const intersectsBounds = bounds && cx <= right && cx + 7 >= left && cy <= bottom && cy + 7 >= top;
      const entirelyInsideBounds = bounds && cx >= left && cx + 7 <= right && cy >= top && cy + 7 <= bottom;
      if (intersectsBounds) activeUsage[code]++;
      histogram[cellErrors]++;
      if (cellWhites === 0 || cellWhites === 64) {
        const expected = cellWhites === 0 ? 0 : 8;
        if (cellWhites === 0) {uniformEmpty++; if (entirelyInsideBounds) activeUniformEmpty++;}
        else {uniformFilled++; if (entirelyInsideBounds) activeUniformFilled++;}
        if (cellObjectPixels === 64) {if (cellWhites === 0) interiorEmpty++; else interiorFilled++;}
        if (code !== expected || cellErrors !== 0) uniformFailures.push({frame, cell, whitePixels: cellWhites, code, expected, cellErrors});
      } else {nonuniform++; nonuniformCells++; nonuniformErrors += cellErrors; nonuniformHistogram[cellErrors]++;}
    }
    assert.equal(errors, metadata.statistics[frame].mismatches, 'Independently reconstructed errors differ from converter statistics.');
    fullErrors += errors; bboxErrors += errorsInBounds; bboxArea += area;
    falseWhite += extraWhite; missedWhite += missingWhite; outsideBoundsErrors += errors - errorsInBounds;
    frames.push({frame, sourceFrame: sourceFrame < 0 ? null : sourceFrame, phase: metadata.statistics[frame].phase,
      activeBounds: bounds, activeBoundsArea: area, fullErrors: errors, wholeFrameErrorFraction: errors / (WIDTH * HEIGHT),
      errorsInsideActiveBounds: errorsInBounds, activeBoundsErrorFraction: area ? errorsInBounds / area : null,
      errorsOutsideActiveBounds: errors - errorsInBounds, falseWhitePixels: extraWhite, missedWhitePixels: missingWhite,
      sourceWhitePixels: whites, nonuniformCells});
  }
  const result = {pass: uniformFailures.length === 0, name: metadata.name, frameCount: metadata.frameCount,
    fontGlyphs: glyphCount, baseFontPrefixPreserved: true,
    scope: 'Independent source-bit and font-byte reconstruction. Active bounds are each source image\'s tight white-pixel bounding box, not a 3D object mask. Black space outside it is excluded from the active error denominator; outside errors are reported separately. An optional separately rendered object mask provides an additional object-only denominator.',
    hashes: {sourcePacked: sha(raw), screens: sha(screens), font: sha(font)},
    wholeImage: {mismatches: fullErrors, comparedPixels: metadata.frameCount * WIDTH * HEIGHT,
      errorFraction: fullErrors / (metadata.frameCount * WIDTH * HEIGHT)},
    activeBounds: {mismatches: bboxErrors, comparedPixels: bboxArea, errorFraction: bboxArea ? bboxErrors / bboxArea : null,
      perVisibleFrameErrorFraction: stats(frames.filter(frame => frame.activeBounds).map(frame => frame.activeBoundsErrorFraction)),
      errorsOutsideBounds: outsideBoundsErrors},
    objectMask: rawMask ? {sha256: sha(rawMask), comparedPixels: objectPixels, mismatches: objectErrors,
      errorFraction: objectPixels ? objectErrors / objectPixels : null, errorsOutsideObject: outsideObjectErrors,
      outputWhiteOutsideObject, sourceWhiteOutsideObject,
      uniformInteriorEmptyTiles: interiorEmpty, uniformInteriorFilledTiles: interiorFilled} : null,
    mismatchPolarity: {falseWhitePixels: falseWhite, missedWhitePixels: missedWhite},
    uniformTiles: {empty: uniformEmpty, filled: uniformFilled, emptyEntirelyInsideBounds: activeUniformEmpty,
      filledEntirelyInsideBounds: activeUniformFilled, exactExpectedCodes: {empty: 0, filled: 8}, failures: uniformFailures},
    nonuniformTiles: {count: nonuniform, mismatches: nonuniformErrors, meanMismatchedPixels: nonuniform ? nonuniformErrors / nonuniform : 0},
    tileErrorHistogram: histogram, nonuniformTileErrorHistogram: nonuniformHistogram, glyphUsageInActiveBounds: activeUsage,
    perFrameErrors: stats(frames.map(frame => frame.fullErrors)), frames};
  return result;
}

function main(argv = process.argv.slice(2)) {
  const options = {};
  for (let index = 0; index < argv.length; index++) {
    const [key, inline] = argv[index].split('=');
    assert(['--frames', '--metadata', '--characters', '--mask', '--output', '--compare'].includes(key), 'Unknown option ' + key);
    options[key] = inline ?? argv[++index]; assert(options[key], 'Missing value for ' + key);
  }
  for (const name of ['--frames', '--metadata', '--characters']) assert(options[name], 'Required option ' + name);
  const result = audit({framesPath: path.resolve(options['--frames']), metadataPath: path.resolve(options['--metadata']), charactersPath: path.resolve(options['--characters']), maskPath: options['--mask'] ? path.resolve(options['--mask']) : null});
  if (options['--compare']) {
    const previous = JSON.parse(fs.readFileSync(path.resolve(options['--compare'])));
    const samePackedReference = previous.hashes.sourcePacked === result.hashes.sourcePacked;
    const sameFont = previous.hashes.font === result.hashes.font;
    result.comparison = {previousName: previous.name, previousSourcePackedSha256: previous.hashes.sourcePacked,
      samePackedReference, sameFont,
      previousWholeImageErrorFraction: previous.wholeImage.errorFraction, currentWholeImageErrorFraction: result.wholeImage.errorFraction,
      previousActiveBoundsErrorFraction: previous.activeBounds.errorFraction, currentActiveBoundsErrorFraction: result.activeBounds.errorFraction,
      previousNonuniformTiles: previous.nonuniformTiles.count, currentNonuniformTiles: result.nonuniformTiles.count,
      previousObjectMaskErrorFraction: previous.objectMask?.errorFraction ?? null,
      currentObjectMaskErrorFraction: result.objectMask?.errorFraction ?? null,
      previousErrorsOutsideObject: previous.objectMask?.errorsOutsideObject ?? null,
      currentErrorsOutsideObject: result.objectMask?.errorsOutsideObject ?? null,
      note: samePackedReference && sameFont ? 'The packed reference and font are identical; this comparison isolates character selection changes.' : 'Comparisons use their respective source references. A changed material or quantizer changes the reference; this is not a controlled font comparison.'};
  }
  if (options['--output']) {const output = path.resolve(options['--output']); fs.mkdirSync(path.dirname(output), {recursive: true}); fs.writeFileSync(output, JSON.stringify(result, null, 2) + '\n');}
  console.log(JSON.stringify({...result, frames: undefined, glyphUsageInActiveBounds: undefined}, null, 2));
  if (!result.pass) throw new Error('Uniform source tiles failed exact empty/full mapping.');
  return result;
}

module.exports = {main};
if (require.main === module) main();
