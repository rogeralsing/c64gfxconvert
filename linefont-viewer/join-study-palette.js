/* Static 4×4 character palette for the wireframe join study. */
(function (root) {
  "use strict";

  const MASK_SPACE = 1 << 16;
  const BORDER = 0xf99f;
  const NOT_LEFT = 0xeeee;
  const NOT_RIGHT = 0x7777;
  const counts = new Uint8Array(MASK_SPACE);
  const components = new Uint8Array(MASK_SPACE);

  function eightWayNeighbors(bits) {
    const across = ((bits & NOT_LEFT) >>> 1) | ((bits & NOT_RIGHT) << 1);
    const row = bits | across;
    return across | (row >>> 4) | (row << 4);
  }

  for (let mask = 1; mask < MASK_SPACE; mask++) {
    counts[mask] = counts[mask >>> 1] + (mask & 1);
    let remaining = mask;
    while (remaining) {
      let connected = remaining & -remaining;
      let expanded = connected;
      do {
        connected = expanded;
        expanded |= eightWayNeighbors(connected) & remaining;
      } while (expanded !== connected);
      components[mask]++;
      remaining ^= connected;
    }
  }

  // Protect the pixels that connect to neighboring chars first. Penalize
  // splitting a connected arm, and keep unnecessary ink relatively costly.
  function difference(original, replacement) {
    const removed = original & ~replacement;
    const added = replacement & ~original;
    return 3 * counts[removed] + 2 * counts[added] +
      10 * counts[removed & BORDER] + 4 * counts[added & BORDER] +
      6 * Math.max(0, components[replacement] - components[original]);
  }

  function nearest(original, candidates) {
    let best = candidates[0];
    let lowest = difference(original, best);
    for (let index = 1; index < candidates.length && lowest; index++) {
      const mask = candidates[index];
      const cost = difference(original, mask);
      if (cost < lowest) {
        best = mask;
        lowest = cost;
      }
    }
    return [best, lowest];
  }

  // Train on final composite cells only. Candidate masks are the most
  // frequent bank misses, but their rank is determined by the improvement
  // across all training cells, including near matches.
  function train(bank, frames, maxSlots = 55) {
    if (maxSlots <= 0) return [];

    const available = new Set(bank);
    const frequency = new Uint32Array(MASK_SPACE);
    for (const {masks} of frames) {
      for (const mask of masks) {
        if (mask && !available.has(mask)) frequency[mask]++;
      }
    }

    const missing = [];
    for (let mask = 1; mask < MASK_SPACE; mask++) {
      if (frequency[mask]) missing.push(mask);
    }
    missing.sort((a, b) => frequency[b] - frequency[a] || a - b);

    const initial = bank.filter(Boolean);
    const bestCosts = Uint16Array.from(missing, mask => (
      initial.length ? nearest(mask, initial)[1] : 0xffff
    ));
    const weights = Uint32Array.from(missing, mask => frequency[mask]);
    const options = missing.slice(0, Math.max(128, maxSlots * 3)).map(mask => ({
      mask,
      costs: Uint16Array.from(missing, original => difference(original, mask)),
    }));

    const chosen = [];
    while (chosen.length < maxSlots && options.length) {
      let bestIndex = -1;
      let bestGain = 0;
      for (let candidate = 0; candidate < options.length; candidate++) {
        const {costs} = options[candidate];
        let gain = 0;
        for (let i = 0; i < bestCosts.length; i++) {
          if (costs[i] < bestCosts[i]) gain += (bestCosts[i] - costs[i]) * weights[i];
        }
        if (gain > bestGain) {
          bestGain = gain;
          bestIndex = candidate;
        }
      }

      if (bestIndex < 0) break;
      const [{mask, costs}] = options.splice(bestIndex, 1);
      chosen.push(mask);
      for (let i = 0; i < bestCosts.length; i++) {
        if (costs[i] < bestCosts[i]) bestCosts[i] = costs[i];
      }
    }
    return chosen;
  }

  // Enumerate supersets that retain every pixel and add at most two. Each
  // new pixel must touch the original mask or attach through the other one.
  function visitConnectedAdditions(mask, visit) {
    const unlit = (MASK_SPACE - 1) ^ mask;
    const adjacent = eightWayNeighbors(mask) & unlit;
    let firstChoices = adjacent;
    while (firstChoices) {
      const first = firstChoices & -firstChoices;
      firstChoices ^= first;
      const single = mask | first;
      visit(single);

      // When both additions touch the original, use ascending bit order
      // to visit the pair once. The others can only attach via the first bit.
      let secondChoices = firstChoices | (eightWayNeighbors(first) & unlit & ~adjacent);
      while (secondChoices) {
        const second = secondChoices & -secondChoices;
        secondChoices ^= second;
        visit(single | second);
      }
    }
  }

  // A target costs one patch in every frame where it appears. Greedy
  // coverage counts that cost once per frame, independent of cell frequency.
  function trainAdditive(outputBank, frames, maxSlots = 55) {
    const fixed = new Set(outputBank);
    const frequency = new Uint32Array(MASK_SPACE);
    const lastFrame = new Uint32Array(MASK_SPACE);
    for (let frame = 0; frame < frames.length; frame++) {
      for (const mask of frames[frame].masks) {
        if (!mask || fixed.has(mask) || lastFrame[mask] === frame + 1) continue;
        lastFrame[mask] = frame + 1;
        frequency[mask]++;
      }
    }

    const coverage = new Uint32Array(MASK_SPACE);
    const addedPixels = new Uint32Array(MASK_SPACE);
    const targetsByCandidate = new Array(MASK_SPACE);
    const candidatesByTarget = new Array(MASK_SPACE);
    for (let target = 1; target < MASK_SPACE; target++) {
      const weight = frequency[target];
      if (!weight) continue;
      const candidates = [target];
      visitConnectedAdditions(target, candidate => candidates.push(candidate));
      if (candidates.some(mask => fixed.has(mask))) continue;

      candidatesByTarget[target] = candidates;
      for (const mask of candidates) {
        (targetsByCandidate[mask] ??= []).push(target);
        coverage[mask] += weight;
        addedPixels[mask] += counts[mask ^ target] * weight;
      }
    }

    const chosen = [];
    while (chosen.length < maxSlots) {
      let best = 0;
      for (let mask = 1; mask < MASK_SPACE; mask++) {
        if (coverage[mask] > coverage[best] ||
            (coverage[mask] === coverage[best] && addedPixels[mask] < addedPixels[best])) {
          best = mask;
        }
      }
      if (!best) break;
      chosen.push(best);

      // Clear each covered target and subtract its weight from all the
      // alternatives. Their lists contain only candidates for this target.
      for (const target of targetsByCandidate[best]) {
        const weight = frequency[target];
        if (!weight) continue;
        frequency[target] = 0;
        for (const mask of candidatesByTarget[target]) {
          coverage[mask] -= weight;
          addedPixels[mask] -= counts[mask ^ target] * weight;
        }
      }
    }
    return chosen;
  }

  function closestSuperset(mask, available) {
    let best = mask;
    let lowest = Infinity;
    visitConnectedAdditions(mask, candidate => {
      if (!available[candidate]) return;
      const cost = difference(mask, candidate);
      if (cost < lowest) {
        best = candidate;
        lowest = cost;
      }
    });
    return best;
  }

  function buildMappings(bank, palette) {
    const candidates = [...new Set([...bank, ...palette])].filter(Boolean);
    const available = new Uint8Array(MASK_SPACE);
    for (const mask of candidates) available[mask] = 1;
    const mapping = new Uint16Array(MASK_SPACE);
    const hybridMapping = new Uint16Array(MASK_SPACE);

    for (let mask = 1; mask < MASK_SPACE; mask++) {
      if (available[mask]) {
        mapping[mask] = mask;
        hybridMapping[mask] = mask;
      } else {
        if (candidates.length) mapping[mask] = nearest(mask, candidates)[0];
        hybridMapping[mask] = closestSuperset(mask, available);
      }
    }
    return {mapping, hybridMapping, available};
  }

  function evaluate(bank, palette, frames, outputBank = bank) {
    const {mapping, hybridMapping, available} = buildMappings(outputBank, palette);
    const codes = new Map(bank.map((mask, index) => [mask, index + 1]));
    const stampFrequency = new Uint32Array(MASK_SPACE);
    const finalFrequency = new Uint32Array(MASK_SPACE);
    const fixedFrequency = new Uint32Array(MASK_SPACE);
    const stats = {
      frameCount: frames.length,
      finalCells: 0,
      stampCount: 0,
      stampBankCodesUsed: 0,
      finalBankCodesUsed: 0,
      shortStamps: 0,
      shortFinal: 0,
      legacyPatchesPerFrame: 0,
      batchPatchesPerFrame: 0,
      remainingPatchesPerFrame: 0,
      hybridPatchesPerFrame: 0,
      maxHybridPatchesPerFrame: 0,
      hybridRoundedCells: 0,
      hybridAddedPixels: 0,
      exactCells: 0,
      joinCells: 0,
      exactJoinCells: 0,
      addedPixels: 0,
      removedPixels: 0,
      lostBoundaryPixels: 0,
      changedBoundaryCells: 0,
      junctionCells: 0,
      exactJunctionCells: 0,
    };

    // A missed pattern costs one patch per frame regardless of how many
    // cells use it. Thus the two batch counters use sets per frame.
    for (const frame of frames) {
      const batchMisses = new Set();
      const fixedMisses = new Set();
      const hybridMisses = new Set();
      stats.legacyPatchesPerFrame += frame.legacyPatches;
      for (const mask of frame.stampMasks) {
        if (!mask) continue;
        stampFrequency[mask]++;
        stats.stampCount++;
        if (counts[mask] <= 2) stats.shortStamps++;
      }
      for (let cell = 0; cell < frame.masks.length; cell++) {
        const mask = frame.masks[cell];
        if (!mask) continue;
        const fixed = mapping[mask];
        const hybrid = hybridMapping[mask];
        finalFrequency[mask]++;
        fixedFrequency[fixed]++;
        stats.finalCells++;
        if (counts[mask] <= 2) stats.shortFinal++;
        if (!codes.has(mask)) batchMisses.add(mask);
        if (!available[hybrid]) hybridMisses.add(hybrid);
        if (hybrid !== mask) stats.hybridRoundedCells++;
        stats.hybridAddedPixels += counts[hybrid & ~mask];
        if (fixed === mask) {
          stats.exactCells++;
        } else {
          fixedMisses.add(mask);
          stats.addedPixels += counts[fixed & ~mask];
          stats.removedPixels += counts[mask & ~fixed];
          stats.lostBoundaryPixels += counts[(mask & ~fixed) & BORDER];
          if ((mask ^ fixed) & BORDER) stats.changedBoundaryCells++;
        }

        // Some joined cells contain an unrelated edge as well, so a knot
        // assembled from only the incident edges may not fill the whole cell.
        if (frame.contributions[cell] >= 2) {
          stats.joinCells++;
          if (fixed === mask) stats.exactJoinCells++;
        }
        if (frame.vertexDegree[cell] >= 2) {
          stats.junctionCells++;
          if (frame.vertexMasks[cell] === mask) stats.exactJunctionCells++;
        }
      }
      stats.batchPatchesPerFrame += batchMisses.size;
      stats.remainingPatchesPerFrame += fixedMisses.size;
      stats.hybridPatchesPerFrame += hybridMisses.size;
      stats.maxHybridPatchesPerFrame = Math.max(stats.maxHybridPatchesPerFrame, hybridMisses.size);
    }

    for (const key of ["legacyPatchesPerFrame", "batchPatchesPerFrame", "remainingPatchesPerFrame", "hybridPatchesPerFrame"]) {
      stats[key] /= frames.length || 1;
    }

    const glyphs = [];
    for (let mask = 1; mask < MASK_SPACE; mask++) {
      const stamps = stampFrequency[mask];
      const final = finalFrequency[mask];
      const fixedFinal = fixedFrequency[mask];
      if (!stamps && !final && !fixedFinal) continue;
      const bankCode = codes.get(mask) ?? null;
      if (bankCode && stamps) stats.stampBankCodesUsed++;
      if (bankCode && final) stats.finalBankCodesUsed++;
      glyphs.push({mask, stamps, final, fixedFinal, bankCode, fixedMask: mapping[mask]});
    }
    return {glyphs, stats, mapping, hybridMapping};
  }

  const api = {train, trainAdditive, evaluate};
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.JoinStudyPalette = api;
})(globalThis);
