/** Share the document's virtual mapper while restricting available native components. */
function mapC64VirtualColors(source, {
  virtualPalette, virtualColorMode, palette, brightnessBands, paletteSettings = {},
  pattern, dither = 0, allowedColorIndices, originX = 0, originY = 0
}) {
  if (pattern === 'off') return null;
  if (!['lines', 'checkers'].includes(pattern) || !['talent', 'computed'].includes(virtualColorMode)) {
    throw new Error('Virtual mapping requires a supported palette mode and pattern.');
  }
  if (!Number.isInteger(originX) || !Number.isInteger(originY) ||
      !Number.isInteger(source?.width) || source.width <= 0 ||
      !Number.isInteger(source.height) || source.height <= 0 ||
      source.data?.length !== source.width * source.height * 4) {
    throw new Error('Virtual mapping requires positive source dimensions and integer pattern origins.');
  }
  if (!Array.isArray(virtualPalette) || !virtualPalette.length) return null;
  const excluded = new Set(paletteSettings.excludedIndices ?? []);
  if (allowedColorIndices !== undefined) {
    if (!Array.isArray(allowedColorIndices) || allowedColorIndices.some(index =>
      !Number.isInteger(index) || index < 0 || index > 15)) {
      throw new Error('Virtual component colors must be C64 palette indices.');
    }
    const allowed = new Set(allowedColorIndices);
    for (const color of virtualPalette) {
      if (!color.colorIndices.every(index => allowed.has(index))) excluded.add(color.index);
    }
  }
  let inRange;
  if (virtualColorMode === 'talent') {
    const { minLightness, maxLightness } = getTalentLightnessLimits(paletteSettings, virtualPalette);
    if (!Number.isInteger(minLightness) || !Number.isInteger(maxLightness) ||
        minLightness < 0 || maxLightness > 100 || minLightness > maxLightness) {
      throw new RangeError('Talent lightness limits require 0 <= minLightness <= maxLightness <= 100.');
    }
    inRange = color => color.lightness * 100 >= minLightness - 1e-6 &&
      color.lightness * 100 <= maxLightness + 1e-6;
  } else {
    const { minLevel = 0, maxLevel = 16 } = paletteSettings;
    if (!Number.isInteger(minLevel) || !Number.isInteger(maxLevel) ||
        minLevel < 0 || maxLevel > 16 || minLevel > maxLevel) {
      throw new RangeError('Virtual palette brightness limits require 0 <= minLevel <= maxLevel <= 16.');
    }
    inRange = color => {
      const level = color.brightnessBands[0] + color.brightnessBands[1];
      return level >= minLevel && level <= maxLevel;
    };
  }
  if (!virtualPalette.some(color => !excluded.has(color.index) && inRange(color))) return null;
  const settings = { ...paletteSettings, excludedIndices: [...excluded] };

  // Four columns preserve the ordered dither phase; eight rows additionally
  // preserve Talent's paired-row dither lattice across region boundaries.
  const left = (originX % 4 + 4) % 4;
  const top = (originY % 8 + 8) % 8;
  let input = source;
  if (left || top) {
    input = new ImageData(source.width + left, source.height + top);
    for (let y = 0; y < source.height; y += 1) {
      input.data.set(source.data.subarray(y * source.width * 4, (y + 1) * source.width * 4),
        ((y + top) * input.width + left) * 4);
    }
  }
  const mapping = virtualColorMode === 'talent'
    ? mapToTalentVirtualPalette(input, virtualPalette, settings, dither)
    : mapToIfliVirtualPalette(input, virtualPalette, brightnessBands, dither, settings);
  const target = resolveVirtualPaletteColors(mapping, virtualPalette, palette, pattern);
  if (!left && !top) return { mapping, target };

  const crop = image => {
    const cropped = new ImageData(source.width, source.height);
    for (let y = 0; y < source.height; y += 1) {
      const offset = ((y + top) * image.width + left) * 4;
      cropped.data.set(image.data.subarray(offset, offset + source.width * 4), y * source.width * 4);
    }
    return cropped;
  };
  const virtualIndices = new Uint8Array(source.width * source.height);
  for (let y = 0; y < source.height; y += 1) {
    const offset = (y + top) * input.width + left;
    virtualIndices.set(mapping.virtualIndices.subarray(offset, offset + source.width), y * source.width);
  }
  return { mapping: { pixels: crop(mapping.pixels), virtualIndices }, target: crop(target) };
}
