'use strict';

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {spawnSync} = require('node:child_process');

const here = __dirname;
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const SOURCE = 0x3000;
const LIMIT = 0xd000;

function main(argv = process.argv.slice(2)) {
  const option = (name, fallback) => argv.find(value => value.startsWith(`--${name}=`))?.slice(name.length + 3) ?? fallback;
  const dataset = option('dataset', 'analytic');
  assert(['analytic', 'protected4'].includes(dataset));
  const assets = path.join(here, 'build/codegen', dataset);
  const frames = fs.readFileSync(path.join(assets, 'reference.frames'));
  const font = fs.readFileSync(path.join(assets, 'font.bin'));
  const encoded = fs.readFileSync(path.join(assets, 'hybrid.bin'));
  const index = JSON.parse(fs.readFileSync(path.join(assets, 'hybrid-index.json')));
  assert.equal(frames.length, 384000);
  assert.equal(font.length, 2048);
  assert.equal(sha(font), 'e4071e1e3176e3ee65eeb5fc2df5bb3eccab7b733b9ea7cbb276a2f3a65a1aac');
  const parts = [];
  const pointers = [];
  let sourceBytes = 0;
  // A forward prefix has at most383 transitions; the corpus's closing patch
  // remains available for separate loop tests and is not an extra stored pose.
  for (const record of index.slice(0, -1)) {
    if (sourceBytes + record.bytes > LIMIT - SOURCE) break;
    pointers.push(SOURCE + sourceBytes);
    parts.push(encoded.subarray(record.offset, record.offset + record.bytes));
    sourceBytes += record.bytes;
  }
  pointers.push(SOURCE + sourceBytes);
  const count = pointers.length;
  assert(count > 1 && count < 256);
  const output = path.join(here, 'build/grouped-native', dataset, 'hybrid-front');
  fs.mkdirSync(output, {recursive: true});
  const pointerBytes = Buffer.alloc(count * 2);
  pointers.forEach((address, index) => pointerBytes.writeUInt16LE(address, index * 2));
  const movie = Buffer.concat(parts);
  const reference = frames.subarray(0, count * 1000);
  fs.writeFileSync(path.join(output, 'font.bin'), font);
  fs.writeFileSync(path.join(output, 'initial.screen'), frames.subarray(0, 1000));
  fs.writeFileSync(path.join(output, 'movie.bin'), movie);
  fs.writeFileSync(path.join(output, 'pointers.bin'), pointerBytes);
  fs.writeFileSync(path.join(output, 'reference.frames'), reference);
  fs.writeFileSync(path.join(output, 'main.asm'), [
    `.const PREVIEW_FRAME_COUNT = ${count}`,
    '.var fontData = LoadBinary("font.bin")',
    '.var initialData = LoadBinary("initial.screen")',
    '.var movieData = LoadBinary("movie.bin")',
    '.var pointerData = LoadBinary("pointers.bin")',
    `.import source "${path.relative(output, path.join(here, 'grouped-player.asm')).split(path.sep).join('/')}"`, ''
  ].join('\n'));
  const assembler = process.env.KICKASS || '/Users/rogerjohansson/.local/bin/kickass';
  const compiled = spawnSync('rtk', ['proxy', assembler, 'main.asm', '-odir', output, '-o', path.join(output, 'player.prg'), '-symbolfile', '-vicesymbols'], {cwd: output, stdio: 'inherit'});
  if (compiled.status !== 0) throw new Error('KickAssembler failed');
  const program = fs.readFileSync(path.join(output, 'player.prg'));
  const labels = Object.fromEntries([...fs.readFileSync(path.join(output, 'main.sym'), 'utf8').matchAll(/\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)/g)].map(match => [match[1], parseInt(match[2], 16)]));
  assert.equal(labels.animation_end - labels.animation, sourceBytes);
  const result = {
    name: 'hybrid-front', variant: 'hybrid-front', codec: 'four-page grouped glyphs with singles',
    hidden: false, sparse: false, dataset,
    settings: {checks: 20, checkerRows: 10, radius: 145, diameter: 290, tilt: 65, fontGlyphs: 256},
    storedFrames: count, storedTransitions: count - 1, firstSourcePose: 0,
    sourcePoseIndices: Array.from({length: count}, (_, index) => index),
    angularRangeDegrees: (count - 1) * 0.9375,
    playback: 'Forward prefix, then stop at last exact pose. No closing discontinuity.',
    abi: 'Four sequential pages: groupCount8,singleCount8, groups[glyph8,count8,offset8...], singles[offset8,glyph8...].',
    dataArenaBytes: LIMIT - SOURCE, payloadBytes: sourceBytes, unusedArenaBytes: LIMIT - labels.animation_end,
    fontBytes: 2048, seedScreenBytes: 1000, pointerBytes: pointerBytes.length,
    codeStateAndPointersBytes: labels.player_code_end - 0x1000, workScreenBytes: 1024,
    zeroPageBytes: 6, basicBytes: 13, programBytes: program.length,
    meaningfulLoadedBytes: labels.player_code_end - 0x1000 + 2048 + 1000 + sourceBytes + 13,
    nativeFps: null, hashes: {program: sha(program), movie: sha(movie), font: sha(font), reference: sha(reference)},
    addresses: {code: 0x1000, codeEnd: labels.player_code_end, font: 0x2000,
      initialScreen: 0x2800, source: SOURCE, sourceEnd: labels.animation_end, front: 0x0400, hidden: null}
  };
  fs.writeFileSync(path.join(output, 'build.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result, null, 2));
  return result;
}

module.exports = {main};
if (require.main === module) main();
