/**
 * Find the minimum-error FLI allocation for every 4 × 8 logical-pixel tile.
 * Squared brightness-band error has priority; squared Oklab chroma error breaks ties.
 * The existing color-conversion helpers are used only when flattening transparency.
 *
 * tileColors contains one palette index per tile, in row-major tile order.
 * rowColors contains two indices per tile row: (tileIndex * 8 + row) * 2.
 * Optional overlayMask contains two hires bits per logical pixel; only the
 * uncovered halves contribute error to the jointly chosen tile and row colors.
 * An overlayColorIndex reserves that color for sprites in each active strip.
 */
function optimizeFliImage(source, palette, brightnessBands, backgroundColorIndex, overlayMask = null,
  overlayColorIndex = null) {
  const result = optimizeFliFrames([source], palette, brightnessBands, backgroundColorIndex,
    overlayMask, overlayColorIndex);
  return { ...result.frames[0], backgroundColorIndex: result.backgroundColorIndex, tileColors: result.tileColors };
}

/**
 * Jointly optimize two IFLI phases. Both frames share each tile's one fixed color,
 * while every frame row retains its own two free colors. The summed error across
 * both frames determines the shared tile color; the frames are not fitted separately.
 */
function optimizeIfliImages(first, second, palette, brightnessBands, backgroundColorIndex) {
  return optimizeFliFrames([first, second], palette, brightnessBands, backgroundColorIndex);
}

/**
 * Exact MCI fit: both standard multicolor bitmap phases share Color RAM, while
 * each phase has its own two screen colors fixed throughout every 4 × 8 tile.
 * The shared tile color minimizes summed brightness-band SSE, then chroma SSE.
 * rowColors repeats each screen pair over eight rows for the common frame API.
 */
function optimizeMciImages(first, second, palette, brightnessBands, backgroundColorIndex) {
  const { width, height, brightnessError, chromaError, frameTargets } = prepareC64FittingTargets(
    [first, second], palette, brightnessBands, backgroundColorIndex
  );
  const epsilon = 1e-12;
  const isBetter = (primary, secondary, bestPrimary, bestSecondary) =>
    primary < bestPrimary - epsilon ||
    (Math.abs(primary - bestPrimary) <= epsilon && secondary < bestSecondary - epsilon);
  const { triples, mappings, primaryCosts, secondaryCosts } = prepareMulticolorBitmapAllocations(
    brightnessError, chromaError, backgroundColorIndex
  );
  const columns = width / 4;
  const tileCount = columns * height / 8;
  const tileColors = new Uint8Array(tileCount);
  const frames = frameTargets.map(() => ({
    pixels: new ImageData(width, height),
    rowColors: new Uint8Array(tileCount * 16)
  }));
  const histogram = new Uint8Array(16);
  const bestPrimary = new Float64Array(32);
  const bestSecondary = new Float64Array(32);
  const bestTriples = new Uint16Array(32);

  for (let tileY = 0; tileY < height; tileY += 8) {
    for (let tileX = 0; tileX < width; tileX += 4) {
      bestPrimary.fill(Infinity);
      bestSecondary.fill(Infinity);
      for (let phase = 0; phase < 2; phase += 1) {
        histogram.fill(0);
        const targets = frameTargets[phase];
        for (let row = 0; row < 8; row += 1) {
          const offset = (tileY + row) * width + tileX;
          for (let column = 0; column < 4; column += 1) histogram[targets[offset + column]] += 1;
        }
        for (let triple = 0; triple < triples.length; triple += 1) {
          let primary = 0;
          let secondary = 0;
          const offset = triple * 16;
          for (let target = 0; target < 16; target += 1) {
            const count = histogram[target];
            if (count === 0) continue;
            primary += count * primaryCosts[offset + target];
            secondary += count * secondaryCosts[offset + target];
          }
          // Each member can occupy the shared Color RAM slot. Conditioning on
          // that slot lets both phases choose their own exact best screen pair.
          for (const shared of triples[triple]) {
            const candidate = phase * 16 + shared;
            if (isBetter(primary, secondary, bestPrimary[candidate], bestSecondary[candidate])) {
              bestPrimary[candidate] = primary;
              bestSecondary[candidate] = secondary;
              bestTriples[candidate] = triple;
            }
          }
        }
      }

      let tileColor = 0;
      let minimumPrimary = Infinity;
      let minimumSecondary = Infinity;
      for (let shared = 0; shared < 16; shared += 1) {
        if (shared === backgroundColorIndex) continue;
        const primary = bestPrimary[shared] + bestPrimary[16 + shared];
        const secondary = bestSecondary[shared] + bestSecondary[16 + shared];
        if (isBetter(primary, secondary, minimumPrimary, minimumSecondary)) {
          tileColor = shared;
          minimumPrimary = primary;
          minimumSecondary = secondary;
        }
      }
      // A background-valued Color RAM slot needs at most two non-background
      // colors per phase. An unused common non-background filler represents
      // that case too, so the search above still covers every legal fit.
      const tileIndex = tileY / 8 * columns + tileX / 4;
      tileColors[tileIndex] = tileColor;
      for (let phase = 0; phase < 2; phase += 1) {
        const triple = bestTriples[phase * 16 + tileColor];
        const screenColors = triples[triple].filter(color => color !== tileColor);
        const { pixels, rowColors } = frames[phase];
        for (let row = 0; row < 8; row += 1) {
          rowColors.set(screenColors, tileIndex * 16 + row * 2);
          for (let column = 0; column < 4; column += 1) {
            const pixel = (tileY + row) * width + tileX + column;
            const color = mappings[triple * 16 + frameTargets[phase][pixel]];
            pixels.data.set(palette[color].rgb, pixel * 4);
            pixels.data[pixel * 4 + 3] = 255;
          }
        }
      }
    }
  }
  return { frames, backgroundColorIndex, tileColors };
}

/**
 * Exact multicolor bitmap fit: each 4 × 8 tile has the image background and
 * three colors fixed for all 32 pixels. Brightness-band SSE takes priority over
 * Oklab chroma SSE. tileColors stores three indices per tile in row-major order.
 */
function optimizeMulticolorBitmapImage(source, palette, brightnessBands, backgroundColorIndex) {
  const { width, height, brightnessError, chromaError, frameTargets } = prepareC64FittingTargets(
    [source], palette, brightnessBands, backgroundColorIndex
  );
  const epsilon = 1e-12;
  const isBetter = (primary, secondary, bestPrimary, bestSecondary) =>
    primary < bestPrimary - epsilon ||
    (Math.abs(primary - bestPrimary) <= epsilon && secondary < bestSecondary - epsilon);
  const { triples, mappings, primaryCosts, secondaryCosts } = prepareMulticolorBitmapAllocations(
    brightnessError, chromaError, backgroundColorIndex
  );

  const columns = width / 4;
  const tileColors = new Uint8Array(columns * height / 8 * 3);
  const pixels = new ImageData(width, height);
  const targets = frameTargets[0];
  const histogram = new Uint8Array(16);
  for (let tileY = 0; tileY < height; tileY += 8) {
    for (let tileX = 0; tileX < width; tileX += 4) {
      histogram.fill(0);
      for (let row = 0; row < 8; row += 1) {
        const offset = (tileY + row) * width + tileX;
        for (let column = 0; column < 4; column += 1) histogram[targets[offset + column]] += 1;
      }
      let bestTriple = 0;
      let bestPrimary = Infinity;
      let bestSecondary = Infinity;
      // Every legal allocation with at most three non-background colors occurs
      // in these 455 triples, with unused fillers if necessary. Pixels are
      // independent once a triple is fixed, so histogram scoring is exhaustive.
      for (let triple = 0; triple < triples.length; triple += 1) {
        let primary = 0;
        let secondary = 0;
        const offset = triple * 16;
        for (let target = 0; target < 16; target += 1) {
          const count = histogram[target];
          if (count === 0) continue;
          primary += count * primaryCosts[offset + target];
          secondary += count * secondaryCosts[offset + target];
          if (primary > bestPrimary + epsilon) break;
        }
        if (isBetter(primary, secondary, bestPrimary, bestSecondary)) {
          bestTriple = triple;
          bestPrimary = primary;
          bestSecondary = secondary;
        }
        if (bestPrimary === 0 && bestSecondary === 0) break;
      }
      const tileIndex = tileY / 8 * columns + tileX / 4;
      tileColors.set(triples[bestTriple], tileIndex * 3);
      for (let row = 0; row < 8; row += 1) {
        for (let column = 0; column < 4; column += 1) {
          const pixel = (tileY + row) * width + tileX + column;
          const color = mappings[bestTriple * 16 + targets[pixel]];
          pixels.data.set(palette[color].rgb, pixel * 4);
          pixels.data[pixel * 4 + 3] = 255;
        }
      }
    }
  }
  return { pixels, backgroundColorIndex, tileColors };
}

/** Exhaustive standard bitmap palettes and their exact per-target costs. */
function prepareMulticolorBitmapAllocations(brightnessError, chromaError, backgroundColorIndex) {
  const epsilon = 1e-12;
  const isBetter = (primary, secondary, bestPrimary, bestSecondary) =>
    primary < bestPrimary - epsilon ||
    (Math.abs(primary - bestPrimary) <= epsilon && secondary < bestSecondary - epsilon);
  const triples = [];
  for (let first = 0; first < 16; first += 1) {
    if (first === backgroundColorIndex) continue;
    for (let second = first + 1; second < 16; second += 1) {
      if (second === backgroundColorIndex) continue;
      for (let third = second + 1; third < 16; third += 1) {
        if (third !== backgroundColorIndex) triples.push([first, second, third]);
      }
    }
  }
  const mappings = new Uint8Array(triples.length * 16);
  const primaryCosts = new Float64Array(mappings.length);
  const secondaryCosts = new Float64Array(mappings.length);
  for (let triple = 0; triple < triples.length; triple += 1) {
    for (let target = 0; target < 16; target += 1) {
      const errorOffset = target * 16;
      let best = backgroundColorIndex;
      for (const candidate of triples[triple]) {
        if (isBetter(brightnessError[errorOffset + candidate], chromaError[errorOffset + candidate],
          brightnessError[errorOffset + best], chromaError[errorOffset + best])) best = candidate;
      }
      const offset = triple * 16 + target;
      mappings[offset] = best;
      primaryCosts[offset] = brightnessError[errorOffset + best];
      secondaryCosts[offset] = chromaError[errorOffset + best];
    }
  }
  return { triples, mappings, primaryCosts, secondaryCosts };
}

/**
 * Exact hires bitmap fit: each 8 × 8 square-pixel tile has two arbitrary C64
 * colors. No image background is reserved. Brightness-band SSE takes priority
 * over Oklab chroma SSE; tileColors stores two indices per row-major tile.
 */
function optimizeHiresBitmapImage(source, palette, brightnessBands) {
  const { pixels, colors } = fitC64TwoColorCells(source, palette, brightnessBands, 8);
  return { pixels, tileColors: colors };
}

/**
 * Exact AFLI fit: each eight-pixel scanline of an 8 × 8 tile has two arbitrary
 * C64 colors, independent of other rows. rowColors stores two indices at
 * (tileIndex * 8 + rowWithinTile) * 2, with tiles in row-major order. No image
 * background is reserved; brightness-band SSE has priority over chroma SSE.
 */
function optimizeAfliImage(source, palette, brightnessBands, overlayMask = null, overlayColorIndex = null) {
  const { pixels, colors } = fitC64TwoColorCells(source, palette, brightnessBands, 1,
    overlayMask, overlayColorIndex);
  return { pixels, rowColors: colors };
}

/** Shared exhaustive two-color search for 8 × 8 Hires and 8 × 1 AFLI cells. */
function fitC64TwoColorCells(source, palette, brightnessBands, cellHeight, overlayMask = null,
  overlayColorIndex = null) {
  const { width, height } = source;
  if (!Number.isInteger(width) || width <= 0 || width % 8 !== 0 ||
      !Number.isInteger(height) || height <= 0 || height % 8 !== 0) {
    const mode = cellHeight === 1 ? 'AFLI' : 'Hires';
    throw new Error(`${mode} dimensions must be positive multiples of 8 × 8 pixels.`);
  }
  if (overlayMask !== null && (!ArrayBuffer.isView(overlayMask) ||
      overlayMask.BYTES_PER_ELEMENT !== 1 || overlayMask.length !== width * height ||
      overlayMask.some(value => value !== 0 && value !== 1))) {
    throw new Error('AFLI overlay mask must contain one binary byte per pixel.');
  }
  if (overlayColorIndex !== null && (!overlayMask || !Number.isInteger(overlayColorIndex) ||
      overlayColorIndex < 0 || overlayColorIndex >= palette.length)) {
    throw new Error('Choose a valid overlay color with its sprite mask.');
  }
  // A fixed black matte handles alpha independently of the selected image BG.
  // Black remains optional in every tile's searched pair.
  const { brightnessError, chromaError, frameTargets } = prepareC64FittingTargets(
    [source], palette, brightnessBands, 0
  );
  const epsilon = 1e-12;
  const isBetter = (primary, secondary, bestPrimary, bestSecondary) =>
    primary < bestPrimary - epsilon ||
    (Math.abs(primary - bestPrimary) <= epsilon && secondary < bestSecondary - epsilon);
  const pairs = [];
  for (let first = 0; first < 16; first += 1) {
    for (let second = first + 1; second < 16; second += 1) pairs.push([first, second]);
  }
  const mappings = new Uint8Array(pairs.length * 16);
  const primaryCosts = new Float64Array(mappings.length);
  const secondaryCosts = new Float64Array(mappings.length);
  for (let pair = 0; pair < pairs.length; pair += 1) {
    const [first, second] = pairs[pair];
    for (let target = 0; target < 16; target += 1) {
      const errorOffset = target * 16;
      const best = isBetter(brightnessError[errorOffset + second], chromaError[errorOffset + second],
        brightnessError[errorOffset + first], chromaError[errorOffset + first]) ? second : first;
      const offset = pair * 16 + target;
      mappings[offset] = best;
      primaryCosts[offset] = brightnessError[errorOffset + best];
      secondaryCosts[offset] = chromaError[errorOffset + best];
    }
  }

  const columns = width / 8;
  const colors = new Uint8Array(columns * height / cellHeight * 2);
  const pixels = new ImageData(width, height);
  const targets = frameTargets[0];
  const histogram = new Uint8Array(16);
  for (let tileY = 0; tileY < height; tileY += cellHeight) {
    for (let tileX = 0; tileX < width; tileX += 8) {
      histogram.fill(0);
      let hasOverlay = false;
      for (let row = 0; row < cellHeight; row += 1) {
        const offset = (tileY + row) * width + tileX;
        for (let column = 0; column < 8; column += 1) {
          const pixel = offset + column;
          // A front-priority sprite hides this pixel, so it cannot consume one
          // of the two colors needed by the visible bitmap pixels in this row.
          if (!overlayMask || overlayMask[pixel] === 0) histogram[targets[pixel]] += 1;
          else hasOverlay = true;
        }
      }
      let bestPair = 0;
      let bestPrimary = Infinity;
      let bestSecondary = Infinity;
      // These 120 pairs cover every two-color allocation, including a single
      // used color with an unused partner. Per-pixel nearest choices are exact
      // for a fixed pair, so the weighted histogram finds the global cell fit.
      for (let pair = 0; pair < pairs.length; pair += 1) {
        if (hasOverlay && pairs[pair].includes(overlayColorIndex)) continue;
        let primary = 0;
        let secondary = 0;
        const offset = pair * 16;
        for (let target = 0; target < 16; target += 1) {
          const count = histogram[target];
          if (count === 0) continue;
          primary += count * primaryCosts[offset + target];
          secondary += count * secondaryCosts[offset + target];
          if (primary > bestPrimary + epsilon) break;
        }
        if (isBetter(primary, secondary, bestPrimary, bestSecondary)) {
          bestPair = pair;
          bestPrimary = primary;
          bestSecondary = secondary;
        }
        if (bestPrimary === 0 && bestSecondary === 0) break;
      }
      const tileIndex = Math.floor(tileY / 8) * columns + tileX / 8;
      const colorOffset = (tileIndex * (8 / cellHeight) + (tileY % 8) / cellHeight) * 2;
      colors.set(pairs[bestPair], colorOffset);
      for (let row = 0; row < cellHeight; row += 1) {
        for (let column = 0; column < 8; column += 1) {
          const pixel = (tileY + row) * width + tileX + column;
          const color = mappings[bestPair * 16 + targets[pixel]];
          pixels.data.set(palette[color].rgb, pixel * 4);
          pixels.data[pixel * 4 + 3] = 255;
        }
      }
    }
  }
  return { pixels, colors };
}

function optimizeFliFrames(sources, palette, brightnessBands, backgroundColorIndex, overlayMask = null,
  overlayColorIndex = null) {
  const { width, height, brightnessError, chromaError, frameTargets } = prepareC64FittingTargets(
    sources, palette, brightnessBands, backgroundColorIndex
  );
  if (overlayMask !== null && (sources.length !== 1 || !ArrayBuffer.isView(overlayMask) ||
      overlayMask.BYTES_PER_ELEMENT !== 1 || overlayMask.length !== width * 2 * height ||
      overlayMask.some(value => value !== 0 && value !== 1))) {
    throw new Error('FLI overlay mask must contain two binary hires bytes per logical pixel.');
  }
  if (overlayColorIndex !== null && (!overlayMask || !Number.isInteger(overlayColorIndex) ||
      overlayColorIndex < 0 || overlayColorIndex >= palette.length)) {
    throw new Error('Choose a valid overlay color with its sprite mask.');
  }

  // Ignore only floating-point roundoff when comparing sums of the same terms.
  const epsilon = 1e-12;
  const isBetter = (primary, secondary, bestPrimary, bestSecondary) =>
    primary < bestPrimary - epsilon ||
    (Math.abs(primary - bestPrimary) <= epsilon && secondary < bestSecondary - epsilon);

  const maskParent = new Uint8Array(16);
  const maskPixel = new Uint8Array(16);
  const partitions = [];
  for (let mask = 1; mask < 16; mask += 1) {
    const bit = mask & -mask;
    maskParent[mask] = mask ^ bit;
    maskPixel[mask] = 31 - Math.clz32(bit);
  }
  for (let first = 0; first < 16; first += 1) {
    for (let second = first; second < 16; second += 1) {
      if ((first & second) === 0) partitions.push([first, second, 15 ^ first ^ second]);
    }
  }

  const rowCache = new Map();
  function getRow(indices, weights = null, excludedColor = -1) {
    const entries = indices.map((index, pixel) => ({ index, weight: weights?.[pixel] ?? 1 }))
      .sort((a, b) => a.index - b.index || a.weight - b.weight);
    const sorted = entries.map(entry => entry.index);
    const sortedWeights = entries.map(entry => entry.weight);
    const pixelKey = weights ? entries.reduce((value, entry, pixel) =>
      value | (entry.index | entry.weight << 4) << (pixel * 6), 0)
      : sorted[0] | sorted[1] << 4 | sorted[2] << 8 | sorted[3] << 12;
    const key = pixelKey + (excludedColor + 1) * 0x1000000;
    if (!rowCache.has(key)) {
      rowCache.set(key, {
        indices: sorted,
        weights: sortedWeights,
        excludedColor,
        computed: 0,
        primary: new Float64Array(16),
        secondary: new Float64Array(16),
        colors: new Uint8Array(32)
      });
    }
    return rowCache.get(key);
  }

  function prepareSubsets(row) {
    const primary = new Float64Array(256);
    const secondary = new Float64Array(256);
    row.subsetPrimary = new Float64Array(16);
    row.subsetSecondary = new Float64Array(16);
    row.subsetColor = new Uint8Array(16);
    row.subsetColor[0] = backgroundColorIndex === row.excludedColor
      ? (row.excludedColor === 0 ? 1 : 0) : backgroundColorIndex;

    for (let mask = 1; mask < 16; mask += 1) {
      const parent = maskParent[mask] * 16;
      const pixel = maskPixel[mask];
      const target = row.indices[pixel] * 16;
      const weight = row.weights[pixel];
      const offset = mask * 16;
      let bestPrimary = Infinity;
      let bestSecondary = Infinity;
      for (let candidate = 0; candidate < 16; candidate += 1) {
        if (candidate === row.excludedColor) continue;
        primary[offset + candidate] = primary[parent + candidate] + weight * brightnessError[target + candidate];
        secondary[offset + candidate] = secondary[parent + candidate] + weight * chromaError[target + candidate];
        if (isBetter(primary[offset + candidate], secondary[offset + candidate], bestPrimary, bestSecondary)) {
          bestPrimary = primary[offset + candidate];
          bestSecondary = secondary[offset + candidate];
          row.subsetColor[mask] = candidate;
        }
      }
      row.subsetPrimary[mask] = bestPrimary;
      row.subsetSecondary[mask] = bestSecondary;
    }
  }

  function fitRow(row, tileColor) {
    if (row.computed & 1 << tileColor) return;
    row.computed |= 1 << tileColor;
    const extraColors = [];
    for (let pixel = 0; pixel < 4; pixel += 1) {
      if (row.weights[pixel] === 0) continue;
      const index = row.indices[pixel];
      if (index !== backgroundColorIndex && index !== tileColor && !extraColors.includes(index)) extraColors.push(index);
    }
    const exactTargetsAllowed = row.indices.every((index, pixel) =>
      row.weights[pixel] === 0 || index !== row.excludedColor);
    if (exactTargetsAllowed && extraColors.length <= 2) {
      const fallback = backgroundColorIndex === row.excludedColor
        ? (row.excludedColor === 0 ? 1 : 0) : backgroundColorIndex;
      row.colors[tileColor * 2] = extraColors[0] ?? fallback;
      row.colors[tileColor * 2 + 1] = extraColors[1] ?? fallback;
      return;
    }

    if (!row.subsetPrimary) prepareSubsets(row);
    const basePrimary = new Float64Array(16);
    const baseSecondary = new Float64Array(16);
    const pixelPrimary = new Float64Array(4);
    const pixelSecondary = new Float64Array(4);
    const fixedColors = [backgroundColorIndex, tileColor].filter(color => color !== row.excludedColor);
    for (let pixel = 0; pixel < 4; pixel += 1) {
      if (row.weights[pixel] === 0) continue;
      if (fixedColors.length === 0) {
        pixelPrimary[pixel] = Infinity;
        pixelSecondary[pixel] = Infinity;
        continue;
      }
      const offset = row.indices[pixel] * 16;
      let color = fixedColors[0];
      if (fixedColors.length > 1 && isBetter(brightnessError[offset + fixedColors[1]], chromaError[offset + fixedColors[1]],
        brightnessError[offset + color], chromaError[offset + color])) color = fixedColors[1];
      pixelPrimary[pixel] = row.weights[pixel] * brightnessError[offset + color];
      pixelSecondary[pixel] = row.weights[pixel] * chromaError[offset + color];
    }
    for (let mask = 1; mask < 16; mask += 1) {
      basePrimary[mask] = basePrimary[maskParent[mask]] + pixelPrimary[maskPixel[mask]];
      baseSecondary[mask] = baseSecondary[maskParent[mask]] + pixelSecondary[maskPixel[mask]];
    }

    // Every legal row assigns its four pixels to the fixed colors or two free groups.
    // These 41 disjoint-subset partitions cover every assignment; each group's best
    // representative is searched over all 16 colors. This is exact, not a greedy fit.
    let bestPrimary = Infinity;
    let bestSecondary = Infinity;
    for (const [first, second, fixed] of partitions) {
      const primary = row.subsetPrimary[first] + row.subsetPrimary[second] + basePrimary[fixed];
      const secondary = row.subsetSecondary[first] + row.subsetSecondary[second] + baseSecondary[fixed];
      if (isBetter(primary, secondary, bestPrimary, bestSecondary)) {
        bestPrimary = primary;
        bestSecondary = secondary;
        row.colors[tileColor * 2] = row.subsetColor[first];
        row.colors[tileColor * 2 + 1] = row.subsetColor[second];
      }
      if (bestPrimary === 0 && bestSecondary === 0) break;
    }
    row.primary[tileColor] = bestPrimary;
    row.secondary[tileColor] = bestSecondary;
  }

  const columns = width / 4;
  const tileCount = columns * height / 8;
  const tileColors = new Uint8Array(tileCount);
  const frames = sources.map(() => ({
    pixels: new ImageData(width, height),
    rowColors: new Uint8Array(tileCount * 16)
  }));

  for (let tileY = 0; tileY < height; tileY += 8) {
    for (let tileX = 0; tileX < width; tileX += 4) {
      const tileIndex = tileY / 8 * columns + tileX / 4;
      const rows = [];
      for (const targets of frameTargets) {
        for (let row = 0; row < 8; row += 1) {
          const offset = (tileY + row) * width + tileX;
          // Each logical pixel has two hires halves. A partly covered pixel
          // still needs its target color for the visible half of the bitmap.
          const weights = overlayMask ? Array.from({ length: 4 }, (_, column) => {
            const hires = (offset + column) * 2;
            return 2 - overlayMask[hires] - overlayMask[hires + 1];
          }) : null;
          const activeOverlay = weights?.some(weight => weight < 2);
          rows.push(getRow(Array.from(targets.subarray(offset, offset + 4)), weights,
            activeOverlay && overlayColorIndex !== null ? overlayColorIndex : -1));
        }
      }
      let bestPrimary = Infinity;
      let bestSecondary = Infinity;
      let tileColor = 0;
      for (let candidate = 0; candidate < 16; candidate += 1) {
        let primary = 0;
        let secondary = 0;
        for (const row of rows) {
          fitRow(row, candidate);
          primary += row.primary[candidate];
          secondary += row.secondary[candidate];
          if (primary > bestPrimary + epsilon) break;
        }
        if (isBetter(primary, secondary, bestPrimary, bestSecondary)) {
          bestPrimary = primary;
          bestSecondary = secondary;
          tileColor = candidate;
        }
        if (bestPrimary === 0 && bestSecondary === 0) break;
      }
      tileColors[tileIndex] = tileColor;

      // All phases use the one jointly selected tileColor, but distinct row pairs.
      for (let frame = 0; frame < frames.length; frame += 1) {
        const { pixels, rowColors } = frames[frame];
        const targets = frameTargets[frame];
        for (let row = 0; row < 8; row += 1) {
          const rowColorOffset = tileIndex * 16 + row * 2;
          const rowFit = rows[frame * 8 + row];
          const first = rowFit.colors[tileColor * 2];
          const second = rowFit.colors[tileColor * 2 + 1];
          rowColors[rowColorOffset] = first;
          rowColors[rowColorOffset + 1] = second;
          // Global background and shared tile colors remain stored as selected,
          // but an active sprite strip may not map bitmap pixels to its color.
          const allowed = [backgroundColorIndex, tileColor, first, second]
            .filter(color => color !== rowFit.excludedColor);
          for (let column = 0; column < 4; column += 1) {
            const pixel = (tileY + row) * width + tileX + column;
            const errorOffset = targets[pixel] * 16;
            let color = allowed[0];
            for (let candidate = 1; candidate < allowed.length; candidate += 1) {
              const next = allowed[candidate];
              if (isBetter(brightnessError[errorOffset + next], chromaError[errorOffset + next],
                brightnessError[errorOffset + color], chromaError[errorOffset + color])) color = next;
            }
            pixels.data.set(palette[color].rgb, pixel * 4);
            pixels.data[pixel * 4 + 3] = 255;
          }
        }
      }
    }
  }

  return { frames, backgroundColorIndex, tileColors };
}

/** Shared source handling keeps all bitmap modes’ alpha/color errors identical. */
function prepareC64FittingTargets(sources, palette, brightnessBands, backgroundColorIndex) {
  if (sources.length === 0) throw new Error('Provide at least one FLI image.');
  const { width, height } = sources[0];
  if (width % 4 !== 0 || height % 8 !== 0 || width === 0 || height === 0) {
    throw new Error('FLI dimensions must be positive multiples of 4 × 8 pixels.');
  }
  if (sources.some((source) => source.width !== width || source.height !== height)) {
    throw new Error('FLI frames must have matching dimensions.');
  }
  if (!Number.isInteger(backgroundColorIndex) || backgroundColorIndex < 0 || backgroundColorIndex >= palette.length) {
    throw new Error('Choose a valid C64 background color.');
  }

  const lightness = new Float64Array(16);
  const chromaA = new Float64Array(16);
  const chromaB = new Float64Array(16);
  for (const band of brightnessBands) {
    for (const entry of band.colors) {
      const index = entry.color.index;
      lightness[index] = band.lightness;
      chromaA[index] = entry.lab.a;
      chromaB[index] = entry.lab.b;
    }
  }

  const brightnessError = new Float64Array(256);
  const chromaError = new Float64Array(256);
  const rgbIndices = new Map();
  for (let target = 0; target < 16; target += 1) {
    const rgb = palette[target].rgb;
    rgbIndices.set(rgb[0] | rgb[1] << 8 | rgb[2] << 16, target);
    for (let candidate = 0; candidate < 16; candidate += 1) {
      const offset = target * 16 + candidate;
      brightnessError[offset] = (lightness[target] - lightness[candidate]) ** 2;
      chromaError[offset] = (chromaA[target] - chromaA[candidate]) ** 2 + (chromaB[target] - chromaB[candidate]) ** 2;
    }
  }

  const background = palette[backgroundColorIndex].rgb;
  const linearBackground = background.map(srgbToLinear);
  const flattenedIndices = new Map();
  const frameTargets = sources.map(() => new Uint8Array(width * height));

  function snapComposite(red, green, blue) {
    const lab = rgbToOklab(red, green, blue);
    let band = brightnessBands[0];
    let distance = Infinity;
    for (const candidate of brightnessBands) {
      const nextDistance = Math.abs(lab.lightness - candidate.lightness);
      if (nextDistance < distance) {
        distance = nextDistance;
        band = candidate;
      }
    }
    let best = band.colors[0].color.index;
    distance = Infinity;
    for (const candidate of band.colors) {
      const nextDistance = (lab.a - candidate.lab.a) ** 2 + (lab.b - candidate.lab.b) ** 2;
      if (nextDistance < distance) {
        distance = nextDistance;
        best = candidate.color.index;
      }
    }
    return best;
  }

  for (let frame = 0; frame < sources.length; frame += 1) {
    const source = sources[frame];
    const targets = frameTargets[frame];
    for (let pixel = 0; pixel < targets.length; pixel += 1) {
      const offset = pixel * 4;
      const alpha = source.data[offset + 3];
      if (alpha === 0) {
        targets[pixel] = backgroundColorIndex;
        continue;
      }
      const red = source.data[offset];
      const green = source.data[offset + 1];
      const blue = source.data[offset + 2];
      const rgbKey = red | green << 8 | blue << 16;
      if (alpha === 255 && rgbIndices.has(rgbKey)) {
        targets[pixel] = rgbIndices.get(rgbKey);
        continue;
      }
      const rgbaKey = (rgbKey | alpha << 24) >>> 0;
      if (!flattenedIndices.has(rgbaKey)) {
        const opacity = alpha / 255;
        const composite = [red, green, blue].map((channel, index) => linearToSrgb(
          srgbToLinear(channel) * opacity + linearBackground[index] * (1 - opacity)
        ));
        flattenedIndices.set(rgbaKey, snapComposite(...composite));
      }
      targets[pixel] = flattenedIndices.get(rgbaKey);
    }
  }

  return { width, height, brightnessError, chromaError, frameTargets };
}
