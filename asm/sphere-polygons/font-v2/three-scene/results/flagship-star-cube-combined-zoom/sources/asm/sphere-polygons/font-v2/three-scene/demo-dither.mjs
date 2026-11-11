// Keep the approved checker entrance unchanged. This scene adds grayscale after
// it; the exporter, rather than Three.js, turns those gray pixels into dots.
import {config as approvedConfig, createScene as createApprovedScene} from './demo.mjs';

const uncontrastedFaceRanges = [[24, 176], [48, 224], [112, 240]];
const grayContrast = 1.15;
const faceRanges = uncontrastedFaceRanges.map(range => range.map(level =>
  Math.round(Math.max(0, Math.min(255, 128 + (level - 128) * grayContrast)) * 10) / 10));
export const config = Object.freeze({
  ...approvedConfig,
  name: 'checker-to-gray-cube',
  title: 'Schackboll till kub med gradienter',
  description: 'Den godkända femsekundersscenen följs av en övertoning till tydliga tvådimensionella gradienter inom kubens sidor. Dithering görs först i bitmapexporten.',
  durationSeconds: 8,
  phaseLabels: {...approvedConfig.phaseLabels, fade:'Tonar till sidgradienter', gray:'Roterande kub med sidgradienter'},
  grayFaceRangesSRGB: faceRanges,
  grayFaceUncontrastedRangesSRGB: uncontrastedFaceRanges,
  grayContrast,
  grayInterpolation: 'Affine linear-light gradient within each local face; endpoints encoded in sRGB.',
  grayFadeSeconds: [5, 6],
});

const clamp = value => Math.max(0, Math.min(1, value));
const smooth = value => value * value * (3 - 2 * value);

function grayFaceMesh(THREE, sourceMesh) {
  const source = sourceMesh.geometry.toNonIndexed();
  const p = source.getAttribute('position'), uv = source.getAttribute('uv');
  const triangles = [[], [], []];
  for (let first = 0; first < p.count; first += 3) {
    const at = first * 3;
    const ax = p.array[at + 3] - p.array[at], ay = p.array[at + 4] - p.array[at + 1], az = p.array[at + 5] - p.array[at + 2];
    const bx = p.array[at + 6] - p.array[at], by = p.array[at + 7] - p.array[at + 1], bz = p.array[at + 8] - p.array[at + 2];
    const normal = [ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx];
    const [nx, ny, nz] = normal.map(Math.abs);
    const axis = nx >= ny && nx >= nz ? 0 : ny >= nz ? 1 : 2;
    triangles[axis].push({first, sign:normal[axis] < 0 ? -1 : 1});
  }

  // Collect triangles by face axis so three material draws suffice. A shared
  // position within a face receives the same gradient value on every triangle.
  const geometry = new THREE.BufferGeometry();
  geometry.name = 'cube-fixed-srgb-face-triangles';
  const positions = new Float32Array(p.array.length), uvs = new Float32Array(uv.array.length);
  const colors = new Float32Array(p.array.length), gradient = new Float32Array(p.array.length);
  const halfSide = 24 / Math.sqrt(3);
  const linearRanges = faceRanges.map(range => range.map(level =>
    new THREE.Color().setRGB(level / 255, level / 255, level / 255, THREE.SRGBColorSpace).r));
  let next = 0;
  for (let axis = 0; axis < 3; axis++) {
    const start = next;
    for (const {first, sign} of triangles[axis]) {
      positions.set(p.array.subarray(first * 3, (first + 3) * 3), next * 3);
      uvs.set(uv.array.subarray(first * 2, (first + 3) * 2), next * 2);
      for (let corner = 0; corner < 3; corner++) {
        const at = (first + corner) * 3;
        const x = p.array[at], y = p.array[at + 1], z = p.array[at + 2];
        const u = axis === 0 ? (1 - sign * z / halfSide) / 2
          : axis === 1 ? (1 + x / halfSide) / 2 : (1 + sign * x / halfSide) / 2;
        const v = axis === 1 ? (1 + sign * z / halfSide) / 2 : (1 - y / halfSide) / 2;
        const q = (clamp(u) + clamp(v)) / 2;
        const [low, high] = linearRanges[axis];
        const light = (1 - q) * high + q * low;
        gradient.fill(light, (next + corner) * 3, (next + corner + 1) * 3);
      }
      next += 3;
    }
    geometry.addGroup(start, next - start, axis);
  }
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
  const color = new THREE.BufferAttribute(colors, 3);
  if (THREE.DynamicDrawUsage !== undefined) color.setUsage(THREE.DynamicDrawUsage);
  geometry.setAttribute('color', color);
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  source.dispose();

  const original = sourceMesh.material.map;
  const checker = Uint8Array.from(original.image.data);
  const textures = faceRanges.map((range, axis) => {
    const texture = new THREE.DataTexture(Uint8Array.from(checker), original.image.width, original.image.height, original.format, original.type);
    texture.name = 'checker-fading-to-white-axis-' + axis;
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.minFilter = texture.magFilter = THREE.NearestFilter;
    texture.wrapS = original.wrapS;
    texture.wrapT = original.wrapT;
    texture.offset.copy(original.offset);
    texture.repeat.copy(original.repeat);
    texture.center.copy(original.center);
    texture.rotation = original.rotation;
    texture.flipY = original.flipY;
    texture.generateMipmaps = false;
    texture.needsUpdate = true;
    return texture;
  });
  const materials = textures.map((map, axis) => {
    const material = new THREE.MeshBasicMaterial({color:0xffffff, map, vertexColors:true, toneMapped:false});
    material.name = 'continuous-srgb-face-' + faceRanges[axis].join('-');
    return material;
  });
  const mesh = new THREE.Mesh(geometry, materials);
  mesh.name = 'fixed-gray-cube';
  mesh.userData.grayFaceRangesSRGB = faceRanges;
  mesh.userData.grayAxisOrder = ['x', 'y', 'z'];
  mesh.visible = false;
  let previousFade = NaN;
  function fade(progress) {
    if (progress === previousFade) return;
    for (let axis = 0; axis < textures.length; axis++) {
      const data = textures[axis].image.data;
      for (let at = 0; at < data.length; at += 4) {
        // Remove the checker while the linear vertex gradient fades in. After
        // six seconds the map is white and only the smooth face colors remain.
        const value = Math.round(checker[at] * (1 - progress) + 255 * progress);
        data[at] = data[at + 1] = data[at + 2] = value;
      }
      textures[axis].needsUpdate = true;
    }
    for (let at = 0; at < colors.length; at++) colors[at] = 1 + (gradient[at] - 1) * progress;
    color.needsUpdate = true;
    previousFade = progress;
  }
  return {mesh, fade};
}

export function createScene(THREE) {
  const approved = createApprovedScene(THREE);
  const original = approved.scene.getObjectByName('morphing-sphere-cube');
  approved.update(5);
  const gray = grayFaceMesh(THREE, original);
  approved.scene.add(gray.mesh);

  function update(time) {
    const t = Math.max(0, Math.min(config.durationSeconds, Number.isFinite(time) ? time : 0));
    approved.update(Math.min(5, t));
    // The first five seconds render the original object and its original
    // buffers/material/texture. The extra mesh stays hidden throughout them.
    original.visible = t > 0 && t <= 5;
    gray.mesh.visible = t > 5;
    if (t >= 5) {
      const yaw = 0.5 + 0.9 * t + 0.18 * Math.sin(1.4 * t);
      const pitch = 0.35 + 1.2 * t;
      const roll = 0.15 + 0.75 * t + 0.22 * Math.sin(1.1 * t);
      gray.mesh.position.copy(original.position);
      gray.mesh.scale.copy(original.scale);
      gray.mesh.rotation.set(pitch, yaw, roll, 'ZXY');
      const progress = smooth(clamp(t - 5));
      gray.fade(progress);
      approved.scene.userData.pose = {...approved.scene.userData.pose, time:t,
        phase:t < 6 ? 'fade' : 'gray', grayFade:progress, grayFaceRangesSRGB:faceRanges,
        yaw, pitch, roll};
    }
  }
  update(0);
  return {scene:approved.scene, camera:approved.camera, update};
}
