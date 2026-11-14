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

/** Match every source pixel independently to the nearest actual Talent virtual color. */
function mapToTalentVirtualPalette(source, virtualPalette, settings = {}) {
  const { minLightness, maxLightness } = getTalentLightnessLimits(settings, virtualPalette);
  if (!Number.isInteger(minLightness) || !Number.isInteger(maxLightness) ||
      minLightness < 0 || maxLightness > 100 || minLightness > maxLightness) {
    throw new RangeError('Talent lightness limits require 0 <= minLightness <= maxLightness <= 100.');
  }
  const excluded = new Set(settings.excludedIndices ?? []);
  const entries = virtualPalette.filter(color => !excluded.has(color.index) &&
    color.lightness * 100 >= minLightness - 1e-6 && color.lightness * 100 <= maxLightness + 1e-6)
    .map(color => ({ color, lab: rgbToOklab(...color.rgb) }));
  if (!entries.length) throw new Error('At least one enabled virtual color is required in the selected lightness range.');
  const pixels = new ImageData(new Uint8ClampedArray(source.data), source.width, source.height);
  const virtualIndices = new Uint8Array(source.width * source.height);
  virtualIndices.fill(255);
  for (let pixel = 0; pixel < virtualIndices.length; pixel += 1) {
    const offset = pixel * 4;
    if (source.data[offset + 3] === 0) continue;
    const lab = rgbToOklab(source.data[offset], source.data[offset + 1], source.data[offset + 2]);
    let best;
    let minimum = Infinity;
    for (const entry of entries) {
      const distance = (lab.lightness - entry.lab.lightness) ** 2 +
        (lab.a - entry.lab.a) ** 2 + (lab.b - entry.lab.b) ** 2;
      if (distance < minimum || distance === minimum && entry.color.index < best.index) {
        minimum = distance;
        best = entry.color;
      }
    }
    virtualIndices[pixel] = best.index;
    pixels.data.set(best.rgb.map(Math.round), offset);
  }
  return { pixels, virtualIndices };
}
