// Render continuous grayscale first. Screen-fixed ordered dithering belongs
// exclusively to the bitmap exporter, never to a material or animation clock.
import {config as tumbleConfig, createScene as createTumblingScene} from './demo-tumbling-star.mjs';

export const config = Object.freeze({
  ...tumbleConfig,
  name: 'dithered-tumbling-star',
  title: 'Gråtonad stjärna som roterar kring alla tre axlar',
  description: 'Den solida stjärnan tumlar kring tre axlar med mjuka gråtoner på sina plana fasetter. Kontinuerlig belysning visar formen; gråskalebilden omvandlas sedan till ett fast dithermönster.',
  sourceDependencies: Object.freeze(['./demo-tumbling-star.mjs', './demo-solid-star.mjs']),
  shading: Object.freeze({
    model: 'Continuous world-normal Lambert lighting with an ambient floor',
    minimumSRGB: 0.20,
    maximumSRGB: 0.90,
    lights: Object.freeze([
      Object.freeze({direction: Object.freeze([-0.55, 0.75, 1]), strength: 1}),
      Object.freeze({direction: Object.freeze([0.8, -0.35, 0.35]), strength: 0.28}),
      Object.freeze({direction: Object.freeze([-0.5, 0.15, -0.85]), strength: 0.12}),
    ]),
  }),
});

export function createScene(THREE) {
  const world = createTumblingScene(THREE);
  const mesh = world.scene.getObjectByName('solid-star');
  const normals = mesh.geometry.getAttribute('normal');
  const localNormals = mesh.material.map((_, index) => new THREE.Vector3().fromBufferAttribute(normals, index * 3));
  const normal = new THREE.Vector3();
  const lights = config.shading.lights.map(light => ({direction: new THREE.Vector3(...light.direction).normalize(), strength: light.strength}));
  const linearGray = value => new THREE.Color().setRGB(value, value, value, THREE.SRGBColorSpace).r;
  const low = linearGray(config.shading.minimumSRGB), high = linearGray(config.shading.maximumSRGB);
  const toSRGB = value => value <= 0.0031308 ? value * 12.92 : 1.055 * value ** (1 / 2.4) - 0.055;
  mesh.material.forEach((material, index) => {
    material.name = 'continuous-gray-star-facet-' + index;
    material.transparent = false;material.opacity = 1;material.depthWrite = true;material.depthTest = true;
    material.toneMapped = false;
  });
  const {binaryPaintRule, whiteFacetIndices, blackFacetIndices, facetColorsConstant, expectedRGBLevels, ...calibration} = world.scene.userData.calibration;
  world.scene.userData.calibration = {...calibration,
    fill: 'Opaque continuous-gray triangles; no binary paint, glass, ball, texture or line strokes.',
    shading: config.shading,
    interpolation: 'Linear-light interpolation between the stated sRGB endpoints, then standard sRGB GPU output.',
    expectedGraySourceRangeBytes: [51, 230],
    quantization: 'Exporter only: 4x4 ordered Bayer at fixed screen coordinates.'};
  const updateTumble = world.update;
  world.update = time => {
    updateTumble(time);
    const levels = [];
    mesh.material.forEach((material, index) => {
      normal.copy(localNormals[index]).applyQuaternion(mesh.quaternion);
      const illumination = Math.min(1, lights.reduce((sum, light) =>
        sum + light.strength * Math.max(0, normal.dot(light.direction)), 0));
      const linear = low + (high - low) * illumination;
      // MeshBasicMaterial stores linear working-space colors. The sRGB render
      // target encodes the actual gray values before the exporter dithers them.
      material.color.setRGB(linear, linear, linear);
      levels.push(toSRGB(linear));
    });
    delete world.scene.userData.pose.whiteFacets;
    world.scene.userData.pose.facetGraySRGB = levels;
    world.scene.userData.pose.shading = 'continuous-grayscale';
  };
  world.update(0);
  return world;
}
