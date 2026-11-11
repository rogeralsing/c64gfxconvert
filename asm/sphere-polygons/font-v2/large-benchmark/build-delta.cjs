'use strict';

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const study = require('./delta-study.cjs');

const VARIANTS = {
  'sparse-front': {codec: 'sparse', sparse: true, hidden: false},
  'sparse-hidden': {codec: 'sparse', sparse: true, hidden: true},
  'packets-hidden': {codec: 'packets', sparse: false, hidden: true},
  'packets-front': {codec: 'packets', sparse: false, hidden: false}
};

function build(name, options = {}) {
  const variant = VARIANTS[name];
  if (!variant) throw new Error('Unknown delta variant ' + name);
  const sourceStudy = options.sourceStudy || study.OUT;
  const outputRoot = options.outputRoot || study.OUT;
  const report = JSON.parse(fs.readFileSync(path.join(sourceStudy, 'study.json')));
  const index = JSON.parse(fs.readFileSync(path.join(sourceStudy, `${variant.codec}-index.json`)));
  const encoded = fs.readFileSync(path.join(sourceStudy, `${variant.codec}.bin`));
  const {font, raw, frames} = study.corpus(options);
  assert.equal(study.sha(raw), report.sourceScreensSha256, 'Codec study and native reference corpus must match');
  const start = options.start || 0;
  const remaining = options.transitions || frames.length - start;
  const payloads = [];
  let payloadBytes = 0;
  for (let step = 0; step < remaining; step++) {
    const item = index[(start + step) % frames.length];
    if (payloadBytes + item.bytes > study.ARENA_END - study.ARENA_START) break;
    payloads.push(encoded.subarray(item.offset, item.offset + item.bytes));
    payloadBytes += item.bytes;
  }
  const count = payloads.length + 1;
  assert(count > 1 && count < 256);
  const movie = Buffer.concat(payloads);
  const pointers = Buffer.alloc(count * 2);
  let offset = 0;
  payloads.forEach((payload, i) => {
    pointers.writeUInt16LE(study.ARENA_START + offset, i * 2);
    offset += payload.length;
  });
  pointers.writeUInt16LE(study.ARENA_START + offset, (count - 1) * 2);
  const outputName = start ? `${name}-from-${String(start).padStart(3, '0')}` : name;
  const output = path.join(outputRoot, outputName);
  fs.mkdirSync(output, {recursive: true});
  fs.writeFileSync(path.join(output, 'font.bin'), font);
  const selected = Array.from({length: count}, (_, i) => frames[(start + i) % frames.length]);
  const reference = Buffer.concat(selected);
  fs.writeFileSync(path.join(output, 'initial.screen'), selected[0]);
  fs.writeFileSync(path.join(output, 'movie.bin'), movie);
  fs.writeFileSync(path.join(output, 'pointers.bin'), pointers);
  fs.writeFileSync(path.join(output, 'reference.frames'), reference);
  fs.writeFileSync(path.join(output, 'main.asm'), [
    `.const PREVIEW_FRAME_COUNT = ${count}`,
    `.const SPARSE_CODEC = ${variant.sparse}`,
    `.const HIDDEN_SCREEN = ${variant.hidden}`,
    '.var fontData = LoadBinary("font.bin")',
    '.var initialData = LoadBinary("initial.screen")',
    '.var movieData = LoadBinary("movie.bin")',
    '.var pointerData = LoadBinary("pointers.bin")',
    `.import source "${path.relative(output, path.join(__dirname, 'delta-player.asm')).split(path.sep).join('/')}"`, ''
  ].join('\n'));
  const assembler = process.env.KICKASS || '/Users/rogerjohansson/.local/bin/kickass';
  const compiled = spawnSync('rtk', ['proxy', assembler, 'main.asm', '-odir', output, '-o', path.join(output, 'player.prg'), '-symbolfile', '-vicesymbols'], {cwd: output, stdio: 'inherit'});
  if (compiled.status !== 0) throw new Error('KickAssembler failed for ' + name);
  const program = fs.readFileSync(path.join(output, 'player.prg'));
  const labels = Object.fromEntries([...fs.readFileSync(path.join(output, 'main.sym'), 'utf8').matchAll(/\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)/g)].map(match => [match[1], parseInt(match[2], 16)]));
  assert(labels.player_code_end <= 0x2000);
  assert.equal(labels.animation_end - labels.animation, movie.length);
  const result = {
    name: outputName, variant: name, ...variant, settings: report.settings, storedFrames: count, storedTransitions: count - 1,
    imageSource: report.imageSource,
    firstSourcePose: start, sourcePoseIndices: Array.from({length: count}, (_, i) => (start + i) % frames.length),
    angularRangeDegrees: (count - 1) * 0.9375,
    playback: 'Forward prefix, then stop at last exact pose. No closing discontinuity.',
    dataArenaBytes: study.ARENA_END - study.ARENA_START, payloadBytes: movie.length,
    unusedArenaBytes: study.ARENA_END - labels.animation_end,
    fontBytes: font.length, seedScreenBytes: 1000, pointerBytes: pointers.length,
    codeStateAndPointersBytes: labels.player_code_end - 0x1000,
    workScreenBytes: variant.hidden ? 2048 : 1024,
    zeroPageBytes: 10, basicBytes: 13, programBytes: program.length,
    meaningfulLoadedBytes: labels.player_code_end - 0x1000 + font.length + 1000 + movie.length + 13,
    nativeFps: null, nativeVerification: 'Run verify-delta.py; never infer native FPS from host decode.',
    hashes: {program: study.sha(program), movie: study.sha(movie), font: study.sha(font), reference: study.sha(reference)},
    addresses: {code: 0x1000, codeEnd: labels.player_code_end, font: 0x2000,
      initialScreen: 0x2800, source: labels.animation, sourceEnd: labels.animation_end,
      front: 0x0400, hidden: variant.hidden ? 0x0800 : null}
  };
  fs.writeFileSync(path.join(output, 'build.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result));
  return result;
}

function main() {
  if (!fs.existsSync(path.join(study.OUT, 'study.json'))) study.main();
  const names = process.argv.slice(2);
  const chunks = names.includes('--chunks');
  const geometry = names.includes('--geometry');
  const selected = names.filter(name => !['--chunks', '--geometry'].includes(name));
  const options = geometry ? {
    sourceStudy: path.join(study.OUT, 'geometry-storage'),
    outputRoot: path.join(study.OUT, 'geometry-native'),
    framesPath: path.join(__dirname, 'build/geometry/frames.screen')
  } : {};
  const results = [];
  for (const name of selected.length ? selected : Object.keys(VARIANTS)) {
    if (!chunks) results.push(build(name, options));
    else {
      let start = 0;
      while (start < 384) {
        const result = build(name, {...options, start, transitions: 384 - start});
        results.push(result);
        start += result.storedTransitions;
      }
    }
  }
  fs.writeFileSync(path.join(options.outputRoot || study.OUT, 'builds.json'), JSON.stringify(results, null, 2) + '\n');
}

module.exports = {VARIANTS, build, main};
if (require.main === module) main();
