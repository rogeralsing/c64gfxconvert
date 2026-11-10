// A stellated cube: each of the six original square faces becomes a pyramid.
// Internal cube faces are omitted, leaving one closed nonconvex glass surface.
import {config as diamondConfig, createScene as createDiamondScene} from './demo-diamond.mjs';

export const config = Object.freeze({
  ...diamondConfig,
  name: 'six-point-glass-star-orbit',
  title: 'Tredimensionell glasstjärna med kretsande boll',
  description: 'En kubs sex sidor är utdragna till sex pyramidspetsar längs rummets tre axlar. Den slutna, konkava glasstjärnan visar breda polerade fasetter medan en stor boll kretsar framför och bakom den.',
  geometry: 'stellated-cube-star',
  sourceDependencies: Object.freeze(['./demo-diamond.mjs', './demo-glass.mjs']),
  star: Object.freeze({cubeHalfExtent: 10, tipDistance: 30, axisTips: 6, triangles: 24}),
});

function starGeometry(THREE) {
  const {cubeHalfExtent: h, tipDistance: distance} = config.star;
  const geometry = new THREE.BufferGeometry(), positions = [];
  function triangle(points, material) {
    const a = new THREE.Vector3().subVectors(points[1], points[0]);
    const b = new THREE.Vector3().subVectors(points[2], points[0]);
    const center = points.reduce((sum, point) => sum.add(point), new THREE.Vector3()).multiplyScalar(1 / 3);
    if (a.cross(b).dot(center) < 0) points = [points[0], points[2], points[1]];
    const first = positions.length / 3;
    for (const point of points) positions.push(point.x, point.y, point.z);
    geometry.addGroup(first, 3, material);
  }
  let faceIndex = 0;
  for (let axis = 0; axis < 3; axis++) for (const sign of [-1, 1]) {
    const u = (axis + 1) % 3, v = (axis + 2) % 3;
    const apex = new THREE.Vector3().setComponent(axis, sign * distance);
    const square = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([su, sv]) =>
      new THREE.Vector3().setComponent(axis, sign * h).setComponent(u, su * h).setComponent(v, sv * h));
    for (let edge = 0; edge < 4; edge++) {
      triangle([square[edge], square[(edge + 1) % 4], apex], faceIndex * 4 + edge);
    }
    faceIndex++;
  }
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.computeVertexNormals();geometry.computeBoundingBox();geometry.computeBoundingSphere();
  geometry.name = 'closed-six-pyramid-stellated-cube';
  geometry.userData = {construction: 'six square cube faces replaced by four-triangle pyramids; no internal cube faces',
    shape: config.geometry, cubeHalfExtent: h, tipDistance: distance, axisTips: 6,
    expectedWeldedVertices: 14, expectedEdges: 36, triangleCount: 24,
    pyramidTriangleCounts: [4, 4, 4, 4, 4, 4], nonconvex: true,
    concaveJoinCondition: 'tipDistance > 2*cubeHalfExtent', flatFaceNormals: true};
  return geometry;
}

export function createScene(THREE) {
  const world = createDiamondScene(THREE);
  const volume = world.scene.getObjectByName('glass-volume');
  const edges = world.scene.getObjectByName('glass-edges');
  const group = world.scene.getObjectByName('glass-cube');
  const geometry = starGeometry(THREE);
  volume.geometry.dispose();volume.geometry = geometry;
  edges.geometry.dispose();edges.geometry = new THREE.EdgesGeometry(geometry, 12);
  const tones = [0.20, 0.36, 0.14, 0.28];
  volume.material.forEach((material, index) => {
    const face = Math.floor(index / 4), tone = tones[(index + face) % tones.length];
    material.emissive.setRGB(tone, tone, tone, THREE.SRGBColorSpace);
    // Concave spikes can put several front-facing facets on the same ray.
    // Keep the nearest surface while it refracts the opaque ball buffer.
    material.depthWrite = true;
    material.name = 'star-polished-facet-' + index;
    material.userData = {facetFloorSRGB: tone, role: 'broad reflected studio tone under physical transmission'};
  });
  // Looking near a body diagonal separates the three opposing axis pairs into
  // six projected rays. A modest local oscillation retains those concave gaps.
  const diagonal = new THREE.Vector3(1, 1, 1).normalize();
  const orientation = new THREE.Quaternion().setFromUnitVectors(diagonal, new THREE.Vector3(0, 0, 1));
  const roll = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), -Math.PI / 12);
  const base = roll.multiply(orientation);
  const oscillation = new THREE.Quaternion();
  const updateDiamond = world.update;
  world.update = time => {
    updateDiamond(time);
    const angle = world.scene.userData.pose.angle;
    oscillation.setFromEuler(new THREE.Euler(0.20 * Math.cos(angle), 0.26 * Math.sin(angle),
      0.10 * Math.sin(angle * 2), 'XYZ'));
    group.quaternion.copy(base).multiply(oscillation);
    world.scene.userData.pose.geometry = config.geometry;
    world.scene.userData.pose.cubeRotation = group.rotation.toArray();
    world.scene.userData.pose.starOrientation = group.quaternion.toArray();
  };
  world.scene.userData.calibration = {...world.scene.userData.calibration,
    geometry: config.geometry, star: geometry.userData, inheritedScene: 'demo-diamond.mjs',
    view: 'near body diagonal, modest closed local oscillation', facetFloorsSRGB: tones};
  world.update(0);
  return world;
}
