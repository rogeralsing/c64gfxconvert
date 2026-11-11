// Fixed world-space point lighting; face normals stay discontinuous at cube edges.
// CPU Lambert evaluation keeps the export deterministic; Bayer dithering stays
// screen anchored in export.mjs, after Three.js renders these grayscale values.
import {config as baseConfig, createScene as createBaseScene} from "./demo-dithered-cube-loop.mjs";
import {fileURLToPath} from "node:url";

const {grayFaceRangesSRGB, grayFaceUncontrastedRangesSRGB, grayContrast,
  grayInterpolation, grayFadeSeconds, ...loopConfig} = baseConfig;

export const config = Object.freeze({
  ...loopConfig,
  name: "pal-world-lit-cube-loop",
  title: "Roterande kub med fast punktljus",
  description: "Fast ljuskälla i världen. Kubens plana sidnormaler och avståndet till ljuset styr toningen under rotationen.",
  sourceDependencies: [fileURLToPath(new URL("./demo-dithered-cube-loop.mjs", import.meta.url)),
    ...baseConfig.sourceDependencies],
  lighting: Object.freeze({type: "world-point-lambert", position: Object.freeze([-60, 65, 90]),
    ambientSRGB: 24, diffuseSRGB: 245, referenceDistance: 100, attenuationPower: 1.2,
    diffuseExponent: 1.35, flatFaceNormals: true, subdivisions: 16}),
  phaseLabels: {blank: "Tom startbild", gray: "Roterande kub i fast punktljus"},
});

export function createScene(THREE) {
  const world = createBaseScene(THREE);
  const mesh = world.scene.getObjectByName("fixed-gray-cube");
  if (!mesh) throw new Error("The approved cube is missing.");
  const side = config.cubeHalfSide * 2;
  mesh.geometry = new THREE.BoxGeometry(side, side, side, config.lighting.subdivisions,
    config.lighting.subdivisions, config.lighting.subdivisions);
  mesh.geometry.name = "flat-normal-subdivided-cube";
  mesh.material = new THREE.MeshBasicMaterial({color: 0xffffff, vertexColors: true, toneMapped: false});
  mesh.material.name = "neutral-gray-world-lambert";
  mesh.scale.setScalar(1);
  const positions = mesh.geometry.getAttribute("position"), normals = mesh.geometry.getAttribute("normal");
  const colors = new THREE.BufferAttribute(new Float32Array(positions.count * 3), 3);
  colors.setUsage(THREE.DynamicDrawUsage);
  mesh.geometry.setAttribute("color", colors);
  const light = new THREE.Vector3(...config.lighting.position);
  const position = new THREE.Vector3(), normal = new THREE.Vector3(), ray = new THREE.Vector3();
  const linear = new THREE.Color(), normalMatrix = new THREE.Matrix3();
  const oldUpdate = world.update;
  const calibration = {...world.scene.userData.calibration,
    affineFaceGradients: false, fixedWorldPointLight: true, flatFaceNormals: true,
    lighting: config.lighting, rgbLightingComputedBeforeDithering: true,
    textureGradientsRemoved: true};
  delete calibration.grayFaceRangesSRGB;
  world.scene.userData.calibration = calibration;
  function update(time) {
    oldUpdate(time);
    mesh.updateMatrixWorld(true);
    normalMatrix.getNormalMatrix(mesh.matrixWorld);
    for (let i = 0; i < positions.count; i++) {
      position.fromBufferAttribute(positions, i).applyMatrix4(mesh.matrixWorld);
      normal.fromBufferAttribute(normals, i).applyNormalMatrix(normalMatrix);
      ray.subVectors(light, position);
      const distance = ray.length();
      ray.multiplyScalar(1 / distance);
      const cosine = Math.max(0, normal.dot(ray));
      const falloff = Math.pow(config.lighting.referenceDistance / distance, config.lighting.attenuationPower);
      const level = Math.min(255, config.lighting.ambientSRGB + config.lighting.diffuseSRGB *
        Math.pow(cosine, config.lighting.diffuseExponent) * falloff) / 255;
      linear.setRGB(level, level, level, THREE.SRGBColorSpace);
      colors.setXYZ(i, linear.r, linear.g, linear.b);
    }
    colors.needsUpdate = true;
    world.scene.userData.pose = {...world.scene.userData.pose, lightPositionWorld: light.toArray()};
  }
  update(0);
  return {scene: world.scene, camera: world.camera, update};
}
