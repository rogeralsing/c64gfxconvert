// One opaque, filled object. A fixed light/dark facet split keeps one broad,
// visible white side on each arm throughout the complete rotation loop.
export const config = Object.freeze({
  name: 'solid-six-point-star',
  title: 'Solid tredimensionell stjärna med långa spetsar',
  description: 'En kubs sex sidor dras ut till långa pyramidspetsar. Stjärnan roterar med helt fyllda svarta och vita fasetter mot svart bakgrund.',
  width: 160, height: 100, fps: 25, durationSeconds: 161 / 25,
  loop: Object.freeze({startFrame: 1, frameCount: 160}),
  geometry: 'solid-stellated-cube-star',
  star: Object.freeze({cubeHalfExtent: 8.5, tipDistance: 40, axisTips: 6, triangles: 24}),
  phaseLabels: {blank: 'Tom startbild', star: 'Roterande solid stjärna'},
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
    shape: config.geometry, ...config.star, expectedWeldedVertices: 14, expectedEdges: 36,
    triangleCount: 24, nonconvex: true, armRatio: distance / h, flatFaceNormals: true};
  return geometry;
}

export function createScene(THREE) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x000000);
  const camera = new THREE.OrthographicCamera(-80, 80, 50, -50, 0.1, 400);
  camera.position.set(0, 0, 180);camera.lookAt(0, 0, 0);
  const geometry = makeGeometry(THREE);
  const materials = Array.from({length: 24}, (_, index) => {
    const material = new THREE.MeshBasicMaterial({color: 0xffffff, depthWrite: true, depthTest: true,
      side: THREE.FrontSide, toneMapped: false});
    material.name = 'solid-binary-facet-' + index;
    return material;
  });
  const mesh = new THREE.Mesh(geometry, materials);mesh.name = 'solid-star';scene.add(mesh);
  const diagonal = new THREE.Vector3(1, 1, 1).normalize();
  const orientation = new THREE.Quaternion().setFromUnitVectors(diagonal, new THREE.Vector3(0, 0, 1));
  const roll = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), -Math.PI / 12);
  const base = roll.multiply(orientation), oscillation = new THREE.Quaternion();
  const light = new THREE.Vector3(-0.65, 0.85, 1.05).normalize();
  const normals = geometry.getAttribute('normal');
  const localNormals = Array.from({length: 24}, (_, index) => new THREE.Vector3().fromBufferAttribute(normals, index * 3));
  function orient(quaternion, angle) {
    oscillation.setFromEuler(new THREE.Euler(0.26 * Math.cos(angle), 0.34 * Math.sin(angle),
      0.12 * Math.sin(angle * 2), 'XYZ'));
    quaternion.copy(base).multiply(oscillation);
  }
  const minimumFacing = new Float64Array(24).fill(1), lighting = new Float64Array(24);
  const probe = new THREE.Quaternion(), normal = new THREE.Vector3();
  for (let frame = 0; frame < config.loop.frameCount; frame++) {
    orient(probe, frame / config.loop.frameCount * Math.PI * 2);
    localNormals.forEach((local, index) => {
      normal.copy(local).applyQuaternion(probe);
      minimumFacing[index] = Math.min(minimumFacing[index], normal.z);
      lighting[index] += normal.dot(light);
    });
  }
  const whiteFaces = [];
  for (let pyramid = 0; pyramid < 6; pyramid++) {
    const candidates = [0, 1, 2, 3].map(face => pyramid * 4 + face);
    candidates.sort((a, b) => minimumFacing[b] - minimumFacing[a] || lighting[b] - lighting[a]);
    if (minimumFacing[candidates[0]] <= 0) throw Error('An arm has no consistently visible white facet');
    whiteFaces.push(candidates[0]);
  }
  materials.forEach((material, index) => material.color.setScalar(whiteFaces.includes(index) ? 1 : 0));
  scene.userData.calibration = {geometry: geometry.userData,
    fill: 'Opaque black/white entire triangles; no textures, transparency, glass, line strokes or intermediate gray.',
    lightDirectionWorld: light.toArray(),
    binaryLightRule: 'Fixed white facet per pyramid maximizes minimum camera-facing area over all loop poses; other facets are black.',
    fixedWhiteFacets: whiteFaces, minimumWhiteFacetCameraDot: whiteFaces.map(index => minimumFacing[index]),
    expectedRGBLevels: [0, 255]};

  function update(time) {
    const t = Number.isFinite(time) ? time : 0;
    mesh.visible = t >= 1 / config.fps;
    let frame = t * config.fps - config.loop.startFrame;
    if (Math.abs(frame - Math.round(frame)) < 1e-7) frame = Math.round(frame);
    const progress = ((frame % config.loop.frameCount) + config.loop.frameCount) % config.loop.frameCount / config.loop.frameCount;
    const angle = progress * Math.PI * 2;
    orient(mesh.quaternion, angle);
    const whiteFacets = whiteFaces.length;
    scene.userData.pose = {time: t, phase: mesh.visible ? 'star' : 'blank', progress, angle,
      orientation: mesh.quaternion.toArray(), whiteFacets, loop: config.loop};
  }
  update(0);
  return {scene, camera, update};
}
