'use strict';

// Append exact, screen-aligned Bayer tones to the existing font. The original
// 168 glyphs and the declared approved prefix remain unchanged in
// the prefix-pinned comparison. Primary matching can use every glyph.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {generateFont, toBytes} = require('../font.cjs');
const {dedupe} = require('../font4-dedupe.cjs');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const pop = n => { n -= (n >>> 1) & 0x55555555; n = (n & 0x33333333) + ((n >>> 2) & 0x33333333); return (((n + (n >>> 4)) & 0x0f0f0f0f) * 0x01010101) >>> 24; };
const matrix = [0,8,2,10,12,4,14,6,3,11,1,9,15,7,13,5];
function expand(pattern) {
  const rows = Buffer.alloc(8);
  for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) if (pattern & (1 << (y * 4 + 3 - x))) {
    rows[y * 2] |= 3 << (6 - x * 2); rows[y * 2 + 1] |= 3 << (6 - x * 2);
  }
  return rows;
}
function compact(rows) {
  let result = 0;
  for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) if ((rows[y * 2] >> (7 - x * 2)) & 1) result |= 1 << (y * 4 + 3 - x);
  assert(expand(result).equals(rows)); return result;
}
function tile(movie, frame, cell) {
  const x = cell % 40 * 4, y = Math.floor(cell / 40) * 4, shift = x % 8 ? 0 : 4;
  const at = frame * 2000 + y * 20 + (x >> 3);
  let result = 0;
  for (let row = 0; row < 4; row++) result |= ((movie[at + row * 20] >> shift) & 15) << (row * 4);
  return result;
}
function main(argv = process.argv.slice(2)) {
  const options = {};
  for (let i = 0; i < argv.length; i++) {
    const [key, inline] = argv[i].split('='); assert(['--input','--output'].includes(key));
    options[key] = inline ?? argv[++i]; assert(options[key]);
  }
  assert(options['--input'] && options['--output']);
  const input = path.resolve(options['--input']), output = path.resolve(options['--output']);
  const source = JSON.parse(fs.readFileSync(path.join(input, 'metadata.json')));
  const frames = source.frameCount;
  assert.equal(source.width, 160); assert.equal(source.height, 100); assert.equal(source.fps, 25);
  assert(Number.isInteger(frames) && frames >= 2 && frames <= 255, 'Movie frameCount must be an integer2..255.');
  if (source.approvedPrefixFrames !== undefined) assert(Number.isInteger(source.approvedPrefixFrames) && source.approvedPrefixFrames >= 0 && source.approvedPrefixFrames <= frames, 'approvedPrefixFrames must be an integer0..frameCount.');
  const prefixFrames = Math.min(source.approvedPrefixFrames ?? 125, frames);
  if (source.frames !== undefined) assert(Array.isArray(source.frames) && source.frames.length === frames, 'Phase metadata must describe every movie frame.');
  const isGrayFrame = frame => source.frames?.[frame]?.phase === 'gray';
  const movie = fs.readFileSync(path.resolve(input, source.framesFile));
  const mask = fs.readFileSync(path.resolve(input, source.objectMaskFile));
  assert.equal(movie.length, frames * 2000); assert.equal(mask.length, movie.length);
  assert.equal(sha(movie), source.hashes.frames, 'Bitmap must match the verified export metadata.');
  const base = dedupe(toBytes(generateFont())).font;
  assert.equal(base.length, 1344); assert.equal(sha(base), '68ad34844c8a998f5270c31bc16962545f6c3232555fa03f9faec134c21c5b59');
  const patterns = Array.from({length: 168}, (_, code) => compact(base.subarray(code * 8, code * 8 + 8)));
  const codes = new Map(patterns.map((pattern, code) => [pattern, code]));
  const tones = [], added = [];
  for (let coverage = 0; coverage <= 16; coverage++) {
    let pattern = 0;
    for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) if (matrix[y * 4 + x] < coverage) pattern |= 1 << (y * 4 + 3 - x);
    let code = codes.get(pattern), appended = code === undefined;
    if (appended) {code = patterns.length; patterns.push(pattern); codes.set(pattern, code); added.push({code, pattern});}
    tones.push({coverage, code, appended, pattern: pattern.toString(16).padStart(4, '0')});
  }
  const font = Buffer.concat(patterns.map(expand)); assert.equal(font.length, 1448);
  assert(font.subarray(0, base.length).equals(base));
  const toneSet = new Set(tones.map(tone => parseInt(tone.pattern, 16)));
  const contexts = [], seen = new Map(), cells = new Uint32Array(frames * 1000);
  for (let frame = 0; frame < frames; frame++) for (let cell = 0; cell < 1000; cell++) {
    const target = tile(movie, frame, cell), allowed = tile(mask, frame, cell);
    assert.equal(target & ~allowed, 0);
    const key = target + ':' + allowed;
    let id = seen.get(key);
    if (id === undefined) {
      id = contexts.length; seen.set(key, id);
      const choose = limit => {
        let code = 0, error = 17;
        for (let candidate = 0; candidate < limit; candidate++) {
          if (patterns[candidate] & ~allowed) continue;
          const value = pop(target ^ patterns[candidate]);
          if (value < error) {code = candidate; error = value;}
          if (!value) break;
        }
        return {code, error};
      };
      contexts.push({target, allowed, base: choose(168), extended: choose(patterns.length)});
    }
    cells[frame * 1000 + cell] = id;
  }
  const summarize = (name, pinPrefix) => {
    const screens = Buffer.alloc(frames * 1000), groups = {};
    const grayPatterns = new Map(); let oldPrefixChanges = 0;
    for (let frame = 0; frame < frames; frame++) for (let cell = 0; cell < 1000; cell++) {
      const context = contexts[cells[frame * 1000 + cell]];
      const choice = name === 'baseline168' || pinPrefix && frame < prefixFrames ? context.base : context.extended;
      screens[frame * 1000 + cell] = choice.code;
      assert.equal(patterns[choice.code] & ~context.allowed, 0);
      if (frame < prefixFrames) oldPrefixChanges += Number(choice.code !== context.base.code);
      const keys = ['all', frame < prefixFrames ? 'approvedPrefix' : 'addedTail'];
      if (isGrayFrame(frame)) {
        keys.push('gradientTail');
        keys.push(context.allowed === 65535 ? toneSet.has(context.target) ? 'gradientInteriorExactTone' : 'gradientInteriorOther'
          : context.allowed ? 'gradientObjectBoundary' : 'gradientBackground');
        if (context.allowed === 65535) grayPatterns.set(context.target, (grayPatterns.get(context.target) || 0) + 1);
      }
      for (const key of keys) {
        const stats = groups[key] ||= {tiles: 0, errors: 0, objectPixels: 0, whiteSourcePixels: 0, whiteOutputPixels: 0, exactTiles: 0, bayerAssignments: 0};
        stats.tiles++; stats.errors += choice.error * 4; stats.objectPixels += pop(context.allowed) * 4;
        stats.whiteSourcePixels += pop(context.target) * 4; stats.whiteOutputPixels += pop(patterns[choice.code]) * 4;
        stats.exactTiles += Number(choice.error === 0); stats.bayerAssignments += Number(toneSet.has(patterns[choice.code]));
      }
    }
    for (const stats of Object.values(groups)) stats.objectErrorFraction = stats.errors / Math.max(1, stats.objectPixels);
    const writes = []; let bytes = 0;
    for (let frame = 1; frame < frames; frame++) {
      let changes = 0;
      for (let page = 0; page < 4; page++) {
        let count = 0;
        for (let offset = 0; offset < Math.min(256, 1000 - page * 256); offset++) {
          const cell = page * 256 + offset;
          count += Number(screens[frame * 1000 + cell] !== screens[(frame - 1) * 1000 + cell]);
        }
        assert(count <= 255); bytes += 1 + count * 2; changes += count;
      }
      writes.push(changes);
    }
    const glyphBytes = name === 'baseline168' ? base.length : font.length;
    return {screens, report: {groups, prefixChangedCharacters: oldPrefixChanges, screensSha256: sha(screens),
      prefixSha256: sha(screens.subarray(0, prefixFrames * 1000)), fontBytes: glyphBytes,
      sparsePayloadBytes: bytes, pointerBytes: frames * 2, playbackScriptBytes: 6,
      estimatedLoadedBytesWithExisting473BytePlayerAnd13ByteBasic: bytes + glyphBytes + frames * 2 + 6 + 473 + 13,
      fits40960ByteMovieArena: bytes <= 40960, changedCharactersPerUpdate: {min: Math.min(...writes),
        mean: writes.reduce((a,b) => a+b, 0) / writes.length, max: Math.max(...writes)},
      gradientInteriorUniquePatterns: grayPatterns.size,
      gradientInteriorExactTonePatternOccurrences: [...grayPatterns].filter(([pattern]) => toneSet.has(pattern)).reduce((sum, [,count]) => sum + count, 0),
      gradientInteriorObservedToneCoverages: tones.filter(tone => grayPatterns.has(parseInt(tone.pattern,16))).map(tone => tone.coverage),
      nativeFpsMeasured: false}};
  };
  const pinnedName = `extendedAfter${prefixFrames}`;
  const baseline = summarize('baseline168', true), all = summarize('extendedAllFrames', false), pinned = summarize(pinnedName, true);
  assert(pinned.screens.subarray(0, prefixFrames * 1000).equals(baseline.screens.subarray(0, prefixFrames * 1000)));
  const baselineFile = path.join(__dirname, '../build/three-scene-gradient-c64/baseline-characters/reference.frames');
  const baselineMetadataFile = path.join(path.dirname(baselineFile), 'metadata.json');
  const sameBaselineSource = fs.existsSync(baselineMetadataFile) &&
    JSON.parse(fs.readFileSync(baselineMetadataFile)).hashes.sourcePacked === sha(movie);
  const parity = sameBaselineSource && fs.existsSync(baselineFile) ? fs.readFileSync(baselineFile).equals(baseline.screens) : null;
  if (parity !== null) assert(parity, 'Independent16-bit matcher differs from the production baseline.');
  const metadata = {pass: true, glyphs: patterns.length, fontBytes: font.length, originalGlyphs: 168,
    appendedGlyphs: added.length, sourceFontSha256: sha(base), fontSha256: sha(font),
    existingCodesUnchanged: true, extendedCandidatesStartFrame: prefixFrames, tones};
  const study = {pass: true, sourceBitmapSha256: sha(movie), uniqueTargetAndMaskContexts: contexts.length,
    productionBaselineParity: parity, metadata, variants: {baseline168: baseline.report, extendedAllFrames: all.report, [pinnedName]: pinned.report},
    scope: 'Only13 missing exact Bayer tone glyphs appended. No168-glyph replacement, font training, Three changes or native FPS inference.'};
  fs.mkdirSync(output, {recursive: true});
  fs.writeFileSync(path.join(output, 'font.bin'), font);
  fs.writeFileSync(path.join(output, 'metadata.json'), JSON.stringify(metadata,null,2)+'\n');
  fs.writeFileSync(path.join(output, 'study.json'), JSON.stringify(study,null,2)+'\n');
  fs.writeFileSync(path.join(output, 'baseline.reference.frames'), baseline.screens);
  fs.writeFileSync(path.join(output, 'extended.reference.frames'), pinned.screens);
  console.log(JSON.stringify({...study, variants:Object.fromEntries(Object.entries(study.variants).map(([key,value]) => [key,
    {...value,groups:{all:value.groups.all,gradientTail:value.groups.gradientTail,gradientInteriorExactTone:value.groups.gradientInteriorExactTone,gradientObjectBoundary:value.groups.gradientObjectBoundary}}]))},null,2));
  return study;
}
module.exports = {main};
if (require.main === module) main();
