/** Image-wide PAL border sprites, stored as native 24 × 21 VIC frames. */
function normalizeC64BorderSprites(value) {
  const input = value ?? {};
  const object = item => item !== null && typeof item === 'object' && !Array.isArray(item);
  const color = item => Number.isInteger(item) && item >= 0 && item < 16;
  if (!object(input)) throw new Error('Border sprites require image settings.');
  const group = name => {
    const setting = input[name] ?? {};
    if (!object(setting) || setting.enabled !== undefined && typeof setting.enabled !== 'boolean' ||
        setting.mode !== undefined && !['hires', 'multicolor'].includes(setting.mode) ||
        setting.colorIndex !== undefined && !color(setting.colorIndex) ||
        name === 'vertical' && setting.xExpanded !== undefined && typeof setting.xExpanded !== 'boolean') {
      throw new Error('Border sprite groups require enabled, hires/multicolor, and a C64 color.');
    }
    return { enabled: setting.enabled ?? false, mode: setting.mode ?? 'hires', colorIndex: setting.colorIndex ?? 3,
      ...(name === 'vertical' && setting.xExpanded === false ? { xExpanded: false } : {}) };
  };
  if (input.multicolorIndices !== undefined && (!Array.isArray(input.multicolorIndices) ||
        input.multicolorIndices.length !== 2 || !input.multicolorIndices.every(color))) {
    throw new Error('Border sprites require two shared C64 colors.');
  }
  if (input.optimizeColors !== undefined && typeof input.optimizeColors !== 'boolean') {
    throw new Error('Border sprite color optimization must be a boolean.');
  }
  return { vertical: group('vertical'), sides: group('sides'),
    multicolorIndices: [...(input.multicolorIndices ?? [1, 14])],
    ...(input.optimizeColors ? { optimizeColors: true } : {}) };
}

function getC64BorderLayout(value) {
  const config = normalizeC64BorderSprites(value);
  const left = config.sides.enabled ? 24 : 0;
  const top = config.vertical.enabled ? 35 : 0;
  const bottom = config.vertical.enabled ? 37 : 0;
  return { enabled: config.vertical.enabled || config.sides.enabled,
    width: 320 + left * 2, height: 200 + top + bottom,
    coreX: left, coreY: top, coreWidth: 320, coreHeight: 200,
    left, right: left, top, bottom };
}

/** Sample one native sprite region through the document's existing virtual mapper. */
function prepareC64BorderSpriteRegion(source, palette, config, layout, offsetX, group, indices, cellWidth, virtualOptions, alignment = 0) {
  const { width, height, coreX, coreY } = layout;
  const virtualLayers = virtualOptions?.layers ?? [];
  if (!virtualLayers.some(layer => layer.pattern !== 'off')) return null;
  const vertical = group === 'top' || group === 'bottom';
  const gridWidth = vertical ? 384 / cellWidth : 24 / cellWidth;
  const gridHeight = vertical ? 42 : 200;
  const stepY = 1;
  const left = (group === 'right' ? coreX + 320 : 0) + offsetX + alignment;
  const top = group === 'top' ? -7 : group === 'bottom' ? coreY + 200 : coreY;
  const clip = { x: left, y: group === 'top' ? 0 : top,
    width: vertical ? width : 24, height: group === 'top' ? layout.top : group === 'bottom' ? layout.bottom : 200 };
  const originX = Math.floor((left - coreX) / cellWidth);
  const originY = Math.floor((top - coreY) / stepY);
  let mappedAny = false;
  const layers = virtualLayers.map(layer => {
    const sampled = new ImageData(gridWidth, gridHeight);
    for (let y = 0; y < gridHeight; y += 1) {
      for (let x = 0; x < gridWidth; x += 1) {
        const x0 = Math.max(0, clip.x, left + x * cellWidth);
        const x1 = Math.min(width, clip.x + clip.width, left + (x + 1) * cellWidth);
        const y0 = Math.max(0, clip.y, top + y * stepY);
        const y1 = Math.min(height, clip.y + clip.height, top + (y + 1) * stepY);
        let alpha = 0, count = 0;
        const linear = [0, 0, 0];
        for (let yy = y0; yy < y1; yy += 1) {
          for (let xx = x0; xx < x1; xx += 1) {
            const offset = (yy * width + xx) * 4;
            const coverage = layer.source.data[offset + 3] / 255;
            for (let channel = 0; channel < 3; channel += 1) {
              linear[channel] += srgbToLinear(layer.source.data[offset + channel]) * coverage;
            }
            alpha += coverage;
            count += 1;
          }
        }
        if (alpha > 0) {
          const offset = (y * gridWidth + x) * 4;
          for (let channel = 0; channel < 3; channel += 1) {
            sampled.data[offset + channel] = linearToSrgb(linear[channel] / alpha);
          }
          sampled.data[offset + 3] = 255 * alpha / count;
        }
      }
    }
    const mapped = mapC64VirtualColors(sampled, {
      virtualPalette: virtualOptions.virtualPalette, virtualColorMode: virtualOptions.virtualColorMode,
      palette, brightnessBands: virtualOptions.brightnessBands,
      paletteSettings: layer.paletteSettings, pattern: layer.pattern, dither: layer.dither,
      allowedColorIndices: indices, originX, originY
    });
    mappedAny ||= mapped !== null;
    return { target: mapped?.target ?? sampled, palette: mapped?.mapping.pixels ?? sampled };
  });
  const prepared = mappedAny ? {
    pixels: compositeC64LayerPixels(layers.map(layer => layer.target), gridWidth, gridHeight),
    palette: compositeC64LayerPixels(layers.map(layer => layer.palette), gridWidth, gridHeight),
    left, top, cellWidth, stepY
  } : null;
  return prepared;
}

function convertC64BorderSprites(source, palette, settings, backgroundColorIndex = 0, interlaced = false, virtualOptions) {
  if (typeof interlaced !== 'boolean') throw new Error('Border sprite interlace must be a boolean.');
  const config = normalizeC64BorderSprites(settings);
  const layout = getC64BorderLayout(config);
  const { width, height, coreX, coreY } = layout;
  if (source?.width !== width || source.height !== height || !ArrayBuffer.isView(source.data) ||
      source.data.BYTES_PER_ELEMENT !== 1 || source.data.length !== width * height * 4) {
    throw new Error(`Border sprites require a ${width} × ${height} physical-pixel source image.`);
  }
  if (!Array.isArray(palette) || palette.length !== 16 || palette.some((entry, index) =>
    entry?.index !== index || !Array.isArray(entry.rgb) || entry.rgb.length !== 3 ||
      entry.rgb.some(channel => !Number.isInteger(channel) || channel < 0 || channel > 255))) {
    throw new Error('Border sprites require an indexed 16-color C64 palette.');
  }
  if (!Number.isInteger(backgroundColorIndex) || backgroundColorIndex < 0 || backgroundColorIndex > 15) {
    throw new Error('Border sprites require a valid shared image background color.');
  }
  const colorPlan = virtualOptions?.colorPlan;
  const normalVertical = config.vertical.enabled && config.vertical.xExpanded === false;
  if (normalVertical && colorPlan) {
    const positions = colorPlan.verticalPositions;
    const count = 32 + (config.sides.enabled ? 20 : 0);
    if (!Array.isArray(positions) || positions.length !== 32 || positions.some((x, index) =>
        !Number.isInteger(x) || x < 0 || x > width - 24 || index % 8 && x < positions[index - 1] + 24) ||
        colorPlan.spriteCount !== count || colorPlan.phaseCount !== (interlaced ? 2 : 1) ||
        colorPlan.backgroundColorIndex !== backgroundColorIndex ||
        !config.optimizeColors && (JSON.stringify(colorPlan.multicolorIndices) !== JSON.stringify(config.multicolorIndices) ||
          !Array.isArray(colorPlan.colorIndices) || colorPlan.colorIndices.length !== count ||
          colorPlan.colorIndices.some((color, index) => color !== (index < 32 ? config.vertical : config.sides).colorIndex))) {
      throw new Error('Normal vertical sprites require a matching nonoverlapping placement plan.');
    }
  }
  if (config.optimizeColors) {
    const count = (config.vertical.enabled ? 32 : 0) + (config.sides.enabled ? 20 : 0);
    const color = value => Number.isInteger(value) && value >= 0 && value < 16;
    if (!colorPlan || !Array.isArray(colorPlan.multicolorIndices) || colorPlan.multicolorIndices.length !== 2 ||
        !colorPlan.multicolorIndices.every(color) || !Array.isArray(colorPlan.colorIndices) ||
        colorPlan.colorIndices.length !== count || !colorPlan.colorIndices.every(color) ||
        colorPlan.spriteCount !== count || colorPlan.phaseCount !== (interlaced ? 2 : 1) ||
        colorPlan.backgroundColorIndex !== backgroundColorIndex) {
      throw new Error('Optimized border colors require a completed color plan matching the current image.');
    }
    config.multicolorIndices = [...colorPlan.multicolorIndices];
  }
  const background = palette[backgroundColorIndex].rgb;
  const labs = palette.map(entry => rgbToOklab(...entry.rgb));
  const backgroundLinear = background.map(srgbToLinear);
  const virtualLayers = virtualOptions?.layers ?? [];
  for (const layer of virtualLayers) {
    if (layer.source?.width !== width || layer.source.height !== height ||
        layer.source.data?.length !== width * height * 4) {
      throw new Error('Border virtual-color layers require matching physical source dimensions.');
    }
  }
  const visibleLabs = new Map();
  function visibleRgbaLab(rgba) {
    const key = (rgba[0] | rgba[1] << 8 | rgba[2] << 16 | rgba[3] << 24) >>> 0;
    if (!visibleLabs.has(key)) {
      const alpha = rgba[3] / 255;
      const rgb = Array.from(rgba.subarray(0, 3), (channel, index) => linearToSrgb(
        srgbToLinear(channel) * alpha + backgroundLinear[index] * (1 - alpha)));
      visibleLabs.set(key, rgbToOklab(...rgb));
    }
    return visibleLabs.get(key);
  }
  function visibleLab(x, y) {
    const offset = (y * width + x) * 4;
    return visibleRgbaLab(source.data.subarray(offset, offset + 4));
  }
  function fitFrame(offsetX) {
    const pixels = new ImageData(width, height);
    const opaqueMask = new Uint8Array(width * height);
    for (let offset = 0; offset < pixels.data.length; offset += 4) pixels.data.set([...background, 255], offset);
    const sprites = [];
    const palettePixels = virtualOptions ? new ImageData(width, height) : null;
    const regionTargets = new Map();
    let hasVirtualMapping = false;

    function regionTarget(group, indices, cellWidth, alignment) {
      const key = `${group}:${indices.join(',')}:${cellWidth}:${alignment}`;
      if (!regionTargets.has(key)) {
        const prepared = prepareC64BorderSpriteRegion(source, palette, config, layout,
          offsetX, group, indices, cellWidth, virtualOptions, alignment);
        hasVirtualMapping ||= prepared !== null;
        regionTargets.set(key, prepared);
      }
      return regionTargets.get(key);
    }

    function addSprite(group, band, hardwareSlot, x, y, clip) {
      x += offsetX;
      clip = { ...clip, x: clip.x + offsetX };
      const vertical = group === 'top' || group === 'bottom';
      const setting = vertical ? config.vertical : config.sides;
      const colorIndex = config.optimizeColors ? colorPlan.colorIndices[sprites.length] : setting.colorIndex;
      const multicolor = setting.mode === 'multicolor';
      const xExpanded = vertical && config.vertical.xExpanded !== false;
      const rowHeights = Array(21).fill(1);
      const vicY = y + 50 - coreY;
      const sprite = { index: sprites.length, group, band, hardwareSlot, x, y,
        vicX: x + 24 - coreX, vicY,
        ...(vertical ? { vicYRegister: vicY & 0xff } : {}),
        mode: setting.mode, multicolor, colorIndex,
        xExpanded, yExpanded: false, displayWidth: xExpanded ? 48 : 24,
        displayHeight: rowHeights.reduce((sum, value) => sum + value, 0), rowHeights, clip: { ...clip },
        data: new Uint8Array(64) };
      // Native multicolor sprite codes: transparent, $D025, individual, $D026.
      const indices = multicolor
        ? [backgroundColorIndex, config.multicolorIndices[0], colorIndex, config.multicolorIndices[1]]
        : [backgroundColorIndex, colorIndex];
      const cellWidth = (multicolor ? 2 : 1) * (xExpanded ? 2 : 1);
      const cells = multicolor ? 12 : 24;
      const prepared = regionTarget(group, indices, cellWidth,
        normalVertical && vertical ? (x - offsetX) % cellWidth : 0);
      let rowY = y;
      for (let row = 0; row < 21; row += 1) {
        for (let column = 0; column < cells; column += 1) {
          const x0 = Math.max(0, clip.x, x + column * cellWidth);
          const x1 = Math.min(width, clip.x + clip.width, x + (column + 1) * cellWidth);
          const y0 = Math.max(0, clip.y, rowY);
          const y1 = Math.min(height, clip.y + clip.height, rowY + rowHeights[row]);
          let count = 0;
          const average = { lightness: 0, a: 0, b: 0 };
          let paletteRgba;
          if (prepared && x1 > x0 && y1 > y0) {
            const gx = Math.floor((x + column * cellWidth - prepared.left) / prepared.cellWidth);
            const gy = Math.floor((rowY - prepared.top) / prepared.stepY);
            const offset = (gy * prepared.pixels.width + gx) * 4;
            Object.assign(average, visibleRgbaLab(prepared.pixels.data.subarray(offset, offset + 4)));
            paletteRgba = prepared.palette.data.subarray(offset, offset + 4);
            count = 1;
          } else {
            for (let sampleY = y0; sampleY < y1; sampleY += 1) {
              for (let sampleX = x0; sampleX < x1; sampleX += 1) {
                const lab = visibleLab(sampleX, sampleY);
                average.lightness += lab.lightness; average.a += lab.a; average.b += lab.b;
                count += 1;
              }
            }
          }
          let code = 0;
          if (count) {
            average.lightness /= count; average.a /= count; average.b /= count;
            let error = Infinity;
            indices.forEach((index, candidate) => {
              const lab = labs[index];
              const distance = (average.lightness - lab.lightness) ** 2 + (average.a - lab.a) ** 2 + (average.b - lab.b) ** 2;
              if (distance < error) { error = distance; code = candidate; }
            });
          }
          const bit = column * (multicolor ? 2 : 1);
          sprite.data[row * 3 + Math.floor(bit / 8)] |= code << (multicolor ? 6 - bit % 8 : 7 - bit % 8);
          for (let paintY = y0; paintY < y1; paintY += 1) {
            for (let paintX = x0; paintX < x1; paintX += 1) {
              pixels.data.set([...palette[indices[code]].rgb, 255], (paintY * width + paintX) * 4);
              if (palettePixels) palettePixels.data.set(paletteRgba ?? [...palette[indices[code]].rgb, 255],
                (paintY * width + paintX) * 4);
              opaqueMask[paintY * width + paintX] = code === 0 ? 0 : 1;
            }
          }
        }
        rowY += rowHeights[row];
      }
      sprites.push(sprite);
    }
    if (config.vertical.enabled) {
      const slots = [3, 0, 1, 2, 5, 6, 7, 4];
      for (const group of ['top', 'bottom']) {
        const y = group === 'top' ? -7 : coreY + 200;
        const clip = { x: 0, y: group === 'top' ? 0 : coreY + 200,
          width, height: group === 'top' ? layout.top : layout.bottom };
        for (let band = 0; band < 2; band += 1) {
          slots.forEach((slot, column) => addSprite(group, band, slot,
            normalVertical ? colorPlan?.verticalPositions[sprites.length] ?? Math.round(column * (width - 24) / 7)
              : column * 48, y + band * 21, clip));
        }
      }
    }
    if (config.sides.enabled) {
      for (const group of ['left', 'right']) {
        const x = group === 'left' ? 0 : coreX + 320;
        for (let band = 0; band < 10; band += 1) {
          const lastBand = band === 9;
          // Spare slots start ten transparent rows early, so their normal DMA
          // finishes at the bitmap boundary before the bottom row reuses them.
          const y = coreY + (lastBand ? 179 : band * 21);
          const hardwareSlot = (group === 'left' ? 3 : 4) + (lastBand ? 2 : 0);
          const clip = { x, y: coreY + (lastBand ? 189 : 0), width: 24, height: lastBand ? 11 : 200 };
          addSprite(group, band, hardwareSlot, x, y, clip);
        }
      }
    }
    return { config, backgroundColorIndex, layout, width, height, pixels, opaqueMask, sprites,
      ...(config.optimizeColors || normalVertical && colorPlan ? { colorPlan } : {}),
      ...(hasVirtualMapping ? { palettePixels } : {}) };
  }
  const first = fitFrame(0);
  if (!interlaced) return first;
  const frames = [
    { ...first, phase: 0, offsetX: 0 },
    { ...fitFrame(1), phase: 1, offsetX: 1 }
  ];
  return { ...frames[0], interlaced: true, frames };
}

/** Keep the bitmap encoder's normal core dimensions and add borders only for display. */
function composeC64BorderPreview(core, result, rightSpill = false) {
  const layout = result?.layout;
  if (!layout || result.pixels?.width !== layout.width || result.pixels.height !== layout.height ||
      !ArrayBuffer.isView(result.pixels.data) || result.pixels.data.length !== layout.width * layout.height * 4 ||
      ![160, 320].includes(core?.width) || core.height !== 200 ||
      !ArrayBuffer.isView(core.data) || core.data.length !== core.width * core.height * 4) {
    throw new Error('Border preview requires a 160 or 320 × 200 bitmap and matching border pixels.');
  }
  const pixels = new ImageData(layout.width, layout.height);
  pixels.data.set(result.pixels.data);
  const scale = 320 / core.width;
  for (let y = 0; y < 200; y += 1) {
    for (let x = 0; x < 320; x += 1) {
      const offset = (y * core.width + Math.floor(x / scale)) * 4;
      pixels.data.set(core.data.subarray(offset, offset + 4), ((y + layout.coreY) * layout.width + x + layout.coreX) * 4);
    }
  }
  if (result.opaqueMask !== undefined) {
    if (!ArrayBuffer.isView(result.opaqueMask) || result.opaqueMask.BYTES_PER_ELEMENT !== 1 ||
        result.opaqueMask.length !== layout.width * layout.height) {
      throw new Error('Border preview requires a matching native sprite opacity mask.');
    }
    // A shifted left sprite may cover the bitmap's first background column.
    // Apply native sprite priority after placing the bitmap core.
    for (let index = 0; index < result.opaqueMask.length; index += 1) {
      if (result.opaqueMask[index]) pixels.data.set(result.pixels.data.subarray(index * 4, index * 4 + 4), index * 4);
    }
  }
  if (rightSpill && layout.right > 0) {
    if (!ArrayBuffer.isView(result.opaqueMask) || result.opaqueMask.BYTES_PER_ELEMENT !== 1 ||
        result.opaqueMask.length !== layout.width * layout.height) {
      throw new Error('Interlaced border spill requires the converted sprite opacity mask.');
    }
    // The shifted multicolor field's final doubled pixel extends one hires
    // pixel beyond the core. Sprite code zero reveals it through the border.
    for (let y = 0; y < 200; y += 1) {
      const target = (y + layout.coreY) * layout.width + layout.coreX + 320;
      if (result.opaqueMask[target] === 0) {
        const offset = (y * core.width + core.width - 1) * 4;
        pixels.data.set(core.data.subarray(offset, offset + 4), target * 4);
      }
    }
  }
  return pixels;
}
