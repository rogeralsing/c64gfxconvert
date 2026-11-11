import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {packRGBA} from './export.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const bit = (bytes, index) => (bytes[index >> 3] >> (7 - (index & 7))) & 1;

// An independent recursive Bayer rank, rather than the exporter's table.
function rank(x, y) {
  const pair = (a, b) => 2 * (a ^ b) + b;
  return 4 * pair(x & 1, y & 1) + pair((x >> 1) & 1, (y >> 1) & 1);
}

function verifyRamp() {
  const results = [];
  for (const [gray, expected] of [[0, 0], [64, 4], [128, 8], [192, 12], [255, 16]]) {
    const rgba = Buffer.alloc(8 * 4 * 4);
    for (let pixel = 0; pixel < 32; pixel++) {
      rgba.fill(gray, pixel * 4, pixel * 4 + 3); rgba[pixel * 4 + 3] = 255;
    }
    const packed = packRGBA(rgba, 8, 4, 'ordered');
    const coverage = [0, 0];
    for (let y = 0; y < 4; y++) for (let x = 0; x < 8; x++) {
      const actual = bit(packed, y * 8 + x);
      assert.equal(actual, Number(gray >= (rank(x, y) + 0.5) * 255 / 16));
      coverage[x >> 2] += actual;
    }
    assert.deepEqual(coverage, [expected, expected]);
    results.push({gray, expectedWhitePer4x4: expected, observedWhitePer4x4: coverage});
  }
  return results;
}

async function verifyFaceGradients(metadata, rgba, movie, mask) {
  const THREE = await import('three/webgpu');
  const factory = await import(pathToFileURL(metadata.sceneSource).href);
  const world = await factory.createScene(THREE);
  const frame = metadata.frameCount - 1, {width, height} = metadata;
  await world.update(frame / metadata.fps);
  world.scene.updateMatrixWorld(true); world.camera.updateMatrixWorld(true);
  assert(world.camera.isOrthographicCamera);
  const mesh = world.scene.getObjectByName('fixed-gray-cube');
  assert(mesh?.visible);
  const inverse = mesh.matrixWorld.clone().invert(), half = 24 / Math.sqrt(3);
  const bounds = new THREE.Box3(new THREE.Vector3(-half, -half, -half), new THREE.Vector3(half, half, half));
  const raycaster = new THREE.Raycaster(), point = new THREE.Vector3();
  const faces = {}, faceAt = Array(width * height).fill(null);
  const toLinear = value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  const toSRGB = value => value <= 0.0031308 ? value * 12.92 : 1.055 * value ** (1 / 2.4) - 0.055;
  // Independent, explicit face contract; no values are read from the scene's
  // gradient helper, material colors, or per-vertex color attributes.
  const contrast = 1.15;
  const ranges = [[24, 176], [48, 224], [112, 240]].map(endpoints => endpoints.map(value =>
    Math.max(0, Math.min(255, 128 + (value - 128) * contrast))));
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    raycaster.setFromCamera(new THREE.Vector2((x + 0.5) / width * 2 - 1, 1 - (y + 0.5) / height * 2), world.camera);
    const ray = raycaster.ray.clone().applyMatrix4(inverse);
    if (!ray.intersectBox(bounds, point)) continue;
    const coordinate = [point.x, point.y, point.z], magnitude = coordinate.map(Math.abs);
    const axis = magnitude.indexOf(Math.max(...magnitude));
    if (coordinate.some((value, index) => index !== axis && Math.abs(value) > half - 2)) continue;
    const sign = Math.sign(coordinate[axis]);
    const u = axis === 0 ? (1 - sign * point.z / half) / 2
      : axis === 1 ? (1 + point.x / half) / 2 : (1 + sign * point.x / half) / 2;
    const v = axis === 1 ? (1 + sign * point.z / half) / 2 : (1 - point.y / half) / 2;
    const q = (u + v) / 2, [minimum, maximum] = ranges[axis];
    const expected = 255 * toSRGB((1 - q) * toLinear(maximum / 255) + q * toLinear(minimum / 255));
    const pixel = y * width + x, globalPixel = frame * width * height + pixel;
    assert.equal(bit(mask, globalPixel), 1, 'Analytic interior face must be inside the actual GPU silhouette.');
    const gray = rgba[globalPixel * 4], key = (sign > 0 ? '+' : '-') + 'XYZ'[axis];
    const face = faces[key] ||= {range: [minimum, maximum], samples: [], blocks: []};
    face.samples.push({gray, expected, q, white: bit(movie, globalPixel)}); faceAt[pixel] = key;
  }
  for (let y = 0; y < height; y += 4) for (let x = 0; x < width; x += 4) {
    const key = faceAt[y * width + x]; if (!key) continue;
    let same = true, sum = 0, white = 0;
    for (let dy = 0; dy < 4; dy++) for (let dx = 0; dx < 4; dx++) {
      const pixel = (y + dy) * width + x + dx, globalPixel = frame * width * height + pixel;
      same &&= faceAt[pixel] === key; sum += rgba[globalPixel * 4]; white += bit(movie, globalPixel);
    }
    if (same) faces[key].blocks.push({meanGray: sum / 16, coverage: white / 16});
  }
  const mean = (values, property) => values.reduce((sum, value) => sum + value[property], 0) / values.length;
  const report = {};
  for (const [key, face] of Object.entries(faces)) {
    const samples = face.samples.sort((a, b) => a.q - b.q);
    assert(samples.length >= 30);
    const levels = [...new Set(samples.map(sample => sample.gray))].sort((a, b) => a - b);
    assert(levels.length >= 16, `${key} is not a gradient inside the face.`);
    const errors = samples.map(sample => Math.abs(sample.gray - sample.expected));
    const maximumError = Math.max(...errors);
    assert(maximumError <= 2, `${key} GPU gradient differs from the independent local-face oracle by${maximumError} sRGB bytes.`);
    const quarter = Math.floor(samples.length / 4), bright = samples.slice(0, quarter), dark = samples.slice(-quarter);
    const expectedContrast = mean(bright, 'expected') - mean(dark, 'expected');
    const actualContrast = mean(bright, 'gray') - mean(dark, 'gray');
    assert(expectedContrast > 16); assert(actualContrast >= expectedContrast - 4);
    const blocks = face.blocks.sort((a, b) => a.meanGray - b.meanGray);
    let coverage = null;
    if (blocks.length >= 4) {
      const count = Math.floor(blocks.length / 2), low = blocks.slice(0, count), high = blocks.slice(-count);
      coverage = {blocks: blocks.length, darkMeanGray: mean(low, 'meanGray'), brightMeanGray: mean(high, 'meanGray'),
        darkWhiteFraction: mean(low, 'coverage'), brightWhiteFraction: mean(high, 'coverage')};
      assert(coverage.brightWhiteFraction > coverage.darkWhiteFraction, `${key} Bayer cell density does not increase with tone.`);
    }
    report[key] = {sampleCount: samples.length, distinctLevels: levels.length, minimumGray: levels[0], maximumGray: levels.at(-1),
      expectedFaceSRGBEndpoints: face.range, maximumOracleErrorBytes: maximumError,
      meanOracleErrorBytes: errors.reduce((a, b) => a + b, 0) / errors.length,
      brightRegionMeanGray: mean(bright, 'gray'), darkRegionMeanGray: mean(dark, 'gray'),
      measuredContrastBytes: actualContrast, expectedContrastBytes: expectedContrast,
      brightRegionWhiteFraction: mean(bright, 'white'), darkRegionWhiteFraction: mean(dark, 'white'), aligned4x4Coverage: coverage};
  }
  assert(report['+X']?.aligned4x4Coverage, 'The marked late dark+X face must have independent gradient and Bayer-cell evidence.');
  assert.equal(Object.keys(report).length, 3);
  return {frame, time: frame / metadata.fps, edgeExclusionLocalUnits: 2, contrastAroundSRGB128: contrast,
    method: 'Orthographic ray, inverse actual cube matrix, analytic cube planes, independent face-local UV and standard sRGB transfer functions.',
    faces: report};
}

export async function main(argv = process.argv.slice(2)) {
  const options = {};
  for (let index = 0; index < argv.length; index++) {
    const separator = argv[index].indexOf('=');
    const key = separator < 0 ? argv[index] : argv[index].slice(0, separator);
    assert(['--input', '--output', '--baseline'].includes(key), `Unknown option ${key}`);
    options[key] = separator < 0 ? argv[++index] : argv[index].slice(separator + 1);
    assert(options[key], `Missing value for ${key}`);
  }
  assert(options['--input'] && options['--output'], 'Use --input RAW_EXPORT --output REPORT.json [--baseline APPROVED.frames].');
  const input = path.resolve(options['--input']), output = path.resolve(options['--output']);
  const metadataPath = path.join(input, 'metadata.json');
  const metadata = JSON.parse(fs.readFileSync(metadataPath));
  const approved = JSON.parse(fs.readFileSync(path.join(here, 'results/bitmap-calibration.json')));
  const {width, height, frameCount, fps} = metadata, pixelsPerFrame = width * height;
  assert.equal(width, 160); assert.equal(height, 100);
  assert.equal(frameCount, 200); assert.equal(fps, 25);
  assert.equal(metadata.bitOrder, 'MSB-first');
  assert.equal(metadata.rowOrder, 'top-to-bottom');
  assert.equal(metadata.quantization.mode, 'ordered');
  assert.equal(metadata.renderer.browserUsed, false);
  assert.equal(metadata.renderer.canvasContextRequests, 0);
  assert.equal(approved.frameCount, 125);
  assert.equal(approved.bitmapSha256, '81228daa4fe1645aa544af09c82094b883afc99d6920faa5627fe2d26839c5e0');
  const moviePath = path.resolve(input, metadata.framesFile);
  const rgbaPath = path.resolve(input, metadata.rgbaFile);
  const maskPath = path.resolve(input, metadata.objectMaskFile);
  const movie = fs.readFileSync(moviePath), rgba = fs.readFileSync(rgbaPath), mask = fs.readFileSync(maskPath);
  assert.equal(movie.length, pixelsPerFrame / 8 * frameCount);
  assert.equal(mask.length, movie.length); assert.equal(rgba.length, pixelsPerFrame * 4 * frameCount);
  assert.equal(sha(movie), metadata.hashes.frames); assert.equal(sha(rgba), metadata.hashes.rgba);
  assert.equal(sha(mask), metadata.hashes.objectMask);
  assert.equal(sha(fs.readFileSync(metadata.sceneSource)), metadata.sourceSha256);
  const prefixBytes = approved.frameCount * pixelsPerFrame / 8;
  const prefix = movie.subarray(0, prefixBytes);
  assert.equal(sha(prefix), approved.bitmapSha256, 'Ordered export changed the approved initial checker film.');
  if (options['--baseline']) assert(prefix.equals(fs.readFileSync(path.resolve(options['--baseline']))));
  const ramp = verifyRamp();
  let nonGrayscalePixels = 0, nonOpaquePixels = 0, prefixIntermediatePixels = 0;
  let tailIntermediatePixels = 0, wrongBits = 0, whiteOutsideMask = 0, firstGrayFrame = null;
  const tailLevels = new Uint32Array(256), afterFadeLevels = new Uint32Array(256), phaseHistograms = {};
  for (let frame = 0; frame < frameCount; frame++) {
    const phase = metadata.frames?.[frame]?.phase || 'bitmap';
    const histogram = phaseHistograms[phase] ||= new Uint32Array(256);
    for (let pixel = 0; pixel < pixelsPerFrame; pixel++) {
      const index = frame * pixelsPerFrame + pixel, at = index * 4;
      const gray = rgba[at], alpha = rgba[at + 3], x = pixel % width, y = Math.floor(pixel / width);
      nonGrayscalePixels += Number(gray !== rgba[at + 1] || gray !== rgba[at + 2]);
      nonOpaquePixels += Number(alpha !== 255); histogram[gray]++;
      const intermediate = gray !== 0 && gray !== 255;
      if (frame < approved.frameCount) prefixIntermediatePixels += Number(intermediate);
      else {
        tailLevels[gray]++;
        if (frame >= 6 * fps) afterFadeLevels[gray]++;
        tailIntermediatePixels += Number(intermediate);
        if (intermediate && firstGrayFrame === null) firstGrayFrame = frame;
      }
      const actual = bit(movie, index);
      const expected = Number(gray * alpha / 255 >= (rank(x, y) + 0.5) * 255 / 16);
      wrongBits += Number(actual !== expected);
      whiteOutsideMask += Number(actual && !bit(mask, index));
    }
  }
  assert.equal(nonGrayscalePixels, 0); assert.equal(nonOpaquePixels, 0);
  assert.equal(prefixIntermediatePixels, 0, 'Gray was introduced before the end of the approved checker film.');
  assert(tailIntermediatePixels > 0); assert(firstGrayFrame >= 125);
  assert.equal(wrongBits, 0, 'Packed pixels differ from independently computed screen-anchored Bayer ranks.');
  assert.equal(whiteOutsideMask, 0);
  const gradients = await verifyFaceGradients(metadata, rgba, movie, mask);
  const firstFrameBlack = movie.subarray(0, pixelsPerFrame / 8).every(value => value === 0);
  assert(firstFrameBlack);
  const report = {pass: true, stage: 'Three.js to dithered1-bit bitmap only', characterConversionRun: false, prefixPreserved: true,
    width, height, fps, frameCount, durationSeconds: frameCount / fps,
    sourceSha256: metadata.sourceSha256, bitmapSha256: sha(movie), rgbaSha256: sha(rgba), objectMaskSha256: sha(mask),
    selectedInputs: {frames: moviePath, metadata: metadataPath, rgba: rgbaPath, objectMask: maskPath},
    quantization: {mode: 'ordered', pattern: '4x4 Bayer', screenAnchored: true, gammaSpace: 'sRGB readback'},
    ramp, approvedPrefix: {frames: approved.frameCount, durationSeconds: approved.frameCount / fps,
      bitmapSha256: sha(prefix), expectedSha256: approved.bitmapSha256, unchanged: true, intermediatePixels: prefixIntermediatePixels},
    tail: {firstGrayFrame, firstGraySeconds: firstGrayFrame / fps, intermediatePixels: tailIntermediatePixels,
      afterFadeLevels: Array.from(afterFadeLevels).flatMap((count, level) => count ? [{level, pixels: count}] : []),
      gradients, levels: Array.from(tailLevels)},
    phases: Object.fromEntries(Object.entries(phaseHistograms).map(([phase, histogram]) => [phase,
      {levels: Array.from(histogram).flatMap((count, level) => count ? [{level, pixels: count}] : [])}])),
    verification: {firstFrameBlack, actualGpuReadback: metadata.verification.allFramesReadFromGPU,
      pixelsCompared: pixelsPerFrame * frameCount, wrongBits, whiteOutsideMask,
      nonGrayscalePixels, nonOpaquePixels, binaryPrefixPreserved: true, noCharacterConversion: true}};
  fs.mkdirSync(path.dirname(output), {recursive: true});
  fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({...report, phases: undefined, tail: {...report.tail, levels: undefined, afterFadeLevels: undefined}}, null, 2));
  return report;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch(error => {console.error(error); process.exitCode = 1;});
}
