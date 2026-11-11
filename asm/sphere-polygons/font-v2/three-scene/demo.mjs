// A deterministic Three.js scene. The exporter supplies its own THREE namespace;
// this module has no renderer, package-version, browser, or asset-path dependency.
export const config = Object.freeze({
  name: 'sphere-to-cube',
  title: 'Schacksfär till kub',
  description: 'Vår svartvita schackboll med 14 × 7 rutor följer sin växande korkskruvsbana. Sedan morfas den till en kub med samma schacktextur och fortsatt rotation kring tre axlar.',
  phaseLabels: {blank:'Tom skärm', grow:'Växer och korkskruvar', sphere:'Schacksfär', morph:'Schacksfär till kub', cube:'Roterande schackkub'},
  width: 160,
  height: 100,
  fps: 25,
  durationSeconds: 5,
  checkerColumns: 14,
  checkerRows: 7,
});

const clamp = (value, low = 0, high = 1) => Math.max(low, Math.min(high, value));
const smooth = value => value * value * (3 - 2 * value);

function checkerTexture(THREE) {
  // Exactly one texel per checker square. Pure endpoints plus nearest sampling
  // make the scene a measurable black/white reference before font fitting.
  const width = config.checkerColumns, height = config.checkerRows;
  const pixels = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const value = (x + y) % 2 ? 0 : 255;
    const at = (y * width + x) * 4;
    pixels[at] = pixels[at + 1] = pixels[at + 2] = value;
    pixels[at + 3] = 255;
  }
  const texture = new THREE.DataTexture(pixels, width, height, THREE.RGBAFormat, THREE.UnsignedByteType);
  texture.minFilter = texture.magFilter = THREE.NearestFilter;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.offset.x = 1 / 4 + 1 / config.checkerColumns; // Match the accepted atan2(x,z) checker and white-on-odd parity.
  texture.generateMipmaps = false;
  if (THREE.SRGBColorSpace !== undefined) texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;
  texture.name = 'black-white-14-by-7-checker';
  return texture;
}

export function createScene(THREE) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x000000);
  const camera = new THREE.OrthographicCamera(-80, 80, 50, -50, 0.1, 300);
  camera.position.set(0, 0, 150);
  camera.lookAt(0, 0, 0);

  // A 24-logical-pixel radius is 48 logical / 96 physical pixels across.
  // Start with actual spherical UVs; keep them unchanged through the morph.
  const radius = 24;
  const halfSide = radius / Math.sqrt(3);
  const geometry = new THREE.SphereGeometry(radius, config.checkerColumns * 6, config.checkerRows * 6);
  geometry.name = 'uv-checker-sphere-to-cube';
  const position = geometry.getAttribute('position');
  if (THREE.DynamicDrawUsage !== undefined) position.setUsage(THREE.DynamicDrawUsage);
  const sphere = Float32Array.from(position.array);
  const originalNormals = Float32Array.from(geometry.getAttribute('normal').array);
  const cube = new Float32Array(sphere.length);
  for (let at = 0; at < sphere.length; at += 3) {
    const maximum = Math.max(Math.abs(sphere[at]), Math.abs(sphere[at + 1]), Math.abs(sphere[at + 2]));
    for (let axis = 0; axis < 3; axis++) {
      cube[at + axis] = sphere[at + axis] / maximum * halfSide;
    }
  }
  const material = new THREE.MeshBasicMaterial({color:0xffffff, map:checkerTexture(THREE), toneMapped:false});
  material.name = 'unlit-pure-black-white-checker';
  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = 'morphing-sphere-cube';
  scene.add(mesh);
  scene.userData.calibration = {checkerColumns:14, checkerRows:7, expectedRGBLevels:[0,255], unlit:true};

  let previousMorph = NaN;
  function update(time) {
    const t = clamp(Number.isFinite(time) ? time : 0, 0, config.durationSeconds);
    mesh.visible = t > 0; // The existing C64 player starts from a cleared screen.
    // Preserve the accepted checkerball's three-second entrance. Its script
    // uses physical 320x200 coordinates; this scene uses half-size logical ones.
    const progress = clamp((t - 0.12) / (3 - 0.12));
    const approach = smooth(progress);
    const helix = 26 * Math.sin(Math.PI * progress) ** 2;
    const winding = 4 * Math.PI * progress;
    const centerX = 33 + (210 - 33) * approach + helix * Math.cos(winding);
    const centerY = 97 + (100 - 97) * approach + helix * Math.sin(winding);
    const diameter = t <= 0 ? 0 : 4 + (96 - 4) * clamp(t / 3);
    const scale = diameter / 96;
    mesh.scale.setScalar(scale);
    mesh.position.set((centerX - 160) / 2, (100 - centerY) / 2, 0);
    const yaw = 0.5 + 0.9 * t + 0.18 * Math.sin(1.4 * t);
    const pitch = 0.35 + 1.2 * t;
    const roll = 0.15 + 0.75 * t + 0.22 * Math.sin(1.1 * t);
    mesh.rotation.set(pitch, yaw, roll, 'ZXY'); // Accepted forward transform: Rz * Rx * Ry.
    const morph = smooth(clamp((t - 3) / 1.5));
    if (morph !== previousMorph) {
      for (let at = 0; at < position.array.length; at++) {
        position.array[at] = sphere[at] + (cube[at] - sphere[at]) * morph;
      }
      position.needsUpdate = true;
      geometry.computeVertexNormals();
      // SphereGeometry contains unused duplicated pole vertices. Keep those
      // normals finite as well; the reference material itself is unlit.
      const normal = geometry.getAttribute('normal');
      for (let at = 0; at < normal.array.length; at += 3) {
        if (normal.array[at] === 0 && normal.array[at + 1] === 0 && normal.array[at + 2] === 0) {
          normal.array[at] = originalNormals[at];
          normal.array[at + 1] = originalNormals[at + 1];
          normal.array[at + 2] = originalNormals[at + 2];
        }
      }
      normal.needsUpdate = true;
      geometry.computeBoundingSphere();
      previousMorph = morph;
    }
    const phase = t === 0 ? 'blank' : t < 3 ? 'grow' : t < 4.5 ? 'morph' : 'cube';
    scene.userData.pose = {time:t, phase, morph, logicalDiameter:diameter / 2, centerX, centerY, diameter, yaw, pitch, roll};
  }
  update(0);
  return {scene, camera, update};
}
