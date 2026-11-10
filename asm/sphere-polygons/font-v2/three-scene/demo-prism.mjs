// Reuse the approved orbit, optics and foreground contour unchanged. Only the
// closed glass volume and its edge geometry become a triangular prism.
import {config as glassConfig, createScene as createGlassScene} from './demo-glass.mjs';

export const config = Object.freeze({
  ...glassConfig,
  name: 'glass-prism-orbit',
  title: 'Glasprisma med kretsande boll',
  description: 'Ett slutet triangulärt glasprisma vrider sig långsamt medan en stor boll kretsar framför och bakom det. Prismats plana fasetter bryter och delar bilden av bollen. Gråskalebilden dithras först vid bitmapexporten.',
  geometry: 'triangular-prism',
  sourceDependencies: Object.freeze(['./demo-glass.mjs']),
  prismRadiusLogical: 23,
  prismHeightLogical: 34,
  prismRadialSegments: 3,
});

export function createScene(THREE) {
  const world = createGlassScene(THREE);
  const volume = world.scene.getObjectByName('glass-volume');
  const edges = world.scene.getObjectByName('glass-edges');
  // Equal end radii and closed caps give two parallel, congruent triangular
  // ends joined by three rectangular sides. This is not a cone or pyramid.
  const geometry = new THREE.CylinderGeometry(config.prismRadiusLogical, config.prismRadiusLogical,
    config.prismHeightLogical, config.prismRadialSegments, 1, false);
  geometry.name = 'closed-equilateral-triangular-prism';
  volume.geometry.dispose();volume.geometry = geometry;
  edges.geometry.dispose();edges.geometry = new THREE.EdgesGeometry(geometry);
  world.scene.userData.calibration = {...world.scene.userData.calibration,
    geometry: config.geometry, equalEndRadiiLogical: config.prismRadiusLogical,
    heightLogical: config.prismHeightLogical, triangularCaps: 2, rectangularSides: 3,
    inheritedScene: 'demo-glass.mjs'};
  const updateGlass = world.update;
  world.update = time => {
    updateGlass(time);
    world.scene.userData.pose.geometry = config.geometry;
    world.scene.userData.pose.prismRotation = world.scene.userData.pose.cubeRotation;
  };
  world.update(0);
  return world;
}
