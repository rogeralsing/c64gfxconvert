'use strict';

// Combine frozen source-capacity counts with actual PAL/VIC receipts.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');

const here = __dirname;
const output = path.join(here, 'results');
const read = name => JSON.parse(fs.readFileSync(path.join(here, name)));
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const fontSha = 'e4071e1e3176e3ee65eeb5fc2df5bb3eccab7b733b9ea7cbb276a2f3a65a1aac';
const step = 360 / 384;
const geometryNames = {
  'raw-individual': 'Raw face spans, individual sample lines',
  'raw-fast': 'Raw face spans, combined character rows',
  'packed-fast': 'Compressed face spans, combined character rows',
  'edge-paths-fast': 'Precomputed individual edge paths',
  'edges-fast': 'Raw projected XY, runtime edge crossings',
  'xy-delta-fast': 'Compressed projected XY, runtime edge crossings'
};
const deltaNames = {
  'sparse-front': 'Sparse character delta, direct front screen',
  'sparse-hidden': 'Sparse character delta, hidden screen plus copy',
  'packets-hidden': 'Packet character delta, hidden screen plus copy'
};

function deltaCases(summary, corpus) {
  assert(summary.pass);
  assert.equal(summary.fontSha256, fontSha);
  return Object.entries(summary.variants).map(([variant, value]) => {
    assert(value.pass);
    assert(value.uniquePosesAndTransitionsVerified >= 384);
    const prefix = value.firstPosePrefixStorage;
    return {id: `${corpus}/${variant}`, corpus, label: deltaNames[variant],
      fps: value.meanFps, storedFrames: prefix.frames, storedSourceBytes: prefix.payloadBytes,
      sourceCapacityBytes: summary.dataArena.bytes, fontBytes: value.fontBytes,
      codeStatePointersBytes: value.codeStateAndPointersBytes,
      initialScreenBytes: prefix.initialRawScreenBytesOutsideArena,
      runtimeScreenBytes: value.workScreenBytes, programBytes: value.prefixProgramBytes,
      renderCycles: value.renderCycles, copyCycles: value.copyCycles,
      nativePosesVerified: value.uniquePosesAndTransitionsVerified,
      actualVisibleFieldsVerified: value.actualVisibleFieldsVerified,
      estimatedSecondsAtMeasuredFps: prefix.frames / value.meanFps,
      secondsAt25FpsStorageOnly: prefix.frames / 25,
      angularRangeDegrees: (prefix.frames - 1) * step,
      program: path.relative(here, value.standalonePrefixProgram),
      programSha256: sha(fs.readFileSync(value.standalonePrefixProgram)),
      sourceScreensSha256: summary.sourceScreensSha256};
  });
}

function main() {
  fs.mkdirSync(output, {recursive: true});
  const geometry = read('build/geometry/metadata.json');
  assert.equal(geometry.settings.radius, 145);
  assert.equal(geometry.settings.checks, 20);
  assert.equal(geometry.settings.tilt, 65);
  assert.equal(geometry.fontSha256, fontSha);
  assert.equal(geometry.mesh.faces, 200);
  const geometryCases = Object.entries(geometryNames).map(([variant, label]) => {
    const base = `build/native-geometry/variants/${variant}`;
    const build = read(`${base}/build.json`);
    const proof = read(`${base}/pal-proof/verification.json`);
    assert(proof.pass, `${variant} has no passing PAL receipt`);
    assert.equal(proof.font_sha256, fontSha);
    assert.equal(proof.reference_sha256, sha(fs.readFileSync(path.join(here, 'build/geometry/frames.screen'))));
    assert.equal(proof.program_sha256, sha(fs.readFileSync(path.join(here, base, 'player.prg'))));
    const frames = build.capacity.actualPrefixFrames;
    return {id: `geometry/${variant}`, corpus: 'geometry', label,
      fps: proof.measured_fps, storedFrames: frames,
      storedSourceBytes: build.capacity.actualPrefixSourceBytes,
      sourceCapacityBytes: build.sourceCapacity, frameSourceBytes: build.frameSourceBytes,
      fontBytes: build.fontBytes, codeBytes: build.codeBytes,
      edgeCodeAndStaticBytes: build.edgeCodeBytes || 0,
      lookupAndRemapBytes: build.lookupAndRemapBytes, runtime: build.runtime,
      loadedSeedAlsoUsedAsRuntimeBytes: build.sourceKind === 3 ? 728 : 0,
      renderCycles: proof.render_cycles, preparationAndFillCycles: proof.span_decode_and_fill_cycles,
      resolveCycles: proof.resolve_cycles,
      nativePosesVerified: proof.poses_verified.length,
      actualVisibleFieldsVerified: proof.actual_scanouts_verified,
      estimatedSecondsAtMeasuredFps: frames / proof.measured_fps,
      secondsAt25FpsStorageOnly: frames / 25,
      angularRangeDegrees: (frames - 1) * step,
      program: `${base}/player.prg`, receipt: `${base}/pal-proof/verification.json`,
      programSha256: proof.program_sha256, sourceScreensSha256: proof.reference_sha256,
      timingProgramContainsOneInjectedFrame: true,
      capacityIsEncodedSequentialPrefix: true};
  });
  const analyticDelta = read('build/delta/summary.json');
  const geometryDelta = read('build/delta/geometry-native/summary.json');
  const rows = [...deltaCases(analyticDelta, 'analytic'),
    ...deltaCases(geometryDelta, 'geometry'), ...geometryCases];
  const report = {
    pass: true, settings: geometry.settings, fontSha256: fontSha, mesh: geometry.mesh,
    platform: {emulator: 'PAL VICE 3.10', clockHz: 985248, fieldClocks: 19656,
      speedPercent: 100, warp: false, musicOrOtherIrqWorkload: false},
    storageScope: 'Actual encoded prefixes in current contiguous memory layouts, with code/font/tables/runtime excluded from source arenas. These are not an optimal packing claim for every byte of C64 RAM.',
    timingScope: 'All 384 delta transitions verified through separate RAM-sized native programs. Each geometry method verified at 16 equally spaced poses, including actual completed VIC scanout. Geometry native decode, filling and glyph resolution are timed; projection is precomputed. Geometry sources are injected between paused measurements, so geometry full-prefix playback is not claimed.',
    durationScope: 'Frames divided by measured mean FPS is an estimated duration, not a complete geometry-prefix playback measurement. Storage-only seconds at 25 FPS do not imply geometry can reach 25 FPS.',
    imageScope: 'Analytic corpus reproduces the HTML full-64-pixel matching renderer. Geometry corpus uses 200 flat faces and an eight-probe glyph LUT. Geometry methods share one 384-screen reference and match all 16 native-tested poses. Geometry-delta methods match all 384 reference transitions.',
    quality: read('build/geometry/quality-comparison.json'),
    rejectedDirectPacketPath: analyticDelta.rejectedDirectPacketPath,
    rows
  };
  fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(report, null, 2) + '\n');
  const columns = ['id', 'fps', 'storedFrames', 'storedSourceBytes', 'sourceCapacityBytes',
    'estimatedSecondsAtMeasuredFps', 'secondsAt25FpsStorageOnly', 'angularRangeDegrees'];
  fs.writeFileSync(path.join(output, 'results.csv'), columns.join(',') + '\n' +
    rows.map(row => columns.map(column => row[column]).join(',')).join('\n') + '\n');
  const table = cases => ['| Variant | PAL FPS | Stored frames | Source bytes | Estimated seconds | Rotation |',
    '| --- | ---: | ---: | ---: | ---: | ---: |',
    ...cases.map(row => `| ${row.label} | ${row.fps.toFixed(3)} | ${row.storedFrames} | ${row.storedSourceBytes.toLocaleString('en-US')} | ${row.estimatedSecondsAtMeasuredFps.toFixed(2)} | ${row.angularRangeDegrees.toFixed(2)}° |`)].join('\n');
  const markdown = `# Large-sphere measured results\n\n` +
    `290-pixel diameter, 20 × 10 checker cells, 65° tilt, fixed selected 256-glyph font. ` +
    `The existing camera-axis motion uses 384 poses per 360° turn, 0.9375° per pose.\n\n` +
    `## Exact HTML images\n\n${table(rows.filter(row => row.corpus === 'analytic'))}\n\n` +
    `## Identical geometry images\n\n${table(rows.filter(row => row.corpus === 'geometry'))}\n\n` +
    `Geometry character images differ from HTML because the renderer uses flat faces and an eight-probe glyph lookup. ` +
    `The geometry delta rows provide the image-identical comparison with native filling.\n\n` +
    `Character players have 40,960 source bytes at $3000–$cfff. Geometry players have 24,064 source bytes ` +
    `at $7200–$cfff after 12,612 bytes of glyph/mask/silhouette tables. Font, code, ` +
    `first-image/XY state and working buffers are separately accounted in results.json. ` +
    `Unused address gaps have not been repacked; stored-frame counts describe these tested layouts.\n\n` +
    `Geometry capacity is the largest actual encoded prefix that fits the arena, not a mean-byte estimate. ` +
    `Geometry FPS comes from native rendering of 16 poses spread across the full turn; ` +
    `each pose's source is loaded while emulation is paused. Native XY-delta decoding, edge preparation, filling and ` +
    `glyph resolution are included. Geometry full-prefix playback has not been measured. ` +
    `Durations are frame-count/FPS estimates.\n\n` +
    `All accepted cases passed actual VIC scanout checks with refresh-on-break disabled. ` +
    `The packet decoder writing directly to the front screen is rejected: an intermediate field contains both old ` +
    `and new pixels, despite a 25 FPS final-image cadence.\n\n` +
    `[Machine-readable results](results.json) · [CSV](results.csv)\n`;
  fs.writeFileSync(path.join(output, 'results.md'), markdown);
  fs.copyFileSync(path.join(here, '../c64-preview/build/sphere-c64.png'), path.join(output, 'analytic-c64.png'));
  fs.copyFileSync(path.join(here, 'build/native-geometry/variants/packed-fast/sphere-c64.png'), path.join(output, 'geometry-c64.png'));
  console.log(JSON.stringify(rows.map(({id, fps, storedFrames, estimatedSecondsAtMeasuredFps}) =>
    ({id, fps, storedFrames, estimatedSecondsAtMeasuredFps})), null, 2));
  return report;
}

module.exports = {main};
if (require.main === module) main();
