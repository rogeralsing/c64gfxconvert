// Two independent raw-span movies, each blank + odd48 poses from a96-pose loop.
// The star's original film and zoom table are immutable inputs. The second
// object must have an inspected GPU bitmap before this starts font fitting.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {createRequire} from 'node:module';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.dirname(here);
const options = {};
for (let i = 2; i < process.argv.length; i++) {
  const key = process.argv[i];
  assert(['--ball-scene', '--second-scene', '--second-name', '--output'].includes(key), `Unknown option: ${key}`);
  options[key] = process.argv[++i];
  assert(options[key], `Missing value for ${key}`);
}
const build = path.resolve(options['--output'] || path.join(root, 'build/three-scene-star-ball-data'));
const secondScene = path.resolve(options['--second-scene'] || options['--ball-scene'] || path.join(here, 'demo-checker-ball.mjs'));
const secondName = options['--second-name'] || 'ball';
const {config: secondConfig} = await import(pathToFileURL(secondScene).href);
assert(['ball', 'cube'].includes(secondName), 'The second object must be ball or cube.');
const secondStudyName = path.basename(secondScene, path.extname(secondScene)).replace(/^demo-/, '').replace(/-loop$/, '') + '-zoom-study';
const require = createRequire(import.meta.url);
const {createMatcher, unpackFrame} = require('../bitmap-to-chars.cjs');
const read = file => fs.readFileSync(file);
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const FONT_SHA = '1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1';
const STAR_SHA = '5c245453149adfa4bafd433efa50b606a614ff3264eac46f0c5a0906bc9b698c';
const STAR_LUT_SHA = '37efc20a89731ff3a6b745bfb5e4083947649774b2fe63b56f0c2a4340b2dc21';
const poses = [0, ...Array.from({length: 48}, (_, i) => i * 2 + 1)];
const font = read(path.join(here, 'results/flagship-star-ten-buffer/font.bin'));
assert.equal(sha(font), FONT_SHA);
function write(file, bytes) {
  fs.mkdirSync(path.dirname(file), {recursive: true});
  if (fs.existsSync(file) && read(file).equals(bytes)) return;
  fs.writeFileSync(file + '.tmp', bytes); fs.renameSync(file + '.tmp', file);
}
function json(file, value) { write(file, Buffer.from(JSON.stringify(value, null, 2) + '\n')); }
function sample(reference) {
  assert.equal(reference.length, 97000);
  return Buffer.concat(poses.map(pose => reference.subarray(pose * 1000, (pose + 1) * 1000)));
}
function encode(name, reference, lut, provenance) {
  const directory = path.join(build, name), bytes = [], offsets = [];
  for (let frame = 0; frame < 49; frame++) {
    offsets.push(bytes.length);
    for (let row = 0; row < 25; row++) {
      const cells = reference.subarray(frame * 1000 + row * 40, frame * 1000 + (row + 1) * 40);
      let left = 0, end = 40;
      while (left < 40 && cells[left] === 0) left++;
      if (left === 40) bytes.push(0, 0);
      else {
        while (cells[end - 1] === 0) end--;
        bytes.push(left, end - left, ...cells.subarray(left, end));
      }
    }
  }
  const rows = Buffer.from(bytes), index = Buffer.alloc(98);
  offsets.forEach((offset, i) => index.writeUInt16LE(offset, i * 2));
  const decoded = Buffer.alloc(49000);
  for (let frame = 0; frame < 49; frame++) {
    let cursor = index.readUInt16LE(frame * 2);
    for (let row = 0; row < 25; row++) {
      const x = rows[cursor++], length = rows[cursor++];
      assert(x + length <= 40 && (length > 0 || x === 0));
      rows.copy(decoded, frame * 1000 + row * 40 + x, cursor, cursor + length);
      cursor += length;
    }
    assert.equal(cursor, frame === 48 ? rows.length : index.readUInt16LE((frame + 1) * 2));
  }
  assert(decoded.equals(reference), name + ' independent row decode differs');
  write(path.join(directory, 'rows.bin'), rows);
  write(path.join(directory, 'frame-offsets16.bin'), index);
  write(path.join(directory, 'reference.frames'), reference);
  write(path.join(directory, 'font.bin'), font);
  if (lut) {
    assert.equal(lut.length, 1024);
    write(path.join(directory, 'learned.lut'), lut);
  }
  const files = {rows: 'rows.bin', index: 'frame-offsets16.bin', reference: 'reference.frames', font: 'font.bin', zoomLut: 'learned.lut'};
  const hashes = {rows: sha(rows), index: sha(index), reference: sha(reference), font: sha(font), zoomLut: lut ? sha(lut) : null};
  const proof = {passed: true, object: name, storedFrames: 49, loopFrames: 48, sourcePoseIds: poses,
    nominalFps: 25, loopSecondsAtNominalFps: 48 / 25, rawRowBytes: rows.length,
    indexBytes: index.length, rawFilmBytes: rows.length + index.length, zoomLutBytes: lut ? lut.length : null,
    bitmapFontUnchanged: true, independentlyDecodedAll49Frames: true, internalZeroBytesPreserved: true,
    zoomLutPending: !lut, zoomLutLayout: 'interleaved charCode*4+q, TL TR BL BR', files, hashes, provenance};
  json(path.join(directory, 'proof.json'), proof);
  return proof;
}

const originalStar = read(path.join(here, 'results/flagship-star-ten-buffer/reference.frames'));
const starLut = read(path.join(here, 'results/char-zoom-study/learned.lut'));
assert.equal(sha(originalStar), STAR_SHA); assert.equal(sha(starLut), STAR_LUT_SHA);
const star = encode('star', sample(originalStar), starLut, {
  source: 'accepted original PAL flagship star, not either contrast experiment', originalReferenceSha256: STAR_SHA,
  animationSpeedComparedToOriginal: 2, lookupSource: 'char-zoom-study/learned.lut'});
assert.equal(star.rawRowBytes, 11459);
console.log(JSON.stringify({stage: 'star-ready', rawRows: star.rawRowBytes, filmWithIndex: star.rawFilmBytes}));

const render = path.join(build, 'render-1x');
const metadata = JSON.parse(read(path.join(render, 'metadata.json')));
assert.equal(metadata.sourceSha256, sha(read(secondScene)));
const bitmap = read(path.join(render, 'bitmap.frames')), mask = read(path.join(render, 'object-mask.frames'));
assert.equal(metadata.width, 160); assert.equal(metadata.height, 100); assert.equal(metadata.frameCount, 97);
assert.equal(sha(bitmap), metadata.hashes.frames); assert.equal(sha(mask), metadata.hashes.objectMask);
const preview = JSON.parse(read(path.join(build, 'bitmap-preview-proof.json')));
assert(preview.pass && preview.beforeFontConversion && (preview.pureBlackWhiteRgb || preview.grayscaleRgb));
assert.equal(preview.bitmapSha256, sha(bitmap));
const match = createMatcher(font, true), normal = [Buffer.alloc(1000)];
for (let pose = 1; pose <= 96; pose++) {
  const pixels = unpackFrame(bitmap.subarray(pose * 2000, (pose + 1) * 2000), 160, 100);
  const silhouette = unpackFrame(mask.subarray(pose * 2000, (pose + 1) * 2000), 160, 100);
  normal.push(match(pixels, silhouette).screen);
}
const secondFullReference = Buffer.concat(normal);
write(path.join(build, secondName + '-full-reference.frames'), secondFullReference);
const secondStudy = path.join(here, 'results', secondStudyName);
let secondLut = null;
if (fs.existsSync(path.join(secondStudy, 'proof.json'))) {
  const studyProof = JSON.parse(read(path.join(secondStudy, 'proof.json')));
  const study = JSON.parse(read(path.join(secondStudy, 'study.json')));
  assert(studyProof.passed);
  assert.equal(study.fontSha256, FONT_SHA);
  assert(read(path.join(secondStudy, 'source.chars')).equals(secondFullReference.subarray(1000)), 'Second-object study normal fit differs');
  secondLut = read(path.join(secondStudy, 'learned.lut'));
}
const second = encode(secondName, sample(secondFullReference), secondLut, {
  scene: path.relative(here, secondScene), sourceSha256: metadata.sourceSha256, bitmapSha256: sha(bitmap),
  ...(secondName === 'ball' ? {nativeDiameterY: 176, checkerColumns: 14, checkerRows: 7}
    : {cubeHalfSide: secondConfig.cubeHalfSide ?? 24, affineFaceGradients: !secondConfig.lighting,
      ...(secondConfig.lighting ? {lighting: secondConfig.lighting, fixedWorldPointLight: true} : {}),
      grayscaleRange: preview.rgbLevels}),
  bitmapPreviewInspectedBeforeFontConversion: true,
  ownZoomStudy: secondStudyName, trainingPoses: [1, 72], heldoutPoses: [73, 96]});
const manifest = {passed: true, dataComplete: !!secondLut, fontSha256: FONT_SHA, objects: [star, second],
  combinedRawRowBytes: star.rawRowBytes + second.rawRowBytes,
  combinedIndexBytes: star.indexBytes + second.indexBytes,
  combinedFilmBytes: star.rawFilmBytes + second.rawFilmBytes,
  contiguousMovieCapacity: 32768, fitsContiguousMovieRegion: star.rawRowBytes + second.rawRowBytes <= 32768};
json(path.join(build, 'manifest.json'), manifest);
console.log(JSON.stringify({stage: secondName + '-ready', rows: second.rawRowBytes, combinedRawRows: manifest.combinedRawRowBytes,
  fitsContiguous: manifest.fitsContiguousMovieRegion, ownZoomLutReady: !!secondLut, output: build}));
