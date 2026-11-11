'use strict';

// One-time content-slot optimizer for the universal drawing font.
// Census: unique ideal tiles across all corpora, equal corpus weighting.
// Greedy: each content slot is the tile whose addition most reduces total
// weighted pixel error of the whole census against the font built so far.
// The drawing sections are locked and never re-chosen.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {buildFont, toBytes, CORPORA, readCorpus, tileRows, sha256} = require('./font.cjs');

const HERE = __dirname;

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

function loadCensus(root = process.env.UNIVERSAL_CORPORA_ROOT || path.join(HERE, '../build')) {
  const corpora = [];
  for (const [name, dirName] of CORPORA) {
    const dir = path.join(root, dirName);
    if (!fs.existsSync(path.join(dir, 'reference.frames'))) {
      console.log(`census: skipping ${name} (no corpus at ${dir})`);
      continue;
    }
    const corpus = readCorpus(dir, name);
    const stride = 1000;
    const counts = new Map();
    let total = 0;
    for (let f = 0; f < corpus.frames; f++) {
      for (let i = 0; i < stride; i++) {
        const rows = tileRows(corpus, f, i);
        const key = rows.join(',');
        counts.set(key, (counts.get(key) ?? 0) + 1);
        total++;
      }
    }
    corpora.push({...corpus, counts, total});
    console.log(`census: ${name.padEnd(20)} ${counts.size} unique tiles, ${total} cells (${corpus.hasIdeal ? 'ideal raster' : 'film font'})`);
  }
  assert(corpora.length > 0, 'No corpora found; generate the films or pass --root DIRECTORY.');
  return corpora;
}

function optimize(corpora, options = {}) {
  const {d12Stride = 3} = options;
  const fixed = buildFont({d12Stride, contentRows: []});
  const fixedWords = fixed.rows.slice(0, fixed.fixedSlots).map(wordsOf);
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

function measure(corpus, fontRows) {
  const fontWords = fontRows.map(wordsOf);
  let err = 0;
  for (const [key, count] of corpus.counts) {
    const words = wordsOf(key.split(',').map(Number));
    let best = 64;
    for (const candidate of fontWords) best = Math.min(best, dist(words, candidate));
    err += best * count;
  }
  return {name: corpus.name, frames: corpus.frames, cells: corpus.total, uniqueTiles: corpus.counts.size,
    target: corpus.hasIdeal ? 'ideal-raster' : 'existing-film-font', mismatchedPixels: err,
    errPerFrame: err / corpus.frames, pct: 100 * err / (corpus.frames * 64000), hashes: corpus.hashes};
}

if (require.main === module) {
  const options = {};
  for (let index = 2; index < process.argv.length; index += 2) {
    const key = process.argv[index];
    assert(['--root', '--output', '--measure-font'].includes(key) && process.argv[index + 1], 'Use [--root DIRECTORY] [--output DIRECTORY] [--measure-font FILE].');
    options[key] = process.argv[index + 1];
  }
  const root = path.resolve(options['--root'] || process.env.UNIVERSAL_CORPORA_ROOT || path.join(HERE, '../build'));
  const output = path.resolve(options['--output'] || path.join(HERE, 'build'));
  const corpora = loadCensus(root);
  const uniqueTiles = new Set(corpora.flatMap(corpus => [...corpus.counts.keys()])).size;
  fs.mkdirSync(output, {recursive: true});
  if (options['--measure-font']) {
    const file = path.resolve(options['--measure-font']), bytes = fs.readFileSync(file);
    assert.equal(bytes.length, 2048);
    const rows = Array.from({length: 256}, (_, code) => Array.from(bytes.subarray(code * 8, code * 8 + 8)));
    const report = {pass: true, mode: 'measure-frozen-font', font: path.relative(HERE, file).split(path.sep).join('/'),
      pathBase: 'universal script directory', fontSha256: sha256(bytes),
      producerSha256: Object.fromEntries(['font.cjs', 'optimize-content.cjs'].map(name => [name, sha256(fs.readFileSync(path.join(HERE, name)))])),
      rasterLayout: '320x200 binary byte pixels; 64000 bytes/frame, MSB-left packed only when extracting a tile',
      fitting: 'Unconstrained nearest-glyph Hamming distance; native mask-constrained fitting can differ.',
      corpora: corpora.length, uniqueTiles, results: corpora.map(corpus => measure(corpus, rows))};
    fs.writeFileSync(path.join(output, 'frozen-font-measurement.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify(report, null, 2));
  } else for (const d12Stride of [2, 3]) {
    const t0 = Date.now();
    const {font, contentRows, residual, totalWeight} = optimize(corpora, {d12Stride});
    console.log(`\n=== d12 stride ${d12Stride}: fixed ${font.fixedSlots} slots, content ${font.contentSlots} slots (used ${contentRows.length}), residual ${(residual / totalWeight).toFixed(3)} px/cell weighted`);
    fs.writeFileSync(path.join(output, `font-stride${d12Stride}.bin`), toBytes(font));
    fs.writeFileSync(path.join(output, `content-rows-stride${d12Stride}.json`), JSON.stringify(contentRows));
    for (const corpus of corpora) {
      const m = measure(corpus, font.rows);
      console.log(`${m.name.padEnd(20)} ${m.target} ${(m.errPerFrame).toFixed(1)} px/frame (${m.pct.toFixed(2)}%)`);
    }
    console.log(`(optimize+measure took ${((Date.now() - t0) / 1000).toFixed(1)}s)`);
  }
}

module.exports = {loadCensus, optimize, measure};
