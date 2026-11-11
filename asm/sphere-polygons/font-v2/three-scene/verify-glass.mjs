import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {create, globals} from 'webgpu';
import {packRGBA} from './export.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const bit = (bytes, index) => (bytes[index >> 3] >> (7 - (index & 7))) & 1;
const rank = (x, y) => {
  const pair = (a, b) => 2 * (a ^ b) + b;
  return 4 * pair(x & 1, y & 1) + pair((x >> 1) & 1, (y >> 1) & 1);
};

function bounds(rgba, width, height) {
  const points = [];
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) if (rgba[(y * width + x) * 4]) points.push([x, y]);
  return points.length ? [Math.min(...points.map(p => p[0])), Math.min(...points.map(p => p[1])),
    Math.max(...points.map(p => p[0])) + 1, Math.max(...points.map(p => p[1])) + 1] : null;
}

function signal(full, hidden) {
  return Float64Array.from({length: full.length / 4}, (_, pixel) => Math.max(0, full[pixel * 4] - hidden[pixel * 4]));
}

function signalMetrics(values, width, height) {
  let mass = 0, mx = 0, my = 0, gradient = 0, supportPixels = 0;
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const at = y * width + x, value = values[at];
    mass += value;mx += value * x;my += value * y;
    supportPixels += Number(value >= 3);
    if (x) gradient += Math.abs(value - values[at - 1]);
    if (y) gradient += Math.abs(value - values[at - width]);
  }
  assert(mass > 0, 'The isolated ball signal disappeared');
  return {mass, centroid: [mx / mass, my / mass], supportPixels, normalizedGradient: gradient / mass};
}

function imageDifference(a, b, width, height) {
  let grayPixels = 0, absoluteGrayDifference = 0;
  for (let pixel = 0; pixel < width * height; pixel++) {
    const delta = Math.abs(a[pixel * 4] - b[pixel * 4]);
    grayPixels += Number(delta >= 3);absoluteGrayDifference += delta;
  }
  const ab = packRGBA(a, width, height, 'ordered'), bb = packRGBA(b, width, height, 'ordered');
  let binaryPixels = 0;
  for (let pixel = 0; pixel < width * height; pixel++) binaryPixels += Number(bit(ab, pixel) !== bit(bb, pixel));
  return {grayPixels, binaryPixels, absoluteGrayDifference};
}

function meshFacts(geometry) {
  const positions = geometry.getAttribute('position'), index = geometry.getIndex();
  const triangleVertices = index ? Array.from(index.array) : Array.from({length: positions.count}, (_, i) => i);
  assert.equal(triangleVertices.length % 3, 0);
  const points = Array.from({length: positions.count}, (_, i) => [positions.getX(i), positions.getY(i), positions.getZ(i)]);
  const key = point => point.map(value => Math.round(value * 1e5)).join(',');
  const edges = new Map(), edgeDirections = new Map(), normals = new Set();let signedVolume = 0;
  let nonSupportingTriangles = 0, maximumOutsideFaceDistance = 0;
  for (let at = 0; at < triangleVertices.length; at += 3) {
    const [a, b, c] = triangleVertices.slice(at, at + 3).map(i => points[i]);
    const u = b.map((value, axis) => value - a[axis]), v = c.map((value, axis) => value - a[axis]);
    const normal = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]];
    const length = Math.hypot(...normal);assert(length > 1e-8, 'Glass mesh has a degenerate triangle');
    normals.add(normal.map(value => Math.round(value / length * 1e5)).join(','));
    const outside = Math.max(...points.map(point => point.reduce((sum, value, axis) => sum +
      (value-a[axis])*normal[axis]/length, 0)));
    nonSupportingTriangles += Number(outside > 1e-4);
    maximumOutsideFaceDistance = Math.max(maximumOutsideFaceDistance, outside);
    signedVolume += (a[0]*(b[1]*c[2]-b[2]*c[1]) + a[1]*(b[2]*c[0]-b[0]*c[2]) + a[2]*(b[0]*c[1]-b[1]*c[0])) / 6;
    for (const [p, q] of [[a,b],[b,c],[c,a]]) {
      const edge = [key(p), key(q)].sort().join('|');edges.set(edge, (edges.get(edge) || 0) + 1);
      const direction = key(p) < key(q) ? 1 : -1;
      edgeDirections.set(edge, (edgeDirections.get(edge) || 0) + direction);
    }
  }
  geometry.computeBoundingBox();
  const nonManifoldEdges = [...edges.values()].filter(count => count !== 2).length;
  assert.equal(nonManifoldEdges, 0, 'Glass mesh must be a closed triangular surface');
  const inconsistentEdgeWindings = [...edgeDirections.values()].filter(value => value !== 0).length;
  assert.equal(inconsistentEdgeWindings, 0, 'Shared triangle edges must have opposite winding');
  assert(signedVolume > 0, 'Glass mesh must have outward winding and positive volume');
  const distinctSpatialVertices = new Set(points.map(key)).size;
  return {triangles: triangleVertices.length / 3, distinctSpatialVertices,
    planarNormalDirections: normals.size, edges: edges.size, nonManifoldEdges, weldToleranceLogical: 1e-5, signedVolume,
    inconsistentEdgeWindings, eulerCharacteristic: distinctSpatialVertices-edges.size+triangleVertices.length/3,
    convex: nonSupportingTriangles === 0, nonSupportingTriangles, maximumOutsideFaceDistance,
    bounds: {min: geometry.boundingBox.min.toArray(), max: geometry.boundingBox.max.toArray()},
    annotations: geometry.userData};
}

async function gpuProof(metadata, rgba, movie, output) {
  const factory = await import(pathToFileURL(metadata.sceneSource).href);
  const {config} = factory;
  assert.deepEqual(config.loop, {startFrame: 1, frameCount: 160});
  assert.equal((metadata.sourceDependencies || []).length, (config.sourceDependencies || []).length,
    'Imported render source fingerprints are missing');
  for (const [index, declared] of (config.sourceDependencies || []).entries()) {
    assert.equal(metadata.sourceDependencies[index].source, path.resolve(path.dirname(metadata.sceneSource), declared));
  }
  const previousGlobals = new Map(Object.keys(globals).map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  Object.assign(globalThis, globals);
  const previousNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  const previousSelf = Object.getOwnPropertyDescriptor(globalThis, 'self');
  const gpu = create(['backend=metal']);
  Object.defineProperty(globalThis, 'navigator', {value: {gpu, userAgent: 'Node.js Dawn Metal'}, configurable: true});
  Object.defineProperty(globalThis, 'self', {value: {requestAnimationFrame: () => 1, cancelAnimationFrame() {}}, configurable: true});
  let device, renderer, target, maskMaterial, blackMaterial, outlineWhiteMaterial;
  try {
    const adapter = await gpu.requestAdapter();assert(adapter);
    device = await adapter.requestDevice();
    const THREE = await import('three/webgpu');
    const {width, height, fps} = metadata;
    const canvas = {width, height, style: {}, addEventListener() {}, removeEventListener() {},
      getContext() {throw Error('GPU proof must remain offscreen');}};
    renderer = new THREE.WebGPURenderer({device, canvas, antialias: false});
    renderer.setSize(width, height, false);
    target = new THREE.RenderTarget(width, height, {type: THREE.UnsignedByteType, format: THREE.RGBAFormat, depthBuffer: true});
    target.texture.colorSpace = THREE.SRGBColorSpace;
    renderer.setRenderTarget(target);await renderer.init();
    const world = await factory.createScene(THREE);
    const cube = world.scene.getObjectByName('glass-cube'), ball = world.scene.getObjectByName('orbit-ball');
    const outline = world.scene.getObjectByName('ball-outline');
    const volume = world.scene.getObjectByName('glass-volume');
    assert(cube?.isGroup && ball?.isMesh);
    assert(volume?.isMesh && volume.geometry);
    const shape = {type: volume.geometry.type, parameters: volume.geometry.parameters,
      name: metadata.name, title: metadata.title, kind: config.geometry,
      mesh: meshFacts(volume.geometry)};
    const requireSoftening = !/diamond|star/i.test(config.geometry || config.name || '');
    assert.equal(typeof world.setOptics, 'function', 'The scene must expose independent optical controls');
    assert.equal(config.ballDiameterLogical, 22, 'The revised ball must be about 1.9 times larger');
    assert(ball.material.depthWrite && ball.material.depthTest && !ball.material.transparent);
    maskMaterial = new THREE.MeshBasicMaterial({color: 0xffffff, toneMapped: false});
    if (outline) {
      assert.equal(typeof world.setOutlineEnabled, 'function');
      assert(outline.isMesh && outline.material.side === THREE.BackSide);
      blackMaterial = new THREE.MeshBasicMaterial({color: 0x000000, toneMapped: false, depthWrite: true, depthTest: true});
      outlineWhiteMaterial = new THREE.MeshBasicMaterial({color: 0xffffff, toneMapped: false,
        depthWrite: true, depthTest: true, side: THREE.BackSide});
    }
    async function read() {
      renderer.render(world.scene, world.camera);
      return Buffer.from(await renderer.readRenderTargetPixelsAsync(target, 0, 0, width, height));
    }
    async function mask() {
      const original = world.scene.overrideMaterial;
      world.scene.overrideMaterial = maskMaterial;
      try {return packRGBA(await read(), width, height, 'threshold', 128);}
      finally {world.scene.overrideMaterial = original;}
    }
    const frameSize = width * height * 4, packedSize = width * height / 8;
    const capture = async frame => {await world.update(frame / fps);return read();};
    const start = await capture(config.loop.startFrame);
    assert(start.equals(rgba.subarray(frameSize, frameSize * 2)), 'Independent GPU start differs from export');
    const endpoint = await capture(config.loop.startFrame + config.loop.frameCount);
    const unwrapped = await capture(config.loop.startFrame + config.loop.frameCount * 2);
    assert(endpoint.equals(start), 'GPU loop endpoint changes grayscale pixels');
    assert(unwrapped.equals(start), 'A second unwrapped orbit changes grayscale pixels');
    const startBits = movie.subarray(packedSize, packedSize * 2);
    assert(packRGBA(endpoint, width, height, 'ordered').equals(startBits));
    assert(packRGBA(unwrapped, width, height, 'ordered').equals(startBits));
    const controls = [], cubeMatrices = [], cubeBitmaps = [];
    for (const [frame, side] of [[41, 'front'], [121, 'behind']]) {
      await world.update(frame / fps);
      assert.equal(world.scene.userData.pose.phase, side);
      world.setOptics('default');
      const full = await read();
      assert(full.equals(rgba.subarray(frame * frameSize, (frame + 1) * frameSize)));
      let noOutline = full, noOutlineMask = null;
      if (outline) {
        world.setOutlineEnabled(false);noOutline = await read();noOutlineMask = await mask();world.setOutlineEnabled(true);
      }
      const fullMask = await mask();
      ball.visible = false;const hidden = await read(), hiddenMask = await mask();
      cube.updateMatrixWorld(true);cubeMatrices.push(cube.matrixWorld.elements.slice());
      cubeBitmaps.push(packRGBA(hidden, width, height, 'ordered'));
      ball.visible = true;cube.visible = false;const ballOnly = await read();cube.visible = true;
      world.setOptics('no-refraction');
      const noRefraction = await read();ball.visible = false;const noRefractionHidden = await read();ball.visible = true;
      world.setOptics('sharp');
      const sharp = await read();ball.visible = false;const sharpHidden = await read();ball.visible = true;
      world.setOptics('default');
      world.scene.updateMatrixWorld(true);world.camera.updateMatrixWorld(true);
      const raycaster = new THREE.Raycaster();
      const fullBits = packRGBA(full, width, height, 'ordered'), hiddenBits = packRGBA(hidden, width, height, 'ordered');
      let overlappingPixels = 0, grayChangedInsideCube = 0, binaryChangedInsideCube = 0, foregroundMismatches = 0;
      let sumGrayDifference = 0, effectPixelsOutsideOriginalBall = 0;
      const ballLevels = new Set(), cubeLevels = new Set();
      const difference = Buffer.alloc(frameSize), affectedMask = Buffer.alloc(packedSize);
      let outlineChangedPixels = 0, outlineBlackPixels = 0, coreChangesFromOutline = 0;
      for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
        const pixel = y * width + x, at = pixel * 4;
        if (ballOnly[at]) ballLevels.add(ballOnly[at]);
        if (hidden[at]) cubeLevels.add(hidden[at]);
        const delta = Math.abs(full[at] - hidden[at]);
        if (outline && full[at] !== noOutline[at]) {
          outlineChangedPixels++;outlineBlackPixels += Number(full[at] === 0);
          coreChangesFromOutline += Number(ballOnly[at] !== 0);
        }
        difference[at] = difference[at + 1] = difference[at + 2] = delta ? 255 : 0;difference[at + 3] = 255;
        if (delta >= 3 || ballOnly[at] >= 3) affectedMask[pixel >> 3] |= 128 >> (pixel & 7);
        effectPixelsOutsideOriginalBall += Number(delta >= 3 && ballOnly[at] === 0);
        raycaster.setFromCamera(new THREE.Vector2((x + 0.5) / width * 2 - 1, 1 - (y + 0.5) / height * 2), world.camera);
        const glassHit = raycaster.intersectObject(cube, true).find(hit => hit.object.isMesh), sphereHit = raycaster.intersectObject(ball, false)[0];
        if (!glassHit || !sphereHit || !ballOnly[at]) continue;
        overlappingPixels++;
        if (side === 'behind') assert(sphereHit.distance > glassHit.distance, 'Behind control ball is actually in front');
        else {
          assert(sphereHit.distance < glassHit.distance, 'Front control ball is actually behind');
          foregroundMismatches += Number(full[at] !== ballOnly[at]);
        }
        grayChangedInsideCube += Number(delta !== 0);
        binaryChangedInsideCube += Number(bit(fullBits, pixel) !== bit(hiddenBits, pixel));
        sumGrayDifference += delta;
      }
      assert(overlappingPixels >= 150, `${side} control has insufficient actual larger-ball/cube overlap`);
      assert(grayChangedInsideCube >= 100, `${side} ball is not visible over the cube`);
      assert(binaryChangedInsideCube >= 25, `${side} ball disappears during dithering`);
      assert.equal(foregroundMismatches, 0, 'Glass paints over the foreground ball');
      if (outline) {
        if (side === 'front') {
          assert(outlineChangedPixels >= 20 && outlineBlackPixels >= 20,
            'The front outline must add a visible opaque black annulus');
          assert.equal(coreChangesFromOutline, 0, 'The black outline changes the shaded ball core');
        } else assert(full.equals(noOutline), 'A black outline appeared behind the glass');
      }
      assert(ballLevels.size >= 24 && cubeLevels.size >= 3,
        `GPU source lacks a shaded ball or distinct glass surfaces (${ballLevels.size}/${cubeLevels.size} levels)`);
      const refractedSignal = signal(full, hidden), straightSignal = signal(noRefraction, noRefractionHidden);
      const sharpSignal = signal(sharp, sharpHidden);
      const actualMetrics = signalMetrics(refractedSignal, width, height);
      const straightMetrics = signalMetrics(straightSignal, width, height), sharpMetrics = signalMetrics(sharpSignal, width, height);
      const centroidShift = Math.hypot(...actualMetrics.centroid.map((value, axis) => value - straightMetrics.centroid[axis]));
      const opticalDifference = imageDifference(full, noRefraction, width, height);
      const softeningDifference = imageDifference(full, sharp, width, height);
      if (side === 'behind') {
        assert(opticalDifference.grayPixels >= 60 && opticalDifference.binaryPixels >= 15,
          'Refraction does not survive the actual grayscale and bitmap export');
        if (shape.type === 'BoxGeometry') {
          assert(centroidShift >= 1, `The behind-ball contribution has no measurable spatial displacement (${centroidShift})`);
        } else {
          // Facets can split the ball into lobes whose centroid shifts cancel.
          // Actual contribution outside the straight ball footprint proves a
          // spatial effect without assuming a single displaced blob.
          assert(effectPixelsOutsideOriginalBall >= 40, 'Prism refraction has no displaced spatial footprint');
        }
        assert(effectPixelsOutsideOriginalBall >= 8, `Refraction remains confined to the original ball footprint (${effectPixelsOutsideOriginalBall})`);
        if (requireSoftening) {
          assert(actualMetrics.normalizedGradient < sharpMetrics.normalizedGradient * 0.97,
            `The transmitted ball is not measurably softer than the sharp-refraction control (${actualMetrics.normalizedGradient}/${sharpMetrics.normalizedGradient})`);
          assert(softeningDifference.binaryPixels >= 8, 'Optical softening vanishes in the exported bitmap');
        }
      }
      for (const [name, bytes] of [['full', full], ['hidden', hidden], ['ball', ballOnly], ['diff', difference],
        ['no-refraction', noRefraction], ['no-refraction-hidden', noRefractionHidden], ['sharp', sharp], ['sharp-hidden', sharpHidden],
        ['no-outline', noOutline]]) {
        fs.writeFileSync(path.join(output, `control-${side}-${name}.rgba`), bytes);
      }
      fs.writeFileSync(path.join(output, `control-${side}-full-mask.frames`), fullMask);
      fs.writeFileSync(path.join(output, `control-${side}-hidden-mask.frames`), hiddenMask);
      fs.writeFileSync(path.join(output, `control-${side}-affected-mask.frames`), affectedMask);
      if (noOutlineMask) fs.writeFileSync(path.join(output, `control-${side}-no-outline-mask.frames`), noOutlineMask);
      const cubeBounds = bounds(hidden, width, height), ballBounds = bounds(ballOnly, width, height);
      assert(ballBounds[2] - ballBounds[0] >= 21 && ballBounds[3] - ballBounds[1] >= 21, 'Actual GPU ball is too small');
      controls.push({frame, time: frame / fps, side, actualBallPosition: ball.position.toArray(), overlappingPixels,
        grayChangedInsideCube, binaryChangedInsideCube, foregroundMismatches,
        meanGrayChangeInsideCube: sumGrayDifference / overlappingPixels,
        ballDistinctGrayLevels: ballLevels.size, cubeDistinctGrayLevels: cubeLevels.size,
        cubeBoundsLogical: cubeBounds, ballBoundsLogical: ballBounds,
        cubePhysicalSize: [(cubeBounds[2] - cubeBounds[0]) * 2, (cubeBounds[3] - cubeBounds[1]) * 2],
        ballPhysicalSize: [(ballBounds[2] - ballBounds[0]) * 2, (ballBounds[3] - ballBounds[1]) * 2],
        fullSha256: sha(full), hiddenSha256: sha(hidden), ballOnlySha256: sha(ballOnly),
        noRefractionSha256: sha(noRefraction), noRefractionHiddenSha256: sha(noRefractionHidden),
        sharpSha256: sha(sharp), sharpHiddenSha256: sha(sharpHidden),
        ...(outline ? {outline: {changedGrayPixels: outlineChangedPixels, changedPixelsAreBlack: outlineBlackPixels,
          coreChanges: coreChangesFromOutline, noOutlineSha256: sha(noOutline), noOutlineMaskSha256: sha(noOutlineMask)}} : {}),
        fullMaskSha256: sha(fullMask), hiddenMaskSha256: sha(hiddenMask), affectedMaskSha256: sha(affectedMask),
        optics: {centroidShiftLogical: centroidShift, effectPixelsOutsideOriginalBall,
          softeningRequired: requireSoftening,
          actualSignal: actualMetrics, noRefractionSignal: straightMetrics, sharpSignal: sharpMetrics,
          refractionDifference: opticalDifference, softeningDifference,
          softenedGradientRatio: actualMetrics.normalizedGradient / sharpMetrics.normalizedGradient}});
    }
    const matrixDifference = Math.max(...cubeMatrices[0].map((value, index) => Math.abs(value - cubeMatrices[1][index])));
    let movingCubeBitPixels = 0;
    for (let pixel = 0; pixel < width * height; pixel++) movingCubeBitPixels += Number(bit(cubeBitmaps[0], pixel) !== bit(cubeBitmaps[1], pixel));
    assert(matrixDifference >= 0.1 && movingCubeBitPixels >= 80, 'The cube is not visibly moving across the orbit');
    let outlineProof = null;
    if (outline) {
      const ballMaterial = ball.material, shellMaterial = outline.material;
      const rings = Buffer.alloc(metadata.frameCount * packedSize), ringPixels = [];
      ball.material = blackMaterial;outline.material = outlineWhiteMaterial;
      for (let frame = 0; frame < metadata.frameCount; frame++) {
        await world.update(frame / fps);cube.visible = false;
        const ring = packRGBA(await read(), width, height, 'threshold', 128);
        ring.copy(rings, frame * packedSize);
        let count = 0;
        for (let pixel = 0; pixel < width * height; pixel++) if (bit(ring, pixel)) {
          count++;assert.equal(bit(movie, frame * width * height + pixel), 0, 'A source outline-ring pixel is white');
        }
        if (world.scene.userData.pose.phase === 'behind') assert.equal(count, 0, 'Outline matte exists behind glass');
        ringPixels.push(count);
      }
      ball.material = ballMaterial;outline.material = shellMaterial;
      fs.writeFileSync(path.join(output, 'outline-ring-mask.frames'), rings);
      let unchangedBehindFrames = 0;
      let comparison;
      if (shape.type === 'BoxGeometry') {
        const previousDirectory = path.resolve(output, '../three-scene-glass-refraction/render');
        const previousMovie = fs.readFileSync(path.join(previousDirectory, 'bitmap.frames'));
        const previousRGBA = fs.readFileSync(path.join(previousDirectory, 'color.rgba'));
        for (let frame = config.loop.startFrame + config.loop.frameCount / 2; frame < metadata.frameCount; frame++) {
          assert(movie.subarray(frame * packedSize, (frame + 1) * packedSize).equals(previousMovie.subarray(frame * packedSize, (frame + 1) * packedSize)));
          assert(rgba.subarray(frame * frameSize, (frame + 1) * frameSize).equals(previousRGBA.subarray(frame * frameSize, (frame + 1) * frameSize)));
          unchangedBehindFrames++;
        }
        comparison = {method: 'same cube before outline', previousMovieSha256: sha(previousMovie)};
      } else {
        for (let frame = config.loop.startFrame + config.loop.frameCount / 2; frame < metadata.frameCount; frame++) {
          await world.update(frame / fps);world.setOutlineEnabled(false);
          const noOutline = await read();
          assert(noOutline.equals(rgba.subarray(frame * frameSize, (frame + 1) * frameSize)), 'Same-shape rear outline control changed');
          assert(packRGBA(noOutline, width, height, 'ordered').equals(movie.subarray(frame * packedSize, (frame + 1) * packedSize)));
          unchangedBehindFrames++;
        }
        world.setOutlineEnabled(true);
        comparison = {method: 'actual GPU same-shape no-outline control', shape: shape.type};
      }
      outlineProof = {ringMaskFile: 'outline-ring-mask.frames', ringMaskSha256: sha(rings),
        logicalRingPixelsPerFrame: ringPixels, unchangedBehindFrames, comparison,
        sourceRingWhitePixels: 0, coreDiameterPhysical: 44, outerDiameterPhysical: 48};
    }
    return {loop: {...config.loop, endpointFrame: 161, unwrappedEndpointFrame: 321,
      endpointMatchesStart: true, unwrappedPeriodMatchesStart: true, rgbaSha256: sha(start), bitmapSha256: sha(startBits)},
      cubeMotion: {matrixDifference, changedBitmapPixels: movingCubeBitPixels, matrices: cubeMatrices},
      shape,
      ...(outlineProof ? {outline: outlineProof} : {}), controls};
  } finally {
    maskMaterial?.dispose();blackMaterial?.dispose();outlineWhiteMaterial?.dispose();target?.dispose();renderer?.dispose();device?.destroy();
    if (previousNavigator) Object.defineProperty(globalThis, 'navigator', previousNavigator);else delete globalThis.navigator;
    if (previousSelf) Object.defineProperty(globalThis, 'self', previousSelf);else delete globalThis.self;
    for (const [key, descriptor] of previousGlobals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);else delete globalThis[key];
    }
  }
}

function previews(input, output) {
  const python = `
from pathlib import Path
from PIL import Image,ImageDraw
import json,sys
r=Path(sys.argv[1]);o=Path(sys.argv[2]);m=json.loads((r/'metadata.json').read_text())
raw=(r/m['rgbaFile']).read_bytes();bits=(r/m['framesFile']).read_bytes()
def scaled(data,kind):
 im=Image.frombytes(kind,(160,100),data).convert('RGB')
 return im.resize((320,200),Image.Resampling.NEAREST)
pair=Image.new('RGB',(640,448));d=ImageDraw.Draw(pair)
control=Image.new('RGB',(960,448));c=ImageDraw.Draw(control)
for row,(frame,side) in enumerate(((41,'front'),(121,'behind'))):
 y=row*224;d.text((6,y+5),f'{side.upper()} / frame {frame}: GPU grayscale | ordered 1 bit',fill='white')
 pair.paste(scaled(raw[frame*64000:(frame+1)*64000],'RGBA'),(0,y+24))
 pair.paste(scaled(bits[frame*2000:(frame+1)*2000],'1'),(320,y+24))
 for col,(name,title) in enumerate((('full','Ball visible'),('hidden','Same pose, ball hidden'),('diff','Changed GPU pixels'))):
  c.text((col*320+6,y+5),f'{side.upper()}: {title}',fill='white')
  control.paste(scaled((o/f'control-{side}-{name}.rgba').read_bytes(),'RGBA'),(col*320,y+24))
pair.save(o/'bitmap-front-back.png');control.save(o/'transparency-control.png')
optics=Image.new('RGB',(960,448));od=ImageDraw.Draw(optics)
for col,(name,title) in enumerate((('no-refraction','Zero thickness: no spatial refraction'),('sharp','Sharp refraction'),('full','Refraction + optical softening'))):
 data=(o/f'control-behind-{name}.rgba').read_bytes()
 od.text((col*320+5,5),title,fill='white');optics.paste(scaled(data,'RGBA'),(col*320,24))
 # Quantize again in Python independently for visual control panels.
 bayer=(0,8,2,10,12,4,14,6,3,11,1,9,15,7,13,5)
 pixels=bytes(255 if data[(y*160+x)*4] >= (bayer[(y%4)*4+x%4]+.5)*255/16 else 0 for y in range(100) for x in range(160))
 od.text((col*320+5,229),'Same GPU control after ordered dithering',fill='white')
 optics.paste(scaled(pixels,'L'),(col*320,248))
optics.save(o/'optics-controls.png')
if (o/'control-front-no-outline.rgba').exists():
 outline=Image.new('RGB',(640,448));dd=ImageDraw.Draw(outline)
 for col,(name,title) in enumerate((('no-outline','No black border'),('full','Opaque foreground border'))):
  data=(o/f'control-front-{name}.rgba').read_bytes();dd.text((col*320+5,5),title,fill='white')
  outline.paste(scaled(data,'RGBA'),(col*320,24))
  pixels=bytes(255 if data[(y*160+x)*4] >= (bayer[(y%4)*4+x%4]+.5)*255/16 else 0 for y in range(100) for x in range(160))
  dd.text((col*320+5,229),'Actual GPU control after dithering',fill='white');outline.paste(scaled(pixels,'L'),(col*320,248))
 outline.save(o/'outline-controls.png')
for frame in (1,41,81,121,160):
 scaled(bits[frame*2000:(frame+1)*2000],'1').save(o/f'bitmap-{frame:03d}.png')
loop=[scaled(bits[frame*2000:(frame+1)*2000],'1') for frame in range(1,161)]
loop[0].save(o/'bitmap-loop.gif',save_all=True,append_images=loop[1:],duration=40,loop=0,optimize=False,disposal=1)
with Image.open(o/'bitmap-loop.gif') as gif:
 assert gif.n_frames==160
 for frame,expected in enumerate(loop):
  gif.seek(frame);assert gif.info['duration']==40;assert gif.convert('RGB').tobytes()==expected.tobytes()
`;
  execFileSync('rtk', ['proxy', 'python3', '-c', python, input, output], {stdio: 'pipe'});
}

export async function main(argv = process.argv.slice(2)) {
  const options = {};
  for (let index = 0; index < argv.length; index += 2) {
    assert(['--input', '--output'].includes(argv[index]));assert(argv[index + 1]);options[argv[index]] = argv[index + 1];
  }
  const input = path.resolve(options['--input'] || path.join(here, '../build/three-scene-glass/render'));
  const file = path.resolve(options['--output'] || path.join(input, '../verification.json'));
  const output = path.dirname(file);fs.mkdirSync(output, {recursive: true});fs.rmSync(file, {force: true});
  const metadata = JSON.parse(fs.readFileSync(path.join(input, 'metadata.json')));
  assert.equal(metadata.width, 160);assert.equal(metadata.height, 100);assert.equal(metadata.frameCount, 161);assert.equal(metadata.fps, 25);
  assert.equal(metadata.quantization.mode, 'ordered');assert.equal(metadata.renderer.browserUsed, false);
  assert.equal(metadata.renderer.canvasContextRequests, 0);assert(metadata.verification.allFramesReadFromGPU);
  assert.equal(sha(fs.readFileSync(metadata.sceneSource)), metadata.sourceSha256);
  for (const dependency of metadata.sourceDependencies || []) {
    assert(path.isAbsolute(dependency.source));
    assert.equal(sha(fs.readFileSync(dependency.source)), dependency.sha256, 'Imported render source changed after export');
  }
  const movie = fs.readFileSync(path.join(input, metadata.framesFile));
  const rgba = fs.readFileSync(path.join(input, metadata.rgbaFile));
  const mask = fs.readFileSync(path.join(input, metadata.objectMaskFile));
  assert.equal(movie.length, 161 * 2000);assert.equal(rgba.length, 161 * 64000);assert.equal(mask.length, movie.length);
  assert.equal(sha(movie), metadata.hashes.frames);assert.equal(sha(rgba), metadata.hashes.rgba);assert.equal(sha(mask), metadata.hashes.objectMask);
  let wrongBits = 0, nonGrayscale = 0, nonOpaque = 0, whiteOutsideMask = 0;
  const levels = new Set();
  for (let frame = 0; frame < 161; frame++) for (let y = 0; y < 100; y++) for (let x = 0; x < 160; x++) {
    const pixel = frame * 16000 + y * 160 + x, at = pixel * 4, gray = rgba[at], alpha = rgba[at + 3];
    levels.add(gray);nonGrayscale += Number(gray !== rgba[at + 1] || gray !== rgba[at + 2]);nonOpaque += Number(alpha !== 255);
    const expected = Number(gray * alpha / 255 >= (rank(x, y) + 0.5) * 255 / 16), actual = bit(movie, pixel);
    wrongBits += Number(expected !== actual);whiteOutsideMask += Number(actual && !bit(mask, pixel));
  }
  assert.equal(wrongBits, 0);assert.equal(nonGrayscale, 0);assert.equal(nonOpaque, 0);assert.equal(whiteOutsideMask, 0);
  assert(movie.subarray(0, 2000).every(byte => byte === 0));
  for (let frame = 1; frame < 161; frame++) assert(movie.subarray(frame * 2000, (frame + 1) * 2000).some(byte => byte !== 0));
  const proof = await gpuProof(metadata, rgba, movie, output);
  previews(input, output);
  const report = {pass: true, stage: 'Three.js grayscale to dithered bitmap only', characterConversionRun: false,
    width: 160, height: 100, physicalPreviewPixels: [320, 200], fps: 25, frameCount: 161,
    startupBlankFrames: 1, loopSeconds: 6.4, sourceSha256: metadata.sourceSha256,
    bitmapSha256: sha(movie), rgbaSha256: sha(rgba), objectMaskSha256: sha(mask),
    sourceFile: metadata.sceneSource, input, ...proof,
    sourceDependencies: metadata.sourceDependencies || [],
    quantization: {screenAnchored: true, matrix: '4x4 Bayer', pixelsCompared: 161 * 16000, wrongBits, nonGrayscale, nonOpaque,
      whiteOutsideMask, distinctSourceGrayLevels: levels.size},
    previews: {frontBack: 'bitmap-front-back.png', controls: 'transparency-control.png', loop: 'bitmap-loop.gif',
      optics: 'optics-controls.png',
      ...(proof.outline ? {outline: 'outline-controls.png'} : {}),
      decodedGifFramesAnd40msTimingVerified: true}};
  fs.writeFileSync(file, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report, null, 2));return report;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().then(() => process.exit(0), error => {console.error(error);process.exit(1);});
}
