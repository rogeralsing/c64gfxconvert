'use strict';

// Build the entire scene with an optional repeating suffix, without truncation.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {spawnSync} = require('node:child_process');

const here = __dirname;
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const SOURCE = 0x3000;
const LIMIT = 0xd000;
const POOLS = [
  {name: 'main', start: SOURCE, end: LIMIT, file: 'movie.bin'},
  {name: 'middle', start: 0x1400, end: 0x2000, file: 'movie-middle.bin'},
  {name: 'upper', start: 0x2800, end: 0x3000, file: 'movie-upper.bin'},
  {name: 'low', start: 0x0900, end: 0x1000, file: 'movie-low.bin'}
];

// The decoder already reloads a 16-bit pointer for every patch. Keep each patch
// contiguous, using existing RAM gaps only when the original arena is too small.
function packMovie(movie, index, middleStart = 0x1400) {
  let offset = 0;
  for (const record of index) {
    assert.equal(record.offset, offset, 'Sparse patches must cover the movie contiguously.');
    assert(Number.isInteger(record.bytes) && record.bytes > 0, 'Sparse patches must have a positive whole-byte length.');
    offset += record.bytes;
    assert(offset <= movie.length, 'Sparse patch extends beyond the movie.');
  }
  assert.equal(offset, movie.length, 'Sparse patch index must cover the entire movie.');
  const pooled = movie.length > LIMIT - SOURCE;
  const pools = (pooled ? POOLS : POOLS.slice(0, 1)).map(pool => ({...pool, start: pool.name === 'middle' ? middleStart : pool.start, file: pooled && pool.name === 'main' ? 'movie-main.bin' : pool.file, bytes: 0, frames: [], chunks: []}));
  const pointers = new Array(index.length);
  if (!pooled) {
    pools[0].bytes = movie.length;
    pools[0].frames = index.map((_, frame) => frame);
    pools[0].chunks.push(movie);
    index.forEach((record, frame) => {pointers[frame] = SOURCE + record.offset;});
  } else {
    assert(movie.length <= pools.reduce((sum, pool) => sum + pool.end - pool.start, 0), 'The complete clip must fit the available data pools.');
    // First-fit decreasing is deterministic; frame order breaks equal-size ties.
    const ordered = index.map((record, frame) => ({...record, frame})).sort((a, b) => b.bytes - a.bytes || a.frame - b.frame);
    for (const record of ordered) {
      const pool = pools.find(candidate => candidate.bytes + record.bytes <= candidate.end - candidate.start);
      assert(pool, `No contiguous RAM pool fits sparse patch ${record.frame} (${record.bytes} bytes).`);
      pointers[record.frame] = pool.start + pool.bytes;
      pool.chunks.push(movie.subarray(record.offset, record.offset + record.bytes));
      pool.frames.push(record.frame);
      pool.bytes += record.bytes;
    }
  }
  for (const pool of pools) {
    pool.data = Buffer.concat(pool.chunks);
    delete pool.chunks;
    assert.equal(pool.data.length, pool.bytes);
  }
  return {pooled, pools, pointers, capacity: pools.reduce((sum, pool) => sum + pool.end - pool.start, 0)};
}

function compilePlayback(commands, edges, frameCount, fps = 25) {
  assert(Array.isArray(commands) && commands.length >= 2, 'Playback must be a JSON command array ending with hold.');
  assert.equal(commands.at(-1).op, 'hold', 'Playback must end with hold.');
  const outgoing = new Map(edges.map(edge => [edge.fromPose, edge.targetPose]));
  const data = [], normalized = [];
  let previousEnd = null, totalDisplayedFrames = 0, forever = false;
  for (const [commandIndex, command] of commands.entries()) {
    if (command.op === 'hold') {
      assert.equal(commandIndex, commands.length - 1, 'Hold must be the final command.');
      normalized.push({op: 'hold'}); data.push(0); continue;
    }
    assert.equal(command.op, 'play', 'Unsupported playback opcode.');
    assert(!forever, 'No play command may follow an infinite play.');
    const {startFrame, frameCount: count, repeat} = command;
    assert(Number.isInteger(startFrame) && startFrame >= 0 && startFrame <= 255);
    assert(Number.isInteger(count) && count >= 1 && count <= 255 && startFrame + count <= frameCount);
    assert(repeat === 'forever' || Number.isInteger(repeat) && repeat >= 1 && repeat <= 65535,
      'repeat must be an integer1..65535 or the string forever.');
    const end = startFrame + count - 1;
    if (previousEnd === null) assert.equal(startFrame, 0, 'The initial play must start at the implicit blank frame0.');
    else assert.equal(outgoing.get(previousEnd), startFrame, `Unsupported transition ${previousEnd}->${startFrame}`);
    for (let pose = startFrame; pose < end; pose++) assert.equal(outgoing.get(pose), pose + 1, `Unsupported transition ${pose}->${pose + 1}`);
    if (repeat === 'forever' || repeat > 1) assert.equal(outgoing.get(end), startFrame, `Unsupported repeat transition ${end}->${startFrame}`);
    const encodedRepeat = repeat === 'forever' ? 0 : repeat;
    data.push(1, startFrame, count, encodedRepeat & 255, encodedRepeat >> 8);
    normalized.push({op: 'play', startFrame, frameCount: count, repeat});
    if (repeat === 'forever') forever = true;
    else totalDisplayedFrames += count * repeat;
    previousEnd = end;
  }
  assert(data.length <= 255, 'Playback bytecode must fit the8-bit script cursor.');
  assert(previousEnd !== null, 'Playback must contain a play command.');
  return {commands: normalized, bytecode: Buffer.from(data), bytecodeBytes: data.length,
    totalDisplayedFrames: forever ? null : totalDisplayedFrames,
    nominalSeconds: forever ? null : totalDisplayedFrames / fps, repeatsForever: forever};
}

function main(argv = process.argv.slice(2)) {
  const option = (name, fallback) => {const inline = argv.find(value => value.startsWith(`--${name}=`)); if (inline) return inline.slice(name.length + 3); const index = argv.indexOf(`--${name}`); return index >= 0 ? argv[index + 1] : fallback;};
  const input = path.resolve(option('input', path.join(here, 'build/scene-storage/spiral')));
  const root = path.resolve(option('output', path.join(here, 'build/scene-native/spiral')));
  const codec = option('codec', 'sparse');
  assert(['sparse', 'literal'].includes(codec), '--codec must be sparse or literal.');
  const literal = codec === 'literal';
  const variant = literal ? 'literal-front' : 'sparse-front';
  const output = path.join(root, variant);
  const study = JSON.parse(fs.readFileSync(path.join(input, 'study.json')));
  const reference = fs.readFileSync(path.join(input, 'reference.frames'));
  const font = fs.readFileSync(path.join(input, 'font.bin'));
  const movie = fs.readFileSync(path.join(input, `${codec}.bin`));
  const index = JSON.parse(fs.readFileSync(path.join(input, `${codec}-index.json`)));
  const scriptPath = path.resolve(option('script', path.join(here, 'scenes/spiral.playback.json')));
  const count = study.frameCount;
  const loop = study.loop;
  assert(count > 1 && count < 256);
  assert.equal(study.fps, 25);
  assert.equal(reference.length, count * 1000);
  assert(font.length >= 1344 && font.length <= 2048 && font.length % 8 === 0,
    'Font must contain the original168 glyphs plus whole appended glyphs within the256-glyph VIC charset.');
  assert.equal(sha(font.subarray(0, 1344)), '68ad34844c8a998f5270c31bc16962545f6c3232555fa03f9faec134c21c5b59',
    'The original168 glyphs and character codes must remain unchanged.');
  assert(reference.every(code => code < font.length / 8));
  assert.equal(index.length, count - (loop ? 0 : 1));
  assert(reference.subarray(0, 1000).every(code => code === 0));
  assert.equal(sha(reference), study.hashes.reference);
  assert.equal(sha(font), study.hashes.font);
  assert.equal(sha(movie), study.formats[codec].sourceSha256);
  const playback = compilePlayback(JSON.parse(fs.readFileSync(scriptPath)), index, count, study.fps);
  const middleStart = literal ? 0x1700 : 0x1400;
  const packed = packMovie(movie, index, middleStart);
  const mainPool = packed.pools[0];
  fs.mkdirSync(output, {recursive: true});
  const pointers = Buffer.alloc(count * 2);
  index.forEach((record, frame) => {
    assert.equal(record.fromPose, frame);
    assert.equal(record.targetPose, frame === count - 1 ? loop.startFrame : frame + 1);
    pointers.writeUInt16LE(packed.pointers[frame], frame * 2);
  });
  if (!loop) pointers.writeUInt16LE(SOURCE + mainPool.bytes, (count - 1) * 2);
  for (const [name, bytes] of Object.entries({'font.bin': font, 'movie.bin': movie, 'pointers.bin': pointers, 'reference.frames': reference, 'playback.bin': playback.bytecode})) {
    fs.writeFileSync(path.join(output, name), bytes);
  }
  for (const pool of packed.pools) fs.writeFileSync(path.join(output, pool.file), pool.data);
  const playbackMetadata = {...playback, source: scriptPath};
  delete playbackMetadata.bytecode;
  fs.writeFileSync(path.join(output, 'playback.json'), JSON.stringify(playback.commands, null, 2) + '\n');
  fs.writeFileSync(path.join(output, 'playback-metadata.json'), JSON.stringify(playbackMetadata, null, 2) + '\n');
  fs.writeFileSync(path.join(output, 'main.asm'), [
    `.const PREVIEW_FRAME_COUNT = ${count}`,
    `.const LOOP_START_FRAME = ${loop?.startFrame ?? -1}`,
    `.const MOVIE_POOLED = ${packed.pooled}`,
    `.const MOVIE_MIDDLE_START = ${middleStart}`,
    `.const LITERAL_CODEC = ${literal}`,
    '.var fontData = LoadBinary("font.bin")',
    `.var movieData = LoadBinary("${mainPool.file}")`,
    ...(packed.pooled ? [
      '.var movieLowData = LoadBinary("movie-low.bin")',
      '.var movieMiddleData = LoadBinary("movie-middle.bin")',
      '.var movieUpperData = LoadBinary("movie-upper.bin")'
    ] : [
      '.var movieLowData = movieData',
      '.var movieMiddleData = movieData',
      '.var movieUpperData = movieData'
    ]),
    '.var pointerData = LoadBinary("pointers.bin")',
    '.var scriptData = LoadBinary("playback.bin")',
    `.import source "${path.relative(output, path.join(here, 'scene-player.asm')).split(path.sep).join('/')}"`, ''
  ].join('\n'));
  const assembler = process.env.KICKASS || '/Users/rogerjohansson/.local/bin/kickass';
  const compiled = spawnSync('rtk', ['proxy', assembler, 'main.asm', '-odir', output, '-o', path.join(output, 'player.prg'), '-symbolfile', '-vicesymbols'], {cwd: output, stdio: 'inherit'});
  if (compiled.status !== 0) throw new Error('KickAssembler failed');
  const program = fs.readFileSync(path.join(output, 'player.prg'));
  const labels = Object.fromEntries([...fs.readFileSync(path.join(output, 'main.sym'), 'utf8').matchAll(/\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)/g)].map(match => [match[1], parseInt(match[2], 16)]));
  assert.equal(labels.animation_end - labels.animation, mainPool.bytes);
  if (packed.pooled) assert(labels.player_code_end <= middleStart, 'Code and pointers overlap the middle movie pool.');
  // Read the assembled image back, proving each pointer still addresses the exact
  // original encoded patch, including page counts and write order.
  const loadAddress = program.readUInt16LE(0);
  index.forEach((record, frame) => {
    const address = pointers.readUInt16LE(frame * 2);
    const bytes = program.subarray(2 + address - loadAddress, 2 + address - loadAddress + record.bytes);
    assert(bytes.equals(movie.subarray(record.offset, record.offset + record.bytes)), `Assembled sparse patch ${frame} changed.`);
  });
  const codeStateAndPointersBytes = labels.player_code_end - 0x1000;
  const codeStateBytes = codeStateAndPointersBytes - pointers.length - playback.bytecodeBytes;
  const meaningfulLoadedBytes = codeStateBytes + pointers.length + playback.bytecodeBytes + font.length + movie.length + 13;
  const result = {
    name: variant, variant, codec: literal ? 'global varint skip/length with raw literal characters' : 'four-page sparse offset/glyph pairs',
    hidden: false, sparse: !literal, dataset: study.sourceMetadata.name || 'spiral',
    settings: {...(study.sourceMetadata.settings || {}),
      ...(study.sourceMetadata.checks ? {checks: study.sourceMetadata.checks, checkerRows: study.sourceMetadata.checkerRows} : {}),
      fontGlyphs: font.length / 8},
    storedFrames: count, storedTransitions: index.length, firstSourcePose: 0,
    sourcePoseIndices: Array.from({length: count}, (_, frame) => frame),
    nominalFps: 25, nominalDurationSeconds: playback.nominalSeconds, uniqueFrameSeconds: count / 25, fieldsPerImage: 2,
    totalDisplayedFrames: playback.totalDisplayedFrames,
    introSeconds: study.introSeconds, loop,
    playback: playbackMetadata,
    abi: literal ? 'Repeat skip LEB128, literalLength LEB128, literal bytes until screen position 1000. Values 0..1000 use at most two bytes.' : 'Four sequential pages: count8, changes[offset8,glyph8...].',
    finiteClip: !playback.repeatsForever, closingPatchIncluded: Boolean(loop),
    introPayloadBytes: study.formats[codec].introPayloadBytes,
    loopPayloadBytes: study.formats[codec].loopPayloadBytes,
    closingPatchBytes: study.formats[codec].closingPatchBytes,
    dataArenaBytes: packed.capacity, payloadBytes: movie.length, unusedArenaBytes: packed.capacity - movie.length,
    ...(packed.pooled ? {
      pooledPayload: true,
      dataPools: packed.pools.map(({name, start, end, bytes, frames, file}) => ({name, start, end, usedEnd: start + bytes, capacityBytes: end - start, payloadBytes: bytes, frames, file})),
      sourceRegions: packed.pools.filter(pool => pool.bytes > 0).map(({start, bytes, file, data}) => ({start, end: start + bytes, file, sha256: sha(data)})),
      sourcePatches: index.map((record, frame) => ({frame, offset: record.offset, bytes: record.bytes, address: packed.pointers[frame]}))
    } : {}),
    fontBytes: font.length, seedScreenBytes: 0, pointerBytes: pointers.length,
    codeStateBytes, codeStateAndPointersBytes: codeStateBytes + pointers.length,
    codeRegionBytes: codeStateAndPointersBytes,
    playbackBytecodeBytes: playback.bytecodeBytes, workScreenBytes: 1024,
    colorRamBytes: 1024, zeroPageBytes: literal ? 9 : 5, basicBytes: 13, programBytes: program.length,
    meaningfulLoadedBytes, addressGapPaddingBytes: program.length - 2 - meaningfulLoadedBytes,
    animationAndFontBytes: pointers.length + font.length + movie.length,
    memoryAccounting: 'Meaningful loaded bytes excludes PRG address-gap padding, working screen RAM, color RAM, and zero page. Code state excludes the separately counted pointer table and playback bytecode. The first screen is cleared at startup and has no stored seed.',
    nativeFps: null, hashes: {program: sha(program), movie: sha(movie), font: sha(font), reference: sha(reference), playback: sha(playback.bytecode)},
    addresses: {code: 0x1000, codeEnd: labels.player_code_end, font: 0x2000,
      initialScreen: null, source: SOURCE, sourceEnd: labels.animation_end, front: 0x0400, hidden: null}
  };
  fs.writeFileSync(path.join(output, 'build.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result, null, 2));
  return result;
}

module.exports = {main, compilePlayback, packMovie};
if (require.main === module) main();
