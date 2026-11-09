'use strict';

// Package the generated character screens and fixed font into one offline page.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');

const here = __dirname;
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const htmlText = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');

function main(argv = process.argv.slice(2)) {
  const options = {};
  for (let index = 0; index < argv.length; index++) {
    const [name, inline] = argv[index].split('=');
    assert(['--scene-dir', '--output-dir', '--summary-file', '--playback-script', '--scene-source', '--basename'].includes(name), 'Unknown option ' + name);
    options[name] = inline === undefined ? argv[++index] : inline;
    assert(options[name], 'Missing value for ' + name);
  }
  const input = path.resolve(options['--scene-dir'] || path.join(here, 'build/scenes/spiral'));
  const output = path.resolve(options['--output-dir'] || path.join(here, 'build/scenes/spiral'));
  const scene = JSON.parse(fs.readFileSync(path.join(input, 'scene.json')));
  const metadata = JSON.parse(fs.readFileSync(path.join(input, 'metadata.json')));
  const font = fs.readFileSync(path.join(input, 'font.bin'));
  const screens = fs.readFileSync(path.join(input, 'reference.frames'));
  assert.equal(scene.width, 320);
  assert.equal(scene.height, 200);
  assert.equal(scene.fps, 25);
  assert.equal(scene.frames.length, Math.round(scene.durationSeconds * scene.fps));
  if (scene.loop) {
    assert(Number.isInteger(scene.loop.startFrame) && scene.loop.startFrame > 0);
    assert(Number.isInteger(scene.loop.frameCount) && scene.loop.frameCount > 1);
    assert.equal(scene.loop.startFrame + scene.loop.frameCount, scene.frames.length);
  }
  assert.equal(screens.length, scene.frames.length * 1000);
  assert.equal(font.length, 1344);
  assert(screens.every(code => code < font.length / 8));
  assert(screens.subarray(0, 1000).every(code => code === 0), 'The first image must be empty');
  const scriptPath = path.resolve(options['--scene-source'] || metadata.sceneSource && path.resolve(here, metadata.sceneSource) || path.join(here, 'scenes/spiral.scene.cjs'));
  const playbackPath = path.resolve(options['--playback-script'] || path.join(here, 'scenes/spiral.playback.json'));
  const playbackSource = fs.readFileSync(playbackPath, 'utf8');
  const commands = JSON.parse(playbackSource);
  assert(Array.isArray(commands) && commands.length > 1, 'Playback must be a JSON command array');
  let totalDisplayedFrames = 0;
  commands.forEach((command, index) => {
    if (command.op === 'hold') {
      assert.equal(index, commands.length - 1, 'HOLD must be last');
    } else {
      assert.equal(command.op, 'play', 'Unknown playback operation');
      assert(Number.isInteger(command.startFrame) && command.startFrame >= 0);
      assert(Number.isInteger(command.frameCount) && command.frameCount > 0 && command.frameCount <= 255);
      assert(command.startFrame + command.frameCount <= scene.frames.length);
      assert(Number.isInteger(command.repeat) && command.repeat > 0 && command.repeat <= 65535);
      totalDisplayedFrames += command.frameCount * command.repeat;
    }
  });
  assert.equal(commands.at(-1).op, 'hold', 'Finite playback must end with HOLD');
  assert(totalDisplayedFrames > 0);
  const playback = {commands, totalDisplayedFrames, nominalSeconds: totalDisplayedFrames / scene.fps, scriptPath: playbackPath};
  const storage = options['--summary-file'] ? JSON.parse(fs.readFileSync(path.resolve(options['--summary-file']))) : null;
  const data = {scene, playback, metadata, storage, font: font.toString('base64'), screens: screens.toString('base64'),
    fontSha256: sha(font), screensSha256: sha(screens), scriptPath};
  const template = fs.readFileSync(path.join(here, 'scenes/preview-template.html'), 'utf8');
  const html = template.replace('/* SCENE_DATA */', 'const SCENE_DATA = ' + JSON.stringify(data).replaceAll('<', '\\u003c') + ';')
    .replace('<!-- SCENE_SOURCE -->', htmlText(fs.readFileSync(scriptPath, 'utf8')))
    .replace('<!-- SCENE_PATH -->', htmlText(scriptPath))
    .replace('<!-- PLAYBACK_SOURCE -->', htmlText(playbackSource))
    .replace('<!-- PLAYBACK_PATH -->', htmlText(playbackPath));
  fs.mkdirSync(output, {recursive: true});
  const basename = options['--basename'] || 'spiral-scene';
  assert(/^[a-zA-Z0-9_-]+$/.test(basename), 'Invalid preview basename');
  const destination = path.join(output, basename + '.html');
  fs.writeFileSync(destination, html);
  const manifest = {pass: true, html: destination, htmlBytes: Buffer.byteLength(html),
    frameCount: scene.frames.length, fps: scene.fps, uniqueDurationSeconds: scene.durationSeconds,
    durationSeconds: playback.nominalSeconds,
    fontBytes: font.length, fontGlyphs: font.length / 8, fontSha256: data.fontSha256,
    screensSha256: data.screensSha256, selfContained: true, loops: false,
    playbackScript: playbackPath, playbackCommands: commands, totalDisplayedFrames,
    nominalPlaybackSeconds: playback.nominalSeconds,
    loop: scene.loop || null, introSeconds: scene.introSeconds || null,
    scope: 'Host playback reconstructed exclusively from the generated character codes and fixed font. No native C64 FPS claim.'};
  fs.writeFileSync(path.join(output, 'scene-preview-build.json'), JSON.stringify(manifest, null, 2) + '\n');
  console.log(JSON.stringify(manifest, null, 2));
  return manifest;
}

module.exports = {main};
if (require.main === module) main();
