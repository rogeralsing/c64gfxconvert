/** Fit a mixed hires/multicolor screen to one hardware character set. */
function createC64CharsetImage(sourceRGB, palette, settings, ditherAmount = 0) {
  const colorIndex = value => Number.isInteger(value) && value >= 0 && value < 16;
  if (!settings || !colorIndex(settings.backgroundColorIndex) ||
      !Array.isArray(settings.multicolorIndices) || settings.multicolorIndices.length !== 2 ||
      !settings.multicolorIndices.every(colorIndex)) {
    throw new Error('Character mode requires a background and two shared C64 colors.');
  }
  const similarityThreshold = settings.similarityThreshold ?? 35;
  if (!Number.isInteger(similarityThreshold) || similarityThreshold < 0 || similarityThreshold > 100) {
    throw new Error('Character tile similarity must be between 0 and 100.');
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
  const initialErrors = new Float64Array(1000);
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
    initialErrors[cell] = bestError;
    let pattern = patternByKey.get(key);
    if (!pattern) {
      pattern = { glyph: bestGlyph, count: 0, index: patterns.length, cells: [] };
      patternByKey.set(key, pattern);
      patterns.push(pattern);
    }
    pattern.count += 1;
    pattern.cells.push(cell);
    cellPatterns.push(pattern);
  }
  const unrestrictedCharacterCount = patterns.length;
  const initialAttributes = new Uint8Array(attributes);
  const initialPatterns = [...cellPatterns];
  let dictionary = patterns;
  let approximatedCellCount = 0;
  let similarityMergedCellCount = 0;
  const fittedColorErrors = new Float32Array(16 * 16);
  for (let target = 0; target < 16; target += 1) {
    for (let color = 0; color < 16; color += 1) {
      fittedColorErrors[target * 16 + color] = (labs[target][0] - labs[color][0]) ** 2 +
        (labs[target][1] - labs[color][1]) ** 2 + (labs[target][2] - labs[color][2]) ** 2;
    }
  }
  function renderedColor(glyph, attribute, x, y) {
    if (!(attribute & 8)) return glyph[y] & (128 >> x) ? attribute & 7 : backgroundColorIndex;
    const code = (glyph[y] >> (6 - (x & ~1))) & 3;
    return code === 0 ? backgroundColorIndex : code === 3 ? attribute & 7 : multicolorIndices[code - 1];
  }
  if (patterns.length > 256 || similarityThreshold > 0 && patterns.length > 1) {
    const strength = similarityThreshold / 100;
    // Bound both average loss and individual changed pixels; sharp details survive normal settings.
    const meanLimit = (0.15 * strength) ** 2 * 64;
    const peakLimit = similarityThreshold ? (0.1 + 0.9 * strength) ** 2 : 0;
    const epsilon = 1e-7;
    const rawRows = new Float64Array(16 * 8 * 256);
    const fittedRows = new Float64Array(rawRows.length);
    const targetColors = new Uint8Array(64);
    const rawDeltas = new Float64Array(8);
    const fittedDeltas = new Float64Array(8);
    const rawPairs = new Float64Array(16);
    const fittedPairs = new Float64Array(16);
    function buildRows(cell) {
      const originX = cell % 40 * 8;
      const originY = Math.floor(cell / 40) * 8;
      for (let y = 0; y < 8; y += 1) {
        for (let x = 0; x < 8; x += 1) {
          targetColors[y * 8 + x] = renderedColor(initialPatterns[cell].glyph, initialAttributes[cell], x, y);
        }
      }
      for (let attribute = 0; attribute < 16; attribute += 1) {
        const foreground = attribute & 7;
        const indices = [backgroundColorIndex, ...multicolorIndices, foreground];
        for (let row = 0; row < 8; row += 1) {
          const start = (originY + row) * 320 + originX;
          const table = attribute * 2048 + row * 256;
          if (attribute < 8) {
            let rawBase = 0;
            let fittedBase = 0;
            for (let x = 0; x < 8; x += 1) {
              const rawBackground = errors[(start + x) * 16 + backgroundColorIndex];
              const fittedBackground = fittedColorErrors[targetColors[row * 8 + x] * 16 + backgroundColorIndex];
              rawBase += rawBackground;
              fittedBase += fittedBackground;
              rawDeltas[7 - x] = errors[(start + x) * 16 + foreground] - rawBackground;
              fittedDeltas[7 - x] = fittedColorErrors[targetColors[row * 8 + x] * 16 + foreground] - fittedBackground;
            }
            rawRows[table] = rawBase;
            fittedRows[table] = fittedBase;
            for (let byte = 1; byte < 256; byte += 1) {
              const bit = byte & -byte;
              const channel = 31 - Math.clz32(bit);
              rawRows[table + byte] = rawRows[table + (byte ^ bit)] + rawDeltas[channel];
              fittedRows[table + byte] = fittedRows[table + (byte ^ bit)] + fittedDeltas[channel];
            }
          } else {
            for (let pair = 0; pair < 4; pair += 1) {
              for (let code = 0; code < 4; code += 1) {
                rawPairs[pair * 4 + code] = errors[(start + pair * 2) * 16 + indices[code]] +
                  errors[(start + pair * 2 + 1) * 16 + indices[code]];
                fittedPairs[pair * 4 + code] = fittedColorErrors[targetColors[row * 8 + pair * 2] * 16 + indices[code]] +
                  fittedColorErrors[targetColors[row * 8 + pair * 2 + 1] * 16 + indices[code]];
              }
            }
            for (let byte = 0; byte < 256; byte += 1) {
              const a = byte >> 6;
              const b = 4 + ((byte >> 4) & 3);
              const c = 8 + ((byte >> 2) & 3);
              const d = 12 + (byte & 3);
              rawRows[table + byte] = rawPairs[a] + rawPairs[b] + rawPairs[c] + rawPairs[d];
              fittedRows[table + byte] = fittedPairs[a] + fittedPairs[b] + fittedPairs[c] + fittedPairs[d];
            }
          }
        }
      }
    }
    function withinPeak(glyph, attribute, fittedError) {
      if (fittedError <= epsilon || peakLimit >= 1) return true;
      for (let y = 0; y < 8; y += 1) {
        for (let x = 0; x < 8; x += 1) {
          if (fittedColorErrors[targetColors[y * 8 + x] * 16 + renderedColor(glyph, attribute, x, y)] > peakLimit + epsilon) return false;
        }
      }
      return true;
    }
    const glyphScore = {};
    function scoreGlyph(pattern, cell, rankRaw) {
      let fallbackError = Infinity;
      let fallbackAttribute = 0;
      let acceptedRank = Infinity;
      let acceptedError = Infinity;
      let acceptedAttribute = -1;
      for (let attribute = 0; attribute < 16; attribute += 1) {
        let rawError = 0;
        let fittedError = 0;
        for (let row = 0; row < 8; row += 1) {
          const table = attribute * 2048 + row * 256 + pattern.glyph[row];
          rawError += rawRows[table];
          fittedError += fittedRows[table];
        }
        if (fittedError < fallbackError) { fallbackError = fittedError; fallbackAttribute = attribute; }
        const rank = rankRaw ? rawError : fittedError;
        if (rank < acceptedRank && fittedError <= meanLimit + epsilon &&
            rawError - initialErrors[cell] <= meanLimit + epsilon && withinPeak(pattern.glyph, attribute, fittedError)) {
          acceptedRank = rank;
          acceptedError = fittedError;
          acceptedAttribute = attribute;
        }
      }
      glyphScore.error = Math.max(0, acceptedAttribute >= 0 ? acceptedError : fallbackError);
      glyphScore.attribute = acceptedAttribute >= 0 ? acceptedAttribute : fallbackAttribute;
      glyphScore.accepted = acceptedAttribute >= 0;
      glyphScore.rank = acceptedAttribute >= 0 ? acceptedRank : Infinity;
      return glyphScore;
    }
    function sourceKey(cell) {
      const rgba = [];
      for (let y = 0; y < 8; y += 1) {
        const offset = ((Math.floor(cell / 40) * 8 + y) * 320 + cell % 40 * 8) * 4;
        rgba.push(...sourceRGB.data.subarray(offset, offset + 32));
      }
      return initialPatterns[cell].index + ':' + initialAttributes[cell] + ':' + String.fromCharCode(...rgba);
    }
    // One million costs and attributes at most: 5 MB, without retaining row lookup tables.
    const costs = new Float32Array(1000 * patterns.length);
    const choices = new Uint8Array(costs.length);
    const identicalCells = new Map();
    const cellKeys = [];
    for (let cell = 0; cell < 1000; cell += 1) {
      const key = sourceKey(cell);
      cellKeys.push(key);
      const previous = identicalCells.get(key);
      const offset = cell * patterns.length;
      if (previous !== undefined) {
        costs.set(costs.subarray(previous * patterns.length, (previous + 1) * patterns.length), offset);
        choices.set(choices.subarray(previous * patterns.length, (previous + 1) * patterns.length), offset);
        continue;
      }
      identicalCells.set(key, cell);
      buildRows(cell);
      for (const pattern of patterns) {
        const result = pattern === initialPatterns[cell]
          ? { error: 0, attribute: initialAttributes[cell], accepted: true } : scoreGlyph(pattern, cell, false);
        costs[offset + pattern.index] = result.error;
        choices[offset + pattern.index] = result.attribute | (result.accepted ? 16 : 0);
      }
    }
    const bestCosts = new Float32Array(1000).fill(Infinity);
    const covered = new Uint8Array(1000);
    const selected = new Set();
    dictionary = [];
    let next = patterns.reduce((best, pattern) => pattern.count > best.count ? pattern : best, patterns[0]);
    while (next && dictionary.length < 256) {
      dictionary.push(next);
      selected.add(next.index);
      for (let cell = 0; cell < 1000; cell += 1) {
        const offset = cell * patterns.length + next.index;
        bestCosts[cell] = Math.min(bestCosts[cell], costs[offset]);
        if (choices[offset] & 16) covered[cell] = 1;
      }
      let nextScore = -1;
      next = null;
      for (const pattern of patterns) {
        if (selected.has(pattern.index)) continue;
        let score = 0;
        let needed = false;
        for (const cell of pattern.cells) {
          if (!covered[cell]) { needed = true; score += bestCosts[cell]; }
        }
        if (needed && score > nextScore) { nextScore = score; next = pattern; }
      }
    }
    const assignments = new Map();
    for (let cell = 0; cell < 1000; cell += 1) {
      if (selected.has(initialPatterns[cell].index)) continue;
      const key = cellKeys[cell];
      let assignment = assignments.get(key);
      if (!assignment) {
        buildRows(cell);
        let bestAccepted = null;
        let bestFallback = null;
        for (const pattern of dictionary) {
          const result = scoreGlyph(pattern, cell, true);
          const candidate = { ...result, pattern };
          if (result.accepted && (!bestAccepted || result.rank < bestAccepted.rank)) bestAccepted = candidate;
          if (!bestFallback || result.error < bestFallback.error) bestFallback = candidate;
        }
        assignment = bestAccepted || bestFallback;
        assignments.set(key, assignment);
      }
      cellPatterns[cell] = assignment.pattern;
      attributes[cell] = assignment.attribute;
      let changed = false;
      for (let y = 0; y < 8 && !changed; y += 1) {
        for (let x = 0; x < 8; x += 1) {
          const before = renderedColor(initialPatterns[cell].glyph, initialAttributes[cell], x, y);
          const after = renderedColor(assignment.pattern.glyph, assignment.attribute, x, y);
          if (fittedColorErrors[before * 16 + after] > epsilon) { changed = true; break; }
        }
      }
      if (changed) {
        approximatedCellCount += 1;
        if (assignment.accepted && similarityThreshold) similarityMergedCellCount += 1;
      }
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
  const hiresCellCount = attributes.reduce((count, attribute) => count + (attribute < 8 ? 1 : 0), 0);
  return { pixels, charset, screen, colorRam, characterCount: dictionary.length,
    unrestrictedCharacterCount, approximatedCellCount, similarityMergedCellCount,
    hiresCellCount, multicolorCellCount: 1000 - hiresCellCount, similarityThreshold, backgroundColorIndex,
    multicolorIndices: [...multicolorIndices] };
}
