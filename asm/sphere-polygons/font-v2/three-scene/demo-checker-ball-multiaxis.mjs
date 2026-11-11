// The original checker sphere, now tumbling through full turns on two axes.
// Keep the accepted geometry, material, framing and PAL pixel calibration.
import {createScene as createCheckerScene, config as checkerConfig} from './demo-checker-ball.mjs';
import {fileURLToPath} from 'node:url';

export const config = Object.freeze({
  ...checkerConfig,
  name: 'pal-checker-ball-multiaxis',
  title: 'Schackboll som roterar kring flera axlar',
  description: 'En stor svartvit schackboll gör fulla rotationer kring två axlar och snurrar samtidigt kring sin egen axel.',
  sourceDependencies: [
    fileURLToPath(new URL('./demo-checker-ball.mjs', import.meta.url)),
    fileURLToPath(new URL('./demo.mjs', import.meta.url)),
  ],
});

export function createScene(THREE) {
  const world = createCheckerScene(THREE);
  const mesh = world.scene.getObjectByName('pal-checker-ball');
  if (!mesh) throw new Error('The accepted checker sphere is missing.');
  mesh.name = 'pal-checker-ball-multiaxis';
  const base = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.56, 0, 0.24, 'XYZ'));
  const turnX = new THREE.Quaternion(), turnZ = new THREE.Quaternion(), spin = new THREE.Quaternion();
  const axisX = new THREE.Vector3(1, 0, 0), axisY = new THREE.Vector3(0, 1, 0), axisZ = new THREE.Vector3(0, 0, 1);
  Object.assign(world.scene.userData.calibration, {
    rotationComposition: 'fixedTilt * Rx(2π*progress) * Rz(2π*progress) * Ry(4π*progress/14)',
    fullTurnsXPerLoop: 1, fullTurnsZPerLoop: 1,
    localYCheckerColumnsPerLoop: 2,
  });
  function update(time) {
    const t = Number.isFinite(time) ? time : 0;
    mesh.visible = t >= 1 / config.fps;
    let frame = t * config.fps - config.loop.startFrame;
    if (Math.abs(frame - Math.round(frame)) < 1e-7) frame = Math.round(frame);
    const progress = frame / config.loop.frameCount;
    turnX.setFromAxisAngle(axisX, progress * 2 * Math.PI);
    turnZ.setFromAxisAngle(axisZ, progress * 2 * Math.PI);
    spin.setFromAxisAngle(axisY, progress * 4 * Math.PI / config.checkerColumns);
    mesh.quaternion.copy(base).multiply(turnX).multiply(turnZ).multiply(spin);
    world.scene.userData.pose = {time: t, phase: mesh.visible ? 'sphere' : 'blank',
      progress, orientation: mesh.quaternion.toArray(), loop: config.loop};
  }
  update(0);
  return {scene: world.scene, camera: world.camera, update};
}
