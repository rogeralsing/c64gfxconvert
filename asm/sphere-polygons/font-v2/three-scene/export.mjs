import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {create, globals} from 'webgpu';

const here = path.dirname(fileURLToPath(import.meta.url));
const bayer = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

export function packRGBA(rgba, width, height, mode = 'threshold', threshold = 128) {
  assert.equal(rgba.length, width * height * 4);
  assert.equal(width % 8, 0, 'Packed rows require a width divisible by eight.');
  assert(['threshold', 'ordered'].includes(mode));
  assert(Number.isFinite(threshold) && threshold >= 0 && threshold <= 255);
  const packed = Buffer.alloc(width * height / 8);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const pixel = y * width + x, at = pixel * 4;
    const light = (54 * rgba[at] + 183 * rgba[at + 1] + 19 * rgba[at + 2]) / 256 * rgba[at + 3] / 255;
    const cutoff = mode === 'ordered' ? (bayer[(y & 3) * 4 + (x & 3)] + 0.5) * 255 / 16 : threshold;
    if (light >= cutoff) packed[pixel >> 3] |= 128 >> (x & 7);
  }
  return packed;
}

export async function main(argv = process.argv.slice(2)) {
  const options = {};
  for (let index = 0; index < argv.length; index++) {
    const at = argv[index].indexOf('=');
    const key = at < 0 ? argv[index] : argv[index].slice(0, at);
    const inline = at < 0 ? undefined : argv[index].slice(at + 1);
    if (key === '--write-rgba' || key === '--write-mask') { options[key] = true; continue; }
    assert(['--scene', '--output', '--quantize', '--threshold'].includes(key), `Unknown option: ${key}`);
    options[key] = inline ?? argv[++index];
    assert(options[key], `Missing value for ${key}`);
  }
  const source = path.resolve(options['--scene'] || path.join(here, 'demo.mjs'));
  const sceneModule = await import(pathToFileURL(source).href);
  const {config, createScene} = sceneModule;
  assert(config && typeof createScene === 'function', 'Scene module must export config and createScene(THREE).');
  const dependencyFiles = config.sourceDependencies ?? [];
  assert(Array.isArray(dependencyFiles), 'Scene sourceDependencies must be an array of file paths.');
  const sourceDependencies = dependencyFiles.map(file => {
    assert(typeof file === 'string' && file.length > 0, 'Scene dependency paths must be nonempty strings.');
    const dependency = path.resolve(path.dirname(source), file);
    return {source: dependency, sha256: sha(fs.readFileSync(dependency))};
  });
  const {width, height, fps, durationSeconds} = config;
  assert(Number.isInteger(width) && width > 0 && width % 8 === 0);
  assert(Number.isInteger(height) && height > 0);
  assert(Number.isFinite(fps) && fps > 0);
  assert(Number.isFinite(durationSeconds) && durationSeconds > 0);
  const frameCount = Math.round(fps * durationSeconds);
  assert(frameCount > 0 && Math.abs(frameCount - fps * durationSeconds) < 1e-8, 'Duration must span an integer number of frames.');
  if (config.approvedPrefixFrames !== undefined) assert(Number.isInteger(config.approvedPrefixFrames) &&
    config.approvedPrefixFrames >= 0 && config.approvedPrefixFrames <= frameCount, 'Approved prefix must fit inside the movie.');
  const name = config.name || path.basename(source, path.extname(source));
  const output = path.resolve(options['--output'] || path.join(here, '../build/three-scene', name));
  const mode = options['--quantize'] || 'threshold';
  assert(['threshold', 'ordered'].includes(mode));
  const threshold = Number(options['--threshold'] ?? 128);
  assert(Number.isFinite(threshold) && threshold >= 0 && threshold <= 255);

  // Dawn renders directly to GPU textures. No browser, canvas context or DOM
  // is used. The dimensions-only canvas satisfies Three's renderer interface.
  const previousGlobals = new Map(Object.keys(globals).map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  Object.assign(globalThis, globals);
  const previousNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  const previousSelf = Object.getOwnPropertyDescriptor(globalThis, 'self');
  const gpu = create(['backend=metal']);
  Object.defineProperty(globalThis, 'navigator', {value: {gpu, userAgent: 'Node.js Dawn Metal'}, configurable: true});
  // Three starts a metrics animation loop internally; frame rendering here is
  // driven exclusively by update(i/fps), with no asynchronous animation clock.
  Object.defineProperty(globalThis, 'self', {value: {requestAnimationFrame: () => 1, cancelAnimationFrame() {}}, configurable: true});
  let device, renderer, target, maskMaterial;
  try {
    const adapter = await gpu.requestAdapter();
    assert(adapter, 'No native Metal WebGPU adapter is available.');
    device = await adapter.requestDevice();
    const THREE = await import('three/webgpu');
    let canvasContextRequests = 0;
    const canvas = {width, height, style: {}, addEventListener() {}, removeEventListener() {},
      getContext() { canvasContextRequests++; throw new Error('Offscreen export must not request a canvas context.'); }};
    renderer = new THREE.WebGPURenderer({device, canvas, antialias: false});
    renderer.setSize(width, height, false);
    target = new THREE.RenderTarget(width, height, {type: THREE.UnsignedByteType,
      format: THREE.RGBAFormat, depthBuffer: true});
    target.texture.colorSpace = THREE.SRGBColorSpace;
    renderer.setRenderTarget(target);
    await renderer.init();
    const world = await createScene(THREE);
    assert(world.scene?.isScene && world.camera?.isCamera && typeof world.update === 'function');
    if (options['--write-mask']) maskMaterial = new THREE.MeshBasicMaterial({color: 0xffffff, toneMapped: false});
    const packedFrames = [], rawFrames = [], maskFrames = [], litPixels = [], frameMetadata = [];
    const started = performance.now();
    let firstFrameBlack = false;
    for (let frame = 0; frame < frameCount; frame++) {
      await world.update(frame / fps);
      const phase = world.scene.userData.pose?.phase;
      frameMetadata.push({index: frame, time: frame / fps,
        ...(typeof phase === 'string' ? {phase} : {})});
      renderer.render(world.scene, world.camera);
      const rgba = await renderer.readRenderTargetPixelsAsync(target, 0, 0, width, height);
      assert(rgba instanceof Uint8Array && rgba.length === width * height * 4);
      const packed = packRGBA(rgba, width, height, mode, threshold);
      if (frame === 0) firstFrameBlack = packed.every(value => value === 0);
      packedFrames.push(packed);
      if (options['--write-rgba']) rawFrames.push(Buffer.from(rgba));
      if (maskMaterial) {
        const previousMaterial = world.scene.overrideMaterial, previousBackground = world.scene.background;
        world.scene.overrideMaterial = maskMaterial;
        world.scene.background = new THREE.Color(0);
        try {
          renderer.render(world.scene, world.camera);
          const mask = await renderer.readRenderTargetPixelsAsync(target, 0, 0, width, height);
          maskFrames.push(packRGBA(mask, width, height, 'threshold', 128));
        } finally {
          world.scene.overrideMaterial = previousMaterial;
          world.scene.background = previousBackground;
        }
      }
      let lit = 0;
      for (const byte of packed) for (let bit = 0; bit < 8; bit++) lit += (byte >> bit) & 1;
      litPixels.push(lit);
    }
    assert.equal(canvasContextRequests, 0);
    const movie = Buffer.concat(packedFrames);
    const framesFile = 'bitmap.frames';
    const raw = options['--write-rgba'] ? Buffer.concat(rawFrames) : null;
    const mask = maskMaterial ? Buffer.concat(maskFrames) : null;
    const metadata = {name, title: config.title ?? name, description: config.description ?? '',
      width, height, fps, durationSeconds, frameCount,
      frameBytes: width * height / 8, framesFile, format: 'packed1bit',
      bitOrder: 'MSB-first', rowOrder: 'top-to-bottom',
      quantization: {mode, threshold: mode === 'threshold' ? threshold : null,
        luminance: 'Rec.709 integer approximation, composited against black',
        matrix: mode === 'ordered' ? '4x4 Bayer, fixed to screen coordinates' : null},
      renderer: {engine: 'Three.js WebGPURenderer', revision: THREE.REVISION,
        nativeWebGPU: 'webgpu 0.6.2 (Dawn)', backend: 'metal',
        canvasContextRequests, browserUsed: false, targetColorSpace: 'srgb', antialias: false},
      source: path.relative(here, source), sceneSource: source, sourceSha256: sha(fs.readFileSync(source)),
      ...(sourceDependencies.length ? {sourceDependencies} : {}),
      hashes: {frames: sha(movie), rgba: raw ? sha(raw) : null, objectMask: mask ? sha(mask) : null},
      rgbaFile: raw ? 'color.rgba' : null,
      objectMaskFile: mask ? 'object-mask.frames' : null,
      objectMaskScope: mask ? 'Diagnostic only: identical mesh poses rendered with an opaque white MeshBasicMaterial override on black.' : null,
      verification: {firstFrameBlack, deterministicSampleTimes: true, allFramesReadFromGPU: true},
      ...(config.approvedPrefixFrames !== undefined ? {approvedPrefixFrames: config.approvedPrefixFrames} : {}),
      phaseLabels: config.phaseLabels ?? null, frames: frameMetadata,
      litPixels, hostRenderSeconds: (performance.now() - started) / 1000};
    fs.mkdirSync(output, {recursive: true});
    fs.writeFileSync(path.join(output, framesFile), movie);
    if (raw) fs.writeFileSync(path.join(output, 'color.rgba'), raw);
    if (mask) fs.writeFileSync(path.join(output, 'object-mask.frames'), mask);
    fs.writeFileSync(path.join(output, 'metadata.json'), JSON.stringify(metadata, null, 2) + '\n');
    console.log(JSON.stringify({...metadata, litPixels: undefined, frames: undefined, output}, null, 2));
    return metadata;
  } finally {
    maskMaterial?.dispose();
    target?.dispose();
    renderer?.dispose();
    device?.destroy();
    if (previousNavigator) Object.defineProperty(globalThis, 'navigator', previousNavigator);
    else delete globalThis.navigator;
    if (previousSelf) Object.defineProperty(globalThis, 'self', previousSelf);
    else delete globalThis.self;
    for (const [key, descriptor] of previousGlobals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().then(() => process.exit(0), error => { console.error(error); process.exit(1); });
}
