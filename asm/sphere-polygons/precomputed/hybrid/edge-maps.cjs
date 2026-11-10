'use strict';

const { layouts } = require('./common.cjs');
const fillCodecs = require('./fill.cjs').codecs;
const packbits = fillCodecs.find(codec => codec.name === 'wildcard-packbits');
const rawBits = fillCodecs.find(codec => codec.name === 'raw-bits');
const CELLS = 1000;
const isEdge = glyph => glyph !== 0 && glyph !== 15;

function edgePositions(screen) {
  if (!screen || screen.length !== CELLS) throw new Error('An edge screen must have 1000 cells');
  const positions = [];
  for (let i = 0; i < CELLS; i++) if (isEdge(screen[i])) positions.push(i);
  return positions;
}

function destination(out) {
  if (out === undefined) return new Uint8Array(CELLS);
  if (out.length !== CELLS) throw new Error('An edge destination must have 1000 cells');
  return out;
}

function mapCodec(name, layout, compressed = true) {
  const selected = new Set(layout.indices);
  const packing = compressed ? packbits : rawBits, prefix = compressed ? 1 : 0;
  return {
    name,
    ...(layout.name === 'circle' ? { requiresLayout: 'circle' } : {}),
    encode(screen) {
      const positions = edgePositions(screen);
      for (const cell of positions) if (!selected.has(cell)) throw new Error('Edge lies outside declared map layout');
      const presence = new Uint8Array(CELLS);
      for (const cell of positions) presence[cell] = 15;
      // Every selected cell is fixed 0 or 15; there are no free edge-map cells.
      const mask = packing.encode(presence, layout.indices);
      if (compressed && mask.length > 126) throw new Error('Compressed edge mask exceeds one-byte format bound');
      const result = new Uint8Array(prefix + mask.length + positions.length);
      if (compressed) result[0] = mask.length;
      result.set(mask, prefix);
      for (let i = 0; i < positions.length; i++) result[prefix + mask.length + i] = screen[positions[i]];
      return result;
    },
    decode(payload, out, serializedIndices) {
      out = destination(out);
      const indices = layout.name === 'circle' && serializedIndices !== undefined ? serializedIndices : layout.indices;
      if (indices.length > CELLS || indices.some((cell, i) => !Number.isInteger(cell) || cell < 0 || cell >= CELLS || (i && cell <= indices[i - 1]))) throw new Error('Invalid edge-map destination layout');
      if (compressed && (!payload.length || payload[0] > 126 || 1 + payload[0] > payload.length)) throw new Error('Invalid edge-map length');
      const glyphStart = compressed ? 1 + payload[0] : Math.ceil(indices.length / 8);
      if (glyphStart > payload.length) throw new Error('Truncated raw edge map');
      const bits = packing.decode(payload.subarray(prefix, glyphStart), indices.length);
      let read = glyphStart;
      for (let i = 0; i < bits.length; i++) if (bits[i]) {
        if (read >= payload.length || !isEdge(payload[read])) throw new Error('Missing or invalid mapped edge glyph');
        out[indices[i]] = payload[read++];
      }
      if (read !== payload.length) throw new Error('Trailing edge-map glyph bytes');
      return out;
    }
  };
}

function encodeRice(screen) {
  const positions = edgePositions(screen), count = positions.length;
  let bestK = 0, bestBits = Infinity;
  for (let k = 0; k <= 7; k++) {
    let bits = 0, previous = -1;
    for (const position of positions) {
      const gap = position - previous - 1;
      bits += Math.floor(gap / 2 ** k) + 1 + k;
      previous = position;
    }
    if (bits < bestBits) { bestBits = bits; bestK = k; }
  }
  const bitBytes = Math.ceil(bestBits / 8), result = new Uint8Array(2 + bitBytes + count);
  const header = count | (bestK << 10);
  result[0] = header & 255; result[1] = header >>> 8;
  let bitPosition = 0, previous = -1;
  const write = bit => {
    if (bit) result[2 + (bitPosition >>> 3)] |= 0x80 >>> (bitPosition & 7);
    bitPosition++;
  };
  for (let i = 0; i < count; i++) {
    const position = positions[i], gap = position - previous - 1;
    const quotient = Math.floor(gap / 2 ** bestK), remainder = gap % 2 ** bestK;
    for (let q = 0; q < quotient; q++) write(0);
    write(1);
    for (let shift = bestK - 1; shift >= 0; shift--) write((remainder >>> shift) & 1);
    result[2 + bitBytes + i] = screen[position];
    previous = position;
  }
  return result;
}

function decodeRice(payload, out) {
  out = destination(out);
  if (payload.length < 2) throw new Error('Missing Rice edge header');
  const header = payload[0] | (payload[1] << 8), count = header & 1023, k = (header >>> 10) & 7;
  if ((header & 0xe000) || count > CELLS || payload.length < 2 + count) throw new Error('Invalid Rice edge header');
  const streamEnd = payload.length - count, positions = new Uint16Array(count);
  let bitPosition = 0, previous = -1;
  const read = () => {
    if (2 + (bitPosition >>> 3) >= streamEnd) throw new Error('Truncated Rice edge positions');
    const bit = (payload[2 + (bitPosition >>> 3)] >>> (7 - (bitPosition & 7))) & 1;
    bitPosition++;
    return bit;
  };
  for (let i = 0; i < count; i++) {
    let quotient = 0, remainder = 0;
    while (!read()) if (++quotient >= CELLS) throw new Error('Rice edge quotient exceeds screen');
    for (let bit = 0; bit < k; bit++) remainder = (remainder << 1) | read();
    const position = previous + 1 + quotient * 2 ** k + remainder;
    if (position >= CELLS) throw new Error('Rice edge position exceeds screen');
    positions[i] = position;
    previous = position;
  }
  if (2 + Math.ceil(bitPosition / 8) !== streamEnd) throw new Error('Trailing Rice position bytes');
  const padding = (8 - (bitPosition & 7)) & 7;
  if (padding && (payload[streamEnd - 1] & ((1 << padding) - 1))) throw new Error('Nonzero Rice padding');
  for (let i = 0; i < count; i++) {
    const glyph = payload[streamEnd + i];
    if (!isEdge(glyph)) throw new Error('Invalid Rice edge glyph');
    out[positions[i]] = glyph;
  }
  return out;
}

const codecs = [
  mapCodec('edges-map-packbits-full', layouts.full),
  mapCodec('edges-map-packbits-circle', layouts.circle),
  mapCodec('edges-map-raw-full', layouts.full, false),
  mapCodec('edges-map-raw-circle', layouts.circle, false),
  { name: 'edges-rice-gaps', encode: encodeRice, decode: decodeRice }
];
module.exports = { codecs };

if (require.main === module) {
  const assert = require('node:assert/strict');
  const fs = require('node:fs'), path = require('node:path');
  const common = require('./common.cjs'), corpus = common.getCorpus();
  const report = { pass: false, measurement: 'Actual serialized edge payloads, including all local headers and padding; no CPU timing.',
    inputHashes: corpus.inputHashes, trajectory: corpus.trajectory, models: {}, syntheticCases: 0,
    overlayCellsChecked: 0, circleLayoutMetadataBytesOnce: 50 };
  const selected = new Set(layouts.circle.indices);
  function verify(codec, screen) {
    const payload = codec.encode(screen), out = Uint8Array.from({ length: CELLS }, (_, i) => (i * 73 + 91) & 255);
    const before = out.slice();
    assert.equal(codec.decode(payload, out), out);
    for (let i = 0; i < CELLS; i++) {
      assert.equal(out[i], isEdge(screen[i]) ? screen[i] : before[i], `${codec.name} cell ${i}`);
      report.overlayCellsChecked++;
    }
    return payload.length;
  }
  for (const [model, screens] of Object.entries(corpus.models)) {
    report.models[model] = {};
    for (const codec of codecs) {
      const sizes = screens.map(screen => verify(codec, screen));
      report.models[model][codec.name] = { ...common.stats(sizes), sizes, requiresLayout: codec.requiresLayout || null };
    }
    console.log(JSON.stringify({ model, bytes: Object.fromEntries(Object.entries(report.models[model]).map(([name, result]) => [name,
      { min: result.min, mean: result.mean, max: result.max, total: result.total }])) }));
  }
  const synthetic = [new Uint8Array(CELLS), new Uint8Array(CELLS).fill(15),
    Uint8Array.from({ length: CELLS }, (_, i) => i & 1 ? 15 : 0),
    Uint8Array.from({ length: CELLS }, (_, i) => i % 254 + 1 === 15 ? 255 : i % 254 + 1)];
  for (const positions of [[0], [999], [0, 999], [39, 40, 41], [319, 320, 321], layouts.circle.indices]) {
    const screen = new Uint8Array(CELLS).fill(15);
    positions.forEach((cell, i) => { screen[cell] = i % 254 + 1 === 15 ? 255 : i % 254 + 1; });
    synthetic.push(screen);
  }
  for (const screen of synthetic) for (const codec of codecs) {
    if (codec.requiresLayout && edgePositions(screen).some(cell => !selected.has(cell))) {
      assert.throws(() => codec.encode(screen));
    } else { verify(codec, screen); report.syntheticCases++; }
  }
  // Hand-written Rice packet: N=2, k=0, gaps 0 and 2 -> 1 001, then codes.
  const example = decodeRice(Uint8Array.of(2, 0, 0x90, 7, 8), new Uint8Array(CELLS).fill(33));
  assert.equal(example[0], 7); assert.equal(example[3], 8); assert.equal(example[1], 33);
  for (const bytes of [[], [0], [0, 0, 0], [0, 0xe0], [1, 0, 0, 7], [1, 0, 0x81, 7], [1, 0, 0x80, 15]]) {
    assert.throws(() => decodeRice(Uint8Array.from(bytes)));
  }
  for (const codec of codecs.slice(0, 2)) for (const bytes of [[], [127], [0], [1, 128]]) {
    assert.throws(() => codec.decode(Uint8Array.from(bytes)));
  }
  report.pass = true;
  const output = path.resolve(process.argv[2] || path.join(__dirname, 'build/edge-maps-report.json'));
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ pass: true, corpusScreens: 512, codecs: codecs.length, syntheticCases: report.syntheticCases,
    overlayCellsChecked: report.overlayCellsChecked, output }));
}
