'use strict';

// Reuse the unchanged sparse 6502 player for the feedback-filtered character
// screens. All loss decisions happen offline; native playback remains ordinary
// absolute character updates with the original immutable font.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {build} = require('./build-delta.cjs');

const here = __dirname;

function main(argv = process.argv.slice(2)) {
  const option = (name, fallback) => argv.find(value => value.startsWith(`--${name}=`))?.slice(name.length + 3) ?? fallback;
  const dataset = option('dataset', 'analytic');
  const threshold = Number(option('threshold', '2'));
  const protectSolids = argv.includes('--protect-solids');
  assert(['analytic', 'geometry'].includes(dataset));
  assert(Number.isInteger(threshold) && threshold >= 0 && threshold <= 64);
  const directory = `threshold-${threshold}${protectSolids ? '-protect-solids' : ''}`;
  const sourceStudy = path.join(here, 'build/lossy', dataset, directory);
  const outputRoot = path.join(here, 'build/lossy-native', dataset, directory);
  const framesPath = path.join(sourceStudy, 'reference.frames');
  assert.equal(fs.statSync(framesPath).size, 384000);
  fs.mkdirSync(outputRoot, {recursive: true});
  const variants = ['sparse-front', 'sparse-hidden'];
  const builds = variants.map(name => build(name, {sourceStudy, outputRoot, framesPath}));
  const manifest = {dataset, threshold, protectSolids, sourceStudy, framesPath, outputRoot, variants,
    nativeCode: 'Unchanged delta-player.asm through build-delta.cjs',
    reference: 'Offline feedback-filtered displayed character screens; no filtering runs on the C64.',
    playback: 'Each standalone program displays its largest RAM-sized forward prefix, then stops on the last pose.',
    builds};
  fs.writeFileSync(path.join(outputRoot, 'builds.json'), JSON.stringify(builds, null, 2) + '\n');
  fs.writeFileSync(path.join(outputRoot, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
  console.log(JSON.stringify({dataset, threshold, protectSolids, outputRoot, builds: builds.map(({name, storedFrames, payloadBytes, programBytes}) =>
    ({name, storedFrames, payloadBytes, programBytes}))}, null, 2));
  return manifest;
}

module.exports = {main};
if (require.main === module) main();
