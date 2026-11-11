'use strict';

// Compare unchanged delta formats on fixed 4x4 logical fonts. Font pixels are
// expanded to 2x2 physical dots; every C64 glyph still occupies eight bytes.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {encodeSparse, decodeSparse, maxPrefix, summary} = require('./large-benchmark/delta-study.cjs');
const {pageGroups, encodeGroups, decodeGroups} = require('./large-benchmark/codegen-study.cjs');

const here = __dirname;
const input = path.join(here, 'build/font4');
const output = path.join(here, 'build/font4-storage');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const FORMATS = {
  sparse: {encode: (previous, target) => encodeSparse(target, previous), decode: (payload, previous) => decodeSparse(payload, previous)},
  groups: {encode: (previous, target) => encodeGroups(previous, target, false), decode: (payload, previous) => decodeGroups(payload, previous, false)},
  hybrid: {encode: (previous, target) => encodeGroups(previous, target, true), decode: (payload, previous) => decodeGroups(payload, previous, true)}
};

function checkFont(font, count) {
  assert(Number.isInteger(count) && count > 0 && count <= 256);
  assert.equal(font.length, count * 8);
  for (let code = 0; code < count; code++) for (let row = 0; row < 8; row++) {
    const value = font[code * 8 + row];
    assert.equal(value, font[code * 8 + (row ^ 1)], 'Logical row must expand to two physical rows');
    for (let column = 0; column < 8; column += 2) {
      assert.equal((value >>> column) & 1, (value >>> (column + 1)) & 1, 'Logical column must expand to two physical columns');
    }
  }
}

function main(argv = process.argv.slice(2)) {
  const deduped = argv.includes('--deduped');
  const selected = deduped ? ['deduped'] : argv.length ? argv.map(Number) : [64, 128, 256];
  const cases = [];
  fs.mkdirSync(output, {recursive: true});
  for (const selection of selected) {
    const dedupeInput = path.join(here, 'build/font4-dedupe');
    const font = fs.readFileSync(deduped ? path.join(dedupeInput, 'font.bin') : path.join(input, `font${selection}.bin`));
    const raw = fs.readFileSync(deduped ? path.join(dedupeInput, 'reference.frames') : path.join(input, `frames${selection}.screen`));
    const count = deduped ? font.length / 8 : selection;
    if (!deduped) assert([64, 128, 256].includes(count));
    checkFont(font, count);
    assert.equal(raw.length, 384000);
    assert(raw.every(code => code < count));
    const frames = Array.from({length: 384}, (_, index) => raw.subarray(index * 1000, (index + 1) * 1000));
    const directory = path.join(output, deduped ? 'deduped' : `font${count}`);
    fs.mkdirSync(directory, {recursive: true});
    const changes = [], groupsPerPage = [], groupsPerFrame = [], distinctPerFrame = [], occupiedPerFrame = [];
    let positionsInGroups = 0, groupCount = 0, singletonGroups = 0;
    for (let frame = 0; frame < frames.length; frame++) {
      const previous = frames[frame], target = frames[(frame + 1) % frames.length];
      const groups = pageGroups(previous, target);
      changes.push(target.reduce((sum, code, cell) => sum + (code !== previous[cell]), 0));
      groupsPerFrame.push(groups.reduce((sum, page) => sum + page.length, 0));
      groupsPerPage.push(...groups.map(page => page.length));
      for (const group of groups.flat()) {
        positionsInGroups += group.offsets.length;
        groupCount++;
        singletonGroups += Number(group.offsets.length === 1);
      }
      distinctPerFrame.push(new Set(groups.flat().map(group => group.glyph)).size);
      occupiedPerFrame.push(new Set(target).size);
    }
    const record = {
      pass: true, glyphCount: count, fontBytes: font.length, packedLogicalFontBytes: count * 2,
      sourceKind: deduped ? 'Current256-glyph font coarsened to2x2 dots, stable deduplication, original screens remapped; no new palette fitting or rematching.' : 'New fixed4x4 palette fitted to analytic reference pixels; not the current-font coarsening experiment.',
      physicalGlyph: [8, 8], logicalGlyph: [4, 4], physicalDotsPerLogicalDot: [2, 2],
      frameCount: frames.length, screenCharacters: 1000, sourceAreaBytes: 40960,
      fontSha256: sha(font), sourceScreensSha256: sha(raw),
      changedCharacters: summary(changes), glyphGroupsPerPage: summary(groupsPerPage),
      glyphGroupsPerFrame: summary(groupsPerFrame), distinctUpdateGlyphsPerFrame: summary(distinctPerFrame),
      positionsPerGroup: positionsInGroups / groupCount, singletonGroupFraction: singletonGroups / groupCount,
      occupiedGlyphsPerFrame: summary(occupiedPerFrame), formats: {},
      capacityScope: 'Same $3000-$cfff 40960-byte source arena; font, initial screen and frame pointers remain outside it. Smaller font leaves unused address space, not automatically a larger source arena.',
      nativeTimingMeasured: false
    };
    for (const [name, codec] of Object.entries(FORMATS)) {
      const payloads = frames.map((previous, frame) => {
        const target = frames[(frame + 1) % frames.length];
        const payload = codec.encode(previous, target);
        assert(codec.decode(payload, previous).equals(target), `font${count}/${name} roundtrip ${frame}`);
        return payload;
      });
      let offset = 0;
      const index = payloads.map(payload => { const value = {offset, bytes: payload.length}; offset += payload.length; return value; });
      fs.writeFileSync(path.join(directory, `${name}.bin`), Buffer.concat(payloads));
      fs.writeFileSync(path.join(directory, `${name}-index.json`), JSON.stringify(index));
      record.formats[name] = {cyclicPayloadBytes: offset, payloadBytes: summary(payloads.map(payload => payload.length)),
        maximumPrefix: maxPrefix(payloads), sourceSha256: sha(Buffer.concat(payloads)),
        roundtripTransitionsVerified: frames.length};
    }
    fs.writeFileSync(path.join(directory, 'font.bin'), font);
    fs.writeFileSync(path.join(directory, 'reference.frames'), raw);
    fs.writeFileSync(path.join(directory, 'study.json'), JSON.stringify(record, null, 2) + '\n');
    cases.push(record);
  }
  const baselinePath = path.join(here, 'large-benchmark/build/codegen/summary.json');
  const baseline = fs.existsSync(baselinePath) ? JSON.parse(fs.readFileSync(baselinePath)).cases.find(value => value.dataset === 'analytic') : null;
  const result = {pass: true, cases, originalFontBaseline: baseline,
    scope: 'All 384 same-motion fixed-font frames. Sparse/group/hybrid headers are included; no native FPS inferred from host storage.'};
  fs.writeFileSync(path.join(output, deduped ? 'deduped-summary.json' : 'summary.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(cases.map(row => ({glyphCount: row.glyphCount, fontBytes: row.fontBytes,
    changedMean: row.changedCharacters.mean, distinctUpdateGlyphs: row.distinctUpdateGlyphsPerFrame.mean,
    formats: Object.fromEntries(Object.entries(row.formats).map(([name, format]) => [name, {
      bytes: format.cyclicPayloadBytes, frames: format.maximumPrefix.frames}]))})), null, 2));
  return result;
}

module.exports = {main, checkFont};
if (require.main === module) main();
