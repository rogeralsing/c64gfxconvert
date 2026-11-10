'use strict';

// Preserve the approved checker entrance, then inspect gray sides as bitmaps.
const path = require('node:path');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');

const args = process.argv.slice(2);
assert(args.length === 0 || args.length === 2 && args[0] === '--output', 'Use [--output DIRECTORY].');
const output = path.resolve(args[1] || path.join(__dirname, '../build/three-scene-dither'));
const raw = path.join(output, 'render'), preview = path.join(output, 'preview');
function run(executable, file, options) {
  const result = spawnSync('rtk', ['proxy', executable, path.join(__dirname, file), ...options], {encoding: 'utf8', maxBuffer: 4 * 1024 * 1024});
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(file + '\n' + result.stdout + result.stderr);
}
run(process.execPath, 'export.mjs', ['--scene', path.join(__dirname, 'demo-dither.mjs'), '--output', raw, '--quantize', 'ordered', '--write-rgba', '--write-mask']);
run(process.execPath, 'verify-dither.mjs', ['--input', raw, '--output', path.join(output, 'verification.json')]);
run(process.env.PYTHON || 'python3', 'export-bitmap-media.py', ['--input', raw, '--output', preview]);
const verification = JSON.parse(fs.readFileSync(path.join(output, 'verification.json')));
const result = {pass: true, stage: 'bitmap-only', output, characterConversionRun: false,
  verification: path.join(output, 'verification.json'), prefixPreserved: verification.prefixPreserved,
  gif: path.join(preview, 'bitmap.gif'), comparison: path.join(preview, 'comparison.gif')};
fs.writeFileSync(path.join(output, 'pipeline.json'), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify(result, null, 2));
