/** Versioned JSON projects contain source images and settings, never render caches. */
function createC64ProjectCodec({ modeIds, controls, virtualPalette }) {
  const invalid = detail => { throw new Error(`Invalid C64 project: ${detail}.`); };
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const integer = (value, min, max) => Number.isInteger(value) && value >= min && value <= max;
  const colorIndex = value => integer(value, 0, 15);
  const virtualIndices = new Set(virtualPalette.map(color => color.index));

  function parse(text) {
    let project;
    try { project = JSON.parse(text); }
    catch { invalid('the file is not valid JSON'); }
    if (!object(project) || project.app !== 'c64gfxconvert' || project.version !== 1) {
      invalid('expected a C64 Studio project, version 1');
    }
    const { image, view, activeLayer, layers } = project;
    if (!object(image) || !modeIds.includes(image.graphicsMode) ||
        !colorIndex(image.backgroundColorIndex) || !colorIndex(image.spriteColorIndex)) {
      invalid('unsupported image settings');
    }
    if (!object(view) || !['unrestricted', 'palette', 'restricted'].includes(view.previewMode) ||
        typeof view.grid !== 'boolean' || typeof view.paused !== 'boolean') {
      invalid('unsupported preview settings');
    }
    if (!Array.isArray(layers) || !layers.length || !integer(activeLayer, 0, layers.length - 1)) {
      invalid('missing layers or active layer');
    }
    const restored = layers.map((layer, index) => {
      const label = `layer ${index + 1}`;
      if (!object(layer) || typeof layer.name !== 'string' || !layer.name.trim() ||
          typeof layer.visible !== 'boolean' || typeof layer.autoName !== 'boolean') invalid(label);
      const { source, settings } = layer;
      if (source !== null && (!object(source) || typeof source.fileName !== 'string' || !source.fileName ||
          typeof source.dataUrl !== 'string' ||
          !/^data:(?:image\/[a-z0-9.+-]+|application\/octet-stream);base64,[A-Za-z0-9+/]+={0,2}$/.test(source.dataUrl))) {
        invalid(`${label} must contain an embedded image`);
      }
      if (!object(settings) || !object(settings.values) || !object(settings.palette)) invalid(`${label} settings`);
      const values = {};
      for (const control of controls) {
        const value = settings.values[control.id];
        if (control.type === 'checkbox' ? typeof value !== 'boolean'
          : control.type === 'range' ? !Number.isFinite(value) || value < control.min || value > control.max ||
            Math.abs((value - control.min) / control.step - Math.round((value - control.min) / control.step)) > 1e-7
          : !control.options.includes(value)) invalid(`${label}, ${control.id}`);
        values[control.id] = value;
      }
      if (values['levels-black'] >= values['levels-white']) invalid(`${label} levels`);
      const { minLevel, maxLevel, excludedIndices } = settings.palette;
      if (!integer(minLevel, 0, 16) || !integer(maxLevel, minLevel, 16) || !Array.isArray(excludedIndices) ||
          excludedIndices.some(value => !virtualIndices.has(value))) invalid(`${label} palette`);
      const excluded = new Set(excludedIndices);
      if (!virtualPalette.some(color => {
        const level = color.brightnessBands[0] + color.brightnessBands[1];
        return level >= minLevel && level <= maxLevel && !excluded.has(color.index);
      })) invalid(`${label} has no enabled palette colors`);
      return {
        name: layer.name, autoName: layer.autoName, visible: layer.visible,
        source: source && { fileName: source.fileName, dataUrl: source.dataUrl },
        settings: { values, palette: { minLevel, maxLevel, excludedIndices: [...excluded] } }
      };
    });
    return {
      app: 'c64gfxconvert', version: 1,
      image: { graphicsMode: image.graphicsMode, backgroundColorIndex: image.backgroundColorIndex,
        spriteColorIndex: image.spriteColorIndex },
      view: { previewMode: view.previewMode, grid: view.grid, paused: view.paused },
      activeLayer, layers: restored
    };
  }

  return {
    parse,
    stringify(state) {
      return JSON.stringify(parse(JSON.stringify({ ...state, app: 'c64gfxconvert', version: 1 })), null, 2);
    }
  };
}
