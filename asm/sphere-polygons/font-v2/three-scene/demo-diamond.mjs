// A cut, closed glass gem. The approved orbit and foreground contour are reused
// unchanged; broad facet tones carry the shape at the coarse export resolution.
import {config as glassConfig, createScene as createGlassScene} from './demo-glass.mjs';

export const config = Object.freeze({
  ...glassConfig,
  name: 'cut-glass-diamond-orbit',
  title: 'Facetterad glasdiamant med kretsande boll',
  description: 'En stor boll kretsar kring en slipad glasdiamant med platt bord, sluttande krona, bred gördel och spetsig paviljong. Breda fasettreflexer gör formen tydlig, och polerat glas bryter bilden av bollen bakom diamanten.',
  geometry: 'cut-diamond',
  sourceDependencies: Object.freeze(['./demo-glass.mjs']),
  diamond: Object.freeze({sectors: 8, tableRadius: 9, tableY: 22, girdleRadius: 24,
    crownBottomY: 8, girdleBottomY: 6, pointY: -29}),
  diamondOptics: Object.freeze({transmission: 1, ior: 1.55, thickness: 22, roughness: 0.10}),
});

function gray(THREE, value) {
  return new THREE.Color().setRGB(value, value, value, THREE.SRGBColorSpace);
}

function cutGeometry(THREE) {
  const cut = config.diamond;
  const ring = (radius, y) => Array.from({length: cut.sectors}, (_, sector) => {
    const angle = (sector + 0.5) * Math.PI * 2 / cut.sectors;
    return new THREE.Vector3(radius * Math.cos(angle), y, radius * Math.sin(angle));
  });
  const table = ring(cut.tableRadius, cut.tableY);
  const girdleTop = ring(cut.girdleRadius, cut.crownBottomY);
  const girdleBottom = ring(cut.girdleRadius, cut.girdleBottomY);
  const tip = new THREE.Vector3(0, cut.pointY, 0), tableCenter = new THREE.Vector3(0, cut.tableY, 0);
  const geometry = new THREE.BufferGeometry(), positions = [];
  function face(points, material) {
    const a = new THREE.Vector3().subVectors(points[1], points[0]);
    const b = new THREE.Vector3().subVectors(points[2], points[0]);
    const center = points.reduce((sum, point) => sum.add(point), new THREE.Vector3()).multiplyScalar(1 / points.length);
    if (a.cross(b).dot(center) < 0) points = [...points].reverse();
    const first = positions.length / 3;
    for (let vertex = 1; vertex < points.length - 1; vertex++) {
      for (const point of [points[0], points[vertex], points[vertex + 1]]) positions.push(point.x, point.y, point.z);
    }
    geometry.addGroup(first, positions.length / 3 - first, material);
  }
  for (let sector = 0; sector < cut.sectors; sector++) {
    const next = (sector + 1) % cut.sectors;
    face([tableCenter, table[sector], table[next]], 0);
    face([table[sector], girdleTop[sector], girdleTop[next], table[next]], 1 + sector);
    face([girdleTop[sector], girdleBottom[sector], girdleBottom[next], girdleTop[next]], 9 + sector);
    face([girdleBottom[sector], tip, girdleBottom[next]], 17 + sector);
  }
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  // Each face has its own vertices. Crown/girdle quad triangles share a plane,
  // so flat normals expose the cut without introducing a diagonal highlight.
  geometry.computeVertexNormals();geometry.computeBoundingBox();geometry.computeBoundingSphere();
  geometry.name = 'closed-eight-sector-cut-diamond';
  geometry.userData = {cut: 'flat table, sloped crown, narrow girdle, pointed pavilion', sectors: 8,
    triangleCounts: {table: 8, crown: 16, girdle: 16, pavilion: 8, total: 48},
    polygonCounts: {table: 1, crown: 8, girdle: 8, pavilion: 8},
    expectedWeldedVertices: 26, ringDimensions: cut, flatFaceNormals: true};
  return geometry;
}

export function createScene(THREE) {
  const world = createGlassScene(THREE);
  const volume = world.scene.getObjectByName('glass-volume'), edges = world.scene.getObjectByName('glass-edges');
  const original = volume.material;
  const facetFloor = [0.46,
    0.25, 0.38, 0.18, 0.32, 0.15, 0.29, 0.20, 0.35,
    0.40, 0.40, 0.40, 0.40, 0.40, 0.40, 0.40, 0.40,
    0.12, 0.23, 0.15, 0.29, 0.10, 0.20, 0.14, 0.25];
  const materials = facetFloor.map((floor, index) => {
    const material = original.clone();
    material.name = index === 0 ? 'diamond-table' : index < 9 ? 'diamond-crown-' + (index - 1)
      : index < 17 ? 'diamond-girdle-' + (index - 9) : 'diamond-pavilion-' + (index - 17);
    Object.assign(material, config.diamondOptics);
    material.emissive.copy(gray(THREE, floor));
    material.emissiveIntensity = 1;
    material.envMapIntensity = 1.15;
    material.userData = {facetFloorSRGB: floor, role: 'broad reflected studio tone under physical transmission'};
    return material;
  });
  const geometry = cutGeometry(THREE);
  volume.geometry.dispose();volume.geometry = geometry;volume.material = materials;original.dispose();
  edges.geometry.dispose();edges.geometry = new THREE.EdgesGeometry(geometry, 12);
  edges.material = edges.material.clone();edges.material.opacity = 0.22;
  world.scene.userData.calibration = {...world.scene.userData.calibration,
    geometry: config.geometry, optics: config.diamondOptics, cut: geometry.userData,
    facetFloorsSRGB: facetFloor, wireEdgesAreSecondary: true, inheritedScene: 'demo-glass.mjs'};
  const updateGlass = world.update;
  world.update = time => {
    updateGlass(time);
    world.scene.userData.pose.geometry = config.geometry;
    world.scene.userData.pose.diamondRotation = world.scene.userData.pose.cubeRotation;
  };
  world.setOptics = (mode = 'default') => {
    if (mode === 'normal') mode = 'default';
    if (mode === 'sharp-refraction') mode = 'sharp';
    if (!['default', 'no-refraction', 'sharp'].includes(mode)) throw Error('Unknown diamond optics control: ' + mode);
    for (const material of materials) {
      material.thickness = mode === 'no-refraction' ? 0 : config.diamondOptics.thickness;
      material.roughness = mode === 'sharp' ? 0 : config.diamondOptics.roughness;
    }
    return {mode, thickness: materials[0].thickness, roughness: materials[0].roughness, ior: materials[0].ior};
  };
  world.update(0);
  return world;
}
