const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../project.js'), 'utf8'), context);
const codec = context.createC64ProjectCodec({
  modeIds: ['fli', 'afli-sprites', 'hires-2color'],
  controls: [
    { id: 'brightness', type: 'range', min: -100, max: 300, step: 1 },
    { id: 'levels-black', type: 'range', min: 0, max: 254, step: 1 },
    { id: 'levels-white', type: 'range', min: 1, max: 255, step: 1 },
    { id: 'scanline-dither', type: 'checkbox' },
    { id: 'virtual-colors', type: 'select-one', options: ['off', 'lines', 'checkers'] }
  ],
  virtualPalette: [
    { index: 0, brightnessBands: [0, 0] },
    { index: 1, brightnessBands: [0, 1] },
    { index: 2, brightnessBands: [1, 1] }
  ]
});
const source = { fileName: 'cutout.png', dataUrl: 'data:image/png;base64,iVBORw0KGgo=' };
const fixture = () => ({
  app: 'c64gfxconvert', version: 1,
  image: { graphicsMode: 'afli-sprites', backgroundColorIndex: 9, spriteColorIndex: 7 },
  view: { previewMode: 'restricted', grid: false, paused: true },
  activeLayer: 1,
  layers: [
    { name: 'Hidden source', visible: false, autoName: false, source,
      settings: { values: { brightness: 37, 'levels-black': 12, 'levels-white': 225,
        'scanline-dither': true, 'virtual-colors': 'checkers' },
      palette: { minLevel: 1, maxLevel: 2, excludedIndices: [0, 1] } } },
    { name: 'Empty layer', visible: true, autoName: true, source: null,
      settings: { values: { brightness: -18, 'levels-black': 0, 'levels-white': 255,
        'scanline-dither': false, 'virtual-colors': 'off' },
      palette: { minLevel: 0, maxLevel: 16, excludedIndices: [] } } }
  ]
});

test('project JSON preserves embedded sources, shared settings, and distinct ordered layer settings', () => {
  const saved = JSON.parse(codec.stringify(fixture()));
  assert.equal(saved.app, 'c64gfxconvert');
  assert.equal(saved.version, 1);
  assert.deepEqual(saved.image, { graphicsMode: 'afli-sprites', backgroundColorIndex: 9, spriteColorIndex: 7 });
  assert.deepEqual(saved.view, { previewMode: 'restricted', grid: false, paused: true });
  assert.equal(saved.activeLayer, 1);
  assert.deepEqual(saved.layers.map(layer => layer.name), ['Hidden source', 'Empty layer']);
  assert.deepEqual(saved.layers[0].source, source);
  assert.equal(saved.layers[0].visible, false);
  assert.equal(saved.layers[0].settings.values.brightness, 37);
  assert.deepEqual(saved.layers[0].settings.palette, { minLevel: 1, maxLevel: 2, excludedIndices: [0, 1] });
  assert.equal(saved.layers[1].source, null);
  assert.equal(saved.layers[1].autoName, true);
  assert.equal(saved.layers[1].settings.values.brightness, -18);
  const loaded = codec.parse(JSON.stringify(fixture()));
  loaded.layers[0].settings.values.brightness = 100;
  assert.equal(loaded.layers[1].settings.values.brightness, -18);
});

test('project import rejects unsupported documents and unusable settings before replacing a document', () => {
  assert.throws(() => codec.parse('{'), /not valid JSON/);
  const cases = [
    project => { project.app = 'other-app'; },
    project => { project.version = 2; },
    project => { project.image.graphicsMode = 'unknown'; },
    project => { project.image.spriteColorIndex = 16; },
    ...[null, [], [0], [0, 1, 2], [0, 16], [-1, 1], [0, 1.5], ['0', 1]].map(twoColorIndices =>
      project => { project.image.twoColorIndices = twoColorIndices; }),
    project => { project.layers = []; },
    project => { project.activeLayer = 2; },
    project => { project.layers[0].visible = 'false'; },
    project => { project.layers[0].source = { fileName: 'photo.png', dataUrl: 'https://example.com/photo.png' }; },
    project => { project.layers[0].settings.values.brightness = 301; },
    project => { project.layers[0].settings.values.brightness = 0.5; },
    project => { delete project.layers[0].settings.values['scanline-dither']; },
    project => { project.layers[0].settings.values['levels-white'] = 12; },
    project => { project.layers[0].settings.values['virtual-colors'] = 'unknown'; },
    project => { project.layers[0].settings.palette.minLevel = 3; },
    project => { project.layers[0].settings.palette.excludedIndices = [999]; },
    project => { project.layers[0].settings.palette.excludedIndices = [0, 1, 2]; }
  ];
  for (const change of cases) {
    const project = fixture();
    change(project);
    assert.throws(() => codec.parse(JSON.stringify(project)), /Invalid C64 project/);
  }
});

test('two-color projects preserve the chosen shadow and highlight without changing legacy projects', () => {
  const project = fixture();
  project.image.graphicsMode = 'hires-2color';
  project.image.twoColorIndices = [14, 5];
  const loaded = codec.parse(codec.stringify(project));
  assert.equal(loaded.image.graphicsMode, 'hires-2color');
  assert.deepEqual(Array.from(loaded.image.twoColorIndices), [14, 5]);
  assert.equal(codec.parse(JSON.stringify(fixture())).image.twoColorIndices, undefined);
});
