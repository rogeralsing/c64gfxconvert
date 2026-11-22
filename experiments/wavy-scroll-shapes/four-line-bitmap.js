"use strict";

/**
 * Fit two four-line segments per VIC-II cell. The screen colors can change
 * between segments. Color RAM and the background are shared.
 */
function optimizeFourLineBitmapImage(source, palette, brightnessBands, backgroundColorIndex, { colorGroups } = {}) {
  if (source.width !== 160 || source.height !== 200) {
    throw new Error("Four-line multicolor bitmap fitting requires a 160 × 200 image.");
  }
  const { width, height, brightnessError, chromaError, frameTargets: [targets] } = prepareC64FittingTargets(
    [source], palette, brightnessBands, backgroundColorIndex
  );
  const cellWidth = 4;
  const cellHeight = 8;
  const segmentHeight = 4;
  const cellPixels = cellWidth * cellHeight;
  const paletteSize = 16;
  const cellColumns = width / cellWidth;
  const cellCount = cellColumns * height / cellHeight;

  if (colorGroups) {
    // A substitution penalty outweighs all brightness errors in the cell.
    // A group change also outweighs all same-group substitutions.
    const changePenalty = cellPixels * Math.max(...brightnessError) + 1;
    const groupPenalty = (cellPixels + 1) * changePenalty;
    for (let target = 0; target < paletteSize; target += 1) {
      for (let candidate = 0; candidate < paletteSize; candidate += 1) {
        if (target === candidate) continue;
        const penalty = colorGroups[target] === colorGroups[candidate] ? 0 : groupPenalty;
        brightnessError[target * paletteSize + candidate] += changePenalty + penalty;
      }
    }
  }

  const { triples, mappings, primaryCosts, secondaryCosts } = prepareMulticolorBitmapAllocations(
    brightnessError, chromaError, backgroundColorIndex
  );
  const epsilon = 1e-12;
  const isBetter = (primary, secondary, bestPrimary, bestSecondary) =>
    primary < bestPrimary - epsilon ||
    (Math.abs(primary - bestPrimary) <= epsilon && secondary < bestSecondary - epsilon);
  const bitmap = new Uint8Array(cellCount * cellHeight);
  const screenTop = new Uint8Array(cellCount);
  const screenBottom = new Uint8Array(cellCount);
  const screens = [screenTop, screenBottom];
  const colorRam = new Uint8Array(cellCount);
  const pixels = new ImageData(width, height);

  const histogram = new Uint8Array(paletteSize);
  const codes = new Uint8Array(paletteSize);
  const segmentFits = new Array(2);
  // The best palette depends only on the segment's color counts. In
  // particular, the background and solid sections reuse the same fits.
  const fitsByHistogram = new Map();

  function fitSegment() {
    const key = histogram.join(",");
    const cached = fitsByHistogram.get(key);
    if (cached) return cached;

    const bestPrimary = new Float64Array(paletteSize).fill(Infinity);
    const bestSecondary = new Float64Array(paletteSize).fill(Infinity);
    const bestTriples = new Uint16Array(paletteSize);
    const activeTargets = [];
    for (let target = 0; target < paletteSize; target += 1) {
      if (histogram[target]) activeTargets.push(target);
    }
    for (let triple = 0; triple < triples.length; triple += 1) {
      let primary = 0;
      let secondary = 0;
      const paletteOffset = triple * paletteSize;
      for (const target of activeTargets) {
        const count = histogram[target];
        primary += count * primaryCosts[paletteOffset + target];
        secondary += count * secondaryCosts[paletteOffset + target];
      }
      // Any member of the triple may occupy the shared slot. Keep the
      // segment's optimum for every possible shared value.
      for (const shared of triples[triple]) {
        if (isBetter(primary, secondary, bestPrimary[shared], bestSecondary[shared])) {
          bestPrimary[shared] = primary;
          bestSecondary[shared] = secondary;
          bestTriples[shared] = triple;
        }
      }
    }
    const fit = { bestPrimary, bestSecondary, bestTriples };
    fitsByHistogram.set(key, fit);
    return fit;
  }

  for (let tileY = 0; tileY < height; tileY += cellHeight) {
    for (let tileX = 0; tileX < width; tileX += cellWidth) {
      for (let segment = 0; segment < 2; segment += 1) {
        histogram.fill(0);
        const firstRow = tileY + segment * segmentHeight;
        for (let y = firstRow; y < firstRow + segmentHeight; y += 1) {
          const offset = y * width + tileX;
          for (let x = 0; x < cellWidth; x += 1) {
            histogram[targets[offset + x]] += 1;
          }
        }
        segmentFits[segment] = fitSegment();
      }

      let sharedColor = 0;
      let minimumPrimary = Infinity;
      let minimumSecondary = Infinity;
      const [top, bottom] = segmentFits;
      // A shared slot containing the background admits at most two other
      // colors per segment. An unused non-background filler covers that case.
      for (let shared = 0; shared < paletteSize; shared += 1) {
        if (shared === backgroundColorIndex) continue;
        const primary = top.bestPrimary[shared] + bottom.bestPrimary[shared];
        const secondary = top.bestSecondary[shared] + bottom.bestSecondary[shared];
        if (isBetter(primary, secondary, minimumPrimary, minimumSecondary)) {
          sharedColor = shared;
          minimumPrimary = primary;
          minimumSecondary = secondary;
        }
      }

      const cell = (tileY / cellHeight) * cellColumns + tileX / cellWidth;
      colorRam[cell] = sharedColor;
      codes[backgroundColorIndex] = 0;
      codes[sharedColor] = 3;
      for (let segment = 0; segment < 2; segment += 1) {
        const triple = segmentFits[segment].bestTriples[sharedColor];
        const [a, b, c] = triples[triple];
        const first = a === sharedColor ? b : a;
        const second = c === sharedColor ? b : c;
        screens[segment][cell] = (first << 4) | second;
        codes[first] = 1;
        codes[second] = 2;
        const paletteOffset = triple * paletteSize;
        const firstRow = segment * segmentHeight;
        for (let row = firstRow; row < firstRow + segmentHeight; row += 1) {
          let bits = 0;
          const offset = (tileY + row) * width + tileX;
          for (let column = 0; column < cellWidth; column += 1) {
            const pixel = offset + column;
            const color = mappings[paletteOffset + targets[pixel]];
            bits = (bits << 2) | codes[color];
            pixels.data.set(palette[color].rgb, pixel * 4);
            pixels.data[pixel * 4 + 3] = 255;
          }
          bitmap[cell * cellHeight + row] = bits;
        }
      }
    }
  }

  return { pixels, bitmap, screenTop, screenBottom, colorRam, backgroundColorIndex };
}
