'use strict';

// Exact storage measurement of the screenshot settings. Render with the
// original selected font, then remap to the existing coarsened/deduped font.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {buildBrowserSource4} = require('./browser-font4.cjs');
const {encodeSparse, decodeSparse, maxPrefix, summary} = require('./large-benchmark/delta-study.cjs');
const {encodeGroups, decodeGroups} = require('./large-benchmark/codegen-study.cjs');

const HERE = __dirname;
const DEFAULT_OUTPUT = path.join(HERE, 'build/settings-164');
const DEFAULT_FRAMES = 384;
const CAPACITY = 40960;
const ANGLE = 0.38;
const SETTINGS = Object.freeze({checks: 18, radius: 82, tilt: 64, solid: false});
const FONT_SHA = '68ad34844c8a998f5270c31bc16962545f6c3232555fa03f9faec134c21c5b59';
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

function capacitiesForAllStarts(payloads) {
  const results = [];
  for (let start = 0; start < payloads.length; start++) {
    let bytes = 0, frames = 1;
    while (frames < payloads.length) {
      const next = payloads[(start + frames - 1) % payloads.length].length;
      if (bytes + next > CAPACITY) break;
      bytes += next;
      frames++;
    }
    results.push({startPose: start, frames, bytes});
  }
  return {frames: summary(results.map(row => row.frames)),
    minimum: results.reduce((best, row) => row.frames < best.frames ? row : best),
    maximum: results.reduce((best, row) => row.frames > best.frames ? row : best),
    values: results};
}

function main(argv = process.argv.slice(2)) {
  const options = {};
  for (let index = 0; index < argv.length; index++) {
    const [name, inline] = argv[index].split('=');
    assert(['--frames', '--step-radians', '--output'].includes(name), 'Unknown option: ' + name);
    options[name] = inline === undefined ? argv[++index] : inline;
    assert(options[name] !== undefined, 'Missing value for ' + name);
  }
  const FRAMES = Number(options['--frames'] || DEFAULT_FRAMES);
  const STEP = Number(options['--step-radians'] || 2 * Math.PI / FRAMES);
  const OUTPUT = options['--output'] ? path.resolve(options['--output']) : DEFAULT_OUTPUT;
  assert(Number.isInteger(FRAMES) && FRAMES > 1);
  assert(Number.isFinite(STEP) && STEP > 0);
  const uniformClosedCycle = Math.abs(FRAMES * STEP - 2 * Math.PI) < 1e-10;
  const stepDegrees = STEP * 180 / Math.PI;
  fs.mkdirSync(OUTPUT, {recursive: true});
  const context = vm.createContext({});
  vm.runInContext(buildBrowserSource4(), context, {filename: 'browser-font4.generated.js'});
  for (const name of ['direct-core.js', 'sphere-renderer.js']) {
    vm.runInContext(fs.readFileSync(path.join(HERE, 'matching', name), 'utf8'), context, {filename: name});
  }
  const font = context.GlyphMath.generateCoarsenedFont();
  const bytes = Buffer.concat(Array.from(font.glyphs, glyph => Buffer.from(glyph.rows)));
  assert.equal(font.count, 168);
  assert.equal(bytes.length, 1344);
  assert.equal(sha(bytes), FONT_SHA);
  const renderer = new context.SphereMath.SphereRenderer();
  const frames = [], changes = [], used = new Set();
  let firstFineReference;
  const started = process.hrtime.bigint();
  for (let pose = 0; pose < FRAMES; pose++) {
    context.GlyphMath.renderCoarsened(renderer, {...SETTINGS, angle: ANGLE + pose * STEP}, font);
    const screen = Buffer.from(renderer.screen);
    assert(screen.every(code => code < 168));
    const mapped = context.GlyphMath.mapCoarsenedScreen(renderer.fineScreen, font);
    assert(screen.equals(Buffer.from(mapped)), 'Character selection must remain a remap of the original font.');
    frames.push(screen);
    for (const code of screen) used.add(code);
    if (pose === 0) firstFineReference = Buffer.from(renderer.source);
    if ((pose + 1) % 96 === 0) console.log(`Rendered ${pose + 1}/${FRAMES} screenshot-setting poses.`);
  }
  context.GlyphMath.renderCoarsened(renderer, {...SETTINGS, angle: ANGLE + 2 * Math.PI}, font);
  assert(Buffer.from(renderer.screen).equals(frames[0]), 'Full-turn screen must close exactly.');
  assert(Buffer.from(renderer.source).equals(firstFineReference), 'Full-turn mathematical source must close exactly.');
  const raw = Buffer.concat(frames);
  fs.writeFileSync(path.join(OUTPUT, 'font.bin'), bytes);
  fs.writeFileSync(path.join(OUTPUT, 'reference.frames'), raw);
  fs.writeFileSync(path.join(OUTPUT, 'initial.screen'), frames[0]);
  const formats = {};
  const codecs = {
    sparse: {encode: (previous, target) => encodeSparse(target, previous),
      decode: (payload, previous) => decodeSparse(payload, previous)},
    groups: {encode: (previous, target) => encodeGroups(previous, target, false),
      decode: (payload, previous) => decodeGroups(payload, previous, false)},
    hybrid: {encode: (previous, target) => encodeGroups(previous, target, true),
      decode: (payload, previous) => decodeGroups(payload, previous, true)}
  };
  for (let pose = 0; pose < FRAMES; pose++) {
    const previous = frames[pose], target = frames[(pose + 1) % FRAMES];
    changes.push(target.reduce((sum, code, cell) => sum + (code !== previous[cell]), 0));
  }
  for (const [name, codec] of Object.entries(codecs)) {
    const payloads = frames.map((previous, pose) => {
      const target = frames[(pose + 1) % FRAMES];
      const payload = Buffer.from(codec.encode(previous, target));
      assert(Buffer.from(codec.decode(payload, previous)).equals(target), `${name} transition ${pose} failed`);
      return payload;
    });
    let offset = 0;
    const index = payloads.map(payload => {const record = {offset, bytes: payload.length}; offset += payload.length; return record;});
    const source = Buffer.concat(payloads);
    const prefix = maxPrefix(payloads, CAPACITY);
    prefix.angularRangeDegrees = (prefix.frames - 1) * stepDegrees;
    fs.writeFileSync(path.join(OUTPUT, name + '.bin'), source);
    fs.writeFileSync(path.join(OUTPUT, name + '-index.json'), JSON.stringify(index));
    const allStarts = uniformClosedCycle ? capacitiesForAllStarts(payloads) : null;
    if (allStarts) fs.writeFileSync(path.join(OUTPUT, name + '-all-starts.json'), JSON.stringify(allStarts.values));
    const startSummary = allStarts ? {frames: allStarts.frames, minimum: allStarts.minimum, maximum: allStarts.maximum} : null;
    formats[name] = {cyclicPayloadBytes: source.length,
      payloadBytes: summary(payloads.map(payload => payload.length)), maximumPrefix: prefix,
      sourceSha256: sha(source), roundtripTransitionsVerified: FRAMES,
      fullTurnFitsSourceArena: source.length <= CAPACITY,
      capacityAcrossAllStartPoses: startSummary,
      requiresMoreThan8BitFrameIndex: prefix.frames > 255};
  }
  const report = {
    pass: true, frames: FRAMES, settings: {...SETTINGS, diameter: SETTINGS.radius * 2, checkerRows: 9,
      fontGlyphs: font.count, initialAngleRadians: ANGLE, grid: false, measure: true},
    imageSource: 'Exact current HTML matching selection in the original fine font, followed by the existing168-code coarsened/deduplicated mapping. No palette fitting, rematching or lossy delta filtering.',
    motion: {kind: 'camera-Y rotation of the tilted checker sphere', frames: FRAMES,
      rotationDegrees: 360, stepRadians: STEP, stepDegrees,
      sampledSpanDegrees: (FRAMES - 1) * stepDegrees,
      framesPerMathematicalTurn: 2 * Math.PI / STEP,
      fullTurnClosure: uniformClosedCycle, mathematicalFullTurnClosure: true,
      exactClosingPatchToSeed: true,
      closingStepDegrees: 360 - (FRAMES - 1) * stepDegrees,
      closureScope: uniformClosedCycle ? 'Every stored transition has the same angular step, including the closing patch.' : 'Sampled poses have the requested exact angular step; the final exact patch returns to the seed at a different angular interval. This is not a uniform closed360-degree sequence.',
      secondsPerFullTurnAt25Fps: 2 * Math.PI / STEP / 25,
      secondsPerFullTurnAt50Fps: 2 * Math.PI / STEP / 50},
    sourceScreensSha256: sha(raw), fontSha256: sha(bytes), screenBytes: 1000,
    fontBytes: bytes.length, fontGlyphsUsedAcrossMotion: used.size,
    initialScreenBytesOutsideArena: 1000,
    arena: {start: 0x3000, endExclusive: 0xd000, bytes: CAPACITY,
      otherReserved: 'Font1344B, initial screen1000B, code and2-byte frame pointers are outside this source area. The smaller font gap is not repacked into the arena.'},
    changedCharacters: summary(changes), formats,
    nativeTimingMeasured: false,
    capacityScope: 'Exact maximal source-pose-zero prefix in the existing contiguous40,960-byte layout. Capacity is computed from real encoded payloads, not average bytes. All-start ranges are included only for uniformly closed cycles. Playback duration at25/50FPS is storage divided by target rate, not a new native speed measurement.',
    verification: {actualRenderedFrames: FRAMES, nativeFontBytesMatched: true,
      preservedFineGlyphSelection: true, fullTurnScreenAndSourceClosure: true,
      codecsRoundtripTransitions: FRAMES * 3},
    hostSeconds: Number(process.hrtime.bigint() - started) / 1e9
  };
  fs.writeFileSync(path.join(OUTPUT, 'study.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({...report, formats: Object.fromEntries(Object.entries(formats).map(([name, value]) => [name, {...value, capacityAcrossAllStartPoses: value.capacityAcrossAllStartPoses}]))}, null, 2));
  return report;
}

module.exports = {main, capacitiesForAllStarts};
if (require.main === module) main();
