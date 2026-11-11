'use strict';

// Skip small glyph changes during offline encoding. Decisions use the actual
// retained screen, so every displayed tile stays within its pixel-error budget.
// Playback remains the ordinary sparse absolute-character delta format.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {encodeSparse, decodeSparse, maxPrefix, sha, summary, ARENA_START, ARENA_END} = require('./delta-study.cjs');

const HERE = __dirname;
const OUT = path.join(HERE, 'build/lossy');
const SCREEN = 1000;
const FRAMES = 384;
const FONT_SHA = 'e4071e1e3176e3ee65eeb5fc2df5bb3eccab7b733b9ea7cbb276a2f3a65a1aac';
const THRESHOLDS = [0, 1, 2, 3, 4, 8];

function distanceTable(font) {
  const counts = Uint8Array.from({length: 256}, (_, value) => {
    let count = 0;
    for (let bit = 0; bit < 8; bit++) count += (value >>> bit) & 1;
    return count;
  });
  const distances = new Uint8Array(256 * 256);
  for (let a = 0; a < 256; a++) for (let b = 0; b < 256; b++) {
    let count = 0;
    for (let row = 0; row < 8; row++) count += counts[font[a * 8 + row] ^ font[b * 8 + row]];
    distances[a * 256 + b] = count;
  }
  return distances;
}

// Independent pixel traversal: this deliberately does not use the distance
// table or the encoder's decision arithmetic to check its resulting screen.
function pixelErrors(actual, target, font, threshold) {
  let total = 0, wrongChars = 0, worstTile = 0;
  for (let cell = 0; cell < SCREEN; cell++) {
    if (actual[cell] === target[cell]) continue;
    wrongChars++;
    let tile = 0;
    for (let row = 0; row < 8; row++) {
      const a = font[actual[cell] * 8 + row], b = font[target[cell] * 8 + row];
      for (let column = 0; column < 8; column++) {
        if (((a >>> (7 - column)) & 1) !== ((b >>> (7 - column)) & 1)) tile++;
      }
    }
    assert(tile <= threshold, `Tile ${cell} exceeds ${threshold}-pixel budget: ${tile}`);
    total += tile;
    worstTile = Math.max(worstTile, tile);
  }
  return {total, wrongChars, worstTile};
}

function encodeSequence(targetFrames, font, threshold, distances = distanceTable(font), options = {}) {
  assert(Number.isInteger(threshold) && threshold >= 0 && threshold <= 64);
  const retained = Buffer.from(targetFrames[0]);
  const displayed = [Buffer.from(retained)], payloads = [], errors = [{total: 0, wrongChars: 0, worstTile: 0}];
  let candidates = 0, skipped = 0, emitted = 0, forcedSolidChanges = 0;
  const candidateDistances = new Uint32Array(65);
  const frameStats = [{pose: 0, skippedChanges: 0, emittedChanges: 0, pixelErrors: 0, differentCharacters: 0, worstTilePixelErrors: 0}];
  for (let pose = 1; pose < targetFrames.length; pose++) {
    const target = targetFrames[pose], previous = Buffer.from(retained);
    let frameSkipped = 0, frameEmitted = 0, frameForcedSolids = 0;
    for (let cell = 0; cell < SCREEN; cell++) {
      const currentCode = retained[cell], targetCode = target[cell];
      if (currentCode === targetCode) continue;
      const distance = distances[currentCode * 256 + targetCode];
      candidateDistances[distance]++;
      candidates++;
      const forceSolid = options.protectSolids && (targetCode === 0 || targetCode === 15);
      if (distance <= threshold && !forceSolid) { skipped++; frameSkipped++; }
      else {
        retained[cell] = targetCode; emitted++; frameEmitted++;
        if (forceSolid && distance <= threshold) { forcedSolidChanges++; frameForcedSolids++; }
      }
    }
    const payload = encodeSparse(retained, previous);
    assert(decodeSparse(payload, previous).equals(retained));
    const error = pixelErrors(retained, target, font, threshold);
    errors.push(error);
    displayed.push(Buffer.from(retained));
    payloads.push(payload);
    frameStats.push({pose, skippedChanges: frameSkipped, emittedChanges: frameEmitted,
      forcedSolidChanges: frameForcedSolids, pixelErrors: error.total,
      differentCharacters: error.wrongChars, worstTilePixelErrors: error.worstTile});
    if (options.protectSolids) for (let cell = 0; cell < SCREEN; cell++) {
      if (target[cell] === 0 || target[cell] === 15) assert.equal(retained[cell], target[cell], 'Solid target cell must be exact');
    }
  }
  // Reset to the exact first image at the cyclic boundary. The next cycle then
  // sees the same retained state as the offline encoder, without keyframe copy.
  const closing = encodeSparse(targetFrames[0], retained);
  assert(decodeSparse(closing, retained).equals(targetFrames[0]));
  payloads.push(closing);
  let cyclic = Buffer.from(targetFrames[0]);
  for (let cycle = 0; cycle < 3; cycle++) {
    for (let step = 0; step < payloads.length; step++) {
      cyclic = decodeSparse(payloads[step], cyclic);
      const expected = displayed[(step + 1) % displayed.length];
      assert(cyclic.equals(expected), `Sparse replay differs at cycle ${cycle}, step ${step}`);
    }
    assert(cyclic.equals(targetFrames[0]));
  }
  const closingUpdates = targetFrames[0].reduce((count, value, cell) => count + (value !== retained[cell]), 0);
  return {displayed, payloads, frameStats, candidates, skipped, emitted, forcedSolidChanges, closingUpdates,
    candidateDistances: Array.from(candidateDistances), errors};
}

function verifyFeedbackCounterexample(font, distances) {
  const threshold = 3;
  for (let a = 0; a < 256; a++) for (let b = 0; b < 256; b++) {
    if (a === b || distances[a * 256 + b] > threshold) continue;
    for (let c = 0; c < 256; c++) {
      if (distances[b * 256 + c] > threshold || distances[a * 256 + c] <= threshold) continue;
      const targets = [a, b, c].map(code => { const frame = Buffer.alloc(SCREEN); frame[0] = code; return frame; });
      const actual = encodeSequence(targets, font, threshold, distances);
      assert.equal(actual.displayed[1][0], a, 'First small change should be retained');
      assert.equal(actual.displayed[2][0], c, 'Accumulated difference must trigger a real update');
      const naiveRetained = targets[0];
      const naiveError = pixelErrors(naiveRetained, targets[2], font, 64).worstTile;
      assert(naiveError > threshold, 'Comparing ideal adjacent targets must violate this counterexample');
      return {pass: true, threshold, glyphs: [a, b, c], adjacentPixelDifferences: [distances[a * 256 + b], distances[b * 256 + c]],
        retainedToFinalPixelDifference: naiveError, feedbackCorrectlyEmitsFinalGlyph: true};
    }
  }
  throw new Error('No font-based temporal-drift counterexample was found');
}

function runDataset(dataset, thresholds, options = {}) {
  const preview = path.join(HERE, '../c64-preview/build');
  const font = fs.readFileSync(path.join(preview, 'font.bin'));
  assert.equal(font.length, 2048);
  assert.equal(sha(font), FONT_SHA);
  const input = dataset === 'analytic' ? path.join(preview, 'movie.frames') : path.join(HERE, 'build/geometry/frames.screen');
  const raw = fs.readFileSync(input);
  assert.equal(raw.length, FRAMES * SCREEN);
  const targets = Array.from({length: FRAMES}, (_, pose) => raw.subarray(pose * SCREEN, (pose + 1) * SCREEN));
  const settings = JSON.parse(fs.readFileSync(path.join(preview, 'metadata.json'))).settings;
  const distances = distanceTable(font);
  const baseline = targets.map((target, pose) => encodeSparse(targets[(pose + 1) % FRAMES], target));
  const baselineBytes = baseline.reduce((count, payload) => count + payload.length, 0);
  const baselinePrefix = maxPrefix(baseline);
  assert.equal(baselinePrefix.frames, dataset === 'analytic' ? 55 : 74);
  const results = [];
  for (const threshold of thresholds) {
    const directory = path.join(OUT, dataset, `threshold-${threshold}${options.protectSolids ? '-protect-solids' : ''}`);
    fs.mkdirSync(directory, {recursive: true});
    const encoded = encodeSequence(targets, font, threshold, distances, options);
    const reconstructed = Buffer.concat(encoded.displayed);
    if (threshold === 0) assert(reconstructed.equals(raw));
    let offset = 0;
    const index = encoded.payloads.map(payload => {
      const record = {offset, bytes: payload.length}; offset += payload.length; return record;
    });
    const prefix = maxPrefix(encoded.payloads);
    const record = {
      pass: true, dataset, threshold, protectSolids: Boolean(options.protectSolids), settings, frames: FRAMES,
      imageSource: `${dataset === 'analytic' ? 'Analytic HTML matching' : 'Flat 200-face eight-probe geometry'} screens, feedback lossy threshold ${threshold}`,
      sourceScreensSha256: sha(reconstructed), losslessTargetScreensSha256: sha(raw), fontSha256: sha(font),
      screenBytes: SCREEN, fontBytes: font.length,
      arena: {start: ARENA_START, endExclusive: ARENA_END, bytes: ARENA_END - ARENA_START,
        otherReserved: 'Code and pointer tables $1000-$1fff, font $2000-$27ff, raw first screen $2800-$2be7; working screens below $1000.'},
      algorithm: `For each cell compare target glyph pixels with the actually retained glyph. Keep it iff Hamming distance <= threshold${options.protectSolids ? ' and the target is neither empty0 nor full15' : ''}; otherwise emit the exact target code. First image is exact; cycle closes with an exact sparse patch to that first image.`,
      solidPolicy: options.protectSolids ? 'Always update changed target empty0/full15 cells, even when the glyph distance is within threshold. Partial target glyphs retain feedback thresholding.' : 'No special treatment of empty or full target cells.',
      cyclicState: {exactSeed: true, exactClosingPatch: true, cyclesDecodedAndCompared: 3,
        closingBytes: encoded.payloads.at(-1).length, closingUpdates: encoded.closingUpdates},
      updates: {candidateChanges: encoded.candidates, ignoredChanges: encoded.skipped, forcedSolidChanges: encoded.forcedSolidChanges,
        emittedChanges: encoded.emitted, emittedIncludingExactClosure: encoded.emitted + encoded.closingUpdates,
        candidateDistanceHistogram: encoded.candidateDistances,
        skippedFractionOfCandidates: encoded.candidates ? encoded.skipped / encoded.candidates : 0},
      errorRelativeToLosslessFontOutput: {
        independentPixelTraversalFrames: FRAMES,
        maxPixelsPerTile: Math.max(...encoded.errors.map(value => value.worstTile)),
        pixelsPerFrame: summary(encoded.errors.map(value => value.total)),
        differingCharactersPerFrame: summary(encoded.errors.map(value => value.wrongChars)),
        fullScreenPixelErrorFraction: summary(encoded.errors.map(value => value.total / 64000)),
        worstPose: encoded.errors.reduce((best, value, pose) => value.total > encoded.errors[best].total ? pose : best, 0),
        comparisonScope: 'Additional error against the existing fixed-font target, not error against an ideal sphere bitmap.'
      },
      formats: {sparse: {cyclicPayloadBytes: offset, cyclicPointerBytes: FRAMES * 2,
        totalFullTurnWithRawSeedAndFont: offset + FRAMES * 2 + SCREEN + font.length,
        payloadBytes: summary(encoded.payloads.map(payload => payload.length)), maximumPrefix: prefix,
        nativeImplementation: true}},
      baseline: {cyclicPayloadBytes: baselineBytes, maximumPrefix: baselinePrefix},
      payloadSavingsFraction: 1 - offset / baselineBytes,
      maxPrefixFramesGain: prefix.frames - baselinePrefix.frames,
      nativeTimingMeasured: false,
      verification: {sparseRoundtripFrames: FRAMES, threeCycleSparseReplayFrames: FRAMES * 3,
        independentPerTileErrorBoundChecked: true, protectedSolidTargetsExact: options.protectSolids ? true : null,
        firstFrameExact: true, thresholdZeroMatchesLossless: threshold === 0}
    };
    fs.writeFileSync(path.join(directory, 'reference.frames'), reconstructed);
    fs.writeFileSync(path.join(directory, 'font.bin'), font);
    fs.writeFileSync(path.join(directory, 'sparse.bin'), Buffer.concat(encoded.payloads));
    fs.writeFileSync(path.join(directory, 'sparse-index.json'), JSON.stringify(index));
    fs.writeFileSync(path.join(directory, 'per-frame.json'), JSON.stringify(encoded.frameStats));
    fs.writeFileSync(path.join(directory, 'study.json'), JSON.stringify(record, null, 2) + '\n');
    results.push(record);
    console.log(JSON.stringify({dataset, threshold, protectSolids: record.protectSolids, bytes: offset, savings: record.payloadSavingsFraction,
      framesFit: prefix.frames, meanPixelError: record.errorRelativeToLosslessFontOutput.pixelsPerFrame.mean,
      maxPixelError: record.errorRelativeToLosslessFontOutput.pixelsPerFrame.max,
      worstTilePixels: record.errorRelativeToLosslessFontOutput.maxPixelsPerTile}));
  }
  return results;
}

function main(argv = process.argv.slice(2)) {
  const option = name => argv.find(value => value.startsWith(`--${name}=`))?.split('=')[1];
  const datasets = option('dataset') ? [option('dataset')] : ['analytic', 'geometry'];
  assert(datasets.every(dataset => ['analytic', 'geometry'].includes(dataset)));
  const thresholds = option('thresholds') ? option('thresholds').split(',').map(Number) : THRESHOLDS;
  const options = {protectSolids: argv.includes('--protect-solids')};
  assert(thresholds.every(value => THRESHOLDS.includes(value)));
  fs.mkdirSync(OUT, {recursive: true});
  const font = fs.readFileSync(path.join(HERE, '../c64-preview/build/font.bin'));
  const distances = distanceTable(font), pairHistogram = new Array(65).fill(0);
  for (let a = 0; a < 256; a++) for (let b = a + 1; b < 256; b++) pairHistogram[distances[a * 256 + b]]++;
  const fontEvidence = {fontSha256: sha(font), uniqueGlyphPairs: 256 * 255 / 2,
    minimumDistinctGlyphPixelDifference: pairHistogram.findIndex((count, distance) => distance > 0 && count > 0),
    glyphPairDistanceHistogram: pairHistogram};
  fs.writeFileSync(path.join(OUT, 'font-distances.json'), JSON.stringify(fontEvidence, null, 2) + '\n');
  const feedbackRegression = verifyFeedbackCounterexample(font, distances);
  fs.writeFileSync(path.join(OUT, 'feedback-regression.json'), JSON.stringify(feedbackRegression, null, 2) + '\n');
  const newRows = datasets.flatMap(dataset => runDataset(dataset, thresholds, options));
  const summaryPath = path.join(OUT, 'summary.json');
  const previous = fs.existsSync(summaryPath) ? JSON.parse(fs.readFileSync(summaryPath)).rows : [];
  const key = row => `${row.dataset}/${row.threshold}/${Boolean(row.protectSolids)}`;
  const replace = new Set(newRows.map(key));
  const rows = [...previous.filter(row => !replace.has(key(row))), ...newRows]
    .sort((a, b) => a.dataset.localeCompare(b.dataset) || a.threshold - b.threshold || Number(Boolean(a.protectSolids)) - Number(Boolean(b.protectSolids)));
  const combined = {pass: true, fontSha256: FONT_SHA, fontDistanceEvidence: fontEvidence, feedbackRegression,
    scope: 'Same 384-pose large-sphere motion, offline feedback thresholding, unchanged sparse native playback format. Native FPS must be measured separately.', rows};
  fs.writeFileSync(summaryPath, JSON.stringify(combined, null, 2) + '\n');
  return combined;
}

module.exports = {distanceTable, pixelErrors, encodeSequence, verifyFeedbackCounterexample, runDataset, main};
if (require.main === module) main();
