'use strict';

// Ramp-run codec study on the universal font: per frame, first greedy
// geometric ramp-lines, then the screen-order literal codec for the rest.
// Compares against the pure literal codec on the same screens.
const fs = require('node:fs');
const path = require('node:path');
const {buildFont, toBytes, DIRS} = require('./font.cjs');

const HERE = __dirname;
const CORPORA_ROOT = process.env.UNIVERSAL_CORPORA_ROOT || path.join(HERE, '../build');
const SLOPE_SHIFT = 4;
const pop = Uint8Array.from({length: 256}, (_, v) => { let c = 0; for (; v; v &= v - 1) c++; return c; });

const contentRows = JSON.parse(fs.readFileSync(path.join(HERE, 'build/content-rows-stride3.json'), 'utf8'));
const {rows: fontRows, slotMap} = buildFont({d12Stride: 3, contentRows});
const fontBytes = toBytes({rows: fontRows});
const bitmapOf = fontRows;

function loadCorpus(dirName, frames) {
  const dir = path.join(CORPORA_ROOT, dirName);
  const idealPath = path.join(dir, 'ideal.frames');
  const hasIdeal = fs.existsSync(idealPath);
  const ideal = hasIdeal ? fs.readFileSync(idealPath) : null;
  const ref = fs.readFileSync(path.join(dir, 'reference.frames'));
  const curFont = fs.readFileSync(path.join(dir, 'font.bin'));
  const stride = 1000;
  const target = [];
  for (let f = 0; f < frames; f++) {
    const codes = new Array(stride);
    for (let i = 0; i < stride; i++) {
      if (hasIdeal) {
        const base = (f * stride + i) * 8;
        const key = Array.from(ideal.subarray(base, base + 8)).join(',');
        const code = fontRows.findIndex(rows => rows.join(',') === key);
        codes[i] = code >= 0 ? code : nearestCode(rows0(base, ideal));
      } else {
        const base = ref[f * stride + i] * 8;
        const key = Array.from(curFont.subarray(base, base + 8)).join(',');
        const code = fontRows.findIndex(rows => rows.join(',') === key);
        codes[i] = code >= 0 ? code : nearestCode(rows0(base, curFont));
      }
    }
    target.push(codes);
  }
  return {target, stride, hasIdeal, ideal};
}
function rows0(base, buf) {
  const r = new Array(8);
  for (let k = 0; k < 8; k++) r[k] = buf[base + k];
  return r;
}
function nearestCode(rows) {
  let best = 0, bestE = 64;
  for (let c = 0; c < 256; c++) {
    let e = 0;
    for (let r = 0; r < 8; r++) e += pop[fontBytes[c * 8 + r] ^ rows[r]];
    if (e < bestE) { bestE = e; best = c; if (e === 0) break; }
  }
  return best;
}

function literalRuns(prev, target) {
  let bytes = 0, runs = 0;
  let skip = -1, len = 0;
  for (let i = 0; i <= 1000; i++) {
    const changedHere = i < 1000 && prev[i] !== target[i];
    if (changedHere) {
      if (len === 0) skip = i;
      len++;
    } else if (len > 0) {
      while (len > 0) {
        const part = Math.min(len, 255);
        bytes += 2 + part;
        runs++;
        len -= part;
        if (len > 0) skip = 0;
      }
    }
  }
  return {bytes, runs};
}

function encodeFrame(prev, target, pctLine) {
  const stride = 1000;
  const scr = prev.slice();
  // ROI
  const roi = new Uint8Array(stride);
  for (let i = 0; i < stride; i++) {
    if (scr[i] !== target[i]) {
      const x = i % 40, y = (i / 40) | 0;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        const xx = x + dx, yy = y + dy;
        if (xx >= 0 && xx < 40 && yy >= 0 && yy < 25) roi[yy * 40 + xx] = 1;
      }
    }
  }
  // per-cell best chain step (chain must have the tile within tolerance)
  const fitAt = new Map();
  for (const chain of slotMap.chains) {
    const bitmaps = chain.bitmaps;
    for (let i = 0; i < stride; i++) {
      if (!roi[i]) continue;
      const t0 = bitmapOf[target[i]];
      let bestE = pctLine > 0 ? 6 : 2, bestS = -1;
      for (let s = 0; s < bitmaps.length; s++) {
        let e = 0;
        for (let r = 0; r < 8; r++) e += pop[bitmaps[s][r] ^ t0[r]];
        if (e < bestE) { bestE = e; bestS = s; if (e === 0) break; }
      }
      if (bestS >= 0) {
        if (!fitAt.has(i)) fitAt.set(i, []);
        fitAt.get(i).push({chain, step: bestS, err: bestE});
      }
    }
  }
  const candidates = [];
  for (const [start, infos] of fitAt) {
    const sx = start % 40, sy = (start / 40) | 0;
    for (const info0 of infos) {
      if (info0.chain.dir < 0) continue;
      const [dx, dy] = DIRS[info0.chain.dir];
      const cells = [], steps = [];
      let gaps = 0;
      for (let i = 0; i < 48; i++) {
        const x = sx + dx * i, y = sy + dy * i;
        if (x < 0 || x >= 40 || y < 0 || y >= 25) break;
        const at = y * 40 + x;
        const fi = fitAt.get(at)?.find(f2 => f2.chain === info0.chain);
        if (!fi) {
          if (++gaps > 1) break;
          cells.push(at); steps.push(null);
          continue;
        }
        gaps = 0; cells.push(at); steps.push(fi.step);
      }
      while (cells.length && steps[0] === null) { cells.shift(); steps.shift(); }
      while (cells.length && steps[steps.length - 1] === null) { cells.pop(); steps.pop(); }
      const fitted = steps.filter(s => s !== null);
      if (cells.length < 4 || fitted.length < cells.length * 0.8) continue;
      const sA = fitted[0], sB = fitted[fitted.length - 1], len = cells.length;
      const slope = Math.round((sB - sA) * (1 << SLOPE_SHIFT) / (len - 1));
      const n = info0.chain.bitmaps.length;
      let err = 0, gain = 0, saves = 0;
      for (let i = 0; i < len; i++) {
        const s = Math.max(0, Math.min(n - 1, sA + ((slope * i) >> SLOPE_SHIFT)));
        const g = info0.chain.bitmaps[s], t0 = bitmapOf[target[cells[i]]];
        let e = 0;
        for (let r = 0; r < 8; r++) e += pop[g[r] ^ t0[r]];
        err += e;
        for (let r = 0; r < 8; r++) gain += t0[r];
        if (scr[cells[i]] !== g) saves++;
      }
      const budget = Math.max(2, Math.round(pctLine * gain));
      if (err > budget) continue;
      const value = saves * 2 - 5;
      if (value >= 4) candidates.push({info0, cells, sA, slope, err, value, gain});
    }
  }
  candidates.sort((a, b) => b.value - a.value);
  const used = new Uint8Array(stride);
  let lineBytes = 0, lines = 0, lineCells = 0, frameErr = 0;
  for (const cand of candidates) {
    let overlap = 0;
    for (const at of cand.cells) if (used[at]) overlap++;
    if (overlap > cand.cells.length * 0.2) continue;
    const n = cand.info0.chain.bitmaps.length;
    for (let i = 0; i < cand.cells.length; i++) {
      const at = cand.cells[i];
      used[at] = 1;
      scr[at] = cand.info0.chain.base + Math.max(0, Math.min(n - 1, cand.sA + ((cand.slope * i) >> SLOPE_SHIFT)));
    }
    lineBytes += 5; lines++; lineCells += cand.cells.length;
    frameErr += cand.err;
  }
  const lit = literalRuns(scr, target);
  // apply literal runs to reach target
  for (let i = 0; i < stride; i++) scr[i] = target[i];
  return {bytes: lineBytes + lit.bytes, lineBytes, litBytes: lit.bytes, lines, lineCells, runs: lit.runs, frameErr, scr};
}

function pureLiteralBytes(target0) {
  let total = 0;
  for (let f = 1; f < target0.length; f++) total += literalRuns(target0[f - 1], target0[f]).bytes;
  return total;
}

const CORPORA = [
  ['solid-star', 'three-scene-solid-star/characters', 161],
  ['tumbling-star', 'three-scene-tumbling-star/characters', 161],
  ['glass-star', 'three-scene-glass-star/characters', 161],
  ['glass-diamond', 'three-scene-glass-diamond/characters', 161],
];
for (const [name, dirName, frames] of CORPORA) {
  const corpus = loadCorpus(dirName, frames);
  const litOnly = pureLiteralBytes(corpus.target);
  for (const pct of [0, 0.05]) {
    let totBytes = 0, totLit = 0, totLineB = 0, lines = 0, runs = 0, err = 0, lineCells = 0;
    const screens = [corpus.target[0].map(() => 0)]; // frame 0 drawn from blank? use target[0] as base state
    screens[0] = corpus.target[0].slice();
    for (let f = 1; f < frames; f++) {
      const r = encodeFrame(screens[f - 1], corpus.target[f], pct);
      totBytes += r.bytes; totLit += r.litBytes; totLineB += r.lineBytes;
      lines += r.lines; runs += r.runs; err += r.frameErr; lineCells += r.lineCells;
      screens.push(r.scr);
    }
    const n = frames - 1;
    console.log(`${name.padEnd(16)} budget ${Math.round(pct * 100)}%: lines+literal ${(totBytes / n).toFixed(1)} B/f vs pure literal ${(litOnly / n).toFixed(1)} B/f (${(100 * (1 - totBytes / litOnly)).toFixed(0)}%)`);
    console.log(`${' '.repeat(16)} lines ${(lines / n).toFixed(1)}/f (mean ${(lines ? lineCells / lines : 0).toFixed(1)} cells, ${(totLineB / n).toFixed(1)} B/f), literal runs ${(runs / n).toFixed(1)}/f (${(totLit / n).toFixed(1)} B/f), err ${(err / n).toFixed(1)} px/f`);
  }
}
