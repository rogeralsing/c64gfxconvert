'use strict';

// Ramp-run codec study on the universal font: per frame, first greedy
// geometric ramp-lines, then the screen-order literal codec for the rest.
// Compares against the pure literal codec on the same screens.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {buildFont, toBytes, DIRS, CORPORA, readCorpus, tileRows, sha256} = require('./font.cjs');
const {encodePairs, decodePairs} = require('../../precomputed/hybrid/delta.cjs');

const HERE = __dirname;
const SLOPE_SHIFT = 4;
const pop = Uint8Array.from({length: 256}, (_, v) => { let c = 0; for (; v; v &= v - 1) c++; return c; });

let fontRows, slotMap, fontBytes, bitmapOf;

function configureFont(bytes) {
  assert.equal(bytes.length, 2048);
  const fixed = buildFont({d12Stride: 3});
  assert(bytes.subarray(0, fixed.fixedSlots * 8).equals(toBytes(fixed).subarray(0, fixed.fixedSlots * 8)),
    'Ramp commands require the declared stride-3 fixed slot map.');
  fontBytes = bytes;
  fontRows = Array.from({length: 256}, (_, code) => Array.from(bytes.subarray(code * 8, code * 8 + 8)));
  bitmapOf = fontRows;slotMap = fixed.slotMap;
}

function loadCorpus(dirName, root) {
  const corpus = readCorpus(path.join(root, dirName));
  const stride = 1000;
  const target = [];
  const cache = new Map();
  for (let f = 0; f < corpus.frames; f++) {
    const codes = new Array(stride);
    for (let i = 0; i < stride; i++) {
      const rows = tileRows(corpus, f, i), key = rows.join(',');
      if (!cache.has(key)) cache.set(key, nearestCode(rows));
      codes[i] = cache.get(key);
    }
    target.push(codes);
  }
  return {...corpus, target, stride};
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
        for (let r = 0; r < 8; r++) gain += pop[t0[r]];
        if (scr[cells[i]] !== info0.chain.base + s) saves++;
      }
      const budget = Math.round(pctLine * gain);
      if (err > budget) continue;
      const value = saves * 2 - 5;
      if (value >= 4) candidates.push({info0, cells, sA, slope, err, value, gain});
    }
  }
  candidates.sort((a, b) => b.value - a.value);
  const used = new Uint8Array(stride);
  let lineBytes = 0, lines = 0, lineCells = 0, frameErr = 0;
  const records = [];
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
    records.push({start: cand.cells[0], length: cand.cells.length,
      chain: slotMap.chains.indexOf(cand.info0.chain), step: cand.sA, slope: cand.slope});
  }
  const literal = Buffer.from(encodePairs(Uint8Array.from(target), Uint8Array.from(scr)));
  const packet = Buffer.alloc(2 + lineBytes + literal.length);
  packet.writeUInt16LE(records.length);
  // Five bytes: start10, lengthMinusOne6, chain4, step5, signedSlope8,
  // followed by seven zero reserved bits. Direction comes from the chain.
  records.forEach((record, index) => {
    assert(record.start < 1000 && record.length <= 64 && record.chain < 16 && record.step < 32);
    assert(record.slope >= -128 && record.slope <= 127);
    let packed = BigInt(record.start) | BigInt(record.length - 1) << 10n | BigInt(record.chain) << 16n
      | BigInt(record.step) << 20n | BigInt(record.slope & 255) << 25n;
    for (let byte = 0; byte < 5; byte++) {packet[2 + index * 5 + byte] = Number(packed & 255n);packed >>= 8n;}
  });
  literal.copy(packet, 2 + lineBytes);
  // apply literal runs to reach target
  const decoded = decodeFrame(packet, prev);
  assert.deepEqual(Array.from(decoded), Array.from(target), 'Line and literal packet roundtrip');
  return {packet, bytes: packet.length, lineBytes, litBytes: literal.length, framingBytes: 2,
    lines, lineCells, frameErr, scr: Array.from(decoded)};
}

function decodeFrame(packet, previous) {
  assert(packet.length >= 2);
  const scr = Uint8Array.from(previous), lines = packet.readUInt16LE(0);
  let read = 2;
  for (let line = 0; line < lines; line++) {
    assert(read + 5 <= packet.length);
    let packed = 0n;
    for (let byte = 0; byte < 5; byte++) packed |= BigInt(packet[read++]) << BigInt(byte * 8);
    assert.equal(packed >> 33n, 0n, 'Reserved line bits');
    const start = Number(packed & 1023n), length = Number(packed >> 10n & 63n) + 1;
    const chain = slotMap.chains[Number(packed >> 16n & 15n)], first = Number(packed >> 20n & 31n);
    let slope = Number(packed >> 25n & 255n);if (slope & 128) slope -= 256;
    assert(start < 1000 && first < chain.bitmaps.length);
    const [dx, dy] = DIRS[chain.dir], x0 = start % 40, y0 = Math.floor(start / 40);
    for (let index = 0; index < length; index++) {
      const x = x0 + index * dx, y = y0 + index * dy;
      assert(x >= 0 && x < 40 && y >= 0 && y < 25);
      const step = Math.max(0, Math.min(chain.bitmaps.length - 1, first + ((slope * index) >> SLOPE_SHIFT)));
      scr[y * 40 + x] = chain.base + step;
    }
  }
  return decodePairs(packet.subarray(read), scr);
}

if (require.main === module) {
  const options = {};
  for (let index = 2; index < process.argv.length; index += 2) {
    const key = process.argv[index];
    assert(['--root', '--font', '--output'].includes(key) && process.argv[index + 1], 'Use [--root DIRECTORY] [--font FILE] [--output DIRECTORY].');
    options[key] = process.argv[index + 1];
  }
  const root = path.resolve(options['--root'] || process.env.UNIVERSAL_CORPORA_ROOT || path.join(HERE, '../build'));
  const file = path.resolve(options['--font'] || path.join(HERE, '../three-scene/universal-font.bin'));
  const output = path.resolve(options['--output'] || path.join(HERE, 'build'));
  configureFont(fs.readFileSync(file));
  const results = [];
  for (const [name, dirName] of CORPORA.filter(([name]) => ['solid-star', 'tumbling-star', 'glass-star', 'glass-diamond'].includes(name))) {
    if (!fs.existsSync(path.join(root, dirName, 'reference.frames'))) continue;
    const corpus = loadCorpus(dirName, root);
    const edges = Array.from({length: corpus.frames - 1}, (_, from) => [from, from + 1]);
    if (corpus.loop) edges.push([corpus.frames - 1, corpus.loop.startFrame]);
    const litOnly = edges.reduce((sum, [from, to]) => sum + encodePairs(Uint8Array.from(corpus.target[to]), Uint8Array.from(corpus.target[from])).length, 0);
    for (const pct of [0, 0.05]) {
      let totBytes = 0, totLit = 0, totLineB = 0, lines = 0, err = 0, lineCells = 0;
      const payloads = [];
      for (const [from, to] of edges) {
        const r = encodeFrame(corpus.target[from], corpus.target[to], pct);
        totBytes += r.bytes;totLit += r.litBytes;totLineB += r.lineBytes;
        lines += r.lines;err += r.frameErr;lineCells += r.lineCells;payloads.push(r.packet);
      }
      results.push({name, frames: corpus.frames, transitions: edges.length, closingPatchIncluded: Boolean(corpus.loop),
        intermediateErrorBudgetFraction: pct, pureLiteralBytes: litOnly, lineLiteralBytes: totBytes,
        pureLiteralBytesPerTransition: litOnly / edges.length, lineLiteralBytesPerTransition: totBytes / edges.length,
        changePercent: 100 * (totBytes / litOnly - 1), lineBytes: totLineB, literalBytes: totLit,
        framingBytes: 2 * edges.length, lines, lineCells, summedLinePixelErrors: err,
        finalCharacterScreensExact: true, payloadSha256: sha256(Buffer.concat(payloads)), corpusHashes: corpus.hashes});
      console.log(`${name.padEnd(16)} budget ${Math.round(pct * 100)}%: ${(totBytes / edges.length).toFixed(1)} B/f vs literal ${(litOnly / edges.length).toFixed(1)} B/f`);
    }
  }
  assert(results.length > 0, 'No corpora found; generate the films or pass --root DIRECTORY.');
  fs.mkdirSync(output, {recursive: true});
  const report = {pass: true, scope: 'Serialized host codec study, not a C64 runtime or FPS measurement.',
    font: path.relative(HERE, file).split(path.sep).join('/'), pathBase: 'universal script directory', fontSha256: sha256(fontBytes),
    producerSha256: Object.fromEntries(['font.cjs', 'line-encode.cjs', '../../precomputed/hybrid/delta.cjs'].map(name => [name, sha256(fs.readFileSync(path.join(HERE, name)))])),
    targetFitting: 'Unconstrained nearest glyph for each ideal raster tile; existing-font rendering only if ideal.frames is absent.',
    packet: 'lineCount16LE; lineCount five-byte records; exact existing global varint skip/literal residual',
    lineBits: 'start10, lengthMinusOne6, chain4, step5, signedSlope8, reservedZero7 (little-endian)',
    lossless: 'Every serialized packet decodes to its entire 1000-byte target screen. Approximate line pixels are repaired by the literal pass.',
    results};
  fs.writeFileSync(path.join(output, 'line-study.json'), JSON.stringify(report, null, 2) + '\n');
}

module.exports = {configureFont, loadCorpus, encodeFrame, decodeFrame};
