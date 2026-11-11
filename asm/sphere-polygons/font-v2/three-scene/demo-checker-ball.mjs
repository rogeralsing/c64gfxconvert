// The accepted pure black/white checker material and sphere geometry, with a
// stationary PAL-correct camera and a periodic rotation instead of the morph.
import {createScene as createSphereScene} from './demo.mjs';
import {fileURLToPath} from 'node:url';

export const config = Object.freeze({
  name: 'pal-checker-ball',
  title: 'Schackboll med 14 × 7 rutor',
  description: 'En stor svartvit schackboll roterar kring sin egen lutande axel med en liten periodisk rörelse.',
  width: 160, height: 100, fps: 25, durationSeconds: 97 / 25,
  loop: Object.freeze({startFrame: 1, frameCount: 96}),
  checkerColumns: 14, checkerRows: 7,
  displayPixelAspect: 59 / 63,
  sphereRadius: 44,
  sourceDependencies: [fileURLToPath(new URL('./demo.mjs', import.meta.url))],
  phaseLabels: {blank: 'Tom startbild', sphere: 'Roterande schackboll'},
});

export function createScene(THREE) {
  const world = createSphereScene(THREE);
  // This initializes the original geometry at morph=0. Subsequent updates use
  // only the loop below, so entrance animation and cube deformation never run.
  world.update(1 / config.fps);
  const mesh = world.scene.getObjectByName('morphing-sphere-cube');
  if (!mesh) throw new Error('The accepted checker sphere is missing.');
  mesh.name = 'pal-checker-ball';
  mesh.position.set(0, 0, 0);
  mesh.scale.setScalar(config.sphereRadius / 24);
  const extent = 50;
  const aspect = config.width / config.height * config.displayPixelAspect;
  Object.assign(world.camera, {left: -extent * aspect, right: extent * aspect, top: extent, bottom: -extent});
  world.camera.updateProjectionMatrix();
  const base = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.56, 0, 0.24, 'XYZ'));
  const wobble = new THREE.Quaternion(), spin = new THREE.Quaternion();
  const axis = new THREE.Vector3(0, 1, 0);
  world.scene.userData.calibration = {
    checkerColumns: 14, checkerRows: 7, expectedRGBLevels: [0, 255], unlit: true,
    displayPixelAspect: config.displayPixelAspect, displayVideoStandard: 'PAL',
    cameraAspectRule: 'horizontal span / vertical span = raster aspect * display pixel aspect',
    rasterAspect: config.width / config.height, displayAspect: aspect,
    physicalDiameterY: config.sphereRadius * 4,
    symmetryTurnRadians: 4 * Math.PI / config.checkerColumns,
    rotationComposition: 'fixedTilt * periodicWobble(progress) * localYSpin(unwrappedProgress)',
  };
  function update(time) {
    const t = Number.isFinite(time) ? time : 0;
    mesh.visible = t >= 1 / config.fps;
    let frame = t * config.fps - config.loop.startFrame;
    if (Math.abs(frame - Math.round(frame)) < 1e-7) frame = Math.round(frame);
    const progress = frame / config.loop.frameCount;
    wobble.setFromEuler(new THREE.Euler(0.07 * Math.sin(progress * 2 * Math.PI),
      0.04 * Math.sin(progress * 2 * Math.PI), 0.05 * (Math.cos(progress * 2 * Math.PI) - 1), 'XYZ'));
    spin.setFromAxisAngle(axis, progress * 4 * Math.PI / config.checkerColumns);
    mesh.quaternion.copy(base).multiply(wobble).multiply(spin);
    world.scene.userData.pose = {time: t, phase: mesh.visible ? 'sphere' : 'blank',
      progress, orientation: mesh.quaternion.toArray(), loop: config.loop};
  }
  update(0);
  return {scene: world.scene, camera: world.camera, update};
}
