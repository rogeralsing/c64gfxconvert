/** Choose one shared pair and one foreground per logical sprite before export. */
function optimizeC64BorderColors(source, palette, settings, backgroundColorIndex = 0, interlaced = false, options = {}) {
  const config = normalizeC64BorderSprites(settings);
  if (config.vertical.enabled && config.vertical.xExpanded === false) {
    return optimizeC64NormalBorderSprites(source, palette, config, backgroundColorIndex, interlaced, options);
  }
  const manual = convertC64BorderSprites(source, palette, { ...config, optimizeColors: false },
    backgroundColorIndex, interlaced, options);
  const frames = manual.frames ?? [manual];
  const count = manual.sprites.length;
  if (!count) throw new Error('Border color optimization requires at least one enabled border.');
  const layout = manual.layout;
  const { width, height, coreX, coreY } = layout;
  const nativeLabs = palette.map(color => rgbToOklab(...color.rgb));
  const backgroundLinear = palette[backgroundColorIndex].rgb.map(srgbToLinear);
  const colorLabs = new Map();
  function visibleLab(rgba) {
    const key = (rgba[0] | rgba[1] << 8 | rgba[2] << 16 | rgba[3] << 24) >>> 0;
    if (!colorLabs.has(key)) {
      const alpha = rgba[3] / 255;
      colorLabs.set(key, rgbToOklab(...Array.from(rgba.subarray(0, 3), (channel, index) =>
        linearToSrgb(srgbToLinear(channel) * alpha + backgroundLinear[index] * (1 - alpha)))));
    }
    return colorLabs.get(key);
  }
  const sourceLabs = Array.from({ length: width * height }, (_, index) =>
    visibleLab(source.data.subarray(index * 4, index * 4 + 4)));
  const cost = (stat, lab) => Math.max(0, stat[4] + stat[0] *
    (lab.lightness ** 2 + lab.a ** 2 + lab.b ** 2) - 2 *
    (lab.lightness * stat[1] + lab.a * stat[2] + lab.b * stat[3]));
  const coverage = frames.map(() => new Uint8Array(width * height));
  const regions = [];
  for (const [phase, frame] of frames.entries()) {
    for (const group of ['top', 'bottom', 'left', 'right']) {
      const sprites = frame.sprites.filter(sprite => sprite.group === group);
      if (!sprites.length) continue;
      const vertical = group === 'top' || group === 'bottom';
      const multicolor = sprites[0].multicolor;
      const cellWidth = (multicolor ? 2 : 1) * (vertical ? 2 : 1);
      const gridWidth = (vertical ? 384 : 24) / cellWidth;
      const left = (group === 'right' ? coreX + 320 : 0) + phase;
      const top = group === 'top' ? -7 : group === 'bottom' ? coreY + 200 : coreY;
      const cells = [];
      for (const sprite of sprites) {
        for (let row = 0; row < 21; row += 1) {
          for (let column = 0; column < (multicolor ? 12 : 24); column += 1) {
            const x0 = Math.max(0, sprite.clip.x, sprite.x + column * cellWidth);
            const x1 = Math.min(width, sprite.clip.x + sprite.clip.width, sprite.x + (column + 1) * cellWidth);
            const y0 = Math.max(0, sprite.clip.y, sprite.y + row);
            const y1 = Math.min(height, sprite.clip.y + sprite.clip.height, sprite.y + row + 1);
            const stat = [0, 0, 0, 0, 0];
            for (let y = y0; y < y1; y += 1) for (let x = x0; x < x1; x += 1) {
              const lab = sourceLabs[y * width + x];
              stat[0] += 1; stat[1] += lab.lightness; stat[2] += lab.a; stat[3] += lab.b;
              stat[4] += lab.lightness ** 2 + lab.a ** 2 + lab.b ** 2;
              coverage[phase][y * width + x] = 1;
            }
            if (!stat[0]) continue;
            const gx = Math.floor((sprite.x + column * cellWidth - left) / cellWidth);
            const gy = sprite.y + row - top;
            cells.push({ sprite: sprite.index, offset: (gy * gridWidth + gx) * 4,
              physicalOffset: (y0 * width + x0) * 4, stat,
              nativeCosts: nativeLabs.map(lab => cost(stat, lab)) });
          }
        }
      }
      regions.push({ phase, group, multicolor, cellWidth, cells });
    }
  }
  let fixedError = 0;
  for (const covered of coverage) for (let y = 0; y < height; y += 1) for (let x = 0; x < width; x += 1) {
    const border = x < coreX || x >= coreX + 320 || y < coreY || y >= coreY + 200;
    if (border && !covered[y * width + x]) {
      const lab = sourceLabs[y * width + x], bg = nativeLabs[backgroundColorIndex];
      fixedError += (lab.lightness - bg.lightness) ** 2 + (lab.a - bg.a) ** 2 + (lab.b - bg.b) ** 2;
    }
  }
  const virtualRequested = (options.layers ?? []).some(layer => layer.pattern !== 'off') &&
    Array.isArray(options.virtualPalette) && options.virtualPalette.length > 0;
  const scoreCache = new Map();
  const colorSet = indices => [...new Set(indices)].sort((a, b) => a - b);
  function scoreColors(indices, multicolor) {
    const colors = colorSet(indices), key = `${Number(multicolor)}:${colors.join(',')}`;
    if (!scoreCache.has(key)) {
      const scores = new Float64Array(count);
      for (const region of regions.filter(region => region.multicolor === multicolor)) {
        const prepared = prepareC64BorderSpriteRegion(source, palette, config, layout,
          region.phase, region.group, colors, region.cellWidth, options);
        for (const cell of region.cells) {
          // An automatic search must not improve its score by selecting a
          // palette that makes every permitted virtual color unavailable.
          scores[cell.sprite] += virtualRequested && !prepared ? Infinity : prepared
            ? cost(cell.stat, visibleLab(prepared.palette.data.subarray(cell.offset, cell.offset + 4)))
            : Math.min(...colors.map(index => cell.nativeCosts[index]));
        }
      }
      scoreCache.set(key, scores);
    }
    return scoreCache.get(key);
  }
  const hasMulticolor = manual.sprites.some(sprite => sprite.multicolor);
  const pairs = [[...config.multicolorIndices]];
  if (hasMulticolor) for (let first = 0; first < 16; first += 1) for (let second = first + 1; second < 16; second += 1) {
    if (first !== pairs[0][0] || second !== pairs[0][1]) pairs.push([first, second]);
  }
  const tasks = new Map();
  for (const sprite of manual.sprites) for (const pair of (sprite.multicolor ? pairs : [pairs[0]])) {
    for (let foreground = 0; foreground < 16; foreground += 1) {
      const colors = colorSet(sprite.multicolor ? [backgroundColorIndex, ...pair, foreground] : [backgroundColorIndex, foreground]);
      tasks.set(`${Number(sprite.multicolor)}:${colors.join(',')}`, { colors, multicolor: sprite.multicolor });
    }
  }
  options.onProgress?.({ completed: 0, total: tasks.size, ratio: 0 });
  let completed = 0;
  for (const task of tasks.values()) {
    scoreColors(task.colors, task.multicolor);
    completed += 1;
    if (completed % 8 === 0 || completed === tasks.size) {
      options.onProgress?.({ completed, total: tasks.size, ratio: completed / tasks.size });
    }
  }
  const manualColors = manual.sprites.map(sprite => sprite.colorIndex);
  let baselineError = fixedError;
  for (const region of regions) {
    const frame = frames[region.phase], pixels = frame.palettePixels ?? frame.pixels;
    for (const cell of region.cells) {
      baselineError += cost(cell.stat, visibleLab(pixels.data.subarray(cell.physicalOffset, cell.physicalOffset + 4)));
    }
  }
  let best = { multicolorIndices: [...config.multicolorIndices], colorIndices: manualColors, optimizedError: baselineError };
  for (const pair of pairs) {
    let error = fixedError;
    const colorIndices = [];
    for (const sprite of manual.sprites) {
      let foreground = sprite.colorIndex, minimum = Infinity;
      const candidates = [sprite.colorIndex, ...Array.from({ length: 16 }, (_, index) => index).filter(index => index !== sprite.colorIndex)];
      for (const index of candidates) {
        const value = scoreColors(sprite.multicolor ? [backgroundColorIndex, ...pair, index]
          : [backgroundColorIndex, index], sprite.multicolor)[sprite.index];
        if (value < minimum - 1e-12) { minimum = value; foreground = index; }
      }
      error += minimum;
      colorIndices.push(foreground);
    }
    if (error < best.optimizedError - 1e-12) best = { multicolorIndices: [...pair], colorIndices, optimizedError: error };
  }
  return { ...best, baselineError,
    improvementPercent: baselineError > 0
      ? Math.max(0, Math.min(100, 100 * (baselineError - best.optimizedError) / baselineError)) : 0,
    metric: virtualRequested ? 'virtual-surface-oklab-sse' : 'native-pixel-oklab-sse',
    spriteCount: count, phaseCount: frames.length, backgroundColorIndex,
    candidateColorSets: tasks.size };
}

/** Exact placement of eight nonoverlapping normal-width sprites in each PAL band. */
function optimizeC64NormalBorderSprites(source, palette, config, backgroundColorIndex, interlaced, options) {
  const manual = convertC64BorderSprites(source, palette, { ...config, optimizeColors: false },
    backgroundColorIndex, interlaced, { ...options, colorPlan: undefined });
  const frames = manual.frames ?? [manual];
  const { width, height, coreX, coreY } = manual.layout;
  const count = manual.sprites.length, windowCount = width - 23;
  const nativeLabs = palette.map(color => rgbToOklab(...color.rgb));
  const backgroundLinear = palette[backgroundColorIndex].rgb.map(srgbToLinear);
  const labsByColor = new Map();
  function visibleLab(rgba) {
    const key = (rgba[0] | rgba[1] << 8 | rgba[2] << 16 | rgba[3] << 24) >>> 0;
    if (!labsByColor.has(key)) {
      const alpha = rgba[3] / 255;
      labsByColor.set(key, rgbToOklab(...Array.from(rgba.subarray(0, 3), (channel, index) =>
        linearToSrgb(srgbToLinear(channel) * alpha + backgroundLinear[index] * (1 - alpha)))));
    }
    return labsByColor.get(key);
  }
  const sourceLabs = Array.from({ length: width * height }, (_, index) =>
    visibleLab(source.data.subarray(index * 4, index * 4 + 4)));
  const distance = (a, b) => (a.lightness - b.lightness) ** 2 + (a.a - b.a) ** 2 + (a.b - b.b) ** 2;
  const cost = (stat, lab) => Math.max(0, stat[4] + stat[0] *
    (lab.lightness ** 2 + lab.a ** 2 + lab.b ** 2) - 2 *
    (lab.lightness * stat[1] + lab.a * stat[2] + lab.b * stat[3]));
  const virtualRequested = (options.layers ?? []).some(layer => layer.pattern !== 'off') &&
    Array.isArray(options.virtualPalette) && options.virtualPalette.length > 0;
  let backgroundError = 0, baselineError = 0;
  for (const frame of frames) {
    const fitted = frame.palettePixels ?? frame.pixels;
    for (let y = 0; y < height; y += 1) for (let x = 0; x < width; x += 1) {
      if (x >= coreX && x < coreX + 320 && y >= coreY && y < coreY + 200) continue;
      const index = y * width + x, lab = sourceLabs[index];
      backgroundError += distance(lab, nativeLabs[backgroundColorIndex]);
      baselineError += distance(lab, visibleLab(fitted.data.subarray(index * 4, index * 4 + 4)));
    }
  }
  const verticalBackground = Array.from({ length: 4 }, () => new Float64Array(windowCount));
  const sideBackground = new Float64Array(20);
  const regions = [];
  for (let phase = 0; phase < frames.length; phase += 1) {
    for (const group of ['top', 'bottom', ...(config.sides.enabled ? ['left', 'right'] : [])]) {
      const vertical = group === 'top' || group === 'bottom';
      const multicolor = (vertical ? config.vertical : config.sides).mode === 'multicolor';
      const cellWidth = multicolor ? 2 : 1;
      const gridWidth = (vertical ? 384 : 24) / cellWidth;
      const gridHeight = vertical ? 42 : 200;
      const top = group === 'top' ? -7 : group === 'bottom' ? coreY + 200 : coreY;
      const clipY = group === 'top' ? 0 : top;
      const clipBottom = clipY + (group === 'top' ? 35 : group === 'bottom' ? 37 : 200);
      for (let alignment = 0; alignment < (vertical ? cellWidth : 1); alignment += 1) {
        const left = (group === 'right' ? coreX + 320 : 0) + phase + alignment;
        const cells = [];
        for (let row = 0; row < gridHeight; row += 1) {
          const y = top + row;
          if (y < clipY || y >= clipBottom || y < 0 || y >= height) continue;
          for (let column = 0; column < gridWidth; column += 1) {
            const start = left + column * cellWidth;
            const end = Math.min(width, start + cellWidth);
            const stat = [0, 0, 0, 0, 0], sampling = [0, 0, 0, 0, 0];
            for (let x = Math.max(0, start); x < end; x += 1) {
              const lab = sourceLabs[y * width + x];
              const square = lab.lightness ** 2 + lab.a ** 2 + lab.b ** 2;
              sampling[0] += 1; sampling[1] += lab.lightness; sampling[2] += lab.a; sampling[3] += lab.b; sampling[4] += square;
              if (!vertical && x >= coreX && x < coreX + 320) continue;
              stat[0] += 1; stat[1] += lab.lightness; stat[2] += lab.a; stat[3] += lab.b; stat[4] += square;
            }
            if (stat[0]) cells.push({ column, row, stat, nativeCosts: nativeLabs.map(lab => cost(stat, lab)),
              selectionCosts: nativeLabs.map(lab => distance({ lightness: sampling[1] / sampling[0],
                a: sampling[2] / sampling[0], b: sampling[3] / sampling[0] }, lab)),
              coreSpill: sampling[0] !== stat[0],
              offset: (row * gridWidth + column) * 4,
              band: vertical ? (group === 'top' ? 0 : 2) + Math.floor(row / 21)
                : (group === 'left' ? 0 : 10) + Math.min(9, Math.floor(row / 21)) });
          }
        }
        const region = { phase, group, vertical, multicolor, cellWidth, alignment, gridWidth, cells };
        regions.push(region);
        const columns = Array.from({ length: 4 }, () => new Float64Array(gridWidth));
        for (const cell of cells) {
          const value = cell.nativeCosts[backgroundColorIndex];
          if (vertical) columns[cell.band][cell.column] += value;
          else sideBackground[cell.band] += value;
        }
        if (vertical) for (let band = 0; band < 4; band += 1) {
          const prefix = new Float64Array(gridWidth + 1);
          for (let column = 0; column < gridWidth; column += 1) prefix[column + 1] = prefix[column] + columns[band][column];
          for (let x = alignment; x < windowCount; x += cellWidth) {
            const first = (x - alignment) / cellWidth;
            verticalBackground[band][x] += prefix[first + 24 / cellWidth] - prefix[first];
          }
        }
      }
    }
  }
  const scoreCache = new Map();
  const colorSet = indices => [...new Set(indices)].sort((a, b) => a - b);
  function scoreColors(indices, multicolor) {
    const colors = colorSet(indices), key = `${Number(multicolor)}:${colors.join(',')}`;
    if (!scoreCache.has(key)) {
      const vertical = Array.from({ length: 4 }, () => new Float64Array(windowCount));
      const sides = new Float64Array(20);
      const nativeSpill = [];
      for (const region of regions) {
        if (region.multicolor !== multicolor) continue;
        const prepared = prepareC64BorderSpriteRegion(source, palette, config, manual.layout,
          region.phase, region.group, colors, region.cellWidth, options, region.alignment);
        const unavailable = config.optimizeColors && virtualRequested && !prepared;
        const columns = Array.from({ length: 4 }, () => new Float64Array(region.gridWidth));
        for (const cell of region.cells) {
          let value = unavailable ? Infinity : prepared
            ? cost(cell.stat, visibleLab(prepared.palette.data.subarray(cell.offset, cell.offset + 4))) : Infinity;
          if (!unavailable && !prepared) {
            if (cell.coreSpill) { nativeSpill.push(cell); continue; }
            let minimum = Infinity;
            for (const index of colors) if (cell.selectionCosts[index] < minimum) {
              minimum = cell.selectionCosts[index]; value = cell.nativeCosts[index];
            }
          }
          if (region.vertical) columns[cell.band][cell.column] += value;
          else sides[cell.band] += value;
        }
        if (region.vertical) for (let band = 0; band < 4; band += 1) {
          const prefix = new Float64Array(region.gridWidth + 1);
          for (let column = 0; column < region.gridWidth; column += 1) {
            prefix[column + 1] = prefix[column] + columns[band][column];
          }
          for (let x = region.alignment; x < windowCount; x += region.cellWidth) {
            const first = (x - region.alignment) / region.cellWidth;
            vertical[band][x] += unavailable ? Infinity : prefix[first + 24 / region.cellWidth] - prefix[first];
          }
        }
      }
      scoreCache.set(key, { vertical, sides, nativeSpill });
    }
    const score = scoreCache.get(key);
    if (!score.nativeSpill.length) return score;
    const sides = new Float64Array(score.sides);
    // Only the shifted left edge straddles the core. Keep native code-order
    // ties there while sharing all ordinary window costs by component set.
    for (const cell of score.nativeSpill) {
      let minimum = Infinity, chosen = backgroundColorIndex;
      for (const index of indices) if (cell.selectionCosts[index] < minimum) {
        minimum = cell.selectionCosts[index]; chosen = index;
      }
      sides[cell.band] += cell.nativeCosts[chosen];
    }
    return { vertical: score.vertical, sides };
  }
  const pairs = [[...config.multicolorIndices]];
  if (config.optimizeColors && manual.sprites.some(sprite => sprite.multicolor)) {
    const ordered = interlaced && config.sides.enabled && config.sides.mode === 'multicolor' && !virtualRequested;
    for (let first = 0; first < 16; first += 1) for (let second = ordered ? 0 : first + 1; second < 16; second += 1) {
      if (first === second) continue;
      if (first !== pairs[0][0] || second !== pairs[0][1]) pairs.push([first, second]);
    }
  }
  const foregrounds = group => [group.colorIndex, ...(config.optimizeColors
    ? Array.from({ length: 16 }, (_, index) => index).filter(index => index !== group.colorIndex) : [])];
  const tasks = new Map();
  for (const group of [config.vertical, ...(config.sides.enabled ? [config.sides] : [])]) {
    const multicolor = group.mode === 'multicolor';
    for (const pair of multicolor ? pairs : [pairs[0]]) for (const foreground of foregrounds(group)) {
      const colors = colorSet(multicolor ? [backgroundColorIndex, ...pair, foreground] : [backgroundColorIndex, foreground]);
      tasks.set(`${Number(multicolor)}:${colors.join(',')}`, { colors, multicolor });
    }
  }
  options.onProgress?.({ completed: 0, total: tasks.size, ratio: 0 });
  let completed = 0;
  for (const task of tasks.values()) {
    scoreColors(task.colors, task.multicolor);
    completed += 1;
    if (completed % 8 === 0 || completed === tasks.size) options.onProgress?.({ completed, total: tasks.size, ratio: completed / tasks.size });
  }
  function placeBand(gains) {
    const previousRows = [new Float64Array(width + 1)];
    const take = Array.from({ length: 9 }, () => new Uint8Array(width + 1));
    for (let selected = 1; selected <= 8; selected += 1) {
      const row = new Float64Array(width + 1).fill(-Infinity);
      const previous = previousRows[selected - 1];
      for (let end = 1; end <= width; end += 1) {
        row[end] = row[end - 1];
        if (end >= 24) {
          const x = end - 24, candidate = previous[x] + gains[x];
          if (candidate > row[end] + 1e-12) { row[end] = candidate; take[selected][end] = 1; }
        }
      }
      previousRows.push(row);
    }
    const positions = [];
    let end = width, selected = 8;
    while (selected && end) {
      if (take[selected][end]) { positions.unshift(end - 24); end -= 24; selected -= 1; }
      else end -= 1;
    }
    return { gain: previousRows[8][width], positions };
  }
  let best = { multicolorIndices: [...config.multicolorIndices],
    colorIndices: manual.sprites.map(sprite => sprite.colorIndex),
    verticalPositions: manual.sprites.slice(0, 32).map(sprite => sprite.x), optimizedError: baselineError };
  for (const pair of pairs) {
    let error = backgroundError;
    const verticalPositions = [], colorIndices = [];
    const costs = Array.from({ length: 4 }, () => new Float64Array(windowCount).fill(Infinity));
    const colors = Array.from({ length: 4 }, () => new Uint8Array(windowCount));
    const multicolor = config.vertical.mode === 'multicolor';
    for (const foreground of foregrounds(config.vertical)) {
      const score = scoreColors(multicolor ? [backgroundColorIndex, pair[0], foreground, pair[1]]
        : [backgroundColorIndex, foreground], multicolor);
      for (let band = 0; band < 4; band += 1) for (let x = 0; x < windowCount; x += 1) {
        if (score.vertical[band][x] < costs[band][x] - 1e-12) {
          costs[band][x] = score.vertical[band][x]; colors[band][x] = foreground;
        }
      }
    }
    for (let band = 0; band < 4; band += 1) {
      const gains = Float64Array.from(costs[band], (value, x) => verticalBackground[band][x] - value);
      const placed = placeBand(gains);
      error -= placed.gain;
      verticalPositions.push(...placed.positions);
      colorIndices.push(...placed.positions.map(x => colors[band][x]));
    }
    if (config.sides.enabled) for (let side = 0; side < 20; side += 1) {
      let minimum = Infinity, selected = config.sides.colorIndex;
      const mc = config.sides.mode === 'multicolor';
      for (const foreground of foregrounds(config.sides)) {
        const score = scoreColors(mc ? [backgroundColorIndex, pair[0], foreground, pair[1]]
          : [backgroundColorIndex, foreground], mc).sides[side];
        if (score < minimum - 1e-12) { minimum = score; selected = foreground; }
      }
      error += minimum - sideBackground[side];
      colorIndices.push(selected);
    }
    error = Math.max(0, error);
    if (error < best.optimizedError - 1e-12) {
      best = { multicolorIndices: [...pair], colorIndices, verticalPositions, optimizedError: error };
    }
  }
  return { ...best, baselineError,
    improvementPercent: baselineError > 0 ? Math.max(0, Math.min(100, 100 * (baselineError - best.optimizedError) / baselineError)) : 0,
    metric: virtualRequested ? 'virtual-surface-oklab-sse' : 'native-pixel-oklab-sse',
    spriteCount: count, phaseCount: frames.length, backgroundColorIndex,
    candidateColorSets: tasks.size };
}
