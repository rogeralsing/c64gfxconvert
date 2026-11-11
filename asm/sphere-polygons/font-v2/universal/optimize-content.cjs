'use strict';

// One-time content-slot optimizer for the universal drawing font.
// Census: unique ideal tiles across all corpora, equal corpus weighting.
// Greedy: each content slot is the tile whose addition most reduces total
// weighted pixel error of the whole census against the font built so far.
// The drawing sections are locked and never re-chosen.
const fs = require('node:fs');
const path = require('node:path');
const {buildFont, toBytes} = require('./font.cjs');

const HERE = __dirname;
const CORPORA_ROOT = process.env.UNIVERSAL_CORPORA_ROOT || path.join(HERE, '../build');

const CORPORA = [
  ['solid-star', 'three-scene-solid-star/characters', 161],
  ['sphere-to-cube-zoom', 'raw-literal-storage', 250],
  ['gradient-dither-cube', 'three-scene-gradient-c64/characters', 200],
  ['dithered-star', 'three-scene-dithered-star/characters', 241],
  ['tumbling-star', 'three-scene-tumbling-star/characters', 161],
  ['glass-diamond', 'three-scene-glass-diamond/characters', 161],
  ['glass-star', 'three-scene-glass-star/characters', 161],
  ['glass-outline', 'three-scene-glass-outline/characters', 161],
  ['flagship-star', 'three-scene-flagship-star/characters', 97],
];

const pop16 = Uint8Array.from({length: 65536}, (_, v) => {
  let c = 0;
  for (; v; v &= v - 1) c++;
  return c;
});
const wordsOf = rows => [
  (rows[0] << 24 | rows[1] << 16 | rows[2] << 8 | rows[3]) >>> 0,
  (rows[4] << 24 | rows[5] << 16 | rows[6] << 8 | rows[7]) >>> 0,
];
const dist = (a, b) => pop16[(a[0] ^ b[0]) >>> 0 & 0xffff] + pop16[(a[0] ^ b[0]) >>> 16]
  + pop16[(a[1] ^ b[1]) >>> 0 & 0xffff] + pop16[(a[1] ^ b[1]) >>> 16];

function loadCensus() {
  const corpora = [];
  for (const [name, dirName, frames] of CORPORA) {
    const dir = path.join(CORPORA_ROOT, dirName);
    if (!fs.existsSync(path.join(dir, 'reference.frames'))) {
      console.log(`census: skipping ${name} (no corpus at ${dir})`);
      continue;
    }
    const ref = fs.readFileSync(path.join(dir, 'reference.frames'));
    const idealPath = path.join(dir, 'ideal.frames');
    const hasIdeal = fs.existsSync(idealPath);
    const ideal = hasIdeal ? fs.readFileSync(idealPath) : null;
    const curFont = fs.readFileSync(path.join(dir, 'font.bin'));
    const stride = 1000;
    const counts = new Map();
    let total = 0;
    for (let f = 0; f < frames; f++) {
      for (let i = 0; i < stride; i++) {
        const rows = new Array(8);
        if (hasIdeal) {
          const base = (f * stride + i) * 8;
          for (let r = 0; r < 8; r++) rows[r] = ideal[base + r];
        } else {
          const code = ref[f * stride + i] * 8;
          for (let r = 0; r < 8; r++) rows[r] = curFont[code + r];
        }
        const key = rows.join(',');
        counts.set(key, (counts.get(key) ?? 0) + 1);
        total++;
      }
    }
    corpora.push({name, dir, counts, total, hasIdeal});
    console.log(`census: ${name.padEnd(20)} ${counts.size} unique tiles, ${total} cells (${hasIdeal ? 'ideal' : 'film font'})`);
  }
  return corpora;
}

function optimize(corpora, options = {}) {
  const {d12Stride = 3} = options;
  const fixed = buildFont({d12Stride, contentRows: []});
  const fixedWords = fixed.rows.map(wordsOf);
  // merged tiles: key -> {w: [u32,u32], weight: Σ_c count/total_c}
  const tiles = new Map();
  for (const corpus of corpora) {
    for (const [key, count] of corpus.counts) {
      const t = tiles.get(key);
      if (t) t.weight += count / corpus.total;
      else tiles.set(key, {w: wordsOf(key.split(',').map(Number)), weight: count / corpus.total});
    }
  }
  const tileList = [...tiles.entries()].map(([key, t]) => ({key, ...t}));
  console.log(`census: ${tileList.length} unique tiles across ${corpora.length} corpora`);

  const best = new Float64Array(tileList.length);
  for (let i = 0; i < tileList.length; i++) {
    let e = 64;
    for (const fw of fixedWords) {
      const d = dist(tileList[i].w, fw);
      if (d < e) e = d;
    }
    best[i] = e;
  }
  const chosen = [];
  const candidates = tileList.filter((t, i) => best[i] > 0)
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 1200)
    .map(t => t.w);
  for (let slot = 0; slot < fixed.contentSlots && candidates.length; slot++) {
    let bestScore = -1, bestCand = null;
    for (const cand of candidates) {
      let score = 0;
      for (let i = 0; i < tileList.length; i++) {
        const t = tileList[i];
        if (best[i] === 0 || t.weight === 0) continue;
        const gain = best[i] - dist(t.w, cand);
        if (gain > 0) score += gain * t.weight;
      }
      if (score > bestScore) { bestScore = score; bestCand = cand; }
    }
    if (!bestCand || bestScore <= 0) break;
    chosen.push(bestCand);
    for (let i = 0; i < tileList.length; i++) {
      const d = dist(tileList[i].w, bestCand);
      if (d < best[i]) best[i] = d;
    }
  }
  const contentRows = chosen.map(w => [
    (w[0] >>> 24) & 255, (w[0] >>> 16) & 255, (w[0] >>> 8) & 255, w[0] & 255,
    (w[1] >>> 24) & 255, (w[1] >>> 16) & 255, (w[1] >>> 8) & 255, w[1] & 255,
  ]);
  let residual = 0, totalWeight = 0;
  for (let i = 0; i < tileList.length; i++) {
    residual += best[i] * tileList[i].weight;
    totalWeight += tileList[i].weight;
  }
  return {font: buildFont({...options, contentRows}), contentRows, residual, totalWeight};
}

function measure(name, dir, frames, fontRows) {
  const ref = fs.readFileSync(path.join(dir, 'reference.frames'));
  const idealPath = path.join(dir, 'ideal.frames');
  const hasIdeal = fs.existsSync(idealPath);
  const ideal = hasIdeal ? fs.readFileSync(idealPath) : null;
  const curFont = fs.readFileSync(path.join(dir, 'font.bin'));
  const stride = 1000;
  const nearest = new Map();
  let err = 0;
  for (let f = 0; f < frames; f++) {
    for (let i = 0; i < stride; i++) {
      const rows = new Array(8);
      if (hasIdeal) {
        const base = (f * stride + i) * 8;
        for (let r = 0; r < 8; r++) rows[r] = ideal[base + r];
      } else {
        const code = ref[f * stride + i] * 8;
        for (let r = 0; r < 8; r++) rows[r] = curFont[code + r];
      }
      const key = rows.join(',');
      let n = nearest.get(key);
      if (!n) {
        const w = wordsOf(rows);
        let bestE = 64;
        for (const fr of fontRows) {
          const d = dist(w, wordsOf(fr));
          if (d < bestE) bestE = d;
        }
        n = bestE; nearest.set(key, bestE);
      }
      err += n;
    }
  }
  return {name, errPerFrame: err / frames, pct: 100 * err / frames / 8000, hasIdeal};
}

if (require.main === module) {
  const corpora = loadCensus();
  for (const d12Stride of [2, 3]) {
    const t0 = Date.now();
    const {font, contentRows, residual, totalWeight} = optimize(corpora, {d12Stride});
    console.log(`\n=== d12 stride ${d12Stride}: fixed ${font.fixedSlots} slots, content ${font.contentSlots} slots (used ${contentRows.length}), residual ${(residual / totalWeight).toFixed(3)} px/cell weighted`);
    fs.mkdirSync(path.join(HERE, 'build'), {recursive: true});
    fs.writeFileSync(path.join(HERE, `build/font-stride${d12Stride}.bin`), toBytes(font));
    fs.writeFileSync(path.join(HERE, `build/content-rows-stride${d12Stride}.json`), JSON.stringify(contentRows));
    for (const corpus of corpora) {
      const m = measure(corpus.name, corpus.dir, corpus.frames ?? 161, font.rows);
      console.log(`${m.name.padEnd(20)} ${m.hasIdeal ? 'vs ideal' : 'vs film '} ${(m.errPerFrame).toFixed(1)} px/frame (${m.pct.toFixed(2)}%)`);
    }
    console.log(`(optimize+measure took ${((Date.now() - t0) / 1000).toFixed(1)}s)`);
  }
}
