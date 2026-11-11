'use strict';

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const here = __dirname;
const read = name => JSON.parse(fs.readFileSync(path.join(here, name)));
const stats = values => ({min: Math.min(...values), mean: values.reduce((sum, value) => sum + value, 0) / values.length, max: Math.max(...values)});

function countWrites(name, frames) {
  const writes = [[], [], []], population = [[], [], []];
  const kind = code => code === 0 ? 0 : code === 15 ? 1 : 2;
  for (let pose = 0; pose < 384; pose++) {
    const changed = [0, 0, 0], present = [0, 0, 0];
    for (let cell = 0; cell < 1000; cell++) {
      const previous = frames[pose * 1000 + cell];
      const target = frames[((pose + 1) % 384) * 1000 + cell];
      present[kind(previous)]++;
      if (previous !== target) changed[kind(target)]++;
    }
    for (let group = 0; group < 3; group++) {
      writes[group].push(changed[group]); population[group].push(present[group]);
    }
  }
  const label = ['empty', 'full', 'edge'];
  return {name, frames: 384,
    updates: {...Object.fromEntries(label.map((key, group) => [key, stats(writes[group])])),
      totalMean: writes.reduce((sum, values) => sum + stats(values).mean, 0)},
    population: Object.fromEntries(label.map((key, group) => [key, stats(population[group])])),
    scope: 'All384 cyclic transitions, including the exact lossy closing patch; the initial seed is excluded.'};
}

function groupedEstimate(name, frames) {
  let sparse = 0, grouped = 0, hybrid = 0;
  for (let pose = 0; pose < 384; pose++) for (let page = 0; page < 4; page++) {
    const glyphs = new Map();
    let count = 0;
    for (let offset = 0; offset < Math.min(256, 1000 - page * 256); offset++) {
      const cell = page * 256 + offset;
      const previous = frames[pose * 1000 + cell], target = frames[((pose + 1) % 384) * 1000 + cell];
      if (previous !== target) { count++; glyphs.set(target, (glyphs.get(target) || 0) + 1); }
    }
    sparse += 1 + 2 * count;
    grouped += 1 + count + 2 * glyphs.size;
    hybrid += 2;
    for (const occurrences of glyphs.values()) hybrid += occurrences >= 3 ? 2 + occurrences : 2 * occurrences;
  }
  return {name, frames: 384, sparseBytes: sparse, allGroupedBytes: grouped,
    allGroupedSavingsFraction: 1 - grouped / sparse,
    hybridBytes: hybrid, hybridSavingsFraction: 1 - hybrid / sparse,
    scope: 'Host serialized-size estimate. Grouped=count8 groups then glyph8,count8,offset8[]; hybrid adds individual offset8,glyph8 pairs for groups smaller than three.'};
}

function main() {
  const source = read('build/lossy/summary.json');
  const font = read('build/lossy/font-distances.json');
  assert(source.pass);
  assert.equal(font.minimumDistinctGlyphPixelDifference, 3);
  const rows = source.rows.map(row => {
    const nativePath = `build/lossy-native/${row.dataset}/threshold-${row.threshold}${row.protectSolids ? '-protect-solids' : ''}/summary.json`;
    let native = null;
    if (fs.existsSync(path.join(here, nativePath))) {
      const proof = read(nativePath);
      assert(proof.pass);
      native = {measurementReusedByByteIdentity: Object.values(proof.variants).some(value => value.measurementReusedByByteIdentity),
        variants: Object.fromEntries(Object.entries(proof.variants).map(([name, value]) => [name, {
          fps: value.meanFps, storedFrames: value.storedFrames,
          actualVisibleFieldsVerified: value.actualVisibleFieldsVerified,
          programSha256: value.programSha256}]))};
    }
    return {dataset: row.dataset, threshold: row.threshold, protectSolids: !!row.protectSolids,
      cyclicPayloadBytes: row.formats.sparse.cyclicPayloadBytes,
      payloadSavingsFraction: row.payloadSavingsFraction,
      storedFrames: row.formats.sparse.maximumPrefix.frames,
      prefixSourceBytes: row.formats.sparse.maximumPrefix.payloadBytes,
      extraPixelErrorPerFrame: row.errorRelativeToLosslessFontOutput.pixelsPerFrame,
      extraScreenPixelErrorFraction: row.errorRelativeToLosslessFontOutput.fullScreenPixelErrorFraction,
      worstCellPixelError: row.errorRelativeToLosslessFontOutput.maxPixelsPerTile,
      referenceSha256: row.sourceScreensSha256,
      hostFramesVerified: row.verification.sparseRoundtripFrames,
      replayFramesVerified: row.verification.threeCycleSparseReplayFrames,
      native};
  });
  const corpora = [
    ['analytic', '../c64-preview/build/movie.frames'],
    ['geometry', 'build/geometry/frames.screen'],
    ['lossy3', 'build/lossy/analytic/threshold-3/reference.frames'],
    ['lossy4', 'build/lossy/analytic/threshold-4/reference.frames'],
    ['lossy4-protect-solids', 'build/lossy/analytic/threshold-4-protect-solids/reference.frames']
  ].map(([name, file]) => [name, fs.readFileSync(path.join(here, file))]);
  const counts = corpora.map(([name, frames]) => countWrites(name, frames));
  const grouped = corpora.filter(([name]) => name === 'analytic' || name === 'lossy4-protect-solids')
    .map(([name, frames]) => groupedEstimate(name, frames));
  const groupedNative = ['analytic', 'protected4'].map(dataset => {
    const proof = read(`build/grouped-native/${dataset}/summary.json`);
    assert(proof.pass);
    return proof;
  });
  const result = {pass: true, font, rows, actualCharacterWrites: counts,
    groupedPageFormatSizeEstimate: grouped,
    groupedNative, groupedAndCodegenHost: read('build/codegen/summary.json'),
    errorScope: 'Extra pixel differences against the lossless fixed-font output, not against an ideal sphere bitmap.',
    feedback: 'Compare each target with the actually retained displayed glyph. Exact initial frame and exact closing patch reset the cycle state. Native sparse format and decoder remain unchanged.',
    protectedPolicy: 'Always update a changed target empty glyph0 or filled glyph15. Apply the threshold only to partial target glyphs.',
    nativeScope: 'Threshold2 inputs and programs are byte-identical to the existing lossless case; its measurements are reused. Threshold3/4 and protected4 have actual native prefix playback and completed-VIC-field checks. Other thresholds have host results only.',
    storageScope: 'Largest encoded prefix in the existing40960-byte source arena. Font, seed, code and pointers remain separately reserved.',
    groupedScope: 'Pure grouped data and generated-code sizes are host-verified. The four-page hybrid decoder has actual50FPS native prefix receipts for59 lossless and68 protected4 poses. Every displayed field matches; other motions and pure-grouped/generated-code native FPS are unmeasured.'};
  const output = path.join(here, 'results');
  fs.mkdirSync(output, {recursive: true});
  fs.writeFileSync(path.join(output, 'lossy.json'), JSON.stringify(result, null, 2) + '\n');
  const table = rows.filter(row => row.dataset === 'analytic' && row.threshold !== 1).map(row =>
    `| ${row.threshold}${row.protectSolids ? ', preserve empty/full targets' : ''} | ${(100 * row.payloadSavingsFraction).toFixed(2)}% | ${row.storedFrames} | ${row.extraPixelErrorPerFrame.mean.toFixed(2)} | ${row.native ? row.native.variants['sparse-front'].fps.toFixed(3) : 'not measured'} |`);
  const markdown = `# Lossy character delta\n\n` +
    `Same 290-pixel sphere, 20 × 10 checks, 65° tilt and selected 256-glyph font. The font's smallest distinct-glyph difference is **3 pixels**, verified across all 32,640 pairs. A 2-pixel threshold therefore changes no data.\n\n` +
    `| Maximum ignored pixel difference per cell | Payload saved, full 384-pose cycle | Stored prefix frames | Mean extra wrong pixels per image | Native direct-front FPS |\n` +
    `| --- | ---: | ---: | ---: | ---: |\n${table.join('\n')}\n\n` +
    `Error is additional difference against the existing lossless font image. ` +
    `Every decision compares the target with the glyph actually retained on screen; comparing only adjacent ideal frames would permit drift beyond the error budget. All cases pass 384-frame independent pixel checks and three complete sparse-decoder cycles. The cycle uses an exact closing patch to its original seed.\n\n` +
    `Unprotected thresholds can leave small holes or dots inside solid areas. ` +
    `Preserving target empty/full cells removes this artifact. Protected 4 stores 63 frames instead of 55, saves 10.81% of cyclic payload and adds 169.85 wrong pixels per image on average, 0.2654% of the screen. Native direct playback passed 50.125 FPS; hidden-plus-copy passed 25.062 FPS. Every tested empty/full target cell stays exact.\n\n` +
    `## Actual writes per image\n\n` +
    `Without loss: mean 25.6875 empty writes, 24.015625 filled writes and 325.328125 partial-glyph writes, over 384 cyclic transitions. The initial 1,000-character seed is excluded. Empty/full writes are 13.253% of 375.03125 total writes. The screen contains 397.31 empty, 234.79 filled and 367.89 partial cells on average; most unchanged cells need no write.\n\n` +
    `## Grouping repeated glyphs\n\n` +
    `The current sparse format repeats (offset8,glyph8) per update inside four 256-byte blocks. ` +
    `A grouped record (glyph8,count8,offset8[]) reduces six repeats from 12 to 8 bytes. Grouping every glyph makes this particular lossless corpus 17.70% larger because many groups contain only one glyph. A hybrid that groups occurrences of three or more and retains individual pairs for the rest stores 6.36% smaller payload. Combining it with protected 4 uses 241,658 bytes versus 289,560 lossless bytes across the full cycle.\n\n` +
    `The four-block hybrid native player stores 59 lossless poses (40,396 bytes) or 68 protected-4 poses (40,870 bytes). It passed actual completed-field VIC checks at 50.125 FPS for every stored pose. Block order is preserved while groups reorder writes within each block. These two prefixes showed no tearing. Pure all-grouped data stores only 46 lossless poses; its native decoder is not timed.\n\n` +
    '```text\n' +
    'Per block: groupCount8, singleCount8\n' +
    'Groups: glyph8, count8, offset8[count]\n' +
    'Individual updates: offset8, glyph8\n' +
    '```\n\n' +
    `Host-generated 6502 routines also pass execution checks, but cost more memory: 21 lossless poses in screen order or 28 grouped by glyph. No native FPS is claimed for those generated routines.\n\n` +
    `## Reproduce\n\n` +
    '```sh\n' +
    'rtk proxy node asm/sphere-polygons/font-v2/large-benchmark/lossy-study.cjs\n' +
    'rtk proxy node asm/sphere-polygons/font-v2/large-benchmark/lossy-study.cjs --protect-solids\n' +
    'rtk proxy node asm/sphere-polygons/font-v2/large-benchmark/lossy-native.cjs --threshold=4 --protect-solids\n' +
    'rtk proxy python3 asm/sphere-polygons/font-v2/large-benchmark/verify-lossy.py --threshold=4 --protect-solids\n' +
    'rtk proxy node asm/sphere-polygons/font-v2/large-benchmark/lossy-report.cjs\n' +
    '```\n\n' +
    `[Full results and measurement scopes](lossy.json)\n\n` +
    `![Host reconstruction comparison](lossy-comparison.png)\n`;
  fs.writeFileSync(path.join(output, 'lossy.md'), markdown);
  const preview = path.join(here, 'build/lossy-preview/analytic-threshold-4-protect-solids/raw4-vs-protected4-same-pose.png');
  if (fs.existsSync(preview)) fs.copyFileSync(preview, path.join(output, 'lossy-comparison.png'));
  console.log(JSON.stringify({pass: true, hostCases: rows.length, nativeOrIdenticalCases: rows.filter(row => row.native).length,
    minimumGlyphDistance: font.minimumDistinctGlyphPixelDifference, protected4: rows.find(row => row.dataset === 'analytic' && row.threshold === 4 && row.protectSolids)}, null, 2));
  return result;
}

module.exports = {main};
if (require.main === module) main();
