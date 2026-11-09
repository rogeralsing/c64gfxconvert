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
  const output = path.join(root, 'sparse-front');
  const study = JSON.parse(fs.readFileSync(path.join(input, 'study.json')));
  const reference = fs.readFileSync(path.join(input, 'reference.frames'));
  const font = fs.readFileSync(path.join(input, 'font.bin'));
  const movie = fs.readFileSync(path.join(input, 'sparse.bin'));
  const index = JSON.parse(fs.readFileSync(path.join(input, 'sparse-index.json')));
  const scriptPath = path.resolve(option('script', path.join(here, 'scenes/spiral.playback.json')));
  const count = study.frameCount;
  const loop = study.loop;
  assert(count > 1 && count < 256);
  assert.equal(study.fps, 25);
  assert.equal(reference.length, count * 1000);
  assert.equal(font.length, 1344);
  assert.equal(index.length, count - (loop ? 0 : 1));
  assert(reference.subarray(0, 1000).every(code => code === 0));
  assert(movie.length <= LIMIT - SOURCE, 'The complete clip must fit the data arena.');
  assert.equal(sha(reference), study.hashes.reference);
  assert.equal(sha(font), study.hashes.font);
  assert.equal(sha(movie), study.formats.sparse.sourceSha256);
  const playback = compilePlayback(JSON.parse(fs.readFileSync(scriptPath)), index, count, study.fps);
  fs.mkdirSync(output, {recursive: true});
  const pointers = Buffer.alloc(count * 2);
  index.forEach((record, frame) => {
    assert.equal(record.fromPose, frame);
    assert.equal(record.targetPose, frame === count - 1 ? loop.startFrame : frame + 1);
    pointers.writeUInt16LE(SOURCE + record.offset, frame * 2);
  });
  if (!loop) pointers.writeUInt16LE(SOURCE + movie.length, (count - 1) * 2);
  for (const [name, bytes] of Object.entries({'font.bin': font, 'movie.bin': movie, 'pointers.bin': pointers, 'reference.frames': reference, 'playback.bin': playback.bytecode})) {
    fs.writeFileSync(path.join(output, name), bytes);
  }
  const playbackMetadata = {...playback, source: scriptPath};
  delete playbackMetadata.bytecode;
  fs.writeFileSync(path.join(output, 'playback.json'), JSON.stringify(playback.commands, null, 2) + '\n');
  fs.writeFileSync(path.join(output, 'playback-metadata.json'), JSON.stringify(playbackMetadata, null, 2) + '\n');
  fs.writeFileSync(path.join(output, 'main.asm'), [
    `.const PREVIEW_FRAME_COUNT = ${count}`,
    `.const LOOP_START_FRAME = ${loop?.startFrame ?? -1}`,
    '.var fontData = LoadBinary("font.bin")',
    '.var movieData = LoadBinary("movie.bin")',
    '.var pointerData = LoadBinary("pointers.bin")',
    '.var scriptData = LoadBinary("playback.bin")',
    `.import source "${path.relative(output, path.join(here, 'scene-player.asm')).split(path.sep).join('/')}"`, ''
  ].join('\n'));
  const assembler = process.env.KICKASS || '/Users/rogerjohansson/.local/bin/kickass';
  const compiled = spawnSync('rtk', ['proxy', assembler, 'main.asm', '-odir', output, '-o', path.join(output, 'player.prg'), '-symbolfile', '-vicesymbols'], {cwd: output, stdio: 'inherit'});
  if (compiled.status !== 0) throw new Error('KickAssembler failed');
  const program = fs.readFileSync(path.join(output, 'player.prg'));
  const labels = Object.fromEntries([...fs.readFileSync(path.join(output, 'main.sym'), 'utf8').matchAll(/\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)/g)].map(match => [match[1], parseInt(match[2], 16)]));
  assert.equal(labels.animation_end - labels.animation, movie.length);
  const codeStateAndPointersBytes = labels.player_code_end - 0x1000;
  const codeStateBytes = codeStateAndPointersBytes - pointers.length - playback.bytecodeBytes;
  const meaningfulLoadedBytes = codeStateBytes + pointers.length + playback.bytecodeBytes + font.length + movie.length + 13;
  const result = {
    name: 'sparse-front', variant: 'sparse-front', codec: 'four-page sparse offset/glyph pairs',
    hidden: false, sparse: true, dataset: study.sourceMetadata.name || 'spiral',
    settings: {fontGlyphs: font.length / 8, ...(study.sourceMetadata.settings || {}),
      ...(study.sourceMetadata.checks ? {checks: study.sourceMetadata.checks, checkerRows: study.sourceMetadata.checkerRows} : {})},
    storedFrames: count, storedTransitions: index.length, firstSourcePose: 0,
    sourcePoseIndices: Array.from({length: count}, (_, frame) => frame),
    nominalFps: 25, nominalDurationSeconds: playback.nominalSeconds, uniqueFrameSeconds: count / 25, fieldsPerImage: 2,
    totalDisplayedFrames: playback.totalDisplayedFrames,
    introSeconds: study.introSeconds, loop,
    playback: playbackMetadata,
    abi: 'Four sequential pages: count8, changes[offset8,glyph8...].',
    finiteClip: !playback.repeatsForever, closingPatchIncluded: Boolean(loop),
    introPayloadBytes: study.formats.sparse.introPayloadBytes,
    loopPayloadBytes: study.formats.sparse.loopPayloadBytes,
    closingPatchBytes: study.formats.sparse.closingPatchBytes,
    dataArenaBytes: LIMIT - SOURCE, payloadBytes: movie.length, unusedArenaBytes: LIMIT - labels.animation_end,
    fontBytes: font.length, seedScreenBytes: 0, pointerBytes: pointers.length,
    codeStateBytes, codeStateAndPointersBytes: codeStateBytes + pointers.length,
    codeRegionBytes: codeStateAndPointersBytes,
    playbackBytecodeBytes: playback.bytecodeBytes, workScreenBytes: 1024,
    colorRamBytes: 1024, zeroPageBytes: 5, basicBytes: 13, programBytes: program.length,
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

module.exports = {main, compilePlayback};
if (require.main === module) main();
