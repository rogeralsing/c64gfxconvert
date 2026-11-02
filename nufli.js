/**
 * Standard, single-frame NUFLI: 8 × 2 bitmap attributes, six expanded hires
 * underlays, and two sprites covering the 24-pixel FLI bug. Bitmap ink covers
 * sprites; sprites cover bitmap paper. Underlay colors change on odd rows,
 * one scanline after bitmap attributes. No virtual colors or frame blending.
 *
 * The fitter searches bitmap and underlay colors jointly, as in Mufflon, and
 * joins adjacent sections with dynamic programming. It reserves all eight
 * sprite-Y writes before allocating spare writes to the left-edge colors.
 * Main-area error is minimized first; left-edge updates are fitted afterwards.
 * Format reference: Mufflon v2.0, convert_nufli(), SVN r1440.
 */
function optimizeNufliImage(source, palette, brightnessBands) {
  if (source?.width !== 320 || source.height !== 200) {
    throw new Error('NUFLI requires a 320 × 200 source image.');
  }
  const min = Math.min;
  const prepared = prepareC64FittingTargets([source], palette, brightnessBands, 0);
  const targets = prepared.frameTargets[0];
  const errors = new Float64Array(256);
  for (let i = 0; i < 256; i += 1) {
    errors[i] = prepared.brightnessError[i] * 1e8 + prepared.chromaError[i];
  }
  const pairCosts = new Float64Array(256 * 4096);
  // A sprite bit covers two hires pixels. Each pixel may independently put ink
  // in front, but paper and sprite cannot coexist within an uncovered pair.
  for (let pair = 0; pair < 256; pair += 1) {
    const left = (pair >> 4) * 16;
    const right = (pair & 15) * 16;
    for (let sprite = 0; sprite < 16; sprite += 1) {
      for (let ink = 0; ink < 16; ink += 1) {
        const underlayCost = min(errors[left + ink], errors[left + sprite]) +
          min(errors[right + ink], errors[right + sprite]);
        for (let paper = 0; paper < 16; paper += 1) {
          const paperCost = min(errors[left + ink], errors[left + paper]) +
            min(errors[right + ink], errors[right + paper]);
          pairCosts[pair * 4096 + sprite * 256 + ink * 16 + paper] = min(paperCost, underlayCost);
        }
      }
    }
  }
  const screenColors = new Uint8Array(4000);
  const underlayColors = new Uint8Array(606);
  const registerUpdates = new Uint8Array(606);
  const pairAt = (x, y) => targets[y * 320 + x] * 16 + targets[y * 320 + x + 1];
  const tableRow = y => (y + 1) >> 1;
  const spriteAt = (x, y) => underlayColors[tableRow(y) * 6 + Math.floor((x - 24) / 48)];
  const sectionCosts = new Float64Array(6 * 100 * 256);
  const sectionColors = new Uint8Array(sectionCosts.length * 6);
  const halfCosts = new Float64Array(6 * 2 * 4096);
  // For each 48 × 2 section, try both sprite colors and all bitmap colors.
  // Factoring the two scanlines avoids re-scoring pixel pairs 16 times.
  for (let column = 0; column < 6; column += 1) {
    for (let row = 0; row < 100; row += 1) {
      for (let tile = 0; tile < 6; tile += 1) {
        for (let dy = 0; dy < 2; dy += 1) {
          const x = 24 + column * 48 + tile * 8;
          const y = row * 2 + dy;
          const a = pairAt(x, y) * 4096;
          const b = pairAt(x + 2, y) * 4096;
          const c = pairAt(x + 4, y) * 4096;
          const d = pairAt(x + 6, y) * 4096;
          const offset = (tile * 2 + dy) * 4096;
          for (let colors = 0; colors < 4096; colors += 1) {
            halfCosts[offset + colors] = pairCosts[a + colors] + pairCosts[b + colors] +
              pairCosts[c + colors] + pairCosts[d + colors];
          }
        }
      }
      for (let top = 0; top < 16; top += 1) {
        for (let bottom = 0; bottom < 16; bottom += 1) {
          const section = (column * 100 + row) * 256 + top * 16 + bottom;
          let cost = 0;
          for (let tile = 0; tile < 6; tile += 1) {
            const a = tile * 8192 + top * 256;
            const b = tile * 8192 + 4096 + bottom * 256;
            let best = Infinity;
            let chosen = 0;
            for (let colors = 0; colors < 256; colors += 1) {
              const next = halfCosts[a + colors] + halfCosts[b + colors];
              if (next < best) { best = next; chosen = colors; }
              if (best === 0) break;
            }
            cost += best;
            sectionColors[section * 6 + tile] = chosen;
          }
          sectionCosts[section] = cost;
        }
      }
    }
  }

  // Adjacent sections share a sprite color. Keep a frontier for 0..8 spare
  // writes in the split window, then combine columns to guarantee eight total.
  // All eight Y updates must occur inside Mufflon's $3e..$52 table window.
  const chains = [];
  for (let column = 0; column < 6; column += 1) {
    let costs = new Float64Array(144).fill(Infinity);
    let writes = new Uint16Array(144).fill(65535);
    costs.fill(0, 0, 16);
    writes.fill(0, 0, 16);
    const trace = new Int16Array(100 * 144).fill(-1);
    for (let row = 0; row < 100; row += 1) {
      const nextCosts = new Float64Array(144).fill(Infinity);
      const nextWrites = new Uint16Array(144).fill(65535);
      for (let state = 0; state < 144; state += 1) {
        if (!Number.isFinite(costs[state])) continue;
        const top = state & 15;
        for (let bottom = 0; bottom < 16; bottom += 1) {
          const same = top === bottom;
          const spare = same && row + 1 >= 0x3e && row + 1 <= 0x52;
          const nextState = min(8, (state >> 4) + Number(spare)) * 16 + bottom;
          const cost = costs[state] + sectionCosts[(column * 100 + row) * 256 + top * 16 + bottom];
          const changes = writes[state] + Number(!same);
          // Prefer the previous color on ties to leave more register slots free.
          if (cost < nextCosts[nextState] || (cost === nextCosts[nextState] && changes < nextWrites[nextState])) {
            nextCosts[nextState] = cost;
            nextWrites[nextState] = changes;
            trace[row * 144 + nextState] = state;
          }
        }
      }
      costs = nextCosts;
      writes = nextWrites;
    }
    const ends = new Uint8Array(9);
    for (let spare = 0; spare <= 8; spare += 1) {
      let best = spare * 16;
      for (let color = 1; color < 16; color += 1) {
        const state = spare * 16 + color;
        if (costs[state] < costs[best] || (costs[state] === costs[best] && writes[state] < writes[best])) best = state;
      }
      ends[spare] = best;
    }
    chains.push({ costs, writes, trace, ends });
  }
  let totals = new Float64Array(9).fill(Infinity);
  let changes = new Uint16Array(9).fill(65535);
  totals[0] = changes[0] = 0;
  const allocation = new Int16Array(6 * 9).fill(-1);
  for (let column = 0; column < 6; column += 1) {
    const nextTotals = new Float64Array(9).fill(Infinity);
    const nextChanges = new Uint16Array(9).fill(65535);
    const chain = chains[column];
    for (let previous = 0; previous <= 8; previous += 1) {
      for (let spare = 0; spare <= 8; spare += 1) {
        const total = min(8, previous + spare);
        const end = chain.ends[spare];
        const cost = totals[previous] + chain.costs[end];
        const writes = changes[previous] + chain.writes[end];
        if (cost < nextTotals[total] || (cost === nextTotals[total] && writes < nextChanges[total])) {
          nextTotals[total] = cost;
          nextChanges[total] = writes;
          allocation[column * 9 + total] = previous * 9 + spare;
        }
      }
    }
    totals = nextTotals;
    changes = nextChanges;
  }
  let spare = 8;
  for (let column = 5; column >= 0; column -= 1) {
    const allocated = allocation[column * 9 + spare];
    const chain = chains[column];
    let state = chain.ends[allocated % 9];
    for (let row = 99; row >= 0; row -= 1) {
      const bottom = state & 15;
      underlayColors[(row + 1) * 6 + column] = bottom;
      state = chain.trace[row * 144 + state];
      const top = state & 15;
      const section = (column * 100 + row) * 256 + top * 16 + bottom;
      screenColors.set(sectionColors.subarray(section * 6, section * 6 + 6), row * 40 + 3 + column * 6);
    }
    underlayColors[column] = state & 15;
    spare = Math.floor(allocated / 9);
  }
  // The rightmost eight pixels have no sprite underlay.
  for (let row = 0; row < 100; row += 1) {
    let best = Infinity;
    for (let colors = 0; colors < 256; colors += 1) {
      let cost = 0;
      for (let dy = 0; dy < 2; dy += 1) {
        for (let x = 312; x < 320; x += 2) cost += pairCosts[pairAt(x, row * 2 + dy) * 4096 + (colors & 15) * 256 + colors];
      }
      if (cost < best) { best = cost; screenColors[row * 40 + 39] = colors; }
    }
  }
  registerUpdates.set(underlayColors);
  const reserved = new Map();
  for (let sprite = 0; sprite < 8; sprite += 1) {
    let chosen = -1;
    let best = -1;
    for (let row = 0x3e; row <= 0x52; row += 1) {
      let free = 0;
      for (let slot = 1; slot < 6; slot += 1) {
        if (!reserved.has(row * 6 + slot) && underlayColors[row * 6 + slot] === underlayColors[(row - 1) * 6 + slot]) free += 1;
      }
      for (let slot = 0; slot < 6; slot += 1) {
        const index = row * 6 + slot;
        if (reserved.has(index) || underlayColors[index] !== underlayColors[index - 6]) continue;
        // Slot 1 cannot serve the left edge. Otherwise use the least crowded row.
        const score = (slot === 0 ? 100 : 0) + free;
        if (score > best) { best = score; chosen = index; }
      }
    }
    if (chosen < 0) throw new Error('NUFLI fitting could not schedule all sprite Y updates.');
    const command = 0x11 + sprite * 2;
    reserved.set(chosen, command);
    registerUpdates[chosen] = command;
  }

  const bugColors = new Uint8Array(400);
  let current = [0, 6, 11, 1];
  // The three multicolor slots are interchangeable. Search unordered color
  // sets, retaining existing slot assignments to minimize register writes.
  const triples = [];
  const quadruples = [];
  const quadrupleIndex = new Int16Array(65536).fill(-1);
  for (let a = 0; a < 16; a += 1) {
    for (let b = a + 1; b < 16; b += 1) {
      for (let c = b + 1; c < 16; c += 1) {
        const mask = (1 << a) | (1 << b) | (1 << c);
        triples.push({ colors: [a, b, c], mask });
        for (let d = c + 1; d < 16; d += 1) {
          const four = mask | (1 << d);
          quadrupleIndex[four] = quadruples.length;
          quadruples.push([a, b, c, d]);
        }
      }
    }
  }
  // Left-edge writes in slots 2..6 take effect on the next even scanline.
  const commands = [0x70, 0x50, 0xe0, 0x60];
  for (let row = 0; row < 100; row += 1) {
    const free = [];
    if (row > 0) {
      for (let slot = 1; slot < 6; slot += 1) {
        if (!reserved.has(row * 6 + slot) &&
            underlayColors[row * 6 + slot] === underlayColors[(row - 1) * 6 + slot]) free.push(slot);
      }
    }
    const available = row === 0 ? 4 : min(4, free.length);
    const bitmapFree = (row & 3) === 0;
    // Pair costs for two independently addressable hires layers and one wide
    // base color. On normal badlines both bitmap colors are freely selectable.
    const edgeCosts = new Float64Array(16 * 16 * 16 * 24);
    for (let hires = 0; hires < 16; hires += 1) {
      for (let ink = bitmapFree ? 0 : 15; ink < 16; ink += 1) {
        for (let base = 0; base < 16; base += 1) {
          const offset = ((hires * 16 + ink) * 16 + base) * 24;
          for (let pair = 0; pair < 24; pair += 1) {
            const x = (pair % 12) * 2;
            const y = row * 2 + Math.floor(pair / 12);
            const a = targets[y * 320 + x] * 16;
            const b = targets[y * 320 + x + 1] * 16;
            edgeCosts[offset + pair] = min(errors[a + ink], errors[a + hires], errors[a + base]) +
              min(errors[b + ink], errors[b + hires], errors[b + base]);
          }
        }
      }
    }
    function edgeCost(colors, ink, paper, tile) {
      const offset = (colors[0] * 16 + ink) * 16 * 24;
      let cost = 0;
      for (let dy = 0; dy < 2; dy += 1) {
        for (let p = 0; p < 4; p += 1) {
          const pair = dy * 12 + tile * 4 + p;
          cost += min(edgeCosts[offset + paper * 24 + pair],
            edgeCosts[offset + colors[1] * 24 + pair],
            edgeCosts[offset + colors[2] * 24 + pair],
            edgeCosts[offset + colors[3] * 24 + pair]);
        }
      }
      return cost;
    }
    let best = 0;
    for (let tile = 0; tile < 3; tile += 1) {
      let cost = edgeCost(current, 15, 15, tile);
      if (bitmapFree) {
        for (let ink = 0; ink < 16 && cost > 0; ink += 1) {
          for (let paper = 0; paper < 16 && cost > 0; paper += 1) cost = min(cost, edgeCost(current, ink, paper, tile));
        }
      }
      best += cost;
    }
    if (best === 0 || available === 0) { bugColors.set(current, row * 4); continue; }

    let fourCosts;
    if (bitmapFree) {
      // A candidate's three multicolor colors plus paper form a four-color
      // wide palette. Hires ink and the hires sprite are symmetric here. Cache
      // their joint optimum once for each unordered four-color palette.
      fourCosts = new Float64Array(16 * quadruples.length * 3).fill(Infinity);
      for (let hires = 0; hires < 16; hires += 1) {
        for (let ink = hires; ink < 16; ink += 1) {
          const offset = (hires * 16 + ink) * 16 * 24;
          for (let q = 0; q < quadruples.length; q += 1) {
            const [a, b, c, d] = quadruples[q].map(color => offset + color * 24);
            for (let tile = 0; tile < 3; tile += 1) {
              const h = (hires * quadruples.length + q) * 3 + tile;
              const i = (ink * quadruples.length + q) * 3 + tile;
              if (fourCosts[h] === 0 && fourCosts[i] === 0) continue;
              let cost = 0;
              for (let dy = 0; dy < 2; dy += 1) {
                for (let p = 0; p < 4; p += 1) {
                  const pair = dy * 12 + tile * 4 + p;
                  cost += min(edgeCosts[a + pair], edgeCosts[b + pair], edgeCosts[c + pair], edgeCosts[d + pair]);
                }
              }
              fourCosts[h] = min(fourCosts[h], cost);
              fourCosts[i] = min(fourCosts[i], cost);
            }
          }
        }
      }
    }
    let chosen = current;
    // Search all color combinations reachable with the available writes,
    // trying fewer changes first so equal-quality solutions preserve slots.
    for (let writes = 1; writes <= available && best > 0; writes += 1) {
      for (const triple of triples) {
        const missing = triple.colors.filter(color => !current.slice(1).includes(color));
        if (missing.length > writes) continue;
        const colors = [current[0], ...current.slice(1)];
        let next = 0;
        for (let slot = 1; slot < 4; slot += 1) {
          if (!(triple.mask & (1 << colors[slot]))) colors[slot] = missing[next++];
        }
        for (let hires = 0; hires < 16; hires += 1) {
          if (missing.length + Number(hires !== current[0]) !== writes) continue;
          colors[0] = hires;
          let cost = 0;
          for (let tile = 0; tile < 3; tile += 1) {
            if (bitmapFree) {
              let tileCost = Infinity;
              for (let paper = 0; paper < 16; paper += 1) {
                if (triple.mask & (1 << paper)) continue;
                const q = quadrupleIndex[triple.mask | (1 << paper)];
                tileCost = min(tileCost, fourCosts[(hires * quadruples.length + q) * 3 + tile]);
              }
              cost += tileCost;
            } else cost += edgeCost(colors, 15, 15, tile);
            if (cost >= best) break;
          }
          if (cost < best) { best = cost; chosen = [...colors]; }
        }
      }
    }
    if (row > 0) {
      let write = 0;
      for (let slot = 0; slot < 4; slot += 1) {
        if (chosen[slot] !== current[slot]) registerUpdates[row * 6 + free[write++]] = commands[slot] | chosen[slot];
      }
    }
    current = chosen;
    bugColors.set(current, row * 4);
  }

  const bitmap = new Uint8Array(8000);
  const spriteBits = new Uint8Array(3600);
  const bugHiresBits = new Uint8Array(600);
  const bugMulticolorBits = new Uint8Array(600);
  const pixels = new ImageData(320, 200);
  function putPixel(x, y, color, ink) {
    const p = (y * 320 + x) * 4;
    pixels.data.set(palette[color].rgb, p);
    pixels.data[p + 3] = 255;
    if (ink) bitmap[((y >> 3) * 40 + (x >> 3)) * 8 + (y & 7)] |= 128 >> (x & 7);
  }
  function bugPair(x, y, ink, paper, emit) {
    const colors = bugColors.subarray((y >> 1) * 4, (y >> 1) * 4 + 4);
    const a = targets[y * 320 + x] * 16;
    const b = targets[y * 320 + x + 1] * 16;
    let best = Infinity;
    let chosen = 0;
    for (let slot = 0; slot < 4; slot += 1) {
      const base = slot === 0 ? paper : colors[slot];
      const cost = min(errors[a + ink], errors[a + colors[0]], errors[a + base]) +
        min(errors[b + ink], errors[b + colors[0]], errors[b + base]);
      if (cost < best) { best = cost; chosen = slot; }
    }
    if (emit) {
      const base = chosen === 0 ? paper : colors[chosen];
      bugMulticolorBits[y * 3 + (x >> 3)] |= chosen << (6 - (x & 7));
      for (let dx = 0; dx < 2; dx += 1) {
        const t = dx === 0 ? a : b;
        const inkOn = errors[t + ink] <= min(errors[t + colors[0]], errors[t + base]);
        const hiresOn = !inkOn && errors[t + colors[0]] < errors[t + base];
        if (hiresOn) bugHiresBits[y * 3 + ((x + dx) >> 3)] |= 128 >> ((x + dx) & 7);
        putPixel(x + dx, y, inkOn ? ink : hiresOn ? colors[0] : base, inkOn);
      }
    }
    return best;
  }
  for (let y = 0; y < 200; y += 2) {
    for (let column = 0; column < 3; column += 1) {
      let chosen = 255;
      if ((y & 7) === 0) {
        let best = Infinity;
        for (let colors = 0; colors < 256; colors += 1) {
          let cost = 0;
          for (let dy = 0; dy < 2; dy += 1) {
            for (let x = column * 8; x < column * 8 + 8; x += 2) cost += bugPair(x, y + dy, colors >> 4, colors & 15, false);
          }
          if (cost < best) { best = cost; chosen = colors; }
        }
      }
      screenColors[y / 2 * 40 + column] = chosen;
    }
  }
  for (let y = 0; y < 200; y += 1) {
    for (let x = 0; x < 320; x += 2) {
      const colors = screenColors[(y >> 1) * 40 + (x >> 3)];
      const ink = colors >> 4;
      const paper = colors & 15;
      if (x < 24) { bugPair(x, y, ink, paper, true); continue; }
      const a = targets[y * 320 + x] * 16;
      const b = targets[y * 320 + x + 1] * 16;
      const sprite = x >= 312 ? paper : spriteAt(x, y);
      const paperCost = min(errors[a + ink], errors[a + paper]) + min(errors[b + ink], errors[b + paper]);
      const spriteCost = min(errors[a + ink], errors[a + sprite]) + min(errors[b + ink], errors[b + sprite]);
      const useSprite = x < 312 && spriteCost < paperCost;
      const base = useSprite ? sprite : paper;
      if (useSprite) {
        const bit = (x - 24) >> 1;
        spriteBits[y * 18 + (bit >> 3)] |= 128 >> (bit & 7);
      }
      for (let dx = 0; dx < 2; dx += 1) {
        const t = dx === 0 ? a : b;
        const inkOn = errors[t + ink] < errors[t + base];
        putPixel(x + dx, y, inkOn ? ink : base, inkOn);
      }
    }
  }
  return { pixels, bitmap, screenColors, spriteBits, bugHiresBits, bugMulticolorBits,
    underlayColors, bugColors, registerUpdates };
}
