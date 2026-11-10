// Grayscale scene only. The existing exporter applies one screen-fixed Bayer
// pattern after actual GPU readback; no material contains a dither texture.
export const config = Object.freeze({
  name: 'glass-cube-orbit',
  title: 'Glaskub med kretsande boll',
  description: 'En stor gråtonad boll kretsar kring en långsamt vridande glaskub. Riktigt ljusbrytande, lätt frostat glas förskjuter och mjukar upp bollen bakom kuben. Gråskalebilden dithras först vid bitmapexporten.',
  width: 160,
  height: 100,
  fps: 25,
  durationSeconds: 161 / 25,
  loop: Object.freeze({startFrame: 1, frameCount: 160}),
  phaseLabels: {blank: 'Tom startbild', front: 'Bollen framför glaset', behind: 'Bollen genom glaset'},
  cubeSideLogical: 34,
  ballDiameterLogical: 22,
  outlineWidthLogical: 1,
  orbitRadiusLogical: 45,
  orbitTiltLogical: 13,
});

const clamp = value => Math.max(0, Math.min(1, value));

function gray(THREE, value) {
  return new THREE.Color().setRGB(value, value, value, THREE.SRGBColorSpace);
}

function studioEnvironment(THREE) {
  const width = 256, height = 128, data = new Uint8Array(width * height * 4);
  const gaussian = (x, center, spread) => Math.exp(-(((x - center) / spread) ** 2));
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const u = x / width, v = y / height;
    const softbox = 0.96 * gaussian(u, 0.22, 0.055) * gaussian(v, 0.36, 0.23);
    const fill = 0.52 * gaussian(u, 0.69, 0.13) * gaussian(v, 0.46, 0.34);
    const ceiling = 0.2 * gaussian(v, 0.12, 0.1);
    const level = Math.round(clamp(0.012 + softbox + fill + ceiling) * 255), at = (y * width + x) * 4;
    data[at] = data[at + 1] = data[at + 2] = level;data[at + 3] = 255;
  }
  const texture = new THREE.DataTexture(data, width, height, THREE.RGBAFormat, THREE.UnsignedByteType);
  texture.name = 'grayscale-studio-softboxes';
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.mapping = THREE.EquirectangularReflectionMapping;
  texture.needsUpdate = true;
  return texture;
}

function ballMesh(THREE) {
  const geometry = new THREE.SphereGeometry(config.ballDiameterLogical / 2, 48, 32);
  const normal = geometry.getAttribute('normal');
  const light = new THREE.Vector3(-0.6, 0.8, 1.1).normalize();
  const highlight = new THREE.Vector3(-0.3, 0.45, 1).normalize();
  const colors = new Float32Array(normal.count * 3);
  for (let index = 0; index < normal.count; index++) {
    const n = new THREE.Vector3(normal.getX(index), normal.getY(index), normal.getZ(index));
    const diffuse = Math.max(0, n.dot(light));
    const specular = Math.max(0, n.dot(highlight)) ** 22;
    const value = clamp(0.12 + 0.78 * diffuse ** 0.72 + 0.32 * specular);
    const color = gray(THREE, value);
    colors.set([color.r, color.g, color.b], index * 3);
  }
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
    color: 0xffffff, vertexColors: true, toneMapped: false,
    depthWrite: true, depthTest: true,
  }));
  mesh.name = 'orbit-ball';
  return mesh;
}

export function createScene(THREE) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x000000);
  scene.environment = studioEnvironment(THREE);
  scene.environmentIntensity = 0.85;
  const camera = new THREE.OrthographicCamera(-80, 80, 50, -50, 0.1, 400);
  camera.position.set(0, 0, 180);
  camera.lookAt(0, 0, 0);

  const cube = new THREE.Group();
  cube.name = 'glass-cube';
  const optics = Object.freeze({transmission: 1, ior: 1.55, thickness: 22, roughness: 0.19});
  const glassMaterial = new THREE.MeshPhysicalMaterial({
    color: 0xffffff, metalness: 0, ...optics,
    opacity: 1, transparent: false, depthWrite: false, depthTest: true,
    attenuationColor: gray(THREE, 0.96), attenuationDistance: 90,
    envMapIntensity: 0.85, clearcoat: 0.2, clearcoatRoughness: 0.08,
    side: THREE.FrontSide, toneMapped: false,
  });
  glassMaterial.name = 'refractive-frosted-glass';
  const volume = new THREE.Mesh(new THREE.BoxGeometry(config.cubeSideLogical, config.cubeSideLogical,
    config.cubeSideLogical), glassMaterial);
  volume.name = 'glass-volume';cube.add(volume);
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(
    config.cubeSideLogical, config.cubeSideLogical, config.cubeSideLogical)),
  new THREE.LineBasicMaterial({color: gray(THREE, 0.84), transparent: true, opacity: 0.65,
    depthWrite: false, depthTest: true, toneMapped: false}));
  edges.name = 'glass-edges';
  cube.add(edges);
  const ball = ballMesh(THREE);
  // The expanded back-facing shell sits behind the original front-facing
  // sphere, preserving its entire core while writing black depth over glass.
  const outline = new THREE.Mesh(ball.geometry, new THREE.MeshBasicMaterial({
    color: 0x000000, side: THREE.BackSide, depthWrite: true, depthTest: true, toneMapped: false,
  }));
  outline.name = 'ball-outline';
  ball.add(outline);
  let outlineEnabled = true, outlineWeight = 0;
  scene.add(cube, ball);
  scene.userData.calibration = {
    renderColor: 'grayscale before export',
    glass: 'MeshPhysicalMaterial transmission with actual screen-space refracted opaque-buffer sampling and roughness mip filtering.',
    optics,
    intendedPhysicalPixels: {cubeSide: 68, projectedCubeWidth: 100, ballDiameter: 44},
    dither: 'Only exporter ordered quantization, fixed to screen coordinates.',
  };

  function update(time) {
    const t = Number.isFinite(time) ? time : 0;
    const visible = t >= 1 / config.fps;
    cube.visible = ball.visible = visible;
    let frame = t * config.fps - config.loop.startFrame;
    if (Math.abs(frame - Math.round(frame)) < 1e-7) frame = Math.round(frame);
    const progress = ((frame % config.loop.frameCount) + config.loop.frameCount) % config.loop.frameCount / config.loop.frameCount;
    const angle = progress * Math.PI * 2;
    cube.rotation.set(-0.34 + 0.17 * Math.cos(angle), 0.56 + 0.36 * Math.sin(angle),
      0.07 + 0.09 * Math.sin(angle * 2), 'YXZ');
    ball.position.set(config.orbitRadiusLogical * Math.cos(angle),
      config.orbitTiltLogical * Math.sin(angle), config.orbitRadiusLogical * Math.sin(angle));
    // Thicken smoothly while the ball is outside the cube's side silhouette.
    // No shell is drawn behind the glass, so the refracted scene is unchanged.
    const depth = clamp((ball.position.z - 8) / 20);
    outlineWeight = depth * depth * (3 - 2 * depth);
    outline.scale.setScalar(1 + config.outlineWidthLogical * outlineWeight / (config.ballDiameterLogical / 2));
    outline.visible = outlineEnabled && outlineWeight > 0;
    scene.userData.pose = {time: t, phase: !visible ? 'blank' : ball.position.z >= 0 ? 'front' : 'behind',
      progress, angle, ballPosition: ball.position.toArray(), cubeRotation: cube.rotation.toArray(), outlineWeight, loop: config.loop};
  }
  function setOptics(mode = 'normal') {
    if (mode === 'default') mode = 'normal';
    if (mode === 'sharp') mode = 'sharp-refraction';
    if (!['normal', 'no-refraction', 'sharp-refraction'].includes(mode)) throw Error('Unknown optics control: ' + mode);
    // Zero thickness removes the spatial displacement while retaining the same
    // IOR, surface roughness, tint, reflection lighting and render ordering.
    glassMaterial.thickness = mode === 'no-refraction' ? 0 : optics.thickness;
    glassMaterial.roughness = mode === 'sharp-refraction' ? 0 : optics.roughness;
    return {mode, thickness: glassMaterial.thickness, roughness: glassMaterial.roughness, ior: glassMaterial.ior};
  }
  function setOutlineEnabled(enabled = true) {
    outlineEnabled = Boolean(enabled);
    outline.visible = outlineEnabled && outlineWeight > 0;
  }
  update(0);
  return {scene, camera, update, setOptics, setOutlineEnabled};
}
