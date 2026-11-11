'use strict';

// Bake the native age-selection wave into ordinary fixed-font movie frames.
// The existing optimal global skip/literal encoder is used without changes.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {spawnSync} = require('node:child_process');
const {encodePairs, decodePairs} = require('../precomputed/hybrid/delta.cjs');
const {createMatcher} = require('./bitmap-to-chars.cjs');

const here = __dirname;
const LOCKED_FONT_SHA = '1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1';
const PERIOD = 96, HISTORY = 10, LOOP_START = 10, COUNT = LOOP_START + PERIOD;
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const stats = values => ({min: Math.min(...values), mean: values.reduce((a, b) => a + b, 0) / values.length, max: Math.max(...values)});
const changed = (a, b) => a.reduce((sum, value, index) => sum + Number(value !== b[index]), 0);

function sourcePose(serial) {
  return serial <= 0 ? 0 : (serial - 1) % PERIOD + 1;
}

// Matches the native 8-raster-row wave: phase starts at zero on the initial
// blank image, then advances once per committed film image. Outside the chosen
// vertical section, the newest image is selected.
function age(band, phase, firstBand, bandCount) {
  if (band < firstBand || band >= firstBand + bandCount) return 0;
  const vertical = bandCount === 1 ? 0 : (band - firstBand) / (bandCount - 1);
  return Math.round(4.5 + 4.5 * Math.sin(2 * Math.PI * (vertical + phase / PERIOD)));
}

function render(screen, font) {
  const pixels = Buffer.alloc(320 * 200);
  for (let cell = 0; cell < 1000; cell++) {
    const left = cell % 40 * 8, top = Math.floor(cell / 40) * 8;
    for (let y = 0; y < 8; y++) {
      const row = font[screen[cell] * 8 + y];
      for (let x = 0; x < 8; x++) pixels[(top + y) * 320 + left + x] = row >>> (7 - x) & 1;
    }
  }
  return pixels;
}

function rowComposite(serial, frames, firstRow, rowCount) {
  const result = Buffer.alloc(1000);
  for (let row = 0; row < 25; row++) {
    const selected = sourcePose(serial - age(row, serial % PERIOD, firstRow, rowCount));
    frames[selected].copy(result, row * 40, row * 40, row * 40 + 40);
  }
  return result;
}

function rasterComposite(serial, bitmaps, firstRow, rowCount) {
  const result = Buffer.alloc(320 * 200);
  for (let band = 0; band < 100; band++) {
    const selected = sourcePose(serial - age(band, serial % PERIOD, firstRow * 4, rowCount * 4));
    bitmaps[selected].copy(result, band * 640, band * 640, band * 640 + 640);
  }
  return result;
}

function measure(name, screens, loopStart, font, output, metadata, approximation = null) {
  const root = path.join(output, name);
  fs.mkdirSync(root, {recursive: true});
  const edges = screens.map((_, fromPose) => ({fromPose, targetPose: fromPose + 1 < screens.length ? fromPose + 1 : loopStart,
    closing: fromPose === screens.length - 1}));
  const index = [], chunks = [], differences = [];
  let offset = 0;
  for (const edge of edges) {
    const previous = screens[edge.fromPose], target = screens[edge.targetPose];
    const payload = Buffer.from(encodePairs(target, previous));
    assert(Buffer.from(decodePairs(payload, previous)).equals(target), `${name}: delta roundtrip ${edge.fromPose}`);
    index.push({...edge, offset, bytes: payload.length});
    chunks.push(payload); offset += payload.length;
    differences.push(changed(previous, target));
  }
  // Repeated playback includes the closing delta, then every outgoing loop
  // patch. This catches a false closure caused by resetting history or phase.
  let actual = Buffer.from(screens[0]);
  const play = [...index, ...index.slice(loopStart), ...index.slice(loopStart)];
  for (const edge of play) {
    assert(actual.equals(screens[edge.fromPose]));
    actual = Buffer.from(decodePairs(chunks[edge.fromPose], actual));
    assert(actual.equals(screens[edge.targetPose]));
  }
  const movie = Buffer.concat(chunks), reference = Buffer.concat(screens);
  const payloadBytes = movie.length;
  const loopRecords = index.filter(record => record.fromPose >= loopStart);
  const introPayloadBytes = index.filter(record => record.fromPose < loopStart).reduce((sum, record) => sum + record.bytes, 0);
  const loopPayloadBytes = loopRecords.reduce((sum, record) => sum + record.bytes, 0);
  const literal = {payloadBytes, pointerTableBytes: screens.length * 2,
    totalAnimationBytesWithPointers: payloadBytes + screens.length * 2,
    totalAnimationAndFontBytes: payloadBytes + screens.length * 2 + font.length,
    bytesPerFrame: stats(index.map(record => record.bytes)), loopBytesPerFrame: stats(loopRecords.map(record => record.bytes)),
    introPayloadBytes, loopPayloadBytes, closingPatchBytes: index.at(-1).bytes,
    sourceSha256: sha(movie), transitionsVerified: play.length, closingPatchIncluded: true};
  const report = {pass: true, name, frameCount: screens.length, fps: 25,
    firstImageIsImplicitBlank: true, loop: {startFrame: loopStart, frameCount: PERIOD, durationSeconds: PERIOD / 25},
    introSeconds: loopStart / 25, fontBytes: font.length, fontGlyphs: font.length / 8,
    fontUnchanged: sha(font) === LOCKED_FONT_SHA, hashes: {font: sha(font), reference: sha(reference)},
    changedCharactersPerTransition: stats(differences),
    loopChangedCharactersPerTransition: stats(differences.slice(loopStart)),
    formats: {literal}, sourceMetadata: metadata, approximation,
    nativeTimingMeasured: false,
    scope: 'Host-generated ordinary character film and exact original global skip/literal compression. Native FPS has not been measured for this new movie.'};
  fs.writeFileSync(path.join(root, 'font.bin'), font);
  fs.writeFileSync(path.join(root, 'reference.frames'), reference);
  fs.writeFileSync(path.join(root, 'literal.bin'), movie);
  fs.writeFileSync(path.join(root, 'literal-index.json'), JSON.stringify(index, null, 2) + '\n');
  fs.writeFileSync(path.join(root, 'study.json'), JSON.stringify(report, null, 2) + '\n');
  fs.writeFileSync(path.join(root, 'playback.json'), JSON.stringify([
    {op: 'play', startFrame: 0, frameCount: loopStart, repeat: 1},
    {op: 'play', startFrame: loopStart, frameCount: PERIOD, repeat: 'forever'}, {op: 'hold'}
  ], null, 2) + '\n');
  return report;
}

const PREVIEW = String.raw`import json, pathlib, sys
from PIL import Image
root = pathlib.Path(sys.argv[1])
summary = json.loads((root/'comparison.json').read_text())
for name in ['wave-rows-8', 'wave-raster-2']:
    folder = root/name
    if not folder.exists(): continue
    report = json.loads((folder/'study.json').read_text())
    font, screens = (folder/'font.bin').read_bytes(), (folder/'reference.frames').read_bytes()
    glyphs = [Image.frombytes('1',(8,8),font[i*8:i*8+8]).convert('L') for i in range(256)]
    images = []
    for serial in range(report['loop']['startFrame'], report['frameCount']):
        image = Image.new('L',(320,200))
        for cell,code in enumerate(screens[serial*1000:(serial+1)*1000]):
            image.paste(glyphs[code],(cell%40*8,cell//40*8))
        images.append(image.resize((599,400),Image.Resampling.NEAREST).convert('P'))
    images[0].save(folder/'loop-pal.gif',save_all=True,append_images=images[1:],duration=40,loop=0,optimize=False,disposal=2)
    images[25].save(folder/'poster-pal.png')
print('PAL host previews: 599x400, 59/63 pixel aspect rounded, 40ms/frame; no native timing claim.')
`;

function main(argv = process.argv.slice(2)) {
  const option = (name, fallback) => argv.find(value => value.startsWith(`--${name}=`))?.slice(name.length + 3) ?? fallback;
  const input = path.resolve(option('input', path.join(here, 'build/three-scene-flagship-star-pal/storage')));
  const output = path.resolve(option('output', path.join(here, 'build/raster-wave-study')));
  const firstRow = Number(option('start-row', 0)), rowCount = Number(option('rows', 25));
  assert(Number.isInteger(firstRow) && Number.isInteger(rowCount) && firstRow >= 0 && rowCount >= 1 && firstRow + rowCount <= 25);
  const study = JSON.parse(fs.readFileSync(path.join(input, 'study.json')));
  const raw = fs.readFileSync(path.join(input, 'reference.frames')), font = fs.readFileSync(path.join(input, 'font.bin'));
  assert.equal(study.frameCount, 97); assert.equal(study.fps, 25);
  assert.deepEqual({startFrame: study.loop.startFrame, frameCount: study.loop.frameCount}, {startFrame: 1, frameCount: PERIOD});
  assert.equal(sha(font), LOCKED_FONT_SHA); assert.equal(sha(raw), study.hashes.reference);
  const frames = Array.from({length: 97}, (_, i) => raw.subarray(i * 1000, (i + 1) * 1000));
  assert(frames[0].every(value => value === 0));
  fs.mkdirSync(output, {recursive: true});
  const metadata = {name: 'flagship-star-baked-age-wave', fontMode: 'fixed256', firstRow, rowCount,
    ageFormula: 'round(4.5 + 4.5*sin(2*pi*((band-firstBand)/(bandCount-1) + serial/96))); outside the section age=0',
    phase: 'Initial blank serial0 has phase0; advance once on each film-image commit, modulo96.',
    sourcePose: 'serial<=0 uses blank0; otherwise ((serial-1)%96)+1.',
    startup: 'Stored composites0..9 retain the real initially blank history. Only serial0 is entirely blank; history fills gradually.',
    repeatingSuffix: 'Composites10..105: latest source poses10..96,1..9, with phase10..95,0..9. Composite106 exactly reproduces composite10.',
    historyFrames: HISTORY, sourceStorage: input};
  const baseline = measure('baseline', frames, 1, font, output, {name: 'unchanged-PAL-source', fontMode: 'fixed256'});
  assert.equal(baseline.formats.literal.payloadBytes, 15272);
  assert.equal(baseline.formats.literal.sourceSha256, study.formats.literal.sourceSha256);
  const rows = Array.from({length: COUNT}, (_, serial) => rowComposite(serial, frames, firstRow, rowCount));
  assert(rowComposite(COUNT, frames, firstRow, rowCount).equals(rows[LOOP_START]));
  const exact = measure('wave-rows-8', rows, LOOP_START, font, output, {...metadata, bandHeightPixels: 8},
    {pixelError: 0, scope: 'Exact whole-character-row selection from the source movie; no additional bitmap or font approximation.'});
  let fine = null;
  if (!argv.includes('--skip-fine')) {
    const bitmaps = frames.map(frame => render(frame, font)), match = createMatcher(font, true);
    const errors = [], exactCells = [], maxTileErrors = [];
    const fineScreens = Array.from({length: COUNT}, (_, serial) => {
      const result = match(rasterComposite(serial, bitmaps, firstRow, rowCount));
      errors.push(result.statistics.mismatches); exactCells.push(result.statistics.exactCells);
      maxTileErrors.push(result.statistics.maxTileError);
      return result.screen;
    });
    assert(match(rasterComposite(COUNT, bitmaps, firstRow, rowCount)).screen.equals(fineScreens[LOOP_START]));
    const totalMismatchedPixels = errors.reduce((a, b) => a + b, 0);
    fine = measure('wave-raster-2', fineScreens, LOOP_START, font, output, {...metadata, bandHeightPixels: 2},
      {matcher: 'Existing createMatcher(lockedFont,true), minimum 8x8 Hamming error; ties choose the lowest glyph code. No object-mask constraint.',
        comparisonReference: 'Ideal2-raster-band mix of already decoded source glyph bitmaps; errors are additional to the original three.js-to-font conversion.',
        totalMismatchedPixels, comparedPixels: COUNT * 64000, pixelError: totalMismatchedPixels / (COUNT * 64000),
        mismatchedPixelsPerFrame: stats(errors), loopMismatchedPixelsPerFrame: stats(errors.slice(LOOP_START)),
        exactCellsPerFrame: stats(exactCells), maxTileError: Math.max(...maxTileErrors)});
  }
  const variants = [baseline, exact, ...(fine ? [fine] : [])].map(report => ({
    name: report.name, storedFrames: report.frameCount, loopStart: report.loop.startFrame,
    ...report.formats.literal, changedCharactersPerTransition: report.changedCharactersPerTransition,
    extraPayloadVersusBaseline: report.formats.literal.payloadBytes - baseline.formats.literal.payloadBytes,
    approximation: report.approximation
  }));
  const result = {pass: true, input, output, fontSha256: sha(font), fontUnchanged: true, method: metadata,
    storedFrameCountExplanation: '10 one-time startup composites (0..9) plus96 repeating composites (10..105) =106 stored screens and106 outgoing patches including closure. Initial blank has no stored seed. The source baseline is97 screens and97 patches.',
    pointerTableIncreaseBytes: (COUNT - 97) * 2, playbackBytecodeBytes: 11,
    variants, nativeTimingMeasured: false};
  fs.writeFileSync(path.join(output, 'comparison.json'), JSON.stringify(result, null, 2) + '\n');
  if (argv.includes('--preview')) {
    const preview = spawnSync('rtk', ['proxy', 'python3', '-c', PREVIEW, output], {stdio: 'inherit'});
    assert.equal(preview.status, 0, 'Host GIF preview failed.');
  }
  console.log(JSON.stringify(result, null, 2));
  return result;
}

module.exports = {main, age, sourcePose, rowComposite, rasterComposite};
if (require.main === module) main();
