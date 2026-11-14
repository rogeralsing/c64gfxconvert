/** Build complete tone ramps using contacts observed within the same source image. */
function buildTalentToneModel(virtualPalette, observations) {
  const entries = virtualPalette.map(color => ({ color, lab: rgbToOklab(...color.rgb) }))
    .sort((a, b) => a.lab.lightness - b.lab.lightness || a.color.index - b.color.index);
  const byPair = new Map(entries.map(entry => [entry.color.colorIndices.join('-'), entry]));
  const black = byPair.get('0-0');
  const white = byPair.get('1-1');
  if (!black || !white) throw new Error('Talent ramps require black and white endpoints.');
  const candidates = new Map();

  for (const image of observations.images) {
    const next = new Map(entries.map(entry => [entry.color.index, []]));
    const edges = new Map();
    for (const observed of image.edges) {
      let darker = byPair.get(observed.a);
      let lighter = byPair.get(observed.b);
      if (!darker || !lighter || observed.count < observations.minContacts) continue;
      if (darker.lab.lightness > lighter.lab.lightness) [darker, lighter] = [lighter, darker];
      if (lighter.lab.lightness - darker.lab.lightness < 1e-9) continue;
      const cost = (lighter.lab.lightness - darker.lab.lightness) ** 2 +
        (lighter.lab.a - darker.lab.a) ** 2 + (lighter.lab.b - darker.lab.b) ** 2;
      const edge = { from: darker.color.index, to: lighter.color.index, cost, count: observed.count };
      next.get(edge.from).push(edge);
      edges.set(`${edge.from}-${edge.to}`, edge);
    }

    // Squared perceptual steps favor smooth paths without inventing missing contacts.
    const forward = new Map([[black.color.index, { cost: 0, indices: [black.color.index] }]]);
    for (const { color } of entries) {
      const path = forward.get(color.index);
      if (!path) continue;
      for (const edge of next.get(color.index)) {
        const cost = path.cost + edge.cost;
        if (!forward.has(edge.to) || cost < forward.get(edge.to).cost) {
          forward.set(edge.to, { cost, indices: [...path.indices, edge.to] });
        }
      }
    }
    const backward = new Map([[white.color.index, { cost: 0, indices: [white.color.index] }]]);
    for (const { color } of [...entries].reverse()) {
      for (const edge of next.get(color.index)) {
        const path = backward.get(edge.to);
        if (!path) continue;
        const cost = edge.cost + path.cost;
        if (!backward.has(color.index) || cost < backward.get(color.index).cost) {
          backward.set(color.index, { cost, indices: [color.index, ...path.indices] });
        }
      }
    }
    for (const { color } of entries) {
      const start = forward.get(color.index);
      const end = backward.get(color.index);
      if (!start || !end) continue;
      const indices = [...start.indices, ...end.indices.slice(1)];
      const minContacts = Math.min(...indices.slice(1).map((index, position) =>
        edges.get(`${indices[position]}-${index}`).count));
      const ramp = { indices, imageId: image.id, minContacts, cost: start.cost + end.cost };
      const key = indices.join('-');
      if (!candidates.has(key) || minContacts > candidates.get(key).minContacts) candidates.set(key, ramp);
    }
  }

  // Keep enough representative columns to cover every tone on a supported complete path.
  const uncovered = new Set([...candidates.values()].flatMap(ramp => ramp.indices));
  const ramps = [];
  while (uncovered.size) {
    let best;
    let bestCoverage = 0;
    for (const ramp of candidates.values()) {
      const coverage = ramp.indices.filter(index => uncovered.has(index)).length;
      if (coverage > bestCoverage || coverage === bestCoverage && coverage > 0 &&
          (ramp.cost < best.cost || ramp.cost === best.cost && ramp.minContacts > best.minContacts)) {
        best = ramp;
        bestCoverage = coverage;
      }
    }
    ramps.push(best);
    best.indices.forEach(index => uncovered.delete(index));
  }
  const segments = new Map();
  for (const ramp of ramps) {
    for (let position = 1; position < ramp.indices.length; position += 1) {
      const indices = ramp.indices.slice(position - 1, position + 1);
      segments.set(indices.join('-'), { indices });
    }
  }
  return { ramps, segments: [...segments.values()] };
}

/** Legacy row limits migrate once to an envelope of the tones they admitted. */
function getTalentLightnessLimits(settings, virtualPalette) {
  if (settings.minLightness !== undefined || settings.maxLightness !== undefined) {
    return { minLightness: settings.minLightness, maxLightness: settings.maxLightness };
  }
  const minLevel = settings.minLevel ?? 0;
  const maxLevel = settings.maxLevel ?? 16;
  const colors = virtualPalette.filter(color => {
    const level = color.brightnessBands[0] + color.brightnessBands[1];
    return level >= minLevel && level <= maxLevel;
  });
  return {
    minLightness: minLevel === 0 ? 0 : Math.floor(100 * Math.min(...colors.map(color => color.lightness))),
    maxLightness: maxLevel === 16 ? 100 : Math.ceil(100 * Math.max(...colors.map(color => color.lightness)))
  };
}

/** Group neighboring measured lightness values; no group spans more than three percentage points. */
function buildTalentBrightnessLevels(virtualPalette) {
  const entries = virtualPalette.map(color => ({ color, lab: rgbToOklab(...color.rgb) }))
    .sort((first, second) => first.lab.lightness - second.lab.lightness || first.color.index - second.color.index);
  const levels = [];
  for (const entry of entries) {
    const level = levels.at(-1);
    if (!level || entry.lab.lightness - level[0].lab.lightness > 0.03) levels.push([entry]);
    else level.push(entry);
  }
  return levels;
}

/** Share virtual colors across similar vertical pairs; preserve detail with native C64 colors. */
function mapToTalentVirtualPalette(source, virtualPalette, settings = {}, ditherAmount = 0) {
  const { minLightness, maxLightness } = getTalentLightnessLimits(settings, virtualPalette);
  if (!Number.isInteger(minLightness) || !Number.isInteger(maxLightness) ||
      minLightness < 0 || maxLightness > 100 || minLightness > maxLightness) {
    throw new RangeError('Talent lightness limits require 0 <= minLightness <= maxLightness <= 100.');
  }
  const excluded = new Set(settings.excludedIndices ?? []);
  for (const color of virtualPalette) {
    if (color.lightness * 100 < minLightness - 1e-6 || color.lightness * 100 > maxLightness + 1e-6) {
      excluded.add(color.index);
    }
  }

  const nativeBands = new Map();
  for (const color of virtualPalette) {
    if (!color.colorIndices || color.colorIndices[0] !== color.colorIndices[1]) continue;
    const band = color.brightnessBands[0];
    if (!nativeBands.has(band)) nativeBands.set(band, []);
    nativeBands.get(band).push({ color, lab: rgbToOklab(...color.rgb) });
  }
  if (!nativeBands.size) throw new Error('Talent mapping requires native C64 colors in its palette.');
  // Keep native brightness calibration while filtering the enabled solid palette entries.
  const nativeLevels = [...nativeBands.entries()].sort(([first], [second]) => first - second)
    .map(([, entries]) => entries);
  const pairs = new ImageData(source.width, Math.ceil(source.height / 2));
  const similaritySquared = 0.03 ** 2;
  let needsNative = false;
  for (let y = 0; y + 1 < source.height; y += 2) {
    for (let x = 0; x < source.width; x += 1) {
      const upper = (y * source.width + x) * 4;
      const lower = upper + source.width * 4;
      const alpha = source.data[upper + 3];
      if (!alpha || alpha !== source.data[lower + 3]) {
        if (alpha || source.data[lower + 3]) needsNative = true;
        continue;
      }
      const first = rgbToOklab(source.data[upper], source.data[upper + 1], source.data[upper + 2]);
      const second = rgbToOklab(source.data[lower], source.data[lower + 1], source.data[lower + 2]);
      const distance = (first.lightness - second.lightness) ** 2 +
        (first.a - second.a) ** 2 + (first.b - second.b) ** 2;
      if (distance > similaritySquared) {
        needsNative = true;
        continue;
      }
      const pair = ((y / 2) * source.width + x) * 4;
      for (let channel = 0; channel < 3; channel += 1) {
        pairs.data[pair + channel] = linearToSrgb((srgbToLinear(source.data[upper + channel]) +
          srgbToLinear(source.data[lower + channel])) / 2);
      }
      pairs.data[pair + 3] = alpha;
    }
  }
  if (source.height % 2) {
    for (let x = 0; x < source.width; x += 1) {
      if (source.data[((source.height - 1) * source.width + x) * 4 + 3]) needsNative = true;
    }
  }
  if (needsNative && !nativeLevels.some(level => level.some(entry => !excluded.has(entry.color.index)))) {
    const cause = new Error('Talent detail pixels require at least one enabled solid color in the selected lightness range.');
    cause.code = 'TALENT_SOLID_COLOR_REQUIRED';
    throw cause;
  }
  const mapped = needsNative
    ? mapToVirtualPaletteLevels(source, nativeLevels, 0, { excludedIndices: [...excluded] })
    : { pixels: new ImageData(new Uint8ClampedArray(source.data), source.width, source.height),
      virtualIndices: new Uint8Array(source.width * source.height).fill(255) };

  // One dither decision per pair keeps both displayed pixels on the same virtual tone.
  const virtual = mapToVirtualPaletteLevels(pairs, buildTalentBrightnessLevels(virtualPalette), ditherAmount,
    { excludedIndices: [...excluded] });
  for (let y = 0; y + 1 < source.height; y += 2) {
    for (let x = 0; x < source.width; x += 1) {
      const pair = (y / 2) * source.width + x;
      if (!pairs.data[pair * 4 + 3]) continue;
      const upper = y * source.width + x;
      const lower = upper + source.width;
      mapped.virtualIndices[upper] = mapped.virtualIndices[lower] = virtual.virtualIndices[pair];
      for (let channel = 0; channel < 3; channel += 1) {
        mapped.pixels.data[upper * 4 + channel] = mapped.pixels.data[lower * 4 + channel] =
          virtual.pixels.data[pair * 4 + channel];
      }
    }
  }
  return mapped;
}
