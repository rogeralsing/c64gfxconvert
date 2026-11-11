// The flagship: one very large six-tip star, spinning continuously about its
// own three-fold symmetry axis. One symmetry turn (120 degrees) per 96-frame
// loop renders pixel-identical screens at both ends, so the film loops
// seamlessly forever while the visible revolution takes 288 frames (11.52 s).
export const config = Object.freeze({
  name: 'flagship-six-point-star',
  title: 'Flaggskeppsstjärna: mycket stor, kontinuerlig rotation',
  description: 'En nästan skärmfyllande sex-tippad stjärna med långa armar roterar kontinuerligt kring sin trefaldiga symmetriaxel. Fasetterna tonas i sex grånivåer efter ljusriktningen; 120 grader per 96-bilders loop gör filmen oändlig utan synlig fog.',
  width: 160, height: 100, fps: 25, durationSeconds: 97 / 25,
  loop: Object.freeze({startFrame: 1, frameCount: 96}),
  geometry: 'solid-stellated-cube-star',
  star: Object.freeze({cubeHalfExtent: 8.5, tipDistance: 54, axisTips: 6, triangles: 24,
    cameraStretchX: 1.6, cameraHalfExtent: 53, tiltRadians: 0.30,
    shadeLevels: 6, shadeGrays: Object.freeze([0, 51, 102, 153, 204, 255]), spinTurnsPerLoop: 1 / 3,
    spinAxisModelSpace: Object.freeze([1, 1, 1])}),
  phaseLabels: {blank: 'Tom startbild', star: 'Roterande flaggskeppsstjärna'},
});

function makeGeometry(THREE) {
  const {cubeHalfExtent: h, tipDistance: distance} = config.star;
  const geometry = new THREE.BufferGeometry(), positions = [];
  let material = 0;
  for (let axis = 0; axis < 3; axis++) for (const sign of [-1, 1]) {
    const u = (axis + 1) % 3, v = (axis + 2) % 3;
    const apex = new THREE.Vector3().setComponent(axis, sign * distance);
    const square = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([su, sv]) =>
      new THREE.Vector3().setComponent(axis, sign * h).setComponent(u, su * h).setComponent(v, sv * h));
    for (let edge = 0; edge < 4; edge++) {
      let points = [square[edge], square[(edge + 1) % 4], apex];
      const a = new THREE.Vector3().subVectors(points[1], points[0]);
      const b = new THREE.Vector3().subVectors(points[2], points[0]);
      const center = points.reduce((sum, point) => sum.add(point), new THREE.Vector3()).multiplyScalar(1 / 3);
      if (a.cross(b).dot(center) < 0) points = [points[0], points[2], points[1]];
      const first = positions.length / 3;
      for (const point of points) positions.push(point.x, point.y, point.z);
      geometry.addGroup(first, 3, material++);
    }
  }
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.computeVertexNormals();geometry.computeBoundingBox();geometry.computeBoundingSphere();
  geometry.name = 'closed-long-arm-solid-stellated-cube';
  geometry.userData = {construction: 'six square cube faces replaced by four-triangle pyramids, no internal cube faces',
    shape: config.geometry, cubeHalfExtent: h, tipDistance: distance, axisTips: 6,
    expectedWeldedVertices: 14, expectedEdges: 36, triangleCount: 24, nonconvex: true,
    armRatio: distance / h, flatFaceNormals: true};
  return geometry;
}

export function createScene(THREE) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x000000);
  // Screen-space anamorphic view: a square frustum stretched onto the
  // 320x200 raster widens the projection by 1.6x at every rotation angle
  // (unlike a mesh scale, which would rotate the wide tips into the border).
  const extent = config.star.cameraHalfExtent;
  const camera = new THREE.OrthographicCamera(-extent, extent, extent, -extent, 0.1, 400);
  camera.position.set(0, 0, 180);camera.lookAt(0, 0, 0);
  const geometry = makeGeometry(THREE);
  const materials = Array.from({length: 24}, (_, index) => {
    const material = new THREE.MeshBasicMaterial({color: 0xffffff, depthWrite: true, depthTest: true,
      side: THREE.FrontSide, toneMapped: false});
    material.name = 'solid-shaded-facet-' + index;
    return material;
  });
  const mesh = new THREE.Mesh(geometry, materials);mesh.name = 'solid-star';scene.add(mesh);
  // The star's six tips point along the cube axes; its three-fold symmetry
  // axis is the (1,1,1) diagonal. Map that axis onto the view direction, then
  // tilt it so the pyramid facets stay visible throughout the spin.
  const diagonal = new THREE.Vector3(...config.star.spinAxisModelSpace).normalize();
  const toView = new THREE.Quaternion().setFromUnitVectors(diagonal, new THREE.Vector3(0, 0, 1));
  const tilt = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), config.star.tiltRadians);
  const base = new THREE.Quaternion().multiplyQuaternions(tilt, toView);
  const spin = new THREE.Quaternion(), wobble = new THREE.Quaternion();
  const light = new THREE.Vector3(-0.55, 0.75, 1.1).normalize();
  const normals = geometry.getAttribute('normal');
  const localNormals = Array.from({length: 24}, (_, index) => new THREE.Vector3().fromBufferAttribute(normals, index * 3));
  function orient(quaternion, progress) {
    spin.setFromAxisAngle(diagonal, progress * Math.PI * 2 * config.star.spinTurnsPerLoop);
    wobble.setFromEuler(new THREE.Euler(0.07 * Math.sin(progress * Math.PI * 2),
      0.05 * Math.cos(progress * Math.PI * 2), 0.03 * Math.sin(progress * Math.PI * 4), 'XYZ'));
    // Keep the symmetry rotation rightmost: after one period the transform is
    // the initial pose followed by a model-space symmetry of the entire star.
    quaternion.copy(base).multiply(wobble).multiply(spin);
  }
  // Facet shading: each facet's gray is a pure function of its rotated normal
  // and the fixed world light, quantized to config.star.shadeGrays. At the
  // loop boundary the 120-degree spin maps every facet onto an identical
  // facet, so the tone pattern returns exactly.
  const grays = config.star.shadeGrays;
  const probe = new THREE.Quaternion(), normal = new THREE.Vector3();
  function toneFor(index, poseQuaternion) {
    normal.copy(localNormals[index]).applyQuaternion(poseQuaternion);
    const facing = normal.dot(light);
    const level = Math.round((facing * 0.5 + 0.5) * (grays.length - 1));
    return grays[Math.max(0, Math.min(grays.length - 1, level))] / 255;
  }
  scene.userData.calibration = {geometry: geometry.userData,
    fill: 'Opaque flat-shaded facets in six exact gray levels; no textures, transparency, glass or line strokes.',
    lightDirectionWorld: light.toArray(),
    shadingRule: 'Facet gray = shadeGrays[round((normalWorld.dot(light)*0.5+0.5)*(shadeLevels-1))], recomputed every frame from the declared fixed light.',
    shadeLevels: config.star.shadeLevels, shadeGrays: grays,
    spinTurnsPerLoop: config.star.spinTurnsPerLoop, spinAxisModelSpace: diagonal.toArray(),
    rotationComposition: 'base * periodicWobble(progress) * diagonalSpin(unwrappedProgress)',
    symmetryTurn: '120-degree rotation maps the star onto itself',
    cameraStretchX: config.star.cameraStretchX, cameraHalfExtent: config.star.cameraHalfExtent,
    expectedRGBLevels: grays};

  function update(time) {
    const t = Number.isFinite(time) ? time : 0;
    mesh.visible = t >= 1 / config.fps;
    let frame = t * config.fps - config.loop.startFrame;
    if (Math.abs(frame - Math.round(frame)) < 1e-7) frame = Math.round(frame);
    // Leave the spin unwrapped. Endpoint renders therefore prove the actual
    // 120/240-degree symmetry instead of resetting the pose before checking it.
    const progress = frame / config.loop.frameCount;
    orient(mesh.quaternion, progress);
    for (let index = 0; index < materials.length; index++) {
      const gray = mesh.visible ? toneFor(index, mesh.quaternion) : 0;
      // Declare the tone in sRGB so the rendered pixel equals the declared
      // 0..255 level; the renderer converts to linear working color itself.
      if (THREE.SRGBColorSpace !== undefined) materials[index].color.setRGB(gray, gray, gray, THREE.SRGBColorSpace);
      else materials[index].color.setScalar(gray);
    }
    scene.userData.pose = {time: t, phase: mesh.visible ? 'star' : 'blank', progress,
      spinRadians: progress * Math.PI * 2 * config.star.spinTurnsPerLoop,
      orientation: mesh.quaternion.toArray(), shadedFacets: materials.length, loop: config.loop};
  }
  update(0);
  return {scene, camera, update};
}
