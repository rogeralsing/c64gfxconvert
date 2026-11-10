'use strict';

// Fixed canonical byte-Huffman over already encoded character deltas.
// All modelling happens offline. Native playback uses immutable lookup tables.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');

const here = __dirname;
const output = path.join(here, 'build/huffman-study');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const stats = values => ({min: Math.min(...values), mean: values.reduce((sum, value) => sum + value, 0) / values.length, max: Math.max(...values)});

function makeCodes(source) {
  const frequencies = new Uint32Array(256);
  for (const value of source) frequencies[value]++;
  let serial = 0;
  const queue = Array.from(frequencies, (frequency, symbol) => ({frequency, symbol, minimum: symbol, serial: serial++})).filter(item => item.frequency);
  const order = (a, b) => a.frequency - b.frequency || a.minimum - b.minimum || a.serial - b.serial;
  while (queue.length > 1) {
    queue.sort(order);
    const left = queue.shift(), right = queue.shift();
    queue.push({left, right, frequency: left.frequency + right.frequency,
      minimum: Math.min(left.minimum, right.minimum), serial: serial++});
  }
  const lengths = new Uint8Array(256);
  function visit(node, depth) {
    if (node.symbol !== undefined) lengths[node.symbol] = Math.max(1, depth);
    else { visit(node.left, depth + 1); visit(node.right, depth + 1); }
  }
  visit(queue[0], 0);
  const sorted = Array.from(lengths, (length, symbol) => ({length, symbol})).filter(item => item.length).sort((a, b) => a.length - b.length || a.symbol - b.symbol);
  assert(Math.max(...lengths) <= 24, 'Host integer codes must fit 24 bits');
  const codes = new Array(256).fill(null);
  let current = 0, previousLength = sorted[0].length;
  for (let i = 0; i < sorted.length; i++) {
    const {symbol, length} = sorted[i];
    if (i) current = (current + 1) * 2 ** (length - previousLength);
    assert(current < 2 ** length);
    codes[symbol] = {symbol, frequency: frequencies[symbol], length, code: current, bits: current.toString(2).padStart(length, '0')};
    previousLength = length;
  }
  return {frequencies, lengths, codes};
}

function makeTree(codes) {
  const root = {};
  for (const item of codes.filter(Boolean)) {
    let node = root;
    for (const bit of item.bits) node = node[bit] ||= {};
    assert.equal(node.symbol, undefined);
    node.symbol = item.symbol;
  }
  const nodes = [];
  function assign(node) {
    if (node.symbol !== undefined) return {leaf: true, value: node.symbol};
    const index = nodes.length;
    const record = {index};
    nodes.push(record);
    assert(node[0] && node[1], 'Complete Huffman tree must have both children');
    record.left = assign(node[0]); record.right = assign(node[1]);
    return {leaf: false, value: index};
  }
  const first = assign(root);
  assert.equal(first.value, 0);
  assert(nodes.length <= 255);
  const tables = {leftValue: Buffer.alloc(256), rightValue: Buffer.alloc(256),
    leftLeaf: Buffer.alloc(256), rightLeaf: Buffer.alloc(256)};
  for (const node of nodes) for (const side of ['left', 'right']) {
    tables[side + 'Value'][node.index] = node[side].value;
    tables[side + 'Leaf'][node.index] = node[side].leaf ? 0x80 : 0;
  }
  const prefixValue = Buffer.alloc(256), prefixLength = Buffer.alloc(256);
  for (let prefix = 0; prefix < 256; prefix++) {
    let node = 0;
    for (let consumed = 1; consumed <= 8; consumed++) {
      const bit = (prefix >>> (8 - consumed)) & 1;
      const child = nodes[node][bit ? 'right' : 'left'];
      if (child.leaf) {
        prefixValue[prefix] = child.value; prefixLength[prefix] = consumed;
        break;
      }
      node = child.value;
      if (consumed === 8) prefixValue[prefix] = node;
    }
  }
  return {nodes, ...tables, prefixValue, prefixLength};
}

function encode(source, codes) {
  const bytes = [];
  let value = 0, filled = 0, bitLength = 0;
  for (const symbol of source) {
    const item = codes[symbol];
    assert(item);
    for (let bit = item.length - 1; bit >= 0; bit--) {
      value = value * 2 + ((item.code >>> bit) & 1);
      filled++; bitLength++;
      if (filled === 8) { bytes.push(value); value = 0; filled = 0; }
    }
  }
  if (filled) bytes.push(value * 2 ** (8 - filled));
  return {bytes: Buffer.from(bytes), bitLength};
}

function decodeCanonical(encoded, count, codes) {
  const byBits = new Map(codes.filter(Boolean).map(item => [item.bits, item.symbol]));
  const result = Buffer.alloc(count);
  let bits = '', write = 0;
  for (let at = 0; write < count; at++) {
    assert(at < encoded.length * 8, 'Truncated Huffman bitstream');
    bits += (encoded[at >>> 3] >>> (7 - (at & 7))) & 1;
    if (byBits.has(bits)) { result[write++] = byBits.get(bits); bits = ''; }
  }
  return result;
}

function decodeTree(encoded, count, tree) {
  const result = Buffer.alloc(count);
  let bit = 0;
  for (let write = 0; write < count; write++) {
    let node = 0;
    while (true) {
      assert(bit < encoded.length * 8, 'Truncated tree bitstream');
      const side = ((encoded[bit >>> 3] >>> (7 - (bit & 7))) & 1) ? 'right' : 'left';
      bit++;
      const child = tree.nodes[node][side];
      if (child.leaf) { result[write] = child.value; break; }
      node = child.value;
    }
  }
  return {bytes: result, bitsRead: bit};
}

function prefixCapacity(index, overhead, capacity) {
  let count = 1, used = 0;
  for (const frame of index.slice(0, -1)) {
    if (used + overhead + frame.bytes > capacity) break;
    used += overhead + frame.bytes; count++;
  }
  return {framesIncludingSeed: count, encodedTransitions: count - 1, bytes: used, remainingBytes: capacity - used};
}

function study(name, directory) {
  const source = fs.readFileSync(path.join(directory, 'hybrid.bin'));
  const index = JSON.parse(fs.readFileSync(path.join(directory, 'hybrid-index.json')));
  const destination = path.join(output, name);
  fs.mkdirSync(destination, {recursive: true});
  const {frequencies, lengths, codes} = makeCodes(source);
  const tree = makeTree(codes);
  const parts = [], frameIndex = [], framedParts = [];
  let packedBytes = 0, totalBits = 0;
  for (let frame = 0; frame < index.length; frame++) {
    const record = index[frame];
    const input = source.subarray(record.offset, record.offset + record.bytes);
    const encoded = encode(input, codes);
    const canonical = decodeCanonical(encoded.bytes, input.length, codes);
    const decoded = decodeTree(encoded.bytes, input.length, tree);
    assert(canonical.equals(input));
    assert(decoded.bytes.equals(input));
    assert.equal(decoded.bitsRead, encoded.bitLength);
    const header = Buffer.alloc(2); header.writeUInt16LE(input.length);
    framedParts.push(header, encoded.bytes);
    parts.push(encoded.bytes);
    frameIndex.push({frame, offset: packedBytes, bytes: encoded.bytes.length,
      bitLength: encoded.bitLength, decodedBytes: input.length, sourceOffset: record.offset});
    packedBytes += encoded.bytes.length; totalBits += encoded.bitLength;
  }
  const packed = Buffer.concat(parts);
  const whole = encode(source, codes);
  assert.equal(whole.bitLength, totalBits);
  assert(decodeCanonical(whole.bytes, source.length, codes).equals(source));
  const header = Buffer.alloc(266);
  header.write('HUF1'); header.writeUInt16LE(index.length, 4); header.writeUInt32LE(source.length, 6);
  Buffer.from(lengths).copy(header, 10);
  const framed = Buffer.concat([header, ...framedParts]);
  fs.writeFileSync(path.join(destination, 'compressed.bin'), packed);
  fs.writeFileSync(path.join(destination, 'continuous.bin'), whole.bytes);
  fs.writeFileSync(path.join(destination, 'stream.huf'), framed);
  fs.writeFileSync(path.join(destination, 'decoded.bin'), source);
  fs.writeFileSync(path.join(destination, 'frames-index.json'), JSON.stringify(frameIndex, null, 2) + '\n');
  fs.writeFileSync(path.join(destination, 'codes.json'), JSON.stringify(codes, null, 2) + '\n');
  fs.writeFileSync(path.join(destination, 'code-lengths.bin'), Buffer.from(lengths));
  fs.writeFileSync(path.join(destination, 'tree.json'), JSON.stringify(tree.nodes, null, 2) + '\n');
  for (const [field, file] of Object.entries({leftValue: 'left-value.bin', rightValue: 'right-value.bin',
    leftLeaf: 'left-leaf.bin', rightLeaf: 'right-leaf.bin', prefixValue: 'prefix-value.bin', prefixLength: 'prefix-length.bin'})) {
    fs.writeFileSync(path.join(destination, file), tree[field]);
  }
  const entropy = Array.from(frequencies).reduce((sum, frequency) => frequency ? sum - frequency / source.length * Math.log2(frequency / source.length) : sum, 0);
  const longCodeSymbols = codes.filter(item => item && item.length > 8).reduce((sum, item) => sum + item.frequency, 0);
  const result = {
    pass: true, name, source: path.relative(here, directory), frameCount: index.length,
    rawBytes: source.length, alphabetSymbols: codes.filter(Boolean).length,
    minCodeBits: Math.min(...codes.filter(Boolean).map(item => item.length)), maxCodeBits: Math.max(...lengths),
    entropyBitsPerByte: entropy, huffmanMeanBitsPerByte: totalBits / source.length,
    totalEncodedBits: totalBits, continuousPayloadBytes: whole.bytes.length,
    independentlyPaddedPayloadBytes: packed.length,
    paddingBytesVersusContinuous: packed.length - whole.bytes.length,
    perFrameOriginalBytes: stats(index.map(frame => frame.bytes)),
    perFramePackedBytes: stats(frameIndex.map(frame => frame.bytes)),
    perFrameFramedBytes: stats(frameIndex.map(frame => frame.bytes + 2)),
    payloadSavingFraction: 1 - packed.length / source.length,
    framingBytes: index.length * 2, codeLengthHeaderBytes: header.length,
    archiveStreamBytes: framed.length, archiveSavingFraction: 1 - framed.length / source.length,
    nativeTablesBytes: 1536, treeNodes: tree.nodes.length,
    eightBitFastPathSymbolsFraction: 1 - longCodeSymbols / source.length,
    diskBytesPerSecondAt25: {raw: source.length / index.length * 25,
      packedFrames: packed.length / index.length * 25,
      packedFramesWithLength: (packed.length + index.length * 2) / index.length * 25},
    prefixIn40960ByteSourceArea: {
      payloadOnly: prefixCapacity(frameIndex, 0, 40960),
      withDecodedLengthPerFrame: prefixCapacity(frameIndex, 2, 40960),
      withLengthAndTablesInsideArea: prefixCapacity(frameIndex, 2, 40960 - 1536)
    },
    abi: {
      bitOrder: 'MSB first. Each frame is byte-aligned; unused low bits of its final byte are zero.',
      outputLength: 'frames-index.json decodedBytes. stream.huf stores a LE16 decoded length before each independently padded frame.',
      codebook: 'Canonical codes sorted by length, then symbol. Archive header HUF1 + frameCountLE16 + rawTotalLE32 + 256 code-length bytes.',
      tree: 'Root node0; four256-byte left/right value/leaf arrays. Internal value is node index0..254; leaf flag0x80 identifies a symbol value0..255.',
      prefix: 'prefix-length[index8]1..8 means output prefix-value and consume that many bits; zero means consume8 bits, then continue tree decoding from prefix-value.'
    },
    verification: {canonicalRoundtripFrames: index.length, independentTreeRoundtripFrames: index.length,
      wholeStreamBytesCompared: source.length, nativeTimingMeasured: false},
    hashes: {source: sha(source), paddedPacked: sha(packed), continuousPacked: sha(whole.bytes), archive: sha(framed)}
  };
  fs.writeFileSync(path.join(destination, 'metadata.json'), JSON.stringify(result, null, 2) + '\n');
  return result;
}

function splitFields(frame) {
  const fields = [];
  let cursor = 0;
  const take = kind => {
    assert(cursor < frame.length, 'Truncated hybrid grammar');
    const value = frame[cursor++]; fields.push({kind, value}); return value;
  };
  for (let page = 0; page < 4; page++) {
    const groups = take(0), singles = take(0);
    for (let group = 0; group < groups; group++) {
      take(1);
      const count = take(0);
      for (let index = 0; index < count; index++) take(2);
    }
    for (let single = 0; single < singles; single++) { take(2); take(1); }
  }
  assert.equal(cursor, frame.length, 'Hybrid grammar did not cover the entire frame');
  return fields;
}

function encodeFields(fields, models) {
  const bytes = [];
  let value = 0, filled = 0, bitLength = 0;
  for (const field of fields) {
    const code = models[field.kind].codes[field.value];
    for (const bit of code.bits) {
      value = value * 2 + Number(bit); filled++; bitLength++;
      if (filled === 8) { bytes.push(value); value = 0; filled = 0; }
    }
  }
  if (filled) bytes.push(value * 2 ** (8 - filled));
  return {bytes: Buffer.from(bytes), bitLength};
}

function decodeFields(encoded, expectedBytes, models) {
  const tables = models.map(model => new Map(model.codes.filter(Boolean).map(code => [code.bits, code.symbol])));
  const output = [];
  let cursor = 0;
  function take(kind) {
    let bits = '';
    while (true) {
      assert(cursor < encoded.length * 8, 'Truncated field-Huffman stream');
      bits += (encoded[cursor >>> 3] >>> (7 - (cursor & 7))) & 1;
      cursor++;
      if (tables[kind].has(bits)) {
        const value = tables[kind].get(bits);
        output.push(value);
        assert(output.length <= expectedBytes, 'Decoded hybrid exceeds declared frame size');
        return value;
      }
    }
  }
  // This decoder discovers field ordering from decoded group/count values.
  // It receives no external per-byte class list from the encoder.
  for (let page = 0; page < 4; page++) {
    const groups = take(0), singles = take(0);
    for (let group = 0; group < groups; group++) {
      take(1);
      const count = take(0);
      for (let index = 0; index < count; index++) take(2);
    }
    for (let single = 0; single < singles; single++) { take(2); take(1); }
  }
  assert.equal(output.length, expectedBytes);
  return {bytes: Buffer.from(output), bitsRead: cursor};
}

function studyFields() {
  const directory = path.join(here, 'build/settings-164-html25');
  const destination = path.join(output, 'field-aware');
  fs.mkdirSync(destination, {recursive: true});
  const source = fs.readFileSync(path.join(directory, 'hybrid.bin'));
  const index = JSON.parse(fs.readFileSync(path.join(directory, 'hybrid-index.json')));
  const fields = index.map(record => splitFields(source.subarray(record.offset, record.offset + record.bytes)));
  const kinds = ['counts', 'glyphs', 'positions'];
  const streams = kinds.map((name, kind) => Buffer.from(fields.flat().filter(field => field.kind === kind).map(field => field.value)));
  assert.equal(streams.reduce((sum, stream) => sum + stream.length, 0), source.length);
  const models = streams.map(makeCodes);
  const parts = [], frameIndex = [], archiveParts = [];
  let offset = 0, totalBits = 0;
  for (let frame = 0; frame < index.length; frame++) {
    const encoded = encodeFields(fields[frame], models);
    const decoded = decodeFields(encoded.bytes, index[frame].bytes, models);
    const expected = source.subarray(index[frame].offset, index[frame].offset + index[frame].bytes);
    assert(decoded.bytes.equals(expected));
    assert.equal(decoded.bitsRead, encoded.bitLength);
    const length = Buffer.alloc(2); length.writeUInt16LE(expected.length);
    archiveParts.push(length, encoded.bytes);
    parts.push(encoded.bytes);
    frameIndex.push({frame, offset, bytes: encoded.bytes.length, decodedBytes: expected.length, bitLength: encoded.bitLength});
    offset += encoded.bytes.length; totalBits += encoded.bitLength;
  }
  const header = Buffer.alloc(778);
  header.write('HUF3'); header.writeUInt16LE(index.length, 4); header.writeUInt32LE(source.length, 6);
  for (let kind = 0; kind < 3; kind++) {
    Buffer.from(models[kind].lengths).copy(header, 10 + kind * 256);
    fs.writeFileSync(path.join(destination, kinds[kind] + '-codes.json'), JSON.stringify(models[kind].codes, null, 2) + '\n');
    fs.writeFileSync(path.join(destination, kinds[kind] + '-lengths.bin'), Buffer.from(models[kind].lengths));
  }
  const packed = Buffer.concat(parts), archive = Buffer.concat([header, ...archiveParts]);
  const contexts = kinds.map((name, kind) => {
    const model = models[kind];
    const bits = model.codes.filter(Boolean).reduce((sum, code) => sum + code.frequency * code.length, 0);
    const entropy = Array.from(model.frequencies).reduce((sum, frequency) => frequency ? sum - frequency / streams[kind].length * Math.log2(frequency / streams[kind].length) : sum, 0);
    return {name, rawBytes: streams[kind].length, alphabetSymbols: model.codes.filter(Boolean).length,
      entropyBitsPerByte: entropy, huffmanBits: bits, huffmanBitsPerByte: bits / streams[kind].length,
      maximumCodeBits: Math.max(...model.lengths)};
  });
  const report = {pass: true, variant: 'Three field-selected static canonical Huffman books',
    frameCount: index.length, rawBytes: source.length, contexts,
    totalBits, independentlyPaddedPayloadBytes: packed.length,
    payloadSavingFraction: 1 - packed.length / source.length,
    frameLengthBytes: index.length * 2, codebookHeaderBytes: header.length,
    archiveStreamBytes: archive.length, archiveSavingFraction: 1 - archive.length / source.length,
    perFramePackedBytes: stats(frameIndex.map(frame => frame.bytes)),
    diskBytesPerSecondAt25: {raw: source.length / index.length * 25,
      packedFrames: packed.length / index.length * 25,
      withFrameLengths: (packed.length + index.length * 2) / index.length * 25},
    sourceHash: sha(source), compressedHash: sha(packed), archiveHash: sha(archive),
    nativeRuntimeMeasured: false, nativeTableBytesNotYetChosen: true,
    decoder: 'One interleaved MSB-first bitstream per frame. The decoded hybrid grammar selects count/glyph/position codebooks; no per-byte type side channel is stored. Each frame has a LE16 raw byte count, and its final compressed byte is zero-padded.',
    verification: {framesIndependentlyParsedAndDecoded: index.length, bytesCompared: source.length,
      noExternalClassListUsedByDecoder: true},
    scope: 'Actual host serialized size and exact decoding only. A native field-aware decoder and its CPU/table-memory cost are not implemented or timed.'};
  fs.writeFileSync(path.join(destination, 'compressed.bin'), packed);
  fs.writeFileSync(path.join(destination, 'stream.huf'), archive);
  fs.writeFileSync(path.join(destination, 'frames-index.json'), JSON.stringify(frameIndex, null, 2) + '\n');
  fs.writeFileSync(path.join(destination, 'metadata.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report, null, 2));
  return report;
}

function main() {
  if (process.argv.includes('--field-aware')) return studyFields();
  fs.mkdirSync(output, {recursive: true});
  const current = study('current', path.join(here, 'build/settings-164-html25'));
  const largePath = path.join(here, 'build/font4-storage/deduped');
  const cases = [current];
  if (fs.existsSync(path.join(largePath, 'hybrid.bin'))) cases.push(study('large', largePath));
  fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify({pass: true, cases}, null, 2) + '\n');
  console.log(JSON.stringify({pass: true, cases}, null, 2));
  return cases;
}

module.exports = {makeCodes, makeTree, encode, decodeCanonical, decodeTree, study, splitFields, encodeFields, decodeFields, studyFields, main};
if (require.main === module) main();
