'use strict';

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {spawnSync} = require('node:child_process');
const {checkFont} = require('./font4-storage.cjs');

const here = __dirname;
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const SOURCE = 0x3000;
const LIMIT = 0xd000;

function main(argv = process.argv.slice(2)) {
  const option = (name, fallback) => argv.find(value => value.startsWith(`--${name}=`))?.slice(name.length + 3) ?? fallback;
  const count = Number(option('glyphs', '64'));
  const codec = option('codec', 'hybrid');
  assert([64, 128, 256].includes(count));
  assert(['groups', 'hybrid'].includes(codec));
  const assets = path.join(here, 'build/font4-storage', `font${count}`);
  const frames = fs.readFileSync(path.join(assets, 'reference.frames'));
  const font = fs.readFileSync(path.join(assets, 'font.bin'));
  const encoded = fs.readFileSync(path.join(assets, `${codec}.bin`));
  const index = JSON.parse(fs.readFileSync(path.join(assets, `${codec}-index.json`)));
  assert.equal(frames.length, 384000);
  assert(frames.every(code => code < count));
  checkFont(font, count);
  const parts = [], pointers = [];
  let bytes = 0;
  for (const record of index.slice(0, -1)) {
    if (bytes + record.bytes > LIMIT - SOURCE) break;
    pointers.push(SOURCE + bytes);
    parts.push(encoded.subarray(record.offset, record.offset + record.bytes));
    bytes += record.bytes;
  }
  pointers.push(SOURCE + bytes);
  const stored = pointers.length;
  assert(stored > 1 && stored < 256, 'This native player uses an eight-bit frame index');
  const output = path.join(here, 'build/font4-native', `font${count}`, `${codec}-front`);
  fs.mkdirSync(output, {recursive: true});
  const pointerBytes = Buffer.alloc(stored * 2);
  pointers.forEach((address, index) => pointerBytes.writeUInt16LE(address, index * 2));
  const movie = Buffer.concat(parts);
  const reference = frames.subarray(0, stored * 1000);
  fs.writeFileSync(path.join(output, 'font.bin'), font);
  fs.writeFileSync(path.join(output, 'initial.screen'), frames.subarray(0, 1000));
  fs.writeFileSync(path.join(output, 'movie.bin'), movie);
  fs.writeFileSync(path.join(output, 'pointers.bin'), pointerBytes);
  fs.writeFileSync(path.join(output, 'reference.frames'), reference);
  fs.writeFileSync(path.join(output, 'main.asm'), [
    `.const PREVIEW_FRAME_COUNT = ${stored}`,
    `.const FONT_GLYPHS = ${count}`,
    `.const HYBRID_FORMAT = ${codec === 'hybrid'}`,
    '.var fontData = LoadBinary("font.bin")',
    '.var initialData = LoadBinary("initial.screen")',
    '.var movieData = LoadBinary("movie.bin")',
    '.var pointerData = LoadBinary("pointers.bin")',
    `.import source "${path.relative(output, path.join(here, 'font4-player.asm')).split(path.sep).join('/')}"`, ''
  ].join('\n'));
  const assembler = process.env.KICKASS || '/Users/rogerjohansson/.local/bin/kickass';
  const compiled = spawnSync('rtk', ['proxy', assembler, 'main.asm', '-odir', output, '-o', path.join(output, 'player.prg'), '-symbolfile', '-vicesymbols'], {cwd: output, stdio: 'inherit'});
  if (compiled.status !== 0) throw new Error('KickAssembler failed');
  const program = fs.readFileSync(path.join(output, 'player.prg'));
  const labels = Object.fromEntries([...fs.readFileSync(path.join(output, 'main.sym'), 'utf8').matchAll(/\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)/g)].map(match => [match[1], parseInt(match[2], 16)]));
  assert.equal(labels.animation_end - labels.animation, bytes);
  const result = {
    name: `${codec}-front`, variant: `${codec}-front`, codec: `four-page ${codec} character delta`,
    hidden: false, sparse: false, glyphCount: count,
    settings: {checks: 20, checkerRows: 10, radius: 145, diameter: 290, tilt: 65,
      fontGlyphs: count, logicalGlyph: [4, 4], physicalDotsPerLogicalDot: [2, 2]},
    storedFrames: stored, storedTransitions: stored - 1, firstSourcePose: 0,
    sourcePoseIndices: Array.from({length: stored}, (_, index) => index),
    angularRangeDegrees: (stored - 1) * 0.9375,
    playback: 'Forward prefix, then stop at last exact pose. No discontinuous closing loop.',
    dataArenaBytes: LIMIT - SOURCE, payloadBytes: bytes, unusedArenaBytes: LIMIT - labels.animation_end,
    fontBytes: font.length, packedLogicalFontBytes: count * 2,
    fontRamSavedVersus256Glyph8x8: 2048 - font.length,
    seedScreenBytes: 1000, pointerBytes: pointerBytes.length,
    codeStateAndPointersBytes: labels.player_code_end - 0x1000, workScreenBytes: 1024,
    zeroPageBytes: 6, basicBytes: 13, programBytes: program.length,
    meaningfulLoadedBytes: labels.player_code_end - 0x1000 + font.length + 1000 + bytes + 13,
    nativeFps: null, hashes: {program: sha(program), movie: sha(movie), font: sha(font), reference: sha(reference)},
    addresses: {code: 0x1000, codeEnd: labels.player_code_end, font: 0x2000,
      initialScreen: 0x2800, source: SOURCE, sourceEnd: labels.animation_end, front: 0x0400, hidden: null},
    capacityScope: 'Fixed40960-byte movie arena; smaller font does not automatically add its unused address gap to that arena.'
  };
  fs.writeFileSync(path.join(output, 'build.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result, null, 2));
  return result;
}

module.exports = {main};
if (require.main === module) main();
