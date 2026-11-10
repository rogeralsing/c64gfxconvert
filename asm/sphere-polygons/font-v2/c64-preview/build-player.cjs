'use strict';

// A bounded arc of the HTML renderer's exact character screens. Each XOR patch
// works in either direction, so reversing the arc needs no second movie stream.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');

const here = __dirname;
const output = path.join(here, 'build');
const FRAME_COUNT = 48;
const SCREEN_BYTES = 1000;
const SOURCE_ADDRESS = 0x3000;
const SOURCE_LIMIT = 0xd000;
const FONT_SHA256 = 'e4071e1e3176e3ee65eeb5fc2df5bb3eccab7b733b9ea7cbb276a2f3a65a1aac';
const sha256 = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const hex = value => '$' + value.toString(16).padStart(4, '0');

function main() {
  fs.mkdirSync(output, {recursive: true});
  const raw = fs.readFileSync(path.join(output, 'movie.frames'));
  const font = fs.readFileSync(path.join(output, 'font.bin'));
  assert.equal(raw.length % SCREEN_BYTES, 0, 'movie.frames must contain complete screens');
  assert(raw.length >= FRAME_COUNT * SCREEN_BYTES, 'The generator must export at least 48 frames');
  assert.equal(font.length, 2048);
  assert.equal(sha256(font), FONT_SHA256);
  const frames = Array.from({length: FRAME_COUNT}, (_, index) => raw.subarray(index * SCREEN_BYTES, (index + 1) * SCREEN_BYTES));
  const records = [];
  const pointers = [];
  const payloadSizes = [];
  const changedCells = [];
  let bytes = 0;
  for (let index = 0; index < FRAME_COUNT - 1; index++) {
    const mask = Uint8Array.from(frames[index], (code, cell) => code ^ frames[index + 1][cell]);
    const bytesForPatch = [];
    for (let page = 0; page < 4; page++) {
      const pairs = [];
      for (let offset = 0; offset < Math.min(256, SCREEN_BYTES - page * 256); offset++) {
        const value = mask[page * 256 + offset];
        if (value) pairs.push(offset, value);
      }
      assert(pairs.length / 2 < 256, `Patch ${index} page ${page} exceeds one-byte count`);
      bytesForPatch.push(pairs.length / 2, ...pairs);
    }
    const payload = Buffer.from(bytesForPatch);
    const decoded = new Uint8Array(SCREEN_BYTES);
    let read = 0;
    for (let page = 0; page < 4; page++) {
      const count = payload[read++];
      for (let pair = 0; pair < count; pair++) {
        const offset = payload[read++], value = payload[read++];
        assert(offset < Math.min(256, SCREEN_BYTES - page * 256));
        assert(value !== 0);
        decoded[page * 256 + offset] = value;
      }
    }
    assert.equal(read, payload.length);
    assert.deepEqual(Buffer.from(decoded), Buffer.from(mask));
    for (const [source, target] of [[frames[index], frames[index + 1]], [frames[index + 1], frames[index]]]) {
      const actual = Buffer.alloc(SCREEN_BYTES);
      for (let cell = 0; cell < SCREEN_BYTES; cell++) actual[cell] = source[cell] ^ decoded[cell];
      assert(actual.equals(target), `Reversible patch ${index} failed`);
    }
    pointers.push(SOURCE_ADDRESS + bytes);
    records.push(payload);
    bytes += payload.length;
    payloadSizes.push(payload.length);
    changedCells.push(mask.reduce((sum, value) => sum + (value !== 0), 0));
  }
  assert(SOURCE_ADDRESS + bytes <= SOURCE_LIMIT, `XOR movie exceeds native RAM by ${SOURCE_ADDRESS + bytes - SOURCE_LIMIT} bytes`);
  const movie = Buffer.concat(records);
  fs.writeFileSync(path.join(output, 'player-initial.screen'), frames[0]);
  fs.writeFileSync(path.join(output, 'player-movie.xor'), movie);
  fs.writeFileSync(path.join(output, 'player-config.inc'), [
    `.const PREVIEW_FRAME_COUNT = ${FRAME_COUNT}`,
    `.const PREVIEW_PATCH_COUNT = ${FRAME_COUNT - 1}`,
    `.const PREVIEW_SOURCE_BYTES = ${movie.length}`,
    ''
  ].join('\n'));
  fs.writeFileSync(path.join(output, 'player-pointers.inc'), [
    'patch_pointer_low:',
    '    .byte ' + pointers.map(value => hex(value & 255)).join(', '),
    'patch_pointer_high:',
    '    .byte ' + pointers.map(value => hex(value >>> 8)).join(', '),
    ''
  ].join('\n'));

  const assembler = process.env.KICKASS || '/Users/rogerjohansson/.local/bin/kickass';
  const built = spawnSync('rtk', ['proxy', assembler, 'player.asm', '-odir', output, '-o', path.join(output, 'player.prg'), '-debugdump', '-debug', '-symbolfile', '-vicesymbols'], {cwd: here, stdio: 'inherit'});
  if (built.status !== 0) throw new Error(`KickAssembler failed (${built.status ?? built.signal})`);
  const program = fs.readFileSync(path.join(output, 'player.prg'));
  const metadata = {
    frames: FRAME_COUNT,
    patches: FRAME_COUNT - 1,
    traversal: '0..47,46..0,1..47; reversible bounded arc, no discontinuous closing patch',
    stepDegrees: 0.9375,
    arcDegrees: (FRAME_COUNT - 1) * 0.9375,
    roundTripDisplayedFrames: 2 * (FRAME_COUNT - 1),
    requestedFieldsPerFrame: 2,
    palCadenceVerified: false,
    codec: 'page-sparse XOR: four page records, each count8 followed by count pairs of offset8 and nonzero XOR mask8',
    addresses: {code: 0x1000, font: 0x2000, initialScreen: 0x2800, frontScreen: 0x0400, hiddenScreen: 0x0800, movie: SOURCE_ADDRESS, movieEnd: SOURCE_ADDRESS + movie.length, movieLimit: SOURCE_LIMIT},
    sourceBytes: movie.length,
    pointerBytes: 2 * pointers.length,
    initialScreenBytes: SCREEN_BYTES,
    fontBytes: font.length,
    payloadSizes,
    changedCells,
    hashes: {font: sha256(font), initialScreen: sha256(frames[0]), selectedFrames: sha256(raw.subarray(0, FRAME_COUNT * SCREEN_BYTES)), movie: sha256(movie), program: sha256(program)},
    programBytes: program.length
  };
  fs.writeFileSync(path.join(output, 'player-build.json'), JSON.stringify(metadata, null, 2) + '\n');
  console.log(JSON.stringify(metadata, null, 2));
  return metadata;
}

module.exports = {main};
if (require.main === module) main();
