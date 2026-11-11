// Freeze the approved cube's full grayscale state; only its orientation moves.
// The exporter applies screen-anchored ordered dithering to the face gradients.
import {config as grayConfig, createScene as createGrayScene} from './demo-dither.mjs';
import {fileURLToPath} from 'node:url';

export const config = Object.freeze({
  ...grayConfig,
  name: 'pal-dithered-cube-loop',
  title: 'Roterande kub med dithrade sidgradienter',
  description: 'Den godkända kubens kontinuerliga sidgradienter roterar kring tre axlar i en sluten loop.',
  width: 160, height: 100, fps: 25, durationSeconds: 97 / 25,
  loop: Object.freeze({startFrame: 1, frameCount: 96}),
  displayPixelAspect: 59 / 63,
  cubeHalfSide: 24,
  sourceDependencies: [
    fileURLToPath(new URL('./demo-dither.mjs', import.meta.url)),
    fileURLToPath(new URL('./demo.mjs', import.meta.url)),
  ],
  phaseLabels: {blank: 'Tom startbild', gray: 'Roterande kub med sidgradienter'},
});

export function createScene(THREE) {
  const world = createGrayScene(THREE);
  world.update(6); // gray.fade(1): white texture, full affine vertex gradients.
  const mesh = world.scene.getObjectByName('fixed-gray-cube');
  const original = world.scene.getObjectByName('morphing-sphere-cube');
  if (!mesh || !original) throw new Error('The approved gradient cube is missing.');
  original.visible = false;
  mesh.geometry.computeBoundingBox();
  const size = mesh.geometry.boundingBox.getSize(new THREE.Vector3());
  const originalHalfSide = Math.max(size.x, size.y, size.z) / 2;
  if (!(originalHalfSide > 0) || Math.max(size.x, size.y, size.z) - Math.min(size.x, size.y, size.z) > 1e-5)
    throw new Error('The approved geometry must be a cube.');
  mesh.position.set(0, 0, 0);
  mesh.scale.setScalar(config.cubeHalfSide / originalHalfSide);
  const extent = 50;
  const aspect = config.width / config.height * config.displayPixelAspect;
  Object.assign(world.camera, {left: -extent * aspect, right: extent * aspect, top: extent, bottom: -extent});
  world.camera.updateProjectionMatrix();
  const base = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.42, 0.33, 0.17, 'XYZ'));
  const turnX = new THREE.Quaternion(), turnY = new THREE.Quaternion(), turnZ = new THREE.Quaternion();
  const axisX = new THREE.Vector3(1, 0, 0), axisY = new THREE.Vector3(0, 1, 0), axisZ = new THREE.Vector3(0, 0, 1);
  world.scene.userData.calibration = {
    grayscale: true, affineFaceGradients: true, checkerTextureFullyRemoved: true,
    originalHidden: true, grayFade: 1, cubeHalfSide: config.cubeHalfSide,
    originalHalfSide, displayPixelAspect: config.displayPixelAspect, displayVideoStandard: 'PAL',
    rotationComposition: 'fixedTilt * Rx(2πt) * Ry(2πt) * Rz(2πt)',
    grayFaceRangesSRGB: config.grayFaceRangesSRGB,
  };
  function update(time) {
    const t = Number.isFinite(time) ? time : 0;
    mesh.visible = t >= 1 / config.fps;
    let frame = t * config.fps - config.loop.startFrame;
    if (Math.abs(frame - Math.round(frame)) < 1e-7) frame = Math.round(frame);
    const progress = frame / config.loop.frameCount;
    turnX.setFromAxisAngle(axisX, progress * 2 * Math.PI);
    turnY.setFromAxisAngle(axisY, progress * 2 * Math.PI);
    turnZ.setFromAxisAngle(axisZ, progress * 2 * Math.PI);
    mesh.quaternion.copy(base).multiply(turnX).multiply(turnY).multiply(turnZ);
    world.scene.userData.pose = {time: t, phase: mesh.visible ? 'gray' : 'blank',
      progress, orientation: mesh.quaternion.toArray(), grayFade: 1, loop: config.loop};
  }
  update(0);
  return {scene: world.scene, camera: world.camera, update};
}
