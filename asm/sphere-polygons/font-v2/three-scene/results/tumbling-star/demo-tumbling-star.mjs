// Full compound rotation with paint fixed to the object. No facet color changes
// occur during playback; changing visibility comes entirely from 3D occlusion.
import {config as solidConfig, createScene as createSolidScene} from './demo-solid-star.mjs';

export const config = Object.freeze({
  ...solidConfig,
  name: 'tumbling-solid-star',
  title: 'Solid stjärna som roterar kring alla tre axlar',
  description: 'Den solida stjärnan med långa spetsar tumlar ett helt varv kring X, två kring Y och ett kring Z. Svarta och vita fasetter sitter fast på objektet och visar dess fram- och baksidor under hela den sömlösa rotationen.',
  durationSeconds: 241 / 25,
  loop: Object.freeze({startFrame: 1, frameCount: 240}),
  sourceDependencies: Object.freeze(['./demo-solid-star.mjs']),
  rotationOrder: 'XYZ',
  turnsPerLoop: Object.freeze([1, 2, 1]),
  phaseRadians: Object.freeze([0.18, 0.31, 0.07]),
});

export function createScene(THREE) {
  const world = createSolidScene(THREE);
  const mesh = world.scene.getObjectByName('solid-star');
  // The black facets form antipodal pairs. The remaining 18 white facets also
  // cover opposing directions, unlike a palette chosen for one camera view.
  const blackFaces = [0, 6, 8, 14, 16, 22];
  const whiteFaces = [];
  mesh.material.forEach((material, index) => {
    const white = !blackFaces.includes(index);
    material.color.setScalar(white ? 1 : 0);
    material.name = 'tumbling-fixed-' + (white ? 'white-' : 'black-') + index;
    if (white) whiteFaces.push(index);
  });
  const direction = new THREE.Vector3(1, 1, 1).normalize();
  const orientation = new THREE.Quaternion().setFromUnitVectors(direction, new THREE.Vector3(0, 0, 1));
  const base = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), -Math.PI / 12).multiply(orientation);
  const tumble = new THREE.Quaternion();
  const {fixedWhiteFacets, minimumWhiteFacetCameraDot, binaryLightRule, lightDirectionWorld, ...calibration} =
    world.scene.userData.calibration;
  world.scene.userData.calibration = {...calibration,
    binaryPaintRule: 'Fixed object-space paint: one black facet per pyramid in antipodal pairs, all remaining facets white.',
    whiteFacetIndices: whiteFaces, blackFacetIndices: blackFaces, facetColorsConstant: true,
    rotationOrder: config.rotationOrder, turnsPerLoop: config.turnsPerLoop,
    phaseRadians: config.phaseRadians, baseOrientation: base.toArray(),
    rotation: 'base * Qx(theta+phaseX) * Qy(2*theta+phaseY) * Qz(theta+phaseZ)'};

  world.update = time => {
    const t = Number.isFinite(time) ? time : 0;
    mesh.visible = t >= 1 / config.fps;
    let unwrappedFrame = t * config.fps - config.loop.startFrame;
    if (Math.abs(unwrappedFrame - Math.round(unwrappedFrame)) < 1e-7) unwrappedFrame = Math.round(unwrappedFrame);
    const progress = ((unwrappedFrame % config.loop.frameCount) + config.loop.frameCount) % config.loop.frameCount / config.loop.frameCount;
    const theta = progress * Math.PI * 2;
    const eulerWrapped = config.turnsPerLoop.map((turns, axis) => theta * turns + config.phaseRadians[axis]);
    const unwrappedTheta = unwrappedFrame / config.loop.frameCount * Math.PI * 2;
    const eulerUnwrapped = config.turnsPerLoop.map((turns, axis) => unwrappedTheta * turns + config.phaseRadians[axis]);
    tumble.setFromEuler(new THREE.Euler(...eulerWrapped, config.rotationOrder));
    mesh.quaternion.copy(base).multiply(tumble);
    world.scene.userData.pose = {time: t, phase: mesh.visible ? 'star' : 'blank', progress, theta,
      eulerUnwrapped, eulerWrapped, rotationOrder: config.rotationOrder,
      turnsPerLoop: config.turnsPerLoop, baseOrientation: base.toArray(),
      orientation: mesh.quaternion.toArray(), whiteFacets: whiteFaces.length, loop: config.loop};
  };
  world.update(0);
  return world;
}
