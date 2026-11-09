'use strict';

// Glyphs 0 and 15 constrain the underlying fill; every other glyph is replaced
// by the edge overlay and leaves its underlying bit unconstrained.
function constraints(screen, indices, edgeZero = false) {
  const selected = indices === undefined ? Array.from(screen.keys()) : indices;
  const fixed = new Int8Array(selected.length);
  for (let i = 0; i < selected.length; i++) {
    const cell = selected[i];
    if (!Number.isInteger(cell) || cell < 0 || cell >= screen.length) {
      throw new RangeError('Fill layout contains an invalid screen index');
    }
    fixed[i] = screen[cell] === 15 ? 1 : screen[cell] === 0 || edgeZero ? 0 : -1;
  }
  return fixed;
}

function checkCount(count) {
  if (!Number.isSafeInteger(count) || count < 0) throw new RangeError('Invalid fill cell count');
}

function byteConstraints(fixed) {
  const count = Math.ceil(fixed.length / 8);
  const masks = new Uint8Array(count), ones = new Uint8Array(count);
  for (let i = 0; i < fixed.length; i++) {
    if (fixed[i] < 0) continue;
    const bit = 0x80 >>> (i & 7), byte = i >>> 3;
    masks[byte] |= bit;
    if (fixed[i]) ones[byte] |= bit;
  }
  return { masks, ones };
}

function unpack(bytes, count) {
  checkCount(count);
  if (bytes.length !== Math.ceil(count / 8)) throw new Error('Wrong packed fill byte count');
  const result = new Uint8Array(count);
  for (let i = 0; i < count; i++) result[i] = (bytes[i >>> 3] >>> (7 - (i & 7))) & 1;
  return result;
}

function encodeRaw(screen, indices) {
  return byteConstraints(constraints(screen, indices)).ones;
}

// Standard PackBits packet bounds, with 128 rejected rather than emitted as a
// no-op: 0..127 literal bytes; 129..255 repeat one byte 128..2 times.
function encodePackBits(screen, indices, edgeZero) {
  const { masks, ones } = byteConstraints(constraints(screen, indices, edgeZero));
  const count = masks.length, cost = new Uint32Array(count + 1);
  const lengths = new Uint8Array(count), repeats = new Uint8Array(count);
  const values = new Uint8Array(count);
  for (let first = count - 1; first >= 0; first--) {
    let best = 0xffffffff, bestLength = 1, bestRepeat = 0, bestValue = 0;
    const end = Math.min(count, first + 128);
    for (let next = first + 1; next <= end; next++) {
      const candidate = 1 + next - first + cost[next];
      if (candidate <= best) {
        best = candidate; bestLength = next - first; bestRepeat = 0;
      }
    }
    let requiredOnes = 0, requiredZeros = 0;
    for (let next = first; next < end; next++) {
      requiredOnes |= ones[next];
      requiredZeros |= masks[next] ^ ones[next];
      if (requiredOnes & requiredZeros) break;
      const length = next - first + 1;
      if (length < 2) continue;
      const candidate = 2 + cost[next + 1];
      if (candidate <= best) {
        best = candidate; bestLength = length; bestRepeat = 1; bestValue = requiredOnes;
      }
    }
    cost[first] = best;
    lengths[first] = bestLength;
    repeats[first] = bestRepeat;
    values[first] = bestValue;
  }
  const payload = new Uint8Array(cost[0]);
  let write = 0;
  for (let first = 0; first < count;) {
    const length = lengths[first];
    if (repeats[first]) {
      payload[write++] = 257 - length;
      payload[write++] = values[first];
    } else {
      payload[write++] = length - 1;
      payload.set(ones.subarray(first, first + length), write);
      write += length;
    }
    first += length;
  }
  return payload;
}

function decodePackBits(payload, count) {
  checkCount(count);
  const packed = new Uint8Array(Math.ceil(count / 8));
  let read = 0, write = 0;
  while (read < payload.length) {
    const control = payload[read++];
    if (control === 128) throw new Error('Reserved PackBits control');
    if (control < 128) {
      const length = control + 1;
      if (read + length > payload.length || write + length > packed.length) {
        throw new Error('Truncated or overflowing fill literal');
      }
      for (let i = 0; i < length; i++) packed[write++] = payload[read++];
    } else {
      const length = 257 - control;
      if (read >= payload.length || write + length > packed.length) {
        throw new Error('Truncated or overflowing fill repeat');
      }
      packed.fill(payload[read++], write, write + length);
      write += length;
    }
  }
  if (write !== packed.length) throw new Error('Incomplete packed fill');
  return unpack(packed, count);
}

function ulebBytes(value) {
  let bytes = 1;
  while (value >= 128) { value = Math.floor(value / 128); bytes++; }
  return bytes;
}

function writeUleb(result, position, value) {
  do {
    const part = value % 128;
    value = Math.floor(value / 128);
    result[position++] = part | (value ? 128 : 0);
  } while (value);
  return position;
}

// Exact shortest run stream for the chosen grammar. State is (cell, next bit).
// A positive run may extend only until the next opposing fixed bit. A zero run
// flips the bit; two consecutive zero runs can never improve a shortest stream.
function encodeAlternating(screen, indices, edgeZero) {
  const fixed = constraints(screen, indices, edgeZero), count = fixed.length;
  if (!count) return new Uint8Array();
  const cost = [new Uint32Array(count + 1), new Uint32Array(count + 1)];
  const length = [new Uint32Array(count), new Uint32Array(count)];
  const flip = [new Uint8Array(count), new Uint8Array(count)];
  const nextOpposite = [count, count];
  for (let first = count - 1; first >= 0; first--) {
    if (fixed[first] >= 0) nextOpposite[1 - fixed[first]] = first;
    const positiveCost = [Infinity, Infinity], positiveLength = [0, 0];
    for (let bit = 0; bit < 2; bit++) {
      for (let next = first + 1; next <= nextOpposite[bit]; next++) {
        const run = next - first;
        const candidate = ulebBytes(run) + cost[1 - bit][next];
        if (candidate <= positiveCost[bit]) {
          positiveCost[bit] = candidate; positiveLength[bit] = run;
        }
      }
    }
    for (let bit = 0; bit < 2; bit++) {
      if (1 + positiveCost[1 - bit] < positiveCost[bit]) {
        cost[bit][first] = 1 + positiveCost[1 - bit];
        length[bit][first] = positiveLength[1 - bit];
        flip[bit][first] = 1;
      } else {
        cost[bit][first] = positiveCost[bit];
        length[bit][first] = positiveLength[bit];
      }
    }
  }
  const result = new Uint8Array(cost[0][0]);
  let position = 0, first = 0, bit = 0;
  while (first < count) {
    const run = length[bit][first];
    if (flip[bit][first]) {
      result[position++] = 0;
      bit = 1 - bit;
    }
    position = writeUleb(result, position, run);
    first += run;
    bit = 1 - bit;
  }
  return result;
}

function decodeAlternating(payload, count) {
  checkCount(count);
  const result = new Uint8Array(count);
  let read = 0, written = 0, bit = 0;
  while (written < count) {
    let run = 0, multiplier = 1, part;
    do {
      if (read >= payload.length) throw new Error('Truncated alternating fill run');
      part = payload[read++];
      run += (part & 127) * multiplier;
      if (!Number.isSafeInteger(run)) throw new Error('Oversized alternating fill run');
      multiplier *= 128;
      if (!Number.isSafeInteger(multiplier)) throw new Error('Oversized alternating fill integer');
    } while (part & 128);
    if (run > count - written) throw new Error('Alternating fill run exceeds layout');
    result.fill(bit, written, written + run);
    written += run;
    bit = 1 - bit;
  }
  if (read !== payload.length) throw new Error('Trailing alternating fill data');
  return result;
}

const codecs = [
  { name: 'raw-bits', encode: encodeRaw, decode: unpack },
  { name: 'wildcard-packbits', encode: (screen, indices) => encodePackBits(screen, indices, false), decode: decodePackBits },
  { name: 'edge0-packbits-control', encode: (screen, indices) => encodePackBits(screen, indices, true), decode: decodePackBits },
  { name: 'wildcard-alternating-uleb', encode: (screen, indices) => encodeAlternating(screen, indices, false), decode: decodeAlternating },
  { name: 'edge0-alternating-uleb-control', encode: (screen, indices) => encodeAlternating(screen, indices, true), decode: decodeAlternating }
];

module.exports = { codecs };

if (require.main === module) {
  if (process.argv[2] === '--measure') {
    const assert = require('node:assert/strict');
    const fs = require('node:fs'), path = require('node:path');
    const common = require('./common.cjs'), corpus = common.getCorpus();
    const report = {
      pass: false, measurement: 'Serialized fill payload bytes only; no framing, font or CPU timing.',
      framesPerModel: corpus.frames, trajectory: corpus.trajectory, inputHashes: corpus.inputHashes,
      layouts: {}, models: {}, fixedCellsChecked: 0
    };
    for (const [name, layout] of Object.entries(corpus.layouts)) {
      report.layouts[name] = { cells: layout.indices.length, metadataBytesOnce: layout.metadata.length,
        rawPackedBytesPerFrame: Math.ceil(layout.indices.length / 8) };
    }
    for (const [model, screens] of Object.entries(corpus.models)) {
      report.models[model] = {};
      for (const [layoutName, layout] of Object.entries(corpus.layouts)) {
        const results = {};
        for (const codec of codecs) {
          const sizes = [];
          for (const screen of screens) {
            const payload = codec.encode(screen, layout.indices);
            assert(payload instanceof Uint8Array, 'A codec must return actual bytes');
            const bits = codec.decode(payload, layout.indices.length);
            common.checkFill(bits, screen, layout.indices);
            const expanded = common.expandFill(bits, layout.indices);
            for (let cell = 0; cell < screen.length; cell++) {
              if (screen[cell] !== 0 && screen[cell] !== 15) continue;
              assert.equal(expanded[cell], screen[cell], `Omitted or wrong fixed cell ${cell}`);
              report.fixedCellsChecked++;
            }
            sizes.push(payload.length);
          }
          results[codec.name] = { ...common.stats(sizes), sizes };
        }
        report.models[model][layoutName] = results;
        console.log(JSON.stringify({ model, layout: layoutName, meanPayloadBytes: Object.fromEntries(
          Object.entries(results).map(([name, result]) => [name, result.mean])) }));
      }
    }
    report.pass = true;
    const output = path.resolve(process.argv[3] || path.join(__dirname, 'build/fill-report.json'));
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ pass: true, models: Object.keys(corpus.models).length,
      framesPerModel: corpus.frames, fixedCellsChecked: report.fixedCellsChecked, output }));
  } else if (process.argv[2] !== '--self-test') {
    console.error('Usage: node fill.cjs --self-test | --measure [OUTPUT_JSON]');
    process.exitCode = 1;
  } else {
    const assert = require('node:assert/strict');
    let checked = 0;
    function verify(screen) {
      const indices = Uint16Array.from(screen, (_, i) => i);
      for (const codec of codecs) {
        const payload = codec.encode(screen, indices), bits = codec.decode(payload, screen.length);
        assert.equal(bits.length, screen.length);
        for (let i = 0; i < screen.length; i++) {
          assert.ok(bits[i] === 0 || bits[i] === 1);
          if (screen[i] === 0) assert.equal(bits[i], 0);
          if (screen[i] === 15) assert.equal(bits[i], 1);
          if (codec.name.includes('control') && screen[i] !== 15) assert.equal(bits[i], 0);
        }
        checked++;
      }
    }
    for (const count of [0, 1, 7, 8, 9, 127, 128, 129, 475, 600, 1000]) {
      for (const glyph of [0, 15, 1, 255]) verify(new Uint8Array(count).fill(glyph));
      verify(Uint8Array.from({ length: count }, (_, i) => [0, 15, 1][i % 3]));
    }

    // Independent format examples exercise boundary lengths, padding and a
    // repeat packet without obtaining expected bytes from an encoder.
    const packetDecoder = codecs[1].decode, runDecoder = codecs[3].decode;
    assert.deepEqual([...packetDecoder(Uint8Array.of(255, 0xaa), 16)],
      Array.from({ length: 16 }, (_, i) => 1 - (i & 1)));
    assert.deepEqual([...packetDecoder(Uint8Array.of(0, 0x80), 1)], [1]);
    assert.deepEqual([...runDecoder(Uint8Array.of(0, 3, 2, 1), 6)], [1, 1, 1, 0, 0, 1]);
    assert.equal(runDecoder(Uint8Array.of(0x80, 0x80, 1), 16384).reduce((a, b) => a + b, 0), 0);
    for (const [payload, count] of [[[128], 0], [[], 8], [[255], 16], [[255, 0], 8]]) {
      assert.throws(() => packetDecoder(Uint8Array.from(payload), count));
    }
    for (const [payload, count] of [[[1, 0], 1], [[0], 1], [[2], 1], [[128], 128]]) {
      assert.throws(() => runDecoder(Uint8Array.from(payload), count));
    }

    // Enumerate every assignment of free cells in short ternary inputs. The
    // oracle is ordinary binary run counting, independent of wildcard DP.
    let runOptimalityCases = 0;
    for (let count = 0; count <= 8; count++) {
      for (let code = 0; code < 3 ** count; code++) {
        let value = code, freeCount = 0;
        const screen = Uint8Array.from({ length: count }, () => {
          const digit = value % 3; value = Math.floor(value / 3);
          if (digit === 2) freeCount++;
          return [0, 15, 1][digit];
        });
        let best = Infinity;
        for (let assignment = 0; assignment < 2 ** freeCount; assignment++) {
          let bitIndex = 0, previous = 0, bytes = 0, length = 0;
          for (const glyph of screen) {
            const bit = glyph === 1 ? (assignment >>> bitIndex++) & 1 : glyph === 15 ? 1 : 0;
            if (bit !== previous) { bytes++; previous = bit; length = 0; }
            length++;
          }
          if (length) bytes++;
          best = Math.min(best, bytes);
        }
        assert.equal(codecs[3].encode(screen).length, best);
        runOptimalityCases++;
      }
    }

    // Ordinary concrete-byte PackBits oracle. Enumerate the free assignments
    // before optimizing packets, instead of merging byte constraints.
    function concretePacketBytes(bytes, first = 0) {
      if (first === bytes.length) return 0;
      let best = Infinity, repeated = true;
      for (let end = first + 1; end <= bytes.length; end++) {
        best = Math.min(best, end - first + 1 + concretePacketBytes(bytes, end));
        repeated = repeated && bytes[end - 1] === bytes[first];
        if (repeated && end - first >= 2) best = Math.min(best, 2 + concretePacketBytes(bytes, end));
      }
      return best;
    }
    let random = 0x6a09e667, packetOptimalityCases = 0;
    const next = () => { random ^= random << 13; random ^= random >>> 17; random ^= random << 5; return random >>> 0; };
    for (let test = 0; test < 256; test++) {
      const screen = new Uint8Array(32), freePositions = [];
      for (let byte = 0; byte < 4; byte++) {
        const value = next() & 255, freeBit = next() & 7;
        for (let bit = 0; bit < 8; bit++) {
          screen[byte * 8 + bit] = bit === freeBit ? 1 : (value >>> (7 - bit)) & 1 ? 15 : 0;
          if (bit === freeBit) freePositions.push(byte * 8 + bit);
        }
      }
      let best = Infinity;
      for (let assignment = 0; assignment < 16; assignment++) {
        const bytes = new Uint8Array(4);
        for (let i = 0; i < screen.length; i++) if (screen[i] === 15) bytes[i >>> 3] |= 0x80 >>> (i & 7);
        for (let bit = 0; bit < 4; bit++) if ((assignment >>> bit) & 1) bytes[freePositions[bit] >>> 3] |= 0x80 >>> (freePositions[bit] & 7);
        best = Math.min(best, concretePacketBytes(bytes));
      }
      assert.equal(codecs[1].encode(screen).length, best);
      verify(screen);
      packetOptimalityCases++;
    }
    const bridge = Uint8Array.from({ length: 24 }, (_, i) => i >= 8 && i < 16 ? 1 : 15);
    assert.equal(codecs[1].encode(bridge).length, 2);
    assert.equal(codecs[2].encode(bridge).length, 4);
    console.log(JSON.stringify({ pass: true, roundTrips: checked, runOptimalityCases, packetOptimalityCases,
      wildcardBridgeBytes: 2, edgeZeroBridgeBytes: 4 }));
  }
}
