'use strict';

// One offline path from a Three.js scene to the existing character player.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');

function main(argv = process.argv.slice(2)) {
  const options = {};
  for (let index = 0; index < argv.length; index++) {
    const [key, inline] = argv[index].split('=');
    if (key === '--characters') {options[key] = true; continue;}
    assert(['--scene', '--output'].includes(key), 'Unknown option ' + key);
    options[key] = inline ?? argv[++index];
    assert(options[key], 'Missing value for ' + key);
  }
  const here = __dirname, parent = path.dirname(here);
  const output = path.resolve(options['--output'] || path.join(parent, 'build/three-scene-calibrated'));
  const source = path.resolve(options['--scene'] || path.join(here, 'demo.mjs'));
  const raw = path.join(output, 'render'), calibrated = path.join(output, 'calibration');
  const chars = path.join(output, 'characters');
  const storage = path.join(output, 'storage'), native = path.join(output, 'native');
  const preview = path.join(output, 'preview');
  function run(executable, file, args = []) {
    const result = spawnSync('rtk', ['proxy', executable, file, ...args], {encoding: 'utf8', maxBuffer: 4 * 1024 * 1024});
    if (result.error) throw result.error;
    if (result.status !== 0) throw new Error(path.basename(file) + '\n' + result.stdout + result.stderr);
  }
  const node = (file, args) => run(process.execPath, path.join(parent, file), args);
  node('three-scene/export.mjs', ['--scene', source, '--output', raw, '--quantize', 'threshold', '--write-rgba', '--write-mask']);
  node('three-scene/calibrate.mjs', ['--input', raw, '--output', calibrated]);
  const calibration = JSON.parse(fs.readFileSync(path.join(calibrated, 'calibration.json')));
  const bitmap = JSON.parse(fs.readFileSync(path.join(raw, 'metadata.json')));
  if (!options['--characters']) {
    const result = {pass: true, stage: 'bitmap-only', sceneSource: source, output,
      frameCount: bitmap.frameCount, fps: bitmap.fps,
      calibration: path.join(calibrated, 'calibration.json'),
      selectedThreshold: calibration.selectedThreshold,
      bitmap: path.join(calibrated, 'bitmap.frames'),
      metadata: path.join(calibrated, 'metadata.json'),
      characterConversionRun: false};
    fs.writeFileSync(path.join(output, 'pipeline.json'), JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result, null, 2));
    return result;
  }
  assert.equal(bitmap.fps, 25, 'The current native player uses25fps.');
  assert(bitmap.frameCount > 1 && bitmap.frameCount < 256, 'The current native player supports2..255 unique frames.');
  node('bitmap-to-chars.cjs', ['--frames', path.join(calibrated, 'bitmap.frames'), '--metadata', path.join(calibrated, 'metadata.json'), '--output', chars]);
  const script = path.join(chars, 'playback.json');
  node('measure-scene.cjs', ['--input=' + chars, '--output=' + storage]);
  node('build-scene-player.cjs', ['--input', storage, '--output', native, '--script', script]);
  node('build-scene-preview.cjs', ['--scene-dir', chars, '--output-dir', preview, '--summary-file', path.join(storage, 'study.json'), '--playback-script', script, '--scene-source', source, '--basename', 'three-scene']);
  run(process.env.PYTHON || 'python3', path.join(parent, 'export-scene-media.py'), ['--scene-dir', chars, '--output-dir', preview, '--playback-script', script, '--basename', 'three-scene']);
  const conversion = JSON.parse(fs.readFileSync(path.join(chars, 'metadata.json')));
  const build = JSON.parse(fs.readFileSync(path.join(native, 'sparse-front/build.json')));
  const result = {pass: true, sceneSource: source, output, renderer: bitmap.renderer,
    frameCount: bitmap.frameCount, fps: bitmap.fps, durationSeconds: bitmap.frameCount / bitmap.fps,
    packedBitmapBytes: fs.statSync(path.join(calibrated, 'bitmap.frames')).size,
    calibration: {report: path.join(calibrated, 'calibration.json'), selectedThreshold: calibration.selectedThreshold},
    glyphs: conversion.fontGlyphs, error: conversion.errorSummary,
    deltaBytes: build.payloadBytes, loadedBytesWithFontAndPlayer: build.meaningfulLoadedBytes,
    workingScreenBytes: build.workScreenBytes, nativeTimingMeasured: false,
    native: path.join(native, 'sparse-front/player.prg'),
    html: path.join(preview, 'three-scene.html'), gif: path.join(preview, 'three-scene.gif')};
  fs.writeFileSync(path.join(output, 'pipeline.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result, null, 2));
  return result;
}

module.exports = {main};
if (require.main === module) main();
