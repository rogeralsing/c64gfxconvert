/** Fit a mixed hires/multicolor screen to one hardware character set. */
function createC64CharsetImage(sourceRGB, palette, settings, ditherAmount = 0) {
  const colorIndex = value => Number.isInteger(value) && value >= 0 && value < 16;
  if (!settings || !colorIndex(settings.backgroundColorIndex) ||
      !Array.isArray(settings.multicolorIndices) || settings.multicolorIndices.length !== 2 ||
      !settings.multicolorIndices.every(colorIndex)) {
    throw new Error('Character mode requires a background and two shared C64 colors.');
  }
  if (!Array.isArray(palette) || palette.length !== 16 || palette.some((color, index) =>
    color?.index !== index || !Array.isArray(color.rgb) || color.rgb.length !== 3 ||
    color.rgb.some(value => !Number.isInteger(value) || value < 0 || value > 255))) {
    throw new Error('Character mode requires an indexed 16-color C64 palette.');
  }
  if (sourceRGB?.width !== 320 || sourceRGB.height !== 200 ||
      !ArrayBuffer.isView(sourceRGB.data) || sourceRGB.data.BYTES_PER_ELEMENT !== 1 ||
      sourceRGB.data.length !== 320 * 200 * 4) {
    throw new Error('Character mode requires a 320 × 200 source image.');
  }
  const ditherMap = ArrayBuffer.isView(ditherAmount) &&
    ['[object Float32Array]', '[object Float64Array]'].includes(Object.prototype.toString.call(ditherAmount));
  if (ditherMap ? ditherAmount.length !== 320 * 200 ||
      ditherAmount.some(value => !Number.isFinite(value) || value < 0 || value > 1)
    : !Number.isFinite(ditherAmount) || ditherAmount < 0 || ditherAmount > 1) {
    throw new Error('Character dither amount must be between 0 and 1, or a matching float strength map.');
  }
  const { backgroundColorIndex, multicolorIndices } = settings;
  const labs = palette.map(color => {
    const lab = rgbToOklab(...color.rgb);
    return [lab.lightness, lab.a, lab.b];
  });
  const backgroundLinear = palette[backgroundColorIndex].rgb.map(srgbToLinear);
  const sourceLabs = new Float64Array(320 * 200 * 3);
  const errors = new Float32Array(320 * 200 * 16);
  const cachedLabs = new Map();
  for (let pixel = 0; pixel < 320 * 200; pixel += 1) {
    const rgba = sourceRGB.data.subarray(pixel * 4, pixel * 4 + 4);
    const key = (rgba[0] | rgba[1] << 8 | rgba[2] << 16 | rgba[3] << 24) >>> 0;
    if (!cachedLabs.has(key)) {
      const opacity = rgba[3] / 255;
      const rgb = opacity === 1 ? rgba.subarray(0, 3) : Array.from(rgba.subarray(0, 3), (channel, index) =>
        linearToSrgb(srgbToLinear(channel) * opacity + backgroundLinear[index] * (1 - opacity)));
      const lab = rgbToOklab(...rgb);
      cachedLabs.set(key, [lab.lightness, lab.a, lab.b]);
    }
    const lab = cachedLabs.get(key);
    sourceLabs.set(lab, pixel * 3);
    for (let color = 0; color < 16; color += 1) {
      errors[pixel * 16 + color] = (lab[0] - labs[color][0]) ** 2 +
        (lab[1] - labs[color][1]) ** 2 + (lab[2] - labs[color][2]) ** 2;
    }
  }
  const thresholds = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];
  function chooseCode(indices, pixel, paired, threshold) {
    let best = 0;
    let second = -1;
    let bestError = Infinity;
    let secondError = Infinity;
    for (let code = 0; code < indices.length; code += 1) {
      if (indices.indexOf(indices[code]) !== code) continue;
      const error = errors[pixel * 16 + indices[code]] + (paired ? errors[(pixel + 1) * 16 + indices[code]] : 0);
      if (error < bestError) {
        second = best; secondError = bestError;
        best = code; bestError = error;
      } else if (error < secondError) {
        second = code; secondError = error;
      }
    }
    const strength = ditherMap ? paired ? (ditherAmount[pixel] + ditherAmount[pixel + 1]) / 2
      : ditherAmount[pixel] : ditherAmount;
    if (strength && second >= 0) {
      let projection = 0;
      let length = 0;
      for (let channel = 0; channel < 3; channel += 1) {
        const delta = labs[indices[second]][channel] - labs[indices[best]][channel];
        projection += (sourceLabs[pixel * 3 + channel] - labs[indices[best]][channel]) * delta;
        if (paired) projection += (sourceLabs[(pixel + 1) * 3 + channel] - labs[indices[best]][channel]) * delta;
        length += delta * delta * (paired ? 2 : 1);
      }
      if (length && threshold < Math.max(0, Math.min(0.5, projection / length)) * strength) best = second;
    }
    return best;
  }

  const cellPatterns = [];
  const attributes = new Uint8Array(1000);
  const patterns = [];
  const patternByKey = new Map();
  for (let cell = 0; cell < 1000; cell += 1) {
    const originX = cell % 40 * 8;
    const originY = Math.floor(cell / 40) * 8;
    let bestError = Infinity;
    let bestGlyph;
    for (let attribute = 0; attribute < 16; attribute += 1) {
      const multicolor = attribute >= 8;
      const indices = multicolor ? [backgroundColorIndex, ...multicolorIndices, attribute & 7]
        : [backgroundColorIndex, attribute];
      const glyph = new Uint8Array(8);
      let error = 0;
      for (let y = 0; y < 8; y += 1) {
        for (let x = 0; x < 8; x += multicolor ? 2 : 1) {
          const pixel = (originY + y) * 320 + originX + x;
          const threshold = (thresholds[(originY + y) % 4][((originX + x) / (multicolor ? 2 : 1)) % 4] + 0.5) / 16;
          const code = chooseCode(indices, pixel, multicolor, threshold);
          glyph[y] |= code << (multicolor ? 6 - x : 7 - x);
          error += errors[pixel * 16 + indices[code]];
          if (multicolor) error += errors[(pixel + 1) * 16 + indices[code]];
        }
      }
      if (error < bestError) {
        bestError = error;
        bestGlyph = glyph;
        attributes[cell] = attribute;
      }
    }
    const key = String.fromCharCode(...bestGlyph);
    let pattern = patternByKey.get(key);
    if (!pattern) {
      pattern = { glyph: bestGlyph, count: 0, index: patterns.length };
      patternByKey.set(key, pattern);
      patterns.push(pattern);
    }
    pattern.count += 1;
    cellPatterns.push(pattern);
  }
  const unrestrictedCharacterCount = patterns.length;
  let dictionary = patterns;
  let approximatedCellCount = 0;
  if (patterns.length > 256) {
    // Weighted farthest-point sampling retains common glyphs and covers shape diversity.
    const bitCounts = new Uint8Array(256);
    for (let value = 1; value < 256; value += 1) bitCounts[value] = bitCounts[value >> 1] + (value & 1);
    const distances = new Uint8Array(patterns.length).fill(65);
    const selected = new Set();
    dictionary = [];
    let next = patterns.reduce((best, pattern) => pattern.count > best.count ? pattern : best, patterns[0]);
    while (dictionary.length < 256) {
      dictionary.push(next);
      selected.add(next.index);
      let nextScore = -1;
      let nextPattern;
      for (const pattern of patterns) {
        if (selected.has(pattern.index)) continue;
        let distance = 0;
        for (let row = 0; row < 8; row += 1) distance += bitCounts[pattern.glyph[row] ^ next.glyph[row]];
        distances[pattern.index] = Math.min(distances[pattern.index], distance);
        const score = distances[pattern.index] * Math.sqrt(pattern.count);
        if (score > nextScore) { nextScore = score; nextPattern = pattern; }
      }
      next = nextPattern;
    }

    // Row-byte lookup tables compare all stored glyphs and legal cell attributes.
    const rowErrors = new Float64Array(16 * 8 * 256);
    const deltas = new Float64Array(8);
    const pairErrors = new Float64Array(16);
    const fittedColorErrors = new Float32Array(16 * 16);
    for (let target = 0; target < 16; target += 1) {
      for (let color = 0; color < 16; color += 1) {
        fittedColorErrors[target * 16 + color] = (labs[target][0] - labs[color][0]) ** 2 +
          (labs[target][1] - labs[color][1]) ** 2 + (labs[target][2] - labs[color][2]) ** 2;
      }
    }
    for (let cell = 0; cell < 1000; cell += 1) {
      if (selected.has(cellPatterns[cell].index)) continue;
      const originX = cell % 40 * 8;
      const originY = Math.floor(cell / 40) * 8;
      const originalAttribute = attributes[cell];
      const originalIndices = [backgroundColorIndex, ...multicolorIndices, originalAttribute & 7];
      // Approximate the fitted image, including its dithering, rather than reverting to raw RGB.
      for (let row = 0; row < 8; row += 1) {
        const byte = cellPatterns[cell].glyph[row];
        for (let x = 0; x < 8; x += 1) {
          const color = originalAttribute & 8 ? originalIndices[(byte >> (6 - (x & ~1))) & 3]
            : byte & (128 >> x) ? originalAttribute & 7 : backgroundColorIndex;
          const pixel = (originY + row) * 320 + originX + x;
          errors.set(fittedColorErrors.subarray(color * 16, color * 16 + 16), pixel * 16);
        }
      }
      for (let attribute = 0; attribute < 16; attribute += 1) {
        const multicolor = attribute >= 8;
        const foreground = attribute & 7;
        for (let row = 0; row < 8; row += 1) {
          const start = (originY + row) * 320 + originX;
          const table = attribute * 2048 + row * 256;
          if (!multicolor) {
            let backgroundError = 0;
            for (let x = 0; x < 8; x += 1) {
              const background = errors[(start + x) * 16 + backgroundColorIndex];
              backgroundError += background;
              deltas[7 - x] = errors[(start + x) * 16 + foreground] - background;
            }
            rowErrors[table] = backgroundError;
            for (let byte = 1; byte < 256; byte += 1) {
              const bit = byte & -byte;
              rowErrors[table + byte] = rowErrors[table + (byte ^ bit)] + deltas[31 - Math.clz32(bit)];
            }
          } else {
            const indices = [backgroundColorIndex, ...multicolorIndices, foreground];
            for (let pair = 0; pair < 4; pair += 1) {
              for (let code = 0; code < 4; code += 1) {
                pairErrors[pair * 4 + code] = errors[(start + pair * 2) * 16 + indices[code]] +
                  errors[(start + pair * 2 + 1) * 16 + indices[code]];
              }
            }
            for (let byte = 0; byte < 256; byte += 1) {
              rowErrors[table + byte] = pairErrors[byte >> 6] + pairErrors[4 + ((byte >> 4) & 3)] +
                pairErrors[8 + ((byte >> 2) & 3)] + pairErrors[12 + (byte & 3)];
            }
          }
        }
      }
      let bestError = Infinity;
      let bestPattern;
      for (const pattern of dictionary) {
        for (let attribute = 0; attribute < 16; attribute += 1) {
          let error = 0;
          for (let row = 0; row < 8; row += 1) error += rowErrors[attribute * 2048 + row * 256 + pattern.glyph[row]];
          if (error < bestError) {
            bestError = error;
            bestPattern = pattern;
            attributes[cell] = attribute;
          }
        }
      }
      if (bestPattern !== cellPatterns[cell]) approximatedCellCount += 1;
      cellPatterns[cell] = bestPattern;
    }
  }
  const charset = new Uint8Array(2048);
  const screen = new Uint8Array(1000);
  const colorRam = new Uint8Array(attributes);
  const dictionaryIndices = new Map();
  dictionary.forEach((pattern, index) => {
    dictionaryIndices.set(pattern, index);
    charset.set(pattern.glyph, index * 8);
  });
  const pixels = new ImageData(320, 200);
  for (let cell = 0; cell < 1000; cell += 1) {
    const character = dictionaryIndices.get(cellPatterns[cell]);
    screen[cell] = character;
    const attribute = colorRam[cell];
    const multicolor = Boolean(attribute & 8);
    const indices = [backgroundColorIndex, ...multicolorIndices, attribute & 7];
    for (let y = 0; y < 8; y += 1) {
      const byte = charset[character * 8 + y];
      for (let x = 0; x < 8; x += 1) {
        const color = multicolor ? indices[(byte >> (6 - (x & ~1))) & 3]
          : byte & (128 >> x) ? attribute & 7 : backgroundColorIndex;
        const pixel = ((Math.floor(cell / 40) * 8 + y) * 320 + cell % 40 * 8 + x) * 4;
        pixels.data.set([...palette[color].rgb, 255], pixel);
      }
    }
  }
  return { pixels, charset, screen, colorRam, characterCount: dictionary.length,
    unrestrictedCharacterCount, approximatedCellCount, backgroundColorIndex,
    multicolorIndices: [...multicolorIndices] };
}
