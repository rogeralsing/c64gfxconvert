import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
import {packRGBA} from './export.mjs';

const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const countBits = bytes => bytes.reduce((sum, byte) => {
  for (let bit = 0; bit < 8; bit++) sum += (byte >> bit) & 1;
  return sum;
}, 0);

// This stage deliberately imports no character matcher or font conversion.
export async function main(argv = process.argv.slice(2)) {
  const options = {};
  for (let i = 0; i < argv.length; i++) {
    const split = argv[i].indexOf('='), key = split < 0 ? argv[i] : argv[i].slice(0, split);
    if (key === '--bitmap-only') continue;
    assert(['--input', '--output'].includes(key), `Unknown option ${key}`);
    options[key] = split < 0 ? argv[++i] : argv[i].slice(split + 1);
    assert(options[key], `Missing value for ${key}`);
  }
  assert(options['--input'] && options['--output'], 'Use --input RAW_EXPORT --output CALIBRATION.');
  const input = path.resolve(options['--input']), output = path.resolve(options['--output']);
  const metadata = JSON.parse(fs.readFileSync(path.join(input, 'metadata.json')));
  const {width, height, frameCount, fps} = metadata, frameBytes = width * height / 8;
  const rgbaPath = path.resolve(input, metadata.rgbaFile || 'color.rgba');
  const maskPath = path.resolve(input, metadata.objectMaskFile || 'object-mask.frames');
  const rgba = fs.readFileSync(rgbaPath), mask = fs.readFileSync(maskPath);
  assert.equal(rgba.length, width * height * frameCount * 4);
  assert.equal(mask.length, frameBytes * frameCount);
  assert.equal(sha(rgba), metadata.hashes.rgba);
  assert.equal(sha(mask), metadata.hashes.objectMask);
  assert.equal(sha(fs.readFileSync(metadata.sceneSource)), metadata.sourceSha256, 'The exported scene source changed.');

  // Inspect the actual scene texture, independently of its rendered pixels.
  const THREE = await import('three/webgpu');
  const module = await import(pathToFileURL(metadata.sceneSource).href);
  const world = await module.createScene(THREE);
  const textures = [];
  world.scene.traverse(object => {
    if (!object.isMesh) return;
    for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
      assert(material.isMeshBasicMaterial, 'The certified baseline must use unlit MeshBasicMaterial.');
      const texture = material.map;
      if (!texture || textures.includes(texture)) continue;
      assert.equal(texture.image.width, 14); assert.equal(texture.image.height, 7);
      assert.equal(texture.magFilter, THREE.NearestFilter); assert.equal(texture.minFilter, THREE.NearestFilter);
      assert.equal(texture.generateMipmaps, false);
      const data = texture.image.data, origin = Number(data[0] === 255);
      assert.equal(data.length, 14 * 7 * 4);
      for (let y = 0; y < 7; y++) for (let x = 0; x < 14; x++) {
        const at = (y * 14 + x) * 4, value = (origin ^ ((x + y) & 1)) * 255;
        assert.deepEqual(Array.from(data.subarray(at, at + 4)), [value, value, value, 255]);
      }
      textures.push(texture);
    }
  });
  assert(textures.length > 0, 'The baseline must contain the14x7 checker texture.');
  const phases = {}, histogram = new Uint32Array(256);
  let nonBinaryPixels = 0, translucentPixels = 0;
  for (let frame = 0; frame < frameCount; frame++) {
    const phase = metadata.frames?.[frame]?.phase || 'bitmap';
    const stats = phases[phase] ||= {frames: 0, pixels: 0, nonBinaryPixels: 0, levels: new Set()};
    stats.frames++;
    for (let pixel = 0; pixel < width * height; pixel++) {
      const at = (frame * width * height + pixel) * 4;
      const value = rgba[at], binary = (value === 0 || value === 255) && value === rgba[at + 1] && value === rgba[at + 2];
      nonBinaryPixels += Number(!binary); stats.nonBinaryPixels += Number(!binary);
      translucentPixels += Number(rgba[at + 3] !== 255);
      stats.levels.add(value); stats.pixels++; histogram[value]++;
    }
  }
  assert.equal(nonBinaryPixels, 0, 'Actual GPU output contains colors or gray: this binary baseline is not certified.');
  assert.equal(translucentPixels, 0);
  const analyticSphere = {method: 'Orthographic ray/sphere front intersection, inverse Rz*Rx*Ry, original atan2/asin14x7 checker; rim and UV-boundary pixels excluded.',
    comparedPixels: 0, mismatches: 0, whitePixels: 0, blackPixels: 0, frames: []};
  for (const frame of [25, 50, 74].filter(frame => frame < frameCount)) {
    await world.update(frame / fps);
    const pose = world.scene.userData.pose;
    if (!pose || pose.morph !== 0) continue;
    const radius = pose.diameter / 4;
    const cy = Math.cos(pose.yaw), sy = Math.sin(pose.yaw), cp = Math.cos(pose.pitch), sp = Math.sin(pose.pitch);
    const cr = Math.cos(pose.roll), sr = Math.sin(pose.roll);
    let compared = 0;
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      const dx = (x + 0.5 - pose.centerX / 2) / radius, dy = (pose.centerY / 2 - y - 0.5) / radius;
      if (dx * dx + dy * dy >= 0.6) continue;
      const z = Math.sqrt(1 - dx * dx - dy * dy), rx = cr * dx + sr * dy, ry = -sr * dx + cr * dy;
      const ly = cp * ry + sp * z, z1 = -sp * ry + cp * z;
      const lx = cy * rx - sy * z1, lz = sy * rx + cy * z1;
      const column = (Math.atan2(lx, lz) + Math.PI) * 14 / (2 * Math.PI);
      const row = (Math.asin(Math.max(-1, Math.min(1, ly))) + Math.PI / 2) * 7 / Math.PI;
      const cf = column - Math.floor(column), rf = row - Math.floor(row);
      if (Math.min(cf, 1 - cf, rf, 1 - rf) < 0.15) continue;
      const expected = (Math.floor(column) ^ Math.floor(row)) & 1;
      const actual = Number(rgba[(frame * width * height + y * width + x) * 4] === 255);
      analyticSphere.mismatches += Number(actual !== expected);
      analyticSphere.whitePixels += expected; analyticSphere.blackPixels += 1 - expected;
      compared++; analyticSphere.comparedPixels++;
    }
    analyticSphere.frames.push({frame, comparedPixels: compared});
  }
  assert(analyticSphere.comparedPixels > 20);
  assert.equal(analyticSphere.mismatches, 0, 'Actual GPU checker phase differs from the original analytic ball.');

  const movies = new Map(), thresholds = [];
  for (let threshold = 0; threshold <= 255; threshold++) {
    const frames = [];
    for (let frame = 0; frame < frameCount; frame++) frames.push(packRGBA(
      rgba.subarray(frame * width * height * 4, (frame + 1) * width * height * 4), width, height, 'threshold', threshold));
    const movie = Buffer.concat(frames), hash = sha(movie);
    if (!movies.has(hash)) movies.set(hash, {movie, whitePixels: countBits(movie),
      firstFrameBlack: movie.subarray(0, frameBytes).every(byte => byte === 0)});
    const result = movies.get(hash);
    thresholds.push({threshold, bitmapSha256: hash, whitePixels: result.whitePixels, firstFrameBlack: result.firstFrameBlack});
  }
  const plateaus = [];
  for (const row of thresholds.filter(row => row.threshold > 0 && row.threshold < 255 && row.firstFrameBlack)) {
    const last = plateaus.at(-1);
    if (last && last.max + 1 === row.threshold && last.bitmapSha256 === row.bitmapSha256) last.max = row.threshold;
    else plateaus.push({min: row.threshold, max: row.threshold, bitmapSha256: row.bitmapSha256});
  }
  plateaus.sort((a, b) => (b.max - b.min) - (a.max - a.min) || a.min - b.min);
  assert(plateaus.length > 0);
  const plateau = plateaus[0], selectedThreshold = Math.round((plateau.min + plateau.max) / 2);
  const selected = movies.get(plateau.bitmapSha256).movie;
  assert.equal(plateau.min, 1); assert.equal(plateau.max, 254);
  let wrongBits = 0, sourceWhiteOutsideMask = 0;
  for (let pixel = 0; pixel < width * height * frameCount; pixel++) {
    const bit = (selected[pixel >> 3] >> (7 - (pixel & 7))) & 1;
    wrongBits += Number(bit !== Number(rgba[pixel * 4] === 255));
    sourceWhiteOutsideMask += Number(bit && !(mask[pixel >> 3] & (128 >> (pixel & 7))));
  }
  assert.equal(wrongBits, 0); assert.equal(sourceWhiteOutsideMask, 0);
  const selectedMetadata = {...metadata, quantization: {mode: 'threshold', threshold: selectedThreshold,
    selection: 'Rounded midpoint of the measured longest stable interior threshold plateau; no dithering.'},
    rgbaFile: rgbaPath, objectMaskFile: maskPath, framesFile: 'bitmap.frames',
    hashes: {...metadata.hashes, frames: sha(selected)}};
  fs.mkdirSync(output, {recursive: true});
  fs.writeFileSync(path.join(output, 'bitmap.frames'), selected);
  fs.writeFileSync(path.join(output, 'metadata.json'), JSON.stringify(selectedMetadata, null, 2) + '\n');
  const report = {pass: true, stage: 'Three.js to1-bit bitmap only; no character conversion',
    selectedThreshold, quantization: selectedMetadata.quantization, plateau, uniqueBitmapMovies: movies.size,
    width, height, fps, frameCount, durationSeconds: frameCount / fps,
    sourceSha256: metadata.sourceSha256, rgbaSha256: sha(rgba), bitmapSha256: sha(selected),
    checker: {columns: 14, rows: 7, whiteTexels: 49, blackTexels: 49, unlit: true, nearest: true, mipmaps: false},
    analyticSphere,
    grayscaleHistogram: Array.from(histogram), nonBinaryPixels, translucentPixels,
    phases: Object.fromEntries(Object.entries(phases).map(([phase, stats]) => [phase, {...stats, levels: [...stats.levels].sort((a, b) => a - b)}])),
    thresholds, verification: {firstFrameBlack: movies.get(plateau.bitmapSha256).firstFrameBlack,
      sourcePixelBitsCompared: width * height * frameCount, wrongBits, sourceWhiteOutsideMask,
      actualGpuReadback: metadata.verification.allFramesReadFromGPU, ditheringUsed: false, characterConversionRun: false}};
  fs.writeFileSync(path.join(output, 'calibration.json'), JSON.stringify(report, null, 2) + '\n');
  const python = `import json,sys\nfrom pathlib import Path\nfrom PIL import Image,ImageDraw,ImageSequence\np=Path(sys.argv[1]);m=json.loads((p/'metadata.json').read_text());w=m['width'];h=m['height'];n=m['frameCount'];b=(p/'bitmap.frames').read_bytes();rgba=Path(m['rgbaFile']).read_bytes();frames=[]\nfor i in range(n):\n im=Image.frombytes('1',(w,h),b[i*w*h//8:(i+1)*w*h//8]).convert('RGB');frames.append(im.resize((w*4,h*4),Image.Resampling.NEAREST))\nframes[0].save(p/'bitmap.gif',save_all=True,append_images=frames[1:],duration=round(1000/m['fps']),optimize=False,disposal=1)\nsamples=[min(n-1,i) for i in [1,25,50,74,100,124]];sheet=Image.new('RGB',(w*8,(h*4+24)*len(samples)),(18,20,18));draw=ImageDraw.Draw(sheet)\nfor row,i in enumerate(samples):\n top=row*(h*4+24);color=Image.frombytes('RGBA',(w,h),rgba[i*w*h*4:(i+1)*w*h*4]).convert('RGB').resize((w*4,h*4),Image.Resampling.NEAREST);sheet.paste(color,(0,top));sheet.paste(frames[i],(w*4,top));draw.text((8,top+h*4+5),f'Actual Three RGBA, frame {i} / {i/m["fps"]:.2f}s',(220,236,180));draw.text((w*4+8,top+h*4+5),f'1 bit, threshold {m["quantization"]["threshold"]}',(220,236,180))\nsheet.save(p/'bitmap-contact.png');gif=Image.open(p/'bitmap.gif');duration=sum(f.info.get('duration',0) for f in ImageSequence.Iterator(gif));assert duration==round(n/m['fps']*1000);(p/'media.json').write_text(json.dumps({'gifDurationMs':duration,'gifFrames':gif.n_frames,'characterConversionRun':False},indent=2))\n`;
  execFileSync(process.env.PYTHON || 'python3', ['-c', python, output], {stdio: 'inherit'});
  console.log(JSON.stringify({...report, thresholds: undefined, grayscaleHistogram: undefined, phases: undefined,
    output, gif: path.join(output, 'bitmap.gif'), contact: path.join(output, 'bitmap-contact.png')}, null, 2));
  return report;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().then(() => process.exit(0), error => {console.error(error); process.exit(1);});
}
