const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { createContext } = require('./fixtures/sprite-images.cjs');

const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../project.js'), 'utf8'), context);
const codecOptions = {
  modeIds: ['fli', 'afli-sprites', 'hires-2color', 'sprites', 'sprites-hires', 'charset'],
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
};
const codec = context.createC64ProjectCodec(codecOptions);
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
    ...[null, '', 'unknown', 'Pepto', 0, false, [], {}].map(paletteId =>
      project => { project.image.paletteId = paletteId; }),
    ...[null, '', 'unknown', 'Talent', 0, false, [], {}].map(virtualColorMode =>
      project => { project.image.virtualColorMode = virtualColorMode; }),
    ...[null, [], [0], [0, 1, 2], [0, 16], [-1, 1], [0, 1.5], ['0', 1]].map(twoColorIndices =>
      project => { project.image.twoColorIndices = twoColorIndices; }),
    ...[null, [], [0], [0, 1, 2], [0, 16], [-1, 1], [0, 1.5], ['0', 1]].map(charsetMulticolorIndices =>
      project => { project.image.charsetMulticolorIndices = charsetMulticolorIndices; }),
    ...[null, -1, 101, 0.5, '35', false].map(charsetSimilarityThreshold =>
      project => { project.image.charsetSimilarityThreshold = charsetSimilarityThreshold; }),
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

test('projects preserve C64 palettes and virtual color modes while accepting legacy image settings', () => {
  for (const paletteId of ['colodore', 'pepto', 'peptoette-a']) {
    for (const virtualColorMode of ['computed', 'talent']) {
      const project = fixture();
      Object.assign(project.image, { paletteId, virtualColorMode });
      const loaded = codec.parse(codec.stringify(project));
      assert.equal(loaded.image.paletteId, paletteId);
      assert.equal(loaded.image.virtualColorMode, virtualColorMode);
    }
  }
  const legacy = JSON.parse(codec.stringify(fixture()));
  assert.equal(Object.hasOwn(legacy.image, 'paletteId'), false);
  assert.equal(Object.hasOwn(legacy.image, 'virtualColorMode'), false);
});

test('project validation uses the requested virtual catalog and retains exclusions from inactive catalogs', () => {
  const runtime = createContext(['ifli.js', 'talent-palette.js', 'palettes.js', 'project.js']);
  const state = runtime.createC64PaletteState();
  const catalogCodec = runtime.createC64ProjectCodec({
    ...codecOptions, virtualPalette: state.virtualPalette, virtualPalettes: state.virtualPalettes
  });
  const exclusions = mode => Array.from(state.virtualPalettes[mode], color => color.index);
  for (const [current, requested] of [['computed', 'talent'], ['talent', 'computed']]) {
    state.setVirtualColorMode(current);
    const before = JSON.stringify(state.virtualPalette);
    const project = fixture();
    Object.assign(project.image, { paletteId: 'peptoette-a', virtualColorMode: requested });
    for (const layer of project.layers) {
      layer.settings.palette = { minLevel: 0, maxLevel: 16, excludedIndices: exclusions(current) };
    }

    const loaded = catalogCodec.parse(catalogCodec.stringify(project));

    assert.deepEqual(Array.from(loaded.layers[0].settings.palette.excludedIndices), exclusions(current));
    assert.equal(loaded.image.virtualColorMode, requested);
    assert.equal(state.virtualColorMode, current, 'parsing must not select the document catalog in the live UI');
    assert.equal(JSON.stringify(state.virtualPalette), before);
    project.image.virtualColorMode = current;
    assert.throws(() => catalogCodec.parse(JSON.stringify(project)), /no enabled palette colors/);
    assert.equal(state.virtualColorMode, current);
    assert.equal(JSON.stringify(state.virtualPalette), before);
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

test('character projects preserve both shared multicolors without changing legacy projects', () => {
  const project = fixture();
  project.image.graphicsMode = 'charset';
  project.image.charsetMulticolorIndices = [15, 12];
  const saved = JSON.parse(codec.stringify(project));
  assert.deepEqual(saved.image, project.image);
  assert.equal(codec.parse(JSON.stringify(fixture())).image.charsetMulticolorIndices, undefined);
});

test('character projects preserve disabled and maximum similarity thresholds', () => {
  for (const charsetSimilarityThreshold of [0, 100]) {
    const project = fixture();
    project.image.graphicsMode = 'charset';
    project.image.charsetSimilarityThreshold = charsetSimilarityThreshold;
    const loaded = codec.parse(codec.stringify(project));
    assert.equal(loaded.image.charsetSimilarityThreshold, charsetSimilarityThreshold);
  }
  assert.equal(codec.parse(JSON.stringify(fixture())).image.charsetSimilarityThreshold, undefined);
});

test('sprite projects preserve grid geometry and independent shared, sprite, and overlay colors', () => {
  for (const [mode, columns, rows] of [['sprites', 1, 8], ['sprites-hires', 2, 2]]) {
    const project = fixture();
    project.image.graphicsMode = mode;
    project.image.spriteConfig = {
      columns, rows, multicolorIndices: [5, 7],
      spriteColorIndices: [1, 2, 3, 4, 5, 6, 7, 8],
      overlayColorIndices: [15, 14, 13, 12, 11, 10, 9, 8]
    };
    const saved = JSON.parse(codec.stringify(project));
    assert.deepEqual(saved.image, project.image);
  }
  assert.equal(codec.parse(JSON.stringify(fixture())).image.spriteConfig, undefined);
});

test('sprite project import rejects invalid colors, dimensions, and hardware sprite budgets', () => {
  for (const change of [
    config => { config.columns = 0; },
    config => { config.rows = 1.5; },
    config => { config.columns = 9; },
    config => { config.columns = 3; config.rows = 3; },
    config => { config.multicolorIndices = [0]; },
    config => { config.spriteColorIndices[7] = 16; },
    config => { config.overlayColorIndices[0] = '1'; },
    config => { config.overlayColorIndices = []; }
  ]) {
    const project = fixture();
    project.image.spriteConfig = {
      columns: 2, rows: 2, multicolorIndices: [5, 7],
      spriteColorIndices: Array(8).fill(1), overlayColorIndices: Array(8).fill(0)
    };
    change(project.image.spriteConfig);
    assert.throws(() => codec.parse(JSON.stringify(project)), /Invalid C64 project: sprite grids/);
  }
  const project = fixture();
  project.image.graphicsMode = 'sprites-hires';
  project.image.spriteConfig = {
    columns: 1, rows: 8, multicolorIndices: [5, 7],
    spriteColorIndices: Array(8).fill(1), overlayColorIndices: Array(8).fill(0)
  };
  assert.throws(() => codec.parse(JSON.stringify(project)), /Invalid C64 project: sprite grids/);
});
