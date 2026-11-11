'use strict';

// Consume the inspected bitmap film without changing its Three.js source.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');

function main(argv = process.argv.slice(2)) {
  const options = {};
  for (let index = 0; index < argv.length; index++) {
    const [key, inline] = argv[index].split('=');
    assert(['--input', '--output', '--glyph-limit', '--codec'].includes(key), 'Unknown option ' + key);
    options[key] = inline ?? argv[++index]; assert(options[key], 'Missing value for ' + key);
  }
  const here = __dirname, parent = path.dirname(here);
  const input = path.resolve(options['--input'] || path.join(parent, 'build/three-scene-dither/render'));
  const output = path.resolve(options['--output'] || path.join(parent, 'build/three-scene-gradient-c64'));
  const glyphLimit = Number(options['--glyph-limit'] || 256);
  const codec = options['--codec'] || 'sparse';
  assert(['sparse', 'literal'].includes(codec), 'Codec must be sparse or literal.');
  const variant = codec === 'literal' ? 'literal-front' : 'sparse-front';
  assert(Number.isInteger(glyphLimit) && glyphLimit >= 181 && glyphLimit <= 256);
  assert(fs.existsSync(path.join(input, 'metadata.json')), 'Run and inspect build-dither.cjs first.');
  const metadata = JSON.parse(fs.readFileSync(path.join(input, 'metadata.json')));
  const sceneSource = metadata.sceneSource || path.resolve(here, metadata.source || 'demo-dither.mjs');
  const font = path.join(output, 'dither-font'), optimized = path.join(output, 'optimized-font');
  const chars = path.join(output, 'characters');
  const storage = path.join(output, 'storage'), native = path.join(output, 'native'), preview = path.join(output, 'preview');
  const script = path.join(chars, 'playback.json');
  function run(executable, file, args) {
    const result = spawnSync('rtk', ['proxy', executable, path.join(parent, file), ...args], {encoding: 'utf8', maxBuffer: 4 * 1024 * 1024});
    if (result.error) throw result.error;
    if (result.status !== 0) throw new Error(file + '\n' + result.stdout + result.stderr);
  }
  const node = (file, args) => run(process.execPath, file, args);
  node('three-scene/dither-font-study.cjs', ['--input', input, '--output', font]);
  node('three-scene/optimize-dither-font.cjs', ['--input', input, '--font', path.join(font, 'font.bin'), '--output', optimized, '--limit', String(glyphLimit)]);
  node('bitmap-to-chars.cjs', ['--frames', path.join(input, 'bitmap.frames'), '--metadata', path.join(input, 'metadata.json'), '--output', chars, '--font', path.join(optimized, 'font.bin'), '--font-start-frame', '0']);
  const actual = fs.readFileSync(path.join(chars, 'reference.frames'));
  assert(actual.equals(fs.readFileSync(path.join(optimized, 'expected.reference.frames'))), 'Conversion differs from independent16-bit study.');
  node('measure-scene.cjs', ['--input=' + chars, '--output=' + storage, '--codec=' + codec]);
  node('build-scene-player.cjs', ['--input', storage, '--output', native, '--script', script, '--codec', codec]);
  node('build-scene-preview.cjs', ['--scene-dir', chars, '--output-dir', preview, '--summary-file', path.join(storage, 'study.json'), '--playback-script', script, '--scene-source', sceneSource, '--basename', 'gradient-c64']);
  run(process.env.PYTHON || 'python3', 'export-scene-media.py', ['--scene-dir', chars, '--output-dir', preview, '--playback-script', script, '--basename', 'gradient-c64']);
  const build = JSON.parse(fs.readFileSync(path.join(native, variant, 'build.json')));
  const result = {pass: true, stage: 'character film and native PRG', input, output, codec, variant,
    glyphs: build.fontBytes / 8, appendedGlyphs: build.fontBytes / 8 - 168,
    originalGlyphsUnchanged: true, approvedBitmapPrefixFrames: Math.min(metadata.approvedPrefixFrames ?? 125, metadata.frameCount), storedFrames: build.storedFrames,
    measuredPatternsAppended: build.fontBytes / 8 - 181,
    deltaBytes: build.payloadBytes, loadedBytes: build.meaningfulLoadedBytes,
    nativeTimingMeasured: false, program: path.join(native, variant, 'player.prg'),
    html: path.join(preview, 'gradient-c64.html'), gif: path.join(preview, 'gradient-c64.gif')};
  fs.writeFileSync(path.join(output, 'player-pipeline.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result, null, 2));
  return result;
}

module.exports = {main};
if (require.main === module) main();
