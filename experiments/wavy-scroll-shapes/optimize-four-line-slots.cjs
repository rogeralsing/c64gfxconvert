"use strict";

const cellsAcross = 40;
const cellHeight = 8;
const halfHeight = 4;
const ownerCount = 5;
const ownerBytes = ownerCount * 2;
const fixedBlack = 0xff00;

function ownerSlot(code, half) {
  return code === 3 ? 4 : half * 2 + code - 1;
}

function pixelCode(slots, half, owner) {
  if (owner === slots[4]) return 3;
  return owner === slots[half * 2] ? 1 : 2;
}

function readCell(bitmap, owners, index, split) {
  const original = Array.from({ length: ownerCount }, (_, slot) =>
    owners.readUInt16LE(index * ownerBytes + 2 * slot));
  const slots = Array(ownerCount).fill(fixedBlack);
  const halves = [new Set(), new Set()];
  for (let y = 0; y < cellHeight; y++) {
    const half = Number(y >= split);
    const byte = bitmap[index * cellHeight + y];
    for (let shift = 0; shift < 8; shift += 2) {
      const code = (byte >> shift) & 3;
      if (code === 0) continue;
      const slot = ownerSlot(code, half);
      slots[slot] = original[slot];
      halves[half].add(original[slot]);
    }
  }
  const late = (slots[2] !== fixedBlack && original[0] !== original[2])
    || (slots[3] !== fixedBlack && original[1] !== original[3]);
  return { original, slots, halves, late, split, neighbors: [] };
}

function needsLateFetch([upperHigh, upperLow, lowerHigh, lowerLow]) {
  const changed = (upper, lower) => upper !== fixedBlack && lower !== fixedBlack && upper !== lower;
  return changed(upperHigh, lowerHigh) || changed(upperLow, lowerLow);
}

function orientations(owners) {
  if (owners.length === 0) return [[fixedBlack, fixedBlack]];
  const [high, low = fixedBlack] = owners;
  return [[high, low], [low, high]];
}

function assignments([upper, lower]) {
  const sharedOwners = [...new Set([fixedBlack, ...upper, ...lower])];
  const common = [...upper].filter((owner) => lower.has(owner));
  const options = [];
  for (const shared of sharedOwners) {
    const top = [...upper].filter((owner) => owner !== shared).sort((a, b) => a - b);
    const bottom = [...lower].filter((owner) => owner !== shared).sort((a, b) => a - b);
    if (top.length > 2 || bottom.length > 2) continue;
    for (const up of orientations(top)) {
      for (const down of orientations(bottom)) {
        const slots = [...up, ...down, shared];
        if (common.every((owner) => pixelCode(slots, 0, owner) === pixelCode(slots, 1, owner))) {
          options.push(slots);
        }
      }
    }
  }
  return options;
}

function connect(cells, from, fromHalf, to, toHalf) {
  for (const owner of cells[from].halves[fromHalf]) {
    if (!cells[to].halves[toHalf].has(owner)) continue;
    cells[from].neighbors.push({ index: to, local: fromHalf, remote: toHalf, owner });
    cells[to].neighbors.push({ index: from, local: toHalf, remote: fromHalf, owner });
  }
}

function slotChanges(cells, cell, slots) {
  let changes = 0;
  for (const { index, local, remote, owner } of cell.neighbors) {
    if (pixelCode(slots, local, owner) !== pixelCode(cells[index].slots, remote, owner)) changes++;
  }
  return changes;
}

function screenPair(high, low) {
  return high === fixedBlack && low === fixedBlack ? null : high * 65536 + low;
}

function writesFor([upperHigh, upperLow, lowerHigh, lowerLow, shared], split) {
  const high = !split && upperHigh === fixedBlack ? lowerHigh : upperHigh;
  const low = !split && upperLow === fixedBlack ? lowerLow : upperLow;
  return [screenPair(high, low), split ? screenPair(lowerHigh, lowerLow) : null,
    shared === fixedBlack ? null : shared];
}

// Match the grouped LDA, optional ORA and STA emitted by the color generator.
function loadCycles(writer, value) {
  if (writer === 2) return value >= fixedBlack ? 2 : 4;
  const high = Math.floor(value / 65536);
  const low = value % 65536;
  if (high >= fixedBlack && low >= fixedBlack) return 2;
  if (high === fixedBlack || low === fixedBlack) return 4;
  return (high >= fixedBlack ? 2 : 4) + (low >= fixedBlack ? 2 : 4);
}

function updateWriteCounts(counts, writes, delta) {
  for (const [writer, value] of writes.entries()) {
    if (value === null) continue;
    const groups = counts[writer];
    const remaining = (groups.get(value) ?? 0) + delta;
    if (remaining) groups.set(value, remaining);
    else groups.delete(value);
  }
}

function writeCycleDelta(counts, oldWrites, newWrites) {
  const delta = [0, 0, 0];
  for (const [writer, oldValue] of oldWrites.entries()) {
    const newValue = newWrites[writer];
    if (oldValue === newValue) continue;
    const groups = counts[writer];
    if (oldValue !== null) delta[writer] -= 4 + (groups.get(oldValue) === 1 ? loadCycles(writer, oldValue) : 0);
    if (newValue !== null) delta[writer] += 4 + (groups.has(newValue) ? 0 : loadCycles(writer, newValue));
  }
  return [delta[0] + delta[1], delta[2]];
}

function writeCell(bitmap, outputBitmap, outputOwners, index, { slots, original, split }) {
  for (let y = 0; y < cellHeight; y++) {
    const half = Number(y >= split);
    const oldByte = bitmap[index * cellHeight + y];
    let packed = 0;
    for (let shift = 0; shift < 8; shift += 2) {
      const code = (oldByte >> shift) & 3;
      if (code === 0) continue;
      const owner = original[ownerSlot(code, half)];
      packed |= pixelCode(slots, half, owner) << shift;
    }
    outputBitmap[index * cellHeight + y] = packed;
  }
  const [upperHigh, upperLow, lowerHigh, lowerLow, shared] = slots;
  // A single matrix can supply the lower slot if that slot is unused above.
  const refs = [upperHigh === fixedBlack ? lowerHigh : upperHigh,
    upperLow === fixedBlack ? lowerLow : upperLow, lowerHigh, lowerLow, shared];
  for (const [slot, owner] of refs.entries()) {
    outputOwners.writeUInt16LE(owner, index * ownerBytes + slot * 2);
  }
}

function optimizeSlots(bitmap, owners, splits) {
  const cellCount = bitmap.length / cellHeight;
  const rows = cellCount / cellsAcross;
  if (!Number.isInteger(rows) || rows === 0 || owners.length !== cellCount * ownerBytes) {
    throw new Error("Invalid bitmap or owner table for slot optimization.");
  }
  const cells = Array.from({ length: cellCount }, (_, index) => {
    const row = Math.floor(index / cellsAcross);
    const split = (splits?.[row] ?? halfHeight) || cellHeight;
    return readCell(bitmap, owners, index, split);
  });
  const lateCounts = new Uint8Array(rows);
  for (const [index, cell] of cells.entries()) {
    if (cell.late) lateCounts[Math.floor(index / cellsAcross)]++;
    if ((index + 1) % cellsAcross !== 0) {
      connect(cells, index, 0, index + 1, 0);
      connect(cells, index, 1, index + 1, 1);
    }
    if (index + cellsAcross < cellCount) {
      connect(cells, index, Number(cell.split < cellHeight), index + cellsAcross, 0);
    }
  }

  const counts = [new Map(), new Map(), new Map()];
  for (const [index, cell] of cells.entries()) {
    cell.row = Math.floor(index / cellsAcross);
    const split = lateCounts[cell.row] > 0;
    cell.writes = writesFor(cell.slots, split);
    cell.options = assignments(cell.halves)
      .map((slots) => ({ slots, late: needsLateFetch(slots), writes: writesFor(slots, split) }))
      .filter((option) => split || !option.late);
    updateWriteCounts(counts, cell.writes, 1);
  }
  const [topCycles, bottomCycles, colorBudget] = counts.map((groups, writer) =>
    [...groups].reduce((total, [value, stores]) => total + stores * 4 + loadCycles(writer, value), 0));
  const screenBudget = topCycles + bottomCycles;
  let screenCycles = screenBudget;
  let colorCycles = colorBudget;
  const countSlotChanges = () => cells.reduce((total, cell) => total + slotChanges(cells, cell, cell.slots), 0) / 2;
  const before = countSlotChanges();

  // Each move improves the combined score. Keep the screen and vblank
  // writers within their starting cycle counts and keep each late-fetch row.
  let changed;
  do {
    changed = false;
    for (const cell of cells) {
      let best;
      let bestScore = slotChanges(cells, cell, cell.slots);
      for (const option of cell.options) {
        if (cell.late && lateCounts[cell.row] === 1 && !option.late) continue;
        const [screenDelta, colorDelta] = writeCycleDelta(counts, cell.writes, option.writes);
        if (screenCycles + screenDelta > screenBudget || colorCycles + colorDelta > colorBudget) continue;
        const score = slotChanges(cells, cell, option.slots) + screenDelta + colorDelta;
        if (score >= bestScore) continue;
        best = { ...option, screenDelta, colorDelta };
        bestScore = score;
      }
      if (!best) continue;
      updateWriteCounts(counts, cell.writes, -1);
      updateWriteCounts(counts, best.writes, 1);
      screenCycles += best.screenDelta;
      colorCycles += best.colorDelta;
      lateCounts[cell.row] += Number(best.late) - Number(cell.late);
      cell.slots = best.slots;
      cell.late = best.late;
      cell.writes = best.writes;
      changed = true;
    }
  } while (changed);

  const outputBitmap = new Uint8Array(bitmap.length);
  const outputOwners = Buffer.alloc(owners.length);
  for (const [index, cell] of cells.entries()) {
    writeCell(bitmap, outputBitmap, outputOwners, index, cell);
  }
  return {
    bitmap: outputBitmap,
    owners: outputOwners,
    slotChanges: { before, after: countSlotChanges() },
    mappingCycles: { before: screenBudget + colorBudget, after: screenCycles + colorCycles },
  };
}

module.exports = { optimizeSlots };
