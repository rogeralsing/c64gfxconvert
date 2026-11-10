'use strict';

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {SceneRenderer, WIDTH, HEIGHT, CAMERA} = require('./scene-renderer.cjs');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

function main(argv = process.argv.slice(2)) {
  const options = {};
  for (let index = 0; index < argv.length; index++) {
    const [key, inline] = argv[index].split('=');
    if (key === '--write-frames') { options[key] = true; continue; }
    assert(['--scene', '--output'].includes(key), 'Unknown option: ' + key);
    options[key] = inline === undefined ? argv[++index] : inline;
    assert(options[key], 'Missing value for ' + key);
  }
  const source = options['--scene'] ? path.resolve(options['--scene']) : path.join(__dirname, 'scenes/spiral.scene.cjs');
  const scene = require(source);
  assert.equal(scene.width, WIDTH); assert.equal(scene.height, HEIGHT);
  assert.equal(typeof scene.frame, 'function');
  assert(scene.fps > 0 && scene.durationSeconds > 0);
  const count = Math.round(scene.fps * scene.durationSeconds);
  assert(count > 0);
  const output = options['--output'] ? path.resolve(options['--output']) : path.join(__dirname, 'build/scenes', scene.name || 'scene');
  fs.mkdirSync(output, {recursive: true});
  const renderer = new SceneRenderer();
  const font = renderer.fontBytes;
  assert.equal(font.length, 1344);
  assert.equal(sha(font), '68ad34844c8a998f5270c31bc16962545f6c3232555fa03f9faec134c21c5b59');
  const frames = [], ideals = [], poses = [], statistics = [];
  const started = process.hrtime.bigint();
  for (let index = 0; index < count; index++) {
    const time = index / scene.fps;
    const pose = scene.frame(time);
    for (const key of ['centerX', 'centerY', 'diameter', 'yaw', 'pitch', 'roll']) assert(Number.isFinite(pose[key]), `Invalid ${key} at frame ${index}`);
    assert(pose.diameter >= 0);
    const stats = renderer.render(pose, scene.checks);
    const frame = Buffer.from(renderer.screen);
    assert(frame.every(code => code < renderer.font.count));
    frames.push(frame); ideals.push(Buffer.from(renderer.source));
    poses.push({index, frame: index, time, ...pose});
    statistics.push({index, time, ...stats});
    if (options['--write-frames']) {
      const directory = path.join(output, 'frames');
      fs.mkdirSync(directory, {recursive: true});
      fs.writeFileSync(path.join(directory, `${String(index).padStart(3, '0')}.screen`), frame);
    }
  }
  const raw = Buffer.concat(frames), ideal = Buffer.concat(ideals);
  const firstVisibleFrame = frames.findIndex(frame => frame.some(code => code !== 0));
  const loop = scene.loop ? {...scene.loop} : null;
  if (loop) {
    assert(Number.isInteger(loop.startFrame) && loop.startFrame >= 0, 'Loop startFrame must be a stored frame index.');
    assert(Number.isInteger(loop.frameCount) && loop.frameCount > 1, 'A loop requires at least two unique stored frames.');
    assert.equal(loop.startFrame + loop.frameCount, count, 'The loop must finish at the end of the unique timeline.');
    assert(Number.isFinite(loop.periodRadians) && loop.periodRadians > 0, 'Loop periodRadians must be positive.');
    if (scene.introSeconds !== undefined) assert(Math.abs(scene.introSeconds - loop.startFrame / scene.fps) < 1e-10);
    const first = poses[loop.startFrame];
    const endpointTime = count / scene.fps;
    const endpoint = scene.frame(endpointTime);
    for (const pose of [...poses.slice(loop.startFrame), endpoint]) {
      assert.equal(pose.visible, first.visible, 'Loop visibility must stay fixed.');
      for (const key of ['centerX', 'centerY', 'diameter', 'pitch', 'roll']) {
        assert.equal(pose[key], first[key], `The own-axis loop must keep ${key} fixed.`);
      }
      assert(Number.isFinite(pose.yaw));
    }
    for (let offset = 0; offset < loop.frameCount; offset++) {
      const expectedYaw = first.yaw + loop.periodRadians * offset / loop.frameCount;
      assert(Math.abs(poses[loop.startFrame + offset].yaw - expectedYaw) < 1e-10,
        'Stored loop samples must advance yaw evenly through the declared period.');
    }
    const endpointPeriods = (endpoint.yaw - first.yaw) / loop.periodRadians;
    assert(Math.abs(endpointPeriods - Math.round(endpointPeriods)) < 1e-10,
      'The endpoint yaw must complete its period or wrap to an equivalent phase.');
    // Check the scripted endpoint as well as an unwrapped mathematical turn.
    // This proves checker symmetry even when the scene canonicalizes its phase.
    for (const last of [endpoint, {...first, yaw: first.yaw + loop.periodRadians}]) {
      renderer.render(last, scene.checks);
      assert(Buffer.from(renderer.screen).equals(frames[loop.startFrame]),
        'The rendered loop endpoint must exactly equal its first stored character frame.');
      assert(Buffer.from(renderer.source).equals(ideals[loop.startFrame]),
        'The analytic checker pattern must repeat exactly at the loop endpoint.');
    }
  }
  if (scene.name === 'spiral') {
    assert(frames[0].every(code => code === 0), 'First frame must be empty.');
    assert(firstVisibleFrame > 0 && firstVisibleFrame <= 4, 'The first visible dot must appear promptly.');
    assert(frames.slice(firstVisibleFrame).every(frame => frame.some(code => code !== 0)),
      'The growing sphere must stay visible after its first dot.');
    const hold = poses.filter(pose => pose.time >= scene.growSeconds);
    assert(hold.length >= 25);
    for (const pose of hold) {
      assert.equal(pose.diameter, 96);
      assert.equal(pose.centerX, 210);
      assert.equal(pose.centerY, 100);
    }
    const tumble = poses.filter(pose => pose.phase === 'tumble' || pose.phase === 'hold');
    assert(tumble.length >= 20, 'The arrival must include visible multi-axis tumbling before settling.');
    for (const key of ['yaw', 'pitch', 'roll']) assert(Math.abs(tumble.at(-1)[key] - tumble[0][key]) > 0.1, `Tumbling must rotate around ${key}.`);
  }
  const sceneInfo = {name: scene.name || 'scene', fps: scene.fps, durationSeconds: scene.durationSeconds,
    frameCount: count, width: WIDTH, height: HEIGHT, checks: scene.checks, checkerRows: scene.checks / 2,
    growSeconds: scene.growSeconds ?? null, introSeconds: scene.introSeconds ?? (loop ? loop.startFrame / scene.fps : scene.durationSeconds),
    loop, frames: poses};
  const metadata = {
    pass: true, name: sceneInfo.name, fps: scene.fps, durationSeconds: scene.durationSeconds,
    frameCount: count, frameBytes: 1000, width: WIDTH, height: HEIGHT,
    fontGlyphs: renderer.font.count, fontBytes: font.length, emptyGlyph: 0, filledGlyph: renderer.font.filledGlyph,
    checks: scene.checks, checkerRows: scene.checks / 2, camera: CAMERA,
    sceneSource: path.relative(__dirname, source), firstVisibleFrame,
    introSeconds: sceneInfo.introSeconds, loop,
    timing: 'Frame i samples time i/fps. Each stored image displays for 1/fps seconds; there is no duplicated endpoint. ' +
      (loop ? `The closing delta changes frame ${count - 1} to frame ${loop.startFrame}, then repeats the ${loop.frameCount}-frame tail.` : 'There is no closing patch.'),
    rotation: 'Forward object transform Rz(roll) Rx(pitch) Ry(yaw). With pitch and roll fixed, changing yaw spins around the tilted object Y axis.',
    glyphSelection: 'Original fine256-glyph matching constrained to each moving sphere silhouette, then existing coarse168 remap. Both the fine glyph and its mapped2x2 glyph must lie inside the current silhouette. No new font fitting or partial C64 screen frames.',
    hashes: {font: sha(font), screens: sha(raw), ideal: sha(ideal), sceneSource: sha(fs.readFileSync(source))},
    verification: {firstFrameEmpty: frames[0].every(code => code === 0), everyCodeWithinFixedFont: true,
      allMappedGlyphsInsideMovingCircle: true, noClosingPatch: !loop, noDuplicatedEndpoint: true,
      loopEndpointMatchesStart: loop ? true : null, loopIdealEndpointMatchesStart: loop ? true : null,
      loopUnwrappedPeriodMatchesStart: loop ? true : null,
      continuousAfterFirstVisible: firstVisibleFrame >= 0 && frames.slice(firstVisibleFrame).every(frame => frame.some(code => code !== 0))},
    nativeTimingMeasured: false, hostSeconds: Number(process.hrtime.bigint() - started) / 1e9,
    statistics
  };
  fs.writeFileSync(path.join(output, 'font.bin'), font);
  fs.writeFileSync(path.join(output, 'reference.frames'), raw);
  fs.writeFileSync(path.join(output, 'initial.screen'), frames[0]);
  fs.writeFileSync(path.join(output, 'ideal.frames'), ideal);
  fs.writeFileSync(path.join(output, 'scene.json'), JSON.stringify(sceneInfo, null, 2) + '\n');
  fs.writeFileSync(path.join(output, 'metadata.json'), JSON.stringify(metadata, null, 2) + '\n');
  console.log(JSON.stringify({...metadata, statistics: undefined, output}, null, 2));
  return metadata;
}

module.exports = {main};
if (require.main === module) main();
