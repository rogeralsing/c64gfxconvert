'use strict';

// Inspect the actual GPU bitmap before fitting its character palette.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {spawnSync} = require('node:child_process');

const here = __dirname;
const options = {};
for (let index = 2; index < process.argv.length; index++) {
  const key = process.argv[index];
  if (key === '--characters') { options.characters = true; continue; }
  if (key === '--codec') {
    options.codec = process.argv[++index];
    assert(['literal', 'sparse'].includes(options.codec), 'Codec must be literal or sparse.');
    continue;
  }
  assert.equal(key, '--output', 'Use [--output DIRECTORY] [--characters] [--codec literal|sparse].');
  options.output = process.argv[++index];
  assert(options.output, 'Missing output directory.');
}
const output = path.resolve(options.output || path.join(here, '../build/three-scene-rubik'));
const codec = options.codec || 'literal';
const source = path.join(here, 'demo-rubik.mjs');
const raw = path.join(output, 'render');
const verificationFile = path.join(output, 'verification.json');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
function run(executable, file, args) {
  const result = spawnSync('rtk', ['proxy', executable, path.join(here, file), ...args],
    {encoding: 'utf8', maxBuffer: 4 * 1024 * 1024});
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(file + '\n' + result.stdout + result.stderr);
}
let result;
if (!options.characters) {
  run(process.execPath, 'export.mjs', ['--scene', source, '--output', raw,
    '--quantize', 'ordered', '--write-rgba', '--write-mask']);
  run(process.execPath, 'verify-rubik.mjs', ['--input', raw, '--output', verificationFile]);
  run(process.env.PYTHON || 'python3', 'export-bitmap-media.py',
    ['--input', raw, '--output', path.join(output, 'preview')]);
  result = {pass: true, stage: 'bitmap-only', characterConversionRun: false,
    verification: verificationFile, gif: path.join(output, 'preview/bitmap.gif')};
} else {
  assert(fs.existsSync(verificationFile), 'Build and inspect the bitmap first.');
  const verification = JSON.parse(fs.readFileSync(verificationFile));
  const metadata = JSON.parse(fs.readFileSync(path.join(raw, 'metadata.json')));
  assert.equal(verification.pass, true, 'The bitmap must pass its independent verification.');
  assert.equal(metadata.sourceSha256, sha(fs.readFileSync(source)), 'Scene changed; rebuild the bitmap first.');
  for (const [file, hash] of [[metadata.framesFile, metadata.hashes.frames],
    [metadata.rgbaFile, metadata.hashes.rgba], [metadata.objectMaskFile, metadata.hashes.objectMask]]) {
    assert(file && hash);
    assert.equal(sha(fs.readFileSync(path.resolve(raw, file))), hash, 'Bitmap export changed; rebuild it first.');
  }
  run(process.execPath, 'verify-rubik.mjs', ['--input', raw, '--output', verificationFile]);
  const c64 = path.join(output, 'c64');
  run(process.execPath, 'build-dither-player.cjs', ['--input', raw, '--output', c64, '--codec', codec]);
  result = {...JSON.parse(fs.readFileSync(path.join(c64, 'player-pipeline.json'))),
    stage: 'character film and native PRG', characterConversionRun: true,
    bitmapVerification: verificationFile};
}
fs.writeFileSync(path.join(output, 'pipeline.json'), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify(result, null, 2));
