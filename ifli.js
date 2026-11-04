/**
 * Sample two 160 × 200 multicolor phases from a 320 × 200 hires source.
 * Phase A averages columns (0, 1), (2, 3), ...; phase B averages (1, 2),
 * (3, 4), ... . The final column is extended at the right edge of phase B.
 * Premultiplied-alpha averaging prevents transparent RGB from adding fringes.
 * Any positive even source width and positive height are supported.
 */
function sampleIfliPhases(source) {
  const { width, height, data } = source;
  if (!Number.isInteger(width) || width <= 0 || width % 2 !== 0 ||
      !Number.isInteger(height) || height <= 0) {
    throw new Error('IFLI source must have a positive even width and positive height.');
  }

  const phaseWidth = width / 2;
  const phases = [new ImageData(phaseWidth, height), new ImageData(phaseWidth, height)];

  for (let phase = 0; phase < phases.length; phase += 1) {
    const pixels = phases[phase].data;
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < phaseWidth; x += 1) {
        const firstColumn = x * 2 + phase;
        const secondColumn = Math.min(firstColumn + 1, width - 1);
        const first = (y * width + firstColumn) * 4;
        const second = (y * width + secondColumn) * 4;
        const destination = (y * phaseWidth + x) * 4;
        const firstAlpha = data[first + 3];
        const secondAlpha = data[second + 3];
        const alphaSum = firstAlpha + secondAlpha;

        pixels[destination + 3] = alphaSum / 2;
        if (pixels[destination + 3] === 0) continue;

        for (let channel = 0; channel < 3; channel += 1) {
          pixels[destination + channel] = (
            data[first + channel] * firstAlpha + data[second + channel] * secondAlpha
          ) / alphaSum;
        }
      }
    }
  }

  return phases;
}

/**
 * Resolve every retained virtual pair without changing image size.
 * Lines alternate components by row; checkers alternate by row and column.
 * Alpha and transparent/sentinel RGBA values remain unchanged.
 */
function resolveVirtualPaletteColors(mapping, virtualPalette, palette, pattern = 'lines') {
  if (pattern !== 'lines' && pattern !== 'checkers') {
    throw new Error('Virtual color pattern must be lines or checkers.');
  }
  const { width, height, data } = mapping.pixels;
  if (!Number.isInteger(width) || width <= 0 || !Number.isInteger(height) || height <= 0 ||
      !data || data.length !== width * height * 4 ||
      !mapping.virtualIndices || mapping.virtualIndices.length !== width * height) {
    throw new Error('Virtual color source must have positive dimensions and matching pixels and indices.');
  }

  const virtualByIndex = new Map(virtualPalette.map(color => [color.index, color]));
  const paletteByIndex = new Map(palette.map(color => [color.index, color]));
  const resolved = new ImageData(new Uint8ClampedArray(data), width, height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const pixel = y * width + x;
      const offset = pixel * 4;
      const index = mapping.virtualIndices[pixel];
      if (data[offset + 3] === 0 || index === 255) continue;
      const pair = virtualByIndex.get(index)?.colorIndices;
      if (!pair || pair.length !== 2 || !paletteByIndex.has(pair[0]) || !paletteByIndex.has(pair[1])) {
        throw new Error('Virtual color pixels require valid virtual pairs and C64 color indices.');
      }
      const component = (y + (pattern === 'checkers' ? x : 0)) & 1;
      resolved.data.set(paletteByIndex.get(pair[component]).rgb, offset);
    }
  }
  return resolved;
}

/**
 * Split exact even and odd source columns into the two IFLI frames.
 * Virtual components are resolved upstream, when enabled. No color mapping,
 * phase-dependent component swap, or pixel averaging is applied here.
 */
function splitIfliColumns(pixels) {
  const { width, height, data } = pixels;
  if (!Number.isInteger(width) || width <= 0 || width % 2 !== 0 ||
      !Number.isInteger(height) || height <= 0 || !data || data.length !== width * height * 4) {
    throw new Error('IFLI source must have a positive even width, positive height, and matching pixels.');
  }
  const frames = [new ImageData(width / 2, height), new ImageData(width / 2, height)];
  for (let pixel = 0; pixel < width * height; pixel += 1) {
    const source = pixel * 4;
    const destination = Math.floor(pixel / 2) * 4;
    frames[pixel % 2].data.set(data.subarray(source, source + 4), destination);
  }
  return frames;
}

/**
 * Place a multicolor frame on the hires display grid. Phase B starts one hires
 * pixel to the right, matching its sampling origin rather than moving a whole
 * wide pixel. The exposed left column uses the shared background; the right
 * edge is clipped to the same display width as phase A.
 */
function expandIfliFrame(source, phase, backgroundRgb) {
  const width = source.width * 2;
  const display = new ImageData(width, source.height);

  for (let y = 0; y < source.height; y += 1) {
    if (phase === 1) {
      const left = y * width * 4;
      display.data.set(backgroundRgb, left);
      display.data[left + 3] = 255;
    }

    for (let x = 0; x < source.width; x += 1) {
      const destinationX = x * 2 + phase;
      const pixel = source.data.subarray((y * source.width + x) * 4, (y * source.width + x + 1) * 4);
      const destination = (y * width + destinationX) * 4;
      display.data.set(pixel, destination);
      if (destinationX + 1 < width) display.data.set(pixel, destination + 4);
    }
  }

  return display;
}

/**
 * Show both raw multicolor frames as alternating hires columns for inspection.
 * Each pair of output columns is the exact RGBA from phase A, then phase B.
 * This diagnostic view does not blend colors or apply the playback phase offset.
 */
function mergeIfliFrames(first, second) {
  if (!Number.isInteger(first.width) || first.width <= 0 ||
      !Number.isInteger(first.height) || first.height <= 0 ||
      first.width !== second.width || first.height !== second.height) {
    throw new Error('IFLI frames must have matching positive dimensions.');
  }

  const merged = new ImageData(first.width * 2, first.height);
  for (let source = 0; source < first.data.length; source += 4) {
    const destination = source * 2;
    for (let channel = 0; channel < 4; channel += 1) {
      merged.data[destination + channel] = first.data[source + channel];
      merged.data[destination + 4 + channel] = second.data[source + channel];
    }
  }
  return merged;
}

/**
 * Blend opaque hardware frames equally on the same hires grid as playback.
 * Phase B starts one hires column to the right; its exposed left column uses
 * the shared background and its right edge is clipped by expandIfliFrame.
 */
function blendIfliFrames(first, second, backgroundRgb) {
  if (!Number.isInteger(first.width) || first.width <= 0 ||
      !Number.isInteger(first.height) || first.height <= 0 ||
      first.width !== second.width || first.height !== second.height) {
    throw new Error('IFLI frames must have matching positive dimensions.');
  }

  const a = expandIfliFrame(first, 0, backgroundRgb);
  const b = expandIfliFrame(second, 1, backgroundRgb);
  const blended = new ImageData(a.width, a.height);
  for (let offset = 0; offset < blended.data.length; offset += 4) {
    for (let channel = 0; channel < 3; channel += 1) {
      blended.data[offset + channel] = Math.round((a.data[offset + channel] + b.data[offset + channel]) / 2);
    }
    blended.data[offset + 3] = 255;
  }
  return blended;
}

/**
 * Build temporal two-color mixtures from nearby C64 brightness bands.
 * By default, bands may differ by two levels: one on either side of a midpoint.
 * Self-pairs preserve the base colors. Unordered color pairs remain distinct
 * even when different pairs happen to produce the same averaged RGB value.
 * White only mixes with yellow/light green; black only mixes with blue/brown.
 * RGB averages retain half-channel values; only the display hex is rounded.
 */
function buildIfliVirtualPalette(palette, brightnessBands, maxBandDifference = 2) {
  if (!Number.isInteger(maxBandDifference) || maxBandDifference < 0) {
    throw new Error('IFLI brightness-band difference must be a non-negative integer.');
  }

  const bandByColor = new Map();
  for (const [bandIndex, band] of brightnessBands.entries()) {
    for (const entry of band.colors) bandByColor.set(entry.color.index, bandIndex);
  }
  for (const color of palette) {
    if (!bandByColor.has(color.index)) {
      throw new Error('Every IFLI palette color must belong to a brightness band.');
    }
  }

  const result = [];
  for (let first = 0; first < palette.length; first += 1) {
    for (let second = first; second < palette.length; second += 1) {
      const a = palette[first];
      const b = palette[second];
      if (Math.abs(bandByColor.get(a.index) - bandByColor.get(b.index)) > maxBandDifference) continue;
      if ((a.index === 10 && (b.index === 7 || b.index === 13)) ||
          (b.index === 10 && (a.index === 7 || a.index === 13))) continue;
      if (a.index !== b.index) {
        if ((a.index === 1 && b.index !== 7 && b.index !== 13) ||
            (b.index === 1 && a.index !== 7 && a.index !== 13) ||
            (a.index === 0 && b.index !== 6 && b.index !== 9) ||
            (b.index === 0 && a.index !== 6 && a.index !== 9)) continue;
      }

      const [lower, higher] = a.index <= b.index ? [a, b] : [b, a];
      const rgb = a.rgb.map((channel, index) => (channel + b.rgb[index]) / 2);
      const hex = '#' + rgb.map(channel => Math.round(channel).toString(16).padStart(2, '0')).join('').toUpperCase();
      result.push({
        index: result.length,
        id: `ifli-${lower.index}-${higher.index}`,
        colorIndices: [lower.index, higher.index],
        brightnessBands: [bandByColor.get(lower.index), bandByColor.get(higher.index)],
        rgb,
        hex
      });
    }
  }

  return result;
}

/**
 * Snap pixels to one of 17 palette brightness rows, then choose chroma within it.
 * A virtual color's row is the sum of its component band indices (0 through 16).
 * Row lightness is measured from its actual mixture RGB values in Oklab; row
 * numbers do not imply equally spaced lightness. Ordered dither interpolates
 * between the two measured rows surrounding the source lightness. Index 255
 * denotes a fully transparent source pixel. Saved indices retain the exact
 * component pair; display pixels contain rounded mixture RGB and retain alpha.
 * Optional brightness limits clamp the selected row after dithering; they do
 * not rescale or change the source image.
 */
function mapToIfliVirtualPalette(source, virtualPalette, brightnessBands, ditherAmount = 0,
    { minLevel = 0, maxLevel = 16 } = {}) {
  if (!Number.isInteger(minLevel) || !Number.isInteger(maxLevel) ||
      minLevel < 0 || maxLevel > 16 || minLevel > maxLevel) {
    throw new RangeError('Virtual palette brightness limits require 0 <= minLevel <= maxLevel <= 16.');
  }
  if (virtualPalette.length === 0 || virtualPalette.length > 255) {
    throw new Error('IFLI mapping requires between 1 and 255 virtual colors.');
  }

  const levels = Array.from({ length: 17 }, () => []);
  for (const color of virtualPalette) {
    if (!Number.isInteger(color.index) || color.index < 0 || color.index >= 255) {
      throw new Error('IFLI virtual color indices must be integers from 0 to 254.');
    }
    const components = color.brightnessBands;
    if (!components || components.length !== 2 || [0, 1].some(index =>
      !Number.isInteger(components[index]) || components[index] < 0 || components[index] > 8 ||
      !brightnessBands[components[index]])) {
      throw new Error('IFLI virtual colors must refer to two existing brightness bands from 0 to 8.');
    }
    levels[components[0] + components[1]].push({ color, lab: rgbToOklab(...color.rgb) });
  }

  const levelLightness = levels.map((level, index) => {
    if (level.length === 0) {
      throw new Error(`IFLI virtual palette has no colors at brightness level ${index}.`);
    }
    return level.reduce((sum, entry) => sum + entry.lab.lightness, 0) / level.length;
  });

  const thresholds = [
    [0, 8, 2, 10],
    [12, 4, 14, 6],
    [3, 11, 1, 9],
    [15, 7, 13, 5]
  ];
  const pixels = new ImageData(new Uint8ClampedArray(source.data), source.width, source.height);
  const virtualIndices = new Uint8Array(source.width * source.height);
  virtualIndices.fill(255);

  for (let offset = 0; offset < source.data.length; offset += 4) {
    if (source.data[offset + 3] === 0) continue;

    const pixel = offset / 4;
    const lab = rgbToOklab(source.data[offset], source.data[offset + 1], source.data[offset + 2]);
    let brighter = 0;
    while (brighter < 16 && lab.lightness > levelLightness[brighter]) brighter += 1;
    const darker = Math.max(0, brighter - 1);
    const span = levelLightness[brighter] - levelLightness[darker];
    const fraction = span > 0
      ? Math.max(0, Math.min(1, (lab.lightness - levelLightness[darker]) / span)) : 0;
    let levelIndex = fraction < 0.5 ? darker : brighter;
    if (ditherAmount > 0 && darker !== brighter) {
      const x = pixel % source.width;
      const y = Math.floor(pixel / source.width);
      const threshold = (thresholds[y % 4][x % 4] + 0.5) / 16;
      const nearestBrighter = levelIndex === brighter ? 1 : 0;
      const brighterProbability = nearestBrighter + (fraction - nearestBrighter) * ditherAmount;
      levelIndex = threshold < brighterProbability ? brighter : darker;
    }
    levelIndex = Math.max(minLevel, Math.min(maxLevel, levelIndex));
    const level = levels[levelIndex];

    let nearest = level[0];
    let nearestChroma = Infinity;
    for (const candidate of level) {
      const distance = (lab.a - candidate.lab.a) ** 2 + (lab.b - candidate.lab.b) ** 2;
      if (distance < nearestChroma) {
        nearestChroma = distance;
        nearest = candidate;
      }
    }

    virtualIndices[pixel] = nearest.color.index;
    for (let channel = 0; channel < 3; channel += 1) {
      pixels.data[offset + channel] = Math.round(nearest.color.rgb[channel]);
    }
  }

  return { pixels, virtualIndices };
}

