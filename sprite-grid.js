/** Fit a grid of 24 × 21 C64 sprites, optionally beneath hires sprites. */
function createC64SpriteGridImage(sourceRGB, palette, settings, ditherAmount = 0) {
  const colorIndex = value => Number.isInteger(value) && value >= 0 && value <= 15;
  const colors = (value, length) => Array.isArray(value) && value.length === length && value.every(colorIndex);
  if (!settings || !Number.isInteger(settings.columns) || settings.columns < 1 ||
      !Number.isInteger(settings.rows) || settings.rows < 1 || typeof settings.overlay !== 'boolean' ||
      settings.columns * settings.rows * (settings.overlay ? 2 : 1) > 8) {
    throw new Error('Sprite grids require positive columns and rows using at most eight hardware sprites.');
  }
  if (!colorIndex(settings.backgroundColorIndex) || !colors(settings.multicolorIndices, 2) ||
      !colors(settings.spriteColorIndices, 8) || !colors(settings.overlayColorIndices, 8)) {
    throw new Error('Sprite grids require a background, two shared colors, and eight colors for each sprite layer.');
  }
  if (!Array.isArray(palette) || palette.length !== 16 || palette.some((color, index) =>
    color?.index !== index || !Array.isArray(color.rgb) || color.rgb.length !== 3 ||
      color.rgb.some(value => !Number.isInteger(value) || value < 0 || value > 255))) {
    throw new Error('Sprite grids require an indexed 16-color C64 palette.');
  }
  const { columns, rows, overlay, backgroundColorIndex, multicolorIndices,
    spriteColorIndices, overlayColorIndices } = settings;
  const width = columns * 24;
  const height = rows * 21;
  if (sourceRGB?.width !== width || sourceRGB.height !== height ||
      !ArrayBuffer.isView(sourceRGB.data) || sourceRGB.data.BYTES_PER_ELEMENT !== 1 ||
      sourceRGB.data.length !== width * height * 4) {
    throw new Error(`Sprite grids require a ${width} × ${height} source image.`);
  }
  const ditherMap = ArrayBuffer.isView(ditherAmount) &&
    ['[object Float32Array]', '[object Float64Array]'].includes(Object.prototype.toString.call(ditherAmount));
  if (ditherMap ? ditherAmount.length !== width * height ||
      ditherAmount.some(value => !Number.isFinite(value) || value < 0 || value > 1)
    : !Number.isFinite(ditherAmount) || ditherAmount < 0 || ditherAmount > 1) {
    throw new Error('Sprite dither amount must be between 0 and 1, or a matching float strength map.');
  }

  const labs = palette.map(color => {
    const lab = rgbToOklab(...color.rgb);
    return [lab.lightness, lab.a, lab.b];
  });
  const backgroundLinear = palette[backgroundColorIndex].rgb.map(srgbToLinear);
  const sourceLabs = new Map();
  function visibleLab(offset) {
    const rgba = sourceRGB.data.subarray(offset, offset + 4);
    const key = (rgba[0] | rgba[1] << 8 | rgba[2] << 16 | rgba[3] << 24) >>> 0;
    if (!sourceLabs.has(key)) {
      const opacity = rgba[3] / 255;
      const rgb = Array.from(rgba.subarray(0, 3), (channel, index) => linearToSrgb(
        srgbToLinear(channel) * opacity + backgroundLinear[index] * (1 - opacity)));
      const lab = rgbToOklab(...rgb);
      sourceLabs.set(key, [lab.lightness, lab.a, lab.b]);
    }
    return sourceLabs.get(key);
  }
  const pixels = new ImageData(width, height);
  const multicolorPixels = new ImageData(width, height);
  const overlayPixels = new ImageData(width, height);
  const sprites = [];
  const cells = columns * rows;
  // Lower hardware sprite numbers appear in front, so hires slots come first.
  for (let layer = 0; layer < (overlay ? 2 : 1); layer += 1) {
    const multicolor = !overlay || layer === 1;
    for (let cell = 0; cell < cells; cell += 1) {
      sprites.push({ index: sprites.length, column: cell % columns, row: Math.floor(cell / columns),
        colorIndex: (multicolor ? spriteColorIndices : overlayColorIndices)[cell], multicolor,
        data: new Uint8Array(64) });
    }
  }
  const thresholds = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];
  for (let cell = 0; cell < cells; cell += 1) {
    const multicolorSprite = sprites[cell + (overlay ? cells : 0)];
    const hiresSprite = overlay ? sprites[cell] : null;
    // C64 multicolor codes: transparent, $D025, individual color, $D026.
    const indices = [backgroundColorIndex, multicolorIndices[0], spriteColorIndices[cell], multicolorIndices[1]];
    const candidates = [];
    for (let code = 0; code < 4; code += 1) {
      for (let bits = 0; bits < (overlay ? 4 : 1); bits += 1) {
        const first = bits & 2 ? overlayColorIndices[cell] : indices[code];
        const second = bits & 1 ? overlayColorIndices[cell] : indices[code];
        // Duplicate colors must not consume the second dithering candidate.
        if (candidates.some(candidate => candidate.first === first && candidate.second === second)) continue;
        candidates.push({ code, bits, first, second, lab: [...labs[first], ...labs[second]] });
      }
    }
    for (let y = 0; y < 21; y += 1) {
      for (let pair = 0; pair < 12; pair += 1) {
        const x = multicolorSprite.column * 24 + pair * 2;
        const displayY = multicolorSprite.row * 21 + y;
        const offset = (displayY * width + x) * 4;
        const target = [...visibleLab(offset), ...visibleLab(offset + 4)];
        let best = null;
        let second = null;
        let bestError = Infinity;
        let secondError = Infinity;
        for (const candidate of candidates) {
          const error = candidate.lab.reduce((sum, value, channel) => sum + (target[channel] - value) ** 2, 0);
          if (error < bestError) {
            second = best; secondError = bestError;
            best = candidate; bestError = error;
          } else if (error < secondError) {
            second = candidate; secondError = error;
          }
        }
        const strength = ditherMap ? (ditherAmount[offset / 4] + ditherAmount[offset / 4 + 1]) / 2 : ditherAmount;
        if (strength && second) {
          let projection = 0;
          let length = 0;
          for (let channel = 0; channel < target.length; channel += 1) {
            const delta = second.lab[channel] - best.lab[channel];
            projection += (target[channel] - best.lab[channel]) * delta;
            length += delta * delta;
          }
          const coverage = length ? Math.max(0, Math.min(0.5, projection / length)) * strength : 0;
          if ((thresholds[displayY % 4][(x / 2) % 4] + 0.5) / 16 < coverage) best = second;
        }
        multicolorSprite.data[y * 3 + Math.floor(pair / 4)] |= best.code << (6 - (pair % 4) * 2);
        if (hiresSprite) hiresSprite.data[y * 3 + Math.floor(pair / 4)] |= best.bits << (6 - (pair % 4) * 2);
        for (let half = 0; half < 2; half += 1) {
          const pixelOffset = offset + half * 4;
          multicolorPixels.data.set([...palette[indices[best.code]].rgb, 255], pixelOffset);
          const covered = best.bits & (2 >> half);
          if (covered) overlayPixels.data.set([...palette[overlayColorIndices[cell]].rgb, 255], pixelOffset);
          pixels.data.set([...palette[covered ? overlayColorIndices[cell] : indices[best.code]].rgb, 255], pixelOffset);
        }
      }
    }
  }
  return { pixels, multicolorPixels, overlayPixels, sprites };
}
