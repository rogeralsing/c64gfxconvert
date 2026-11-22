"use strict";

const fixedBlack = 0xff00;

// Color RAM only stores the low nibble. Phase B's screen bytes are ready
// before its Color RAM writer runs, even as the next A lookup is decoded.
function stageColorLookups({ top, bottom, spareLow }, refsToStage, lookupWidth) {
  const refs = new Set(refsToStage);
  const sources = new Map();
  const spare = [];
  const byRow = new Map();
  const rowFor = (ref) => Math.floor(ref / lookupWidth);

  for (const [writes, unused, address] of [
    [top, spareLow.top, "screenTopB"],
    [bottom, spareLow.bottom, "screenBottomB"],
  ]) {
    const pairsAt = new Map();
    for (const [pair, cells] of writes) {
      const low = pair & 0xffff;
      if (refs.has(low) && !sources.has(low)) sources.set(low, { address, cell: cells[0] });
      for (const cell of cells) pairsAt.set(cell, pair);
    }

    for (const cell of unused) {
      const pair = pairsAt.get(cell);
      const slot = { address, cell, writes, pair };
      if (pair === undefined) {
        spare.push(slot);
        continue;
      }

      const high = pair >>> 16;
      if (high >= fixedBlack || (pair & 0xffff) !== fixedBlack) continue;
      const row = rowFor(high);
      if (!byRow.has(row)) byRow.set(row, []);
      byRow.get(row).push(slot);
    }
  }

  // Prefer destinations where ORA extends an existing single-store group.
  // Moving a store out of a shared group can require repeating its LDA.
  for (const slots of byRow.values()) {
    slots.sort((left, right) => right.writes.get(right.pair).length - left.writes.get(left.pair).length);
  }

  for (const ref of refs) {
    if (sources.has(ref)) continue;
    const slot = byRow.get(rowFor(ref))?.pop() ?? spare.pop();
    if (!slot) continue;
    const { address, cell, writes, pair } = slot;
    const high = pair === undefined ? fixedBlack : pair >>> 16;

    if (pair !== undefined) {
      const cells = writes.get(pair);
      cells.splice(cells.indexOf(cell), 1);
      if (!cells.length) writes.delete(pair);
    }

    const stagedPair = high * 0x10000 + ref;
    if (!writes.has(stagedPair)) writes.set(stagedPair, []);
    writes.get(stagedPair).push(cell);
    sources.set(ref, { address, cell });
  }
  return sources;
}

module.exports = { stageColorLookups };
