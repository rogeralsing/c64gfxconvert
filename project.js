/** Versioned JSON projects contain source images and settings, never render caches. */
function createC64ProjectCodec({ modeIds, controls, virtualPalette, virtualPalettes, virtualColorIndices,
    legacyTalentPalette, resolveVirtualPalettes }) {
  const invalid = detail => { throw new Error(`Invalid C64 project: ${detail}.`); };
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const integer = (value, min, max) => Number.isInteger(value) && value >= min && value <= max;
  const colorIndex = value => integer(value, 0, 15);
  const catalogs = {
    computed: virtualPalettes?.computed ?? virtualPalette,
    talent: virtualPalettes?.talent ?? virtualPalette,
    legacyTalent: legacyTalentPalette ?? virtualPalettes?.talent ?? virtualPalette
  };
  const virtualIndices = new Set(virtualColorIndices ?? Object.values(catalogs).flat().map(color => color.index));

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
    if (image.paletteId !== undefined && !['colodore', 'pepto', 'peptoette-a'].includes(image.paletteId)) {
      invalid('unsupported C64 palette');
    }
    if (image.virtualColorMode !== undefined && !['computed', 'talent'].includes(image.virtualColorMode)) {
      invalid('unsupported virtual color mode');
    }
    const documentCatalogs = resolveVirtualPalettes
      ? resolveVirtualPalettes(image.paletteId ?? 'colodore') : catalogs;
    const requestedVirtualPalette = documentCatalogs[image.virtualColorMode ?? 'computed'];
    const oldTalentPalette = documentCatalogs.legacyTalent ?? documentCatalogs.talent;
    if (image.twoColorIndices !== undefined && (!Array.isArray(image.twoColorIndices) ||
        image.twoColorIndices.length !== 2 || image.twoColorIndices.some(value => !colorIndex(value)))) {
      invalid('two-color hires requires two C64 palette colors');
    }
    if (image.charsetMulticolorIndices !== undefined && (!Array.isArray(image.charsetMulticolorIndices) ||
        image.charsetMulticolorIndices.length !== 2 || image.charsetMulticolorIndices.some(value => !colorIndex(value)))) {
      invalid('character mode requires two shared C64 palette colors');
    }
    if (image.charsetSimilarityThreshold !== undefined && !integer(image.charsetSimilarityThreshold, 0, 100)) {
      invalid('character similarity threshold must be an integer from 0 to 100');
    }
    const spriteConfig = image.spriteConfig;
    if (spriteConfig !== undefined) {
      const colors = (value, count) => Array.isArray(value) && value.length === count && value.every(colorIndex);
      if (!object(spriteConfig) || !integer(spriteConfig.columns, 1, 8) || !integer(spriteConfig.rows, 1, 8) ||
          spriteConfig.columns * spriteConfig.rows > (image.graphicsMode === 'sprites-hires' ? 4 : 8) ||
          !colors(spriteConfig.multicolorIndices, 2) || !colors(spriteConfig.spriteColorIndices, 8) ||
          !colors(spriteConfig.overlayColorIndices, 8)) {
        invalid('sprite grids require at most eight sprites and valid C64 colors');
      }
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
      const rowInRange = color => {
        const level = color.brightnessBands[0] + color.brightnessBands[1];
        return level >= minLevel && level <= maxLevel;
      };
      const legacyTalent = image.virtualColorMode === 'talent' &&
        settings.palette.minLightness === undefined && settings.palette.maxLightness === undefined;
      const lightnessOf = color => (color.lightness ??
        (color.brightnessBands[0] + color.brightnessBands[1]) / 16) * 100;
      if (legacyTalent && !oldTalentPalette.some(color => rowInRange(color) && !excluded.has(color.index))) {
        invalid(`${label} has no enabled palette colors`);
      }
      let lightnessLimits;
      if (settings.palette.minLightness !== undefined || settings.palette.maxLightness !== undefined) {
        const { minLightness, maxLightness } = settings.palette;
        if (!integer(minLightness, 0, 100) || !integer(maxLightness, minLightness, 100)) {
          invalid(`${label} palette lightness`);
        }
        lightnessLimits = { minLightness, maxLightness };
      } else if (image.virtualColorMode === 'talent') {
        lightnessLimits = typeof getTalentLightnessLimits === 'function'
          ? getTalentLightnessLimits(settings.palette, oldTalentPalette)
          : { minLightness: Math.floor(minLevel / 16 * 100), maxLightness: Math.ceil(maxLevel / 16 * 100) };
      }
      const lightnessInRange = color => lightnessOf(color) >= lightnessLimits.minLightness - 1e-6 &&
        lightnessOf(color) <= lightnessLimits.maxLightness + 1e-6;
      if (legacyTalent && !requestedVirtualPalette.some(color => lightnessInRange(color) && !excluded.has(color.index))) {
        const previous = oldTalentPalette.filter(color => rowInRange(color) && !excluded.has(color.index));
        const target = previous.reduce((sum, color) => sum + lightnessOf(color), 0) / previous.length;
        const inRange = requestedVirtualPalette.filter(lightnessInRange);
        const candidates = inRange.length ? inRange : requestedVirtualPalette;
        const nearest = candidates.reduce((best, color) =>
          Math.abs(lightnessOf(color) - target) < Math.abs(lightnessOf(best) - target) ? color : best);
        if (!inRange.length) {
          lightnessLimits.minLightness = Math.min(lightnessLimits.minLightness, Math.floor(lightnessOf(nearest)));
          lightnessLimits.maxLightness = Math.max(lightnessLimits.maxLightness, Math.ceil(lightnessOf(nearest)));
        }
        excluded.delete(nearest.index);
      }
      if (!requestedVirtualPalette.some(color => !excluded.has(color.index) &&
          (image.virtualColorMode === 'talent' ? lightnessInRange(color) : rowInRange(color)))) {
        invalid(`${label} has no enabled palette colors`);
      }
      return {
        name: layer.name, autoName: layer.autoName, visible: layer.visible,
        source: source && { fileName: source.fileName, dataUrl: source.dataUrl },
        settings: { values, palette: { minLevel, maxLevel, ...lightnessLimits, excludedIndices: [...excluded] } }
      };
    });
    return {
      app: 'c64gfxconvert', version: 1,
      image: { graphicsMode: image.graphicsMode, backgroundColorIndex: image.backgroundColorIndex,
        spriteColorIndex: image.spriteColorIndex,
        ...(image.paletteId === undefined ? {} : { paletteId: image.paletteId }),
        ...(image.virtualColorMode === undefined ? {} : { virtualColorMode: image.virtualColorMode }),
        ...(image.twoColorIndices === undefined ? {} : { twoColorIndices: [...image.twoColorIndices] }),
        ...(image.charsetMulticolorIndices === undefined ? {} : {
          charsetMulticolorIndices: [...image.charsetMulticolorIndices]
        }),
        ...(image.charsetSimilarityThreshold === undefined ? {} : {
          charsetSimilarityThreshold: image.charsetSimilarityThreshold
        }),
        ...(spriteConfig === undefined ? {} : { spriteConfig: {
          columns: spriteConfig.columns, rows: spriteConfig.rows,
          multicolorIndices: [...spriteConfig.multicolorIndices],
          spriteColorIndices: [...spriteConfig.spriteColorIndices],
          overlayColorIndices: [...spriteConfig.overlayColorIndices]
        } }) },
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
