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

/** Fit connected color regions to complete dark-to-light paths before ordered dithering. */
function mapToTalentVirtualPalette(source, virtualPalette, toneModel, ditherAmount = 0, settings = {}) {
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
  const byIndex = new Map(entries.map(entry => [entry.color.index, entry]));
  // Removing a tone removes its incident segments; exclusions never bridge a missing neighbor.
  const segments = new Set(toneModel.segments.map(segment => segment.indices.join('-')));
  const fragments = new Map();
  for (const ramp of toneModel.ramps) {
    let fragment = [];
    const retain = () => {
      if (fragment.length) fragments.set(fragment.map(entry => entry.color.index).join('-'), fragment);
      fragment = [];
    };
    for (const index of ramp.indices) {
      const entry = byIndex.get(index);
      if (!entry) { retain(); continue; }
      if (fragment.length && !segments.has(`${fragment.at(-1).color.index}-${index}`)) retain();
      fragment.push(entry);
    }
    retain();
  }
  const amount = Math.max(0, Math.min(1, ditherAmount));
  const candidates = [...fragments.values()].map(fragment => {
    const states = [];
    for (let index = 0; index < fragment.length; index += 1) {
      const first = fragment[index];
      if (amount === 0 || fragment.length === 1) {
        states.push({ first, second: first, lightness: 0, a: 0, b: 0,
          min: index === 0 ? -Infinity : (fragment[index - 1].lab.lightness + first.lab.lightness) / 2,
          max: index + 1 === fragment.length ? Infinity : (first.lab.lightness + fragment[index + 1].lab.lightness) / 2 });
      }
      if (amount > 0 && index + 1 < fragment.length) {
        const second = fragment[index + 1];
        states.push({ first, second, lightness: second.lab.lightness - first.lab.lightness,
          a: second.lab.a - first.lab.a, b: second.lab.b - first.lab.b,
          min: index === 0 ? -Infinity : first.lab.lightness,
          max: index + 2 === fragment.length ? Infinity : second.lab.lightness });
      }
    }
    return states;
  });
  if (!candidates.length) throw new Error('Talent mapping requires an enabled tone on an observed scale.');

  function probability(target, state) {
    if (state.lightness === 0) return 0;
    const fraction = (target.lightness - state.first.lab.lightness) / state.lightness;
    if (fraction <= 0) return 0;
    if (fraction >= 1) return 1;
    const endpoint = fraction < 0.5 ? 0 : 1;
    return endpoint + (fraction - endpoint) * amount;
  }

  function fit(samples, states, trace = false) {
    let previous = new Float64Array(states.length);
    let current = new Float64Array(states.length);
    const parents = trace ? new Uint16Array(samples.length * states.length) : null;
    for (let position = 0; position < samples.length; position += 1) {
      const sample = samples[position];
      let best = Infinity;
      let parent = 0;
      // A prefix minimum permits staying or traversing successive observed steps.
      // Unrepresented lightness intervals consume no source pixel, but never cross a fragment break.
      for (let index = 0; index < states.length; index += 1) {
        if (previous[index] < best) { best = previous[index]; parent = index; }
        const state = states[index];
        // Measured source lightness admits the stage; chroma cannot skip an intervening tone.
        if (sample.lab.lightness < state.min || sample.lab.lightness > state.max) {
          current[index] = Infinity;
          continue;
        }
        const mix = probability(sample.lab, state);
        const lightness = sample.lab.lightness - state.first.lab.lightness - mix * state.lightness;
        const a = sample.lab.a - state.first.lab.a - mix * state.a;
        const b = sample.lab.b - state.first.lab.b - mix * state.b;
        current[index] = best + (lightness * lightness + a * a + b * b) * sample.pixels.length;
        if (parents) parents[position * states.length + index] = parent;
      }
      [previous, current] = [current, previous];
    }
    let last = 0;
    for (let index = 1; index < states.length; index += 1) if (previous[index] < previous[last]) last = index;
    const cost = previous[last];
    if (!trace) return { cost };
    const steps = new Uint16Array(samples.length);
    for (let position = samples.length - 1; position >= 0; position -= 1) {
      steps[position] = last;
      last = parents[position * states.length + last];
    }
    return { cost, steps };
  }

  const pixelCount = source.width * source.height;
  const labs = Array.from({ length: pixelCount }, (_, pixel) => {
    const offset = pixel * 4;
    return source.data[offset + 3] === 0 ? null
      : rgbToOklab(source.data[offset], source.data[offset + 1], source.data[offset + 2]);
  });
  const visited = new Uint8Array(pixelCount);
  const queue = new Int32Array(pixelCount);
  const thresholds = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];
  const pixels = new ImageData(new Uint8ClampedArray(source.data), source.width, source.height);
  const virtualIndices = new Uint8Array(pixelCount);
  virtualIndices.fill(255);

  for (let seed = 0; seed < pixelCount; seed += 1) {
    if (visited[seed] || !labs[seed]) continue;
    const samplesByRgb = new Map();
    let head = 0;
    let tail = 1;
    queue[0] = seed;
    visited[seed] = 1;
    const visit = (neighbor, current) => {
      if (visited[neighbor] || !labs[neighbor]) return;
      const first = labs[current];
      const second = labs[neighbor];
      // Smooth shading shares a path; sharp lightness or chroma edges start another region.
      if (Math.abs(first.lightness - second.lightness) > 0.12 ||
          (first.a - second.a) ** 2 + (first.b - second.b) ** 2 > 0.06 ** 2) return;
      visited[neighbor] = 1;
      queue[tail++] = neighbor;
    };
    while (head < tail) {
      const pixel = queue[head++];
      const offset = pixel * 4;
      const rgb = source.data[offset] * 65536 + source.data[offset + 1] * 256 + source.data[offset + 2];
      if (!samplesByRgb.has(rgb)) samplesByRgb.set(rgb, { lab: labs[pixel], pixels: [] });
      samplesByRgb.get(rgb).pixels.push(pixel);
      if (pixel % source.width > 0) visit(pixel - 1, pixel);
      if (pixel % source.width + 1 < source.width) visit(pixel + 1, pixel);
      if (pixel >= source.width) visit(pixel - source.width, pixel);
      if (pixel + source.width < pixelCount) visit(pixel + source.width, pixel);
    }
    const samples = [...samplesByRgb.values()].sort((first, second) =>
      first.lab.lightness - second.lab.lightness || first.lab.a - second.lab.a || first.lab.b - second.lab.b);
    let winner = candidates[0];
    let best = Infinity;
    // Every candidate remains open until the whole region's dark-to-light sequence is scored.
    for (const candidate of candidates) {
      const { cost } = fit(samples, candidate);
      if (cost < best) { best = cost; winner = candidate; }
    }
    const { steps } = fit(samples, winner, true);
    for (let position = 0; position < samples.length; position += 1) {
      const sample = samples[position];
      const state = winner[steps[position]];
      const mix = probability(sample.lab, state);
      for (const pixel of sample.pixels) {
        const threshold = (thresholds[Math.floor(pixel / source.width) % 4][pixel % source.width % 4] + 0.5) / 16;
        const selected = threshold < mix ? state.second : state.first;
        virtualIndices[pixel] = selected.color.index;
        for (let channel = 0; channel < 3; channel += 1) pixels.data[pixel * 4 + channel] = Math.round(selected.color.rgb[channel]);
      }
    }
  }
  return { pixels, virtualIndices };
}
