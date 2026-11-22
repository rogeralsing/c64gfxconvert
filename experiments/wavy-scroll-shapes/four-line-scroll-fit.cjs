"use strict";

const width = 160;
const height = 200;
const cellWidth = 4;
const cellHeight = 8;
const halfHeight = 4;
const cellsAcross = width / cellWidth;
const rowBytes = 1000;
const fixedBlack = 0xff00;
const silhouettePenalty = 4;
// One actual error outranks an entire cell's worth of owner tie-breaks.
const errorScale = 128;

function createDistance(columns, rows, activeRows, rowColors) {
  const stride = columns + 1;
  const period = rowBytes + 1 - columns;
  const lastWindow = rows - activeRows;
  const distances = new Map();
  function owner(reference) {
    if (reference >= fixedBlack) return { row: 0, column: 0, first: 0, last: lastWindow, color: reference & 15 };
    const row = Math.floor(reference / stride);
    return { row, column: reference % stride, first: Math.max(0, row - activeRows + 1), last: Math.min(row, lastWindow) };
  }
  return function distance(from, to) {
    if (from === to) return 0;
    // Preserve the original silhouette when using a single window.
    if (to === fixedBlack && lastWindow === 0) return Infinity;
    const key = Math.min(from, to) * 65536 + Math.max(from, to);
    const saved = distances.get(key);
    if (saved !== undefined) return saved;
    const source = owner(from);
    const mapped = owner(to);
    // Rows can share an owner if their active windows coincide. Black is
    // safe when a crowded cell cannot cover all active wave rows.
    if (lastWindow > 0 && to !== fixedBlack && (source.first !== mapped.first || source.last !== mapped.last)) {
      distances.set(key, Infinity);
      return Infinity;
    }

    let errors = 0;
    if (rowColors) {
      for (let window = source.first; window <= source.last; window++) {
        const sourceBase = (source.row - window) * rowBytes;
        const mappedBase = (mapped.row - window) * rowBytes;
        for (let offset = 0; offset < period; offset++) {
          const wanted = source.color ?? rowColors[sourceBase + (offset + source.column) % period];
          const actual = mapped.color ?? rowColors[mappedBase + (offset + mapped.column) % period];
          if (wanted !== actual) errors += wanted && actual ? 1 : silhouettePenalty;
        }
      }
    } else {
      errors = 1;
    }
    const sameColumn = from < fixedBlack && to < fixedBlack && from % stride === to % stride;
    const result = errors * errorScale + (sameColumn ? 1 : 2);
    distances.set(key, result);
    return result;
  };
}

function bestHalf(histogram, shared, distance) {
  const candidates = [...histogram.keys()].filter((reference) => reference !== shared).sort((a, b) => a - b);
  const targets = [...histogram].map(([reference, count]) => ({
    count,
    base: Math.min(distance(reference, shared), distance(reference, fixedBlack)),
    local: candidates.map((candidate) => distance(reference, candidate)),
  }));
  if (candidates.length < 2) {
    const score = targets.reduce((sum, { count, base, local }) => sum + count * Math.min(base, local[0] ?? Infinity), 0);
    return { score, references: candidates };
  }
  let best = { score: Infinity, references: [] };
  for (let first = 0; first < candidates.length - 1; first++) {
    for (let second = first + 1; second < candidates.length; second++) {
      let score = 0;
      for (const { count, base, local } of targets) score += count * Math.min(base, local[first], local[second]);
      if (score < best.score) best = { score, references: [candidates[first], candidates[second]] };
    }
  }
  return best;
}

function mapHalf(histogram, references, shared, distance) {
  const owners = [fixedBlack, ...references, shared];
  const mapping = new Map();
  for (const target of histogram.keys()) {
    let bestDistance = Infinity;
    let bestOwner = fixedBlack;
    for (const owner of owners) {
      const cost = distance(target, owner);
      if (cost < bestDistance) {
        bestDistance = cost;
        bestOwner = owner;
      }
    }
    mapping.set(target, bestOwner);
  }
  const used = new Set(mapping.values());
  return { mapping, local: references.filter((reference) => used.has(reference)), shared: used.has(shared) };
}

function chooseCell(histograms, distance) {
  const sharedCandidates = new Set([fixedBlack, ...histograms[0].keys(), ...histograms[1].keys()]);
  let best = { score: Infinity, shared: fixedBlack, halves: null };
  for (const shared of sharedCandidates) {
    const halves = histograms.map((histogram) => bestHalf(histogram, shared, distance));
    const score = halves[0].score + halves[1].score;
    if (score < best.score || (score === best.score && best.shared === fixedBlack)) {
      best = { score, shared, halves };
    }
  }
  const halves = best.halves.map(({ references }, half) => mapHalf(histograms[half], references, best.shared, distance));
  const shared = halves.some((half) => half.shared) ? best.shared : fixedBlack;
  return { halves, shared };
}

function matchLocalSlots(top, bottom) {
  const localTop = [top[0] ?? fixedBlack, top[1] ?? fixedBlack];
  const localBottom = [bottom[0] ?? fixedBlack, bottom[1] ?? fixedBlack];
  const changed = (upper, lower) => Number(upper !== fixedBlack && lower !== fixedBlack && upper !== lower);
  const inOrder = changed(localTop[0], localBottom[0]) + changed(localTop[1], localBottom[1]);
  const reversed = changed(localTop[0], localBottom[1]) + changed(localTop[1], localBottom[0]);
  if (reversed < inOrder) localBottom.reverse();
  return [localTop, localBottom];
}

function fitScrollBitmap(targets, { columns, rows, rowColors, splits, activeRows = rows }) {
  if (targets.length !== width * height) throw new Error("Expected a 160 × 200 scrolling target.");
  if (rowColors && (rowColors.length !== activeRows * rowBytes || rowColors.some((color) => color > 15))) {
    throw new Error(`Expected ${activeRows} rows of ${rowBytes} C64 palette indices.`);
  }
  const distance = createDistance(columns, rows, activeRows, rowColors);
  const cellCount = cellsAcross * height / cellHeight;
  const bitmap = new Uint8Array(cellCount * cellHeight);
  const owners = Buffer.alloc(cellCount * 10);
  for (let cell = 0; cell < cellCount; cell++) {
    const left = (cell % cellsAcross) * cellWidth;
    const cellRow = Math.floor(cell / cellsAcross);
    const top = cellRow * cellHeight;
    const split = (splits?.[cellRow] ?? halfHeight) || cellHeight;
    const histograms = [new Map(), new Map()];
    for (let y = 0; y < cellHeight; y++) {
      const histogram = histograms[Number(y >= split)];
      for (let x = 0; x < cellWidth; x++) {
        const target = targets[(top + y) * width + left + x];
        if (target !== fixedBlack) histogram.set(target, (histogram.get(target) ?? 0) + 1);
      }
    }
    const { halves, shared } = chooseCell(histograms, distance);
    const locals = matchLocalSlots(halves[0].local, halves[1].local);
    const displayed = locals.map(([first, second]) => [fixedBlack, first, second, shared]);
    for (let y = 0; y < cellHeight; y++) {
      const half = Number(y >= split);
      let packed = 0;
      for (let x = 0; x < cellWidth; x++) {
        const target = targets[(top + y) * width + left + x];
        const owner = halves[half].mapping.get(target) ?? fixedBlack;
        packed = (packed << 2) | displayed[half].indexOf(owner);
      }
      bitmap[cell * cellHeight + y] = packed;
    }
    // An unused upper slot can carry the lower color without a late fetch.
    const references = [locals[0][0] === fixedBlack ? locals[1][0] : locals[0][0],
      locals[0][1] === fixedBlack ? locals[1][1] : locals[0][1], ...locals[1], shared];
    for (const [slot, reference] of references.entries()) owners.writeUInt16LE(reference, cell * 10 + slot * 2);
  }
  return { bitmap, owners };
}

module.exports = { fitScrollBitmap };
