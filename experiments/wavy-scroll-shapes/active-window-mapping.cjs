"use strict";

const { instructionCycles } = require("./pack-four-line-raster.cjs");

const fixedBlack = 0xff00;

function activeIntervals(refs, { width, activeRows }, lastStart) {
  const intervals = [];
  for (const ref of refs) {
    if (ref === undefined || ref === fixedBlack) continue;
    if (ref > fixedBlack) return [[0, lastStart]];
    const row = Math.floor(ref / width);
    intervals.push([Math.max(0, row - activeRows + 1), Math.min(row, lastStart)]);
  }
  intervals.sort(([first], [second]) => first - second);

  const merged = [];
  for (const [first, last] of intervals) {
    const previous = merged.at(-1);
    if (previous && first <= previous[1] + 1) previous[1] = Math.max(previous[1], last);
    else merged.push([first, last]);
  }
  return merged;
}

function renderFringe(lower, middle, upper, lastStart) {
  lower.sort((a, b) => a.intervals[0][1] - b.intervals[0][1]);
  upper.sort((a, b) => a.intervals[0][0] - b.intervals[0][0]);
  const code = [];

  if (lower.length) {
    // X is the smaller start. Enter at the first prefix that still overlaps it.
    code.push("lda !windowLowerLo+,x", "sta !windowLowerJump+ + 1",
      "lda !windowLowerHi+,x", "sta !windowLowerJump+ + 2", "!windowLowerJump:", "jmp $ffff");
    for (const { intervals: [[, last]], lines } of lower) {
      code.push(`!windowLower${last}:`, ...lines);
    }
    code.push("!windowMiddle:");
  }

  for (const { intervals, lines } of middle) {
    if (intervals.length === 1 && intervals[0][0] === 0 && intervals[0][1] === lastStart) {
      code.push(...lines);
      continue;
    }
    // With shorter windows, an interior bin can require both endpoints.
    for (const [first, last] of intervals) {
      code.push(`cpx #${last + 1}`, "bcs !windowNextInterval+",
        `cpy #${first}`, "bcs !windowWrite+", "!windowNextInterval:");
    }
    code.push("jmp !windowSkip+", "!windowWrite:", ...lines, "!windowSkip:");
  }

  // Y is the larger start. Once it misses a suffix, it misses all later ones.
  for (const { intervals: [[first]], lines } of upper) {
    code.push(`cpy #${first}`, "bcs !windowUpper+", "rts", "!windowUpper:", ...lines);
  }
  code.push("rts");

  if (lower.length) {
    const targets = Array.from({ length: lastStart + 1 }, (_, start) => {
      const bin = lower.find(({ intervals: [[, last]] }) => start <= last);
      return bin ? `!windowLower${bin.intervals[0][1]}-` : "!windowMiddle-";
    });
    code.push("!windowLowerLo:", `.byte ${targets.map((target) => `<(${target})`).join(", ")}`,
      "!windowLowerHi:", `.byte ${targets.map((target) => `>(${target})`).join(", ")}`);
  }
  return code;
}

function maxFringeCycles(lower, middle, upper, lastStart) {
  // Two indexed loads can cross a page during the lower jump. An upper
  // branch can also cross a page. Interior guards can fall through to JMP.
  const entryAndReturn = (lower.length ? 21 : 0) + 6;
  const middleGuards = middle.reduce((total, { intervals }) => {
    const always = intervals.length === 1 && intervals[0][0] === 0 && intervals[0][1] === lastStart;
    return total + (always ? 0 : intervals.length * 10 + 3);
  }, 0);

  let worst = 0;
  for (let first = 0; first <= lastStart; first++) {
    // An adjacent transition includes the work for either start on its own.
    const last = Math.min(first + 1, lastStart);
    const active = ({ intervals }) => intervals.some(([lo, hi]) => lo <= last && hi >= first);
    const upperActive = upper.filter(active).length;
    const upperGuards = upperActive * 6 + (upperActive < upper.length ? 4 : 0);
    const payload = [...lower, ...middle, ...upper].reduce((total, bin) =>
      total + (active(bin) ? bin.cycles : 0), 0);
    worst = Math.max(worst, entryAndReturn + middleGuards + upperGuards + payload);
  }
  return worst;
}

// X and Y contain the smaller and larger of the previous and next window starts.
// Their union includes old destinations that must be overwritten with black.
function emitWindowWrites(cellsByValue, address, load, window, { commonRaster, alternateOwners }) {
  const lastStart = window.rows - window.activeRows;
  const bins = new Map();

  for (const [value, destinations] of cellsByValue) {
    const refs = address === "colorRam" ? [value] : [value >>> 16, value & 0xffff];
    const writeGroups = new Map();
    for (const cell of destinations) {
      const intervals = activeIntervals([...refs, alternateOwners?.get(cell)], window, lastStart);
      if (!intervals.length) continue;
      const key = intervals.toString();
      if (!bins.has(key)) bins.set(key, { intervals, lines: [] });
      if (!writeGroups.has(key)) writeGroups.set(key, []);
      writeGroups.get(key).push(cell);
    }
    for (const [key, group] of writeGroups) {
      bins.get(key).lines.push(...load(value, group), ...group.map((cell) => `sta ${address} + ${cell}`));
    }
  }

  const common = [];
  const lower = [];
  const middle = [];
  const upper = [];
  const cyclesByStart = Array(lastStart + 1).fill(0);
  const storesByStart = Array(lastStart + 1).fill(0);
  for (const bin of bins.values()) {
    const { intervals, lines } = bin;
    const cycles = lines.reduce((sum, line) => sum + instructionCycles(line), 0);
    bin.cycles = cycles;
    const stores = lines.filter((line) => line.startsWith("sta ")).length;
    const [[first, last]] = intervals;
    // At top speed spare raster slots also take a few bins just outside
    // the common range. A bin outside the active window writes black.
    const packedBoundary = commonRaster && window.packBoundary && intervals.length === 1
      && ((first === 0 && last >= lastStart - window.packBoundary.prefix)
        || (first <= window.packBoundary.suffix && last === lastStart));
    for (const [first, last] of packedBoundary ? [[0, lastStart]] : intervals) {
      for (let start = first; start <= last; start++) {
        cyclesByStart[start] += cycles;
        storesByStart[start] += stores;
      }
    }
    if (intervals.length !== 1) middle.push(bin);
    else if (packedBoundary) common.push(...lines);
    else if (first === 0 && last === lastStart) {
      if (commonRaster) common.push(...lines);
      else middle.unshift(bin);
    } else if (first === 0) lower.push(bin);
    else if (last === lastStart) upper.push(bin);
    else middle.push(bin);
  }

  return {
    common,
    fringe: renderFringe(lower, middle, upper, lastStart),
    cyclesByStart,
    storesByStart,
    worstCaseCycles: maxFringeCycles(lower, middle, upper, lastStart),
  };
}

module.exports = { emitWindowWrites };
