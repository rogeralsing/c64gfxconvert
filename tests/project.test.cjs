const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { createContext } = require('./fixtures/sprite-images.cjs');

const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../source-crop.js'), 'utf8'), context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../project.js'), 'utf8'), context);
const codecOptions = {
  modeIds: ['fli', 'afli-sprites', 'hires-2color', 'sprites', 'sprites-hires', 'charset'],
  controls: [
    { id: 'brightness', type: 'range', min: -100, max: 300, step: 1 },
    { id: 'levels-black', type: 'range', min: 0, max: 254, step: 1 },
    { id: 'levels-white', type: 'range', min: 1, max: 255, step: 1 },
    { id: 'interlace-spacing', type: 'range', min: 1, max: 32, step: 1 },
    { id: 'interlace-direction', type: 'select-one', options: ['horizontal', 'diagonal-up', 'diagonal-down'] },
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
        'interlace-spacing': 4, 'interlace-direction': 'diagonal-up',
        'scanline-dither': true, 'virtual-colors': 'checkers' },
      curvePoints: [{ input: 0, output: 0 }, { input: 96, output: 60 }, { input: 255, output: 255 }],
      palette: { minLevel: 1, maxLevel: 2, excludedIndices: [0, 1] } } },
    { name: 'Empty layer', visible: true, autoName: true, source: null,
      settings: { values: { brightness: -18, 'levels-black': 0, 'levels-white': 255,
        'interlace-spacing': 2, 'interlace-direction': 'horizontal',
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

test('mixed projects preserve marker colors, binary tiles, visibility, and active layer alongside legacy image layers', () => {
  const project = fixture();
  const tiles = Array(1000).fill(0);
  tiles[0] = tiles[41] = tiles[999] = 1;
  project.layers.push({ type: 'tile-markers', name: 'Selected tiles', autoName: false, visible: false,
    source: null, settings: null, markers: { color: '#00aaff', tiles } });
  project.activeLayer = 2;

  const saved = JSON.parse(codec.stringify(project));
  assert.deepEqual(saved.layers[2], project.layers[2]);
  assert.deepEqual(saved.layers[0].source, source);
  assert.equal(saved.layers[0].settings.values.brightness, 37);
  assert.equal(saved.activeLayer, 2);
  const restored = codec.parse(JSON.stringify(saved));
  restored.layers[2].markers.tiles[41] = 0;
  assert.equal(saved.layers[2].markers.tiles[41], 1);
});

test('project import rejects invalid marker maps and unknown layer types', () => {
  for (const change of [
    layer => { layer.type = 'unknown'; },
    layer => { layer.markers.color = 'red'; },
    layer => { layer.markers.color = '#fff'; },
    layer => { layer.markers.tiles.pop(); },
    layer => { layer.markers.tiles.push(0); },
    layer => { layer.markers.tiles[50] = 2; },
    layer => { layer.markers.tiles[50] = true; },
    layer => { layer.markers.tiles[50] = null; },
    layer => { layer.source = source; },
    layer => { layer.settings = fixture().layers[0].settings; }
  ]) {
    const project = fixture();
    project.layers[1] = { type: 'tile-markers', name: 'Markers', autoName: true, visible: true,
      source: null, settings: null, markers: { color: '#ffcc00', tiles: Array(1000).fill(0) } };
    change(project.layers[1]);
    assert.throws(() => codec.parse(JSON.stringify(project)), /Invalid C64 project: layer 2/);
  }
});

test('project curves, crops, and interlace settings round-trip per layer and migrate older projects', () => {
  const project = fixture();
  project.layers[0].settings.crop = { mode: 'polygon', points: [
    { x: 0.1, y: 0.2 }, { x: 0.9, y: 0.2 }, { x: 0.6, y: 0.55 }, { x: 0.8, y: 0.9 }, { x: 0.1, y: 0.9 }
  ] };
  const saved = JSON.parse(codec.stringify(project));
  assert.deepEqual(saved.layers[0].settings.curvePoints, project.layers[0].settings.curvePoints);
  assert.deepEqual(saved.layers[0].settings.crop, project.layers[0].settings.crop);
  assert.equal(saved.layers[1].settings.crop, null);
  assert.deepEqual(saved.layers[0].source, source, 'crop keeps the full embedded source image');
  assert.equal(saved.layers[0].settings.values['interlace-spacing'], 4);
  assert.equal(saved.layers[0].settings.values['interlace-direction'], 'diagonal-up');
  assert.deepEqual(saved.layers[1].settings.curvePoints, [{ input: 0, output: 0 }, { input: 255, output: 255 }]);
  const loaded = codec.parse(JSON.stringify(saved));
  loaded.layers[0].settings.crop.points[0].x = 0.3;
  assert.equal(saved.layers[0].settings.crop.points[0].x, 0.1);
  loaded.layers[0].settings.curvePoints[1].output = 30;
  assert.equal(loaded.layers[1].settings.curvePoints[1].output, 255);
  assert.equal(saved.layers[0].settings.curvePoints[1].output, 60);

  for (const layer of project.layers) {
    delete layer.settings.curvePoints;
    delete layer.settings.crop;
    delete layer.settings.values['interlace-spacing'];
    delete layer.settings.values['interlace-direction'];
  }
  const migrated = JSON.parse(JSON.stringify(codec.parse(JSON.stringify(project))));
  for (const layer of migrated.layers) {
    assert.equal(layer.settings.crop, null);
    assert.deepEqual(layer.settings.curvePoints, [{ input: 0, output: 0 }, { input: 255, output: 255 }]);
    assert.equal(layer.settings.values['interlace-spacing'], 2);
    assert.equal(layer.settings.values['interlace-direction'], 'horizontal');
  }
});

test('project import rejects malformed crop masks before replacing a document', () => {
  const rectangle = { mode: 'rectangle', points: [
    { x: 0.1, y: 0.2 }, { x: 0.8, y: 0.2 }, { x: 0.8, y: 0.9 }, { x: 0.1, y: 0.9 }
  ] };
  for (const crop of [
    false, {}, { mode: 'triangle', points: rectangle.points },
    { mode: 'polygon', points: [] },
    { mode: 'polygon', points: [{ x: 0, y: 0 }, { x: 1, y: 0 }] },
    { mode: 'polygon', points: [{ x: 0, y: 0 }, { x: 0.5, y: 0.5 }, { x: 1, y: 1 }] },
    { mode: 'polygon', points: [{ x: -0.1, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }] },
    { mode: 'rectangle', points: rectangle.points.map((point, index) => index === 1 ? { ...point, y: 0.4 } : point) }
  ]) {
    const project = fixture();
    project.layers[0].settings.crop = crop;
    assert.throws(() => codec.parse(JSON.stringify(project)), /Invalid C64 project: layer 1 crop mask/);
  }
  const project = fixture();
  project.layers[0].settings.crop = rectangle;
  assert.deepEqual(JSON.parse(codec.stringify(project)).layers[0].settings.crop, rectangle);
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
    ...[0, 33, 2.5, '4', null].map(value =>
      project => { project.layers[0].settings.values['interlace-spacing'] = value; }),
    ...['vertical', '', 0, null].map(value =>
      project => { project.layers[0].settings.values['interlace-direction'] = value; }),
    ...[null, [], [{ input: 0, output: 0 }],
      [{ input: 1, output: 0 }, { input: 255, output: 255 }],
      [{ input: 0, output: 0 }, { input: 255, output: 256 }],
      [{ input: 0, output: 0 }, { input: 96, output: 60 }, { input: 96, output: 90 }, { input: 255, output: 255 }],
      [{ input: 0, output: 0 }, { input: 120, output: 60 }, { input: 96, output: 90 }, { input: 255, output: 255 }]
    ].map(value => project => { project.layers[0].settings.curvePoints = value; }),
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

test('Talent projects retain separate lightness caps and validate enabled colors by their actual lightness', () => {
  const toneCodec = context.createC64ProjectCodec({
    ...codecOptions,
    virtualPalettes: {
      computed: codecOptions.virtualPalette,
      talent: [
        { index: 0, brightnessBands: [0, 0], lightness: 0 },
        { index: 1, brightnessBands: [0, 1], lightness: 0.45 },
        { index: 2, brightnessBands: [1, 1], lightness: 0.6 }
      ]
    }
  });
  const project = fixture();
  project.image.virtualColorMode = 'talent';
  for (const layer of project.layers) {
    layer.settings.palette = {
      minLevel: 0, maxLevel: 0, minLightness: 44, maxLightness: 46, excludedIndices: [0, 2]
    };
  }
  const saved = JSON.parse(toneCodec.stringify(project));
  assert.deepEqual(saved.layers[0].settings.palette, project.layers[0].settings.palette);
  saved.image.virtualColorMode = 'computed';
  saved.layers.forEach(layer => { layer.settings.palette.excludedIndices = [1, 2]; });
  const restored = JSON.parse(toneCodec.stringify(saved));
  assert.equal(restored.layers[0].settings.palette.minLightness, 44);
  assert.equal(restored.layers[0].settings.palette.maxLightness, 46);

  for (const [minLightness, maxLightness] of [[-1, 100], [0, 101], [45, 44], [0.5, 100], [46, 60]]) {
    const invalid = structuredClone(project);
    Object.assign(invalid.layers[0].settings.palette, { minLightness, maxLightness });
    assert.throws(() => toneCodec.parse(JSON.stringify(invalid)), /Invalid C64 project/);
  }
});

test('project validation uses the requested virtual catalog and retains exclusions from inactive catalogs', () => {
  const runtime = createContext(['ifli.js', 'talent-palette.js', 'talent-neighbors.js', 'talent-mapping.js', 'palettes.js', 'source-crop.js', 'project.js']);
  const state = runtime.createC64PaletteState();
  const catalogCodec = runtime.createC64ProjectCodec({
    ...codecOptions, virtualPalette: state.virtualPalette, virtualPalettes: state.virtualPalettes,
    virtualColorIndices: state.virtualColorIndices,
    legacyTalentPalette: state.legacyTalentPalette,
    resolveVirtualPalettes: id => {
      const resolved = runtime.createC64PaletteState(id);
      return { ...resolved.virtualPalettes, legacyTalent: resolved.legacyTalentPalette };
    }
  });
  const documentCatalogs = runtime.createC64PaletteState('peptoette-a').virtualPalettes;
  const exclusions = mode => Array.from(documentCatalogs[mode], color => color.index);
  for (const [current, requested] of [['computed', 'talent'], ['talent', 'computed']]) {
    state.setVirtualColorMode(current);
    const before = JSON.stringify(state.virtualPalette);
    const project = fixture();
    Object.assign(project.image, { paletteId: 'peptoette-a', virtualColorMode: requested, talentPatternVersion: 2 });
    for (const layer of project.layers) {
      layer.settings.palette = {
        minLevel: 0, maxLevel: 16, minLightness: 0, maxLightness: 100, excludedIndices: exclusions(current)
      };
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

test('legacy Talent row caps migrate using the document palette and retain Talent color exclusions', () => {
  const runtime = createContext(['ifli.js', 'talent-palette.js', 'talent-neighbors.js', 'talent-mapping.js', 'palettes.js', 'source-crop.js', 'project.js']);
  const state = runtime.createC64PaletteState('colodore');
  const catalogCodec = runtime.createC64ProjectCodec({
    ...codecOptions, virtualPalette: state.virtualPalette, virtualPalettes: state.virtualPalettes,
    virtualColorIndices: state.virtualColorIndices,
    legacyTalentPalette: state.legacyTalentPalette,
    resolveVirtualPalettes: id => {
      const resolved = runtime.createC64PaletteState(id);
      return { ...resolved.virtualPalettes, legacyTalent: resolved.legacyTalentPalette };
    }
  });
  const talentIndex = state.virtualPalettes.talent.find(color => color.colorIndices.join('-') === '0-4').index;
  const patterns = state.virtualPalettes.talent.filter(color => color.patternWidth);
  const patternIndices = Array.from(patterns, color => color.index);
  const project = fixture();
  Object.assign(project.image, { paletteId: 'peptoette-a', virtualColorMode: 'talent' });
  project.layers[0].settings.palette = { minLevel: 2, maxLevel: 2, excludedIndices: [talentIndex] };

  const restored = JSON.parse(catalogCodec.stringify(project));

  assert.deepEqual(restored.layers[0].settings.palette, {
    minLevel: 2, maxLevel: 2, minLightness: 33, maxLightness: 38, excludedIndices: [talentIndex, ...patternIndices]
  });
  assert.equal(restored.layers[1].settings.palette.minLightness, 0);
  assert.equal(restored.layers[1].settings.palette.maxLightness, 100);
  assert.equal(state.id, 'colodore', 'project migration must not select a palette in the live document');

  state.select('peptoette-a');
  delete project.image.paletteId;
  const defaultPalette = JSON.parse(catalogCodec.stringify(project));
  assert.equal(defaultPalette.layers[0].settings.palette.minLightness, 31);
  assert.equal(defaultPalette.layers[0].settings.palette.maxLightness, 41);
  assert.equal(state.id, 'peptoette-a', 'missing palette IDs mean Colodore, irrespective of the live document');

  const oldGreen = state.legacyTalentPalette.find(color => color.colorIndices.every(index => index === 5));
  const excludedIndices = state.legacyTalentPalette.filter(color => color.index !== oldGreen.index).map(color => color.index);
  project.image.paletteId = 'peptoette-a';
  project.layers[0].settings.palette = { minLevel: 10, maxLevel: 10, excludedIndices };
  const migrated = JSON.parse(catalogCodec.stringify(project)).layers[0].settings.palette;
  const newlyEnabled = state.virtualPalettes.talent.filter(color => !migrated.excludedIndices.includes(color.index));
  assert.equal(newlyEnabled.length, 1, 'a valid legacy selection retains its single chosen Talent color');
  assert.equal(newlyEnabled[0].index, oldGreen.index);
  assert.deepEqual(migrated.excludedIndices, [...excludedIndices, ...patternIndices]);
  assert.ok(newlyEnabled[0].lightness * 100 >= migrated.minLightness);
  assert.ok(newlyEnabled[0].lightness * 100 <= migrated.maxLightness);

  Object.assign(project.layers[0].settings.palette, { minLightness: 0, maxLightness: 100 });
  project.layers[0].settings.palette.excludedIndices.push(oldGreen.index);
  assert.throws(() => catalogCodec.parse(JSON.stringify(project)), /no enabled palette colors/,
    'explicit lightness selections remain strict');
  const withPattern = structuredClone(project);
  withPattern.image.talentPatternVersion = 1;
  const originalPatterns = Array.from(patterns.filter(color => !color.patternVersion), color => color.index);
  const newPatterns = Array.from(patterns.filter(color => color.patternVersion === 2), color => color.index);
  const savedExclusions = withPattern.layers[0].settings.palette.excludedIndices;
  savedExclusions.push(...originalPatterns.slice(1));
  const reopened = catalogCodec.parse(catalogCodec.stringify(withPattern));
  assert.equal(reopened.image.talentPatternVersion, 1);
  assert.deepEqual(Array.from(reopened.layers[0].settings.palette.excludedIndices),
    [...savedExclusions, ...newPatterns], 'a version 1 project restores its pattern selection and excludes newer swatches');

  withPattern.image.talentPatternVersion = 2;
  const expanded = catalogCodec.parse(catalogCodec.stringify(withPattern));
  assert.equal(expanded.image.talentPatternVersion, 2);
  assert.deepEqual(Array.from(expanded.layers[0].settings.palette.excludedIndices),
    savedExclusions, 'a current project retains the enabled new swatches');

  delete project.layers[0].settings.palette.minLightness;
  delete project.layers[0].settings.palette.maxLightness;
  assert.throws(() => catalogCodec.parse(JSON.stringify(project)), /no enabled palette colors/,
    'legacy documents with no enabled old tones remain invalid');
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

test('projects preserve global border sprite modes and colors without adding settings to legacy documents', () => {
  for (const borderSprites of [
    { vertical: { enabled: false, mode: 'hires', colorIndex: 3 },
      sides: { enabled: false, mode: 'hires', colorIndex: 3 },
      multicolorIndices: [1, 14] },
    { vertical: { enabled: true, mode: 'hires', colorIndex: 0 },
      sides: { enabled: false, mode: 'multicolor', colorIndex: 15 },
      multicolorIndices: [2, 13] },
    { vertical: { enabled: true, mode: 'multicolor', colorIndex: 13 },
      sides: { enabled: true, mode: 'multicolor', colorIndex: 13 },
      multicolorIndices: [6, 1], optimizeColors: true },
    { vertical: { enabled: true, mode: 'multicolor', colorIndex: 3, xExpanded: false },
      sides: { enabled: true, mode: 'hires', colorIndex: 14 },
      multicolorIndices: [1, 6], optimizeColors: false }
  ]) {
    const project = fixture();
    project.image.borderSprites = borderSprites;
    const saved = JSON.parse(codec.stringify(project));
    assert.deepEqual(saved.image, project.image);
    const loaded = codec.parse(JSON.stringify(saved));
    loaded.image.borderSprites.vertical.enabled = !borderSprites.vertical.enabled;
    loaded.image.borderSprites.sides.colorIndex = 1;
    loaded.image.borderSprites.multicolorIndices[0] = 7;
    assert.deepEqual(saved.image.borderSprites, borderSprites);
  }
  assert.equal(Object.hasOwn(codec.parse(JSON.stringify(fixture())).image, 'borderSprites'), false);
});

test('project import rejects incomplete border sprite settings and invalid modes, flags, or colors', () => {
  for (const change of [
    image => { image.borderSprites = null; },
    image => { image.borderSprites = []; },
    image => { delete image.borderSprites.vertical; },
    image => { image.borderSprites.sides = null; },
    image => { image.borderSprites.vertical.mode = 'bitmap'; },
    image => { image.borderSprites.sides.mode = 'Hires'; },
    image => { image.borderSprites.vertical.enabled = 1; },
    image => { image.borderSprites.sides.enabled = 'false'; },
    image => { image.borderSprites.vertical.colorIndex = -1; },
    image => { image.borderSprites.sides.colorIndex = 16; },
    image => { image.borderSprites.multicolorIndices = [1]; },
    image => { image.borderSprites.multicolorIndices = [1, 2, 3]; },
    image => { image.borderSprites.multicolorIndices = ['1', 2]; },
    image => { image.borderSprites.multicolorIndices[1] = 16; },
    image => { image.borderSprites.optimizeColors = 'true'; },
    ...[0, 'false', null].map(value => image => { image.borderSprites.vertical.xExpanded = value; })
  ]) {
    const project = fixture();
    project.image.borderSprites = {
      vertical: { enabled: true, mode: 'hires', colorIndex: 3 },
      sides: { enabled: true, mode: 'multicolor', colorIndex: 15 },
      multicolorIndices: [1, 14]
    };
    change(project.image);
    assert.throws(() => codec.parse(JSON.stringify(project)), /Invalid C64 project: border sprites/);
  }
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
